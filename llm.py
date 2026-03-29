import json
import re
import time
import logging
from datetime import datetime
from functools import wraps
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from config import GOOGLE_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

# Configure Gemini
genai.configure(api_key=GOOGLE_API_KEY)
_model = genai.GenerativeModel(GEMINI_MODEL)


def retry_with_backoff(max_retries=3, base_delay=1.0, backoff_multiplier=2.0):
    """Decorator that retries a function on transient API failures with exponential backoff.

    Retryable: ResourceExhausted (429), ServiceUnavailable (503), ConnectionError, TimeoutError.
    All other exceptions are raised immediately.
    """
    retryable = (ResourceExhausted, ServiceUnavailable, ConnectionError, TimeoutError)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable as e:
                    if attempt == max_retries:
                        logger.error("All %d retries exhausted for %s: %s", max_retries, func.__name__, e)
                        raise
                    logger.warning("Retry %d/%d for %s after %s: %.1fs backoff",
                                   attempt + 1, max_retries, func.__name__, type(e).__name__, delay)
                    time.sleep(delay)
                    delay *= backoff_multiplier
        return wrapper
    return decorator


@retry_with_backoff()
def _generate(prompt):
    """Wrapper around model.generate_content with retry logic."""
    return _model.generate_content(prompt)


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

    response = _generate(prompt)
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


def triage_email(sender, subject, body, user_name="Vashwar", categories=None):
    """Triage an email with priority scoring, categorization, and action detection.

    Returns a dict with:
        summary (str), mentions_user (bool), urgency (str),
        category (str), action_required (bool), deadlines (list[str])
    """
    truncated_body = body[:4000] if len(body) > 4000 else body

    if categories:
        cat_instruction = f'- "category": one of {json.dumps(categories)}'
    else:
        cat_instruction = '- "category": a short label that best describes this email (e.g. "work", "newsletter", "finance")'

    prompt = f"""Analyze this email and return a JSON object with exactly these keys:
- "summary": a concise 1-2 sentence summary
- "mentions_user": true if the email specifically mentions or addresses "{user_name}" by name, false otherwise
- "urgency": one of "high", "medium", or "low"
{cat_instruction}
- "action_required": true if this email requires a response or action from the recipient, false otherwise
- "deadlines": a list of deadline strings found in the email (empty list if none)

Do NOT invent dates, names, or deadlines that are not explicitly in the email.

Email details:
From: {sender}
Subject: {subject}
Body:
{truncated_body}

Return ONLY the JSON object, no other text."""

    response = _generate(prompt)
    result = _parse_json_response(response.text)

    if result is None:
        return {
            "summary": response.text.strip()[:200],
            "mentions_user": False,
            "urgency": "low",
            "category": "uncategorized",
            "action_required": False,
            "deadlines": [],
        }

    return {
        "summary": result.get("summary", "No summary available"),
        "mentions_user": result.get("mentions_user", False),
        "urgency": result.get("urgency", "low").lower(),
        "category": result.get("category", "uncategorized"),
        "action_required": result.get("action_required", False),
        "deadlines": result.get("deadlines", []),
    }


def refine_draft(rough_text, recipient, subject, tone="Professional"):
    """Refine a rough draft into a professional email.

    Returns a dict with 'subject' (refined) and 'body' (refined).
    """
    prompt = f"""You are an expert executive assistant and professional copywriter. Your task is to take a rough draft or bullet points and transform them into a polished, clear, and highly effective email.

Here are your strict guidelines:
1. Maintain the Core Message: Do not alter the fundamental meaning, intent, or facts of the original draft.
2. No Hallucinations: NEVER invent dates, metrics, names, or commitments that are not explicitly provided in the rough draft. If information seems missing, leave it out or use a placeholder like [Insert Date].
3. Be Concise: Respect the recipient's time. Eliminate fluff, repetitive phrasing, and unnecessary pleasantries. Get straight to the point.
4. Tone: Adjust the writing to match the requested tone: {tone}.
5. Grammar & Flow: Fix all typos, grammatical errors, and awkward phrasing. Ensure smooth transitions between ideas.

Please refine the following draft AND improve the subject line:

Original Subject: {subject}
Requested Tone: {tone}
Rough Draft:
{rough_text}

Return a JSON object with exactly two keys:
- "subject": the refined, clear, and concise subject line
- "body": the refined email body text

Return ONLY the JSON object, no other text."""

    response = _generate(prompt)
    result = _parse_json_response(response.text)

    if result and "subject" in result and "body" in result:
        return {"subject": result["subject"], "body": result["body"]}

    # Fallback: return raw text as body with original subject
    return {"subject": subject, "body": response.text.strip()}


def revise_draft(current_subject, current_body, feedback, tone="Professional"):
    """Revise an already-refined email based on user feedback.

    Returns a dict with 'subject' and 'body'.
    """
    prompt = f"""You are an expert executive assistant and professional copywriter. A user has reviewed a refined email draft and wants changes.

Apply the user's feedback to revise the email. Follow these rules:
1. Only change what the feedback asks for — keep everything else intact.
2. No Hallucinations: NEVER invent dates, metrics, names, or commitments not in the current draft or feedback.
3. Maintain the requested tone: {tone}.

Current Subject: {current_subject}
Current Body:
{current_body}

User Feedback: {feedback}

Return a JSON object with exactly two keys:
- "subject": the revised subject line
- "body": the revised email body text

Return ONLY the JSON object, no other text."""

    response = _generate(prompt)
    result = _parse_json_response(response.text)

    if result and "subject" in result and "body" in result:
        return {"subject": result["subject"], "body": result["body"]}

    return {"subject": current_subject, "body": response.text.strip()}


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

    response = _generate(prompt)
    return response.text.strip()


def parse_meeting_request(natural_language):
    """Parse a natural language meeting request into structured data.

    Returns a dict with:
        summary (str), start (str), end (str), attendees (list[str])
    """
    today = datetime.now().strftime("%Y-%m-%d %A")

    prompt = f"""Parse this meeting request into a JSON object with these keys:
- "summary": the meeting title/description
- "start": start datetime in ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
- "end": end datetime in ISO 8601 format (default to 1 hour after start if not specified)
- "attendees": list of email addresses mentioned (empty list if none)

Today is {today}. Use this as reference for relative dates like "next Tuesday", "tomorrow", etc.

Meeting request: {natural_language}

Return ONLY the JSON object, no other text."""

    response = _generate(prompt)
    result = _parse_json_response(response.text)

    if result is None:
        return None

    return {
        "summary": result.get("summary", "Meeting"),
        "start": result.get("start", ""),
        "end": result.get("end", ""),
        "attendees": result.get("attendees", []),
    }
