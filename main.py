from auth import get_gmail_service, get_calendar_service
from gmail_service import fetch_unread_emails, search_emails, get_email_by_id
from llm import summarize_email
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


def main():
    print("Authenticating with Google APIs...")
    get_gmail_service()
    get_calendar_service()
    print("Authentication successful! Gmail and Calendar services ready.\n")

    while True:
        print("=== Gmail & Calendar Assistant ===")
        print("  1. Summarize Unread Emails")
        print("  2. Search & Read Emails")
        print("  0. Exit")
        print()

        choice = input("Select an option: ").strip()

        if choice == "1":
            option_summarize_unread()
        elif choice == "2":
            option_search_and_read()
        elif choice == "0":
            print("Goodbye!")
            break
        else:
            print("Invalid option. Please try again.\n")


if __name__ == "__main__":
    main()
