from auth import get_gmail_service, get_calendar_service
from gmail_service import fetch_unread_emails, search_emails, get_email_by_id, send_email, send_reply
from llm import summarize_email, refine_draft, generate_auto_reply
from config import USER_NAME


def option_summarize_unread():
    """Option 1: Summarize unread emails."""
    count = input("How many unread emails to fetch? [10]: ").strip()
    max_results = int(count) if count else 10

    print(f"\nFetching up to {max_results} unread emails...")
    emails = fetch_unread_emails(max_results)

    if not emails:
        print("No unread emails found.")
        return

    print(f"\nFound {len(emails)} unread email(s). Analyzing...\n")

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

        print()


def option_search_and_read():
    """Option 2: Search and read emails."""
    query = input("Enter Gmail search query (e.g., from:someone subject:project): ").strip()
    if not query:
        print("No query entered.")
        return

    count = input("Max results? [10]: ").strip()
    max_results = int(count) if count else 10

    print(f"\nSearching for: {query}")
    emails = search_emails(query, max_results)

    if not emails:
        print("No emails found matching your query.")
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
            print("Invalid selection.")


def option_compose_email():
    """Option 3: Compose an email with AI assistance."""
    to = input("Recipient email address: ").strip()
    if not to:
        print("No recipient entered.")
        return

    subject = input("Subject: ").strip()
    if not subject:
        print("No subject entered.")
        return

    print("Enter your rough draft (type END on a new line to finish):")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    rough_text = "\n".join(lines)

    if not rough_text.strip():
        print("Empty draft. Aborting.")
        return

    print("\nRefining your draft with AI...")
    refined = refine_draft(rough_text, to, subject)

    print(f"\n{'='*60}")
    print(f"To:      {to}")
    print(f"Subject: {subject}")
    print(f"{'='*60}")
    print(refined)
    print(f"{'='*60}\n")

    confirm = input("Send this email? (Y/N): ").strip().upper()
    if confirm == "Y":
        result = send_email(to, subject, refined)
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
        print("No unread emails found.")
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
        print("Invalid selection.")
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
        # Extract sender email address
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


def main():
    print("Authenticating with Google APIs...")
    get_gmail_service()
    get_calendar_service()
    print("Authentication successful! Gmail and Calendar services ready.\n")

    while True:
        print("=== Gmail & Calendar Assistant ===")
        print("  1. Summarize Unread Emails")
        print("  2. Search & Read Emails")
        print("  3. Compose Email (AI-Assisted)")
        print("  4. Auto-Reply to Email")
        print("  0. Exit")
        print()

        choice = input("Select an option: ").strip()

        if choice == "1":
            option_summarize_unread()
        elif choice == "2":
            option_search_and_read()
        elif choice == "3":
            option_compose_email()
        elif choice == "4":
            option_auto_reply()
        elif choice == "0":
            print("Goodbye!")
            break
        else:
            print("Invalid option. Please try again.\n")


if __name__ == "__main__":
    main()
