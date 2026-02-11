# Advisor Appointment Voice Agent

A Streamlit-based voice assistant that books tentative advisor slots: collects topic and time preference, offers two slots, confirms, then creates a calendar hold, notes entry, and email draft via MCP. The caller receives a booking code and a secure link to complete details.

## Folder layout

- **`src/config/`** — Environment and settings (single source of truth).
- **`src/routes/`** — UI layer: Streamlit app and reusable components.
- **`src/services/`** — Business logic: conversation engine, intents, slots, validators.
- **`src/llm/`** — LLM integration (Groq).
- **`src/mcp/`** — Domain: Google Calendar, Sheets, Gmail integrations.
- **`src/voice/`** — Domain: STT/TTS.
- **`src/utils/`** — Shared helpers (timezone, secure link).
- **`data/`** — Mock calendar and topic taxonomy.

## Run locally

From repo root:

```bash
pip install -r requirements.txt
cp env.example .env
# Edit .env and set GROQ_API_KEY
streamlit run src/routes/app.py
```

## Deploy on Streamlit Community Cloud

1. **Push this repo to GitHub** (if not already).

2. **Go to [share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.

3. **New app** → choose repo `Voice-Agent-Appointment-Scheduler`, branch `main`, **Main file path:** `src/routes/app.py` → Deploy.

4. **Secrets** (in the app’s **Settings** → **Secrets**): add at least:
   - `GROQ_API_KEY` = your Groq API key  
   Optional (for Calendar/Sheets):
   - `GOOGLE_SERVICE_ACCOUNT_KEY_PATH` = path not used on Cloud; instead paste the **entire JSON key** as a secret named `GOOGLE_SERVICE_ACCOUNT_KEY` (value = contents of the `.json` file).
   - `GOOGLE_CALENDAR_ID`, `GOOGLE_SHEET_ID`, `GMAIL_USER`, `TIMEZONE`, `BASE_URL` as needed.

   Example (minimal):
   ```toml
   GROQ_API_KEY = "your-groq-api-key"
   ```

5. The app will build and run; the URL will be `https://<your-app>.streamlit.app`.

## Testing

From repo root:

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

Tests cover:

- **Intent classifier** — Text and voice-style inputs (book, reschedule, cancel, prepare, availability).
- **Slot manager** — Datetime parsing (`"Friday, 10am"`, `"10 Feb"`) and `offer_slots` with mock calendar.
- **Conversation engine** — Full user journeys: book new (text + voice-style), reschedule, cancel; disclaimer, topic/datetime validation, slot choice ("first"/"second"/"none"), confirmation yes/no.
- **Actions** — `on_booking_complete` / `on_reschedule_complete` with mocked MCP (no real Google calls).

Voice flow is the same as text once STT transcribes: the same `session.step(user_text)` is used for both, so conversation tests validate both input modes.

## Mock calendar

See `data/mock_calendar.json` for the structure. Slots are in IST. Adjust dates and times there for testing.

## Phase 2: Calendar, Sheets, Gmail (MCP)

When a new booking is confirmed, the app:

- **Calendar:** Creates a tentative hold with title `Advisor Q&A — {Topic} — {Code}`.
- **Sheets:** Appends a row to the "Advisor Pre-Bookings" sheet (timestamp, booking_code, topic, slot, status, source).
- **Gmail:** Creates a draft email to the advisor with booking details (approval-gated; not sent).

Set `GOOGLE_SERVICE_ACCOUNT_KEY_PATH` (or `GOOGLE_APPLICATION_CREDENTIALS`) to the path of your Google service account JSON. Enable Calendar API, Sheets API, and Gmail API for that project.

- **Sheets:** The app appends to the **first sheet** in the spreadsheet (range `A:F`). You must **share the Google Sheet** with the service account: open the JSON key, copy the `client_email` (e.g. `xxx@project.iam.gserviceaccount.com`), then in Google Sheets open your spreadsheet → Share → add that email as **Editor**. Otherwise you get 403 "The caller does not have permission".
- **Gmail:** Creating drafts with a service account requires **Google Workspace domain-wide delegation** and impersonating a user; otherwise the draft step is skipped with a friendly message. For personal Gmail or without delegation, Calendar and Sheets still work.
- If credentials or IDs are missing, MCP steps are skipped and the booking still completes.

## Reschedule / cancel

Reschedule and cancel flows are handled by the conversation engine: user provides booking code, then chooses new slots (reschedule) or confirms cancellation. MCP calendar and sheets are updated accordingly.

## Security & compliance

- No PII on the call (no phone, email, or account numbers).
- Informational only; investment advice is refused with educational links.
- Timezone (IST) and date/time are repeated on confirmation.
