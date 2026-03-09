"""
FP2 (Aqara mmWave) integration endpoints.

Supports two data sources:
  1. Home Assistant REST API polling (original)
  2. Direct HAP push from fp2_hap_client.py (new)
"""

import asyncio
from collections import deque
import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field

from src.api.dependencies import (
    get_aqara_cloud_service,
    get_fp2_layout_store_service,
    get_fp2_service,
)
from src.services.aqara_cloud_service import (
    AqaraCloudAPIError,
    AqaraCloudConfigurationError,
    AqaraCloudService,
)
from src.services.fp2_layout_store import FP2LayoutStoreService
from src.services.fp2_service import FP2Service, FP2Snapshot, FP2Zone, FP2Target

logger = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory store for HAP push data ────────────────────────
_hap_latest: Dict[str, Any] = {}
_hap_listeners: list = []
_raw_capture_history = deque(maxlen=400)
_raw_capture_sequence = 0
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_PAIRING_DATA_PATH = _PROJECT_ROOT / ".fp2_pairing.json"
_MAC_RE = re.compile(r"([0-9a-f]{1,2}[:-]){5}[0-9a-f]{1,2}", re.IGNORECASE)
_PRESENCE_MOVEMENT_EVENTS = {1, 2, 3, 4, 8, 9}


def _get_latest_hap_snapshot() -> Optional[FP2Snapshot]:
    """Return the latest direct HAP snapshot even if it is stale."""
    snapshot = _hap_latest.get("snapshot")
    if snapshot is None:
        return None
    return snapshot


def _get_recent_hap_snapshot(max_age_sec: float = 15.0) -> Optional[FP2Snapshot]:
    """Return the latest direct HAP snapshot if it is still fresh."""
    snapshot = _get_latest_hap_snapshot()
    updated = _hap_latest.get("updated_at")
    if snapshot is None or updated is None:
        return None

    if time.time() - updated > max_age_sec:
        return None

    return snapshot


def _snapshot_source(snapshot: Optional[FP2Snapshot]) -> str:
    if snapshot is None:
        return ""
    return str(snapshot.raw_attributes.get("source") or "hap_direct")


def _should_refresh_from_cloud(
    snapshot: Optional[FP2Snapshot],
    aqara_cloud_service: AqaraCloudService,
) -> bool:
    if not aqara_cloud_service.is_configured:
        return False
    if snapshot is None:
        return not _has_direct_hap_pairing()
    source = _snapshot_source(snapshot)
    if source == "aqara_cloud":
        return False
    return not _has_direct_hap_pairing()


async def _fetch_and_ingest_cloud_payload(aqara_cloud_service: AqaraCloudService) -> dict[str, Any]:
    payload = await aqara_cloud_service.fetch_current_pose_payload()
    payload.setdefault("metadata", {})
    payload["metadata"]["source"] = "aqara_cloud"
    payload["metadata"]["cloud_refresh"] = True
    await _ingest_fp2_payload(HAPPushPayload.model_validate(payload))
    return payload


def _load_pairing_metadata() -> Dict[str, Any]:
    """Read saved HAP pairing metadata if present."""
    if not _PAIRING_DATA_PATH.exists():
        return {}

    try:
        payload = json.loads(_PAIRING_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read FP2 pairing metadata from %s", _PAIRING_DATA_PATH)
        return {}

    if isinstance(payload, dict):
        return payload
    return {}


def _normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    match = _MAC_RE.search(value)
    if not match:
        return None
    return match.group(0).lower().replace("-", ":")


def _lookup_local_ip_by_mac(mac_address: str | None) -> str | None:
    """Best-effort local ARP lookup for the current device IP."""
    normalized = _normalize_mac(mac_address)
    if not normalized:
        return None

    try:
        output = subprocess.check_output(["arp", "-a"], text=True, timeout=3)
    except Exception:
        return None

    for line in output.splitlines():
        if normalized not in line.lower():
            continue
        match = re.search(r"\(([^)]+)\)", line)
        if match:
            return match.group(1)
    return None


def _has_direct_hap_pairing() -> bool:
    """Check whether the workspace is configured for direct HAP mode."""
    return _PAIRING_DATA_PATH.exists()


def _copy_resource_values(raw_attributes: Dict[str, Any]) -> Dict[str, Any]:
    values = raw_attributes.get("resource_values") or {}
    if not isinstance(values, dict):
        return {}
    return {str(key): value for key, value in values.items()}


def _build_changed_resources(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    changed: Dict[str, Dict[str, Any]] = {}
    for rid in sorted(set(previous.keys()) | set(current.keys())):
        previous_value = previous.get(rid)
        current_value = current.get(rid)
        if previous_value == current_value:
            continue
        changed[rid] = {
            "previous": previous_value,
            "current": current_value,
        }
    return changed


def _record_raw_capture(snapshot: FP2Snapshot) -> None:
    """Store a compact raw capture entry for later FP2 debugging."""
    global _raw_capture_sequence

    raw = snapshot.raw_attributes or {}
    resource_values = _copy_resource_values(raw)
    previous_entry = _raw_capture_history[-1] if _raw_capture_history else None
    previous_values = previous_entry.get("resource_values", {}) if previous_entry else {}
    active_targets = [
        {
            "target_id": target.target_id,
            "zone_id": target.zone_id,
            "x": target.x,
            "y": target.y,
            "distance": target.distance,
            "angle": target.angle,
            "activity": target.activity,
            "confidence": target.confidence,
        }
        for target in snapshot.targets
    ]

    _raw_capture_sequence += 1
    _raw_capture_history.append(
        {
            "sequence": _raw_capture_sequence,
            "captured_at": time.time(),
            "snapshot_timestamp": snapshot.timestamp.isoformat(),
            "source": raw.get("source") or "unknown",
            "presence": snapshot.presence,
            "movement_event": raw.get("movement_event"),
            "fall_state": raw.get("fall_state"),
            "current_zone": raw.get("current_zone"),
            "online": raw.get("online"),
            "rssi": raw.get("rssi"),
            "light_level": raw.get("light_level"),
            "sensor_angle": raw.get("sensor_angle"),
            "active_target_count": len(snapshot.targets),
            "active_targets": active_targets,
            "zones": raw.get("zones") or [],
            "advanced_metrics": raw.get("advanced_metrics") or {},
            "zone_metrics": raw.get("zone_metrics") or {},
            "resource_ids": sorted(resource_values.keys()),
            "resource_values": resource_values,
            "changed_resources": _build_changed_resources(previous_values, resource_values),
        }
    )


def _build_stale_hap_payload(snapshot: Optional[FP2Snapshot], *, reason: str) -> Dict[str, Any]:
    """Convert the last known pushed FP2 snapshot into an explicit offline payload."""
    fp2_service = get_fp2_service()
    payload = fp2_service.snapshot_to_pose_data(snapshot)
    payload.setdefault("metadata", {})
    source = "hap_direct"
    if snapshot is not None:
        source = str(snapshot.raw_attributes.get("source") or "hap_direct")
    payload["metadata"]["source"] = source
    payload["metadata"]["entity_id"] = source
    payload["metadata"]["available"] = snapshot is not None
    payload["metadata"]["presence"] = bool(snapshot.presence) if snapshot is not None else False
    payload["metadata"]["stale"] = True
    payload["metadata"]["error"] = reason
    if snapshot is None:
        payload["persons"] = []
        payload["zone_summary"] = {}
    return payload


def _evaluate_presence_signals(snapshot: Optional[FP2Snapshot]) -> Dict[str, Any]:
    """Build a best-effort presence view without overwriting the raw sensor flag."""
    if snapshot is None:
        return {
            "raw_presence": False,
            "effective_presence": False,
            "derived_presence": False,
            "presence_mode": "none",
            "presence_reason": None,
            "presence_signals": {},
        }

    raw_presence = bool(snapshot.presence)
    raw = snapshot.raw_attributes or {}
    advanced_metrics = raw.get("advanced_metrics") or {}
    movement_event = raw.get("movement_event")
    target_count = len(snapshot.targets)
    occupied_zones = sum(1 for zone in snapshot.zones if zone.occupied)
    realtime_people_count = advanced_metrics.get("realtime_people_count")
    has_current_zone = bool(raw.get("current_zone"))
    has_coordinates = bool(raw.get("coordinates") or raw.get("live_coordinates"))
    movement_presence = movement_event in _PRESENCE_MOVEMENT_EVENTS

    signals = {
        "targets": target_count > 0,
        "zones": occupied_zones > 0,
        "realtime_people": isinstance(realtime_people_count, (int, float)) and realtime_people_count > 0,
        "movement": movement_presence,
        "current_zone": has_current_zone,
        "coordinates": has_coordinates,
    }

    derived_presence = False
    reason = None
    if not raw_presence:
        for signal_name in ("targets", "zones", "realtime_people", "coordinates", "current_zone", "movement"):
            if signals[signal_name]:
                derived_presence = True
                reason = signal_name
                break

    effective_presence = raw_presence or derived_presence
    if raw_presence:
        mode = "raw"
    elif derived_presence:
        mode = "derived"
    else:
        mode = "none"

    return {
        "raw_presence": raw_presence,
        "effective_presence": effective_presence,
        "derived_presence": derived_presence,
        "presence_mode": mode,
        "presence_reason": reason,
        "presence_signals": signals,
    }


def _build_device_metadata(fp2_service: FP2Service) -> Dict[str, Any]:
    """Build a stable description of the bound FP2 device."""
    settings = fp2_service.settings
    pairing = _load_pairing_metadata()
    latest_snapshot = _get_latest_hap_snapshot()
    pushed_device = dict(_hap_latest.get("device") or {})
    snapshot_device = {}
    if latest_snapshot is not None:
        snapshot_device = dict(latest_snapshot.raw_attributes.get("device") or {})

    device_label = settings.fp2_name or "Aqara FP2"
    room_label = settings.fp2_room or "-"
    connection = _hap_latest.get("connection") or {}
    transport = (
        connection.get("transport")
        or pushed_device.get("transport")
        or snapshot_device.get("transport")
        or "hap_direct"
    )
    transport_key = str(transport).lower()
    is_cloud = transport_key == "aqara_cloud"

    if is_cloud:
        base = {
            "name": device_label,
            "room": room_label,
            "model": settings.fp2_model or "Aqara FP2",
            "sku": settings.fp2_sku or None,
            "device_id": settings.fp2_device_id or None,
            "mac_address": settings.fp2_mac_address or None,
            "firmware": settings.fp2_firmware or None,
            "ip_address": None,
            "hap_port": None,
            "pairing_id": None,
            "transport": "Aqara Cloud",
            "wifi": {},
        }
    else:
        device_ip = pairing.get("AccessoryIP") or settings.fp2_ip_address
        device_port = pairing.get("AccessoryPort")
        wifi_channel = settings.fp2_wifi_channel or "-"
        signal_strength = settings.fp2_signal_strength or "-"
        base = {
            "name": device_label,
            "room": room_label,
            "model": settings.fp2_model or "Aqara FP2",
            "sku": settings.fp2_sku or None,
            "device_id": settings.fp2_device_id or None,
            "mac_address": settings.fp2_mac_address or None,
            "firmware": settings.fp2_firmware or None,
            "ip_address": device_ip or None,
            "hap_port": device_port,
            "pairing_id": pairing.get("AccessoryPairingID"),
            "transport": "HomeKit / HAP",
            "wifi": {
                "ssid": settings.router_ssid or None,
                "router_ip": settings.router_ip or None,
                "channel": wifi_channel,
                "signal_strength": signal_strength,
                "bssid": settings.fp2_bssid or None,
            },
        }

    merged = {**base, **snapshot_device, **pushed_device}
    merged_wifi = {
        **(base.get("wifi") or {}),
        **(snapshot_device.get("wifi") or {}),
        **(pushed_device.get("wifi") or {}),
    }
    merged["wifi"] = merged_wifi

    if connection.get("transport"):
        merged["transport"] = connection.get("transport")
    if connection.get("position_id"):
        merged["position_id"] = connection.get("position_id")
    if connection.get("api_domain"):
        merged["api_domain"] = connection.get("api_domain")

    local_ip = _lookup_local_ip_by_mac(merged.get("mac_address"))
    if local_ip:
        merged["ip_address"] = local_ip

    return merged


def _parse_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _parse_csv_int_list(raw: str | None) -> list[int]:
    values: list[int] = []
    for item in _parse_csv_list(raw):
        try:
            values.append(int(item))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid integer value '{item}'") from exc
    return values


def _raise_cloud_http_error(exc: Exception) -> None:
    if isinstance(exc, AqaraCloudConfigurationError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, AqaraCloudAPIError):
        raise HTTPException(
            status_code=502,
            detail={
                "message": str(exc),
                "intent": exc.intent,
                "code": exc.code,
                "http_status": exc.http_status,
            },
        ) from exc
    raise exc


def _update_cloud_event_state(message: Dict[str, Any]) -> None:
    event_type = str(message.get("eventType") or "").strip()
    if not event_type:
        return

    connection = dict(_hap_latest.get("connection") or {})
    connection["transport"] = "aqara_cloud"
    connection["last_event_type"] = event_type
    connection["last_event_at"] = datetime.utcnow().isoformat()
    if event_type.endswith("_online"):
        connection["state"] = "live"
        connection["online"] = True
    elif event_type.endswith("_offline"):
        connection["state"] = "offline"
        connection["online"] = False
    _hap_latest["connection"] = connection
    _hap_latest.setdefault("device", {})
    _hap_latest["updated_at"] = _hap_latest.get("updated_at") or time.time()


@router.get("/status")
async def get_fp2_status(
    fp2_service: FP2Service = Depends(get_fp2_service),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Get FP2 integration status."""
    status = await fp2_service.get_status()
    latest_hap_snapshot = _get_latest_hap_snapshot()
    hap_snapshot = _get_recent_hap_snapshot()
    if hap_snapshot is None and _should_refresh_from_cloud(latest_hap_snapshot, aqara_cloud_service):
        try:
            await _fetch_and_ingest_cloud_payload(aqara_cloud_service)
            latest_hap_snapshot = _get_latest_hap_snapshot()
            hap_snapshot = _get_recent_hap_snapshot()
        except Exception as exc:
            logger.warning("Failed to refresh Aqara Cloud status snapshot: %s", exc)
    status["device"] = _build_device_metadata(fp2_service)
    if hap_snapshot is not None:
        source = str(hap_snapshot.raw_attributes.get("source") or "hap_direct")
        connection = dict(_hap_latest.get("connection") or {})
        transport = connection.get("transport") or str(hap_snapshot.raw_attributes.get("transport") or source)
        presence_eval = _evaluate_presence_signals(hap_snapshot)
        status["status"] = "healthy"
        status["running"] = True
        status["entity_id"] = source
        status["last_snapshot"] = hap_snapshot.timestamp.isoformat()
        status["presence"] = presence_eval["effective_presence"]
        status["presence_raw"] = presence_eval["raw_presence"]
        status["presence_mode"] = presence_eval["presence_mode"]
        status["presence_reason"] = presence_eval["presence_reason"]
        status["source"] = source
        status["hap_connected"] = source == "hap_direct"
        status["stream_connected"] = True
        status.setdefault("stats", {})
        status["stats"]["mode"] = source
        status["stats"]["last_error"] = None
        status["stats"]["last_entity_state"] = source
        status["connection"] = {
            "transport": transport,
            "state": connection.get("state") or "live",
            "last_update_age_sec": round(time.time() - _hap_latest.get("updated_at", time.time()), 1),
            "light_level": hap_snapshot.raw_attributes.get("light_level"),
            "targets": len(hap_snapshot.targets),
            "zones": [
                {
                    "zone_id": zone.zone_id,
                    "name": zone.name,
                    "occupied": zone.occupied,
                    "target_count": zone.target_count,
                }
                for zone in hap_snapshot.zones
            ],
            "rssi": connection.get("rssi") or hap_snapshot.raw_attributes.get("rssi"),
            "online": connection.get("online"),
            "position_id": connection.get("position_id"),
            "api_domain": connection.get("api_domain"),
        }
    elif latest_hap_snapshot is not None or _has_direct_hap_pairing():
        source = "hap_direct"
        connection = dict(_hap_latest.get("connection") or {})
        presence_eval = _evaluate_presence_signals(latest_hap_snapshot)
        if latest_hap_snapshot is not None:
            source = str(latest_hap_snapshot.raw_attributes.get("source") or "hap_direct")
        transport = connection.get("transport") or (
            latest_hap_snapshot.raw_attributes.get("transport") if latest_hap_snapshot is not None else "hap_direct"
        ) or source
        updated_at = _hap_latest.get("updated_at")
        last_age = round(time.time() - updated_at, 1) if updated_at else None
        status["status"] = "degraded"
        status["running"] = True
        status["entity_id"] = source
        status["last_snapshot"] = latest_hap_snapshot.timestamp.isoformat() if latest_hap_snapshot else None
        status["presence"] = False
        status["presence_raw"] = presence_eval["raw_presence"]
        status["presence_mode"] = "stale"
        status["presence_reason"] = presence_eval["presence_reason"]
        status["source"] = source
        status["hap_connected"] = False
        status["stream_connected"] = False
        status.setdefault("stats", {})
        status["stats"]["mode"] = source
        status["stats"]["last_error"] = (
            "FP2 cloud stream is stale or offline"
            if source == "aqara_cloud"
            else "Direct HAP stream is stale or offline"
        )
        status["stats"]["last_entity_state"] = f"{source}_offline"
        status["connection"] = {
            "transport": transport,
            "state": "stale",
            "last_update_age_sec": last_age,
            "light_level": latest_hap_snapshot.raw_attributes.get("light_level") if latest_hap_snapshot else None,
            "targets": 0,
            "zones": [],
            "rssi": connection.get("rssi") or (latest_hap_snapshot.raw_attributes.get("rssi") if latest_hap_snapshot else None),
            "online": connection.get("online"),
            "position_id": connection.get("position_id"),
            "api_domain": connection.get("api_domain"),
        }
    else:
        status["source"] = "home_assistant"
        status["hap_connected"] = False
        status["stream_connected"] = False
        status.setdefault("stats", {})
        status["stats"]["mode"] = "home_assistant"
        status["connection"] = {
            "transport": "home_assistant",
            "state": "waiting_for_hap_push",
            "last_update_age_sec": None,
            "light_level": None,
            "targets": 0,
            "zones": [],
        }
    status["enabled"] = fp2_service.settings.fp2_enabled
    return status


@router.get("/current")
async def get_fp2_current_pose_like_data(
    entity_id: str | None = Query(default=None, description="Optional HA entity_id override"),
    fp2_service: FP2Service = Depends(get_fp2_service),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Get latest FP2 snapshot converted to pose-like output."""
    if not fp2_service.settings.fp2_enabled:
        data = fp2_service.snapshot_to_pose_data()
        data["metadata"]["enabled"] = False
        return data

    hap_snapshot = _get_recent_hap_snapshot()
    latest_hap_snapshot = _get_latest_hap_snapshot()
    if hap_snapshot is not None:
        snapshot = hap_snapshot
        source = str(snapshot.raw_attributes.get("source") or "hap_direct")
        resolved_entity_id = source
    elif _should_refresh_from_cloud(latest_hap_snapshot, aqara_cloud_service):
        try:
            return await _fetch_and_ingest_cloud_payload(aqara_cloud_service)
        except Exception as exc:
            if latest_hap_snapshot is not None and _snapshot_source(latest_hap_snapshot) == "aqara_cloud":
                return _build_stale_hap_payload(
                    latest_hap_snapshot,
                    reason=f"Cloud refresh failed; serving cached Aqara snapshot: {exc}",
                )
            _raise_cloud_http_error(exc)
    elif latest_hap_snapshot is not None:
        return _build_stale_hap_payload(
            latest_hap_snapshot,
            reason="FP2 direct stream is stale or the device is offline",
        )
    elif _has_direct_hap_pairing():
        return _build_stale_hap_payload(
            None,
            reason="Direct HAP stream is stale or the FP2 device is offline",
        )
    else:
        resolved_entity_id = await fp2_service.resolve_entity_id(entity_id)
        snapshot = await fp2_service.fetch_snapshot(entity_id=resolved_entity_id)
        source = "home_assistant"

    payload = fp2_service.snapshot_to_pose_data(snapshot)
    payload.setdefault("metadata", {})
    payload["metadata"]["available"] = snapshot is not None
    if snapshot is None and fp2_service._stats.get("last_error"):
        payload["metadata"]["error"] = fp2_service._stats["last_error"]
    presence_eval = _evaluate_presence_signals(snapshot)
    payload["metadata"]["presence_raw"] = presence_eval["raw_presence"]
    payload["metadata"]["effective_presence"] = presence_eval["effective_presence"]
    payload["metadata"]["derived_presence"] = presence_eval["derived_presence"]
    payload["metadata"]["presence_mode"] = presence_eval["presence_mode"]
    payload["metadata"]["presence_reason"] = presence_eval["presence_reason"]
    payload["metadata"]["presence_signals"] = presence_eval["presence_signals"]
    payload["metadata"]["entity_id"] = resolved_entity_id
    payload["metadata"]["source"] = source
    return payload


@router.get("/entities")
async def list_fp2_entities(
    fp2_service: FP2Service = Depends(get_fp2_service),
):
    """Discover FP2-related entities in Home Assistant."""
    if not fp2_service.settings.fp2_enabled:
        return {"count": 0, "entities": [], "enabled": False}

    entities = await fp2_service.fetch_all_fp2_entities()
    return {"count": len(entities), "entities": entities, "enabled": True}


@router.get("/recommended-entity")
async def get_recommended_fp2_entity(
    fp2_service: FP2Service = Depends(get_fp2_service),
):
    """Get best-effort recommended FP2 entity_id from HA states."""
    if not fp2_service.settings.fp2_enabled:
        return {"recommended_entity_id": None, "enabled": False}

    entity_id = await fp2_service.recommend_entity_id()
    return {"recommended_entity_id": entity_id, "enabled": True}


class AqaraResourceWriteRequest(BaseModel):
    resource_id: str
    value: Any
    subject_id: str | None = None
    refresh_state: bool = True


class AqaraResourceSubscriptionRequest(BaseModel):
    resource_ids: list[str]
    subject_id: str | None = None
    attach: str | None = None


class FP2LayoutStateWriteRequest(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict)
    scope: str | None = None


class FP2LayoutStateResponse(BaseModel):
    found: bool
    scope: str
    payload: Dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    storage_backend: str | None = None


@router.get("/cloud/config")
async def get_fp2_cloud_config(
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Return Aqara cloud backend configuration status."""
    return aqara_cloud_service.get_configuration_status()


@router.get("/cloud/resources")
async def get_fp2_cloud_resources(
    resource_ids: str | None = Query(default=None, description="Comma-separated resource IDs"),
    include_values: bool = Query(default=False, description="Fetch current resource values from Aqara"),
    writable_only: bool = Query(default=False, description="Only return writable resources"),
    reportable_only: bool = Query(default=False, description="Only return reportable resources"),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """List FP2 Aqara resources, access flags, and optional live values."""
    try:
        return await aqara_cloud_service.get_resource_catalog(
            include_values=include_values,
            resource_ids=_parse_csv_list(resource_ids) or None,
            writable_only=writable_only,
            reportable_only=reportable_only,
        )
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.get("/cloud/current")
async def get_fp2_cloud_current(
    ingest: bool = Query(default=True, description="Push the fresh Aqara snapshot into backend state"),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Fetch a live FP2 snapshot directly from Aqara cloud."""
    try:
        payload = await aqara_cloud_service.fetch_current_pose_payload()
        payload.setdefault("metadata", {})
        payload["metadata"]["source"] = "aqara_cloud"
        payload["metadata"]["cloud_refresh"] = True
        if ingest:
            ingest_result = await _ingest_fp2_payload(HAPPushPayload.model_validate(payload))
            payload["metadata"]["ingested"] = True
            payload["metadata"]["ingest_summary"] = ingest_result
        else:
            payload["metadata"]["ingested"] = False
        return payload
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.post("/cloud/resources/write")
async def write_fp2_cloud_resource(
    request: AqaraResourceWriteRequest,
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Write a configurable FP2 Aqara resource and optionally refresh state."""
    try:
        write_result = await aqara_cloud_service.write_resource(
            resource_id=request.resource_id,
            value=request.value,
            subject_id=request.subject_id,
        )
        response: Dict[str, Any] = {"write": write_result}
        if request.refresh_state:
            payload = await aqara_cloud_service.fetch_current_pose_payload()
            ingest_result = await _ingest_fp2_payload(HAPPushPayload.model_validate(payload))
            response["current"] = payload
            response["ingest_summary"] = ingest_result
        return response
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.get("/layout-state", response_model=FP2LayoutStateResponse)
async def get_fp2_layout_state(
    scope: str | None = Query(default=None, description="Optional override for layout storage scope"),
    layout_store: FP2LayoutStoreService = Depends(get_fp2_layout_store_service),
):
    """Return persisted FP2 room/template/layout state."""
    state = await layout_store.get_state(scope=scope)
    resolved_scope = scope or layout_store.default_scope()
    if state is None:
        return FP2LayoutStateResponse(found=False, scope=resolved_scope)
    return FP2LayoutStateResponse(found=True, **state)


@router.put("/layout-state", response_model=FP2LayoutStateResponse)
async def put_fp2_layout_state(
    request: FP2LayoutStateWriteRequest,
    layout_store: FP2LayoutStoreService = Depends(get_fp2_layout_store_service),
):
    """Persist FP2 room/template/layout state."""
    payload = request.payload if isinstance(request.payload, dict) else {}
    state = await layout_store.save_state(payload=payload, scope=request.scope)
    return FP2LayoutStateResponse(found=True, **state)


@router.get("/cloud/history")
async def get_fp2_cloud_history(
    resource_ids: str = Query(..., description="Comma-separated resource IDs"),
    start_time: int = Query(..., description="Unix timestamp in milliseconds"),
    end_time: int | None = Query(default=None, description="Unix timestamp in milliseconds"),
    size: int = Query(default=100, ge=1, le=500),
    scan_id: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Fetch FP2 resource history from Aqara cloud."""
    ids = _parse_csv_list(resource_ids)
    if not ids:
        raise HTTPException(status_code=400, detail="resource_ids is required")
    try:
        return await aqara_cloud_service.fetch_resource_history(
            resource_ids=ids,
            start_time=start_time,
            end_time=end_time,
            size=size,
            scan_id=scan_id,
            subject_id=subject_id,
        )
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.get("/cloud/statistics")
async def get_fp2_cloud_statistics(
    resource_ids: str = Query(..., description="Comma-separated resource IDs"),
    start_time: int = Query(..., description="Unix timestamp in milliseconds"),
    dimension: str = Query(..., description="Aqara statistics dimension, e.g. 1h or 1d"),
    aggr_types: str = Query(..., description="Comma-separated Aqara aggregation types"),
    end_time: int | None = Query(default=None, description="Unix timestamp in milliseconds"),
    size: int = Query(default=100, ge=1, le=500),
    scan_id: str | None = Query(default=None),
    subject_id: str | None = Query(default=None),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Fetch FP2 resource statistics from Aqara cloud."""
    ids = _parse_csv_list(resource_ids)
    if not ids:
        raise HTTPException(status_code=400, detail="resource_ids is required")
    try:
        return await aqara_cloud_service.fetch_resource_statistics(
            resource_ids=ids,
            start_time=start_time,
            end_time=end_time,
            dimension=dimension,
            aggr_types=_parse_csv_int_list(aggr_types),
            size=size,
            scan_id=scan_id,
            subject_id=subject_id,
        )
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.post("/cloud/subscribe")
async def subscribe_fp2_cloud_resources(
    request: AqaraResourceSubscriptionRequest,
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Subscribe the current app credentials to FP2 resource reports."""
    if not request.resource_ids:
        raise HTTPException(status_code=400, detail="resource_ids is required")
    try:
        return await aqara_cloud_service.subscribe_resources(
            resource_ids=request.resource_ids,
            attach=request.attach,
            subject_id=request.subject_id,
        )
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.post("/cloud/unsubscribe")
async def unsubscribe_fp2_cloud_resources(
    request: AqaraResourceSubscriptionRequest,
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Remove FP2 resource subscriptions for the current app credentials."""
    if not request.resource_ids:
        raise HTTPException(status_code=400, detail="resource_ids is required")
    try:
        return await aqara_cloud_service.unsubscribe_resources(
            resource_ids=request.resource_ids,
            subject_id=request.subject_id,
        )
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.get("/cloud/push-errors")
async def get_fp2_cloud_push_errors(
    msg_type: str | None = Query(default=None, description="resource_report or control_fail"),
    start_time: int | None = Query(default=None, description="Unix timestamp in milliseconds"),
    end_time: int | None = Query(default=None, description="Unix timestamp in milliseconds"),
    size: int = Query(default=50, ge=1, le=200),
    scan_id: str | None = Query(default=None),
    open_id: str | None = Query(default=None),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Inspect Aqara push delivery failures for the current app/openId."""
    try:
        return await aqara_cloud_service.get_push_errors(
            open_id=open_id,
            msg_type=msg_type,
            start_time=start_time,
            end_time=end_time,
            size=size,
            scan_id=scan_id,
        )
    except Exception as exc:
        _raise_cloud_http_error(exc)


@router.post("/cloud/push")
async def receive_fp2_cloud_push(
    message: Dict[str, Any] = Body(...),
    aqara_cloud_service: AqaraCloudService = Depends(get_aqara_cloud_service),
):
    """Receive Aqara Message Push payloads and update backend FP2 state."""
    try:
        result = await aqara_cloud_service.handle_message_push(message)
    except Exception as exc:
        _raise_cloud_http_error(exc)

    if result.get("kind") == "resource_report":
        ingest_result = await _ingest_fp2_payload(HAPPushPayload.model_validate(result["payload"]))
        return {
            "status": "ok",
            "kind": "resource_report",
            "resource_count": result.get("resource_count", 0),
            "ingest_summary": ingest_result,
        }

    _update_cloud_event_state(message)
    return {
        "status": "accepted",
        "kind": result.get("kind"),
        "event_type": result.get("event_type"),
    }


@router.get("/raw-history")
async def get_fp2_raw_history(
    limit: int = Query(default=60, ge=1, le=400, description="Number of most recent raw captures to return"),
    changed_only: bool = Query(default=False, description="Return only captures with changed resource values"),
):
    """Return recent raw FP2 captures for debugging Aqara Cloud payloads."""
    entries = list(_raw_capture_history)
    if changed_only:
        entries = [entry for entry in entries if entry.get("changed_resources")]
    return {
        "count": min(limit, len(entries)),
        "total": len(entries),
        "latest_sequence": _raw_capture_sequence,
        "captures": entries[-limit:],
    }


@router.websocket("/ws")
async def websocket_fp2_stream(
    websocket: WebSocket,
    entity_id: str | None = Query(default=None),
):
    """WebSocket stream for real-time FP2 snapshots."""
    await websocket.accept()
    fp2_service = get_fp2_service()
    if not fp2_service.settings.fp2_enabled:
        await websocket.send_json({
            "type": "error",
            "message": "FP2 integration is disabled. Set FP2_ENABLED=true.",
        })
        await websocket.close(code=1008)
        return

    try:
        # If explicit entity is requested, run dedicated polling loop for this client.
        if entity_id:
            while True:
                hap_snapshot = _get_recent_hap_snapshot()
                if hap_snapshot is not None:
                    snapshot = hap_snapshot
                    resolved_entity_id = "hap_direct"
                    source = "hap_direct"
                else:
                    resolved_entity_id = await fp2_service.resolve_entity_id(entity_id)
                    snapshot = await fp2_service.fetch_snapshot(entity_id=resolved_entity_id)
                    source = "home_assistant"
                payload = fp2_service.snapshot_to_pose_data(snapshot)
                payload.setdefault("metadata", {})
                payload["metadata"]["available"] = snapshot is not None
                if snapshot is None and fp2_service._stats.get("last_error"):
                    payload["metadata"]["error"] = fp2_service._stats["last_error"]
                payload["metadata"]["entity_id"] = resolved_entity_id
                payload["metadata"]["source"] = source
                await websocket.send_json(payload)
                await asyncio.sleep(fp2_service.settings.fp2_poll_interval)
        else:
            queue = fp2_service.subscribe()
            try:
                await websocket.send_json(fp2_service.snapshot_to_pose_data())
                while True:
                    snapshot = await queue.get()
                    await websocket.send_json(fp2_service.snapshot_to_pose_data(snapshot))
            finally:
                fp2_service.unsubscribe(queue)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("FP2 websocket error: %s", exc)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        pass


# ── Direct HAP push endpoint ─────────────────────────────────

class HAPPushPayload(BaseModel):
    timestamp: float
    presence: bool
    zones: list[Dict[str, Any]] = Field(default_factory=list)
    targets: list[Dict[str, Any]] = Field(default_factory=list)
    light_level: Optional[float] = None
    source: str = "hap_direct"
    raw_attributes: Dict[str, Any] = Field(default_factory=dict)
    device: Dict[str, Any] = Field(default_factory=dict)
    connection: Dict[str, Any] = Field(default_factory=dict)


async def _ingest_fp2_payload(payload: HAPPushPayload) -> Dict[str, Any]:
    """Store normalized FP2 payload from HAP or Aqara Cloud into shared backend state."""
    global _hap_latest

    normalized_targets = []
    targets = []
    target_counts_by_zone: Dict[str, int] = {}

    for target in payload.targets:
        zone_id = target.get("zone_id", "detection_area")
        normalized_target = {
            **target,
            "zone_id": zone_id,
        }
        normalized_targets.append(normalized_target)
        target_counts_by_zone[zone_id] = target_counts_by_zone.get(zone_id, 0) + 1
        targets.append(FP2Target(
            target_id=str(target.get("target_id") or target.get("id") or f"person_{len(targets)}"),
            zone_id=zone_id,
            x=float(target.get("x", 0.0) or 0.0),
            y=float(target.get("y", 0.0) or 0.0),
            distance=float(target.get("distance", 0.0) or 0.0),
            angle=float(target.get("angle", 0.0) or 0.0),
            activity=str(target.get("activity") or "present"),
            confidence=float(target.get("confidence", 0.95) or 0.95),
        ))

    normalized_zones = []
    zones = []
    for z in payload.zones:
        zone_id = z.get("zone_id", "unknown")
        occupied = z.get("occupied", False)
        fallback_count = int(z.get("target_count", 0) or 0)
        if payload.source == "aqara_cloud":
            target_count = target_counts_by_zone.get(zone_id, 0)
        else:
            target_count = target_counts_by_zone.get(zone_id, fallback_count)
        normalized_zone = {
            **z,
            "zone_id": zone_id,
            "name": z.get("name", zone_id),
            "occupied": occupied,
            "target_count": target_count,
        }
        normalized_zones.append(normalized_zone)
        zones.append(FP2Zone(
            zone_id=zone_id,
            name=normalized_zone["name"],
            occupied=occupied,
            target_count=target_count,
        ))

    snapshot = FP2Snapshot(
        timestamp=datetime.fromtimestamp(payload.timestamp),
        presence=payload.presence,
        zones=zones,
        targets=targets,
        raw_attributes={
            "source": payload.source,
            "transport": payload.connection.get("transport") or payload.source,
            "zones": normalized_zones,
            "targets": normalized_targets,
            "light_level": payload.light_level,
            "push_time": time.time(),
            **payload.raw_attributes,
        },
    )

    # Update in-memory store
    _hap_latest["snapshot"] = snapshot
    _hap_latest["updated_at"] = time.time()
    _hap_latest["device"] = payload.device
    _hap_latest["connection"] = payload.connection
    _record_raw_capture(snapshot)

    # Also update fp2_service's last snapshot if available
    try:
        fp2_service = get_fp2_service()
        fp2_service._last_snapshot = snapshot
        await fp2_service._notify_listeners(snapshot)
    except Exception:
        pass

    # Notify WebSocket listeners
    for q in list(_hap_listeners):
        try:
            q.put_nowait(snapshot)
        except asyncio.QueueFull:
            pass

    return {
        "status": "ok",
        "presence": payload.presence,
        "zones": len(zones),
        "targets": len(targets),
    }


@router.post("/push")
async def push_fp2_data(payload: HAPPushPayload):
    """Receive FP2 data directly from HAP client or external Aqara monitor."""
    return await _ingest_fp2_payload(payload)


@router.get("/hap-status")
async def get_hap_status():
    """Check status of direct HAP connection."""
    snapshot = _hap_latest.get("snapshot")
    updated = _hap_latest.get("updated_at")

    if snapshot is None:
        return {
            "connected": False,
            "message": "Нет данных от HAP-клиента. Запустите: python3 scripts/fp2_hap_client.py monitor --backend http://localhost:8000",
        }

    age = time.time() - updated if updated else None
    stale = age is not None and age > 10

    return {
        "connected": not stale,
        "stale": stale,
        "last_update_age_sec": round(age, 1) if age else None,
        "presence": snapshot.presence,
        "zones": [{"zone_id": z.zone_id, "occupied": z.occupied} for z in snapshot.zones],
        "targets": len(snapshot.targets),
        "source": "hap_direct",
        "device": _build_device_metadata(get_fp2_service()),
    }


@router.websocket("/ws/hap")
async def websocket_hap_stream(websocket: WebSocket):
    """WebSocket stream for real-time FP2 data from HAP client."""
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _hap_listeners.append(queue)

    try:
        # Send current state first
        snapshot = _hap_latest.get("snapshot")
        if snapshot:
            fp2_service = get_fp2_service()
            await websocket.send_json(fp2_service.snapshot_to_pose_data(snapshot))

        while True:
            snap = await queue.get()
            fp2_service = get_fp2_service()
            await websocket.send_json(fp2_service.snapshot_to_pose_data(snap))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("HAP websocket error: %s", exc)
    finally:
        if queue in _hap_listeners:
            _hap_listeners.remove(queue)
