"""
FP2 (Aqara mmWave) integration endpoints.

Supports two data sources:
  1. Home Assistant REST API polling (original)
  2. Direct HAP push from fp2_hap_client.py (new)
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

from src.api.dependencies import get_fp2_service
from src.services.fp2_service import FP2Service, FP2Snapshot, FP2Zone, FP2Target

logger = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory store for HAP push data ────────────────────────
_hap_latest: Dict[str, Any] = {}
_hap_listeners: list = []
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_PAIRING_DATA_PATH = _PROJECT_ROOT / ".fp2_pairing.json"


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


def _load_pairing_metadata() -> Dict[str, Any]:
    """Read saved HAP pairing metadata if present."""
    if not _PAIRING_DATA_PATH.exists():
        return {}

    try:
        return json.loads(_PAIRING_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read FP2 pairing metadata from %s", _PAIRING_DATA_PATH)
        return {}


def _has_direct_hap_pairing() -> bool:
    """Check whether the workspace is configured for direct HAP mode."""
    return _PAIRING_DATA_PATH.exists()


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
    payload["metadata"]["available"] = False
    payload["metadata"]["presence"] = False
    payload["metadata"]["stale"] = True
    payload["metadata"]["error"] = reason
    payload["persons"] = []
    payload["zone_summary"] = {}
    return payload


def _build_device_metadata(fp2_service: FP2Service) -> Dict[str, Any]:
    """Build a stable description of the bound FP2 device."""
    settings = fp2_service.settings
    pairing = _load_pairing_metadata()
    latest_snapshot = _get_latest_hap_snapshot()
    pushed_device = dict(_hap_latest.get("device") or {})
    snapshot_device = {}
    if latest_snapshot is not None:
        snapshot_device = dict(latest_snapshot.raw_attributes.get("device") or {})

    device_ip = pairing.get("AccessoryIP") or settings.fp2_ip_address
    device_port = pairing.get("AccessoryPort")
    device_label = settings.fp2_name or "Aqara FP2"
    room_label = settings.fp2_room or "-"
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

    connection = _hap_latest.get("connection") or {}
    if connection.get("transport"):
        merged["transport"] = connection.get("transport")

    return merged


@router.get("/status")
async def get_fp2_status(
    fp2_service: FP2Service = Depends(get_fp2_service),
):
    """Get FP2 integration status."""
    status = await fp2_service.get_status()
    latest_hap_snapshot = _get_latest_hap_snapshot()
    hap_snapshot = _get_recent_hap_snapshot()
    status["device"] = _build_device_metadata(fp2_service)
    if hap_snapshot is not None:
        source = str(hap_snapshot.raw_attributes.get("source") or "hap_direct")
        connection = dict(_hap_latest.get("connection") or {})
        transport = connection.get("transport") or str(hap_snapshot.raw_attributes.get("transport") or source)
        status["status"] = "healthy"
        status["running"] = True
        status["entity_id"] = source
        status["last_snapshot"] = hap_snapshot.timestamp.isoformat()
        status["presence"] = hap_snapshot.presence
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
        }
    elif latest_hap_snapshot is not None or _has_direct_hap_pairing():
        source = "hap_direct"
        connection = dict(_hap_latest.get("connection") or {})
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
):
    """Get latest FP2 snapshot converted to pose-like output."""
    if not fp2_service.settings.fp2_enabled:
        data = fp2_service.snapshot_to_pose_data()
        data["metadata"]["enabled"] = False
        return data

    hap_snapshot = _get_recent_hap_snapshot()
    if hap_snapshot is not None:
        snapshot = hap_snapshot
        source = str(snapshot.raw_attributes.get("source") or "hap_direct")
        resolved_entity_id = source
    elif _get_latest_hap_snapshot() is not None:
        return _build_stale_hap_payload(
            _get_latest_hap_snapshot(),
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
    zones: list = []
    targets: list = []
    light_level: Optional[float] = None
    source: str = "hap_direct"
    raw_attributes: Dict[str, Any] = {}
    device: Dict[str, Any] = {}
    connection: Dict[str, Any] = {}


@router.post("/push")
async def push_fp2_data(payload: HAPPushPayload):
    """Receive FP2 data directly from HAP client (scripts/fp2_hap_client.py).

    This bypasses HA entirely — the HAP client reads FP2 via HomeKit
    and pushes snapshots here.
    """
    global _hap_latest

    # Convert to FP2Snapshot
    zones = []
    targets = []
    for z in payload.zones:
        zone_id = z.get("zone_id", "unknown")
        occupied = z.get("occupied", False)
        zones.append(FP2Zone(
            zone_id=zone_id,
            name=z.get("name", zone_id),
            occupied=occupied,
            target_count=int(z.get("target_count", 1 if occupied else 0) or 0),
        ))
        if occupied and not payload.targets:
            targets.append(FP2Target(
                target_id=f"person_{zone_id}",
                zone_id=zone_id,
                activity="present",
                confidence=0.95,
            ))

    if payload.targets:
        for target in payload.targets:
            zone_id = target.get("zone_id", "detection_area")
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

    snapshot = FP2Snapshot(
        timestamp=datetime.fromtimestamp(payload.timestamp),
        presence=payload.presence,
        zones=zones,
        targets=targets,
        raw_attributes={
            "source": payload.source,
            "transport": payload.connection.get("transport") or payload.source,
            "zones": payload.zones,
            "targets": payload.targets,
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
