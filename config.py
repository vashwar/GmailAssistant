import os
import json
from dotenv import load_dotenv

load_dotenv()

# Paths
CREDENTIALS_PATH = os.path.join("credentials", "credentials.json")
TOKEN_PATH = os.path.join("credentials", "token.json")

# OAuth2 scopes — Gmail (full access) + Calendar
SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/calendar",
]

# Gemini / LLM
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Email categorization rules — keywords matched case-insensitively against sender and subject.
# Emails that don't match any category go to "Misc".
# Override via .env by setting EMAIL_CATEGORIES to a JSON string.
_DEFAULT_EMAIL_CATEGORIES = {
    "Jobs": ["linkedin", "recruiter", "job", "career", "hiring", "glassdoor", "indeed", "dice"],
    "Academic": ["haas", "ewmba", ".edu", "university", "berkeley", "coursework", "cohort", "academic"],
    "Online Shopping": ["amazon", "ebay", "target", "walmart", "etsy", "order confirmation", "shipment", "tracking", "shopify"],
    "Grocery": ["whole foods", "meat corner", "instacart", "grocery", "safeway", "trader joe"],
    "Restaurant": ["doordash", "ubereats", "grubhub", "restaurant", "dining", "reservation", "opentable", "yelp receipt"],
    "Bills": ["pg&e", "utility", "bill", "payment due", "invoice", "subscription", "comcast", "xfinity", "t-mobile", "at&t", "verizon"],
    "Travel": ["airline", "flight", "hotel", "booking", "boarding pass", "trip", "united", "delta", "southwest", "airbnb", "expedia", "kayak"],
    "Banks/Investment": ["bank", "chase", "wells fargo", "credit card", "brokerage", "venmo", "zelle", "tax", "fidelity", "schwab", "robinhood", "statement"],
    "Social Media": ["facebook", "instagram", "twitter", "tiktok", "reddit", "nextdoor", "snapchat"],
    "Newsletters": ["substack", "medium", "newsletter", "digest", "weekly update", "mailing list"],
    "Promotions": ["sale", "coupon", "promo", "% off", "deal", "loyalty", "reward", "offer", "unsubscribe"],
    "Family": ["rashna9@gmail.com", "harun.rashid68@yahoo.com", "harunur.rashid68@gmail.com", "laila.rashid1980@gmail.com"],
    "NewsSummary": ["onboarding@resend.dev"],
}

_env_categories = os.getenv("EMAIL_CATEGORIES", "")
EMAIL_CATEGORIES = json.loads(_env_categories) if _env_categories else _DEFAULT_EMAIL_CATEGORIES

# User identity for mention detection
USER_NAME = os.getenv("USER_NAME", "Vashwar")

# Timezone for calendar events
TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
