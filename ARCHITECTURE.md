# Architecture Documentation

## Overview

Gmail & Calendar Assistant is a Python CLI application that integrates Gmail API, Google Calendar API, and Google AI (Gemma/Gemini) to provide intelligent email management and calendar scheduling. The architecture follows a layered service pattern with strict one-way dependencies to prevent circular imports and maintain clean separation of concerns.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        User (CLI)                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                      main.py                                 │
│                   (CLI Menu Loop)                            │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
┌───────▼──────┐ ┌───▼──────┐ ┌───▼──────────┐
│ triage_      │ │ gmail_   │ │ calendar_    │
│ engine.py    │ │ service  │ │ service.py   │
└───────┬──────┘ └───┬──────┘ └───┬──────────┘
        │            │            │
        │       ┌────▼────┐  ┌────▼────┐
        │       │ llm.py  │  │ auth.py │
        │       └────┬────┘  └────┬────┘
        │            │            │
        └────────────┼────────────┘
                     │
              ┌──────▼──────┐
              │  config.py  │
              │  (.env)     │
              └─────────────┘
```

## Module Dependencies

**Dependency Flow (strictly one-way):**

```
main.py
  ↓
triage_engine.py
  ↓
gmail_service.py, calendar_service.py, llm.py
  ↓
auth.py, config.py
```

**Rules:**
- No circular dependencies allowed
- Service modules (gmail_service, calendar_service, llm) are independent of each other
- All modules can import from config.py and auth.py
- main.py orchestrates but never imported by other modules

## Core Modules

### 1. main.py - CLI Orchestrator

**Responsibility:** User interaction and workflow orchestration

**Key Functions:**
- `main()` - Entry point, displays menu loop
- `option_smart_triage()` - Delegates to triage_engine
- `option_search_emails()` - Search and display emails
- `option_compose_email()` - AI-assisted email composition with feedback loop
- `option_auto_reply()` - Generate and send auto-replies
- `option_view_calendar()` - Display calendar events
- `option_schedule_meeting()` - Natural language meeting scheduling

**Design Patterns:**
- Menu-driven CLI with numbered options
- Explicit user confirmation (Y/N) before all destructive/send operations
- Contact search with fuzzy matching for recipient selection
- Feedback loop for AI-generated drafts (compose → refine → revise → approve)

### 2. triage_engine.py - Smart Triage Pipeline

**Responsibility:** Email scoring, categorization, digest generation, bulk actions

**Key Components:**

#### Two-Phase Priority Scoring
1. **Rule-based scoring** (deterministic, from `triage_rules.yaml`)
   - Sender matching (highest priority)
   - Subject keyword matching (medium priority)
   - Body keyword matching (lowest priority)
2. **LLM fallback** (only if no rule matches)
   - AI-scored urgency: HIGH/MEDIUM/LOW
   - Rule priority always wins when matched

#### Keyword-First Categorization
1. **Fast keyword matching** against 13 default categories
   - Exact email match for sender addresses (strict guardrail)
   - Substring match for non-email keywords
2. **LLM refinement** (optional, triggered by user feedback)
   - User provides feedback on incorrect categorization
   - AI re-categorizes all emails based on feedback
   - Iterative approval loop until user accepts

#### Digest Building
- Groups emails by priority (HIGH/MEDIUM/LOW)
- Extracts all deadlines across emails
- Surfaces all attachments with metadata
- Formats executive briefing with emoji indicators

#### Bulk Actions
- Trash specific emails or all LOW priority
- Interactive deadline picker (add selected to calendar)
- Auto-reply with AI-generated responses
- Label management with category-based Gmail labels

**Data Flow:**
```
fetch_unread_emails() → score_email() → build_digest() → format_digest() → action_menu
                            ↓
                    match_rule() (YAML)
                    categorize_email() (keywords)
                    triage_email() (LLM)
```

### 3. gmail_service.py - Gmail API Operations

**Responsibility:** Gmail API wrapper with MIME parsing and contact management

**Key Functions:**
- `fetch_unread_emails(max_results)` - Get unread messages with full parsing
- `search_emails(query)` - Gmail search operators support
- `send_email(to, subject, body)` - Send new email
- `send_reply(msg_id, to, subject, body, thread_id)` - Threaded replies with proper headers
- `trash_email(msg_id)` - Move to trash
- `search_contacts(query)` - Find recipients from email history
- `get_or_create_label(name)` - Label management
- `apply_label(msg_id, label_id)` - Apply Gmail labels

**MIME Parsing Architecture:**
- Single-pass tree walk via `_walk_payload()`
- Extracts both body text and attachment metadata in one traversal
- HTML-to-text conversion with BeautifulSoup
- Base64 decoding for attachment data
- Handles multipart messages, nested structures, inline images

**Contact Search:**
- Searches both FROM and TO fields in email history
- Returns unique contacts with name extraction
- Case-insensitive matching

### 4. calendar_service.py - Google Calendar API Operations

**Responsibility:** Calendar event management

**Key Functions:**
- `get_events_today()` - Today's schedule
- `get_events_week()` - Week ahead view
- `create_event(summary, start, end, attendees, meet_link)` - Create events
- `create_event_from_deadline(subject, deadline_str)` - Parse and create deadline events

**Event Creation:**
- ISO 8601 datetime formatting with timezone support
- Optional Google Meet link generation
- Multi-attendee support with email validation

### 5. llm.py - AI Integration Layer

**Responsibility:** Google AI API wrapper with retry logic and structured output parsing

**Supported Models:**
- Gemma 4 31B Instruct (default, free tier)
- Gemini 2.0/3.0 Flash (configurable via `.env`)

**Key Functions:**

#### Email Analysis
- `triage_email()` - Full triage analysis
  - Summary (1-2 sentences)
  - Urgency scoring (high/medium/low)
  - Mention detection (checks for USER_NAME)
  - Action required flag
  - Deadline extraction
  - Category suggestion
- `categorize_email_llm()` - Single-email categorization with user feedback support

#### Draft Composition
- `refine_draft()` - Polish rough text into professional email
  - Tone adjustment (Professional/Friendly/Formal/Casual)
  - Subject line refinement
  - Grammar and flow fixes
  - Anti-hallucination guardrails (no invented dates/names/metrics)
- `revise_draft()` - Apply user feedback to existing draft
  - Targeted changes only (preserves unchanged parts)
  - Maintains tone consistency

#### Auto-Reply
- `generate_auto_reply()` - Context-aware reply generation

#### Meeting Parsing
- `parse_meeting_request()` - Natural language → structured event
  - Relative date parsing ("next Tuesday", "tomorrow")
  - Time extraction and ISO 8601 conversion
  - Attendee email extraction

**Error Handling Architecture:**

```python
@retry_with_backoff(max_retries=3, base_delay=1.0, backoff_multiplier=2.0)
def _generate(prompt):
    return _model.generate_content(prompt)
```

**Retryable Errors:**
- `ResourceExhausted` (429) - Rate limit
- `ServiceUnavailable` (503) - Temporary outage
- `ConnectionError` - Network failure
- `TimeoutError` - Request timeout

**Retry Strategy:**
- Exponential backoff: 1s → 2s → 4s
- Max 3 retries before failure
- All other exceptions raised immediately

**JSON Response Parsing:**

3-tier fallback strategy in `_parse_json_response()`:
1. Direct `json.loads()` on cleaned text
2. Strip markdown code fences (```json ... ```) and retry
3. Regex extraction of first JSON object `\{.*\}`

Every LLM function has a **fallback default** if JSON parsing fails:
- `triage_email()` → urgency="low", no deadlines, summary=raw_text[:200]
- `categorize_email_llm()` → "Misc"
- `refine_draft()` → original subject + raw response as body

### 6. auth.py - OAuth2 & Service Management

**Responsibility:** Google OAuth2 flow and cached service builders

**Global Service Caching:**
```python
_gmail_service = None
_calendar_service = None

def get_gmail_service():
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = build('gmail', 'v1', credentials=creds)
    return _gmail_service
```

**Benefits:**
- Services built once per session
- Credentials cached in `credentials/token.json`
- Automatic token refresh on expiry
- Re-authentication flow if token invalid

**OAuth2 Scopes:**
- `https://mail.google.com/` - Full Gmail access
- `https://www.googleapis.com/auth/calendar` - Calendar read/write

**First-Run Flow:**
1. Check for `credentials/token.json`
2. If missing, launch browser for OAuth consent
3. User grants permissions
4. Token saved for future sessions

**Scope Addition:**
If calendar scope added later, user must delete `token.json` and re-authenticate.

### 7. config.py - Configuration Management

**Responsibility:** Environment variable loading and constants

**Configuration Sources:**
1. `.env` file (via python-dotenv)
2. Hardcoded defaults as fallbacks

**Key Configuration:**
```python
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-31b-it")
USER_NAME = os.getenv("USER_NAME", "Vashwar")
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
EMAIL_CATEGORIES = json.loads(os.getenv("EMAIL_CATEGORIES", "{}")) or _DEFAULT_EMAIL_CATEGORIES
```

**Default Email Categories (13 total):**
- Jobs, Academic, Online Shopping, Grocery, Restaurant
- Bills, Travel, Banks/Investment, Social Media
- Newsletters, Promotions, Family, NewsSummary

**Category Override:**
- Set `EMAIL_CATEGORIES` in `.env` as JSON string
- Merged with YAML categories in triage_rules

### 8. triage_rules.yaml - Declarative Priority Rules

**Purpose:** User-customizable priority scoring without code changes

**Structure:**
```yaml
rules:
  - match:
      from: "boss@company.com"
    priority: HIGH
    category: "Work - Leadership"

  - match:
      subject_contains: "URGENT"
    priority: HIGH

  - match:
      keyword: "invoice"
    priority: MEDIUM
    category: "Bills"

default_category: "general"

categories:
  Jobs: ["linkedin", "recruiter", "hiring"]
  Bills: ["invoice", "payment", "subscription"]
```

**Matching Precedence (auto-sorted by specificity):**
1. `from` - Sender email (highest)
2. `subject_contains` - Subject keyword (medium)
3. `keyword` - Subject or body (500 char preview) (lowest)

**Category Precedence:**
1. Rule-based category (from YAML)
2. Keyword-based category (from EMAIL_CATEGORIES)
3. LLM-suggested category
4. Default category

## Data Flow Diagrams

### Smart Triage Flow

```
User selects "Smart Triage"
    ↓
main.py → triage_engine.run_triage()
    ↓
Fetch N unread emails (default 50)
    ↓
For each email:
    ┌──────────────────────┐
    │  score_email()       │
    │  ├─ match_rule()     │ ← triage_rules.yaml
    │  ├─ categorize()     │ ← EMAIL_CATEGORIES (keywords)
    │  └─ triage_email()   │ ← LLM API call
    └──────────────────────┘
    ↓
build_digest() → Groups by priority, extracts deadlines/attachments
    ↓
format_digest() → Executive briefing text
    ↓
Display digest + action menu
    ↓
User actions:
    [R] Read email
    [T] Trash specific
    [TL] Trash all LOW
    [A] Auto-reply (LLM API call)
    [D] Add deadlines to calendar
    [C] View by category
    [L] Label by category (with LLM refinement loop if feedback given)
```

### Email Composition Flow

```
User selects "Compose Email"
    ↓
Mode selection: [N]ew or [R]eply
    ↓
Contact search → Fuzzy match from email history
    ↓
User enters: subject, tone, rough draft
    ↓
LLM refine_draft() → {subject, body}
    ↓
Display refined draft
    ↓
User feedback loop:
    [S]end → Confirm Y/N → send_email()
    [R]evise → Enter feedback → LLM revise_draft() → Display → Loop
    [C]ancel → Discard
```

### Meeting Scheduling Flow

```
User selects "Schedule Meeting"
    ↓
Enter natural language request:
    "Team sync next Tuesday at 2 PM with alice@company.com"
    ↓
LLM parse_meeting_request()
    ↓
{summary, start, end, attendees: []} extracted
    ↓
Interactive attendee picker:
    Search contacts → Select → Add
    Enter email directly → Add
    [D]one when finished
    ↓
Google Meet link? [Y/N]
    ↓
Confirm all details
    ↓
create_event() → Calendar API
```

## Security & Privacy Considerations

### API Key Management
- `.env` file excluded from git via `.gitignore`
- `GOOGLE_API_KEY` never logged or displayed
- OAuth2 tokens stored locally in `credentials/token.json` (also gitignored)

### User Confirmation Gates
**All destructive/send operations require explicit Y/N confirmation:**
- Send email (new or reply)
- Trash emails (individual or bulk)
- Create calendar events
- Apply Gmail labels

**Rationale:** Prevents accidental LLM-generated actions from executing without user review.

### LLM Hallucination Guardrails

**Prompts explicitly forbid inventing:**
- Dates and deadlines
- Names and email addresses
- Metrics and numbers
- Commitments or promises

**Example from `refine_draft()` prompt:**
```
2. No Hallucinations: NEVER invent dates, metrics, names, or commitments
   that are not explicitly provided in the rough draft. If information
   seems missing, leave it out or use a placeholder like [Insert Date].
```

### Email Body Truncation
All email bodies truncated to **4000 characters** before sending to LLM to:
- Avoid token limit errors
- Reduce API costs
- Prevent context overflow

### OAuth2 Scope Limitations
- Gmail: Full access (`https://mail.google.com/`) required for trash, send, labels
- Calendar: Read/write only (`calendar`, not `calendar.readonly`)

**Why full Gmail access?**
- Needed for send, trash, label operations
- Read-only scope insufficient for assistant features

## Testing Architecture

### Test Coverage

**66 tests across 4 files:**
1. `test_triage_rules.py` - Rule loading, matching, categorization
2. `test_llm.py` - JSON parsing, triage scoring, retry logic
3. `test_gmail_service.py` - MIME walking, attachment extraction
4. `test_digest.py` - Digest building, formatting (priority & category views)

### Mocking Strategy

**All external APIs mocked:**
- Gmail API responses: Mock message objects with MIME structure
- Calendar API: Mock event creation/fetch
- LLM API: Mock `_generate()` to return fixture JSON strings
- File I/O: Mock YAML loading, .env reading

**Benefits:**
- No live API calls during tests (fast, no cost, no auth required)
- Deterministic test results
- Offline testing capability

### Test Fixtures

**MIME message fixtures:**
```python
MULTIPART_ALTERNATIVE_MIME = {
    'id': 'test123',
    'threadId': 'thread123',
    'payload': {
        'mimeType': 'multipart/alternative',
        'parts': [
            {'mimeType': 'text/plain', 'body': {'data': base64_encoded_text}},
            {'mimeType': 'text/html', 'body': {'data': base64_encoded_html}},
        ]
    }
}
```

**LLM response fixtures:**
```python
MOCK_TRIAGE_RESPONSE = """{
  "summary": "Project deadline reminder",
  "urgency": "high",
  "mentions_user": true,
  "action_required": true,
  "category": "Work",
  "deadlines": ["2026-04-15"]
}"""
```

## Performance Considerations

### API Call Optimization

**Smart Triage API Usage:**
- 1 LLM call per email (for triage analysis)
- Optional +1 per auto-reply
- Optional +N for label refinement (only if user rejects initial categorization)

**Example for 50 emails:**
- Base: 50 LLM calls
- With 3 auto-replies: 53 calls
- With label refinement: 103 calls (50 + 50 + 3)

**Rate Limit Mitigation:**
- Switched to Gemma 4 31B (free tier, higher limits than Gemini)
- Exponential backoff retry on 429 errors
- Body truncation (4000 char) reduces token usage

### Caching

**Service Caching:**
- Gmail/Calendar services built once per session
- Reduces auth overhead on repeated operations

**No Email Caching:**
- All fetches are live (ensures up-to-date data)
- Trade-off: More API calls for freshness

### MIME Parsing Efficiency

Single-pass tree walk:
- Extract text and attachments in one traversal
- Avoid multiple `_walk_payload()` calls per message

## Future Architecture Improvements

### Potential Enhancements

1. **Local LLM Support**
   - Add Ollama backend option for offline operation
   - Provider abstraction: `LLMProvider` interface with `GemmaProvider`, `OllamaProvider`

2. **Email Caching Layer**
   - SQLite database for offline access
   - Incremental sync (only fetch new messages)
   - Reduces Gmail API quota usage

3. **Batch LLM Calls**
   - Send multiple emails in one API call using structured prompts
   - Reduce latency for large triage operations

4. **Async/Concurrent Processing**
   - `asyncio` for parallel LLM calls during triage
   - Significant speedup for 50+ email batches

5. **Web UI**
   - FastAPI backend serving same service modules
   - React frontend for visual digest/calendar

6. **Plugin System**
   - User-defined triage rules as Python functions
   - Custom LLM prompt templates
   - Extensible action menu

## Deployment & Packaging

### Current Distribution
- Git clone + pip install
- Manual `.env` configuration
- Local execution only

### Potential Improvements
1. **PyPI Package**
   - `pip install gmail-assistant`
   - CLI entry point: `gmail-assistant`

2. **Docker Container**
   - Pre-configured environment
   - Volume mount for credentials

3. **Configuration Wizard**
   - Interactive setup on first run
   - OAuth flow integrated into CLI
   - Auto-generate `.env` from prompts

## Conclusion

The architecture prioritizes:
- **Simplicity** - Flat module structure, no complex frameworks
- **Modularity** - Service modules independent and testable
- **Safety** - Explicit confirmations, anti-hallucination guardrails
- **Extensibility** - YAML rules, .env config, swappable LLM providers
- **Testability** - Mock-friendly design, 66 tests with 100% mocked APIs

The one-way dependency flow and service layer pattern make the codebase maintainable and easy to extend with new features like Slack integration, SMS notifications, or additional LLM providers.
