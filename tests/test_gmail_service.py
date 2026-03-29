"""Tests for Gmail service: MIME walking, attachment extraction, size formatting."""

import pytest

from gmail_service import _walk_payload, _format_size, _decode_base64url

import base64


def _b64(text):
    """Encode text as base64url for test payloads."""
    return base64.urlsafe_b64encode(text.encode()).decode()


# ── _format_size tests ────────────────────────────────────────────────────────


def test_format_size_bytes():
    assert _format_size(500) == "500 B"


def test_format_size_kilobytes():
    assert _format_size(1536) == "1.5 KB"


def test_format_size_megabytes():
    assert _format_size(1572864) == "1.5 MB"


def test_format_size_zero():
    assert _format_size(0) == "0 B"


# ── _walk_payload tests ──────────────────────────────────────────────────────


def test_walk_plain_text_only():
    """Single plain text part extracts body, no attachments."""
    payload = {
        "mimeType": "text/plain",
        "body": {"data": _b64("Hello world")},
    }
    body, attachments = _walk_payload(payload)
    assert body == "Hello world"
    assert attachments == []


def test_walk_html_only():
    """Single HTML part is stripped to text."""
    html = "<html><body><p>Hello <b>world</b></p></body></html>"
    payload = {
        "mimeType": "text/html",
        "body": {"data": _b64(html)},
    }
    body, attachments = _walk_payload(payload)
    assert "Hello" in body
    assert "world" in body
    assert "<b>" not in body


def test_walk_multipart_prefers_plain():
    """Multipart with both plain and HTML prefers plain text."""
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("Plain text")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>HTML text</p>")}},
        ],
    }
    body, attachments = _walk_payload(payload)
    assert body == "Plain text"


def test_walk_with_attachment():
    """Attachment parts are collected with metadata."""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("Email body")}},
            {
                "mimeType": "application/pdf",
                "filename": "report.pdf",
                "body": {"size": 45000, "attachmentId": "abc123"},
            },
        ],
    }
    body, attachments = _walk_payload(payload)
    assert body == "Email body"
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "report.pdf"
    assert attachments[0]["size"] == 45000
    assert attachments[0]["mime_type"] == "application/pdf"


def test_walk_multiple_attachments():
    """Multiple attachments are all collected."""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("body")}},
            {"mimeType": "image/png", "filename": "photo.png", "body": {"size": 1000}},
            {"mimeType": "application/zip", "filename": "archive.zip", "body": {"size": 5000}},
        ],
    }
    body, attachments = _walk_payload(payload)
    assert len(attachments) == 2
    filenames = {a["filename"] for a in attachments}
    assert filenames == {"photo.png", "archive.zip"}


def test_walk_nested_multipart():
    """Deeply nested multipart structures are walked correctly."""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _b64("Nested plain")}},
                    {"mimeType": "text/html", "body": {"data": _b64("<p>Nested HTML</p>")}},
                ],
            },
            {"mimeType": "application/pdf", "filename": "nested.pdf", "body": {"size": 100}},
        ],
    }
    body, attachments = _walk_payload(payload)
    assert body == "Nested plain"
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "nested.pdf"


def test_walk_empty_payload():
    """Payload with no body data and no parts returns None body."""
    payload = {"mimeType": "text/plain", "body": {}}
    body, attachments = _walk_payload(payload)
    assert body is None
    assert attachments == []


def test_walk_attachment_via_content_disposition():
    """Attachment detected via Content-Disposition header when filename field is empty."""
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("body")}},
            {
                "mimeType": "application/octet-stream",
                "filename": "",
                "headers": [
                    {"name": "Content-Disposition", "value": 'attachment; filename="data.csv"'},
                ],
                "body": {"size": 2048},
            },
        ],
    }
    body, attachments = _walk_payload(payload)
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "data.csv"
