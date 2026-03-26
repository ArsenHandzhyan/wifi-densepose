"""Shared coordinator for Aqara FP2 cloud polling."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    API_DOMAINS,
    CONF_ACCESS_TOKEN,
    CONF_DEVICE_ID,
    CONF_REFRESH_TOKEN,
    CONF_REGION,
    DOMAIN,
    MONTHLY_QUOTA_MAX,
    RATE_LIMIT_CODES,
    RATE_LIMIT_MAX_CALLS,
    RATE_LIMIT_WINDOW,
    SCAN_INTERVAL,
    SCAN_INTERVAL_BACKOFF,
    SCAN_INTERVAL_FATAL,
    SCAN_INTERVAL_QUOTA_EXHAUSTED,
    SCAN_INTERVAL_RATE_LIMITED,
    TOKEN_EXPIRY_CODES,
    TOKEN_REFRESH_INTENT,
)

_LOGGER = logging.getLogger(__name__)

APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
DEFAULT_INTENT = "config.device.getState"
FALLBACK_INTENTS = (
    "device.getState",
    "getDeviceState",
    "Config.device.getState",
)
FATAL_RESPONSE_CODES = {
    106,  # Invalid sign
    107,  # Illegal appKey
    109,  # Token is absence
    2002,  # Appid or Appkey illegal
    2003,  # AuthCode incorrect
    2004,  # AccessToken incorrect
    2006,  # RefreshToken incorrect
    2007,  # RefreshToken expired
    2008,  # Permission denied
    2010,  # Unauthorized user
    2013,  # Developer permission denied
    2014,  # Resource permission denied
}
MAX_CONSECUTIVE_ERRORS = 3


def extract_params(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract params from either result payload shape."""
    if not isinstance(payload, dict):
        return []

    params = payload.get("params")
    if isinstance(params, list):
        return params

    nested_result = payload.get("result")
    if isinstance(nested_result, dict):
        nested_params = nested_result.get("params")
        if isinstance(nested_params, list):
            return nested_params

    return []


class AqaraDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Shared data update coordinator for Aqara FP2."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]):
        """Initialize the coordinator."""
        self.hass = hass
        self.config = config
        self.region = config.get(CONF_REGION, "europe")
        self.access_token = config.get(CONF_ACCESS_TOKEN)
        self.refresh_token = config.get(CONF_REFRESH_TOKEN)
        self.device_id = config.get(CONF_DEVICE_ID)
        self.api_domain = API_DOMAINS.get(self.region, API_DOMAINS["europe"])
        self.base_url = f"https://{self.api_domain}/v3.0/open/api"
        self.session = async_get_clientsession(hass)
        self._working_intent = DEFAULT_INTENT
        self._intent_confirmed = False
        self._consecutive_errors = 0
        self._logged_missing_access_token = False
        self._logged_missing_device_id = False

        # Rate limiting: sliding window of call timestamps
        self._call_timestamps: deque[float] = deque()
        self._monthly_call_count = 0
        self._month_started = datetime.now(timezone.utc).month
        self._rate_limited_until: float = 0
        self._quota_exhausted = False

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Aqara API."""
        if not self.access_token:
            if not self._logged_missing_access_token:
                _LOGGER.warning("Aqara FP2 polling skipped: access_token is not configured")
                self._logged_missing_access_token = True
            return {}

        if not self.device_id:
            if not self._logged_missing_device_id:
                _LOGGER.warning("Aqara FP2 polling skipped: device_id is not configured")
                self._logged_missing_device_id = True
            return {}

        # Check rate limits before making any calls
        skip_reason = self._check_rate_limits()
        if skip_reason:
            _LOGGER.debug("Aqara FP2 polling skipped: %s", skip_reason)
            return {}

        # If intent already confirmed, only try that one (saves API calls)
        if self._intent_confirmed:
            intents_to_try = [self._working_intent]
        else:
            intents_to_try = self._build_intent_order()

        try:
            last_error: dict[str, Any] | None = None
            for intent in intents_to_try:
                result = await self._request(intent, {"did": self.device_id})
                if result and result.get("code") == 0:
                    self._working_intent = intent
                    self._intent_confirmed = True
                    self._on_success()
                    return result.get("result", {})

                if isinstance(result, dict):
                    last_error = result
                    code = result.get("code")
                    self._log_intent_failure(intent, result)

                    # Rate limited by server — stop immediately, wait
                    if code in RATE_LIMIT_CODES:
                        self._on_rate_limited()
                        return {}

                    # Token expired — try refresh before giving up
                    if code in TOKEN_EXPIRY_CODES:
                        refreshed = await self._try_refresh_token()
                        if refreshed:
                            retry = await self._request(intent, {"did": self.device_id})
                            if retry and retry.get("code") == 0:
                                self._working_intent = intent
                                self._intent_confirmed = True
                                self._on_success()
                                return retry.get("result", {})
                        self._on_fatal_error()
                        return {}

                    if code in FATAL_RESPONSE_CODES:
                        _LOGGER.error(
                            "Aqara FP2 fatal API error for device %s; "
                            "intent=%s code=%s message=%s detail=%s",
                            self.device_id,
                            intent,
                            code,
                            result.get("message"),
                            result.get("msgDetails") or result.get("messageDetail"),
                        )
                        self._on_fatal_error()
                        return {}
                else:
                    _LOGGER.debug("Aqara FP2 intent failed: %s -> %s", intent, result)

            # All intents failed
            self._on_error()
            _LOGGER.error(
                "All Aqara FP2 intents failed for device %s; "
                "last_code=%s last_message=%s last_detail=%s "
                "(consecutive_errors=%d, next poll in %s)",
                self.device_id,
                last_error.get("code") if isinstance(last_error, dict) else None,
                last_error.get("message") if isinstance(last_error, dict) else None,
                (
                    last_error.get("msgDetails") or last_error.get("messageDetail")
                    if isinstance(last_error, dict)
                    else None
                ),
                self._consecutive_errors,
                self.update_interval,
            )
            return {}
        except Exception as err:  # noqa: BLE001
            self._on_error()
            _LOGGER.error("Error fetching Aqara FP2 data: %s", err)
            return {}

    def _build_intent_order(self) -> list[str]:
        """Build deduplicated intent list with working intent first."""
        intents = [self._working_intent, DEFAULT_INTENT, *FALLBACK_INTENTS]
        seen: set[str] = set()
        ordered: list[str] = []
        for intent in intents:
            if intent not in seen:
                seen.add(intent)
                ordered.append(intent)
        return ordered

    def _on_success(self) -> None:
        """Reset error state and restore normal polling interval."""
        if self._consecutive_errors > 0:
            _LOGGER.info(
                "Aqara FP2 recovered after %d consecutive errors, "
                "restoring %s polling interval",
                self._consecutive_errors,
                SCAN_INTERVAL,
            )
        self._consecutive_errors = 0
        self.update_interval = SCAN_INTERVAL

    def _on_error(self) -> None:
        """Increment error count and apply backoff if needed."""
        self._consecutive_errors += 1
        self._intent_confirmed = False  # re-probe intents on next attempt
        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self.update_interval = SCAN_INTERVAL_BACKOFF
            _LOGGER.warning(
                "Aqara FP2: %d consecutive errors, backing off to %s",
                self._consecutive_errors,
                SCAN_INTERVAL_BACKOFF,
            )

    def _on_fatal_error(self) -> None:
        """Apply long backoff for fatal/auth errors."""
        self._consecutive_errors += 1
        self._intent_confirmed = False
        self.update_interval = SCAN_INTERVAL_FATAL
        _LOGGER.error(
            "Aqara FP2: fatal error, backing off to %s",
            SCAN_INTERVAL_FATAL,
        )

    def _check_rate_limits(self) -> str | None:
        """Check all rate limits and return skip reason, or None if OK."""
        now = time.monotonic()

        # Server told us to wait
        if now < self._rate_limited_until:
            remaining = int(self._rate_limited_until - now)
            return f"rate limited by server, {remaining}s remaining"

        # Monthly quota exhausted
        current_month = datetime.now(timezone.utc).month
        if current_month != self._month_started:
            # New month — reset counter
            self._month_started = current_month
            self._monthly_call_count = 0
            self._quota_exhausted = False
            if self.update_interval == SCAN_INTERVAL_QUOTA_EXHAUSTED:
                self.update_interval = SCAN_INTERVAL
                _LOGGER.info("Aqara FP2: new month, restoring normal polling")

        if self._quota_exhausted:
            return "monthly quota exhausted, waiting for next month"

        if self._monthly_call_count >= MONTHLY_QUOTA_MAX:
            self._quota_exhausted = True
            self.update_interval = SCAN_INTERVAL_QUOTA_EXHAUSTED
            _LOGGER.warning(
                "Aqara FP2: monthly API quota approaching limit (%d/%d), "
                "switching to %s polling",
                self._monthly_call_count,
                MONTHLY_QUOTA_MAX,
                SCAN_INTERVAL_QUOTA_EXHAUSTED,
            )
            return "monthly quota exhausted"

        # 5-minute sliding window: 300 calls per 5 min
        window_start = now - RATE_LIMIT_WINDOW
        while self._call_timestamps and self._call_timestamps[0] < window_start:
            self._call_timestamps.popleft()

        if len(self._call_timestamps) >= RATE_LIMIT_MAX_CALLS:
            oldest_in_window = self._call_timestamps[0]
            wait_until = oldest_in_window + RATE_LIMIT_WINDOW
            self._rate_limited_until = wait_until
            remaining = int(wait_until - now)
            self.update_interval = SCAN_INTERVAL_RATE_LIMITED
            _LOGGER.warning(
                "Aqara FP2: approaching 5-min rate limit (%d/%d calls), "
                "pausing for %ds",
                len(self._call_timestamps),
                RATE_LIMIT_MAX_CALLS,
                remaining,
            )
            return f"5-min rate limit, pausing {remaining}s"

        return None

    def _record_api_call(self) -> None:
        """Record an API call for rate limiting."""
        self._call_timestamps.append(time.monotonic())
        self._monthly_call_count += 1

    def _on_rate_limited(self) -> None:
        """Handle rate limit response from server."""
        self._rate_limited_until = time.monotonic() + RATE_LIMIT_WINDOW
        self.update_interval = SCAN_INTERVAL_RATE_LIMITED
        _LOGGER.warning(
            "Aqara FP2: rate limited by server, pausing polling for %ds",
            RATE_LIMIT_WINDOW,
        )

    async def _try_refresh_token(self) -> bool:
        """Attempt to refresh the access token using refresh_token."""
        if not self.refresh_token:
            _LOGGER.warning("Aqara FP2: access token expired but no refresh_token configured")
            return False

        _LOGGER.info("Aqara FP2: attempting token refresh")
        result = await self._request(
            TOKEN_REFRESH_INTENT,
            {"refreshToken": self.refresh_token},
        )

        if not isinstance(result, dict) or result.get("code") != 0:
            _LOGGER.error(
                "Aqara FP2: token refresh failed: code=%s message=%s",
                result.get("code") if isinstance(result, dict) else None,
                result.get("message") if isinstance(result, dict) else None,
            )
            return False

        token_data = result.get("result", {})
        new_access = token_data.get("accessToken")
        new_refresh = token_data.get("refreshToken")

        if not new_access:
            _LOGGER.error("Aqara FP2: token refresh returned empty accessToken")
            return False

        self.access_token = new_access
        if new_refresh:
            self.refresh_token = new_refresh

        _LOGGER.info("Aqara FP2: token refreshed successfully")
        return True

    def _log_intent_failure(self, intent: str, result: dict[str, Any]) -> None:
        """Log Aqara API failures with their actual response details."""
        _LOGGER.debug(
            "Aqara FP2 intent failed: intent=%s code=%s message=%s detail=%s",
            intent,
            result.get("code"),
            result.get("message"),
            result.get("msgDetails") or result.get("messageDetail"),
        )

    async def _request(self, intent: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make an Aqara V3 API request."""
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))

        params = {
            "Accesstoken": self.access_token,
            "Appid": APP_ID,
            "Keyid": KEY_ID,
            "Nonce": nonce,
            "Time": timestamp,
        }
        sorted_keys = sorted(params.keys())
        concat_str = "&".join(f"{key}={params[key]}" for key in sorted_keys)
        concat_str += APP_KEY
        sign = hashlib.md5(concat_str.lower().encode()).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "Accesstoken": self.access_token,
            "Appid": APP_ID,
            "Keyid": KEY_ID,
            "Nonce": nonce,
            "Time": timestamp,
            "Sign": sign,
            "Lang": "en",
        }
        payload = {
            "intent": intent,
            "data": data or {},
        }

        self._record_api_call()
        async with self.session.post(self.base_url, headers=headers, json=payload) as resp:
            return await resp.json(content_type=None)
