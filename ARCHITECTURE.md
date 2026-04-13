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

## Future Enhancements

### Planned Features (from TODOS.md)

#### 1. Batch Auto-Reply for Low-Priority Emails (P2)

**What:** Auto-generate replies for all LOW priority emails at once after triage. User reviews all drafts in batch, then approves/rejects each.

**Why:** Triage identifies low-priority emails, but you still handle each manually. Batch reply converts awareness into time savings.

**Implementation:**
```python
# After triage digest display
def _action_batch_auto_reply(digest):
    low_emails = digest["groups"]["LOW"]
    drafts = []

    for email in low_emails:
        reply = generate_auto_reply(email["from"], email["subject"], email["body"])
        drafts.append((email, reply))

    # Batch review UI
    for i, (email, reply) in enumerate(drafts):
        print(f"\n[{i+1}/{len(drafts)}] Reply to: {email['from']}")
        print(reply)
        action = input("[S]end / [E]dit / [Skip]: ")
        # Handle action
```

**Architecture Impact:**
- Extends triage_engine with new bulk action
- Reuses existing `generate_auto_reply()` from llm.py
- Needs batch review UI similar to compose feedback loop
- Safety: Individual approval required per reply

**Dependencies:** Smart Triage Engine (already built)

**Effort:** Small (S)

**Risk:** Sending inappropriate auto-replies without careful review. Mitigation: individual approval + clear diff highlighting.

---

#### 2. Smart Follow-Up Detection (P2)

**What:** Scan sent mail for threads where you sent the last message and haven't received a reply in X days (default 3). Surface in triage digest with AI-generated nudge emails.

**Why:** Forgotten follow-ups leak productivity. You lose track of pending responses.

**Implementation:**
```python
# New module: followup_detector.py
def detect_stale_threads(days_threshold=3):
    """Find threads where user sent last message > threshold days ago."""
    query = f"in:sent newer_than:{days_threshold}d"
    sent_messages = search_emails(query)

    stale_threads = []
    for msg in sent_messages:
        thread = fetch_thread(msg["threadId"])
        if is_last_sender_me(thread) and days_since(thread[-1]) > days_threshold:
            stale_threads.append(thread)

    return stale_threads

def generate_nudge_email(thread):
    """LLM generates gentle follow-up email based on thread context."""
    context = "\n".join([msg["body"] for msg in thread[-3:]])  # Last 3 messages
    prompt = f"""Generate a brief, polite follow-up email for this thread.
    Context: {context}

    The email should gently check in without being pushy."""
    return _generate(prompt).text
```

**Digest Integration:**
```python
# In build_digest()
stale_threads = detect_stale_threads(days_threshold=3)
digest["followups"] = [
    {
        "subject": thread[0]["subject"],
        "recipient": thread[-1]["to"],
        "days_ago": days_since(thread[-1]),
        "nudge_draft": generate_nudge_email(thread)
    }
    for thread in stale_threads
]

# In format_digest() - add new section
if digest["followups"]:
    lines.append("  FOLLOW-UPS NEEDED")
    for f in digest["followups"]:
        lines.append(f"  * {f['subject']} — to {f['recipient']} ({f['days_ago']} days ago)")
```

**Architecture Impact:**
- New module: `followup_detector.py`
- Extends gmail_service with `fetch_thread()` method
- New LLM function: `generate_nudge_email()`
- Integrates into triage digest as new section
- New action menu option: `[F] Send follow-ups`

**Dependencies:** Smart Triage Engine

**Effort:** Medium → Small with AI assistance

**Gmail API Requirements:**
- `in:sent` search query
- Thread fetching (multiple messages in conversation)
- Date comparison logic

---

### Architectural Improvements

#### 3. Local LLM Support

**Add Ollama backend for offline operation:**
```python
# llm.py - Provider abstraction
class LLMProvider:
    def generate(self, prompt: str) -> str:
        raise NotImplementedError

class GemmaCloudProvider(LLMProvider):
    """Current Google AI API implementation"""
    def generate(self, prompt):
        return _model.generate_content(prompt).text

class OllamaProvider(LLMProvider):
    """Local Ollama implementation"""
    def __init__(self, model="gemma-4-31b"):
        self.model = model
        self.client = ollama.Client()

    def generate(self, prompt):
        response = self.client.generate(model=self.model, prompt=prompt)
        return response['response']

# config.py
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "cloud")  # "cloud" or "ollama"
```

**Benefits:**
- No API costs
- No rate limits
- Offline operation
- Faster for local models

**Trade-offs:**
- Requires Ollama installation
- 31B model needs ~20GB RAM
- Slower inference than cloud (depends on hardware)

---

#### 4. Email Caching Layer (SQLite)

**Persistent local storage for email data:**
```python
# cache.py - New module
import sqlite3
from datetime import datetime

class EmailCache:
    def __init__(self, db_path="emails.db"):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                sender TEXT,
                subject TEXT,
                body TEXT,
                date DATETIME,
                priority TEXT,
                category TEXT,
                summary TEXT,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def sync_new_emails(self):
        """Incremental sync: fetch only emails since last sync"""
        last_sync = self.get_last_sync_time()
        new_emails = fetch_unread_emails(since=last_sync)
        self.insert_emails(new_emails)

    def search_local(self, query):
        """Fast SQL search on cached data"""
        return self.conn.execute(
            "SELECT * FROM emails WHERE subject LIKE ? OR body LIKE ?",
            (f"%{query}%", f"%{query}%")
        ).fetchall()
```

**Benefits:**
- Offline access to historical emails
- Fast local search (no API calls)
- Reduced Gmail API quota usage
- Historical analytics capability

**Integration Points:**
- `gmail_service.py` checks cache before API call
- `triage_engine.py` can triage from cache
- Periodic background sync for new emails

**Storage Requirements:**
- ~1KB per email (text only)
- 10,000 emails ≈ 10MB database file

---

#### 5. Async/Concurrent Processing

**Parallel LLM calls for faster triage:**
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def score_email_async(email, rules, categories):
    """Async wrapper around score_email"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, score_email, email, rules, categories
    )

async def run_triage_async(emails):
    """Score all emails in parallel"""
    tasks = [score_email_async(e, rules, categories) for e in emails]
    return await asyncio.gather(*tasks)

# Usage in triage_engine.py
scored = asyncio.run(run_triage_async(emails))
```

**Performance Gains:**
- 50 emails sequential: ~50 seconds (1 LLM call/sec)
- 50 emails parallel (10 concurrent): ~5 seconds
- **10x speedup** for large batches

**Considerations:**
- LLM API rate limits (Gemma 4 31B: ~60 QPM)
- Optimal concurrency: 10-20 parallel calls
- Requires async/await refactoring of service modules

---

#### 6. Batch LLM Calls

**Single API call for multiple emails:**
```python
def triage_batch(emails, categories):
    """Triage multiple emails in one LLM call"""
    emails_json = json.dumps([
        {"from": e["from"], "subject": e["subject"], "body": e["body"][:500]}
        for e in emails
    ])

    prompt = f"""Analyze these {len(emails)} emails and return a JSON array
    with triage results for each. Format:
    [
      {{"email_index": 0, "summary": "...", "urgency": "high", ...}},
      {{"email_index": 1, "summary": "...", "urgency": "low", ...}},
      ...
    ]

    Emails: {emails_json}
    """

    response = _generate(prompt)
    results = _parse_json_response(response.text)
    return results
```

**Benefits:**
- Reduces API calls: 50 emails → 1 call (if fits in context)
- Lower latency (fewer round-trips)
- Better cost efficiency

**Trade-offs:**
- Context window limits (256K tokens ≈ ~100 emails)
- Harder JSON parsing (larger response)
- Less granular error handling

---

#### 7. Web UI

**FastAPI backend + React frontend:**
```
gmailassistant/
├── api/
│   ├── main.py          # FastAPI app
│   ├── routers/
│   │   ├── triage.py    # POST /triage
│   │   ├── compose.py   # POST /compose
│   │   └── calendar.py  # GET /events
│   └── models.py        # Pydantic schemas
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── DigestView.tsx
│   │   │   ├── ComposeModal.tsx
│   │   │   └── CalendarWidget.tsx
│   │   └── App.tsx
│   └── package.json
└── (existing CLI modules reused as backend services)
```

**Benefits:**
- Visual digest with drag-to-trash
- Rich text editor for compose
- Calendar integration with timeline view
- Mobile-friendly responsive design

**Architecture:**
- Reuse existing service modules (gmail_service, llm, etc.)
- API layer wraps CLI functions
- OAuth2 handled server-side
- WebSocket for real-time updates

---

#### 8. Plugin System

**User-defined triage rules as Python code:**
```python
# plugins/custom_rules.py
from triage_engine import register_rule

@register_rule(priority=1)  # Highest priority
def vip_sender_rule(email):
    """Auto-prioritize emails from VIP list"""
    vips = ["ceo@company.com", "boss@company.com"]
    if any(vip in email["from"] for vip in vips):
        return {"priority": "HIGH", "category": "VIP"}
    return None

@register_rule(priority=10)
def weekend_demotion(email):
    """Lower priority for emails sent on weekends"""
    if is_weekend(email["date"]):
        return {"priority": "LOW", "category": "Weekend"}
    return None
```

**Custom LLM prompts:**
```python
# plugins/custom_prompts.py
CUSTOM_TRIAGE_PROMPT = """You are a senior executive's assistant.
Analyze emails with extreme attention to financial mentions and deadlines.
Always escalate anything involving money, contracts, or legal matters to HIGH priority.
"""

register_prompt("triage", CUSTOM_TRIAGE_PROMPT)
```

**Benefits:**
- No code changes to core app
- User-specific business logic
- Community plugin sharing
- A/B test different prompts

**Plugin Discovery:**
```python
# config.py
PLUGINS_DIR = os.getenv("PLUGINS_DIR", "plugins/")

# Load all .py files in plugins/
for plugin_file in glob(f"{PLUGINS_DIR}/*.py"):
    importlib.import_module(plugin_file)
```

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
