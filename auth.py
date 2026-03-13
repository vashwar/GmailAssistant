import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from config import CREDENTIALS_PATH, TOKEN_PATH, SCOPES

# Cached service objects
_gmail_service = None
_calendar_service = None


def get_credentials():
    """Load or create OAuth2 credentials, re-authing if scopes changed."""
    creds = None

    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

        # If the saved token doesn't cover all required scopes, delete and re-auth
        if creds and creds.scopes and not set(SCOPES).issubset(set(creds.scopes)):
            os.remove(TOKEN_PATH)
            creds = None

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

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
