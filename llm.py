import json
import re
import google.generativeai as genai
from config import GOOGLE_API_KEY, GEMINI_MODEL

# Configure Gemini
genai.configure(api_key=GOOGLE_API_KEY)
_model = genai.GenerativeModel(GEMINI_MODEL)


def _parse_json_response(text):
    """Extract JSON from a Gemini response, handling markdown fences."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def summarize_email(sender, subject, body, user_name="Vashwar"):
    """Summarize an email and extract key information.

    Returns a dict with:
        summary (str), mentions_user (bool), urgency (str), deadlines (list[str])
    """
    # Truncate very long bodies to avoid token limits
    truncated_body = body[:4000] if len(body) > 4000 else body

    prompt = f"""Analyze this email and return a JSON object with exactly these keys:
- "summary": a concise 1-2 sentence summary
- "mentions_user": true if the email specifically mentions or addresses "{user_name}" by name, false otherwise
- "urgency": one of "high", "medium", or "low"
- "deadlines": a list of deadline strings found in the email (empty list if none)

Email details:
From: {sender}
Subject: {subject}
Body:
{truncated_body}

Return ONLY the JSON object, no other text."""

    response = _model.generate_content(prompt)
    result = _parse_json_response(response.text)

    if result is None:
        return {
            "summary": response.text.strip()[:200],
            "mentions_user": False,
            "urgency": "low",
            "deadlines": [],
        }

    return {
        "summary": result.get("summary", "No summary available"),
        "mentions_user": result.get("mentions_user", False),
        "urgency": result.get("urgency", "low"),
        "deadlines": result.get("deadlines", []),
    }


def refine_draft(rough_text, recipient, subject):
    """Refine a rough draft into a professional email.

    Returns the polished email body as a string.
    """
    prompt = f"""You are an email drafting assistant. Take the rough draft below and refine it
into a professional, well-formatted email. Keep the original intent and key points.
Adjust the tone to be professional yet friendly. Do not add a subject line.

Recipient: {recipient}
Subject: {subject}
Rough draft:
{rough_text}

Return ONLY the refined email body text, ready to send. No extra commentary."""

    response = _model.generate_content(prompt)
    return response.text.strip()


def generate_auto_reply(sender, subject, body):
    """Generate an appropriate auto-reply to an email.

    Returns the reply body as a string.
    """
    truncated_body = body[:4000] if len(body) > 4000 else body

    prompt = f"""You are an email assistant. Generate a brief, professional reply to this email.
The reply should acknowledge the email and provide an appropriate response.

From: {sender}
Subject: {subject}
Body:
{truncated_body}

Return ONLY the reply body text, ready to send. No extra commentary."""

    response = _model.generate_content(prompt)
    return response.text.strip()
