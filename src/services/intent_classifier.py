"""Intent classification using simple keyword matching.

Phase 1: lightweight, deterministic classifier built on the `INTENTS`
mapping defined in `src.config.settings`. This keeps dependencies minimal
and is easy to unit-test. Later we can optionally add a Groq-backed
classifier behind the same interface.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from src.config.settings import INTENTS


IntentName = str


@dataclass
class IntentResult:
    """Result of intent classification."""

    intent: Optional[IntentName]
    confidence: float
    raw_text: str


class KeywordIntentClassifier:
    """Very simple keyword-based intent classifier.

    Strategy:
    - Lowercase the user text.
    - For each intent, count how many of its keywords are present.
    - Choose the intent with the highest count.
    - Map counts to a rough confidence score.
    """

    def __init__(self, intents: Dict[IntentName, List[str]] | None = None) -> None:
        self._intents: Dict[IntentName, List[str]] = intents or INTENTS

    def classify(self, text: str) -> IntentResult:
        lowered = text.lower().strip()
        if not lowered:
            return IntentResult(intent=None, confidence=0.0, raw_text=text)

        best_intent: Optional[IntentName] = None
        best_score = 0

        for intent, keywords in self._intents.items():
            score = 0
            for kw in keywords:
                if kw.lower() in lowered:
                    score += 1
            if score > best_score:
                best_score = score
                best_intent = intent

        if best_score == 0 or best_intent is None:
            return IntentResult(intent=None, confidence=0.0, raw_text=text)

        # Rough confidence heuristic: 0.4, 0.7, 0.9+ depending on matches.
        if best_score == 1:
            confidence = 0.4
        elif best_score == 2:
            confidence = 0.7
        else:
            confidence = 0.9

        return IntentResult(intent=best_intent, confidence=confidence, raw_text=text)


def classify_intent(text: str) -> IntentResult:
    """Convenience function for one-off intent classification."""
    classifier = KeywordIntentClassifier()
    return classifier.classify(text)


__all__ = ["IntentResult", "KeywordIntentClassifier", "classify_intent"]

