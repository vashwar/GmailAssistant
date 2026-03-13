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
