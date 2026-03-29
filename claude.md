# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## gstack

- For all web browsing, always use the `/browse` skill from gstack. Never use `mcp__claude-in-chrome__*` tools.

### Available gstack skills

- `/office-hours` - Office hours
- `/plan-ceo-review` - Plan CEO review
- `/plan-eng-review` - Plan engineering review
- `/plan-design-review` - Plan design review
- `/design-consultation` - Design consultation
- `/review` - Code review
- `/ship` - Ship
- `/land-and-deploy` - Land and deploy
- `/canary` - Canary
- `/benchmark` - Benchmark
- `/browse` - Web browsing
- `/qa` - QA
- `/qa-only` - QA only
- `/design-review` - Design review
- `/setup-browser-cookies` - Setup browser cookies
- `/setup-deploy` - Setup deploy
- `/retro` - Retro
- `/investigate` - Investigate
- `/document-release` - Document release
- `/codex` - Codex
- `/cso` - CSO
- `/autoplan` - Auto plan
- `/careful` - Careful mode
- `/freeze` - Freeze
- `/guard` - Guard
- `/unfreeze` - Unfreeze
- `/gstack-upgrade` - Upgrade gstack

## Project Overview

Python CLI assistant integrating Gmail and Google Calendar APIs, powered by Google Gemini AI (`gemini-2.0-flash`). Acts as an intelligent executive assistant for email triage, AI-assisted drafting, auto-replies, and calendar management.

## Running the App

```bash
pip install -r requirements.txt
python main.py
```

First run opens a browser for Google OAuth2 consent. Subsequent runs use the cached `credentials/token.json`. If you need to re-authorize (e.g., after adding Calendar scope), delete `credentials/token.json` and restart.

## Testing

```bash
python -m pytest tests/ -v
```

48 tests across 4 files covering triage rules, LLM functions, MIME parsing, and digest formatting. All tests use mocked API responses (no live API calls).

## Architecture

```
main.py              → CLI menu loop, user interaction workflows
├── triage_engine.py → Smart Triage pipeline (rules + LLM scoring, digest, bulk actions)
├── auth.py          → OAuth2 flow, cached Gmail/Calendar service builders
├── config.py        → .env loading, constants (scopes, paths, user name, timezone, Gemini model)
├── llm.py           → Gemini AI calls (triage, summarize, draft, revise, auto-reply, parse meetings)
├── gmail_service.py → Gmail API operations (fetch, search, send, reply, trash, contacts, MIME parsing)
└── calendar_service.py → Calendar API operations (view events, create events/deadlines)
```

```
triage_rules.yaml    → Configurable priority rules (sender/subject/keyword matching)
```

**Dependency flow is strictly one-way:** `main.py` → `triage_engine.py` → service modules → `auth.py`/`config.py`. No circular imports.

### Key patterns

- **Global service caching** — `auth.py` caches `_gmail_service` and `_calendar_service` at module level; built lazily on first call.
- **Structured LLM output** — `llm.py` prompts Gemini for JSON responses, parsed by `_parse_json_response()` with a 3-tier fallback (direct parse → strip markdown fences → regex extraction). Every LLM function has a fallback default if parsing fails.
- **Retry with backoff** — All `_model.generate_content()` calls go through `_generate()` which retries on 429/503/ConnectionError/TimeoutError with exponential backoff (max 3 retries).
- **Two-phase priority scoring** — `triage_engine.py` applies deterministic YAML rules first (sender > subject > keyword specificity), then LLM scoring as fallback. Rule-based priority wins when matched.
- **Single-pass MIME walking** — `gmail_service.py` walks the MIME tree once via `_walk_payload()`, extracting both body text and attachment metadata in a single pass.
- **User confirmation before actions** — All send/trash/create operations require explicit Y/N confirmation in the CLI. This is a deliberate design choice — never bypass it.
- **Hallucination guardrails** — LLM prompts explicitly forbid inventing dates, names, metrics, or commitments. Maintain these rules when modifying prompts.

### Config and credentials

- `credentials/credentials.json` — OAuth2 client secrets (not in repo)
- `credentials/token.json` — Generated OAuth2 token (not in repo)
- `.env` — Contains `GOOGLE_API_KEY` (Gemini), optional `GEMINI_MODEL` override, `USER_NAME` (default "Vashwar"), `TIMEZONE` (default "America/Los_Angeles")
- `triage_rules.yaml` — Priority rules with sender/subject/keyword matching and categories
- OAuth2 scopes: full Gmail access (`https://mail.google.com/`) + Calendar read/write

## Project Specification

### Core Features

1. **Smart Triage (Inbox Briefing)** — Fetch unread emails, apply configurable rules + AI scoring, generate executive digest grouped by HIGH/MEDIUM/LOW priority, surface deadlines and attachments, bulk actions (trash LOW, add deadlines to calendar, auto-reply).
2. **Search & Read** — Gmail search operators (`from:`, `subject:`, `has:attachment`), display clean parsed email text.
3. **AI-Assisted Compose** — Contact search for recipients, tone selection (Professional/Friendly/Formal/Casual), AI refines subject + body, feedback loop for revisions, send only after approval.
4. **Auto-Reply** — Pick an unread email, AI generates reply, user approves before sending. Replies maintain thread context (In-Reply-To, References headers).
5. **Calendar View** — Today's events or full week ahead.
6. **Meeting Scheduling** — Natural language parsing to create events, interactive attendee picker with contact search, optional Google Meet link generation.

### LLM Engine

Built modularly in `llm.py` to allow swapping between cloud API (Gemini) and local models (Ollama, HuggingFace). All AI calls go through `_generate()` with retry-with-backoff. Email bodies are truncated to 4000 chars before sending to the LLM.

### Future work

See `TODOS.md` for deferred items (batch auto-reply, smart follow-up detection).
