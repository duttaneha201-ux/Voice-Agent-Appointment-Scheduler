"""Speech-to-text: transcribe audio bytes to text for voice input."""

from __future__ import annotations

import io
from typing import Optional


def transcribe_audio(audio_bytes: bytes) -> Optional[str]:
    """
    Transcribe WAV audio bytes to text using SpeechRecognition (Google Web API, free tier).
    Returns None on error or empty result.
    """
    if not audio_bytes:
        return None
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio)
        return (text or "").strip() or None
    except sr.UnknownValueError:
        return None
    except Exception:
        return None


__all__ = ["transcribe_audio"]
