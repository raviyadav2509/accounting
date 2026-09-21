import os
from dotenv import load_dotenv

load_dotenv()

QBO_CLIENT_ID = os.getenv("QBO_CLIENT_ID")
QBO_CLIENT_SECRET = os.getenv("QBO_CLIENT_SECRET")
QBO_REDIRECT_URI = os.getenv("QBO_REDIRECT_URI")
QBO_BASE_URL = os.getenv("QBO_BASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


ENABLE_MOCK_ATO_LODGEMENT = _env_flag("ENABLE_MOCK_ATO_LODGEMENT", False)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_USE_TLS = _env_flag("SMTP_USE_TLS", True)
SMTP_USE_SSL = _env_flag("SMTP_USE_SSL", False)
EMAIL_FROM = os.getenv("EMAIL_FROM") or SMTP_USERNAME
EMAIL_VERIFICATION_EXPIRY_MINUTES = int(
    os.getenv("EMAIL_VERIFICATION_EXPIRY_MINUTES", "30")
)
EMAIL_VERIFICATION_DEBUG_LINKS = _env_flag(
    "EMAIL_VERIFICATION_DEBUG_LINKS",
    False,
)

QBO_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QBO_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

TOKEN_FILE = "tokens.json"
REVIEW_FILE = "bas_review_status.json"
APPROVAL_FILE = "bas_approval.json"
DATABASE_FILE = os.getenv("BAS_DATABASE_FILE", "bas_history.db")

# Sandbox defaults only. Move these to .env before production.
WAGE_ACCOUNT_ID = os.getenv("QBO_WAGE_ACCOUNT_ID", "66")
PAYG_ACCOUNT_ID = os.getenv("QBO_PAYG_ACCOUNT_ID", "49")

DEFAULT_BAS_START = os.getenv("DEFAULT_BAS_START", "2026-09-03")
DEFAULT_BAS_END = os.getenv("DEFAULT_BAS_END", "2026-09-30")
