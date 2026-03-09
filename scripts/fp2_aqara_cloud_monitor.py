#!/usr/bin/env python3
"""
Poll Aqara Open API for FP2 telemetry and push snapshots into the local backend.

This restores the existing FP2-only UI flow when direct HAP pairing is blocked.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import importlib.util
import json
import logging
import math
from pathlib import Path
import sys
import time
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
AQARA_PROBE_PATH = ROOT_DIR / "scripts" / "aqara_api_probe.py"


def load_probe_module():
    spec = importlib.util.spec_from_file_location("aqara_api_probe", AQARA_PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {AQARA_PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = load_probe_module()


logger = logging.getLogger("fp2_aqara_cloud_monitor")

PRESENCE_RESOURCE_ID = "3.51.85"
LIGHT_RESOURCE_ID = "0.4.85"
RSSI_RESOURCE_ID = "8.0.2026"
ONLINE_RESOURCE_ID = "8.0.2045"
ANGLE_RESOURCE_ID = "8.0.2116"
COORDINATES_RESOURCE_ID = "4.22.700"
REALTIME_POSITION_SWITCH_RESOURCE_ID = "4.22.85"
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


@dataclass
class CloudFP2Device:
    did: str
    name: str
    model: str
    firmware: str
    position_id: str | None
    state: int | None


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


class AqaraCloudClient:
    def __init__(self, settings):
        self.settings = settings
        self.access_token = settings.access_token
        self.refresh_token = settings.refresh_token
        self.resource_info: dict[str, dict[str, Any]] = {}

    @property
    def candidate_dids(self) -> list[str]:
        candidates: list[str] = []
        raw = (self.settings.device_id or "").strip()
        if raw:
            candidates.append(raw)
            lowered = raw.lower()
            if not lowered.startswith("lumi1."):
                candidates.append(f"lumi1.{lowered}")
        return list(dict.fromkeys(candidates))

    def refresh_access_token(self, persist: bool = True) -> str:
        http_status, body = probe.api_call(
            self.settings,
            "config.auth.refreshToken",
            {"refreshToken": self.refresh_token},
        )
        if http_status != 200 or body.get("code") != 0:
            raise RuntimeError(f"refreshToken failed: {body.get('code')} {body.get('message')}")

        result = body.get("result") or {}
        self.access_token = result.get("accessToken", self.access_token)
        self.refresh_token = result.get("refreshToken", self.refresh_token)
        self.settings.access_token = self.access_token
        self.settings.refresh_token = self.refresh_token

        if persist:
            expires_at = datetime.now() + timedelta(seconds=int(result.get("expiresIn", 0) or 0))
            probe.write_env_updates(
                self.settings.env_path,
                {
                    "AQARA_ACCESS_TOKEN": self.access_token,
                    "AQARA_REFRESH_TOKEN": self.refresh_token,
                    "AQARA_OPEN_ID": result.get("openId", self.settings.open_id),
                    "AQARA_ACCESS_TOKEN_EXPIRES": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )

        logger.info("Aqara access token refreshed")
        return self.access_token

    def api_query(self, intent: str, data: dict[str, Any], retry_refresh: bool = True) -> dict[str, Any]:
        http_status, body = probe.api_call(
            self.settings,
            intent,
            data,
            access_token=self.access_token,
        )
        if http_status == 200 and body.get("code") == 0:
            return body

        if retry_refresh and body.get("code") in {108, 401, 403}:
            self.refresh_access_token(persist=True)
            return self.api_query(intent, data, retry_refresh=False)

        raise RuntimeError(f"{intent} failed: {body.get('code')} {body.get('message')}")

    def resolve_device(self) -> CloudFP2Device:
        for did in self.candidate_dids:
            body = self.api_query(
                "query.device.info",
                {"dids": [did], "positionId": "", "pageNum": 1, "pageSize": 50},
            )
            data = ((body.get("result") or {}).get("data") or [])
            if data:
                item = data[0]
                logger.info("Resolved FP2 device via did %s", item.get("did"))
                return CloudFP2Device(
                    did=item.get("did"),
                    name=item.get("deviceName") or self.settings.device_name or "Aqara FP2",
                    model=item.get("model") or self.settings.model,
                    firmware=item.get("firmwareVersion") or "",
                    position_id=item.get("positionId"),
                    state=item.get("state"),
                )

        body = self.api_query(
            "query.device.info",
            {"dids": [], "positionId": "", "pageNum": 1, "pageSize": 200},
        )
        data = ((body.get("result") or {}).get("data") or [])
        needle = (self.settings.device_id or "").lower()
        for item in data:
            did = str(item.get("did", "")).lower()
            if needle and did.endswith(needle):
                logger.info("Resolved FP2 device via full list lookup: %s", item.get("did"))
                return CloudFP2Device(
                    did=item.get("did"),
                    name=item.get("deviceName") or self.settings.device_name or "Aqara FP2",
                    model=item.get("model") or self.settings.model,
                    firmware=item.get("firmwareVersion") or "",
                    position_id=item.get("positionId"),
                    state=item.get("state"),
                )

        raise RuntimeError("Unable to resolve FP2 cloud DID from Aqara API")

    def load_resource_info(self, model: str) -> dict[str, dict[str, Any]]:
        body = self.api_query("query.resource.info", {"model": model})
        mapping: dict[str, dict[str, Any]] = {}
        for item in body.get("result") or []:
            rid = item.get("resourceId")
            if rid:
                mapping[rid] = item
        self.resource_info = mapping
        logger.info("Loaded %d Aqara resource definitions for %s", len(mapping), model)
        return mapping

    def fetch_resource_values(self, did: str) -> list[dict[str, Any]]:
        body = self.api_query("query.resource.value", {"resources": [{"subjectId": did}]})
        result = body.get("result") or []
        if not isinstance(result, list):
            raise RuntimeError("query.resource.value returned unexpected payload")
        return result

    def write_resource(self, did: str, resource_id: str, value: Any) -> None:
        body = self.api_query(
            "write.resource.device",
            [{"subjectId": did, "resources": [{"resourceId": resource_id, "value": str(value)}]}],
        )
        logger.info("Wrote Aqara resource %s=%s via cloud API", resource_id, value)
        return body


class FP2CloudMonitor:
    def __init__(
        self,
        settings,
        backend_url: str,
        interval: float = 2.0,
        *,
        coordinate_keepalive: bool = True,
        coordinate_keepalive_cooldown: float = 15.0,
    ):
        self.settings = settings
        self.backend_url = backend_url.rstrip("/")
        self.interval = interval
        self.coordinate_keepalive = coordinate_keepalive
        self.coordinate_keepalive_cooldown = coordinate_keepalive_cooldown
        self.client = AqaraCloudClient(settings)
        self.device: CloudFP2Device | None = None
        self.last_presence: bool | None = None
        self.last_confirmed_targets: list[dict[str, Any]] = []
        self.last_confirmed_zone: str | None = None
        self.last_confirmed_targets_at: float | None = None
        self.last_coordinate_keepalive_at: float | None = None
        self.base_target_hold_seconds = max(4.0, interval * 4)
        self.active_motion_hold_seconds = max(8.0, interval * 8)

    def _resource_map(self, resources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(item.get("resourceId")): item for item in resources if item.get("resourceId")}

    def _resource_value(self, resource_map: dict[str, dict[str, Any]], resource_id: str) -> Any:
        return (resource_map.get(resource_id) or {}).get("value")

    def _ensure_coordinate_upload_enabled(self, resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.coordinate_keepalive or self.device is None:
            return resources

        resource_map = self._resource_map(resources)
        switch_value = parse_int(self._resource_value(resource_map, REALTIME_POSITION_SWITCH_RESOURCE_ID))
        if switch_value == 1:
            return resources

        now = time.time()
        if (
            self.last_coordinate_keepalive_at is not None
            and (now - self.last_coordinate_keepalive_at) < self.coordinate_keepalive_cooldown
        ):
            return resources

        logger.warning(
            "Realtime coordinate upload switch %s is OFF; enabling it via Aqara Cloud API",
            REALTIME_POSITION_SWITCH_RESOURCE_ID,
        )
        self.client.write_resource(self.device.did, REALTIME_POSITION_SWITCH_RESOURCE_ID, 1)
        self.last_coordinate_keepalive_at = now
        refreshed = self.client.fetch_resource_values(self.device.did)
        refreshed_map = self._resource_map(refreshed)
        refreshed_value = parse_int(self._resource_value(refreshed_map, REALTIME_POSITION_SWITCH_RESOURCE_ID))
        logger.info(
            "Realtime coordinate upload switch %s after write: %s",
            REALTIME_POSITION_SWITCH_RESOURCE_ID,
            refreshed_value if refreshed_value is not None else "unknown",
        )
        return refreshed

    def _max_timestamp(self, resources: list[dict[str, Any]]) -> float:
        timestamps = [parse_int(item.get("timeStamp")) for item in resources]
        valid = [ts for ts in timestamps if ts is not None]
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
            logger.warning("Failed to parse coordinate payload: %s", raw)
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
        # `13.121+` are visitor/statistics channels, not live zone occupancy counts.
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
            rid: item.get("value")
            for rid, item in resource_map.items()
            if item.get("value") not in (None, "")
        }

    def _resource_labels(self, resource_values: dict[str, Any]) -> dict[str, str]:
        labels: dict[str, str] = {}
        for rid in resource_values:
            meta = self.client.resource_info.get(rid) or {}
            label = meta.get("name") or meta.get("description")
            if label:
                labels[rid] = str(label)
        return labels

    def _hold_window_for_event(self, movement_event: int | None) -> float:
        if movement_event in {6, 7, 8, 9, 10}:
            return self.active_motion_hold_seconds
        return self.base_target_hold_seconds

    def _build_held_targets(
        self,
        event_timestamp: float,
        movement_event: int | None,
    ) -> tuple[list[dict[str, Any]], float | None]:
        if not self.last_confirmed_targets or self.last_confirmed_targets_at is None:
            return [], None

        hold_age_sec = max(0.0, event_timestamp - self.last_confirmed_targets_at)
        if hold_age_sec > self._hold_window_for_event(movement_event):
            return [], None

        held_targets: list[dict[str, Any]] = []
        for target in self.last_confirmed_targets:
            held = dict(target)
            held["activity"] = "held"
            held["confidence"] = min(float(target.get("confidence", 0.95) or 0.95), 0.6)
            held["held"] = True
            held["hold_age_sec"] = round(hold_age_sec, 2)
            held_targets.append(held)
        return held_targets, round(hold_age_sec, 2)

    def _build_payload(self, resources: list[dict[str, Any]]) -> dict[str, Any]:
        if self.device is None:
            raise RuntimeError("Cloud device is not initialized")

        resource_map = self._resource_map(resources)
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
            self.last_confirmed_targets = [dict(target) for target in live_targets]
            self.last_confirmed_targets_at = event_timestamp
            self.last_confirmed_zone = current_zone
            targets = live_targets
        elif presence:
            held_targets, hold_age = self._build_held_targets(event_timestamp, movement_event)
            if held_targets:
                targets = held_targets
                coordinates_source = "hold"
                coordinates_hold_age_sec = hold_age
                current_zone = current_zone or self.last_confirmed_zone
            else:
                targets = []
                coordinates_source = "none"
        else:
            targets = []
            coordinates_source = "none"
            self.last_confirmed_targets = []
            self.last_confirmed_targets_at = None
            self.last_confirmed_zone = None
        zones = self._parse_zones(
            resource_map,
            presence=presence,
            active_targets=targets,
            realtime_people_count=advanced_metrics["realtime_people_count"],
        )
        zone_metrics = self._parse_zone_metrics(resource_map)
        resource_values = self._resource_values(resource_map)
        device_timestamp = self._max_timestamp(resources)

        payload = {
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
                "name": self.settings.device_name or self.device.name,
                "model": self.settings.model or self.device.model,
                "device_id": self.settings.device_id or self.device.did,
                "cloud_did": self.device.did,
                "firmware": self.device.firmware or self.settings.fp2_firmware,
                "transport": "Aqara Cloud",
            },
            "connection": {
                "transport": "aqara_cloud",
                "state": "live",
                "api_domain": self.settings.api_domain,
                "position_id": self.device.position_id,
                "online": online,
                "rssi": rssi,
                "targets": len(targets),
                "coordinates_source": coordinates_source,
                "realtime_people_count": advanced_metrics["realtime_people_count"],
                "people_count_1m": advanced_metrics["people_count_1m"],
                "walking_distance_m": advanced_metrics["walking_distance_m"],
            },
        }
        return payload

    def push_snapshot(self, payload: dict[str, Any]) -> None:
        response = requests.post(
            f"{self.backend_url}/api/v1/fp2/push",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()

    def initialize(self) -> None:
        try:
            self.device = self.client.resolve_device()
            self.client.load_resource_info(self.device.model)
            logger.info("Aqara cloud monitor initialized using current access token")
        except Exception as exc:
            logger.warning("Current Aqara access token bootstrap failed: %s; trying refresh", exc)
            self.client.refresh_access_token(persist=True)
            self.device = self.client.resolve_device()
            self.client.load_resource_info(self.device.model)
        logger.info(
            "Aqara cloud FP2 monitor bound to did=%s model=%s firmware=%s",
            self.device.did,
            self.device.model,
            self.device.firmware or "-",
        )

    def run(self) -> int:
        init_backoff = max(self.interval, 2.0)
        logger.info("Pushing FP2 cloud snapshots to %s/api/v1/fp2/push every %.1fs", self.backend_url, self.interval)
        while True:
            try:
                if self.device is None:
                    self.initialize()
                    logger.info("Aqara cloud monitor initialized")
                    init_backoff = max(self.interval, 2.0)
                resources = self.client.fetch_resource_values(self.device.did)
                resources = self._ensure_coordinate_upload_enabled(resources)
                payload = self._build_payload(resources)
                self.push_snapshot(payload)
                presence = payload["presence"]
                zone_count = len(payload["zones"])
                target_count = len(payload["targets"])
                light = payload.get("light_level")
                changed = self.last_presence is None or self.last_presence != presence
                if changed:
                    logger.info(
                        "FP2 cloud snapshot: presence=%s targets=%d zones=%d light=%s",
                        "YES" if presence else "no",
                        target_count,
                        zone_count,
                        f"{light:.0f} lux" if isinstance(light, float) else "-",
                    )
                else:
                    logger.debug(
                        "FP2 cloud snapshot: presence=%s targets=%d zones=%d",
                        presence,
                        target_count,
                        zone_count,
                    )
                self.last_presence = presence
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                logger.error("Cloud monitor cycle failed: %s", exc)
                if self.device is None:
                    logger.info("Retrying Aqara cloud initialization in %.1fs", init_backoff)
                    time.sleep(init_backoff)
                    init_backoff = min(init_backoff * 2, 30.0)
                    continue
            time.sleep(self.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aqara Cloud FP2 monitor")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT_DIR / ".env",
        help="Path to project .env",
    )
    parser.add_argument(
        "--backend",
        default="http://127.0.0.1:8000",
        help="Backend base URL",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--no-coordinate-keepalive",
        action="store_true",
        help="Do not auto-enable the realtime coordinate upload switch (4.22.85)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    settings = probe.load_settings(args.env_file)
    monitor = FP2CloudMonitor(
        settings,
        backend_url=args.backend,
        interval=args.interval,
        coordinate_keepalive=not args.no_coordinate_keepalive,
    )
    try:
        return monitor.run()
    except KeyboardInterrupt:
        logger.info("Cloud monitor stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
