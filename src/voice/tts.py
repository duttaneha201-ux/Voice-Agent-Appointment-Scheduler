"""Text-to-speech: generate audio from agent text for playback in the browser."""

from __future__ import annotations

import io
from typing import Optional


def text_to_speech_mp3(text: str, lang: str = "en") -> Optional[bytes]:
    """
    Generate MP3 bytes from text using gTTS.
    Returns None on error (e.g. empty text or API failure).
    """
    if not text or not text.strip():
        return None
    try:
        from gtts import gTTS
        buf = io.BytesIO()
        tts = gTTS(text=text.strip(), lang=lang)
        tts.write_to_fp(buf)
        return buf.getvalue()
    except Exception:
        return None


__all__ = ["text_to_speech_mp3"]
