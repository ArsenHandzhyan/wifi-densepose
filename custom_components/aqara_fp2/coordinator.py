"""Shared coordinator for Aqara FP2 cloud polling."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    API_DOMAINS,
    CONF_ACCESS_TOKEN,
    CONF_APP_ID,
    CONF_APP_KEY,
    CONF_DEVICE_ID,
    CONF_KEY_ID,
    CONF_REFRESH_TOKEN,
    CONF_REGION,
    DEFAULT_APP_ID,
    DEFAULT_APP_KEY,
    DEFAULT_KEY_ID,
    DEVICE_INFO_INTENT,
    DOMAIN,
    MONTHLY_QUOTA_MAX,
    RATE_LIMIT_CODES,
    RATE_LIMIT_MAX_CALLS,
    RATE_LIMIT_WINDOW,
    RESOURCE_VALUE_INTENT,
    SCAN_INTERVAL,
    SCAN_INTERVAL_BACKOFF,
    SCAN_INTERVAL_FATAL,
    SCAN_INTERVAL_QUOTA_EXHAUSTED,
    SCAN_INTERVAL_RATE_LIMITED,
    TOKEN_EXPIRY_CODES,
    TOKEN_REFRESH_INTENT,
)

_LOGGER = logging.getLogger(__name__)
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

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize the coordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.config = {**config_entry.data, **config_entry.options}
        self.region = self.config.get(CONF_REGION, "europe")
        self.access_token = self.config.get(CONF_ACCESS_TOKEN)
        self.refresh_token = self.config.get(CONF_REFRESH_TOKEN)
        self.device_id = self.config.get(CONF_DEVICE_ID)
        self.app_id = self.config.get(CONF_APP_ID) or DEFAULT_APP_ID
        self.app_key = self.config.get(CONF_APP_KEY) or DEFAULT_APP_KEY
        self.key_id = self.config.get(CONF_KEY_ID) or DEFAULT_KEY_ID
        self.api_domain = API_DOMAINS.get(self.region, API_DOMAINS["europe"])
        self.base_url = f"https://{self.api_domain}/v3.0/open/api"
        self.session = async_get_clientsession(hass)
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

        try:
            device_info = await self._fetch_device_info()
            if not device_info:
                self._on_error()
                _LOGGER.error("Aqara FP2 device info lookup failed for %s", self.device_id)
                return {}

            subject_id = device_info.get("did") or self.device_id
            if not subject_id:
                self._on_error()
                _LOGGER.error("Aqara FP2 device info returned no usable did")
                return {}

            if subject_id != self.device_id:
                self.device_id = subject_id
                self._persist_entry_updates(device_id=subject_id)

            result = await self._request_with_token_refresh(
                RESOURCE_VALUE_INTENT,
                {"resources": [{"subjectId": subject_id}]},
            )
            if result and result.get("code") == 0:
                params = [
                    {
                        "resId": item.get("resourceId"),
                        "value": item.get("value"),
                        "subjectId": item.get("subjectId"),
                        "timeStamp": item.get("timeStamp"),
                    }
                    for item in (result.get("result") or [])
                    if isinstance(item, dict) and item.get("resourceId")
                ]
                self._on_success()
                return {
                    "params": params,
                    "device_info": device_info,
                }

            self._on_error()
            self._log_intent_failure(RESOURCE_VALUE_INTENT, result)
            _LOGGER.error(
                "Aqara FP2 resource query failed for device %s; "
                "last_code=%s last_message=%s last_detail=%s "
                "(consecutive_errors=%d, next poll in %s)",
                self.device_id,
                result.get("code") if isinstance(result, dict) else None,
                result.get("message") if isinstance(result, dict) else None,
                (
                    result.get("msgDetails") or result.get("messageDetail")
                    if isinstance(result, dict)
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
        self._persist_entry_updates(
            access_token=new_access,
            refresh_token=new_refresh or self.refresh_token,
        )

        _LOGGER.info("Aqara FP2: token refreshed successfully")
        return True

    def _persist_entry_updates(
        self,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
        app_id: str | None = None,
        app_key: str | None = None,
        key_id: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """Persist runtime credential updates back into the config entry."""
        updates = {
            CONF_ACCESS_TOKEN: access_token or self.access_token,
            CONF_REFRESH_TOKEN: refresh_token or self.refresh_token,
            CONF_APP_ID: app_id or self.app_id,
            CONF_APP_KEY: app_key or self.app_key,
            CONF_KEY_ID: key_id or self.key_id,
            CONF_DEVICE_ID: device_id or self.device_id,
        }
        data = {**self.config_entry.data, **updates}
        options = {**self.config_entry.options, **updates}
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=data,
            options=options,
        )
        self.config = {**data, **options}

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
        include_access_token = bool(self.access_token) and intent not in {
            TOKEN_REFRESH_INTENT,
            "config.auth.getAuthCode",
            "config.auth.getToken",
        }
        params = {
            "Appid": self.app_id,
            "Keyid": self.key_id,
            "Nonce": nonce,
            "Time": timestamp,
        }
        if include_access_token:
            params["Accesstoken"] = self.access_token
        sorted_keys = sorted(params.keys())
        concat_str = "&".join(f"{key}={params[key]}" for key in sorted_keys)
        concat_str += self.app_key
        sign = hashlib.md5(concat_str.lower().encode()).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "Appid": self.app_id,
            "Keyid": self.key_id,
            "Nonce": nonce,
            "Time": timestamp,
            "Sign": sign,
            "Lang": "en",
        }
        if include_access_token:
            headers["Accesstoken"] = self.access_token
        payload = {
            "intent": intent,
            "data": data or {},
        }

        self._record_api_call()
        async with self.session.post(self.base_url, headers=headers, json=payload) as resp:
            return await resp.json(content_type=None)

    async def _request_with_token_refresh(
        self,
        intent: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request and retry once after token refresh if needed."""
        result = await self._request(intent, data)
        if not isinstance(result, dict) or result.get("code") not in TOKEN_EXPIRY_CODES:
            return result

        refreshed = await self._try_refresh_token()
        if not refreshed:
            self._on_fatal_error()
            return result

        retry = await self._request(intent, data)
        return retry

    async def _fetch_device_info(self) -> dict[str, Any] | None:
        """Resolve the canonical Aqara subject did for the configured device."""
        queries: list[dict[str, Any]] = []
        if self.device_id:
            queries.append({"did": self.device_id})
        queries.append({})

        seen: set[tuple[tuple[str, Any], ...]] = set()
        for query in queries:
            marker = tuple(sorted(query.items()))
            if marker in seen:
                continue
            seen.add(marker)

            result = await self._request_with_token_refresh(DEVICE_INFO_INTENT, query)
            if not isinstance(result, dict):
                continue
            if result.get("code") != 0:
                self._log_intent_failure(DEVICE_INFO_INTENT, result)
                continue

            items = (result.get("result") or {}).get("data") or []
            if not items:
                continue

            if self.device_id:
                target = str(self.device_id).lower()
                for item in items:
                    item_did = str(item.get("did", "")).lower()
                    if item_did == target or item_did.endswith(target):
                        return item
            return items[0]

        return None
