# Gmail & Calendar Assistant

A Python CLI tool that acts as an intelligent executive assistant for Gmail and Google Calendar, powered by Google Gemini AI.

## Features

### 1. Smart Triage (Inbox Briefing)
- Fetches unread emails and scores them using **configurable YAML rules + AI fallback**
- **Email categorization** — automatically sorts emails into 13 categories (Jobs, Bills, Academic, Shopping, Newsletters, etc.) using fast keyword matching; uncategorized emails refined by AI
- Groups emails into HIGH / MEDIUM / LOW priority in an executive digest
- Flags emails that mention you by name
- Extracts deadlines and surfaces attachments
- **Bulk actions**:
  - Trash specific emails or all LOW priority emails
  - **View by category** — group and review emails by category
  - **Label emails by category** — apply Gmail labels; keyword-first plan shown to user, AI refinement loop if user gives feedback
  - Add selected deadlines to calendar (pick which ones)
  - Auto-reply to emails

### 2. Search & Read Emails
- Search using standard Gmail operators (`from:someone`, `subject:project`, `has:attachment`)
- View parsed, clean text of any email

### 3. Compose Email (AI-Assisted)
Two modes:
- **Send new email**:
  - **Contact search** — type a name to find recipients from your email history, or enter an address directly
  - Enter subject, pick tone, draft body
  - AI refines both subject and body using a strict copywriter prompt (no hallucinated dates/names)
  - **Feedback loop** — provide feedback and AI revises; repeat until satisfied
  - Sends only after explicit Y confirmation
- **Reply to existing email**:
  - Search for a contact by name or email
  - Select from recent emails with that contact (shows sender, subject, date)
  - View the original email for context
  - Same AI refinement and feedback loop as new email
  - Sends as a threaded reply with proper `In-Reply-To` / `References` headers

### 4. Auto-Reply
- Pick an unread email and generate an AI-drafted reply
- Review and approve (Y/N) before sending

### 5. View Calendar
- View today's events or the full week ahead

### 6. Schedule Meeting
- Describe a meeting in natural language (e.g., *"Sync with John next Tuesday at 2 PM"*)
- AI parses the title, start/end times, and attendees
- **Interactive attendee picker** — search contacts or enter emails to add invitees
- Option to auto-generate a Google Meet link

## Setup

### Prerequisites
- Python 3.9+
- A Google Cloud project with **Gmail API** and **Google Calendar API** enabled
- OAuth2 credentials (`credentials.json`) downloaded from Google Cloud Console
- A [Gemini API key](https://aistudio.google.com/apikey)

### Installation

```bash
git clone https://github.com/vashwar/GmailAssistant.git
cd GmailAssistant
pip install -r requirements.txt
```

### Configuration

1. Place your OAuth2 `credentials.json` in the `credentials/` folder.

2. Create a `.env` file in the project root:
   ```
   GOOGLE_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-2.0-flash
   USER_NAME=YourName
   TIMEZONE=America/Los_Angeles
   EMAIL_CATEGORIES={"Jobs": ["linkedin", "recruiter"], "Bills": ["invoice", "payment"], ...}
   ```
   - `USER_NAME` — used for mention detection in email triage (default: `Vashwar`)
   - `TIMEZONE` — sets the calendar timezone (default: `America/Los_Angeles`)
   - `EMAIL_CATEGORIES` — optional JSON dict to override the default 13 categories; if not set, uses built-in categories (Jobs, Academic, Shopping, Grocery, Restaurant, Bills, Travel, Banks/Investment, Social Media, Newsletters, Promotions, Family, NewsSummary)

3. (Optional) Customize triage rules in `triage_rules.yaml` to auto-prioritize emails by sender, subject, or keyword.

4. Run the app — on first launch it will open a browser for Google OAuth consent:
   ```bash
   python main.py
   ```
   This generates `credentials/token.json` for future sessions.

> **Note:** If you initially authorized only Gmail, delete `credentials/token.json` and restart to re-authenticate with both Gmail and Calendar scopes.

## Usage

```bash
python main.py
```

```
+---------------------------------------+
|     Gmail & Calendar Assistant        |
+---------------------------------------+
|  1. Smart Triage (Inbox Briefing)     |
|  2. Search & Read Emails              |
|  3. Compose Email (AI-Assisted)       |
|  4. Auto-Reply to Email               |
|  5. View Calendar                     |
|  6. Schedule Meeting                  |
|  0. Exit                              |
+---------------------------------------+
```

## Testing

```bash
python -m pytest tests/ -v
```

66 tests across 4 files covering:
- Triage rules and precedence
- Email categorization (keyword matching and LLM-based)
- LLM functions (JSON parsing, retry logic, draft refinement)
- MIME walking and attachment extraction
- Digest building and formatting (by priority and by category)

All tests use mocked API responses — no live API calls required.

## Project Structure

```
GmailAssistant/
├── .env                    # API keys and config
├── .gitignore              # Excludes credentials, .env, __pycache__
├── credentials/
│   ├── credentials.json    # OAuth2 client config
│   └── token.json          # Generated OAuth2 token
├── requirements.txt        # Python dependencies
├── triage_rules.yaml       # Configurable priority rules (sender/subject/keyword)
├── config.py               # Loads .env, constants, EMAIL_CATEGORIES (13 default categories)
├── auth.py                 # OAuth2 flow and service builders
├── gmail_service.py        # Gmail API operations (fetch, search, send, trash, contacts, labels)
├── llm.py                  # Gemini AI integration (triage, draft, revise, parse, categorize)
├── calendar_service.py     # Google Calendar API operations
├── triage_engine.py        # Smart Triage pipeline (keyword categorization, LLM fallback, digest, labeling, deadline picker)
├── main.py                 # CLI entry point
└── tests/
    ├── test_triage_rules.py  # Rule loading, matching, categorization (keyword and LLM)
    ├── test_llm.py           # JSON parsing, triage scoring, categorization, retry logic
    ├── test_gmail_service.py # MIME walking, attachment extraction
    └── test_digest.py        # Digest building, formatting by priority and by category
```

## Dependencies

- `google-api-python-client` — Gmail and Calendar API client
- `google-auth-oauthlib` — OAuth2 authentication
- `google-generativeai` — Gemini AI SDK
- `python-dotenv` — Environment variable loading
- `python-dateutil` — Date parsing for calendar events
- `beautifulsoup4` — HTML email body extraction
- `pyyaml` — Triage rules configuration
- `pytest` — Test framework
