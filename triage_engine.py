import os
import fnmatch
import logging
from datetime import datetime

import yaml

from config import USER_NAME, TIMEZONE
from gmail_service import fetch_unread_emails, trash_email, _format_size
from llm import triage_email, generate_auto_reply
from calendar_service import create_event_from_deadline

logger = logging.getLogger(__name__)

RULES_PATH = "triage_rules.yaml"


# ── Rule loading ──────────────────────────────────────────────────────────────

def load_rules(path=RULES_PATH):
    """Load triage rules from YAML. Returns (rules_list, default_category) or ([], "general") on failure."""
    if not os.path.exists(path):
        logger.info("No triage rules file at %s — using LLM-only scoring.", path)
        return [], "general"

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        logger.warning("Malformed or unreadable triage rules (%s): %s — using LLM-only scoring.", path, e)
        print(f"  Warning: Could not parse {path}: {e}")
        return [], "general"

    if not isinstance(data, dict):
        logger.warning("triage_rules.yaml root is not a dict — using LLM-only scoring.")
        print(f"  Warning: {path} has invalid structure.")
        return [], "general"

    rules = data.get("rules", [])
    if not isinstance(rules, list):
        rules = []
    default_category = data.get("default_category", "general")

    # Auto-sort by specificity: sender > subject_contains > keyword
    def _specificity(rule):
        match = rule.get("match", {})
        if "from" in match:
            return 0
        if "subject_contains" in match:
            return 1
        if "keyword" in match:
            return 2
        return 3

    rules.sort(key=_specificity)
    return rules, default_category


def match_rule(email, rules):
    """Apply first-match rule against an email. Returns (priority, category) or (None, None)."""
    sender = email.get("from", "").lower()
    subject = email.get("subject", "").lower()
    body_preview = email.get("body", "")[:500].lower()

    for rule in rules:
        match = rule.get("match", {})

        if "from" in match:
            pattern = match["from"].lower()
            # Check both raw sender and extracted email address
            if fnmatch.fnmatch(sender, f"*{pattern}*") or fnmatch.fnmatch(sender, pattern):
                return rule.get("priority", "MEDIUM").upper(), rule.get("category")
            continue

        if "subject_contains" in match:
            keyword = match["subject_contains"].lower()
            if keyword in subject:
                return rule.get("priority", "MEDIUM").upper(), rule.get("category")
            continue

        if "keyword" in match:
            keyword = match["keyword"].lower()
            if keyword in subject or keyword in body_preview:
                return rule.get("priority", "MEDIUM").upper(), rule.get("category")
            continue

    return None, None


# ── Scoring pipeline ──────────────────────────────────────────────────────────

def score_email(email, rules, default_category="general", categories=None):
    """Two-phase scoring: deterministic rules first, LLM fallback.

    Returns a scored dict augmenting the original email with triage fields.
    """
    rule_priority, rule_category = match_rule(email, rules)

    # LLM pass — always run for summary, deadlines, action detection
    llm_result = triage_email(
        email["from"], email["subject"], email["body"],
        user_name=USER_NAME, categories=categories,
    )

    # Merge: rule-based priority wins if set
    if rule_priority:
        priority = rule_priority
    else:
        priority = llm_result.get("urgency", "low").upper()

    category = rule_category or llm_result.get("category", default_category)

    return {
        **email,
        "priority": priority,
        "category": category,
        "summary": llm_result.get("summary", ""),
        "action_required": llm_result.get("action_required", False),
        "mentions_user": llm_result.get("mentions_user", False),
        "deadlines": llm_result.get("deadlines", []),
    }


# ── Digest building ──────────────────────────────────────────────────────────

def build_digest(scored_emails):
    """Aggregate scored emails into a digest structure grouped by priority."""
    groups = {"HIGH": [], "MEDIUM": [], "LOW": []}
    all_deadlines = []
    all_attachments = []

    for email in scored_emails:
        bucket = email.get("priority", "LOW").upper()
        if bucket not in groups:
            bucket = "LOW"
        groups[bucket].append(email)

        for d in email.get("deadlines", []):
            all_deadlines.append({
                "deadline": d,
                "subject": email.get("subject", ""),
                "from": email.get("from", ""),
            })

        for att in email.get("attachments", []):
            all_attachments.append({
                **att,
                "email_subject": email.get("subject", ""),
                "email_from": email.get("from", ""),
            })

    return {
        "total": len(scored_emails),
        "groups": groups,
        "deadlines": all_deadlines,
        "attachments": all_attachments,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def format_digest(digest):
    """Render the digest as a formatted CLI string."""
    lines = []
    total = digest["total"]
    ts = digest["generated_at"]

    lines.append("")
    lines.append("=" * 62)
    lines.append(f"  INBOX BRIEFING  —  {ts}  —  {total} unread emails")
    lines.append("=" * 62)

    email_number = 1
    number_map = {}  # global_number -> email dict

    for level, emoji in [("HIGH", "!!"), ("MEDIUM", "--"), ("LOW", "..")]:
        group = digest["groups"].get(level, [])
        if not group:
            continue

        lines.append("")
        lines.append(f"  {emoji} {level} PRIORITY ({len(group)})")
        lines.append(f"  {'─' * 40}")

        for email in group:
            number_map[email_number] = email
            subj = email.get("subject", "(no subject)")
            if len(subj) > 50:
                subj = subj[:47] + "..."
            sender = email.get("from", "")
            lines.append(f"  {email_number}. {sender}")
            lines.append(f"     {subj}")

            parts = []
            if email.get("action_required"):
                parts.append("Action required")
            if email.get("mentions_user"):
                parts.append(f"Mentions {USER_NAME}")
            if email.get("deadlines"):
                parts.append(f"Deadline: {', '.join(email['deadlines'])}")
            if parts:
                lines.append(f"     -> {'. '.join(parts)}.")

            if email.get("attachments"):
                for att in email["attachments"]:
                    size = _format_size(att.get("size", 0))
                    lines.append(f"     [ATT] {att['filename']} ({size})")

            lines.append(f"     Summary: {email.get('summary', '')}")
            email_number += 1

    # Deadlines section
    if digest["deadlines"]:
        lines.append("")
        lines.append("  DEADLINES DETECTED")
        lines.append(f"  {'─' * 40}")
        for d in digest["deadlines"]:
            lines.append(f"  * {d['deadline']} — {d['subject']} (from {d['from']})")

    # Attachments section
    if digest["attachments"]:
        lines.append("")
        lines.append(f"  ATTACHMENTS ({len(digest['attachments'])} total)")
        lines.append(f"  {'─' * 40}")
        for att in digest["attachments"]:
            size = _format_size(att.get("size", 0))
            lines.append(f"  * {att['filename']} ({size}) — from: {att['email_subject']}")

    lines.append("")
    lines.append("=" * 62)

    return "\n".join(lines), number_map


# ── Action menu ───────────────────────────────────────────────────────────────

def _action_read(number_map):
    """Read a specific email from the digest."""
    choice = input("  Enter email number to read: ").strip()
    if not choice.isdigit():
        print("  Invalid number.\n")
        return
    num = int(choice)
    if num not in number_map:
        print(f"  No email #{num} in digest.\n")
        return
    email = number_map[num]
    print(f"\n{'=' * 60}")
    print(f"From:    {email['from']}")
    print(f"To:      {email.get('to', '')}")
    print(f"Subject: {email['subject']}")
    print(f"Date:    {email.get('date', '')}")
    print(f"{'=' * 60}")
    print(email.get("body", "(no body)"))
    print(f"{'=' * 60}\n")


def _action_trash_specific(number_map):
    """Trash specific emails by number."""
    print("  Enter email numbers to trash (comma-separated, e.g. 1,3,5):")
    selection = input("  > ").strip()
    if not selection:
        return
    for idx_str in selection.split(","):
        idx_str = idx_str.strip()
        if idx_str.isdigit() and int(idx_str) in number_map:
            email = number_map[int(idx_str)]
            try:
                trash_email(email["id"])
                print(f"  Trashed: {email['subject']}")
            except Exception as e:
                print(f"  Failed to trash '{email['subject']}': {e}")
        else:
            print(f"  Invalid number: {idx_str}")
    print()


def _action_trash_all_low(number_map, digest):
    """Trash all LOW priority emails."""
    low_emails = digest["groups"].get("LOW", [])
    if not low_emails:
        print("  No LOW priority emails to trash.\n")
        return

    print(f"  This will trash {len(low_emails)} LOW priority email(s).")
    confirm = input("  Proceed? (Y/N): ").strip().upper()
    if confirm != "Y":
        print("  Cancelled.\n")
        return

    for email in low_emails:
        try:
            trash_email(email["id"])
            print(f"  Trashed: {email['subject']}")
        except Exception as e:
            print(f"  Failed to trash '{email['subject']}': {e}")
    print()


def _action_add_deadlines(digest):
    """Add all detected deadlines to calendar."""
    deadlines = digest["deadlines"]
    if not deadlines:
        print("  No deadlines detected.\n")
        return

    print(f"  Adding {len(deadlines)} deadline(s) to calendar...")
    for d in deadlines:
        try:
            created = create_event_from_deadline(d["subject"], d["deadline"])
            print(f"  Created: {created.get('summary', 'event')} on {d['deadline']}")
        except Exception as e:
            print(f"  Could not create event for '{d['deadline']}': {e}")
    print()


def _action_auto_reply(number_map):
    """Auto-reply to a specific email from the digest."""
    choice = input("  Enter email number to reply to: ").strip()
    if not choice.isdigit() or int(choice) not in number_map:
        print("  Invalid number.\n")
        return

    email = number_map[int(choice)]
    print(f"\n  Generating reply to: {email['subject']}...")
    reply_body = generate_auto_reply(email["from"], email["subject"], email["body"])

    print(f"\n{'=' * 60}")
    print(f"Reply to: {email['from']}")
    print(f"Subject:  Re: {email['subject']}")
    print(f"{'=' * 60}")
    print(reply_body)
    print(f"{'=' * 60}\n")

    confirm = input("  Send this reply? (Y/N): ").strip().upper()
    if confirm == "Y":
        from gmail_service import send_reply
        sender = email["from"]
        if "<" in sender:
            sender = sender.split("<")[1].rstrip(">")
        try:
            result = send_reply(
                email["id"], sender, email["subject"],
                reply_body, email["threadId"]
            )
            print(f"  Reply sent! Message ID: {result['id']}\n")
        except Exception as e:
            print(f"  Failed to send reply: {e}\n")
    else:
        print("  Reply discarded.\n")


# ── Main entry point ──────────────────────────────────────────────────────────

def run_triage():
    """Run the full Smart Triage pipeline: fetch -> score -> digest -> actions."""
    count = input("How many unread emails to triage? [50]: ").strip()
    try:
        max_results = int(count) if count else 50
    except ValueError:
        print("Invalid number, using default of 50.")
        max_results = 50

    print(f"\nFetching up to {max_results} unread emails...")
    emails = fetch_unread_emails(max_results)

    if not emails:
        print("No unread emails found.\n")
        return

    print(f"Found {len(emails)} email(s). Running triage")

    # Load rules
    rules, default_category = load_rules()
    categories = list({r.get("category") for r in rules if r.get("category")})
    if not categories:
        categories = None

    # Score each email with progress indicator
    scored = []
    for i, email in enumerate(emails, 1):
        print(f"  Analyzing {i}/{len(emails)}: {email['subject'][:40]}...", end="\r")
        try:
            result = score_email(email, rules, default_category, categories)
            scored.append(result)
        except Exception as e:
            logger.warning("Failed to score email %s: %s", email.get("id"), e)
            print(f"\n  Warning: Could not analyze '{email['subject']}': {e}")
            # Include with defaults so partial results still show
            scored.append({
                **email,
                "priority": "LOW",
                "category": default_category,
                "summary": "(analysis failed)",
                "action_required": False,
                "mentions_user": False,
                "deadlines": [],
            })

    print()  # Clear progress line

    # Build and display digest
    digest = build_digest(scored)
    digest_text, number_map = format_digest(digest)
    print(digest_text)

    # Action loop
    while True:
        print("Actions:")
        print("  [R]  Read an email (enter number)")
        print("  [T]  Trash emails (by number)")
        print("  [TL] Trash all LOW priority emails")
        print("  [A]  Auto-reply to an email")
        print("  [D]  Add deadlines to calendar")
        print("  [Q]  Back to main menu")

        action = input("\n> ").strip().upper()

        if action == "Q":
            break
        elif action == "R":
            _action_read(number_map)
        elif action == "T":
            _action_trash_specific(number_map)
        elif action == "TL":
            _action_trash_all_low(number_map, digest)
        elif action == "A":
            _action_auto_reply(number_map)
        elif action == "D":
            _action_add_deadlines(digest)
        else:
            print("  Invalid action.\n")
