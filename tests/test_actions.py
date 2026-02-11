"""Unit tests for actions (on_booking_complete, on_reschedule_complete) with mocked MCP."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.services.actions import MCPResult, on_booking_complete, on_reschedule_complete
from src.services.conversation_engine import ConversationContext
from src.services.slot_manager import Slot


def _mock_settings():
    from src.config.settings import Settings
    return Settings(
        groq_api_key="",
        google_credentials_path="",
        google_calendar_id="primary",
        google_sheet_id="",
        advisor_email="",
        base_url="https://example.com",
        timezone="IST",
    )


class TestOnBookingComplete:
    """on_booking_complete only runs MCP when context has booking_code and chosen_slot."""

    def test_incomplete_context_skips_mcp(self) -> None:
        settings = _mock_settings()
        ctx = ConversationContext(
            intent="book_new",
            topic_label="SIP/Mandates",
            preferred_datetime_text="Friday 10am",
            offered_slots=[Slot("2026-02-13", "10:00", "IST")],
            chosen_slot_index=None,
            booking_code=None,
        )
        result = on_booking_complete(ctx, settings)
        assert result.calendar[1] == "skipped" or not result.calendar[0]
        assert result.sheets[1] == "skipped" or not result.sheets[0]
        assert result.errors == []

    def test_no_booking_code_skips(self) -> None:
        settings = _mock_settings()
        ctx = ConversationContext(
            intent="book_new",
            topic_label="KYC",
            offered_slots=[Slot("2026-02-13", "10:00", "IST")],
            chosen_slot_index=0,
            booking_code=None,
        )
        result = on_booking_complete(ctx, settings)
        assert result.errors == []

    @patch("src.services.actions.create_tentative_hold")
    @patch("src.services.actions.append_prebooking_row")
    def test_full_context_calls_mcp(
        self, mock_sheets, mock_calendar
    ) -> None:
        mock_calendar.return_value = (True, "ok")
        mock_sheets.return_value = (True, "ok")
        settings = _mock_settings()
        slot = Slot("2026-02-13", "10:00", "IST")
        ctx = ConversationContext(
            intent="book_new",
            topic_label="SIP/Mandates",
            offered_slots=[slot],
            chosen_slot_index=0,
            booking_code="NL-A742",
        )
        result = on_booking_complete(ctx, settings)
        assert mock_calendar.called
        assert mock_sheets.called
        assert result.calendar[0] is True
        assert result.sheets[0] is True
        assert result.errors == []

    @patch("src.services.actions.create_tentative_hold")
    @patch("src.services.actions.append_prebooking_row")
    def test_calendar_failure_records_error(
        self, mock_sheets, mock_calendar
    ) -> None:
        mock_calendar.return_value = (False, "Calendar API error")
        mock_sheets.return_value = (True, "ok")
        settings = _mock_settings()
        slot = Slot("2026-02-13", "10:00", "IST")
        ctx = ConversationContext(
            intent="book_new",
            topic_label="KYC",
            offered_slots=[slot],
            chosen_slot_index=0,
            booking_code="NL-B123",
        )
        result = on_booking_complete(ctx, settings)
        assert not result.calendar[0]
        assert "Calendar" in result.calendar[1] or "error" in result.calendar[1].lower()
        assert len(result.errors) >= 1


class TestOnRescheduleComplete:
    """on_reschedule_complete only runs when intent is reschedule and code/slot set."""

    def test_wrong_intent_skips(self) -> None:
        settings = _mock_settings()
        slot = Slot("2026-02-13", "10:00", "IST")
        ctx = ConversationContext(
            intent="book_new",
            existing_booking_code="NL-A742",
            offered_slots=[slot],
            chosen_slot_index=0,
        )
        result = on_reschedule_complete(ctx, settings)
        assert result.errors == []
        assert result.calendar[1] == "skipped" or not result.calendar[0]

    def test_no_existing_code_skips(self) -> None:
        settings = _mock_settings()
        slot = Slot("2026-02-13", "10:00", "IST")
        ctx = ConversationContext(
            intent="reschedule",
            existing_booking_code=None,
            offered_slots=[slot],
            chosen_slot_index=0,
        )
        result = on_reschedule_complete(ctx, settings)
        assert result.errors == []

    @patch("src.services.actions.find_event_by_booking_code")
    @patch("src.services.actions.update_event_to_slot")
    @patch("src.services.actions.update_prebooking_row_for_reschedule")
    def test_reschedule_calls_mcp(
        self, mock_sheets_update, mock_update, mock_find
    ) -> None:
        mock_find.return_value = "event-id-123"
        mock_update.return_value = (True, "ok")
        mock_sheets_update.return_value = (True, "ok")
        settings = _mock_settings()
        slot = Slot("2026-02-13", "10:00", "IST")
        ctx = ConversationContext(
            intent="reschedule",
            existing_booking_code="NL-A742",
            offered_slots=[slot],
            chosen_slot_index=0,
        )
        result = on_reschedule_complete(ctx, settings)
        assert mock_find.called
        assert mock_update.called
        assert mock_sheets_update.called
        assert result.calendar[0] is True
        assert result.sheets[0] is True

    @patch("src.services.actions.find_event_by_booking_code")
    def test_booking_code_not_found_records_error(self, mock_find) -> None:
        mock_find.return_value = None
        settings = _mock_settings()
        slot = Slot("2026-02-13", "10:00", "IST")
        ctx = ConversationContext(
            intent="reschedule",
            existing_booking_code="NL-UNKNOWN",
            offered_slots=[slot],
            chosen_slot_index=0,
        )
        result = on_reschedule_complete(ctx, settings)
        assert not result.calendar[0]
        assert "not found" in result.calendar[1].lower() or "Booking" in result.calendar[1]
        assert len(result.errors) >= 1


class TestMCPResult:
    def test_all_ok(self) -> None:
        r = MCPResult(calendar=(True, "ok"), sheets=(True, "ok"))
        assert r.all_ok() is True
        r.calendar = (False, "err")
        assert r.all_ok() is False
