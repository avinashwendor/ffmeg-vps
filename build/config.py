"""API keys for workflow generation — env vars or build/secrets_local.py (gitignored)."""
import os

TAVILY_KEY = os.environ.get("TAVILY_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
ELEVENLABS_KEY = os.environ.get("ELEVENLABS_KEY", "")
CARTESIA_API_KEY = os.environ.get("CARTESIA_API_KEY", "")
CARTESIA_VOICE_ID = os.environ.get("CARTESIA_VOICE_ID", "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
COMPOSER_URL = os.environ.get("COMPOSER_URL", "https://ffmeg-vps-production.up.railway.app")
COMPOSER_AUTH_TOKEN = os.environ.get("COMPOSER_AUTH_TOKEN", "")
RAILWAY_S3_ACCESS_KEY = os.environ.get("RAILWAY_S3_ACCESS_KEY", "")
RAILWAY_S3_SECRET_KEY = os.environ.get("RAILWAY_S3_SECRET_KEY", "")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")

LINKEDIN_ORG_ID = os.environ.get("LINKEDIN_ORG_ID", "")
LINKEDIN_CREDENTIAL_TYPE = os.environ.get(
    "LINKEDIN_CREDENTIAL_TYPE", "linkedInOAuth2Api"
)  # same as other_linkdien.json; use linkedInCommunityManagementOAuth2Api only if v2 works for you
LINKEDIN_PUBLISH_AS = os.environ.get("LINKEDIN_PUBLISH_AS", "organization")  # organization | person
LINKEDIN_PERSON_URN = os.environ.get(
    "LINKEDIN_PERSON_URN", "urn:li:person:kg3LWhQv94"
)  # Lakshit — matches other_linkdien.json; required when LINKEDIN_PUBLISH_AS=person
LINKEDIN_API_VERSION = os.environ.get("LINKEDIN_API_VERSION", "202501")
LINKEDIN_SEARCH_QUERY = os.environ.get(
    "LINKEDIN_SEARCH_QUERY",
    "vending machine smart retail passive income UPI India Dubai news trends 2026",
)
TELEGRAM_LINKEDIN_BOT_TOKEN = os.environ.get("TELEGRAM_LINKEDIN_BOT_TOKEN", "")
TELEGRAM_LINKEDIN_CHAT_ID = os.environ.get("TELEGRAM_LINKEDIN_CHAT_ID", "")

try:
    from secrets_local import *  # noqa: F403
except ImportError:
    pass
