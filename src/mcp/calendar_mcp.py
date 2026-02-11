"""Google Calendar MCP adapter: create tentative holds and query available slots from your calendar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.config.settings import BOOKING_DURATION_MINUTES

# Scopes: events (create holds) + readonly (freebusy query)
_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


@dataclass
class SlotInfo:
    date: str  # YYYY-MM-DD
    time: str  # HH:MM or H:MM 24h
    timezone: str


def _get_credentials(credentials_path: str):
    if not credentials_path or not Path(credentials_path).exists():
        return None
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_file(
        credentials_path, scopes=_CALENDAR_SCOPES
    )


def _normalize_time(hh_mm: str) -> str:
    """Ensure time is HH:MM (e.g. '9:30' -> '09:30', '12:00' unchanged)."""
    parts = hh_mm.strip().split(":")
    if len(parts) < 2:
        return hh_mm
    try:
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        return f"{h:02d}:{m:02d}"
    except ValueError:
        return hh_mm


def _slot_to_start_end_rfc3339(slot: SlotInfo, duration_minutes: int = BOOKING_DURATION_MINUTES):
    """Return (start_str, end_str) in RFC 3339 with explicit offset (e.g. +05:30) so Calendar API shows correct local time."""
    time_norm = _normalize_time(slot.time)
    naive = datetime.strptime(f"{slot.date} {time_norm}", "%Y-%m-%d %H:%M")
    tz = ZoneInfo(slot.timezone)
    start_dt = naive.replace(tzinfo=tz)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    return start_dt.isoformat(), end_dt.isoformat()


def get_available_slots(
    calendar_id: str,
    credentials_path: str,
    timezone: str = "Asia/Kolkata",
    days_ahead: int = 14,
    slot_duration_minutes: int = BOOKING_DURATION_MINUTES,
    start_hour: int = 9,
    end_hour: int = 17,
    weekdays: Tuple[int, ...] = (1, 2, 3, 4, 5),  # Tue=1 .. Sat=5 (Python weekday)
) -> List[SlotInfo]:
    """
    Query your Google Calendar free/busy and return slots that are free.
    Slots are on the given weekdays (default Tue–Sat), between start_hour and end_hour, in 30‑min steps.
    Returns empty list on error (e.g. no credentials or API failure).
    """
    if not credentials_path or not calendar_id or not Path(credentials_path).exists():
        return []
    creds = _get_credentials(credentials_path)
    if not creds:
        return []
    try:
        from googleapiclient.discovery import build
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        # Query from now; end after days_ahead
        time_min = now
        time_max = now + timedelta(days=days_ahead)
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "items": [{"id": calendar_id}],
        }
        service = build("calendar", "v3", credentials=creds)
        result = service.freebusy().query(body=body).execute()
        busy_list = []
        for cal_id, cal_data in result.get("calendars", {}).items():
            busy_list.extend(cal_data.get("busy", []))
        # Parse busy periods as (start, end) datetime
        def parse_iso(s: str) -> datetime:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        busy_ranges = []
        for b in busy_list:
            start_s = b.get("start") or ""
            end_s = b.get("end") or ""
            if start_s and end_s:
                start_dt = parse_iso(start_s).astimezone(tz)
                end_dt = parse_iso(end_s).astimezone(tz)
                busy_ranges.append((start_dt, end_dt))
        # Candidate slots: every slot_duration_minutes from start_hour to end_hour on weekdays
        slots_out: List[SlotInfo] = []
        start_date = time_min.date()
        end_date = time_max.date()
        day = start_date
        while day <= end_date:
            if day.weekday() in weekdays:
                for hour in range(start_hour, end_hour):
                    for minute in (0, 30):
                        slot_start = datetime(day.year, day.month, day.day, hour, minute, 0, tzinfo=tz)
                        slot_end = slot_start + timedelta(minutes=slot_duration_minutes)
                        if slot_start < now:
                            continue
                        # Skip if overlaps any busy period
                        overlaps = any(
                            slot_start < be and bs < slot_end
                            for bs, be in busy_ranges
                        )
                        if not overlaps:
                            slots_out.append(SlotInfo(
                                date=day.strftime("%Y-%m-%d"),
                                time=slot_start.strftime("%H:%M"),
                                timezone=timezone,
                            ))
            day += timedelta(days=1)
        return slots_out
    except Exception:
        return []


def _normalize_booking_code_for_lookup(code: str) -> str:
    """Normalize so 'NLP 760', 'NL-P760', 'NL P760' all match (e.g. voice transcription)."""
    if not code:
        return ""
    return "".join(c for c in code.strip().upper() if c.isalnum())


def find_event_by_booking_code(
    calendar_id: str,
    credentials_path: str,
    code: str,
) -> Optional[str]:
    """
    Find a calendar event whose summary contains the booking code (e.g. " — NL-V779").
    Events are titled "Advisor Q&A — {Topic} — {Code}".
    Code is normalized so "NLP 760" / "NL-P760" match (voice transcription).
    Returns event_id if found, None otherwise. Searches now-90d to now+365d.
    """
    if not credentials_path or not calendar_id or not code or not Path(credentials_path).exists():
        return None
    creds = _get_credentials(credentials_path)
    if not creds:
        return None
    code_norm = _normalize_booking_code_for_lookup(code)
    if not code_norm:
        return None
    try:
        from googleapiclient.discovery import build
        tz = ZoneInfo("UTC")
        now = datetime.now(tz)
        time_min = (now - timedelta(days=90)).isoformat()
        time_max = (now + timedelta(days=365)).isoformat()
        service = build("calendar", "v3", credentials=creds)
        request = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        while request is not None:
            response = request.execute()
            for event in response.get("items", []):
                summary = (event.get("summary") or "")
                # Direct match (e.g. "NL-P760" in summary)
                if code.strip() in summary:
                    return event.get("id")
                # Normalized match: event title ends with " — {Code}", normalize and compare
                if " — " in summary:
                    event_code = summary.rsplit(" — ", 1)[-1].strip()
                    if _normalize_booking_code_for_lookup(event_code) == code_norm:
                        return event.get("id")
            request = service.events().list_next(request, response)
        return None
    except Exception:
        return None


def update_event_to_slot(
    calendar_id: str,
    credentials_path: str,
    event_id: str,
    slot: SlotInfo,
) -> tuple[bool, str]:
    """
    Update an existing calendar event's start/end to the given slot (for reschedule).
    Returns (success, message).
    """
    if not credentials_path or not calendar_id or not event_id:
        return False, "Calendar update skipped (missing calendar ID, credentials, or event ID)"
    creds = _get_credentials(credentials_path)
    if not creds:
        return False, "Calendar update skipped (credentials file not found)"
    try:
        from googleapiclient.discovery import build
        start_str, end_str = _slot_to_start_end_rfc3339(slot)
        body = {
            "start": {"dateTime": start_str, "timeZone": slot.timezone},
            "end": {"dateTime": end_str, "timeZone": slot.timezone},
        }
        service = build("calendar", "v3", credentials=creds)
        service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=body,
        ).execute()
        return True, "Calendar event rescheduled"
    except Exception as e:
        return False, f"Calendar update error: {e}"


def delete_event_by_id(
    calendar_id: str,
    credentials_path: str,
    event_id: str,
) -> tuple[bool, str]:
    """
    Delete a calendar event (for cancel). Returns (success, message).
    """
    if not credentials_path or not calendar_id or not event_id:
        return False, "Calendar delete skipped (missing calendar ID, credentials, or event ID)"
    creds = _get_credentials(credentials_path)
    if not creds:
        return False, "Calendar delete skipped (credentials file not found)"
    try:
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds)
        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id,
        ).execute()
        return True, "Calendar event cancelled (deleted)"
    except Exception as e:
        return False, f"Calendar delete error: {e}"


def create_tentative_hold(
    topic: str,
    booking_code: str,
    slot: SlotInfo,
    calendar_id: str,
    credentials_path: str,
) -> tuple[bool, str]:
    """
    Create a tentative calendar event: "Advisor Q&A — {Topic} — {Code}".
    Sends RFC 3339 with explicit offset (e.g. 10:00+05:30) so the event shows at the correct local time.
    If the event appears at 4:30 AM instead of 10 AM, set your Google Calendar view timezone to Asia/Kolkata.
    Returns (success, message).
    """
    if not credentials_path or not calendar_id:
        return True, "Calendar skipped (no credentials or calendar ID)"
    creds = _get_credentials(credentials_path)
    if not creds:
        return True, "Calendar skipped (credentials file not found)"
    try:
        from googleapiclient.discovery import build
        start_str, end_str = _slot_to_start_end_rfc3339(slot)
        title = f"Advisor Q&A — {topic} — {booking_code}"
        body = {
            "summary": title,
            "description": f"Tentative advisor slot. Topic: {topic}. Code: {booking_code}.",
            "start": {"dateTime": start_str, "timeZone": slot.timezone},
            "end": {"dateTime": end_str, "timeZone": slot.timezone},
            "status": "tentative",
        }
        service = build("calendar", "v3", credentials=creds)
        service.events().insert(calendarId=calendar_id, body=body).execute()
        return True, "Calendar hold created"
    except Exception as e:
        return False, f"Calendar error: {e}"


__all__ = [
    "SlotInfo",
    "create_tentative_hold",
    "get_available_slots",
    "find_event_by_booking_code",
    "update_event_to_slot",
    "delete_event_by_id",
]
