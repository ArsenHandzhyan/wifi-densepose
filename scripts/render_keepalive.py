#!/usr/bin/env python3
"""
Render Keep-Alive Script

Prevents Render free tier service from sleeping by periodically
pinging health and FP2 endpoints.

Usage:
    python3 scripts/render_keepalive.py &
    
Or with nohup:
    nohup python3 scripts/render_keepalive.py > /dev/null 2>&1 &
"""

import time
import requests
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("keepalive")

# Render service endpoints
BASE_URL = "https://wifi-densepose-qtgc.onrender.com"
ENDPOINTS = [
    "/api/v1/health",
    "/api/v1/fp2/status",
    "/api/v1/info",
]

# Ping every 10 minutes (Render sleeps after 15 min of inactivity)
INTERVAL = 600  # 10 minutes


def ping_endpoint(endpoint: str) -> bool:
    url = f"{BASE_URL}{endpoint}"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            log.info(f"✓ {endpoint} - OK")
            return True
        else:
            log.warning(f"✗ {endpoint} - HTTP {r.status_code}")
            return False
    except Exception as e:
        log.error(f"✗ {endpoint} - Error: {e}")
        return False


def main():
    log.info("=" * 50)
    log.info("Render Keep-Alive started")
    log.info(f"Base URL: {BASE_URL}")
    log.info(f"Interval: {INTERVAL}s ({INTERVAL/60:.0f} min)")
    log.info("=" * 50)

    while True:
        log.info("--- Keep-alive ping ---")
        for endpoint in ENDPOINTS:
            ping_endpoint(endpoint)
        
        next_ping = datetime.now().timestamp() + INTERVAL
        log.info(f"Next ping at {datetime.fromtimestamp(next_ping).strftime('%H:%M:%S')}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Keep-alive stopped.")
