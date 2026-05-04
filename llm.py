import json
import re
import time
import logging
import threading
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
def _generate(prompt, **kwargs):
    """Wrapper around model.generate_content with retry logic."""
    return _model.generate_content(prompt, **kwargs)


def _parse_json_response(text):
    """Extract JSON from a Gemini response, handling markdown fences."""
    # Strip markdown code fences if present (using character class to avoid UI breakage)
    cleaned = re.sub(r"[`]{3}(?:json)?\s*", "", text)
    cleaned = re.sub(r"[`]{3}\s*", "", cleaned)
    cleaned = cleaned.strip()
    
    # Remove trailing commas from objects and arrays (common in Gemma models)
    cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            extracted = match.group()
            # Run the trailing comma cleanup again on the extracted portion
            extracted = re.sub(r",\s*([\}\]])", r"\1", extracted)
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                pass
    return None


class RateLimiter:
    """Token-bucket rate limiter to keep LLM calls under a max requests-per-minute ceiling."""

    def __init__(self, max_per_minute=15):
        self._interval = 60.0 / max_per_minute  # seconds between requests
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        """Block until the next request is allowed."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._interval:
                sleep_time = self._interval - elapsed
                logger.debug("Rate limiter sleeping %.1fs", sleep_time)
                time.sleep(sleep_time)
            self._last_call = time.monotonic()


# Global rate limiter — shared across all LLM calls in triage batches
_rate_limiter = RateLimiter(max_per_minute=15)


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

    response = _generate(prompt, generation_config={"response_mime_type": "application/json"})
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

    response = _generate(prompt, generation_config={"response_mime_type": "application/json"})
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


def _parse_json_array_response(text):
    """Extract a JSON array from a Gemini response, handling markdown fences."""
    cleaned = re.sub(r"[`]{3}(?:json)?\s*", "", text)
    cleaned = re.sub(r"[`]{3}\s*", "", cleaned)
    cleaned = cleaned.strip()
    cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: find outermost JSON array
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        extracted = re.sub(r",\s*([\}\]])", r"\1", match.group())
        try:
            parsed = json.loads(extracted)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


BATCH_SIZE = 20


def triage_emails_batch(emails, user_name="Vashwar", categories=None):
    """Triage multiple emails in a single LLM call.

    Args:
        emails: List of email dicts, each with 'from', 'subject', 'body' keys.
        user_name: User name for mentions detection.
        categories: Optional list of category names.

    Returns a list of triage result dicts (same keys as triage_email()),
    one per input email in the same order. Falls back to individual
    triage_email() calls if batch parsing fails.
    """
    if not emails:
        return []

    if categories:
        cat_instruction = f'- "category": one of {json.dumps(categories)}'
    else:
        cat_instruction = '- "category": a short label that best describes this email (e.g. "work", "newsletter", "finance")'

    # Build numbered email list
    email_blocks = []
    for idx, email in enumerate(emails, 1):
        body = email.get("body", "")
        truncated_body = body[:4000] if len(body) > 4000 else body
        email_blocks.append(
            f"--- Email {idx} ---\n"
            f"From: {email.get('from', '')}\n"
            f"Subject: {email.get('subject', '')}\n"
            f"Body:\n{truncated_body}"
        )

    emails_text = "\n\n".join(email_blocks)

    prompt = f"""Analyze each of the following {len(emails)} emails and return a JSON **array** of {len(emails)} result objects, one per email in the same order.

Each result object must have exactly these keys:
- "summary": a concise 1-2 sentence summary
- "mentions_user": true if the email specifically mentions or addresses "{user_name}" by name, false otherwise
- "urgency": one of "high", "medium", or "low"
{cat_instruction}
- "action_required": true if this email requires a response or action from the recipient, false otherwise
- "deadlines": a list of deadline strings found in the email (empty list if none)

Do NOT invent dates, names, or deadlines that are not explicitly in the emails.

{emails_text}

Return ONLY the JSON array of {len(emails)} objects, no other text."""

    try:
        response = _generate(prompt, generation_config={"response_mime_type": "application/json"})
        results = _parse_json_array_response(response.text)

        if results is not None and len(results) == len(emails):
            normalized = []
            for r in results:
                if not isinstance(r, dict):
                    raise ValueError("Non-dict entry in batch response")
                normalized.append({
                    "summary": r.get("summary", "No summary available"),
                    "mentions_user": r.get("mentions_user", False),
                    "urgency": r.get("urgency", "low").lower() if isinstance(r.get("urgency"), str) else "low",
                    "category": r.get("category", "uncategorized"),
                    "action_required": r.get("action_required", False),
                    "deadlines": r.get("deadlines", []),
                })
            return normalized
    except Exception as e:
        logger.warning("Batch triage failed (%s), falling back to individual calls", e)

    # Fallback: individual calls
    logger.info("Falling back to individual triage_email() calls for %d emails", len(emails))
    fallback_default = {
        "summary": "(analysis failed)",
        "mentions_user": False,
        "urgency": "low",
        "category": "uncategorized",
        "action_required": False,
        "deadlines": [],
    }
    results = []
    for email in emails:
        _rate_limiter.wait()
        try:
            results.append(triage_email(
                email.get("from", ""), email.get("subject", ""), email.get("body", ""),
                user_name=user_name, categories=categories,
            ))
        except Exception as e:
            logger.warning("Individual triage also failed for '%s': %s",
                           email.get("subject", "")[:50], e)
            results.append(fallback_default)
    return results


def categorize_email_llm(sender, subject, body, categories, feedback=None, current_category=None):
    """Ask the LLM to categorize a single email into one of the given categories.

    Args:
        sender: Email sender.
        subject: Email subject.
        body: Email body.
        categories: List of allowed category names.
        feedback: Optional user feedback explaining what's wrong with the current plan.
        current_category: The category currently assigned (shown to LLM with feedback).

    Returns a category string.
    """
    truncated_body = body[:4000] if len(body) > 4000 else body
    cat_list = json.dumps(categories)

    feedback_block = ""
    if feedback and current_category:
        feedback_block = f"""
The user reviewed the categorization and gave this feedback:
"{feedback}"
The email was previously categorized as "{current_category}".
Take the user's feedback into account when choosing the new category.
"""

    prompt = f"""Categorize this email into exactly ONE of the following categories:
{cat_list}

If none fit well, use "Misc".
{feedback_block}
Email details:
From: {sender}
Subject: {subject}
Body:
{truncated_body}

Return a JSON object with exactly one key:
- "category": the chosen category

Return ONLY the JSON object, no other text."""

    response = _generate(prompt, generation_config={"response_mime_type": "application/json"})
    result = _parse_json_response(response.text)

    if result and isinstance(result.get("category"), str):
        return result["category"]
    return "Misc"


def refine_draft(rough_text, recipient, subject, tone="Professional",
                  reply_context=None, user_name=None):
    """Refine a rough draft into a professional email.

    Args:
        rough_text: The user's rough draft text.
        recipient: Recipient email address.
        subject: Email subject line.
        tone: Writing tone string.
        reply_context: Optional dict with 'sender_name', 'subject', 'body' from
                       the original email being replied to.
        user_name: Optional user name for sign-off (e.g. "Vashwar").

    Returns a dict with 'subject' (refined) and 'body' (refined).
    """
    reply_block = ""
    if reply_context:
        orig_body = reply_context.get("body", "")[:2000]
        sender_name = reply_context.get("sender_name", "")
        reply_block = f"""
This is a REPLY to the following email:
From: {sender_name}
Subject: {reply_context.get('subject', '')}
Body:
{orig_body}

IMPORTANT reply rules:
- Address the sender as {sender_name} (use their real name, NOT a placeholder).
- This is a REPLY — do NOT use placeholder brackets like [Name] or [Sender Name] anywhere.
"""
        if user_name:
            reply_block += f"- Sign off with: Thanks,\\n{user_name}\n"

    prompt = f"""You are an expert executive assistant and professional copywriter. Your task is to take a rough draft or bullet points and transform them into a polished, clear, and highly effective email.

Here are your strict guidelines:
1. Maintain the Core Message: Do not alter the fundamental meaning, intent, or facts of the original draft.
2. No Hallucinations: NEVER invent dates, metrics, names, or commitments that are not explicitly provided in the rough draft. If information seems missing, leave it out or use a placeholder like [Insert Date].
3. Be Concise: Respect the recipient's time. Eliminate fluff, repetitive phrasing, and unnecessary pleasantries. Get straight to the point.
4. Tone: Adjust the writing to match the requested tone: {tone}.
5. Grammar & Flow: Fix all typos, grammatical errors, and awkward phrasing. Ensure smooth transitions between ideas.
{reply_block}
Please refine the following draft AND improve the subject line:

Original Subject: {subject}
Requested Tone: {tone}
Rough Draft:
{rough_text}

Return a JSON object with exactly two keys:
- "subject": the refined, clear, and concise subject line
- "body": the refined email body text

Return ONLY the JSON object, no other text."""

    response = _generate(prompt, generation_config={"response_mime_type": "application/json"})
    result = _parse_json_response(response.text)

    if result and "subject" in result and "body" in result:
        return {"subject": result["subject"], "body": result["body"]}

    # Fallback: return raw text as body with original subject
    return {"subject": subject, "body": response.text.strip()}


def revise_draft(current_subject, current_body, feedback, tone="Professional",
                 reply_context=None, user_name=None):
    """Revise an already-refined email based on user feedback.

    Args:
        current_subject: Current email subject.
        current_body: Current email body.
        feedback: User's revision feedback.
        tone: Writing tone string.
        reply_context: Optional dict with 'sender_name', 'subject', 'body' from
                       the original email being replied to.
        user_name: Optional user name for sign-off.

    Returns a dict with 'subject' and 'body'.
    """
    reply_block = ""
    if reply_context:
        sender_name = reply_context.get("sender_name", "")
        reply_block = f"""
This is a REPLY to an email from {sender_name}.
IMPORTANT: Address the sender as {sender_name} (use their real name, NOT a placeholder).
Do NOT use placeholder brackets like [Name] or [Sender Name] anywhere.
"""
        if user_name:
            reply_block += f"Sign off with: Thanks,\\n{user_name}\n"

    prompt = f"""You are an expert executive assistant and professional copywriter. A user has reviewed a refined email draft and wants changes.

Apply the user's feedback to revise the email. Follow these rules:
1. Only change what the feedback asks for — keep everything else intact.
2. No Hallucinations: NEVER invent dates, metrics, names, or commitments not in the current draft or feedback.
3. Maintain the requested tone: {tone}.
{reply_block}
Current Subject: {current_subject}
Current Body:
{current_body}

User Feedback: {feedback}

Return a JSON object with exactly two keys:
- "subject": the revised subject line
- "body": the revised email body text

Return ONLY the JSON object, no other text."""

    response = _generate(prompt, generation_config={"response_mime_type": "application/json"})
    result = _parse_json_response(response.text)

    if result and "subject" in result and "body" in result:
        return {"subject": result["subject"], "body": result["body"]}

    return {"subject": current_subject, "body": response.text.strip()}


def generate_auto_reply(sender, subject, body, user_name=None):
    """Generate an appropriate auto-reply to an email.

    Args:
        sender: Email sender string (e.g. "John Doe <john@example.com>").
        subject: Email subject.
        body: Email body text.
        user_name: Optional user name for sign-off.

    Returns the reply body as a string.
    """
    truncated_body = body[:4000] if len(body) > 4000 else body

    sign_off = ""
    if user_name:
        sign_off = f"\nSign off the reply with: Thanks,\\n{user_name}"

    prompt = f"""You are an email assistant. Generate a brief, professional reply to this email.
The reply should acknowledge the email and provide an appropriate response.
Do NOT use placeholder brackets like [Name] or [Your Name] anywhere.{sign_off}

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

    response = _generate(prompt, generation_config={"response_mime_type": "application/json"})
    result = _parse_json_response(response.text)

    if result is None:
        return None

    return {
        "summary": result.get("summary", "Meeting"),
        "start": result.get("start", ""),
        "end": result.get("end", ""),
        "attendees": result.get("attendees", []),
    }