"""Conversation state machine for the Advisor Appointment Voice Agent.

States:
- GREETING
- DISCLAIMER
- INTENT_CONFIRMATION  (book new / reschedule / cancel)
- TOPIC_COLLECTION
- DATETIME_COLLECTION
- SLOT_OFFER
- CONFIRMATION
- BOOKING_COMPLETE
- RESCHEDULE_ASK_CODE / CANCEL_ASK_CODE / CANCEL_CONFIRM (reschedule/cancel flows)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional

from src.config.settings import DISCLAIMER, TOPICS
from src.services.booking_code import generate_booking_code
from src.services.intent_classifier import IntentResult, KeywordIntentClassifier
from src.services.slot_manager import Slot, offer_slots
from src.services.slot_manager import _parse_preferred_datetime as parse_preferred_datetime


class ConversationState(Enum):
    GREETING = auto()
    DISCLAIMER = auto()
    INTENT_CONFIRMATION = auto()
    TOPIC_COLLECTION = auto()
    DATETIME_COLLECTION = auto()
    SLOT_OFFER = auto()
    CONFIRMATION = auto()
    BOOKING_COMPLETE = auto()
    RESCHEDULE_ASK_CODE = auto()
    CANCEL_ASK_CODE = auto()
    CANCEL_CONFIRM = auto()


@dataclass
class ConversationContext:
    intent: Optional[str] = None
    topic_label: Optional[str] = None
    preferred_datetime_text: Optional[str] = None
    offered_slots: List[Slot] = field(default_factory=list)
    chosen_slot_index: Optional[int] = None
    booking_code: Optional[str] = None
    existing_booking_code: Optional[str] = None  # for reschedule/cancel


@dataclass
class AgentTurn:
    text: str
    state: ConversationState
    context: ConversationContext
    intent_result: Optional[IntentResult] = None


class ConversationSession:
    """Encapsulates stateful dialog behavior."""

    def __init__(self, timezone_label: str = "IST") -> None:
        self.state = ConversationState.GREETING
        self.context = ConversationContext()
        self._intent_classifier = KeywordIntentClassifier()
        self._timezone_label = timezone_label

    # Public API ---------------------------------------------------------
    def step(self, user_text: str) -> AgentTurn:
        """Advance the conversation based on user input."""
        intent_result = self._intent_classifier.classify(user_text)
        # Only update context.intent from classifier when user is choosing intent.
        # Never overwrite during reschedule/cancel flow (existing_booking_code set) so we
        # always call on_reschedule_complete and update the existing event, not create a new one.
        if intent_result.intent and not self.context.existing_booking_code and self.state in (
            ConversationState.GREETING,
            ConversationState.DISCLAIMER,
            ConversationState.INTENT_CONFIRMATION,
        ):
            self.context.intent = intent_result.intent

        if self.state == ConversationState.GREETING:
            return self._handle_greeting(intent_result)
        if self.state == ConversationState.DISCLAIMER:
            return self._handle_disclaimer(user_text, intent_result)
        if self.state == ConversationState.INTENT_CONFIRMATION:
            return self._handle_intent_confirmation(user_text, intent_result)
        if self.state == ConversationState.TOPIC_COLLECTION:
            return self._handle_topic(user_text, intent_result)
        if self.state == ConversationState.DATETIME_COLLECTION:
            return self._handle_datetime(user_text, intent_result)
        if self.state == ConversationState.SLOT_OFFER:
            return self._handle_slot_choice(user_text, intent_result)
        if self.state == ConversationState.CONFIRMATION:
            return self._handle_confirmation(user_text, intent_result)
        if self.state == ConversationState.BOOKING_COMPLETE:
            # Once complete, keep reminding user of booking details.
            text = self._summarize_booking()
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        if self.state == ConversationState.RESCHEDULE_ASK_CODE:
            return self._handle_reschedule_ask_code(user_text, intent_result)
        if self.state == ConversationState.CANCEL_ASK_CODE:
            return self._handle_cancel_ask_code(user_text, intent_result)
        if self.state == ConversationState.CANCEL_CONFIRM:
            return self._handle_cancel_confirm(user_text, intent_result)

        # Fallback
        return AgentTurn(
            text="Sorry, something went wrong. Let's start again. What would you like help with today?",
            state=ConversationState.GREETING,
            context=self.context,
            intent_result=intent_result,
        )

    # State handlers -----------------------------------------------------
    def _handle_greeting(self, intent_result: IntentResult) -> AgentTurn:
        self.state = ConversationState.DISCLAIMER
        text = (
            "Hello, you're speaking with the Advisor Appointment Assistant. "
            "I can help you book, reschedule, or cancel an advisor slot, "
            "and share what to prepare.\n\n"
            f"Before we begin, I must share a short disclaimer:\n{DISCLAIMER}\n\n"
            "Shall we continue?"
        )
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_disclaimer(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        lowered = user_text.lower()
        if any(x in lowered for x in ["yes", "yeah", "ok", "sure", "continue", "go ahead"]):
            self.state = ConversationState.INTENT_CONFIRMATION
            text = (
                "Great. What would you like to do today?\n\n"
                "• **Book a new advisor slot** — I'll collect your topic and preferred time, then offer two slots.\n"
                "• **Reschedule** — Change an existing booking (you'll need your booking code).\n"
                "• **Cancel** — Cancel an existing booking (you'll need your booking code).\n\n"
                "Please say: book new, reschedule, or cancel."
            )
        else:
            text = "No problem. When you're ready, just say you'd like to continue with booking or questions."
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_intent_confirmation(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        lowered = user_text.lower().strip()
        # Check cancel first so "cancel" / "abort" / "delete" / "remove" are never treated as reschedule
        if any(x in lowered for x in ["cancel", "abort", "delete", "remove", "delete booking", "remove booking"]):
            intent = "cancel"
        elif "reschedule" in lowered or any(x in lowered for x in ["change booking", "move my slot", "postpone", "different time"]):
            intent = "reschedule"
        elif intent_result.intent == "book_new" or any(x in lowered for x in ["book", "new slot", "appointment", "schedule a", "book a"]):
            intent = "book_new"
        else:
            intent = intent_result.intent
            if not intent and any(x in lowered for x in ["schedule", "slot", "meeting"]):
                intent = "book_new"

        if intent == "book_new":
            self.context.intent = "book_new"
            self.state = ConversationState.TOPIC_COLLECTION
            text = (
                "I'll help you book a new advisor slot. "
                "What would you like to discuss with the advisor?\n"
                "For example: KYC/Onboarding, SIP/Mandates, Statements/Tax Docs, "
                "Withdrawals & Timelines, or Account Changes/Nominee."
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        if intent == "reschedule":
            self.context.intent = "reschedule"
            self.state = ConversationState.RESCHEDULE_ASK_CODE
            text = (
                "I'll help you reschedule. Please have your booking code ready—"
                "it looks like NL-A742. What is your booking code?"
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        if intent == "cancel":
            self.context.intent = "cancel"
            self.state = ConversationState.CANCEL_ASK_CODE
            text = (
                "I'll help you cancel your booking. Please tell me your booking code "
                "(for example, NL-A742)."
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        text = (
            "I didn't catch that. What would you like to do?\n\n"
            "• Say **book new** to book a new advisor slot.\n"
            "• Say **reschedule** to change an existing booking.\n"
            "• Say **cancel** to cancel an existing booking."
        )
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_reschedule_ask_code(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        code = user_text.strip() or None
        if not code:
            text = "Please tell me your booking code (for example, NL-A742)."
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        self.context.existing_booking_code = code
        self.state = ConversationState.DATETIME_COLLECTION
        text = (
            f"Thanks. To which date and time would you like to reschedule? "
            "You can book a slot, if available, **Tuesday through Saturday, between 9am and 5pm** "
            f"({self._timezone_label})."
        )
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_cancel_ask_code(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        code = user_text.strip() or None
        if not code:
            text = "Please tell me your booking code (for example, NL-A742)."
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        self.context.existing_booking_code = code
        self.state = ConversationState.CANCEL_CONFIRM
        text = (
            f"I'll cancel the booking for code **{code}**. "
            "Confirm cancellation? Say yes or no."
        )
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_cancel_confirm(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        lowered = user_text.lower()
        if any(x in lowered for x in ["yes", "yeah", "confirm", "go ahead", "cancel", "sure", "ok"]):
            code = self.context.existing_booking_code or "your booking"
            self.state = ConversationState.BOOKING_COMPLETE
            text = f"Cancellation recorded for **{code}**. You will receive a confirmation. Anything else?"
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        if any(x in lowered for x in ["no", "don't", "do not"]):
            self.state = ConversationState.INTENT_CONFIRMATION
            text = "Cancellation not done. What would you like to do: book new, reschedule, or cancel?"
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        text = "Please say yes to confirm cancellation, or no to keep the booking."
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_topic(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        topic_label = self._detect_topic(user_text)
        if not topic_label:
            text = (
                "I didn't quite catch the topic. Please choose one of these:\n"
                "- KYC/Onboarding\n- SIP/Mandates\n- Statements/Tax Docs\n"
                "- Withdrawals & Timelines\n- Account Changes/Nominee"
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        self.context.topic_label = topic_label
        self.state = ConversationState.DATETIME_COLLECTION
        text = (
            f"Got it, we'll discuss **{topic_label}**.\n\n"
            "You can book a slot, if available, **Tuesday through Saturday, between 9am and 5pm** "
            f"({self._timezone_label}). "
            "On which day and roughly what time would you prefer to speak with the advisor?"
        )
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_datetime(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        self.context.preferred_datetime_text = user_text.strip() or None

        # Get two slots matching preference (e.g. Friday, 10am).
        slots = offer_slots(preferred_datetime_text=self.context.preferred_datetime_text)
        self.context.offered_slots = slots
        self.state = ConversationState.SLOT_OFFER

        if not slots:
            text = (
                "I couldn't find any open advisor slots matching your preference. "
                "For now, I can place you on a waitlist and an advisor will reach out "
                "when a suitable time opens. Would you like to be added to the waitlist?"
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        # Build slot options text.
        lines = []
        for idx, slot in enumerate(slots, start=1):
            lines.append(f"{idx}. {slot.label()}")
        options_text = "\n".join(lines)
        text = (
            "Thanks. Based on your preference, here are two available slots:\n\n"
            f"{options_text}\n\n"
            "Please say 'first' or 'option 1', or 'second' or 'option 2'. "
            "If neither works, say 'none'."
        )
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_slot_choice(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        lowered = user_text.lower().strip()
        # If user re-states a date/time (e.g. "Friday, 10am"), treat as "different slot" and re-offer
        pref_weekday, pref_minutes, _ = parse_preferred_datetime(user_text)
        if (pref_weekday is not None or pref_minutes is not None) and len(lowered) > 2:
            self.context.preferred_datetime_text = user_text.strip()
            slots = offer_slots(preferred_datetime_text=self.context.preferred_datetime_text)
            self.context.offered_slots = slots
            if slots:
                lines = [f"{i}. {s.label()}" for i, s in enumerate(slots, start=1)]
                text = (
                    "No problem. Based on your new preference, here are two available slots:\n\n"
                    + "\n".join(lines) + "\n\n"
                    "Please say 'first' or 'option 1', or 'second' or 'option 2'. "
                    "If neither works, say 'none'."
                )
            else:
                text = (
                    "I couldn't find any slots for that day. "
                    "Tell me another day and time that works for you, "
                    f"in {self._timezone_label}."
                )
                self.state = ConversationState.DATETIME_COLLECTION
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        idx: Optional[int]
        # Check "none"/"neither" before "one" (so "none" is not matched as "one")
        if "none" in lowered or "neither" in lowered:
            self.state = ConversationState.BOOKING_COMPLETE
            text = (
                "I understand that none of the suggested slots work for you. "
                "I'll place a note to add you to the waitlist so an advisor can "
                "offer alternatives. You won't be booked into any slot right now."
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)
        if any(x in lowered for x in ["first", "1", "one", "option 1", "slot 1"]):
            idx = 0
        elif any(x in lowered for x in ["second", "2", "two", "option 2", "slot 2"]):
            idx = 1
        else:
            text = (
                "Please choose one of the options by saying 'first' or 'second'. "
                "If neither works, say 'none'. Or tell me a different day and time (e.g. Friday, 10am)."
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        if not self.context.offered_slots or idx >= len(self.context.offered_slots):
            text = "Those options seem to have expired. Let me fetch fresh slots."
            self.state = ConversationState.DATETIME_COLLECTION
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        self.context.chosen_slot_index = idx
        chosen = self.context.offered_slots[idx]
        self.state = ConversationState.CONFIRMATION
        text = (
            "Just to confirm, I have you for:\n"
            f"- {chosen.label()}\n\n"
            f"All times are in {self._timezone_label}. "
            "Shall I place a tentative hold for this advisor slot?"
        )
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    def _handle_confirmation(self, user_text: str, intent_result: IntentResult) -> AgentTurn:
        lowered = user_text.lower()
        if any(x in lowered for x in ["yes", "yeah", "confirm", "go ahead", "book", "sounds good", "ok", "sure"]):
            if self.context.intent == "reschedule":
                # Reschedule: keep existing_booking_code; don't generate new code
                self.state = ConversationState.BOOKING_COMPLETE
            else:
                self.context.booking_code = generate_booking_code()
                self.state = ConversationState.BOOKING_COMPLETE
            text = self._summarize_booking()
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        if any(x in lowered for x in ["no", "don't", "do not", "change", "different"]):
            # Let user pick a different time.
            self.state = ConversationState.DATETIME_COLLECTION
            text = (
                "No problem, we won't book that slot. "
                "Tell me another day and approximate time that works for you, "
                f"in {self._timezone_label}."
            )
            return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

        text = "Please say 'yes' to confirm this slot, or 'no' to choose another time."
        return AgentTurn(text=text, state=self.state, context=self.context, intent_result=intent_result)

    # Helpers -------------------------------------------------------------
    def _detect_topic(self, user_text: str) -> Optional[str]:
        lowered = user_text.lower()
        for label, keywords in TOPICS.items():
            for kw in keywords:
                if kw.lower() in lowered:
                    return label
        return None

    def _summarize_booking(self) -> str:
        # Reschedule complete: chosen slot + existing code
        if (
            self.context.intent == "reschedule"
            and self.context.existing_booking_code
            and self.context.chosen_slot_index is not None
            and self.context.offered_slots
            and self.context.chosen_slot_index < len(self.context.offered_slots)
        ):
            slot = self.context.offered_slots[self.context.chosen_slot_index]
            return (
                f"Your booking **{self.context.existing_booking_code}** has been rescheduled to "
                f"{slot.label()}.\n\nAll times are in {self._timezone_label}. Anything else?"
            )
        if self.context.booking_code and self.context.chosen_slot_index is not None:
            slot = self.context.offered_slots[self.context.chosen_slot_index]
            secure_link = f"/complete-booking/{self.context.booking_code}"
            return (
                "Your tentative advisor slot is booked.\n\n"
                f"- Topic: {self.context.topic_label or 'Advisor Q&A'}\n"
                f"- Slot: {slot.label()}\n"
                f"- Booking code: {self.context.booking_code}\n\n"
                "Please note: this is a tentative hold. To securely share your "
                "contact details and any documents, use the secure link we provide:\n"
                f"{secure_link}\n\n"
                f"All times are in {self._timezone_label}. "
                "You can mention your booking code when you contact support."
            )
        if self.context.intent == "reschedule" and self.context.existing_booking_code:
            return (
                f"Your reschedule request for booking code **{self.context.existing_booking_code}** "
                "has been noted. An advisor will reach out with new slot options. Anything else?"
            )
        if self.context.intent == "cancel" and self.context.existing_booking_code:
            return (
                f"Cancellation for **{self.context.existing_booking_code}** has been recorded. "
                "Anything else?"
            )
        return (
            "You are not currently booked into a specific slot. "
            "If you'd like, we can look at more times or place you on a waitlist."
        )


__all__ = ["ConversationState", "ConversationContext", "AgentTurn", "ConversationSession"]

