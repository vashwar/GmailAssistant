import os
import fnmatch
import logging
from datetime import datetime

import yaml

from config import USER_NAME, TIMEZONE, EMAIL_CATEGORIES
from gmail_service import fetch_unread_emails, trash_email, _format_size, get_or_create_label, apply_label
from llm import triage_email, generate_auto_reply, categorize_email_llm
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


# ── Keyword-based categorization ─────────────────────────────────────────────

def categorize_email(email, categories=None):
    """Categorize an email by matching sender and subject against keyword lists.

    Checks sender first (exact email matches and keyword substrings), then subject.
    Returns the category name or "Misc" if no match.
    """
    if not categories:
        categories = EMAIL_CATEGORIES
    if not categories:
        return "Misc"

    sender = email.get("from", "").lower()
    subject = email.get("subject", "").lower()

    for category, keywords in categories.items():
        for keyword in keywords:
            kw = keyword.lower()
            if kw in sender or kw in subject:
                return category

    return "Misc"


# ── Scoring pipeline ──────────────────────────────────────────────────────────

def score_email(email, rules, default_category="general", categories=None):
    """Two-phase scoring: deterministic rules first, LLM fallback.

    Category precedence: rule_category > keyword_category > llm_category > default.

    Returns a scored dict augmenting the original email with triage fields.
    """
    rule_priority, rule_category = match_rule(email, rules)

    # Keyword-based categorization from EMAIL_CATEGORIES
    keyword_category = categorize_email(email)

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

    # Category precedence: rule > keyword > LLM > default
    if rule_category:
        category = rule_category
    elif keyword_category != "Misc":
        category = keyword_category
    else:
        llm_category = llm_result.get("category", default_category)
        # LLM may return a list — normalize to string
        if isinstance(llm_category, list):
            category = llm_category[0] if llm_category else default_category
        else:
            category = llm_category

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

            cat = email.get("category", "")
            if cat:
                lines.append(f"     Category: {cat}")
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


def format_category_view(scored_emails):
    """Render scored emails grouped by category."""
    # Group by category
    cat_groups = {}
    for email in scored_emails:
        cat = email.get("category", "Misc")
        cat_groups.setdefault(cat, []).append(email)

    # Sort categories alphabetically, but "Misc" last
    sorted_cats = sorted(cat_groups.keys(), key=lambda c: (c == "Misc", c))

    lines = []
    lines.append("")
    lines.append("=" * 62)
    lines.append(f"  INBOX BY CATEGORY  —  {len(scored_emails)} emails in {len(cat_groups)} categories")
    lines.append("=" * 62)

    for cat in sorted_cats:
        emails = cat_groups[cat]
        lines.append("")
        lines.append(f"  [{cat}] ({len(emails)})")
        lines.append(f"  {'─' * 40}")

        for email in emails:
            subj = email.get("subject", "(no subject)")
            if len(subj) > 50:
                subj = subj[:47] + "..."
            sender = email.get("from", "")
            pri = email.get("priority", "LOW")
            lines.append(f"    {pri:<6} {sender}")
            lines.append(f"           {subj}")

    lines.append("")
    lines.append("=" * 62)

    return "\n".join(lines)


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
    """Let the user pick which detected deadlines to add to calendar."""
    deadlines = digest["deadlines"]
    if not deadlines:
        print("  No deadlines detected.\n")
        return

    print(f"\n  Detected {len(deadlines)} deadline(s):\n")
    for i, d in enumerate(deadlines, 1):
        print(f"    [{i}] {d['deadline']} — {d['subject']} (from {d['from']})")

    print(f"\n  Enter deadline numbers to add (comma-separated, e.g. 1,3)")
    print(f"  or 'A' to add all, or press Enter to cancel:")
    selection = input("  > ").strip()

    if not selection:
        print("  Cancelled.\n")
        return

    if selection.upper() == "A":
        selected = deadlines
    else:
        selected = []
        for idx_str in selection.split(","):
            idx_str = idx_str.strip()
            if idx_str.isdigit():
                idx = int(idx_str)
                if 1 <= idx <= len(deadlines):
                    selected.append(deadlines[idx - 1])
                else:
                    print(f"  Invalid number: {idx_str}")
            else:
                print(f"  Invalid input: {idx_str}")

    if not selected:
        print("  No valid deadlines selected.\n")
        return

    print(f"\n  Adding {len(selected)} deadline(s) to calendar...")
    for d in selected:
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


def _print_label_plan(plan):
    """Print the proposed labeling plan grouped by category."""
    cat_groups = {}
    for email, cat in plan:
        cat_groups.setdefault(cat, []).append(email)

    sorted_cats = sorted(cat_groups.keys(), key=lambda c: (c == "Misc", c))
    print(f"\n  Proposed labels for {len(plan)} email(s) across {len(cat_groups)} categories:\n")
    for cat in sorted_cats:
        emails = cat_groups[cat]
        print(f"    [{cat}] ({len(emails)})")
        for email in emails:
            subj = email.get("subject", "(no subject)")
            if len(subj) > 50:
                subj = subj[:47] + "..."
            print(f"      - {email.get('from', '')} — {subj}")
    print()


def _apply_labels(plan):
    """Apply Gmail labels from a confirmed plan. Returns (labeled_count, total)."""
    label_cache = {}
    labeled = 0

    for email, cat in plan:
        try:
            if cat not in label_cache:
                label_cache[cat] = get_or_create_label(cat)
            apply_label(email["id"], label_cache[cat])
            labeled += 1
        except Exception as e:
            print(f"  Failed to label '{email.get('subject', '')}': {e}")

    return labeled, len(plan)


def _action_label_by_category(scored_emails):
    """Label emails by category: keyword-first, LLM with user feedback on rejection."""
    if not scored_emails:
        print("  No emails to label.\n")
        return

    # Phase 1: keyword-only categorization
    plan = []
    for email in scored_emails:
        cat = categorize_email(email)
        plan.append((email, cat))

    all_categories = list(EMAIL_CATEGORIES.keys()) + ["Misc"]

    while True:
        _print_label_plan(plan)

        confirm = input("  Apply these labels? (Y/N): ").strip().upper()
        if confirm == "Y":
            labeled, total = _apply_labels(plan)
            print(f"  Labeled {labeled}/{total} email(s).\n")
            return

        # User rejected — ask for feedback
        print("\n  What should be changed? (e.g. 'move LinkedIn emails to Jobs not Misc',")
        print("  'all shopping receipts should be Online Shopping', etc.)")
        feedback = input("  Feedback (or press Enter to cancel): ").strip()
        if not feedback:
            print("  Cancelled.\n")
            return

        # Re-categorize all emails with LLM using the feedback
        print(f"\n  Re-categorizing {len(plan)} email(s) with AI using your feedback...")
        new_plan = []
        for i, (email, current_cat) in enumerate(plan, 1):
            print(f"    Analyzing {i}/{len(plan)}: {email['subject'][:40]}...", end="\r")
            try:
                llm_cat = categorize_email_llm(
                    email["from"], email["subject"], email["body"],
                    all_categories,
                    feedback=feedback,
                    current_category=current_cat,
                )
                new_plan.append((email, llm_cat))
            except Exception as e:
                logger.warning("LLM categorization failed for %s: %s", email.get("id"), e)
                new_plan.append((email, current_cat))

        print()  # clear progress line
        plan = new_plan


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
        print("  [C]  View by category")
        print("  [L]  Label emails by category")
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
        elif action == "C":
            print(format_category_view(scored))
        elif action == "L":
            _action_label_by_category(scored)
        else:
            print("  Invalid action.\n")
