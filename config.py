import os
from dotenv import load_dotenv

load_dotenv()

QBO_CLIENT_ID = os.getenv("QBO_CLIENT_ID")
QBO_CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
QBO_REDIRECT_URI = os.getenv("QBO_REDIRECT_URI")
QBO_BASE_URL = os.getenv("QBO_BASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")

QBO_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

TOKEN_FILE = "tokens.json"
REVIEW_FILE = "bas_review_status.json"
APPROVAL_FILE = "bas_approval.json"

# Sandbox defaults only. Move these to .env before production.
WAGE_ACCOUNT_ID = os.getenv("QBO_WAGE_ACCOUNT_ID", "66")
PAYG_ACCOUNT_ID = os.getenv("QBO_PAYG_ACCOUNT_ID", "49")

DEFAULT_BAS_START = os.getenv("DEFAULT_BAS_START", "2026-09-03")
DEFAULT_BAS_END = os.getenv("DEFAULT_BAS_END", "2026-09-30")
