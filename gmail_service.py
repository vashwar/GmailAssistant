import base64
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from auth import get_gmail_service


def _decode_base64url(data):
    """Decode base64url-encoded data to a UTF-8 string."""
    padded = data + "=" * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_body(payload):
    """Recursively walk MIME parts to extract the email body.
    Prefers text/plain; falls back to text/html stripped via BeautifulSoup.
    """
    plain_text = None
    html_text = None

    if "parts" in payload:
        for part in payload["parts"]:
            result = _extract_body(part)
            if result:
                # Keep looking for plain text, but save html as fallback
                mime = part.get("mimeType", "")
                if mime == "text/plain" or (not plain_text and "plain" not in str(result)):
                    if mime == "text/plain":
                        plain_text = result
                    elif mime == "text/html":
                        html_text = result
                    elif plain_text is None:
                        plain_text = result
        return plain_text or html_text
    else:
        mime = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")
        if not body_data:
            return None
        decoded = _decode_base64url(body_data)
        if mime == "text/plain":
            return decoded
        elif mime == "text/html":
            soup = BeautifulSoup(decoded, "html.parser")
            return soup.get_text(separator="\n", strip=True)
        return decoded


def _parse_message(msg):
    """Parse a full Gmail message into a clean dict."""
    headers = msg.get("payload", {}).get("headers", [])
    header_map = {h["name"].lower(): h["value"] for h in headers}

    body = _extract_body(msg.get("payload", {})) or "(no body)"

    return {
        "id": msg["id"],
        "threadId": msg.get("threadId", ""),
        "subject": header_map.get("subject", "(no subject)"),
        "from": header_map.get("from", "(unknown sender)"),
        "to": header_map.get("to", ""),
        "date": header_map.get("date", ""),
        "body": body,
    }


def fetch_unread_emails(max_results=10):
    """Fetch unread emails from the inbox."""
    service = get_gmail_service()
    results = service.users().messages().list(
        userId="me", q="is:unread", maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        return []

    parsed = []
    for msg_stub in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_stub["id"], format="full"
        ).execute()
        parsed.append(_parse_message(msg))

    return parsed


def search_emails(query, max_results=10):
    """Search emails using Gmail search operators."""
    service = get_gmail_service()
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        return []

    parsed = []
    for msg_stub in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_stub["id"], format="full"
        ).execute()
        parsed.append(_parse_message(msg))

    return parsed


def get_email_by_id(msg_id):
    """Fetch and parse a single email by its message ID."""
    service = get_gmail_service()
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()
    return _parse_message(msg)


def send_email(to, subject, body):
    """Compose and send a new email."""
    service = get_gmail_service()
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return sent


def send_reply(original_msg_id, to, subject, body, thread_id):
    """Send a reply to an existing email thread."""
    service = get_gmail_service()

    # Fetch original message for In-Reply-To header
    original = service.users().messages().get(
        userId="me", id=original_msg_id, format="metadata",
        metadataHeaders=["Message-ID"]
    ).execute()
    headers = original.get("payload", {}).get("headers", [])
    original_message_id = ""
    for h in headers:
        if h["name"].lower() == "message-id":
            original_message_id = h["value"]
            break

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if original_message_id:
        message["In-Reply-To"] = original_message_id
        message["References"] = original_message_id

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": thread_id}
    ).execute()
    return sent
