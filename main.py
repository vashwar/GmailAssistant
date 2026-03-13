from auth import get_gmail_service, get_calendar_service


def main():
    print("Authenticating with Google APIs...")
    gmail = get_gmail_service()
    calendar = get_calendar_service()
    print("Authentication successful! Gmail and Calendar services ready.")


if __name__ == "__main__":
    main()
