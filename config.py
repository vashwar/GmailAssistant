import os
import json
from dotenv import load_dotenv

load_dotenv()

# Paths
CREDENTIALS_PATH = os.path.join("credentials", "credentials.json")
TOKEN_PATH = os.path.join("credentials", "token.json")

# OAuth2 scopes — Gmail + Calendar
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]

# Gemini / LLM
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Email categorization rules
EMAIL_CATEGORIES = json.loads(os.getenv("EMAIL_CATEGORIES", "{}"))

# User identity for mention detection
USER_NAME = "Vashwar"
