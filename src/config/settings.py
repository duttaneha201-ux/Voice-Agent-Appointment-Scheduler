"""Pydantic settings and app constants."""
from pydantic import BaseModel, Field

# Topic taxonomy (5 advisory categories)
TOPICS = {
    "KYC/Onboarding": ["kyc", "onboarding", "verification", "documents", "identity"],
    "SIP/Mandates": ["sip", "mandate", "systematic", "recurring", "auto-debit"],
    "Statements/Tax Docs": ["statement", "tax", "form 16", "capital gains", "annual statement"],
    "Withdrawals & Timelines": ["withdraw", "redeem", "timeline", "when will i get", "payout"],
    "Account Changes/Nominee": ["change", "nominee", "bank details", "update", "modify"],
}

# Intents
INTENTS = {
    "book_new": ["book", "schedule", "appointment", "slot", "meeting"],
    "reschedule": ["change", "reschedule", "move", "different time", "postpone"],
    "cancel": ["cancel", "delete", "remove", "abort"],
    "prepare": ["what to bring", "prepare", "documents needed", "what do i need"],
    "availability": ["when available", "free slots", "open times", "availability"],
}

DISCLAIMER = (
    "This is for informational purposes only and does not constitute investment advice. "
    "Please consult a qualified advisor for decisions."
)

BOOKING_DURATION_MINUTES = 30
BOOKING_CODE_PREFIX = "NL"


class Settings(BaseModel):
    groq_api_key: str = Field(default="", description="Groq API key for LLM")
    google_credentials_path: str = Field(default="", description="Path to Google service account JSON")
    google_calendar_id: str = Field(default="primary", description="Google Calendar ID")
    google_sheet_id: str = Field(default="", description="Google Sheet ID for pre-bookings")
    advisor_email: str = Field(default="", description="Advisor email for drafts")
    base_url: str = Field(default="https://example.com", description="Base URL for secure links")
    timezone: str = Field(default="Asia/Kolkata", description="Display timezone (IST)")

    def groq_configured(self) -> bool:
        return bool(self.groq_api_key.strip())

    def google_configured(self) -> bool:
        return bool(self.google_credentials_path.strip())
