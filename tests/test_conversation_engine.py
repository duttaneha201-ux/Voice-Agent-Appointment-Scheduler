"""Unit tests for conversation engine: full user journeys (text and voice-style input)."""

from __future__ import annotations

import pytest

from src.services.conversation_engine import (
    AgentTurn,
    ConversationContext,
    ConversationSession,
    ConversationState,
)


def _run_steps(session: ConversationSession, user_inputs: list[str]) -> list[AgentTurn]:
    """Run a sequence of user messages and return agent turns."""
    turns: list[AgentTurn] = []
    for i, user_text in enumerate(user_inputs):
        # First step is greeting: empty input
        if i == 0 and not user_text and session.state == ConversationState.GREETING:
            turn = session.step("")
        else:
            turn = session.step(user_text)
        turns.append(turn)
    return turns


class TestBookNewFlowTextInput:
    """Full book-new journey with explicit text inputs."""

    def test_full_book_new_journey(self) -> None:
        session = ConversationSession(timezone_label="IST")
        # 1. Greeting (empty triggers disclaimer)
        t1 = session.step("")
        assert session.state == ConversationState.DISCLAIMER
        assert "disclaimer" in t1.text.lower() or "continue" in t1.text.lower()

        # 2. Accept disclaimer
        t2 = session.step("Yes, let's continue")
        assert session.state == ConversationState.INTENT_CONFIRMATION
        assert "book" in t2.text.lower() or "reschedule" in t2.text.lower()

        # 3. Choose book new
        t3 = session.step("I want to book a new advisor slot")
        assert session.state == ConversationState.TOPIC_COLLECTION
        assert "topic" in t3.text.lower() or "discuss" in t3.text.lower()

        # 4. Topic
        t4 = session.step("SIP mandates")
        assert session.state == ConversationState.DATETIME_COLLECTION
        assert session.context.topic_label is not None
        assert "SIP" in session.context.topic_label or "Mandate" in session.context.topic_label

        # 5. Datetime
        t5 = session.step("Friday, 10am")
        assert session.state == ConversationState.SLOT_OFFER
        assert len(session.context.offered_slots) <= 2

        # 6. Choose first slot
        t6 = session.step("First")
        assert session.state == ConversationState.CONFIRMATION
        assert session.context.chosen_slot_index == 0
        assert "confirm" in t6.text.lower() or "hold" in t6.text.lower()

        # 7. Confirm
        t7 = session.step("Yes, please book it")
        assert session.state == ConversationState.BOOKING_COMPLETE
        assert session.context.booking_code is not None
        assert "NL-" in session.context.booking_code
        assert "tentative" in t7.text.lower() or "booked" in t7.text.lower()

    def test_book_new_voice_style_inputs(self) -> None:
        """Same flow with voice-transcription style inputs (yeah, book, sip, first, yes)."""
        session = ConversationSession(timezone_label="IST")
        session.step("")
        session.step("yeah")
        assert session.state == ConversationState.INTENT_CONFIRMATION
        session.step("book")
        assert session.state == ConversationState.TOPIC_COLLECTION
        session.step("sip")
        assert session.state == ConversationState.DATETIME_COLLECTION
        session.step("friday 10 am")
        assert session.state == ConversationState.SLOT_OFFER
        session.step("first")
        assert session.state == ConversationState.CONFIRMATION
        assert session.context.chosen_slot_index == 0
        session.step("yes")
        assert session.state == ConversationState.BOOKING_COMPLETE
        assert session.context.booking_code is not None

    def test_slot_choice_second_option(self) -> None:
        session = ConversationSession(timezone_label="IST")
        _run_steps(
            session,
            ["", "yes", "book new", "KYC onboarding", "Tuesday 2pm"],
        )
        assert session.state == ConversationState.SLOT_OFFER
        session.step("second")
        assert session.state == ConversationState.CONFIRMATION
        assert session.context.chosen_slot_index == 1
        session.step("confirm")
        assert session.state == ConversationState.BOOKING_COMPLETE

    def test_slot_none_goes_to_waitlist(self) -> None:
        session = ConversationSession(timezone_label="IST")
        _run_steps(
            session,
            ["", "yes", "book", "statements", "Friday 10am"],
        )
        assert session.state == ConversationState.SLOT_OFFER
        session.step("none")
        assert session.state == ConversationState.BOOKING_COMPLETE
        assert "waitlist" in session.step("").text.lower()

    def test_confirmation_no_returns_to_datetime(self) -> None:
        session = ConversationSession(timezone_label="IST")
        _run_steps(
            session,
            ["", "yes", "book", "withdrawals", "Saturday 11am"],
        )
        session.step("first")
        assert session.state == ConversationState.CONFIRMATION
        session.step("no, different time")
        assert session.state == ConversationState.DATETIME_COLLECTION


class TestRescheduleFlow:
    """Reschedule journey: intent -> code -> datetime -> slot -> confirm."""

    def test_reschedule_full_flow(self) -> None:
        session = ConversationSession(timezone_label="IST")
        session.step("")
        session.step("yes")
        session.step("reschedule")
        assert session.state == ConversationState.RESCHEDULE_ASK_CODE
        session.step("NL-A742")
        assert session.context.existing_booking_code == "NL-A742"
        assert session.state == ConversationState.DATETIME_COLLECTION
        session.step("Wednesday 3pm")
        assert session.state == ConversationState.SLOT_OFFER
        session.step("first")
        assert session.state == ConversationState.CONFIRMATION
        session.step("yes")
        assert session.state == ConversationState.BOOKING_COMPLETE
        # Reschedule keeps existing code, no new booking_code
        assert session.context.existing_booking_code == "NL-A742"
        assert "rescheduled" in session.step("").text.lower()


class TestCancelFlow:
    """Cancel journey: intent -> code -> confirm yes/no."""

    def test_cancel_full_flow(self) -> None:
        session = ConversationSession(timezone_label="IST")
        session.step("")
        session.step("ok")
        session.step("cancel")
        assert session.state == ConversationState.CANCEL_ASK_CODE
        session.step("NL-B123")
        assert session.context.existing_booking_code == "NL-B123"
        assert session.state == ConversationState.CANCEL_CONFIRM
        session.step("yes")
        assert session.state == ConversationState.BOOKING_COMPLETE
        assert "cancellation" in session.step("").text.lower()

    def test_cancel_no_returns_to_intent(self) -> None:
        session = ConversationSession(timezone_label="IST")
        session.step("")
        session.step("continue")
        session.step("cancel")
        session.step("NL-X999")
        assert session.state == ConversationState.CANCEL_CONFIRM
        session.step("no")
        assert session.state == ConversationState.INTENT_CONFIRMATION


class TestDisclaimerAndIntentClarification:
    """Disclaimer rejection and unclear intent."""

    def test_disclaimer_no_stays_on_disclaimer(self) -> None:
        session = ConversationSession(timezone_label="IST")
        session.step("")
        t = session.step("no")
        assert session.state == ConversationState.DISCLAIMER
        session.step("yes")
        assert session.state == ConversationState.INTENT_CONFIRMATION

    def test_intent_unclear_repeats_options(self) -> None:
        session = ConversationSession(timezone_label="IST")
        session.step("")
        session.step("yes")
        t = session.step("I'm not sure")
        assert session.state == ConversationState.INTENT_CONFIRMATION
        assert "book" in t.text.lower() and "reschedule" in t.text.lower()


class TestTopicAndDatetimeValidation:
    """Topic not recognized, datetime with no slots."""

    def test_topic_unclear_repeats_list(self) -> None:
        session = ConversationSession(timezone_label="IST")
        session.step("")
        session.step("yes")
        session.step("book new")
        t = session.step("something random")
        assert session.state == ConversationState.TOPIC_COLLECTION
        assert "KYC" in t.text or "SIP" in t.text

    def test_no_slots_offers_waitlist(self) -> None:
        session = ConversationSession(timezone_label="IST")
        session.step("")
        session.step("yes")
        session.step("book")
        session.step("account changes")
        # Monday has no slots in mock (Tue–Sat only)
        t = session.step("Monday 9am")
        assert session.state == ConversationState.SLOT_OFFER
        assert len(session.context.offered_slots) == 0
        assert "waitlist" in t.text.lower()


class TestBookingCompleteState:
    """After booking complete, step() returns summary."""

    def test_booking_complete_repeats_summary(self) -> None:
        session = ConversationSession(timezone_label="IST")
        _run_steps(session, ["", "yes", "book", "nominee", "Friday 10am", "first", "yes"])
        assert session.state == ConversationState.BOOKING_COMPLETE
        t = session.step("anything")
        assert "NL-" in t.text or "booked" in t.text.lower()
