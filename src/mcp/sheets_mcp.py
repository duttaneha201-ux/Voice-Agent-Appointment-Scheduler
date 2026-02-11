"""Google Sheets MCP adapter: append rows to Advisor Pre-Bookings log and update for reschedule."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


def _get_credentials(credentials_path: str):
    if not credentials_path or not Path(credentials_path).exists():
        return None
    from google.oauth2 import service_account
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    return service_account.Credentials.from_service_account_file(credentials_path, scopes=SCOPES)


# Columns: A=timestamp, B=booking_code, C=topic, D=slot_label, E=status, F=source
_BOOKING_CODE_COL = 1  # 0-based
_SLOT_LABEL_COL = 3
_STATUS_COL = 4


def _normalize_booking_code(code: str) -> str:
    """Normalize for matching (e.g. 'NLP 760' / 'NL-P760' -> 'NLP760')."""
    if not code:
        return ""
    return "".join(c for c in (code or "").strip().upper() if c.isalnum())


def update_prebooking_row_for_reschedule(
    sheet_id: str,
    credentials_path: str,
    booking_code: str,
    new_slot_label: str,
    new_status: str = "rescheduled",
) -> tuple[bool, str]:
    """
    Find the row with this booking_code (column B) and update slot_label (D) and status (E).
    So the same row shows the new slot and "rescheduled" instead of leaving the old row and appending a new one.
    Returns (success, message). If no row is found, returns (False, "Booking code not found in sheet").
    """
    if not sheet_id or not credentials_path or not booking_code:
        return True, "Sheets skipped (no sheet ID, credentials, or booking code)"
    creds = _get_credentials(credentials_path)
    if not creds:
        return True, "Sheets skipped (credentials file not found)"
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        service = build("sheets", "v4", credentials=creds)
        # Read first sheet, columns A–F
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="A:F",
        ).execute()
        rows = result.get("values") or []
        # Find row index (0-based) where column B matches booking_code
        row_index: Optional[int] = None
        code_norm = _normalize_booking_code(booking_code)
        for i, row in enumerate(rows):
            if len(row) > _BOOKING_CODE_COL and _normalize_booking_code(row[_BOOKING_CODE_COL]) == code_norm:
                row_index = i
                break
        if row_index is None:
            return False, "Booking code not found in sheet (no row to update)"
        # Update row: D = new_slot_label, E = new_status (1-based row = row_index + 1)
        one_based = row_index + 1
        range_str = f"D{one_based}:E{one_based}"
        body = {"values": [[new_slot_label, new_status]]}
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_str,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
        return True, "Existing sheet row updated to new slot (rescheduled)"
    except HttpError as e:
        if e.resp.status == 403:
            return False, (
                "Sheets 403: The caller does not have permission. "
                "Share this Google Sheet with your service account email (client_email in the JSON key) as Editor."
            )
        return False, f"Sheets error: {e}"
    except Exception as e:
        return False, f"Sheets error: {e}"


def update_prebooking_row_status(
    sheet_id: str,
    credentials_path: str,
    booking_code: str,
    new_status: str,
) -> tuple[bool, str]:
    """
    Find the row with this booking_code (column B, normalized match) and update status (column E).
    Used for cancel: set status to "cancelled". Returns (success, message).
    """
    if not sheet_id or not credentials_path or not booking_code:
        return True, "Sheets skipped (no sheet ID, credentials, or booking code)"
    creds = _get_credentials(credentials_path)
    if not creds:
        return True, "Sheets skipped (credentials file not found)"
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        service = build("sheets", "v4", credentials=creds)
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range="A:F",
        ).execute()
        rows = result.get("values") or []
        row_index: Optional[int] = None
        code_norm = _normalize_booking_code(booking_code)
        for i, row in enumerate(rows):
            if len(row) > _BOOKING_CODE_COL and _normalize_booking_code(row[_BOOKING_CODE_COL]) == code_norm:
                row_index = i
                break
        if row_index is None:
            return False, "Booking code not found in sheet"
        one_based = row_index + 1
        range_str = f"E{one_based}"
        body = {"values": [[new_status]]}
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=range_str,
            valueInputOption="USER_ENTERED",
            body=body,
        ).execute()
        return True, "Sheet row status updated to " + new_status
    except HttpError as e:
        if e.resp.status == 403:
            return False, (
                "Sheets 403: The caller does not have permission. "
                "Share this Google Sheet with your service account email (client_email in the JSON key) as Editor."
            )
        return False, f"Sheets error: {e}"
    except Exception as e:
        return False, f"Sheets error: {e}"


def append_prebooking_row(
    sheet_id: str,
    credentials_path: str,
    booking_code: str,
    topic: str,
    slot_label: str,
    status: str = "tentative",
    source: str = "voice_agent",
) -> tuple[bool, str]:
    """
    Append a row to the Advisor Pre-Bookings sheet.
    Columns: timestamp, booking_code, topic, slot, status, source.
    Returns (success, message).
    """
    if not sheet_id or not credentials_path:
        return True, "Sheets skipped (no sheet ID or credentials)"
    creds = _get_credentials(credentials_path)
    if not creds:
        return True, "Sheets skipped (credentials file not found)"
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        values: List[List[str]] = [[ts, booking_code, topic, slot_label, status, source]]
        service = build("sheets", "v4", credentials=creds)
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="A:F",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
        return True, "Pre-booking logged to sheet"
    except HttpError as e:
        if e.resp.status == 403:
            return False, (
                "Sheets 403: The caller does not have permission. "
                "Share this Google Sheet with your service account email (client_email in the JSON key) as Editor."
            )
        return False, f"Sheets error: {e}"
    except Exception as e:
        return False, f"Sheets error: {e}"


__all__ = ["append_prebooking_row", "update_prebooking_row_for_reschedule", "update_prebooking_row_status"]
