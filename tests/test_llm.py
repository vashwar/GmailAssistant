"""Tests for LLM functions: JSON parsing, triage_email, retry decorator."""

import json
import time
from unittest.mock import patch, MagicMock

import pytest

from llm import _parse_json_response, triage_email, retry_with_backoff


# ── JSON parsing tests ────────────────────────────────────────────────────────


def test_parse_json_clean():
    """Parse clean JSON string."""
    text = '{"summary": "Test", "urgency": "high"}'
    result = _parse_json_response(text)
    assert result["summary"] == "Test"
    assert result["urgency"] == "high"


def test_parse_json_with_markdown_fences():
    """Parse JSON wrapped in markdown code fences."""
    text = '```json\n{"summary": "Test"}\n```'
    result = _parse_json_response(text)
    assert result["summary"] == "Test"


def test_parse_json_embedded_in_text():
    """Extract JSON embedded in surrounding text."""
    text = 'Here is the result:\n{"key": "value"}\nDone.'
    result = _parse_json_response(text)
    assert result["key"] == "value"


def test_parse_json_invalid():
    """Invalid JSON returns None."""
    result = _parse_json_response("This is not JSON at all")
    assert result is None


def test_parse_json_empty():
    """Empty string returns None."""
    result = _parse_json_response("")
    assert result is None


# ── triage_email tests ────────────────────────────────────────────────────────


@patch("llm._generate")
def test_triage_email_success(mock_generate):
    """triage_email returns all expected fields from LLM."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "summary": "Budget review needed",
        "mentions_user": True,
        "urgency": "high",
        "category": "finance",
        "action_required": True,
        "deadlines": ["April 2"],
    })
    mock_generate.return_value = mock_response

    result = triage_email("boss@co.com", "Q2 Budget", "Please review", categories=["finance", "general"])
    assert result["summary"] == "Budget review needed"
    assert result["urgency"] == "high"
    assert result["category"] == "finance"
    assert result["action_required"] is True
    assert result["deadlines"] == ["April 2"]
    assert result["mentions_user"] is True


@patch("llm._generate")
def test_triage_email_fallback_on_bad_json(mock_generate):
    """triage_email returns defaults when LLM returns garbage."""
    mock_response = MagicMock()
    mock_response.text = "I can't process this email right now sorry"
    mock_generate.return_value = mock_response

    result = triage_email("a@b.com", "Test", "Body")
    assert result["urgency"] == "low"
    assert result["category"] == "uncategorized"
    assert result["action_required"] is False
    assert result["deadlines"] == []


@patch("llm._generate")
def test_triage_email_no_categories(mock_generate):
    """triage_email works without explicit categories (free-form)."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "summary": "Newsletter update",
        "mentions_user": False,
        "urgency": "low",
        "category": "newsletters",
        "action_required": False,
        "deadlines": [],
    })
    mock_generate.return_value = mock_response

    result = triage_email("news@x.com", "Weekly Digest", "Here are updates", categories=None)
    assert result["category"] == "newsletters"


@patch("llm._generate")
def test_triage_email_truncates_long_body(mock_generate):
    """Bodies longer than 4000 chars are truncated."""
    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "summary": "Long email", "mentions_user": False, "urgency": "low",
        "category": "general", "action_required": False, "deadlines": [],
    })
    mock_generate.return_value = mock_response

    long_body = "x" * 10000
    triage_email("a@b.com", "Test", long_body)

    # Verify the prompt sent to LLM has truncated body
    call_args = mock_generate.call_args[0][0]
    assert len(call_args) < 10000  # prompt should be < 10K total


# ── Retry decorator tests ────────────────────────────────────────────────────


def test_retry_succeeds_first_try():
    """Function that succeeds on first call is not retried."""
    call_count = {"n": 0}

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def succeeds():
        call_count["n"] += 1
        return "ok"

    assert succeeds() == "ok"
    assert call_count["n"] == 1


def test_retry_succeeds_after_transient_failure():
    """Function succeeds after a transient ConnectionError."""
    call_count = {"n": 0}

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def fails_then_succeeds():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("transient")
        return "ok"

    assert fails_then_succeeds() == "ok"
    assert call_count["n"] == 2


def test_retry_exhausted_raises():
    """Function that always fails raises after max retries."""
    @retry_with_backoff(max_retries=2, base_delay=0.01)
    def always_fails():
        raise TimeoutError("timeout")

    with pytest.raises(TimeoutError):
        always_fails()


def test_retry_non_retryable_raises_immediately():
    """Non-retryable exceptions are raised without retry."""
    call_count = {"n": 0}

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def raises_value_error():
        call_count["n"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        raises_value_error()
    assert call_count["n"] == 1
