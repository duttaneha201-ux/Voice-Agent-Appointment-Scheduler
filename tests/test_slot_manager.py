"""Unit tests for slot manager (datetime parsing and offer_slots)."""

from __future__ import annotations

import pytest

from src.services.slot_manager import (
    Slot,
    load_slots,
    offer_slots,
)
from src.services.slot_manager import _parse_preferred_datetime as parse_preferred_datetime


class TestParsePreferredDatetime:
    """Parsing user preference text (e.g. 'Friday, 10am')."""

    def test_empty_returns_none(self) -> None:
        wd, mins, date = parse_preferred_datetime("")
        assert wd is None and mins is None and date is None
        wd, mins, date = parse_preferred_datetime("   ")
        assert wd is None and mins is None and date is None

    def test_weekday_only(self) -> None:
        # Monday=0, Tuesday=1, ..., Friday=4
        wd, mins, date = parse_preferred_datetime("Friday")
        assert wd == 4
        assert mins is None
        assert date is None
        wd, _, _ = parse_preferred_datetime("tuesday")
        assert wd == 1

    def test_weekday_and_time(self) -> None:
        wd, mins, date = parse_preferred_datetime("Friday, 10am")
        assert wd == 4
        assert mins is not None
        assert mins == 10 * 60  # 10:00
        assert date is None
        wd, mins, _ = parse_preferred_datetime("wednesday 2 pm")
        assert wd == 2
        assert mins == 14 * 60

    def test_explicit_date(self) -> None:
        # "10 Feb, 10am" avoids "4" being parsed as 4am
        wd, mins, date = parse_preferred_datetime("10 Feb, 10am")
        assert date == "2026-02-10"
        assert wd is not None
        assert mins == 10 * 60
        wd, _, date = parse_preferred_datetime("6 February")
        assert date == "2026-02-06"

    def test_time_formats(self) -> None:
        _, mins, _ = parse_preferred_datetime("10:00")
        assert mins == 10 * 60
        _, mins, _ = parse_preferred_datetime("2:30 pm")
        assert mins == 14 * 60 + 30


class TestOfferSlots:
    """Slot offering from mock calendar (Tue–Sat in data)."""

    def test_no_preference_returns_up_to_two(self) -> None:
        slots = offer_slots()
        assert len(slots) <= 2
        assert all(isinstance(s, Slot) for s in slots)

    def test_friday_preference_returns_friday_slots(self) -> None:
        # Mock calendar: Feb 10 (Tue), 11 (Wed), 12 (Thu), 13 (Fri), 14 (Sat)
        slots = offer_slots(preferred_datetime_text="Friday")
        assert len(slots) <= 2
        for s in slots:
            assert s.weekday() == 4  # Friday

    def test_tuesday_preference_returns_tuesday_slots(self) -> None:
        slots = offer_slots(preferred_datetime_text="Tuesday")
        assert len(slots) <= 2
        for s in slots:
            assert s.weekday() == 1

    def test_friday_10am_ranks_by_time(self) -> None:
        slots = offer_slots(preferred_datetime_text="Friday, 10am")
        assert len(slots) <= 2
        for s in slots:
            assert s.weekday() == 4
        # Should prefer slots near 10:00
        if len(slots) >= 2:
            t0 = slots[0].time
            t1 = slots[1].time
            assert t0 <= t1 or abs(int(t0.split(":")[0]) - 10) <= abs(int(t1.split(":")[0]) - 10)

    def test_explicit_date_in_calendar(self) -> None:
        slots = offer_slots(preferred_datetime_text="10 Feb, 10am")
        assert len(slots) <= 2
        for s in slots:
            assert s.date == "2026-02-10"

    def test_explicit_date_not_in_calendar_returns_empty(self) -> None:
        # Mock has Feb 10–14; use a date not in mock so we get [] when using mock data
        from unittest.mock import patch
        from src.services.slot_manager import load_slots
        mock_slots = load_slots()  # only dates 10–14
        with patch("src.services.slot_manager._load_slots_from_calendar_or_mock", return_value=mock_slots):
            slots = offer_slots(preferred_datetime_text="20 Feb")
        assert slots == []


class TestSlot:
    """Slot dataclass and label()."""

    def test_label_format(self) -> None:
        s = Slot(date="2026-02-10", time="10:00", timezone="Asia/Kolkata")
        label = s.label()
        assert "Feb" in label or "February" in label
        assert "10" in label
        assert "10" in label or "AM" in label
        assert "Asia" in label or "IST" in label or "Kolkata" in label

    def test_weekday(self) -> None:
        s = Slot(date="2026-02-10", time="10:00", timezone="IST")
        assert s.weekday() == 1  # Tuesday
