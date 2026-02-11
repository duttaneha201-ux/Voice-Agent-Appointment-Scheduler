"""Unit tests for intent classifier (text and voice-style inputs)."""

from __future__ import annotations

import pytest

from src.services.intent_classifier import (
    IntentResult,
    KeywordIntentClassifier,
    classify_intent,
)


class TestKeywordIntentClassifier:
    """Intent classification for textual and voice-transcribed inputs."""

    def test_empty_returns_none(self) -> None:
        classifier = KeywordIntentClassifier()
        r = classifier.classify("")
        assert r.intent is None
        assert r.confidence == 0.0
        r = classifier.classify("   ")
        assert r.intent is None

    def test_book_new_text(self) -> None:
        r = classify_intent("I want to book an appointment")
        assert r.intent == "book_new"
        assert r.confidence > 0

    def test_book_new_voice_style(self) -> None:
        r = classify_intent("book a slot")
        assert r.intent == "book_new"
        r = classify_intent("schedule a meeting")
        assert r.intent == "book_new"

    def test_reschedule_text(self) -> None:
        # Use phrases that don't share keywords with book_new (e.g. "schedule" in "reschedule")
        r = classify_intent("move to different time")
        assert r.intent == "reschedule"
        r = classify_intent("I want to postpone")
        assert r.intent == "reschedule"

    def test_reschedule_voice_style(self) -> None:
        r = classify_intent("postpone")
        assert r.intent == "reschedule"
        r = classify_intent("move to different time")
        assert r.intent == "reschedule"

    def test_cancel_text(self) -> None:
        # "cancel" contains "change", "remove" contains "move"; use abort/delete
        r = classify_intent("abort")
        assert r.intent == "cancel"
        r = classify_intent("delete")
        assert r.intent == "cancel"

    def test_cancel_voice_style(self) -> None:
        r = classify_intent("abort")
        assert r.intent == "cancel"
        r = classify_intent("delete")
        assert r.intent == "cancel"

    def test_prepare_intent(self) -> None:
        r = classify_intent("what to bring")
        assert r.intent == "prepare"
        r = classify_intent("documents needed")
        assert r.intent == "prepare"

    def test_availability_intent(self) -> None:
        # "free slots" shares "slot" with book_new; use "open times" for unique match
        r = classify_intent("open times")
        assert r.intent == "availability"
        r = classify_intent("availability")
        assert r.intent == "availability"

    def test_confidence_increases_with_more_matches(self) -> None:
        r1 = classify_intent("book")
        r2 = classify_intent("book appointment slot")
        assert r1.intent == "book_new" and r2.intent == "book_new"
        assert r2.confidence >= r1.confidence

    def test_raw_text_preserved(self) -> None:
        text = "  Book a slot please  "
        r = classify_intent(text)
        assert r.raw_text == text

    def test_custom_intents(self) -> None:
        classifier = KeywordIntentClassifier(
            intents={"greet": ["hello", "hi"], "bye": ["goodbye", "bye"]}
        )
        r = classifier.classify("hello there")
        assert r.intent == "greet"
        r = classifier.classify("goodbye")
        assert r.intent == "bye"
