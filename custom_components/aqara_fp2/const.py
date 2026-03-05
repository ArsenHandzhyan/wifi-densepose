"""Constants for Aqara FP2 integration."""

from datetime import timedelta

DOMAIN = "aqara_fp2"
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
SCAN_INTERVAL = timedelta(seconds=30)  # Must be timedelta!
