"""Orchestration: run MCP (calendar, sheets) when a new booking is confirmed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List

from src.mcp.calendar_mcp import (
    SlotInfo,
    create_tentative_hold,
    delete_event_by_id,
    find_event_by_booking_code,
    update_event_to_slot,
)
from src.mcp.sheets_mcp import (
    append_prebooking_row,
    update_prebooking_row_for_reschedule,
    update_prebooking_row_status,
)

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.services.conversation_engine import ConversationContext


@dataclass
class MCPResult:
    calendar: tuple[bool, str] = (True, "skipped")
    sheets: tuple[bool, str] = (True, "skipped")
    errors: List[str] = field(default_factory=list)

    def all_ok(self) -> bool:
        return self.calendar[0] and self.sheets[0]


def on_booking_complete(context: "ConversationContext", settings: "Settings") -> MCPResult:
    """
    Create calendar hold, append sheet row, and create advisor email draft.
    Only call this for a new booking (context.booking_code and context.chosen_slot_index set).
    """
    result = MCPResult()
    if not context.booking_code or context.chosen_slot_index is None or not context.offered_slots:
        return result
    if context.chosen_slot_index >= len(context.offered_slots):
        return result

    slot = context.offered_slots[context.chosen_slot_index]
    topic = context.topic_label or "Advisor Q&A"
    slot_info = SlotInfo(date=slot.date, time=slot.time, timezone=slot.timezone)
    creds = getattr(settings, "google_credentials_path", "") or ""

    result.calendar = create_tentative_hold(
        topic=topic,
        booking_code=context.booking_code,
        slot=slot_info,
        calendar_id=settings.google_calendar_id,
        credentials_path=creds,
    )
    if not result.calendar[0]:
        result.errors.append(result.calendar[1])

    result.sheets = append_prebooking_row(
        sheet_id=settings.google_sheet_id,
        credentials_path=creds,
        booking_code=context.booking_code,
        topic=topic,
        slot_label=slot.label(),
        status="tentative",
        source="voice_agent",
    )
    if not result.sheets[0]:
        result.errors.append(result.sheets[1])

    return result


def on_reschedule_complete(context: "ConversationContext", settings: "Settings") -> MCPResult:
    """
    Update the existing calendar event to the new slot and append a reschedule row to the sheet.
    Only call when intent is reschedule, existing_booking_code and chosen_slot are set.
    """
    result = MCPResult()
    if context.intent != "reschedule" or not context.existing_booking_code:
        return result
    if context.chosen_slot_index is None or not context.offered_slots:
        return result
    if context.chosen_slot_index >= len(context.offered_slots):
        return result

    slot = context.offered_slots[context.chosen_slot_index]
    slot_info = SlotInfo(date=slot.date, time=slot.time, timezone=slot.timezone)
    creds = getattr(settings, "google_credentials_path", "") or ""
    cal_id = settings.google_calendar_id
    topic = context.topic_label or "Advisor Q&A"

    event_id = find_event_by_booking_code(
        calendar_id=cal_id,
        credentials_path=creds,
        code=context.existing_booking_code,
    )
    if not event_id:
        result.calendar = (False, "Booking code not found on calendar.")
        result.errors.append(result.calendar[1])
        return result

    result.calendar = update_event_to_slot(
        calendar_id=cal_id,
        credentials_path=creds,
        event_id=event_id,
        slot=slot_info,
    )
    if not result.calendar[0]:
        result.errors.append(result.calendar[1])

    # Update the existing sheet row to new slot and status "rescheduled" (no duplicate row)
    result.sheets = update_prebooking_row_for_reschedule(
        sheet_id=settings.google_sheet_id,
        credentials_path=creds,
        booking_code=context.existing_booking_code,
        new_slot_label=slot.label(),
        new_status="rescheduled",
    )
    if not result.sheets[0]:
        result.errors.append(result.sheets[1])
        # Fallback: append a reschedule row so we still have an audit trail
        append_ok, append_msg = append_prebooking_row(
            sheet_id=settings.google_sheet_id,
            credentials_path=creds,
            booking_code=context.existing_booking_code,
            topic=topic,
            slot_label=slot.label(),
            status="rescheduled",
            source="voice_agent",
        )
        if append_ok:
            result.sheets = (True, "Reschedule appended (original row not found)")

    return result


def on_cancel_complete(context: "ConversationContext", settings: "Settings") -> MCPResult:
    """
    Remove the calendar event and update the sheet row to "cancelled".
    Only call when intent is cancel and existing_booking_code is set.
    Booking code is matched with normalization (e.g. "NLP 760" matches "NL-P760").
    """
    result = MCPResult()
    if context.intent != "cancel" or not context.existing_booking_code:
        return result

    creds = getattr(settings, "google_credentials_path", "") or ""
    cal_id = settings.google_calendar_id
    code = context.existing_booking_code.strip()

    event_id = find_event_by_booking_code(
        calendar_id=cal_id,
        credentials_path=creds,
        code=code,
    )
    if event_id:
        result.calendar = delete_event_by_id(
            calendar_id=cal_id,
            credentials_path=creds,
            event_id=event_id,
        )
        if not result.calendar[0]:
            result.errors.append(result.calendar[1])
    else:
        result.calendar = (False, "Booking code not found on calendar.")
        result.errors.append(result.calendar[1])

    result.sheets = update_prebooking_row_status(
        sheet_id=settings.google_sheet_id,
        credentials_path=creds,
        booking_code=code,
        new_status="cancelled",
    )
    if not result.sheets[0]:
        result.errors.append(result.sheets[1])

    return result


__all__ = ["MCPResult", "on_booking_complete", "on_reschedule_complete", "on_cancel_complete"]
