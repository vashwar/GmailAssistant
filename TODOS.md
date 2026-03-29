# TODOS

## P2 — Batch Auto-Reply for Low-Priority Emails

**What:** After triage categorizes emails by urgency, auto-generate replies for all LOW priority at once. User reviews all drafts in batch, then approves/rejects each.
**Why:** Triage tells you what's low-priority, but you still have to act on each email manually. Batch reply turns awareness into saved time.
**Pros:** Significant time savings for high-volume inboxes. Natural extension of triage.
**Cons:** Risk of sending inappropriate auto-replies. Needs careful prompt engineering.
**Context:** Depends on the Smart Triage Engine being built first — uses its priority scoring output. Build the batch review UI similar to the existing compose feedback loop.
**Effort:** S (human) → S with CC
**Priority:** P2
**Depends on:** Smart Triage Engine

## P2 — Smart Follow-Up Detection

**What:** Scan sent mail for threads where you sent the last message and haven't received a reply in X days (configurable, default 3). Surface in triage digest with nudge email generation.
**Why:** Forgotten follow-ups are a real productivity leak. You forget you're waiting on someone.
**Pros:** Recovers lost threads. Gentle nudge emails maintain momentum.
**Cons:** Needs sent-mail scanning (new Gmail query pattern). Date math for "days since sent."
**Context:** Integrate into the triage digest as a "FOLLOW-UPS NEEDED" section after deadlines. Use Gmail search `in:sent` + thread analysis. The LLM generates the nudge email.
**Effort:** M (human) → S with CC
**Priority:** P2
**Depends on:** Smart Triage Engine
