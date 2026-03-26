"""Constants for Aqara FP2 integration."""

from datetime import timedelta

DOMAIN = "aqara_fp2"
COORDINATOR = "coordinator"
CONF_REGION = "region"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_DEVICE_ID = "device_id"

PLATFORMS = ["binary_sensor", "sensor"]

# API endpoints
API_DOMAINS = {
    "europe": "open-ger.aqara.com",
    "china": "open-cn.aqara.com",
    "usa": "open-usa.aqara.com",
    "russia": "open-rus.aqara.com",
    "singapore": "open-sgp.aqara.com",
    "korea": "open-kor.aqara.com",
}

# Default configuration
DEFAULT_REGION = "europe"
SCAN_INTERVAL = timedelta(seconds=60)
SCAN_INTERVAL_BACKOFF = timedelta(minutes=5)
SCAN_INTERVAL_FATAL = timedelta(minutes=30)
SCAN_INTERVAL_RATE_LIMITED = timedelta(minutes=6)  # 5-min window + margin
SCAN_INTERVAL_QUOTA_EXHAUSTED = timedelta(hours=1)  # monthly quota hit

# Rate limiting (Aqara free tier)
RATE_LIMIT_WINDOW = 300  # 5 minutes in seconds
RATE_LIMIT_MAX_CALLS = 290  # 300 limit, 10 call safety margin
MONTHLY_QUOTA_MAX = 95_000  # 100K limit, 5K safety margin

# Rate limit response codes
RATE_LIMIT_CODES = {429, 2015, 2016}  # HTTP 429 + Aqara-specific rate limit codes

# Token refresh
CONF_APP_ID = "app_id"
CONF_APP_KEY = "app_key"
CONF_KEY_ID = "key_id"
TOKEN_REFRESH_INTENT = "config.auth.refreshToken"
TOKEN_EXPIRY_CODES = {108, 2005}  # Token has expired, AccessToken expired
