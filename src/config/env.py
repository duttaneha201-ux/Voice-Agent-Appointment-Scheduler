"""Load and validate environment variables. Single source for env handling."""
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of src/)
_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_root / ".env")


def _get(key: str, default: str = "") -> str:
    """Get config: Streamlit secrets (deployed) then env vars (local)."""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and st.secrets and key in st.secrets:
            return str(st.secrets.get(key, default))
    except Exception:
        pass
    return os.getenv(key, default)


def load_env() -> None:
    """Ensure .env is loaded. Call at app startup."""
    load_dotenv(_root / ".env")


def get_settings() -> "Settings":
    """Return validated settings. Uses Streamlit secrets when deployed, else env / .env."""
    from src.config.settings import Settings

    # Google credentials: path, or JSON content (Streamlit Cloud: use GOOGLE_SERVICE_ACCOUNT_KEY secret)
    raw_path = (
        _get("GOOGLE_SERVICE_ACCOUNT_KEY")
        or _get("GOOGLE_SERVICE_ACCOUNT_KEY_PATH")
        or _get("GOOGLE_APPLICATION_CREDENTIALS", "")
    )
    google_credentials_path = ""
    if raw_path:
        if isinstance(raw_path, dict):
            import json
            try:
                fd, path = tempfile.mkstemp(suffix=".json")
                with os.fdopen(fd, "w") as f:
                    json.dump(raw_path, f)
                google_credentials_path = path
            except Exception:
                pass
        else:
            raw_path = str(raw_path).strip()
            if raw_path.startswith("{") and "client_email" in raw_path:
                try:
                    import json
                    json.loads(raw_path)
                    fd, path = tempfile.mkstemp(suffix=".json")
                    with os.fdopen(fd, "w") as f:
                        f.write(raw_path)
                    google_credentials_path = path
                except Exception:
                    pass
            else:
                p = Path(raw_path)
                if not p.is_absolute():
                    p = _root / p
                if p.exists():
                    google_credentials_path = str(p.resolve())

    advisor_email = _get("GMAIL_USER") or _get("ADVISOR_EMAIL", "")
    return Settings(
        groq_api_key=_get("GROQ_API_KEY", ""),
        google_credentials_path=google_credentials_path or "",
        google_calendar_id=_get("GOOGLE_CALENDAR_ID", "primary"),
        google_sheet_id=_get("GOOGLE_SHEET_ID", ""),
        advisor_email=advisor_email,
        base_url=_get("BASE_URL", "https://example.com"),
        timezone=_get("TIMEZONE", "Asia/Kolkata"),
    )
