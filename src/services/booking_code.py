"""Booking code generator for advisor appointments."""

from __future__ import annotations

import random
import string

from src.config.settings import BOOKING_CODE_PREFIX


def generate_booking_code() -> str:
    """Generate booking code like 'NL-A742'.

    - Prefix from `BOOKING_CODE_PREFIX` (e.g. 'NL')
    - One random uppercase letter
    - Three-digit number
    """

    letter = random.choice(string.ascii_uppercase)
    number = random.randint(100, 999)
    return f"{BOOKING_CODE_PREFIX}-{letter}{number}"


__all__ = ["generate_booking_code"]

