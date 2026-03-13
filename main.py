import sys
from auth import get_gmail_service, get_calendar_service
from gmail_service import fetch_unread_emails, search_emails, get_email_by_id, send_email, send_reply
from llm import summarize_email, refine_draft, generate_auto_reply, parse_meeting_request
from calendar_service import get_todays_events, get_weeks_events, create_event, create_event_from_deadline
from config import USER_NAME

MENU = """
+---------------------------------------+
|     Gmail & Calendar Assistant        |
+---------------------------------------+
|  1. Summarize Unread Emails           |
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


def option_summarize_unread():
    """Option 1: Summarize unread emails with deadline extraction."""
    count = input("How many unread emails to fetch? [10]: ").strip()
    max_results = int(count) if count else 10

    print(f"\nFetching up to {max_results} unread emails...")
    emails = fetch_unread_emails(max_results)

    if not emails:
        print("No unread emails found.\n")
        return

    print(f"Found {len(emails)} unread email(s). Analyzing...\n")

    all_deadlines = []

    for i, email in enumerate(emails, 1):
        print(f"--- Email {i}/{len(emails)} ---")
        print(f"  From:    {email['from']}")
        print(f"  Subject: {email['subject']}")
        print(f"  Date:    {email['date']}")

        analysis = summarize_email(email["from"], email["subject"], email["body"], USER_NAME)

        print(f"  Summary: {analysis['summary']}")
        print(f"  Urgency: {analysis['urgency'].upper()}")

        if analysis["mentions_user"]:
            print(f"  ** MENTIONS {USER_NAME.upper()} **")

        if analysis["deadlines"]:
            print(f"  Deadlines: {', '.join(analysis['deadlines'])}")
            for d in analysis["deadlines"]:
                all_deadlines.append((email["subject"], d))

        print()

    if all_deadlines:
        print(f"Found {len(all_deadlines)} deadline(s) across emails:")
        for i, (subj, deadline) in enumerate(all_deadlines, 1):
            print(f"  [{i}] {deadline} (from: {subj})")

        add_to_cal = input("\nAdd these deadlines to your calendar? (Y/N): ").strip().upper()
        if add_to_cal == "Y":
            for subj, deadline in all_deadlines:
                try:
                    created = create_event_from_deadline(subj, deadline)
                    print(f"  Created: {created.get('summary', 'event')} on {deadline}")
                except Exception as e:
                    print(f"  Could not create event for '{deadline}': {e}")
            print()


def option_search_and_read():
    """Option 2: Search and read emails."""
    query = input("Enter Gmail search query (e.g., from:someone subject:project): ").strip()
    if not query:
        print("No query entered.\n")
        return

    count = input("Max results? [10]: ").strip()
    max_results = int(count) if count else 10

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


def option_compose_email():
    """Option 3: Compose an email with AI assistance."""
    to = input("Recipient email address: ").strip()
    if not to:
        print("No recipient entered.\n")
        return

    subject = input("Subject: ").strip()
    if not subject:
        print("No subject entered.\n")
        return

    print("\nSelect tone:")
    print("  [1] Professional")
    print("  [2] Friendly")
    print("  [3] Formal")
    print("  [4] Casual")
    tone_map = {"1": "Professional", "2": "Friendly", "3": "Formal", "4": "Casual"}
    tone_choice = input("Tone [1]: ").strip()
    tone = tone_map.get(tone_choice, "Professional")
    print(f"Using tone: {tone}\n")

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
    refined = refine_draft(rough_text, to, subject, tone)
    refined_subject = refined["subject"]
    refined_body = refined["body"]

    print(f"\n{'='*60}")
    print(f"To:      {to}")
    print(f"Subject: {refined_subject}")
    if refined_subject != subject:
        print(f"         (was: {subject})")
    print(f"{'='*60}")
    print(refined_body)
    print(f"{'='*60}\n")

    confirm = input("Send this email? (Y/N): ").strip().upper()
    if confirm == "Y":
        result = send_email(to, refined_subject, refined_body)
        print(f"Email sent successfully! Message ID: {result['id']}\n")
    else:
        print("Email discarded.\n")


def option_auto_reply():
    """Option 4: Generate and send auto-replies to unread emails."""
    count = input("How many unread emails to check? [5]: ").strip()
    max_results = int(count) if count else 5

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
    reply_body = generate_auto_reply(email["from"], email["subject"], email["body"])

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
    if parsed["attendees"]:
        print(f"  Attendees: {', '.join(parsed['attendees'])}")

    add_meet = input("\nAdd a Google Meet link? (Y/N): ").strip().upper()
    meet_link = add_meet == "Y"

    confirm = input("Create this event? (Y/N): ").strip().upper()
    if confirm == "Y":
        created = create_event(
            parsed["summary"],
            parsed["start"],
            parsed["end"],
            parsed["attendees"] if parsed["attendees"] else None,
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
        "1": ("Summarize Unread Emails", option_summarize_unread),
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
