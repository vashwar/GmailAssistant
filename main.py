import sys
from auth import get_gmail_service, get_calendar_service
from gmail_service import fetch_unread_emails, search_emails, get_email_by_id, send_email, send_reply, search_contacts
from llm import refine_draft, revise_draft, generate_auto_reply, parse_meeting_request
from calendar_service import get_todays_events, get_weeks_events, create_event
from triage_engine import run_triage
from config import USER_NAME

MENU = """
+---------------------------------------+
|     Gmail & Calendar Assistant        |
+---------------------------------------+
|  1. Smart Triage (Inbox Briefing)     |
|  2. Search & Read Emails              |
|  3. Compose Email (AI-Assisted)       |
|  4. Auto-Reply to Email               |
|  5. View Calendar                     |
|  6. Schedule Meeting                  |
|  0. Exit                              |
+---------------------------------------+
"""


def _format_event(event):
    """Format a calendar event for display."""
    start = event.get("start", {})
    end = event.get("end", {})
    start_str = start.get("dateTime", start.get("date", ""))
    end_str = end.get("dateTime", end.get("date", ""))
    if "T" in start_str:
        start_str = start_str.replace("T", " ")[:16]
    if "T" in end_str:
        end_str = end_str.replace("T", " ")[:16]
    summary = event.get("summary", "(No title)")
    return f"{start_str} - {end_str}  {summary}"


def option_search_and_read():
    """Option 2: Search and read emails."""
    query = input("Enter Gmail search query (e.g., from:someone subject:project): ").strip()
    if not query:
        print("No query entered.\n")
        return

    count = input("Max results? [10]: ").strip()
    try:
        max_results = int(count) if count else 10
    except ValueError:
        print("Invalid number, using default of 10.")
        max_results = 10

    print(f"\nSearching for: {query}")
    emails = search_emails(query, max_results)

    if not emails:
        print("No emails found matching your query.\n")
        return

    print(f"\nFound {len(emails)} email(s):\n")
    for i, email in enumerate(emails, 1):
        print(f"  [{i}] {email['from']} — {email['subject']} ({email['date']})")

    print()
    choice = input("Enter number to read full email (or press Enter to skip): ").strip()
    if choice and choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(emails):
            email = emails[idx]
            print(f"\n{'='*60}")
            print(f"From:    {email['from']}")
            print(f"To:      {email['to']}")
            print(f"Subject: {email['subject']}")
            print(f"Date:    {email['date']}")
            print(f"{'='*60}")
            print(email["body"])
            print(f"{'='*60}\n")
        else:
            print("Invalid selection.\n")


def _pick_recipient():
    """Prompt for a recipient — type an email or search contacts by name."""
    print("Recipient — enter an email address or a name to search:")
    query = input("> ").strip()
    if not query:
        return None

    # If it looks like an email, use it directly
    if "@" in query:
        return query

    # Otherwise, search contacts
    print(f"\nSearching contacts for \"{query}\"...")
    contacts = search_contacts(query)

    if not contacts:
        print("No contacts found. Enter the email address manually:")
        manual = input("> ").strip()
        return manual if manual else None

    print(f"\nFound {len(contacts)} contact(s):\n")
    for i, c in enumerate(contacts, 1):
        display = f"{c['name']} <{c['email']}>" if c["name"] else c["email"]
        print(f"  [{i}] {display}")

    print()
    choice = input("Select a contact (or type an email to use instead): ").strip()
    if "@" in choice:
        return choice
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(contacts):
            return contacts[idx]["email"]
    print("Invalid selection.")
    return None


def _draft_and_send(to, subject, tone, send_fn, reply_context=None, user_name=None):
    """Shared draft/refine/send loop used by both new email and reply flows.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        tone: Writing tone string.
        send_fn: Callable(refined_subject, refined_body) that sends the message
                 and returns the API result dict.
        reply_context: Optional dict with 'sender_name', 'subject', 'body' from
                       the original email being replied to.
        user_name: Optional user name for sign-off in replies.
    """
    print("Enter your rough draft (type END on a new line to finish):")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    rough_text = "\n".join(lines)

    if not rough_text.strip():
        print("Empty draft. Aborting.\n")
        return

    print("\nRefining your draft with AI...")
    refined = refine_draft(rough_text, to, subject, tone,
                           reply_context=reply_context, user_name=user_name)
    refined_subject = refined["subject"]
    refined_body = refined["body"]

    while True:
        print(f"\n{'='*60}")
        print(f"To:      {to}")
        print(f"Subject: {refined_subject}")
        if refined_subject != subject:
            print(f"         (was: {subject})")
        print(f"{'='*60}")
        print(refined_body)
        print(f"{'='*60}\n")

        confirm = input("Send this email? (Y/N/Q to quit): ").strip().upper()
        if confirm == "Y":
            result = send_fn(refined_subject, refined_body)
            print(f"Email sent successfully! Message ID: {result['id']}\n")
            break
        elif confirm == "Q":
            print("Email discarded.\n")
            break
        else:
            feedback = input("What would you like to change? ").strip()
            if not feedback:
                print("No feedback provided. Keeping current draft.\n")
                continue
            print("\nRevising draft...")
            revised = revise_draft(refined_subject, refined_body, feedback, tone,
                                   reply_context=reply_context, user_name=user_name)
            refined_subject = revised["subject"]
            refined_body = revised["body"]


def _pick_tone():
    """Prompt user for a writing tone. Returns tone string."""
    print("\nSelect tone:")
    print("  [1] Professional")
    print("  [2] Friendly")
    print("  [3] Formal")
    print("  [4] Casual")
    tone_map = {"1": "Professional", "2": "Friendly", "3": "Formal", "4": "Casual"}
    tone_choice = input("Tone [1]: ").strip()
    tone = tone_map.get(tone_choice, "Professional")
    print(f"Using tone: {tone}\n")
    return tone


def _compose_new_email():
    """Compose and send a new email."""
    to = _pick_recipient()
    if not to:
        print("No recipient selected.\n")
        return

    subject = input("Subject: ").strip()
    if not subject:
        print("No subject entered.\n")
        return

    tone = _pick_tone()

    def send_new(refined_subject, refined_body):
        return send_email(to, refined_subject, refined_body)

    _draft_and_send(to, subject, tone, send_new)


def _compose_reply():
    """Search for an existing email by contact and reply to it."""
    # Step 1: Find the contact
    print("Search for a contact to reply to:")
    query = input("> ").strip()
    if not query:
        print("No search query entered.\n")
        return

    # Search contacts
    if "@" in query:
        contact_email = query
    else:
        print(f"\nSearching contacts for \"{query}\"...")
        contacts = search_contacts(query)

        if not contacts:
            print("No contacts found. Enter the email address manually:")
            manual = input("> ").strip()
            if not manual:
                print("No recipient selected.\n")
                return
            contact_email = manual
        else:
            print(f"\nFound {len(contacts)} contact(s):\n")
            for i, c in enumerate(contacts, 1):
                display = f"{c['name']} <{c['email']}>" if c["name"] else c["email"]
                print(f"  [{i}] {display}")

            print()
            choice = input("Select a contact (or type an email): ").strip()
            if "@" in choice:
                contact_email = choice
            elif choice.isdigit() and 1 <= int(choice) <= len(contacts):
                contact_email = contacts[int(choice) - 1]["email"]
            else:
                print("Invalid selection.\n")
                return

    # Step 2: Search for recent emails from/to this contact
    print(f"\nSearching emails with {contact_email}...")
    emails = search_emails(f"from:{contact_email} OR to:{contact_email}", max_results=10)

    if not emails:
        print(f"No emails found with {contact_email}.\n")
        return

    print(f"\nFound {len(emails)} email(s):\n")
    for i, email in enumerate(emails, 1):
        print(f"  [{i}] {email['from']} — {email['subject']} ({email['date']})")

    print()
    choice = input("Select an email to reply to (or press Enter to cancel): ").strip()
    if not choice or not choice.isdigit():
        print("Cancelled.\n")
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(emails):
        print("Invalid selection.\n")
        return

    email = emails[idx]

    # Show the original email for context
    print(f"\n{'='*60}")
    print(f"From:    {email['from']}")
    print(f"Subject: {email['subject']}")
    print(f"Date:    {email['date']}")
    print(f"{'='*60}")
    body_preview = email['body'][:500]
    print(body_preview)
    if len(email['body']) > 500:
        print("... (truncated)")
    print(f"{'='*60}\n")

    # Step 3: Draft and send reply using shared flow
    to = email["from"]
    # Extract sender display name (e.g. "John Doe <john@example.com>" → "John Doe")
    sender_name = to.split("<")[0].strip().strip('"') if "<" in to else to.split("@")[0]
    if "<" in to:
        to = to.split("<")[1].rstrip(">")
    subject = email["subject"] if email["subject"].lower().startswith("re:") else f"Re: {email['subject']}"

    tone = _pick_tone()

    reply_context = {
        "sender_name": sender_name,
        "subject": email["subject"],
        "body": email["body"],
    }

    def send_as_reply(refined_subject, refined_body):
        return send_reply(email["id"], to, refined_subject, refined_body, email["threadId"])

    _draft_and_send(to, subject, tone, send_as_reply,
                    reply_context=reply_context, user_name=USER_NAME)


def option_compose_email():
    """Option 3: Compose an email with AI assistance."""
    print("\n  [1] Send new email")
    print("  [2] Reply to existing email")
    choice = input("\nSelect option: ").strip()

    if choice == "1":
        _compose_new_email()
    elif choice == "2":
        _compose_reply()
    else:
        print("Invalid option.\n")


def option_auto_reply():
    """Option 4: Generate and send auto-replies to unread emails."""
    count = input("How many unread emails to check? [5]: ").strip()
    try:
        max_results = int(count) if count else 5
    except ValueError:
        print("Invalid number, using default of 5.")
        max_results = 5

    print(f"\nFetching up to {max_results} unread emails...")
    emails = fetch_unread_emails(max_results)

    if not emails:
        print("No unread emails found.\n")
        return

    print(f"\nFound {len(emails)} unread email(s):\n")
    for i, email in enumerate(emails, 1):
        print(f"  [{i}] {email['from']} — {email['subject']}")

    print()
    choice = input("Enter number to generate a reply for (or press Enter to skip): ").strip()
    if not choice or not choice.isdigit():
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(emails):
        print("Invalid selection.\n")
        return

    email = emails[idx]
    print(f"\nGenerating reply to: {email['subject']}...")
    reply_body = generate_auto_reply(email["from"], email["subject"], email["body"],
                                     user_name=USER_NAME)

    print(f"\n{'='*60}")
    print(f"Reply to: {email['from']}")
    print(f"Subject:  Re: {email['subject']}")
    print(f"{'='*60}")
    print(reply_body)
    print(f"{'='*60}\n")

    confirm = input("Send this reply? (Y/N): ").strip().upper()
    if confirm == "Y":
        sender = email["from"]
        if "<" in sender:
            sender = sender.split("<")[1].rstrip(">")
        result = send_reply(
            email["id"], sender, email["subject"],
            reply_body, email["threadId"]
        )
        print(f"Reply sent successfully! Message ID: {result['id']}\n")
    else:
        print("Reply discarded.\n")


def option_view_calendar():
    """Option 5: View today's or this week's calendar."""
    print("  [1] Today's events")
    print("  [2] This week's events")
    view = input("Choose view: ").strip()

    if view == "1":
        print("\nToday's Events:")
        events = get_todays_events()
    elif view == "2":
        print("\nThis Week's Events:")
        events = get_weeks_events()
    else:
        print("Invalid choice.\n")
        return

    if not events:
        print("  No events found.")
    else:
        for event in events:
            print(f"  {_format_event(event)}")
    print()


def option_schedule_meeting():
    """Option 6: Schedule a meeting from natural language."""
    print("Describe the meeting (e.g., 'Sync with John next Tuesday at 2 PM'):")
    request = input("> ").strip()
    if not request:
        print("No input provided.\n")
        return

    print("\nParsing your request...")
    parsed = parse_meeting_request(request)

    if not parsed or not parsed.get("start"):
        print("Could not parse the meeting request. Please try again with more detail.\n")
        return

    print(f"\n  Title:     {parsed['summary']}")
    print(f"  Start:     {parsed['start']}")
    print(f"  End:       {parsed['end']}")

    # Collect attendees interactively
    attendees = list(parsed.get("attendees") or [])
    if attendees:
        print(f"  Attendees (from description): {', '.join(attendees)}")

    print("\nAdd attendees to send meeting invites.")
    while True:
        email = _pick_recipient()
        if email:
            if email not in attendees:
                attendees.append(email)
                print(f"  Added: {email}")
            else:
                print(f"  {email} is already in the list.")
        add_more = input("Add another attendee? (Y/N): ").strip().upper()
        if add_more != "Y":
            break

    if attendees:
        print(f"\n  Final attendees: {', '.join(attendees)}")

    add_meet = input("\nAdd a Google Meet link? (Y/N): ").strip().upper()
    meet_link = add_meet == "Y"

    confirm = input("Create this event? (Y/N): ").strip().upper()
    if confirm == "Y":
        created = create_event(
            parsed["summary"],
            parsed["start"],
            parsed["end"],
            attendees if attendees else None,
            add_meet_link=meet_link,
        )
        print(f"\nEvent created: {created.get('htmlLink', '')}")
        if meet_link and "conferenceData" in created:
            entry_points = created["conferenceData"].get("entryPoints", [])
            for ep in entry_points:
                if ep.get("entryPointType") == "video":
                    print(f"Meet link: {ep['uri']}")
                    break
        print()
    else:
        print("Event creation cancelled.\n")


def main():
    print("Authenticating with Google APIs...")
    try:
        get_gmail_service()
        get_calendar_service()
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)
    print("Authentication successful!\n")

    options = {
        "1": ("Smart Triage (Inbox Briefing)", run_triage),
        "2": ("Search & Read Emails", option_search_and_read),
        "3": ("Compose Email (AI-Assisted)", option_compose_email),
        "4": ("Auto-Reply to Email", option_auto_reply),
        "5": ("View Calendar", option_view_calendar),
        "6": ("Schedule Meeting", option_schedule_meeting),
    }

    while True:
        print(MENU)
        choice = input("Select an option: ").strip()

        if choice == "0":
            print("Goodbye!")
            break
        elif choice in options:
            try:
                options[choice][1]()
            except KeyboardInterrupt:
                print("\n\nOperation cancelled.\n")
            except Exception as e:
                print(f"\nError: {e}\n")
        else:
            print("Invalid option. Please try again.\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)
