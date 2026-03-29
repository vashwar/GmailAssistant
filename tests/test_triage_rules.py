"""Tests for triage rule loading, matching, and precedence."""

import os
import tempfile

import pytest
import yaml

from unittest.mock import patch, MagicMock
from triage_engine import load_rules, match_rule, categorize_email, score_email


def _write_rules(tmp_path, data):
    """Helper: write a YAML rules file and return the path."""
    path = os.path.join(tmp_path, "rules.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return path


# ── Loading tests ─────────────────────────────────────────────────────────────


def test_load_rules_missing_file():
    """Missing file returns empty rules and default category."""
    rules, default = load_rules("/nonexistent/rules.yaml")
    assert rules == []
    assert default == "general"


def test_load_rules_valid_yaml(tmp_path):
    """Valid YAML parses correctly."""
    data = {
        "rules": [
            {"match": {"from": "boss@co.com"}, "priority": "HIGH", "category": "management"},
            {"match": {"subject_contains": "invoice"}, "priority": "MEDIUM", "category": "finance"},
        ],
        "default_category": "inbox",
    }
    path = _write_rules(str(tmp_path), data)
    rules, default = load_rules(path)
    assert len(rules) == 2
    assert default == "inbox"


def test_load_rules_malformed_yaml(tmp_path):
    """Malformed YAML returns empty rules gracefully."""
    path = os.path.join(str(tmp_path), "bad.yaml")
    with open(path, "w") as f:
        f.write(": : : not valid yaml [[[")
    rules, default = load_rules(path)
    assert rules == []
    assert default == "general"


def test_load_rules_non_dict_root(tmp_path):
    """YAML that parses to a non-dict returns empty rules."""
    path = os.path.join(str(tmp_path), "list.yaml")
    with open(path, "w") as f:
        f.write("- item1\n- item2\n")
    rules, default = load_rules(path)
    assert rules == []
    assert default == "general"


def test_load_rules_empty_rules_list(tmp_path):
    """YAML with empty rules list works."""
    data = {"rules": [], "default_category": "misc"}
    path = _write_rules(str(tmp_path), data)
    rules, default = load_rules(path)
    assert rules == []
    assert default == "misc"


def test_load_rules_auto_sorts_by_specificity(tmp_path):
    """Rules are auto-sorted: sender > subject > keyword."""
    data = {
        "rules": [
            {"match": {"keyword": "deadline"}, "priority": "HIGH"},
            {"match": {"from": "vip@co.com"}, "priority": "HIGH"},
            {"match": {"subject_contains": "urgent"}, "priority": "HIGH"},
        ],
    }
    path = _write_rules(str(tmp_path), data)
    rules, _ = load_rules(path)
    # sender first, then subject, then keyword
    assert "from" in rules[0]["match"]
    assert "subject_contains" in rules[1]["match"]
    assert "keyword" in rules[2]["match"]


# ── Matching tests ────────────────────────────────────────────────────────────


def test_match_rule_sender_exact():
    """Exact sender match works."""
    rules = [{"match": {"from": "boss@company.com"}, "priority": "HIGH", "category": "mgmt"}]
    email = {"from": "Boss <boss@company.com>", "subject": "Hello", "body": "Hi"}
    priority, category = match_rule(email, rules)
    assert priority == "HIGH"
    assert category == "mgmt"


def test_match_rule_sender_glob():
    """Glob pattern sender match works."""
    rules = [{"match": {"from": "*@newsletter.example.com"}, "priority": "LOW", "category": "newsletters"}]
    email = {"from": "news@newsletter.example.com", "subject": "Weekly digest", "body": ""}
    priority, category = match_rule(email, rules)
    assert priority == "LOW"
    assert category == "newsletters"


def test_match_rule_subject_contains():
    """Subject substring match is case-insensitive."""
    rules = [{"match": {"subject_contains": "URGENT"}, "priority": "HIGH"}]
    email = {"from": "someone@x.com", "subject": "This is urgent please read", "body": ""}
    priority, category = match_rule(email, rules)
    assert priority == "HIGH"


def test_match_rule_keyword_in_body():
    """Keyword match searches subject + first 500 chars of body."""
    rules = [{"match": {"keyword": "deadline"}, "priority": "HIGH"}]
    email = {"from": "a@b.com", "subject": "FYI", "body": "The deadline is March 30 " + "x" * 600}
    priority, _ = match_rule(email, rules)
    assert priority == "HIGH"


def test_match_rule_keyword_beyond_500_chars():
    """Keyword beyond 500 chars of body is NOT matched."""
    rules = [{"match": {"keyword": "deadline"}, "priority": "HIGH"}]
    email = {"from": "a@b.com", "subject": "FYI", "body": "x" * 510 + "deadline"}
    priority, _ = match_rule(email, rules)
    assert priority is None


def test_match_rule_no_match():
    """No matching rule returns None, None."""
    rules = [{"match": {"from": "specific@domain.com"}, "priority": "HIGH"}]
    email = {"from": "other@domain.com", "subject": "Hello", "body": "World"}
    priority, category = match_rule(email, rules)
    assert priority is None
    assert category is None


# ── categorize_email tests ───────────────────────────────────────────────────

SAMPLE_CATEGORIES = {
    "Jobs": ["linkedin", "recruiter", "job"],
    "Family": ["rashna9@gmail.com", "harun.rashid68@yahoo.com"],
    "Bills": ["pg&e", "invoice", "payment due"],
    "Academic": ["haas", ".edu", "university"],
}


def test_categorize_sender_keyword():
    """Keyword in sender matches the category."""
    email = {"from": "notifications@linkedin.com", "subject": "New connection"}
    assert categorize_email(email, SAMPLE_CATEGORIES) == "Jobs"


def test_categorize_sender_exact_email():
    """Exact email address in sender matches (Family)."""
    email = {"from": "Rashna <rashna9@gmail.com>", "subject": "Hello"}
    assert categorize_email(email, SAMPLE_CATEGORIES) == "Family"


def test_categorize_subject_keyword():
    """Keyword in subject matches."""
    email = {"from": "noreply@example.com", "subject": "Your invoice is ready"}
    assert categorize_email(email, SAMPLE_CATEGORIES) == "Bills"


def test_categorize_case_insensitive():
    """Matching is case-insensitive."""
    email = {"from": "admin@LINKEDIN.com", "subject": "RECRUITER reached out"}
    assert categorize_email(email, SAMPLE_CATEGORIES) == "Jobs"


def test_categorize_no_match_returns_misc():
    """No keyword match returns 'Misc'."""
    email = {"from": "random@unknown.com", "subject": "Random stuff"}
    assert categorize_email(email, SAMPLE_CATEGORIES) == "Misc"


def test_categorize_empty_categories():
    """Empty categories dict returns 'Misc'."""
    email = {"from": "a@b.com", "subject": "Hello"}
    assert categorize_email(email, {}) == "Misc"


def test_categorize_none_categories_uses_default():
    """None categories falls back to default EMAIL_CATEGORIES."""
    email = {"from": "notifications@linkedin.com", "subject": "New job"}
    result = categorize_email(email, None)
    assert result == "Jobs"


def test_categorize_edu_in_sender():
    """'.edu' keyword matches university senders."""
    email = {"from": "registrar@berkeley.edu", "subject": "Enrollment"}
    assert categorize_email(email, SAMPLE_CATEGORIES) == "Academic"


# ── score_email LLM category normalization ───────────────────────────────────


@patch("triage_engine.triage_email")
def test_score_email_normalizes_list_category(mock_triage):
    """LLM returning a list for category is normalized to a string."""
    mock_triage.return_value = {
        "summary": "Test",
        "mentions_user": False,
        "urgency": "low",
        "category": ["work", "finance"],
        "action_required": False,
        "deadlines": [],
    }
    email = {"from": "random@unknown.com", "subject": "Random", "body": "text",
             "id": "1", "threadId": "t1"}
    result = score_email(email, rules=[], default_category="general")
    assert isinstance(result["category"], str)
    assert result["category"] == "work"


@patch("triage_engine.triage_email")
def test_score_email_normalizes_empty_list_category(mock_triage):
    """LLM returning an empty list falls back to default category."""
    mock_triage.return_value = {
        "summary": "Test",
        "mentions_user": False,
        "urgency": "low",
        "category": [],
        "action_required": False,
        "deadlines": [],
    }
    email = {"from": "random@unknown.com", "subject": "Random", "body": "text",
             "id": "1", "threadId": "t1"}
    result = score_email(email, rules=[], default_category="general")
    assert result["category"] == "general"
