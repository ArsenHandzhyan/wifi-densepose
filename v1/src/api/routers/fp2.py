"""
FP2 (Aqara mmWave) integration endpoints.

Supports two data sources:
  1. Home Assistant REST API polling (original)
  2. Direct HAP push from fp2_hap_client.py (new)
"""

import logging
import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, Query, HTTPException
from pydantic import BaseModel

from src.api.dependencies import (
    get_fp2_service,
    require_auth,
    require_websocket_auth_if_enabled,
)
from src.services.fp2_service import FP2Service, FP2Snapshot, FP2Zone, FP2Target

logger = logging.getLogger(__name__)
router = APIRouter()

# ── In-memory store for HAP push data ────────────────────────
_hap_latest: Dict[str, Any] = {}
_hap_listeners: list = []


def _selected_entity_id(fp2_service: FP2Service, entity_id: str | None) -> str:
    return entity_id or fp2_service.settings.fp2_entity_id


def _build_fp2_pose_payload(
    fp2_service: FP2Service,
    *,
    entity_id: str | None = None,
    snapshot: FP2Snapshot | None = None,
) -> Dict[str, Any] | None:
    selected_entity_id = _selected_entity_id(fp2_service, entity_id)

    if not fp2_service.settings.fp2_enabled:
        payload = fp2_service.snapshot_to_pose_data()
        payload.setdefault("metadata", {})
        payload["metadata"].update(
            {
                "enabled": False,
                "entity_id": selected_entity_id,
                "fp2_state": "disabled",
                "stale": False,
                "upstream_available": False,
            }
        )
        return payload

    if snapshot is not None:
        payload = fp2_service.snapshot_to_pose_data(snapshot)
        payload.setdefault("metadata", {})
        payload["metadata"].update(
            {
                "enabled": True,
                "entity_id": selected_entity_id,
                "fp2_state": "fresh",
                "stale": False,
                "upstream_available": True,
            }
        )
        return payload

    cached_snapshot = fp2_service.last_snapshot
    if cached_snapshot is None:
        return None

    payload = fp2_service.snapshot_to_pose_data(cached_snapshot)
    payload.setdefault("metadata", {})
    payload["metadata"].update(
        {
            "enabled": True,
            "entity_id": selected_entity_id,
            "fp2_state": "stale_cache",
            "stale": True,
            "upstream_available": False,
            "cached_snapshot_timestamp": cached_snapshot.timestamp.isoformat(),
        }
    )
    if fp2_service.last_error:
        payload["metadata"]["last_error"] = fp2_service.last_error
        payload["metadata"]["message"] = "Serving cached FP2 snapshot because upstream is unavailable"
    return payload


def _build_fp2_unavailable_detail(
    fp2_service: FP2Service,
    *,
    entity_id: str | None = None,
) -> Dict[str, Any]:
    selected_entity_id = _selected_entity_id(fp2_service, entity_id)
    return {
        "error": "fp2_upstream_unavailable",
        "message": "FP2 upstream unavailable and no cached snapshot is available",
        "entity_id": selected_entity_id,
        "enabled": True,
        "upstream_available": False,
        "cached_snapshot_available": False,
        "last_error": fp2_service.last_error,
    }


@router.get("/status")
async def get_fp2_status(
    fp2_service: FP2Service = Depends(get_fp2_service),
):
    """Get FP2 integration status."""
    status = await fp2_service.get_status()
    status["enabled"] = fp2_service.settings.fp2_enabled
    return status


@router.get("/current")
async def get_fp2_current_pose_like_data(
    entity_id: str | None = Query(default=None, description="Optional HA entity_id override"),
    fp2_service: FP2Service = Depends(get_fp2_service),
):
    """Get latest FP2 snapshot converted to pose-like output."""
    if not fp2_service.settings.fp2_enabled:
        return _build_fp2_pose_payload(fp2_service, entity_id=entity_id)

    snapshot = await fp2_service.fetch_snapshot(entity_id=entity_id)
    payload = _build_fp2_pose_payload(fp2_service, entity_id=entity_id, snapshot=snapshot)
    if payload is None:
        raise HTTPException(
            status_code=503,
            detail=_build_fp2_unavailable_detail(fp2_service, entity_id=entity_id),
        )
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
                snapshot = await fp2_service.fetch_snapshot(entity_id=entity_id)
                payload = _build_fp2_pose_payload(fp2_service, entity_id=entity_id, snapshot=snapshot)
                if payload is None:
                    await websocket.send_json({
                        "type": "error",
                        **_build_fp2_unavailable_detail(fp2_service, entity_id=entity_id),
                    })
                else:
                    await websocket.send_json(payload)
                await asyncio.sleep(fp2_service.settings.fp2_poll_interval)
        else:
            queue = fp2_service.subscribe()
            try:
                initial_payload = _build_fp2_pose_payload(fp2_service)
                if initial_payload is not None:
                    await websocket.send_json(initial_payload)
                elif fp2_service.last_error:
                    await websocket.send_json({
                        "type": "error",
                        **_build_fp2_unavailable_detail(fp2_service),
                    })
                while True:
                    snapshot = await queue.get()
                    await websocket.send_json(
                        _build_fp2_pose_payload(fp2_service, snapshot=snapshot)
                    )
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
    light_level: Optional[float] = None
    source: str = "hap_direct"


@router.post("/push")
async def push_fp2_data(
    payload: HAPPushPayload,
    current_user: Optional[Dict[str, Any]] = Depends(require_auth),
):
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
            name=zone_id,
            occupied=occupied,
            target_count=1 if occupied else 0,
        ))
        if occupied:
            targets.append(FP2Target(
                target_id=f"person_{zone_id}",
                zone_id=zone_id,
                activity="present",
                confidence=0.95,
            ))

    snapshot = FP2Snapshot(
        timestamp=datetime.fromtimestamp(payload.timestamp, tz=timezone.utc),
        presence=payload.presence,
        zones=zones,
        targets=targets,
        raw_attributes={
            "source": payload.source,
            "light_level": payload.light_level,
            "push_time": time.time(),
        },
    )

    # Update in-memory store
    _hap_latest["snapshot"] = snapshot
    _hap_latest["updated_at"] = time.time()

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
        "accepted_by": current_user["id"] if current_user else "anonymous",
    }


@router.get("/hap-status")
async def get_hap_status(
    current_user: Optional[Dict[str, Any]] = Depends(require_auth),
):
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
        "requested_by": current_user["id"] if current_user else "anonymous",
    }


@router.websocket("/ws/hap")
async def websocket_hap_stream(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="Authentication token"),
):
    """WebSocket stream for real-time FP2 data from HAP client."""
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _hap_listeners.append(queue)

    try:
        await require_websocket_auth_if_enabled(token)

        # Send current state first
        snapshot = _hap_latest.get("snapshot")
        if snapshot:
            fp2_service = get_fp2_service()
            await websocket.send_json(fp2_service.snapshot_to_pose_data(snapshot))

        while True:
            snap = await queue.get()
            fp2_service = get_fp2_service()
            await websocket.send_json(fp2_service.snapshot_to_pose_data(snap))
    except HTTPException as exc:
        await websocket.send_json({
            "type": "error",
            "message": exc.detail,
        })
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("HAP websocket error: %s", exc)
    finally:
        if queue in _hap_listeners:
            _hap_listeners.remove(queue)
