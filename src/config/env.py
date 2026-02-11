"""Load and validate environment variables. Single source for env handling."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of src/)
_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_root / ".env")


def load_env() -> None:
    """Ensure .env is loaded. Call at app startup."""
    load_dotenv(_root / ".env")


def get_settings() -> "Settings":
    """Return validated settings. Supports your env vars and legacy names."""
    from src.config.settings import Settings
    # Credentials: GOOGLE_SERVICE_ACCOUNT_KEY_PATH or GOOGLE_APPLICATION_CREDENTIALS
    raw_path = (
        os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY_PATH")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    )
    # Resolve relative paths against project root so ./service-account-key.json works
    google_credentials_path = ""
    if raw_path:
        p = Path(raw_path.strip())
        if not p.is_absolute():
            p = _root / p
        google_credentials_path = str(p.resolve())
    # Advisor / draft recipient: GMAIL_USER or ADVISOR_EMAIL
    advisor_email = os.getenv("GMAIL_USER") or os.getenv("ADVISOR_EMAIL", "")
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        google_credentials_path=google_credentials_path or "",
        google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary"),
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", ""),
        advisor_email=advisor_email,
        base_url=os.getenv("BASE_URL", "https://example.com"),
        timezone=os.getenv("TIMEZONE", "Asia/Kolkata"),
    )
