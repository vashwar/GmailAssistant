import base64
import re
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from auth import get_gmail_service


def _decode_base64url(data):
    """Decode base64url-encoded data to a UTF-8 string."""
    padded = data + "=" * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _format_size(size_bytes):
    """Convert byte count to human-readable string (e.g. 1.2 MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def _walk_payload(payload):
    """Single-pass MIME tree walk extracting body text and attachment metadata.

    Returns (body_text, attachments) where:
        body_text: str or None — plain text preferred, HTML fallback stripped via BeautifulSoup
        attachments: list of dicts with {filename, size, mime_type, part_id}
    """
    plain_text = None
    html_text = None
    attachments = []

    def _walk(part):
        nonlocal plain_text, html_text
        mime = part.get("mimeType", "")

        # Recurse into multipart containers
        if "parts" in part:
            for sub in part["parts"]:
                _walk(sub)
            return

        # Check for attachment (has filename in headers or disposition)
        filename = part.get("filename", "")
        if not filename:
            # Check Content-Disposition header for filename
            for header in part.get("headers", []):
                if header["name"].lower() == "content-disposition" and "filename" in header["value"]:
                    # Extract filename from header
                    match = re.search(r'filename="?([^";]+)"?', header["value"])
                    if match:
                        filename = match.group(1)
                    break

        if filename:
            body_meta = part.get("body", {})
            attachments.append({
                "filename": filename,
                "size": body_meta.get("size", 0),
                "mime_type": mime,
                "part_id": body_meta.get("attachmentId", ""),
            })
            return

        # Extract body text from leaf parts
        body_data = part.get("body", {}).get("data", "")
        if not body_data:
            return

        decoded = _decode_base64url(body_data)
        if mime == "text/plain" and plain_text is None:
            plain_text = decoded
        elif mime == "text/html" and html_text is None:
            html_text = decoded

    _walk(payload)

    # Prefer plain text; fall back to stripped HTML
    if plain_text:
        body = plain_text
    elif html_text:
        soup = BeautifulSoup(html_text, "html.parser")
        body = soup.get_text(separator="\n", strip=True)
    else:
        body = None

    return body, attachments


def _parse_message(msg):
    """Parse a full Gmail message into a clean dict including attachments."""
    headers = msg.get("payload", {}).get("headers", [])
    header_map = {h["name"].lower(): h["value"] for h in headers}

    body, attachments = _walk_payload(msg.get("payload", {}))

    return {
        "id": msg["id"],
        "threadId": msg.get("threadId", ""),
        "subject": header_map.get("subject", "(no subject)"),
        "from": header_map.get("from", "(unknown sender)"),
        "to": header_map.get("to", ""),
        "date": header_map.get("date", ""),
        "body": body or "(no body)",
        "attachments": attachments,
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


def search_contacts(query, max_results=20):
    """Search sent and received emails to find contacts matching a name or email.

    Returns a deduplicated list of dicts: [{"name": ..., "email": ...}, ...]
    """
    service = get_gmail_service()

    # Search both sent and received emails for the query
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    if not messages:
        return []

    seen_emails = set()
    contacts = []

    for msg_stub in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_stub["id"], format="metadata",
            metadataHeaders=["From", "To", "Cc"]
        ).execute()

        headers = msg.get("payload", {}).get("headers", [])
        for h in headers:
            if h["name"] in ("From", "To", "Cc"):
                # Parse "Name <email>" or just "email" patterns
                for addr in h["value"].split(","):
                    addr = addr.strip()
                    match = re.match(r'"?([^"<]*)"?\s*<([^>]+)>', addr)
                    if match:
                        name = match.group(1).strip().strip('"')
                        email = match.group(2).strip().lower()
                    elif "@" in addr:
                        name = ""
                        email = addr.strip().lower()
                    else:
                        continue

                    if email not in seen_emails and query.lower() in (name + " " + email).lower():
                        seen_emails.add(email)
                        contacts.append({"name": name, "email": email})

    return contacts


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


def mark_as_read(msg_id):
    """Mark an email as read by removing the UNREAD label."""
    service = get_gmail_service()
    service.users().messages().modify(
        userId="me", id=msg_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def trash_email(msg_id):
    """Move an email to Trash."""
    service = get_gmail_service()
    service.users().messages().trash(userId="me", id=msg_id).execute()


def get_or_create_label(label_name):
    """Get a Gmail label ID by name, creating it if it doesn't exist.

    Returns the label ID string.
    """
    service = get_gmail_service()
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        if label["name"].lower() == label_name.lower():
            return label["id"]

    # Create the label
    body = {
        "name": label_name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }
    created = service.users().labels().create(userId="me", body=body).execute()
    return created["id"]


def apply_label(msg_id, label_id):
    """Apply a label to a Gmail message."""
    service = get_gmail_service()
    service.users().messages().modify(
        userId="me", id=msg_id,
        body={"addLabelIds": [label_id]},
    ).execute()


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
