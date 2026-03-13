import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from config import CREDENTIALS_PATH, TOKEN_PATH, SCOPES

# Cached service objects
_gmail_service = None
_calendar_service = None
_credentials = None


def get_credentials():
    """Load or create OAuth2 credentials.

    If the existing token doesn't cover all required scopes, attempts to
    re-authenticate. If re-auth fails (e.g., scope not enabled in Cloud Console),
    falls back to the existing token so Gmail features still work.
    """
    global _credentials
    if _credentials is not None:
        return _credentials

    creds = None

    if os.path.exists(TOKEN_PATH):
        # Load with whatever scopes the token has
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        # Need fresh auth — request all scopes
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    # Check if we're missing any scopes
    if creds and creds.scopes and not set(SCOPES).issubset(set(creds.scopes)):
        missing = set(SCOPES) - set(creds.scopes)
        print(f"\nNote: Token is missing scope(s): {missing}")
        print("Calendar features may not work until you re-authenticate.")
        print("To fix: delete credentials/token.json and restart the app.\n")

    _credentials = creds
    return creds


def get_gmail_service():
    """Return a cached Gmail API service object."""
    global _gmail_service
    if _gmail_service is None:
        creds = get_credentials()
        _gmail_service = build("gmail", "v1", credentials=creds)
    return _gmail_service


def get_calendar_service():
    """Return a cached Calendar API service object."""
    global _calendar_service
    if _calendar_service is None:
        creds = get_credentials()
        _calendar_service = build("calendar", "v3", credentials=creds)
    return _calendar_service
