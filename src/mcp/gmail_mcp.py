"""Gmail MCP adapter: create draft emails to the advisor for booking approval."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional


def _get_credentials(credentials_path: str, subject_email: Optional[str] = None):
    if not credentials_path or not Path(credentials_path).exists():
        return None
    from google.oauth2 import service_account
    SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]
    creds = service_account.Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    if subject_email:
        creds = creds.with_subject(subject_email)
    return creds


def create_draft_advisor_email(
    credentials_path: str,
    advisor_email: str,
    booking_code: str,
    topic: str,
    slot_label: str,
    from_email: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Create a Gmail draft to the advisor with booking details (approval-gated; not sent).
    If using a service account, set from_email to the delegated user (e.g. advisor or a shared inbox).
    Returns (success, message).
    """
    if not advisor_email or not credentials_path:
        return True, "Gmail draft skipped (no advisor email or credentials)"
    creds = _get_credentials(credentials_path, subject_email=from_email)
    if not creds:
        return True, "Gmail draft skipped (credentials file not found)"
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        body_text = (
            f"Advisor pre-booking (tentative hold).\n\n"
            f"Booking code: {booking_code}\n"
            f"Topic: {topic}\n"
            f"Slot: {slot_label}\n\n"
            "Please review and confirm. Do not share PII in reply."
        )
        msg = MIMEText(body_text)
        msg["to"] = advisor_email
        msg["subject"] = f"Advisor Pre-Booking — {booking_code} — {topic}"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service = build("gmail", "v1", credentials=creds)
        service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return True, "Advisor email draft created"
    except HttpError as e:
        if e.resp.status == 400 or (getattr(e, "error_details", None) and "failedPrecondition" in str(e.error_details)):
            return True, (
                "Gmail draft skipped (service account cannot create drafts; "
                "use domain-wide delegation or OAuth for a user account)."
            )
        return False, f"Gmail draft error: {e}"
    except Exception as e:
        return False, f"Gmail draft error: {e}"


__all__ = ["create_draft_advisor_email"]
