#!/usr/bin/env python3
"""
FP2 → Homebridge Bridge

Polls input_boolean.fp2_presence from Home Assistant,
and sends webhook to Homebridge HttpWebHooks plugin
so binary_sensor.fp2_presence in HA gets real state.

Usage:
    python3 scripts/fp2_homebridge_bridge.py
"""

import time
import os
import requests
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("fp2-bridge")

HA_URL = os.getenv("HA_URL", "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")
SOURCE_ENTITY = os.getenv("SOURCE_ENTITY", "input_boolean.fp2_presence")
HOMEBRIDGE_WEBHOOK_URL = os.getenv("HOMEBRIDGE_WEBHOOK_URL", "http://localhost:51828")
SENSOR_ID = "fp2_motion"
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "2.0"))

def get_headers() -> dict[str, str]:
    if not HA_TOKEN:
        raise RuntimeError("HA_TOKEN environment variable is required")
    return {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }


def get_ha_state(entity_id: str) -> str | None:
    try:
        r = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=get_headers(), timeout=5)
        if r.status_code == 200:
            return r.json().get("state")
    except Exception as e:
        log.warning("HA poll error: %s", e)
    return None


def send_webhook(state: bool):
    value = "true" if state else "false"
    url = f"{HOMEBRIDGE_WEBHOOK_URL}/?accessoryId={SENSOR_ID}&state={value}"
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            log.info("Webhook sent → %s → binary_sensor.fp2_presence = %s",
                     "MOTION DETECTED" if state else "NO MOTION", state)
        else:
            log.warning("Webhook error: %s", r.status_code)
    except Exception as e:
        log.warning("Webhook request failed: %s", e)


def main():
    if not HA_TOKEN:
        raise SystemExit("HA_TOKEN environment variable is required for Home Assistant access")

    log.info("FP2 Bridge starting...")
    log.info("  Source: %s @ %s", SOURCE_ENTITY, HA_URL)
    log.info("  Homebridge webhook: %s", HOMEBRIDGE_WEBHOOK_URL)
    log.info("  Poll interval: %.1fs", POLL_INTERVAL)

    last_state = None

    while True:
        raw = get_ha_state(SOURCE_ENTITY)
        if raw is not None:
            presence = raw in ("on", "true", "home", "detected")
            if presence != last_state:
                log.info("State changed: %s → %s", last_state, "PRESENT" if presence else "ABSENT")
                send_webhook(presence)
                last_state = presence
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
