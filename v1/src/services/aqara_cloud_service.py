"""
Aqara Open API service for FP2 resource access and message push support.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import math
import random
import time
from typing import Any, Optional

import httpx

from src.config.settings import Settings

logger = logging.getLogger(__name__)

PRESENCE_RESOURCE_ID = "3.51.85"
LIGHT_RESOURCE_ID = "0.4.85"
RSSI_RESOURCE_ID = "8.0.2026"
ONLINE_RESOURCE_ID = "8.0.2045"
ANGLE_RESOURCE_ID = "8.0.2116"
COORDINATES_RESOURCE_ID = "4.22.700"
MOVEMENT_EVENT_RESOURCE_ID = "13.27.85"
FALL_EVENT_RESOURCE_ID = "4.31.85"
AREA_ENTRY_COUNT_RESOURCE_ID = "13.120.85"
REALTIME_PEOPLE_RESOURCE_ID = "0.60.85"
PEOPLE_STATISTICS_RESOURCE_ID = "0.61.85"
WALKING_DISTANCE_RESOURCE_ID = "0.63.85"
PEOPLE_STATISTICS_SWITCH_RESOURCE_ID = "4.71.85"
WALKING_DISTANCE_SWITCH_RESOURCE_ID = "4.75.85"
ZONE_OCCUPANCY_PREFIX = "3."
ZONE_OCCUPANCY_SUFFIX = ".85"
ZONE_MINUTE_STAT_PREFIX = "0."
ZONE_STATISTICS_PREFIX = "13."
ZONE_STAT_BASE = 120

_CRITICAL_RESOURCE_IDS = {
    PRESENCE_RESOURCE_ID,
    ONLINE_RESOURCE_ID,
    LIGHT_RESOURCE_ID,
    RSSI_RESOURCE_ID,
    MOVEMENT_EVENT_RESOURCE_ID,
    COORDINATES_RESOURCE_ID,
}


class AqaraCloudError(RuntimeError):
    """Base Aqara cloud integration error."""


class AqaraCloudConfigurationError(AqaraCloudError):
    """Raised when Aqara cloud integration is not configured."""


class AqaraCloudAPIError(AqaraCloudError):
    """Raised when Aqara Open API returns an error response."""

    def __init__(
        self,
        intent: str,
        *,
        http_status: int,
        code: Any = None,
        message: str | None = None,
        details: Any = None,
    ):
        self.intent = intent
        self.http_status = http_status
        self.code = code
        self.details = details
        resolved_message = message or "Aqara API request failed"
        super().__init__(f"{intent} failed: {resolved_message} (http={http_status}, code={code})")


@dataclass
class AqaraCloudDevice:
    did: str
    name: str
    model: str
    firmware: str
    position_id: Optional[str]
    state: Optional[int]


def parse_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def parse_bool_flag(value: Any) -> bool | None:
    parsed = parse_int(value)
    if parsed is None:
        return None
    return parsed == 1


def zone_id_for_number(zone_number: int | None) -> str:
    if zone_number in (None, 0):
        return "detection_area"
    return f"zone_{zone_number}"


def _resource_sort_key(resource_id: str) -> tuple[int, ...]:
    parts = []
    for part in str(resource_id).split("."):
        parsed = parse_int(part)
        parts.append(parsed if parsed is not None else 999999)
    return tuple(parts)


def _stringify_write_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _decode_access_flags(access: Any) -> dict[str, Any]:
    access_int = parse_int(access) or 0
    readable = access_int in {1, 3, 5, 7}
    reportable = access_int in {2, 3, 6, 7}
    writable = access_int in {4, 5, 6, 7}
    access_labels = []
    if readable:
        access_labels.append("read")
    if writable:
        access_labels.append("write")
    if reportable:
        access_labels.append("report")
    return {
        "access": access_int,
        "readable": readable,
        "writable": writable,
        "reportable": reportable,
        "access_label": "/".join(access_labels) or "none",
    }


class AqaraCloudService:
    """Backend-side Aqara Open API client for FP2."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.access_token = settings.aqara_access_token
        self.refresh_token = settings.aqara_refresh_token
        self.open_id = settings.aqara_open_id
        self._device: AqaraCloudDevice | None = None
        self._resource_info: dict[str, dict[str, Any]] = {}
        self._last_resource_map: dict[str, dict[str, Any]] = {}
        self._last_confirmed_targets: list[dict[str, Any]] = []
        self._last_confirmed_zone: str | None = None
        self._last_confirmed_targets_at: float | None = None
        self._token_lock = asyncio.Lock()
        self._device_lock = asyncio.Lock()
        self.base_target_hold_seconds = 4.0
        self.active_motion_hold_seconds = 8.0

    @property
    def api_url(self) -> str:
        return f"https://{self.settings.aqara_api_domain}/v3.0/open/api"

    @property
    def is_configured(self) -> bool:
        required = [
            self.settings.aqara_api_domain,
            self.settings.aqara_app_id,
            self.settings.aqara_app_key,
            self.settings.aqara_key_id,
            self.settings.fp2_device_id,
        ]
        has_token = bool(self.access_token or self.refresh_token)
        return all(required) and has_token

    def get_configuration_status(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured,
            "api_domain": self.settings.aqara_api_domain,
            "app_id_present": bool(self.settings.aqara_app_id),
            "app_key_present": bool(self.settings.aqara_app_key),
            "key_id_present": bool(self.settings.aqara_key_id),
            "access_token_present": bool(self.access_token),
            "refresh_token_present": bool(self.refresh_token),
            "open_id_present": bool(self.open_id),
            "fp2_device_id_present": bool(self.settings.fp2_device_id),
        }

    def _ensure_configured(self) -> None:
        if self.is_configured:
            return
        raise AqaraCloudConfigurationError(
            "Aqara Open API is not fully configured. "
            "Check AQARA_APP_ID, AQARA_APP_KEY, AQARA_KEY_ID, AQARA_ACCESS_TOKEN/AQARA_REFRESH_TOKEN, and FP2_DEVICE_ID."
        )

    def _sign_headers(self, access_token: str = "") -> dict[str, str]:
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))
        params = {
            "Appid": self.settings.aqara_app_id,
            "Keyid": self.settings.aqara_key_id,
            "Nonce": nonce,
            "Time": timestamp,
        }
        if access_token:
            params["Accesstoken"] = access_token

        sign_input = "&".join(f"{key}={params[key]}" for key in sorted(params))
        sign = hashlib.md5(f"{sign_input}{self.settings.aqara_app_key}".lower().encode()).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "Appid": self.settings.aqara_app_id,
            "Keyid": self.settings.aqara_key_id,
            "Nonce": nonce,
            "Time": timestamp,
            "Sign": sign,
            "Lang": "en",
        }
        if access_token:
            headers["Accesstoken"] = access_token
        return headers

    async def _post(self, intent: str, data: Any, *, access_token: str = "") -> tuple[int, dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    self.api_url,
                    headers=self._sign_headers(access_token),
                    json={"intent": intent, "data": data},
                )
        except httpx.HTTPError as exc:
            raise AqaraCloudAPIError(
                intent,
                http_status=502,
                message=str(exc),
            ) from exc
        try:
            payload = response.json()
        except Exception as exc:
            raise AqaraCloudAPIError(
                intent,
                http_status=response.status_code,
                message=f"invalid JSON response: {exc}",
            ) from exc
        return response.status_code, payload

    async def refresh_access_token(self, *, force: bool = False) -> str:
        self._ensure_configured()
        async with self._token_lock:
            if self.access_token and not force:
                return self.access_token
            if not self.refresh_token:
                raise AqaraCloudConfigurationError("AQARA_REFRESH_TOKEN is missing")

            http_status, body = await self._post(
                "config.auth.refreshToken",
                {"refreshToken": self.refresh_token},
            )
            if http_status != 200 or body.get("code") != 0:
                raise AqaraCloudAPIError(
                    "config.auth.refreshToken",
                    http_status=http_status,
                    code=body.get("code"),
                    message=body.get("message"),
                    details=body,
                )

            result = body.get("result") or {}
            access_token = result.get("accessToken")
            refresh_token = result.get("refreshToken")
            if not access_token or not refresh_token:
                raise AqaraCloudAPIError(
                    "config.auth.refreshToken",
                    http_status=http_status,
                    code=body.get("code"),
                    message="response did not include updated tokens",
                    details=body,
                )

            self.access_token = access_token
            self.refresh_token = refresh_token
            self.open_id = result.get("openId", self.open_id)
            self.settings.aqara_access_token = access_token
            self.settings.aqara_refresh_token = refresh_token
            self.settings.aqara_open_id = self.open_id
            logger.info("Aqara access token refreshed in backend service")
            return access_token

    async def _api_query(self, intent: str, data: Any, *, retry_refresh: bool = True) -> Any:
        self._ensure_configured()
        if not self.access_token:
            await self.refresh_access_token(force=True)

        http_status, body = await self._post(intent, data, access_token=self.access_token)
        if http_status == 200 and body.get("code") == 0:
            return body.get("result")

        error_code = body.get("code") if isinstance(body, dict) else None
        if retry_refresh and error_code in {108, 401, 403} and self.refresh_token:
            await self.refresh_access_token(force=True)
            return await self._api_query(intent, data, retry_refresh=False)

        raise AqaraCloudAPIError(
            intent,
            http_status=http_status,
            code=error_code,
            message=body.get("message") if isinstance(body, dict) else "request failed",
            details=body,
        )

    @property
    def candidate_dids(self) -> list[str]:
        raw = (self.settings.fp2_device_id or "").strip()
        if not raw:
            return []
        candidates = [raw]
        lowered = raw.lower()
        if not lowered.startswith("lumi1."):
            candidates.append(f"lumi1.{lowered}")
        return list(dict.fromkeys(candidates))

    async def ensure_device_ready(self, *, force_refresh: bool = False) -> AqaraCloudDevice:
        self._ensure_configured()
        async with self._device_lock:
            if self._device is not None and self._resource_info and not force_refresh:
                return self._device
            if force_refresh:
                self._device = None
                self._resource_info = {}

            device = await self._resolve_device()
            resource_info = await self._load_resource_info(device.model)
            self._device = device
            self._resource_info = resource_info
            return device

    async def _resolve_device(self) -> AqaraCloudDevice:
        for did in self.candidate_dids:
            result = await self._api_query(
                "query.device.info",
                {"dids": [did], "positionId": "", "pageNum": 1, "pageSize": 50},
            )
            data = (result or {}).get("data") or []
            if data:
                item = data[0]
                return AqaraCloudDevice(
                    did=item.get("did"),
                    name=item.get("deviceName") or self.settings.fp2_name or "Aqara FP2",
                    model=item.get("model") or self.settings.fp2_model or "lumi.motion.agl001",
                    firmware=item.get("firmwareVersion") or self.settings.fp2_firmware or "",
                    position_id=item.get("positionId"),
                    state=item.get("state"),
                )

        result = await self._api_query(
            "query.device.info",
            {"dids": [], "positionId": "", "pageNum": 1, "pageSize": 200},
        )
        data = (result or {}).get("data") or []
        needle = (self.settings.fp2_device_id or "").lower()
        for item in data:
            did = str(item.get("did", "")).lower()
            if needle and did.endswith(needle):
                return AqaraCloudDevice(
                    did=item.get("did"),
                    name=item.get("deviceName") or self.settings.fp2_name or "Aqara FP2",
                    model=item.get("model") or self.settings.fp2_model or "lumi.motion.agl001",
                    firmware=item.get("firmwareVersion") or self.settings.fp2_firmware or "",
                    position_id=item.get("positionId"),
                    state=item.get("state"),
                )

        raise AqaraCloudAPIError(
            "query.device.info",
            http_status=200,
            code="device_not_found",
            message="Unable to resolve FP2 cloud DID from Aqara API",
        )

    async def _load_resource_info(self, model: str) -> dict[str, dict[str, Any]]:
        result = await self._api_query("query.resource.info", {"model": model})
        mapping: dict[str, dict[str, Any]] = {}
        for item in result or []:
            resource_id = item.get("resourceId")
            if resource_id:
                mapping[str(resource_id)] = item
        return mapping

    def get_device_summary(self) -> dict[str, Any]:
        device = self._device
        return {
            "name": self.settings.fp2_name or (device.name if device else "Aqara FP2"),
            "model": self.settings.fp2_model or (device.model if device else None),
            "device_id": self.settings.fp2_device_id or None,
            "cloud_did": device.did if device else None,
            "firmware": self.settings.fp2_firmware or (device.firmware if device else None),
            "position_id": device.position_id if device else None,
            "api_domain": self.settings.aqara_api_domain,
            "transport": "Aqara Cloud",
        }

    def _resource_map(self, resources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in resources:
            resource_id = item.get("resourceId")
            if not resource_id:
                continue
            normalized = dict(item)
            normalized["resourceId"] = str(resource_id)
            if not normalized.get("subjectId") and self._device is not None:
                normalized["subjectId"] = self._device.did
            if normalized.get("timeStamp") is None:
                fallback_time = item.get("time") or item.get("timestamp")
                normalized["timeStamp"] = parse_int(fallback_time) or int(time.time() * 1000)
            result[str(resource_id)] = normalized
        return result

    def _resource_value(self, resource_map: dict[str, dict[str, Any]], resource_id: str) -> Any:
        return (resource_map.get(resource_id) or {}).get("value")

    async def fetch_resource_values(self, *, resource_ids: list[str] | None = None) -> list[dict[str, Any]]:
        device = await self.ensure_device_ready()
        resource_request: dict[str, Any] = {"subjectId": device.did}
        if resource_ids:
            resource_request["resourceIds"] = resource_ids
        result = await self._api_query("query.resource.value", {"resources": [resource_request]})
        if not isinstance(result, list):
            raise AqaraCloudAPIError(
                "query.resource.value",
                http_status=200,
                code="invalid_payload",
                message="expected list result",
                details=result,
            )
        resource_map = self._resource_map(result)
        self._last_resource_map.update(resource_map)
        return list(resource_map.values())

    def _has_minimum_resource_state(self, resource_map: dict[str, dict[str, Any]]) -> bool:
        return _CRITICAL_RESOURCE_IDS.issubset(resource_map.keys())

    async def merge_resource_report(
        self,
        resources: list[dict[str, Any]],
        *,
        fetch_full_if_needed: bool = False,
    ) -> list[dict[str, Any]]:
        await self.ensure_device_ready()
        merged = dict(self._last_resource_map)
        merged.update(self._resource_map(resources))

        if fetch_full_if_needed and not self._has_minimum_resource_state(merged):
            full_snapshot = await self.fetch_resource_values()
            merged = self._resource_map(full_snapshot)
            merged.update(self._resource_map(resources))

        self._last_resource_map = merged
        return list(merged.values())

    def _max_timestamp(self, resources: list[dict[str, Any]]) -> float:
        timestamps = [parse_int(item.get("timeStamp")) for item in resources]
        valid = [value for value in timestamps if value is not None]
        if not valid:
            return time.time()
        return max(valid) / 1000.0

    def _parse_targets(self, resource_map: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
        raw = self._resource_value(resource_map, COORDINATES_RESOURCE_ID)
        current_zone = None
        if not raw:
            return [], current_zone

        try:
            coordinates = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to parse FP2 coordinate payload: %s", raw)
            return [], current_zone

        targets: list[dict[str, Any]] = []
        for index, item in enumerate(coordinates if isinstance(coordinates, list) else []):
            if not isinstance(item, dict):
                continue
            if str(item.get("state")) != "1":
                continue
            range_id = parse_int(item.get("rangeId"))
            zone_id = zone_id_for_number(range_id)
            if current_zone is None:
                current_zone = zone_id
            x = parse_float(item.get("x")) or 0.0
            y = parse_float(item.get("y")) or 0.0
            distance = math.sqrt(x * x + y * y)
            angle = math.degrees(math.atan2(y, x)) if (x or y) else 0.0
            targets.append(
                {
                    "target_id": f"target_{item.get('id', index)}",
                    "zone_id": zone_id,
                    "x": x,
                    "y": y,
                    "distance": round(distance, 2),
                    "angle": round(angle, 1),
                    "activity": "present",
                    "confidence": 0.95,
                    "target_type": item.get("targetType"),
                    "range_id": range_id,
                }
            )
        return targets, current_zone

    def _parse_zones(
        self,
        resource_map: dict[str, dict[str, Any]],
        *,
        presence: bool,
        active_targets: list[dict[str, Any]],
        realtime_people_count: int | None,
    ) -> list[dict[str, Any]]:
        target_counts_by_zone: dict[str, int] = {}
        for target in active_targets:
            zone_id = str(target.get("zone_id") or "detection_area")
            target_counts_by_zone[zone_id] = target_counts_by_zone.get(zone_id, 0) + 1

        zones: list[dict[str, Any]] = []
        for zone_number in range(1, 31):
            occupancy_id = f"{ZONE_OCCUPANCY_PREFIX}{zone_number}{ZONE_OCCUPANCY_SUFFIX}"
            occupied = str(self._resource_value(resource_map, occupancy_id) or "0") == "1"
            zone_id = zone_id_for_number(zone_number)
            target_count = target_counts_by_zone.get(zone_id, 0)
            if not occupied and target_count <= 0:
                continue
            zones.append(
                {
                    "zone_id": zone_id,
                    "name": f"Zone {zone_number}",
                    "occupied": occupied,
                    "target_count": max(target_count, 1 if occupied else 0),
                }
            )

        if zones:
            return zones

        target_hint = realtime_people_count
        if target_hint is None:
            target_hint = len(active_targets) if active_targets else 0
        return [
            {
                "zone_id": "detection_area",
                "name": "Detection Area",
                "occupied": presence,
                "target_count": max(target_hint, len(active_targets), 1 if presence else 0),
            }
        ]

    def _parse_zone_metrics(self, resource_map: dict[str, dict[str, Any]]) -> dict[str, dict[str, int]]:
        zone_metrics: dict[str, dict[str, int]] = {}

        area_entries_10s = parse_int(self._resource_value(resource_map, AREA_ENTRY_COUNT_RESOURCE_ID))
        people_count_1m = parse_int(self._resource_value(resource_map, PEOPLE_STATISTICS_RESOURCE_ID))
        if area_entries_10s is not None or people_count_1m is not None:
            zone_metrics["detection_area"] = {
                "people_entries_10s": area_entries_10s or 0,
                "people_count_1m": people_count_1m or 0,
            }

        for zone_number in range(1, 31):
            zone_id = zone_id_for_number(zone_number)
            minute_id = f"{ZONE_MINUTE_STAT_PREFIX}{ZONE_STAT_BASE + zone_number}{ZONE_OCCUPANCY_SUFFIX}"
            entry_id = f"{ZONE_STATISTICS_PREFIX}{ZONE_STAT_BASE + zone_number}{ZONE_OCCUPANCY_SUFFIX}"
            people_entries_10s = parse_int(self._resource_value(resource_map, entry_id))
            zone_people_count_1m = parse_int(self._resource_value(resource_map, minute_id))
            if people_entries_10s is None and zone_people_count_1m is None:
                continue
            zone_metrics[zone_id] = {
                "people_entries_10s": people_entries_10s or 0,
                "people_count_1m": zone_people_count_1m or 0,
            }

        return zone_metrics

    def _parse_advanced_metrics(self, resource_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            "realtime_people_count": parse_int(self._resource_value(resource_map, REALTIME_PEOPLE_RESOURCE_ID)),
            "people_count_1m": parse_int(self._resource_value(resource_map, PEOPLE_STATISTICS_RESOURCE_ID)),
            "area_entries_10s": parse_int(self._resource_value(resource_map, AREA_ENTRY_COUNT_RESOURCE_ID)),
            "walking_distance_m": parse_float(self._resource_value(resource_map, WALKING_DISTANCE_RESOURCE_ID)),
            "people_statistics_enabled": parse_bool_flag(
                self._resource_value(resource_map, PEOPLE_STATISTICS_SWITCH_RESOURCE_ID)
            ),
            "walking_distance_enabled": parse_bool_flag(
                self._resource_value(resource_map, WALKING_DISTANCE_SWITCH_RESOURCE_ID)
            ),
        }

    def _resource_values(self, resource_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            resource_id: item.get("value")
            for resource_id, item in resource_map.items()
            if item.get("value") not in (None, "")
        }

    def _resource_labels(self, resource_values: dict[str, Any]) -> dict[str, str]:
        labels: dict[str, str] = {}
        for resource_id in resource_values:
            meta = self._resource_info.get(resource_id) or {}
            label = meta.get("name") or meta.get("description")
            if label:
                labels[resource_id] = str(label)
        return labels

    def _hold_window_for_event(self, movement_event: int | None) -> float:
        if movement_event in {6, 7, 8, 9, 10}:
            return self.active_motion_hold_seconds
        return self.base_target_hold_seconds

    def _build_held_targets(
        self,
        *,
        event_timestamp: float,
        movement_event: int | None,
    ) -> tuple[list[dict[str, Any]], float | None]:
        if not self._last_confirmed_targets or self._last_confirmed_targets_at is None:
            return [], None

        hold_age_sec = max(0.0, event_timestamp - self._last_confirmed_targets_at)
        if hold_age_sec > self._hold_window_for_event(movement_event):
            return [], None

        held_targets: list[dict[str, Any]] = []
        for target in self._last_confirmed_targets:
            held = dict(target)
            held["activity"] = "held"
            held["confidence"] = min(float(target.get("confidence", 0.95) or 0.95), 0.6)
            held["held"] = True
            held["hold_age_sec"] = round(hold_age_sec, 2)
            held_targets.append(held)
        return held_targets, round(hold_age_sec, 2)

    async def build_pose_payload_from_resources(self, resources: list[dict[str, Any]]) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        resource_map = self._resource_map(resources)
        if resource_map:
            self._last_resource_map = resource_map

        presence = str(self._resource_value(resource_map, PRESENCE_RESOURCE_ID) or "0") == "1"
        light_level = parse_float(self._resource_value(resource_map, LIGHT_RESOURCE_ID))
        rssi = parse_int(self._resource_value(resource_map, RSSI_RESOURCE_ID))
        online = str(self._resource_value(resource_map, ONLINE_RESOURCE_ID) or "0") == "1"
        movement_event = parse_int(self._resource_value(resource_map, MOVEMENT_EVENT_RESOURCE_ID))
        fall_state = parse_int(self._resource_value(resource_map, FALL_EVENT_RESOURCE_ID))
        sensor_angle = parse_float(self._resource_value(resource_map, ANGLE_RESOURCE_ID))
        advanced_metrics = self._parse_advanced_metrics(resource_map)
        live_targets, current_zone = self._parse_targets(resource_map)
        event_timestamp = time.time()
        coordinates_source = "live"
        coordinates_hold_age_sec = None

        if live_targets:
            for target in live_targets:
                target["held"] = False
                target["hold_age_sec"] = 0.0
            self._last_confirmed_targets = [dict(target) for target in live_targets]
            self._last_confirmed_targets_at = event_timestamp
            self._last_confirmed_zone = current_zone
            targets = live_targets
        elif presence:
            held_targets, hold_age = self._build_held_targets(
                event_timestamp=event_timestamp,
                movement_event=movement_event,
            )
            if held_targets:
                targets = held_targets
                coordinates_source = "hold"
                coordinates_hold_age_sec = hold_age
                current_zone = current_zone or self._last_confirmed_zone
            else:
                targets = []
                coordinates_source = "none"
        else:
            targets = []
            coordinates_source = "none"
            self._last_confirmed_targets = []
            self._last_confirmed_targets_at = None
            self._last_confirmed_zone = None

        zones = self._parse_zones(
            resource_map,
            presence=presence,
            active_targets=targets,
            realtime_people_count=advanced_metrics["realtime_people_count"],
        )
        zone_metrics = self._parse_zone_metrics(resource_map)
        resource_values = self._resource_values(resource_map)
        device_timestamp = self._max_timestamp(resources)

        return {
            "timestamp": event_timestamp,
            "presence": presence,
            "zones": zones,
            "targets": targets,
            "light_level": light_level,
            "source": "aqara_cloud",
            "raw_attributes": {
                "source": "aqara_cloud",
                "transport": "aqara_cloud",
                "push_time": time.time(),
                "device_timestamp": device_timestamp,
                "current_zone": current_zone,
                "rssi": rssi,
                "online": online,
                "movement_event": movement_event,
                "fall_state": fall_state,
                "sensor_angle": sensor_angle,
                "coordinates": targets,
                "live_coordinates": live_targets,
                "coordinates_source": coordinates_source,
                "coordinates_hold_age_sec": coordinates_hold_age_sec,
                "advanced_metrics": advanced_metrics,
                "zone_metrics": zone_metrics,
                "resource_values": resource_values,
                "resource_labels": self._resource_labels(resource_values),
            },
            "device": {
                "name": self.settings.fp2_name or device.name,
                "model": self.settings.fp2_model or device.model,
                "device_id": self.settings.fp2_device_id or device.did,
                "cloud_did": device.did,
                "firmware": device.firmware or self.settings.fp2_firmware,
                "transport": "Aqara Cloud",
            },
            "connection": {
                "transport": "aqara_cloud",
                "state": "live" if online else "offline",
                "api_domain": self.settings.aqara_api_domain,
                "position_id": device.position_id,
                "online": online,
                "rssi": rssi,
                "targets": len(targets),
                "coordinates_source": coordinates_source,
                "realtime_people_count": advanced_metrics["realtime_people_count"],
                "people_count_1m": advanced_metrics["people_count_1m"],
                "walking_distance_m": advanced_metrics["walking_distance_m"],
            },
        }

    async def fetch_current_pose_payload(self) -> dict[str, Any]:
        resources = await self.fetch_resource_values()
        return await self.build_pose_payload_from_resources(resources)

    async def get_resource_catalog(
        self,
        *,
        include_values: bool = False,
        resource_ids: list[str] | None = None,
        writable_only: bool = False,
        reportable_only: bool = False,
    ) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        selected = set(resource_ids or [])
        current_values = self._last_resource_map
        if include_values:
            await self.fetch_resource_values(resource_ids=resource_ids or None)
            current_values = self._last_resource_map

        resources: list[dict[str, Any]] = []
        for resource_id in sorted(self._resource_info.keys(), key=_resource_sort_key):
            if selected and resource_id not in selected:
                continue
            meta = dict(self._resource_info[resource_id])
            access_flags = _decode_access_flags(meta.get("access"))
            if writable_only and not access_flags["writable"]:
                continue
            if reportable_only and not access_flags["reportable"]:
                continue

            current = current_values.get(resource_id) if current_values else None
            resources.append(
                {
                    "resource_id": resource_id,
                    "name": meta.get("name"),
                    "description": meta.get("description"),
                    "model": meta.get("model") or device.model,
                    "default_value": meta.get("defaultValue"),
                    "min_value": meta.get("minValue"),
                    "max_value": meta.get("maxValue"),
                    "unit": meta.get("unit"),
                    "enums": meta.get("enums"),
                    **access_flags,
                    "current_value": current.get("value") if current else None,
                    "time_stamp": current.get("timeStamp") if current else None,
                }
            )

        return {
            "device": self.get_device_summary(),
            "count": len(resources),
            "include_values": include_values,
            "resources": resources,
        }

    async def write_resource(self, *, resource_id: str, value: Any, subject_id: str | None = None) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        normalized_value = _stringify_write_value(value)
        data = [
            {
                "subjectId": subject_id or device.did,
                "resources": [{"resourceId": resource_id, "value": normalized_value}],
            }
        ]
        await self._api_query("write.resource.device", data)
        logger.info("Wrote Aqara resource %s=%s", resource_id, normalized_value)
        return {
            "resource_id": resource_id,
            "value": normalized_value,
            "subject_id": subject_id or device.did,
            "written_at": int(time.time() * 1000),
        }

    async def fetch_resource_history(
        self,
        *,
        resource_ids: list[str],
        start_time: int,
        end_time: int | None = None,
        size: int | None = None,
        scan_id: str | None = None,
        subject_id: str | None = None,
    ) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        payload: dict[str, Any] = {
            "subjectId": subject_id or device.did,
            "resourceIds": resource_ids,
            "startTime": str(start_time),
        }
        if end_time is not None:
            payload["endTime"] = str(end_time)
        if size is not None:
            payload["size"] = size
        if scan_id:
            payload["scanId"] = scan_id

        result = await self._api_query("fetch.resource.history", payload)
        rows = (result or {}).get("data") or []
        return {
            "device": self.get_device_summary(),
            "scan_id": (result or {}).get("scanId"),
            "count": len(rows),
            "resource_labels": self._resource_labels({row.get("resourceId"): row.get("value") for row in rows if row.get("resourceId")}),
            "data": rows,
        }

    async def fetch_resource_statistics(
        self,
        *,
        resource_ids: list[str],
        start_time: int,
        dimension: str,
        aggr_types: list[int],
        end_time: int | None = None,
        size: int | None = None,
        scan_id: str | None = None,
        subject_id: str | None = None,
    ) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        payload: dict[str, Any] = {
            "resources": {
                "subjectId": subject_id or device.did,
                "resourceIds": resource_ids,
                "aggrTypes": aggr_types,
            },
            "startTime": str(start_time),
            "dimension": dimension,
        }
        if end_time is not None:
            payload["endTime"] = str(end_time)
        if size is not None:
            payload["size"] = size
        if scan_id:
            payload["scanId"] = scan_id

        result = await self._api_query("fetch.resource.statistics", payload)
        rows = (result or {}).get("data") or []
        return {
            "device": self.get_device_summary(),
            "scan_id": (result or {}).get("scanId"),
            "count": len(rows),
            "dimension": dimension,
            "aggr_types": aggr_types,
            "resource_labels": self._resource_labels({row.get("resourceId"): row.get("value") for row in rows if row.get("resourceId")}),
            "data": rows,
        }

    async def subscribe_resources(
        self,
        *,
        resource_ids: list[str],
        attach: str | None = None,
        subject_id: str | None = None,
    ) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        payload: dict[str, Any] = {
            "resources": [
                {
                    "subjectId": subject_id or device.did,
                    "resourceIds": resource_ids,
                }
            ]
        }
        if attach:
            payload["resources"][0]["attach"] = attach
        await self._api_query("config.resource.subscribe", payload)
        return {
            "subject_id": subject_id or device.did,
            "resource_ids": resource_ids,
            "attach": attach,
            "subscribed": True,
        }

    async def unsubscribe_resources(
        self,
        *,
        resource_ids: list[str],
        subject_id: str | None = None,
    ) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        payload = {
            "resources": [
                {
                    "subjectId": subject_id or device.did,
                    "resourceIds": resource_ids,
                }
            ]
        }
        await self._api_query("config.resource.unsubscribe", payload)
        return {
            "subject_id": subject_id or device.did,
            "resource_ids": resource_ids,
            "subscribed": False,
        }

    async def get_push_errors(
        self,
        *,
        open_id: str | None = None,
        msg_type: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        size: int | None = None,
        scan_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_configured()
        payload: dict[str, Any] = {
            "appId": self.settings.aqara_app_id,
        }
        effective_open_id = open_id or self.open_id
        if effective_open_id:
            payload["openId"] = effective_open_id
        if msg_type:
            payload["msgType"] = msg_type
        if start_time is not None:
            payload["startTime"] = start_time
        if end_time is not None:
            payload["endTime"] = end_time
        if size is not None:
            payload["size"] = size
        if scan_id:
            payload["scanId"] = scan_id

        result = await self._api_query("query.push.errorMsg", payload)
        messages = (result or {}).get("msg") or []
        parsed_messages = []
        for item in messages:
            parsed = dict(item)
            content = item.get("content")
            if isinstance(content, str):
                try:
                    parsed["content_parsed"] = json.loads(content)
                except json.JSONDecodeError:
                    parsed["content_parsed"] = None
            parsed_messages.append(parsed)
        return {
            "scan_id": (result or {}).get("scanId"),
            "count": len(parsed_messages),
            "messages": parsed_messages,
        }

    def _extract_resource_report_items(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        data = message.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("resources"), list):
                data = data.get("resources")
            elif data.get("resourceId"):
                data = [data]
        if not isinstance(data, list):
            return []

        rows = []
        for item in data:
            if not isinstance(item, dict):
                continue
            resource_id = item.get("resourceId") or item.get("resource_id")
            if not resource_id:
                continue
            rows.append(
                {
                    "subjectId": item.get("subjectId") or item.get("did") or item.get("deviceId"),
                    "resourceId": str(resource_id),
                    "value": item.get("value"),
                    "timeStamp": parse_int(item.get("time")) or parse_int(item.get("timeStamp")) or int(time.time() * 1000),
                    "statusCode": item.get("statusCode"),
                    "triggerSource": item.get("triggerSource"),
                    "attach": item.get("attach"),
                }
            )
        return rows

    async def handle_message_push(self, message: dict[str, Any]) -> dict[str, Any]:
        device = await self.ensure_device_ready()
        msg_type = message.get("msgType")
        event_type = message.get("eventType")

        if msg_type == "resource_report":
            resources = self._extract_resource_report_items(message)
            filtered_resources = [
                item
                for item in resources
                if item.get("resourceId") and (item.get("subjectId") in {None, device.did})
            ]
            merged_resources = await self.merge_resource_report(
                filtered_resources,
                fetch_full_if_needed=True,
            )
            payload = await self.build_pose_payload_from_resources(merged_resources)
            return {
                "kind": "resource_report",
                "resource_count": len(filtered_resources),
                "payload": payload,
            }

        return {
            "kind": "event",
            "event_type": event_type,
            "message": message,
        }
