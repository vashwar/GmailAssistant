"""Tests for digest building and formatting."""

import pytest

from triage_engine import build_digest, format_digest


def _make_email(priority="LOW", subject="Test", sender="a@b.com",
                deadlines=None, attachments=None, summary="A summary",
                action_required=False, mentions_user=False):
    """Helper: create a scored email dict."""
    return {
        "id": f"msg-{subject}",
        "threadId": "thread-1",
        "subject": subject,
        "from": sender,
        "to": "me@x.com",
        "date": "2026-03-28",
        "body": "Email body text",
        "priority": priority,
        "category": "general",
        "summary": summary,
        "action_required": action_required,
        "mentions_user": mentions_user,
        "deadlines": deadlines or [],
        "attachments": attachments or [],
    }


# ── build_digest tests ───────────────────────────────────────────────────────


def test_build_digest_groups_by_priority():
    """Emails are grouped into HIGH/MEDIUM/LOW buckets."""
    emails = [
        _make_email(priority="HIGH", subject="Urgent"),
        _make_email(priority="LOW", subject="Newsletter"),
        _make_email(priority="MEDIUM", subject="FYI"),
        _make_email(priority="HIGH", subject="Action needed"),
    ]
    digest = build_digest(emails)
    assert len(digest["groups"]["HIGH"]) == 2
    assert len(digest["groups"]["MEDIUM"]) == 1
    assert len(digest["groups"]["LOW"]) == 1
    assert digest["total"] == 4


def test_build_digest_collects_deadlines():
    """Deadlines from all emails are aggregated."""
    emails = [
        _make_email(deadlines=["March 31"]),
        _make_email(deadlines=["April 2", "April 5"]),
        _make_email(deadlines=[]),
    ]
    digest = build_digest(emails)
    assert len(digest["deadlines"]) == 3


def test_build_digest_collects_attachments():
    """Attachments from all emails are aggregated."""
    emails = [
        _make_email(attachments=[{"filename": "a.pdf", "size": 100, "mime_type": "application/pdf", "part_id": ""}]),
        _make_email(attachments=[
            {"filename": "b.xlsx", "size": 200, "mime_type": "application/xlsx", "part_id": ""},
            {"filename": "c.doc", "size": 300, "mime_type": "application/doc", "part_id": ""},
        ]),
    ]
    digest = build_digest(emails)
    assert len(digest["attachments"]) == 3


def test_build_digest_empty_inbox():
    """Empty email list produces empty digest."""
    digest = build_digest([])
    assert digest["total"] == 0
    assert digest["groups"]["HIGH"] == []
    assert digest["deadlines"] == []
    assert digest["attachments"] == []


# ── format_digest tests ──────────────────────────────────────────────────────


def test_format_digest_contains_briefing_header():
    """Formatted digest contains the INBOX BRIEFING header."""
    emails = [_make_email(priority="HIGH", subject="Important")]
    digest = build_digest(emails)
    text, number_map = format_digest(digest)
    assert "INBOX BRIEFING" in text


def test_format_digest_number_map():
    """Number map correctly indexes emails by display number."""
    emails = [
        _make_email(priority="HIGH", subject="First"),
        _make_email(priority="LOW", subject="Second"),
    ]
    digest = build_digest(emails)
    _, number_map = format_digest(digest)
    assert 1 in number_map
    assert 2 in number_map
    assert number_map[1]["subject"] == "First"
    assert number_map[2]["subject"] == "Second"


def test_format_digest_truncates_long_subjects():
    """Subjects longer than 50 chars are truncated in display."""
    long_subject = "A" * 60
    emails = [_make_email(priority="HIGH", subject=long_subject)]
    digest = build_digest(emails)
    text, _ = format_digest(digest)
    # The full 60-char subject should NOT appear; truncated version should
    assert long_subject not in text
    assert "A" * 47 + "..." in text


def test_format_digest_shows_deadlines_section():
    """Deadlines section appears when deadlines exist."""
    emails = [_make_email(deadlines=["April 2"], subject="Budget Review", sender="boss@co.com")]
    digest = build_digest(emails)
    text, _ = format_digest(digest)
    assert "DEADLINES DETECTED" in text
    assert "April 2" in text


def test_format_digest_shows_attachments_section():
    """Attachments section appears when attachments exist."""
    emails = [_make_email(attachments=[{"filename": "report.pdf", "size": 1024, "mime_type": "application/pdf", "part_id": ""}])]
    digest = build_digest(emails)
    text, _ = format_digest(digest)
    assert "ATTACHMENTS" in text
    assert "report.pdf" in text


def test_format_digest_shows_action_required():
    """Action required flag is displayed."""
    emails = [_make_email(priority="HIGH", action_required=True)]
    digest = build_digest(emails)
    text, _ = format_digest(digest)
    assert "Action required" in text


def test_format_digest_empty_digest():
    """Empty digest still renders without errors."""
    digest = build_digest([])
    text, number_map = format_digest(digest)
    assert "INBOX BRIEFING" in text
    assert "0 unread" in text
    assert len(number_map) == 0
