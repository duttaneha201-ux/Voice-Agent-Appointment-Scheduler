"""Slot offering logic: uses your Google Calendar free/busy when configured, else mock_calendar.json.

Parses user preference (e.g. "Friday, 10am") and returns slots matching that day,
ranked by proximity to the preferred time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "mock_calendar.json"

# Python weekday: Monday=0, ..., Sunday=6
WEEKDAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]
WEEKDAY_ABBREV = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]
MONTH_ABBREV = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _parse_preferred_datetime(text: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Parse "Friday, 10am", "4 Feb, 10am", "Friday, 4 Feb, 10am" style text.
    Returns (preferred_weekday 0-6, preferred_minutes_since_midnight, preferred_date YYYY-MM-DD or None).
    When both a weekday and a date (e.g. "4 Feb") are present, the explicit date is preferred for filtering.
    """
    if not text or not text.strip():
        return None, None, None
    lowered = text.lower().strip()
    weekday: Optional[int] = None
    preferred_date: Optional[str] = None

    # 1) Date-like first: "4 Feb", "Feb 4", "6 February" — explicit date overrides weekday
    for month_idx, (full, abbr) in enumerate(zip(MONTH_NAMES, MONTH_ABBREV), start=1):
        # "4 february" or "4 feb"
        m = re.search(rf"(\d{{1,2}})\s*(?:{re.escape(full)}|{re.escape(abbr)})\b", lowered)
        if m:
            day = int(m.group(1))
            if 1 <= day <= 31:
                try:
                    dt = datetime(2026, month_idx, day)
                    preferred_date = dt.strftime("%Y-%m-%d")
                    weekday = dt.weekday()
                except ValueError:
                    pass
            if preferred_date is not None:
                break
        # "february 4" or "feb 4"
        if preferred_date is None:
            m = re.search(rf"(?:{re.escape(full)}|{re.escape(abbr)})\s*(\d{{1,2}})\b", lowered)
            if m:
                day = int(m.group(1))
                if 1 <= day <= 31:
                    try:
                        dt = datetime(2026, month_idx, day)
                        preferred_date = dt.strftime("%Y-%m-%d")
                        weekday = dt.weekday()
                    except ValueError:
                        pass
                if preferred_date is not None:
                    break

    # 2) If no date found, use weekday names / abbreviations
    if preferred_date is None:
        for i, name in enumerate(WEEKDAY_NAMES):
            if name in lowered:
                weekday = i
                break
        if weekday is None:
            for i, abbr in enumerate(WEEKDAY_ABBREV):
                if abbr in lowered:
                    weekday = i
                    break

    hour: Optional[float] = None
    # 10am, 2pm, 10:00, 14:00, 10 am, 2 pm
    time_match = re.search(
        r"(?:^|\s)(\d{1,2})\s*:?\s*(\d{2})?\s*(am|pm)?(?:\s|$|,)", lowered
    )
    if time_match:
        h = int(time_match.group(1))
        m = int(time_match.group(2)) if time_match.group(2) else 0
        ampm = (time_match.group(3) or "").strip()
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        elif not ampm and h <= 23:
            pass
        h = min(23, max(0, h))
        hour = h + m / 60.0
    if hour is None and re.search(r"\b(\d{1,2})\s*(am|pm)\b", lowered):
        m = re.search(r"(\d{1,2})\s*(am|pm)", lowered)
        if m:
            h = int(m.group(1))
            if m.group(2) == "pm" and h < 12:
                h += 12
            elif m.group(2) == "am" and h == 12:
                h = 0
            hour = min(23, max(0, h))
    preferred_minutes = int(hour * 60) if hour is not None else None
    return weekday, preferred_minutes, preferred_date


def _slot_minutes(slot: "Slot") -> int:
    """Slot time as minutes since midnight for ranking."""
    parts = slot.time.split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return h * 60 + m


@dataclass
class Slot:
    date: str  # ISO date YYYY-MM-DD
    time: str  # HH:MM (24h)
    timezone: str

    def label(self) -> str:
        """Human-friendly label like 'Tuesday, Feb 10 at 2:00 PM IST'."""
        dt = datetime.fromisoformat(f"{self.date}T{self.time}")
        pretty_date = dt.strftime("%A, %b %d")
        pretty_time = dt.strftime("%I:%M %p").lstrip("0")
        return f"{pretty_date} at {pretty_time} {self.timezone}"

    def weekday(self) -> int:
        """Python weekday: Monday=0, ..., Sunday=6."""
        return datetime.strptime(self.date, "%Y-%m-%d").weekday()


def load_slots() -> List[Slot]:
    """Load slots from mock_calendar.json (fallback when real calendar not used or fails)."""
    with DATA_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    slots: List[Slot] = []
    for entry in data.get("available_slots", []):
        date = entry["date"]
        tz = entry.get("timezone", "Asia/Kolkata")
        for t in entry.get("times", []):
            slots.append(Slot(date=date, time=t, timezone=tz))
    return slots


def _load_slots_from_calendar_or_mock() -> List[Slot]:
    """Use real Google Calendar free/busy when credentials and calendar ID are set; else mock."""
    try:
        from src.config import get_settings
        from src.mcp.calendar_mcp import SlotInfo, get_available_slots
        settings = get_settings()
        if settings.google_configured() and getattr(settings, "google_calendar_id", None):
            creds = getattr(settings, "google_credentials_path", "") or ""
            cal_id = settings.google_calendar_id
            tz = getattr(settings, "timezone", "Asia/Kolkata")
            infos: List[SlotInfo] = get_available_slots(
                calendar_id=cal_id,
                credentials_path=creds,
                timezone=tz,
                days_ahead=14,
                start_hour=9,
                end_hour=17,
                weekdays=(1, 2, 3, 4, 5),  # Tue–Sat
            )
            if infos:
                return [Slot(date=s.date, time=s.time, timezone=s.timezone) for s in infos]
    except Exception:
        pass
    return load_slots()


def offer_slots(
    preferred_date: str | None = None,
    preferred_time: str | None = None,
    preferred_datetime_text: str | None = None,
) -> List[Slot]:
    """
    Return up to two slots matching the user's preference.
    When Google credentials and calendar ID are set, slots come from your calendar free/busy; else mock.
    Parses preferred_datetime_text (e.g. "Friday, 10am") or uses preferred_date/preferred_time.
    Filters by weekday and ranks by proximity to preferred time.
    """
    all_slots = _load_slots_from_calendar_or_mock()
    text = preferred_datetime_text or ""
    if preferred_date:
        text = f"{text} {preferred_date}".strip()
    if preferred_time:
        text = f"{text} {preferred_time}".strip()
    preferred_weekday, preferred_minutes, preferred_date_parsed = _parse_preferred_datetime(text)

    # Prefer explicit date (e.g. "4 Feb") over weekday — filter by that date when present
    if preferred_date_parsed is not None:
        on_date = [s for s in all_slots if s.date == preferred_date_parsed]
        if on_date:
            if preferred_minutes is not None:
                on_date.sort(key=lambda s: abs(_slot_minutes(s) - preferred_minutes))
            else:
                on_date.sort(key=lambda s: s.time)
            return on_date[:2]
        # No slots on that date; return empty so agent can say "no slots on that day"
        return []

    if preferred_weekday is not None:
        on_day = [s for s in all_slots if s.weekday() == preferred_weekday]
        if on_day:
            if preferred_minutes is not None:
                on_day.sort(key=lambda s: abs(_slot_minutes(s) - preferred_minutes))
            else:
                on_day.sort(key=lambda s: (s.date, s.time))
            return on_day[:2]
        # Requested weekday (e.g. Monday) has no slots in the window — don't offer other days
        return []
    if preferred_minutes is not None:
        all_slots.sort(key=lambda s: abs(_slot_minutes(s) - preferred_minutes))
    return all_slots[:2]

