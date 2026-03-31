"""CSI Real-Time Prediction & Recording API Router."""

import logging
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional, List

from ...services.csi_prediction_service import csi_prediction_service
from ...services.csi_recording_service import csi_recording_service
from ...services.csi_management_probe import (
    build_csi_probe_timeout,
    infer_csi_status_schema,
    probe_csi_node_status,
)
from ...services.recording_truth_hardening import build_truth_hardening_report
from ...services.tts_service import get_tts_service
from ...services.zone_calibration_service import zone_calibration_service
from ...services.csi_node_inventory import list_csi_nodes
from ...services.fewshot_calibration_storage_service import fewshot_calibration_storage_service
from ...services.fewshot_adaptation_consumer_service import fewshot_adaptation_consumer_service
from ...services.dual_validation_service import DualValidationService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CSI Prediction"])
PROJECT_ROOT = Path(__file__).resolve().parents[4]
TTS_HELPER = PROJECT_ROOT / "scripts" / "tts_helper.py"
GARAGE_ZONE_REVIEW_PACKET_SCRIPT = PROJECT_ROOT / "scripts" / "init_garage_zone_review_packet.py"
_tts_helper_lock = threading.Lock()
_tts_helper_proc: subprocess.Popen | None = None
DUAL_VALIDATION_GOLD_DIR = PROJECT_ROOT / "output" / "garage_guided_review_dense1"
DUAL_VALIDATION_CAPTURES_DIR = PROJECT_ROOT / "temp" / "captures"
DUAL_VALIDATION_OUTPUT_DIR = PROJECT_ROOT / "output" / "dual_validation"
_validation_cache: dict[str, Any] = {}
_validation_cache_ts: float | None = None
_validation_source_mtime: float | None = None
_validation_resolutions_path = DUAL_VALIDATION_OUTPUT_DIR / "resolutions.json"


def _load_validation_resolutions() -> dict[str, Any]:
    if _validation_resolutions_path.exists():
        try:
            return json.loads(_validation_resolutions_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_validation_resolutions(payload: dict[str, Any]) -> None:
    DUAL_VALIDATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _validation_resolutions_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _latest_validation_source_mtime() -> float:
    latest = 0.0
    if _validation_resolutions_path.exists():
        try:
            latest = max(latest, _validation_resolutions_path.stat().st_mtime)
        except OSError:
            pass
    if DUAL_VALIDATION_GOLD_DIR.exists():
        for ann_path in DUAL_VALIDATION_GOLD_DIR.rglob("manual_annotations_v1.json"):
            try:
                latest = max(latest, ann_path.stat().st_mtime)
            except OSError:
                continue
    return latest


def _ensure_validation_state(force: bool = False) -> dict[str, Any]:
    global _validation_cache_ts, _validation_cache, _validation_source_mtime
    now = time.time()
    source_mtime = _latest_validation_source_mtime()
    if (
        not force
        and _validation_cache_ts
        and now - _validation_cache_ts < 15
        and _validation_source_mtime == source_mtime
    ):
        return _validation_cache

    svc = DualValidationService(
        gold_dir=DUAL_VALIDATION_GOLD_DIR,
        captures_dir=DUAL_VALIDATION_CAPTURES_DIR,
    )
    svc.load_gold_annotations()
    svc.load_capture_data()
    svc.build_zone_fingerprints()
    svc.validate_all()
    validated_doc, conflicts_doc = svc.get_output_bundle()
    resolutions = _load_validation_resolutions()
    _validation_cache = {
        "generated": validated_doc.get("generated"),
        "gold_fingerprints": validated_doc.get("gold_fingerprints", {}),
        "segments": validated_doc.get("segments", []),
        "summary": validated_doc.get("summary", {}),
        "conflicts": conflicts_doc.get("conflicts", []),
        "resolutions": resolutions.get("resolutions", {}),
    }
    _validation_cache_ts = now
    _validation_source_mtime = source_mtime
    return _validation_cache


def _summarize_validation(segments: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(segments)
    validated = len([s for s in segments if s.get("status") == "validated"])
    conflict = len([s for s in segments if s.get("status") == "conflict"])
    ambiguous = len([s for s in segments if s.get("status") == "ambiguous"])
    return {
        "total_segments": total,
        "validated_count": validated,
        "conflict_count": conflict,
        "ambiguous_count": ambiguous,
        "validated_pct": validated / total if total else 0.0,
        "conflict_pct": conflict / total if total else 0.0,
        "ambiguous_pct": ambiguous / total if total else 0.0,
    }


def _segment_to_status(segment: dict[str, Any], resolution: dict[str, Any] | None) -> dict[str, Any]:
    start_sec = float(segment.get("start_sec", 0))
    end_sec = float(segment.get("end_sec", 0))
    return {
        "segment_id": segment.get("id"),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "duration_sec": max(0.0, end_sec - start_sec),
        "video_label": segment.get("video_label"),
        "csi_label": segment.get("csi_closest_zone"),
        "similarity_score": segment.get("csi_similarity"),
        "validation_status": segment.get("status"),
        "resolved_by": resolution.get("resolved_by") if resolution else None,
        "resolved_at": resolution.get("resolved_at") if resolution else None,
        "resolution": resolution.get("resolution") if resolution else None,
    }


def _extract_node_fingerprint(stats: dict[str, Any]) -> dict[str, Any]:
    per_node: dict[str, Any] = {}
    for key, value in stats.items():
        if "_" not in key:
            continue
        node_id, feat = key.split("_", 1)
        if node_id not in per_node:
            per_node[node_id] = {}
        if feat in {"amp_mean", "sc_var_mean", "rssi_mean", "motion_mean", "tvar", "diff1"}:
            per_node[node_id][feat] = value.get("mean") if isinstance(value, dict) else value
    return per_node


def _resolve_tts_helper_python() -> str:
    candidates = [
        "/opt/homebrew/opt/python@3.14/bin/python3.14",
        shutil.which("python3"),
        sys.executable,
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            probe = subprocess.run(
                [candidate, "-c", "import elevenlabs"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if probe.returncode == 0:
                return candidate
        except Exception:
            continue
    return sys.executable


TTS_HELPER_PYTHON = _resolve_tts_helper_python()


def _run_zone_review_bootstrap(summary_path: Path) -> str | None:
    if not GARAGE_ZONE_REVIEW_PACKET_SCRIPT.exists():
        logger.warning("record_stop zone-review bootstrap script missing: %s", GARAGE_ZONE_REVIEW_PACKET_SCRIPT)
        return None
    try:
        completed = subprocess.run(
            [sys.executable, str(GARAGE_ZONE_REVIEW_PACKET_SCRIPT), "--summary", str(summary_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        logger.warning("record_stop zone-review bootstrap failed for %s: %s", summary_path, exc)
        return None
    if completed.returncode != 0:
        logger.warning(
            "record_stop zone-review bootstrap exited with code %s for %s: %s",
            completed.returncode,
            summary_path,
            (completed.stderr or completed.stdout).strip(),
        )
        return None
    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    if not lines:
        logger.warning("record_stop zone-review bootstrap returned no output for %s", summary_path)
        return None
    packet_path = Path(lines[-1]).expanduser()
    if not packet_path.exists():
        logger.warning("record_stop zone-review packet does not exist for %s: %s", summary_path, packet_path)
        return None
    return str(packet_path)


def _normalize_record_stop_result(result: dict[str, Any]) -> dict[str, Any]:
    summary_path_raw = result.get("session_summary_path")
    if not summary_path_raw:
        return result

    summary_path = Path(str(summary_path_raw)).expanduser()
    if not summary_path.exists():
        return result

    try:
        session_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("record_stop failed to read summary %s: %s", summary_path, exc)
        return result

    changed = False
    zone_review_packet_path = str(session_summary.get("zone_review_packet_path") or "").strip() or None
    if zone_review_packet_path:
        packet_path_obj = Path(zone_review_packet_path).expanduser()
        if not packet_path_obj.exists():
            session_summary.pop("zone_review_packet_path", None)
            zone_review_packet_path = None
            changed = True
        else:
            zone_review_packet_path = str(packet_path_obj)
            session_summary["zone_review_packet_path"] = zone_review_packet_path

    if not zone_review_packet_path:
        eligibility_probe = build_truth_hardening_report(session_summary)
        zone_packet = (eligibility_probe.get("zone_review_packet") or {})
        if bool(zone_packet.get("eligible")):
            generated_path = _run_zone_review_bootstrap(summary_path)
            if generated_path:
                zone_review_packet_path = generated_path
                session_summary["zone_review_packet_path"] = zone_review_packet_path
                changed = True

    truth_hardening = build_truth_hardening_report(
        session_summary,
        zone_review_packet_path=zone_review_packet_path,
    )
    if session_summary.get("truth_hardening") != truth_hardening:
        session_summary["truth_hardening"] = truth_hardening
        changed = True

    if changed:
        try:
            summary_path.write_text(
                json.dumps(session_summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("record_stop failed to persist normalized summary %s: %s", summary_path, exc)

    result["truth_hardening"] = session_summary.get("truth_hardening")
    result["zone_review_packet_path"] = zone_review_packet_path
    return result


async def _ensure_csi_runtime_started() -> dict[str, Any]:
    """Ensure the CSI runtime is available for live control paths."""
    try:
        result = await csi_prediction_service.ensure_started(interval=2.0)
    except OSError as e:
        if "Address already in use" in str(e):
            raise HTTPException(
                status_code=409,
                detail="UDP port 5005 is already in use. Stop other CSI capture processes first.",
            )
        raise HTTPException(status_code=500, detail=str(e))

    if result.get("ok"):
        return result

    status_name = result.get("status", "startup_failed")
    if status_name == "model_not_loaded":
        raise HTTPException(
            status_code=503,
            detail="CSI runtime model unavailable. Train or restore the runtime bundle before starting.",
        )
    raise HTTPException(
        status_code=503,
        detail=f"CSI runtime start failed: {status_name}",
    )


def _raise_record_start_error(result: dict[str, Any]) -> None:
    error_code = str(result.get("error_code") or "record_start_failed")
    message = str(result.get("error") or "Failed")
    detail: dict[str, Any] = {
        "error": error_code,
        "message": message,
    }
    if "preflight" in result:
        detail["preflight"] = result.get("preflight")
    if "teacher_status" in result:
        detail["teacher_status"] = result.get("teacher_status")

    if error_code == "already_recording":
        raise HTTPException(status_code=409, detail=detail)
    if error_code == "invalid_teacher_config":
        raise HTTPException(status_code=400, detail=detail)
    raise HTTPException(status_code=503, detail=detail)


def _raise_zone_calibration_error(result: dict[str, Any]) -> None:
    error_code = str(result.get("error_code") or "zone_calibration_failed")
    detail: dict[str, Any] = {
        "error": error_code,
        "message": str(result.get("error") or "Failed"),
    }
    if "active_zone" in result:
        detail["active_zone"] = result.get("active_zone")
    if "quality" in result:
        detail["quality"] = result.get("quality")
    if "zones_ready_count" in result:
        detail["zones_ready_count"] = result.get("zones_ready_count")
    if "zones_calibrated" in result:
        detail["zones_calibrated"] = result.get("zones_calibrated")
    if "min_centroid_distance" in result:
        detail["min_centroid_distance"] = result.get("min_centroid_distance")

    if error_code == "unknown_zone":
        raise HTTPException(status_code=404, detail=detail)
    if error_code in {"capture_in_progress", "insufficient_zone_coverage", "centroids_too_close"}:
        raise HTTPException(status_code=409, detail=detail)
    raise HTTPException(status_code=400, detail=detail)


class RecordingVoiceCueRequest(BaseModel):
    at_sec: float
    text: str


class RecordingStartRequest(BaseModel):
    label: str
    chunk_sec: int = 60
    with_video: bool = False
    video_required: Optional[bool] = None
    teacher_source_kind: Optional[str] = None
    teacher_source_url: str = ""
    teacher_source_name: str = ""
    teacher_device: str = ""
    teacher_device_name: str = ""
    teacher_input_pixel_format: str = "nv12"
    teacher_start_timeout_sec: float = 12.0
    person_count: Optional[int] = None
    motion_type: str = ""
    notes: str = ""
    voice_prompt: bool = True
    skip_preflight: bool = False
    voice_cues: list[RecordingVoiceCueRequest] = Field(default_factory=list)


class RuntimeModelSelectRequest(BaseModel):
    model_id: str


class ValidationResolveRequest(BaseModel):
    segment_id: str
    resolution: str
    operator_note: str | None = None


class ValidationBatchApproveRequest(BaseModel):
    recording_id: str | None = None
    dry_run: bool = False


@router.get("/status")
async def csi_status():
    """Current CSI prediction status with history."""
    return csi_prediction_service.get_status()


@router.get("/features")
async def csi_features():
    """Dump the last extracted window features for training data collection.

    Returns the raw feature dict from the most recent prediction window,
    useful for collecting labeled training data from live CSI stream.
    """
    feat = getattr(csi_prediction_service, '_last_window_feat', None)
    if feat is None:
        raise HTTPException(status_code=404, detail="No window features available yet")
    current = csi_prediction_service.current
    return {
        "features": {k: float(v) if isinstance(v, (int, float)) else v for k, v in feat.items()},
        "binary": current.get("binary", "unknown"),
        "binary_confidence": current.get("binary_confidence", 0),
        "coarse": current.get("coarse", "unknown"),
        "nodes_active": current.get("nodes_active", 0),
        "pps": current.get("pps", 0),
        "window_time": current.get("window_time", 0),
        "ts": time.time(),
    }


@router.get("/models")
async def csi_models():
    """List runtime-ready CSI models supported by the current loader."""
    models = csi_prediction_service.list_runtime_ready_models()
    default_item = next((item for item in models if item.get("is_default")), None)
    active_item = next((item for item in models if item.get("is_active")), None)
    return {
        "models": models,
        "active_model_id": (active_item.get("model_id") if active_item else None) or csi_prediction_service.current.get("model_id"),
        "model_loaded": csi_prediction_service.binary_model is not None,
        "default_model_id": default_item.get("model_id") if default_item else None,
    }


@router.post("/model/select")
async def csi_select_model(req: RuntimeModelSelectRequest):
    """Select an already prepared runtime-ready CSI model."""
    try:
        selected = csi_prediction_service.select_runtime_model(req.model_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=500, detail=str(error))

    return {
        "status": "selected",
        "model": selected,
        "model_version": csi_prediction_service.current.get("model_version"),
        "model_loaded": csi_prediction_service.binary_model is not None,
    }


@router.get("/validation/status")
async def csi_validation_status(
    recording_id: str | None = None,
    manifest_version: str | None = None,
    status_filter: str | None = None,
    refresh: bool = False,
):
    state = _ensure_validation_state(force=refresh)
    segments = list(state.get("segments", []))
    if recording_id:
        segments = [s for s in segments if s.get("recording_label") == recording_id]
    if status_filter and status_filter != "all":
        segments = [s for s in segments if s.get("status") == status_filter]
    resolutions = state.get("resolutions", {})
    payload_segments = [
        _segment_to_status(seg, resolutions.get(seg.get("id"))) for seg in segments
    ]
    return {
        "recording_id": recording_id,
        "manifest_version": manifest_version,
        "summary": _summarize_validation(segments),
        "segments": payload_segments,
    }


@router.get("/validation/segment/{segment_id}")
async def csi_validation_segment(segment_id: str):
    state = _ensure_validation_state(force=False)
    segments = state.get("segments", [])
    segment = next((s for s in segments if s.get("id") == segment_id), None)
    if not segment:
        raise HTTPException(status_code=404, detail="segment not found")
    resolutions = state.get("resolutions", {})
    closest_zone = segment.get("csi_closest_zone")
    fp_stats = state.get("gold_fingerprints", {}).get(closest_zone, {})
    per_node = _extract_node_fingerprint(fp_stats.get("stats", {}) if isinstance(fp_stats, dict) else {})
    resolution = resolutions.get(segment_id)
    return {
        "segment_id": segment_id,
        "start_sec": segment.get("start_sec"),
        "end_sec": segment.get("end_sec"),
        "video_label": segment.get("video_label"),
        "csi_label": segment.get("csi_closest_zone"),
        "similarity_score": segment.get("csi_similarity"),
        "validation_status": segment.get("status"),
        "all_similarities": segment.get("all_similarities", {}),
        "csi_fingerprint": {"per_node": per_node, "zone": closest_zone},
        "resolution": resolution.get("resolution") if resolution else None,
        "operator_note": resolution.get("operator_note") if resolution else None,
        "resolved_at": resolution.get("resolved_at") if resolution else None,
    }


@router.post("/validation/resolve")
async def csi_validation_resolve(payload: ValidationResolveRequest):
    if payload.resolution not in {"confirm_video", "accept_csi", "mark_ambiguous"}:
        raise HTTPException(status_code=400, detail="invalid resolution")
    state = _ensure_validation_state(force=False)
    resolutions = state.get("resolutions", {})
    now_iso = datetime.now(timezone.utc).isoformat()
    resolutions[payload.segment_id] = {
        "resolution": payload.resolution,
        "resolved_by": "operator",
        "resolved_at": now_iso,
        "operator_note": payload.operator_note,
    }
    _save_validation_resolutions({"resolutions": resolutions})
    state["resolutions"] = resolutions
    return {
        "segment_id": payload.segment_id,
        "resolution": payload.resolution,
        "resolved_at": now_iso,
        "updated_summary": _summarize_validation(state.get("segments", [])),
    }


@router.post("/validation/batch-approve")
async def csi_validation_batch_approve(payload: ValidationBatchApproveRequest):
    state = _ensure_validation_state(force=False)
    segments = state.get("segments", [])
    if payload.recording_id:
        segments = [s for s in segments if s.get("recording_label") == payload.recording_id]
    validated = [s for s in segments if s.get("status") == "validated"]
    if payload.dry_run:
        return {"approved_count": len(validated), "skipped_count": 0, "updated_summary": _summarize_validation(segments)}
    resolutions = state.get("resolutions", {})
    now_iso = datetime.now(timezone.utc).isoformat()
    for seg in validated:
        seg_id = seg.get("id")
        if not seg_id:
            continue
        resolutions[seg_id] = {
            "resolution": "confirm_video",
            "resolved_by": "auto",
            "resolved_at": now_iso,
            "operator_note": None,
        }
    _save_validation_resolutions({"resolutions": resolutions})
    state["resolutions"] = resolutions
    return {
        "approved_count": len(validated),
        "skipped_count": 0,
        "updated_summary": _summarize_validation(segments),
    }


@router.post("/start")
async def csi_start():
    """Start CSI prediction (load model + start UDP listener)."""
    return await _ensure_csi_runtime_started()


@router.post("/stop")
async def csi_stop():
    """Stop CSI prediction."""
    return await csi_prediction_service.stop()


@router.post("/voice/start")
async def csi_voice_start():
    """Enable real-time voice announcements via ElevenLabs TTS."""
    return csi_prediction_service.voice_start()


@router.post("/voice/stop")
async def csi_voice_stop():
    """Disable voice announcements."""
    return csi_prediction_service.voice_stop()


@router.get("/nodes")
async def csi_nodes():
    """Check ESP32 node health across management and CSI data planes."""
    import aiohttp
    nodes = []
    mgmt_by_ip: dict[str, dict[str, Any]] = {}
    csi_health = csi_prediction_service.get_node_health()

    csi_nodes_list = list_csi_nodes()
    async with aiohttp.ClientSession(timeout=build_csi_probe_timeout()) as session:
        probe_results = await asyncio.gather(
            *(
                probe_csi_node_status(
                    session,
                    str(node["ip"]),
                    attempts=3,
                    retry_delay_sec=0.35,
                )
                for node in csi_nodes_list
            )
        )

    for node, probe in zip(csi_nodes_list, probe_results):
        ip = str(node["ip"])
        if probe.get("ok"):
            data = probe.get("data") or {}
            mgmt_by_ip[ip] = {
                "ok": True,
                "uptime": data.get("uptime_sec", 0),
                "errors": data.get("send_errors", data.get("send_errors_total", 0)),
                "firmware": data.get("firmware_version", data.get("version", data.get("fw", "?"))),
                "status_schema": infer_csi_status_schema(data),
                "raw": data,
            }
        else:
            mgmt_by_ip[ip] = {
                "ok": False,
                "error": probe.get("error"),
                "error_type": probe.get("error_type"),
            }

    for node in csi_nodes_list:
        name = str(node["node_id"])
        ip = str(node["ip"])
        mgmt = mgmt_by_ip.get(ip, {"ok": False, "error": "not_probed"})
        stream = csi_health.get(name, {})
        stream_status = str(stream.get("status") or "offline")
        stream_ok = stream_status in {"online", "degraded"}
        mgmt_ok = bool(mgmt.get("ok"))

        if mgmt_ok and stream_status == "online":
            status = "up"
        elif mgmt_ok or stream_ok:
            status = "degraded"
        else:
            status = "down"

        node_payload = {
            "name": name,
            "ip": ip,
            "status": status,
            "role": node.get("role", "unknown"),
            "required": bool(node.get("required")),
            "position_known": bool(node.get("position_known")),
            "management_status": "up" if mgmt_ok else "down",
            "management_ok": mgmt_ok,
            "stream_status": stream_status,
            "stream_ok": stream_ok,
            "last_seen_sec": stream.get("last_seen_sec"),
            "split_brain": bool(stream_ok and not mgmt_ok),
        }
        if mgmt_ok:
            raw = mgmt.get("raw") or {}
            node_payload["uptime"] = mgmt.get("uptime", 0)
            node_payload["errors"] = mgmt.get("errors", 0)
            node_payload["firmware"] = mgmt.get("firmware", "?")
            node_payload["status_schema"] = mgmt.get("status_schema")
            node_payload["runtime_mode"] = raw.get("runtime_mode")
            node_payload["connected_ssid"] = raw.get("connected_ssid")
            node_payload["connected_bssid"] = raw.get("connected_bssid")
            node_payload["primary_channel"] = raw.get("primary_channel")
            node_payload["secondary_channel"] = raw.get("secondary_channel")
            node_payload["authmode"] = raw.get("authmode")
            node_payload["tx_power_dbm"] = raw.get("tx_power_dbm")
            node_payload["http_restarts"] = raw.get("http_restarts")
        else:
            node_payload["management_error"] = mgmt.get("error")
        nodes.append(node_payload)

    return {"nodes": nodes}


@router.get("/nodes/health")
async def csi_nodes_health():
    """Per-node health based on last-seen CSI/keepalive packets."""
    return csi_prediction_service.get_node_health()


@router.get("/nodes/packets")
async def csi_nodes_packets():
    """Per-node packet counts in current buffer — diagnostic endpoint."""
    import time
    svc = csi_prediction_service
    now = time.time() - (svc._start_time or time.time())
    window_start = now - 2.0  # last 2 seconds (WINDOW_SEC)
    result = {}
    for ip, pkts in svc._packets.items():
        total = len(pkts)
        in_window = sum(1 for t, _, _, _ in pkts if t >= window_start)
        result[ip] = {"total_buffer": total, "in_window_2s": in_window}
    return result


# ── Recording endpoints ────────────────────────────────────────

@router.post("/record/start")
async def record_start(req: RecordingStartRequest):
    """Start recording CSI data (parallel with live prediction)."""
    # Ensure prediction is running (UDP listener active).
    await _ensure_csi_runtime_started()

    result = await csi_recording_service.start_recording(
        label=req.label,
        chunk_sec=req.chunk_sec,
        with_video=req.with_video,
        video_required=req.video_required,
        teacher_source_kind=req.teacher_source_kind,
        teacher_source_url=req.teacher_source_url or None,
        teacher_source_name=req.teacher_source_name or None,
        teacher_device=req.teacher_device or None,
        teacher_device_name=req.teacher_device_name or None,
        teacher_input_pixel_format=req.teacher_input_pixel_format or None,
        teacher_start_timeout_sec=req.teacher_start_timeout_sec,
        person_count=req.person_count,
        motion_type=req.motion_type,
        notes=req.notes,
        voice_prompt=req.voice_prompt,
        skip_preflight=req.skip_preflight,
        voice_cues=[cue.model_dump() for cue in req.voice_cues],
    )
    if not result["ok"]:
        _raise_record_start_error(result)
    return result


@router.post("/record/stop")
async def record_stop():
    """Stop recording and flush all data."""
    result = await csi_recording_service.stop_recording()
    return _normalize_record_stop_result(result)


@router.get("/record/status")
async def record_status():
    """Get recording status."""
    return csi_recording_service.get_status()


@router.get("/record/preflight")
async def record_preflight(
    check_video: bool = False,
    video_required: Optional[bool] = None,
    teacher_source_kind: Optional[str] = None,
    teacher_source_url: str = "",
    teacher_source_name: str = "",
    teacher_device: str = "",
    teacher_device_name: str = "",
    teacher_input_pixel_format: str = "nv12",
    teacher_start_timeout_sec: float = 12.0,
):
    """Run pre-flight checks on all devices."""
    return await csi_recording_service.preflight_check(
        check_video=check_video,
        video_required=video_required,
        teacher_source_kind=teacher_source_kind,
        teacher_source_url=teacher_source_url or None,
        teacher_source_name=teacher_source_name or None,
        teacher_device=teacher_device or None,
        teacher_device_name=teacher_device_name or None,
        teacher_input_pixel_format=teacher_input_pixel_format or None,
        teacher_start_timeout_sec=teacher_start_timeout_sec,
    )


# ── TTS Endpoints ──────────────────────────────────────────────


class TTSSpeakRequest(BaseModel):
    text: str
    block: bool = False


class TTSPrecacheRequest(BaseModel):
    phrases: List[str]


def _helper_env(block: bool = True) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath_parts = [str(PROJECT_ROOT / "v1")]
    existing = env.get("PYTHONPATH", "").strip()
    if existing:
        pythonpath_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env["TTS_HELPER_BLOCK"] = "1" if block else "0"
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in {"TTS_PROVIDER", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE_NAME"}:
                continue
            env[key] = value.strip().strip("'").strip('"')
    return env


def _run_tts_helper(command: list[str], *, block: bool = True, timeout: float = 30.0) -> dict:
    global _tts_helper_proc
    proc = subprocess.Popen(
        [TTS_HELPER_PYTHON, str(TTS_HELPER), *command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_helper_env(block=block),
    )
    with _tts_helper_lock:
        _tts_helper_proc = proc
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError("TTS helper timed out")
    finally:
        with _tts_helper_lock:
            if _tts_helper_proc is proc:
                _tts_helper_proc = None

    if proc.returncode != 0:
        detail = stderr.strip() or stdout.strip() or "TTS helper failed"
        raise RuntimeError(detail)
    payload = (stdout or "{}").strip()
    return json.loads(payload) if payload else {}


def _spawn_tts_helper(command: list[str]) -> None:
    global _tts_helper_proc
    with _tts_helper_lock:
        existing = _tts_helper_proc
        _tts_helper_proc = None
    if existing is not None:
        try:
            if existing.poll() is None:
                existing.terminate()
                try:
                    existing.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    existing.kill()
                    existing.wait(timeout=2.0)
            else:
                existing.wait(timeout=2.0)
        except Exception:
            pass
    proc = subprocess.Popen(
        [TTS_HELPER_PYTHON, str(TTS_HELPER), *command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_helper_env(block=False),
    )
    with _tts_helper_lock:
        _tts_helper_proc = proc


def _stop_tts_helper() -> bool:
    global _tts_helper_proc
    with _tts_helper_lock:
        proc = _tts_helper_proc
        _tts_helper_proc = None
    if not proc or proc.poll() is not None:
        return False
    proc.terminate()
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2.0)
    return True


def _get_live_tts_service():
    tts = get_tts_service()
    if not tts.available and getattr(tts, "_provider", "") == "elevenlabs":
        tts = get_tts_service(force_reload=True)
    return tts


@router.get("/tts/status")
async def tts_status():
    """Get TTS service status."""
    try:
        return _run_tts_helper(["status"])
    except Exception as exc:
        logger.warning("TTS helper status failed, falling back to in-process service: %s", exc)
        tts = _get_live_tts_service()
        return {
            "available": tts.available,
            "backend": "elevenlabs" if tts.available else "macos_say",
            "provider": getattr(tts, "_provider", "unknown"),
            "voice_id": getattr(tts, "_resolved_voice_id", None),
            "voice_name": getattr(tts, "_resolved_voice_name", None),
        }


@router.get("/tts/voices")
async def tts_voices():
    """List available ElevenLabs voices."""
    try:
        return _run_tts_helper(["voices"], timeout=45.0)
    except Exception as exc:
        logger.warning("TTS helper voices failed, falling back to in-process service: %s", exc)
        tts = _get_live_tts_service()
        return {"voices": tts.list_voices()}


@router.post("/tts/speak")
async def tts_speak(req: TTSSpeakRequest):
    """Speak text through TTS."""
    try:
        if req.block:
            payload = _run_tts_helper(["speak", req.text], block=True, timeout=120.0)
        else:
            tts = _get_live_tts_service()
            _spawn_tts_helper(["speak", req.text])
            payload = {
                "ok": True,
                "backend": "elevenlabs" if tts.available else "macos_say",
                "queued": True,
            }
        payload["text"] = req.text
        return payload
    except Exception as exc:
        logger.warning("TTS helper speak failed, falling back to in-process service: %s", exc)
        tts = _get_live_tts_service()
        tts.speak(req.text, block=req.block)
        return {"ok": True, "text": req.text, "backend": "elevenlabs" if tts.available else "macos_say"}


@router.post("/tts/precache")
async def tts_precache(req: TTSPrecacheRequest):
    """Pre-generate audio cache for phrases."""
    tts = _get_live_tts_service()
    count = tts.precache(req.phrases)
    return {"ok": True, "cached": count, "total": len(req.phrases)}


@router.post("/tts/voice/{voice_id}")
async def tts_set_voice(voice_id: str):
    """Switch TTS voice."""
    try:
        return _run_tts_helper(["set-voice", voice_id], timeout=45.0)
    except Exception as exc:
        logger.warning("TTS helper set-voice failed, falling back to in-process service: %s", exc)
        tts = _get_live_tts_service()
        tts.set_voice(voice_id)
        return {"ok": True, "voice_id": voice_id}


@router.post("/tts/stop")
async def tts_stop():
    """Stop current TTS playback."""
    stopped_helper = _stop_tts_helper()
    tts = _get_live_tts_service()
    stopped_local = bool(tts.stop())
    return {
        "ok": True,
        "status": "stopped" if (stopped_helper or stopped_local) else "already_stopped",
        "stopped_helper": stopped_helper,
        "stopped_local": stopped_local,
    }


# ── V23: Empty baseline calibration endpoints ──────────────────────

@router.get("/baseline/status")
async def baseline_status():
    """Get current empty-room baseline calibration status."""
    return csi_prediction_service.get_baseline_status()


@router.post("/baseline/capture/start")
async def baseline_capture_start():
    """Start empty-room baseline capture. Room MUST be empty."""
    return csi_prediction_service.start_baseline_capture()


@router.post("/baseline/capture/stop")
async def baseline_capture_stop():
    """Stop baseline capture and finalize profiles."""
    return csi_prediction_service.stop_baseline_capture()


# ── Zone calibration endpoints (shadow-only garage zoning) ────────


class ZoneCalibrateRequest(BaseModel):
    zone: str
    duration_sec: float = 15.0


class FewshotProtocolStepRequest(BaseModel):
    id: str
    label: str
    display_zone: Optional[str] = None
    capture_zone: Optional[str] = None
    activity: Optional[str] = None
    research_only: bool = False
    duration_sec: float = 0.0
    target_windows: int = 0
    index: int = 0


class FewshotSessionStartRequest(BaseModel):
    protocol_id: str
    protocol_name: Optional[str] = None
    zone_scheme: Optional[str] = None
    total_windows: int = 0
    window_duration_sec: float = 0.0
    metadata: dict = Field(default_factory=dict)
    steps: list[FewshotProtocolStepRequest] = Field(default_factory=list)


class FewshotStepLifecycleRequest(BaseModel):
    step_id: str
    metadata: dict = Field(default_factory=dict)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class FewshotSessionFinalizeRequest(BaseModel):
    fit_result: Optional[dict] = None
    metadata: dict = Field(default_factory=dict)
    completed_at: Optional[str] = None
    status: str = "completed"


class FewshotConsumerActivateRequest(BaseModel):
    session_id: Optional[str] = None
    storage_path: Optional[str] = None


class FewshotConsumerDeactivateRequest(BaseModel):
    reason: str = "api_deactivate"


@router.get("/zone/status")
async def zone_calibration_status():
    """Get current zone calibration status (shadow-only)."""
    return zone_calibration_service.get_status()


@router.post("/zone/calibrate/start")
async def zone_calibrate_start(req: ZoneCalibrateRequest):
    """Start collecting calibration windows for a specific zone.

    Shadow-only: does NOT affect V5 production output.
    """
    result = zone_calibration_service.start_zone_capture(req.zone)
    if not result["ok"]:
        _raise_zone_calibration_error(result)
    return result


@router.post("/zone/calibrate/stop")
async def zone_calibrate_stop():
    """Stop the current zone capture phase."""
    result = zone_calibration_service.stop_zone_capture()
    return result


@router.post("/zone/calibrate/fit")
async def zone_calibrate_fit():
    """Fit NearestCentroid classifier on collected calibration windows.

    Requires at least 2 zones with >= 2 windows each.
    Shadow-only: does NOT affect V5 production output.
    """
    result = zone_calibration_service.fit()
    if not result["ok"]:
        _raise_zone_calibration_error(result)
    return result


@router.post("/zone/calibrate/inject")
async def zone_calibrate_inject(req: dict):
    """Inject current live features into a zone's calibration buffer.

    Body: {"zone": "door"|"center", "count": 10, "interval": 2}
    Captures `count` windows at `interval` seconds apart from live CSI stream.
    """
    import asyncio
    zone = req.get("zone")
    count = req.get("count", 10)
    interval = req.get("interval", 2)

    if not zone:
        raise HTTPException(status_code=400, detail="zone required")

    accepted = 0
    rejected = 0
    skipped_dup = 0
    last_t_mid = None
    # Wait for unique CSI windows (update ~every 5s), collect up to `count`
    max_attempts = count * 5  # allow extra attempts to skip duplicates
    attempts = 0
    while accepted < count and attempts < max_attempts:
        attempts += 1
        feat = dict(csi_prediction_service._last_feat_dict)
        t_mid = feat.get("t_mid")
        if not feat or t_mid is None:
            rejected += 1
            await asyncio.sleep(interval)
            continue
        if t_mid == last_t_mid:
            skipped_dup += 1
            await asyncio.sleep(1)
            continue
        last_t_mid = t_mid
        result = zone_calibration_service.inject_window(feat, zone)
        if result.get("accepted"):
            accepted += 1
        else:
            rejected += 1
        await asyncio.sleep(interval)

    return {
        "ok": True,
        "zone": zone,
        "accepted": accepted,
        "rejected": rejected,
        "skipped_duplicates": skipped_dup,
        "total_windows": accepted,
    }


@router.post("/zone/calibrate/reset")
async def zone_calibrate_reset():
    """Reset all zone calibration state."""
    zone_calibration_service.reset()
    return {"ok": True, "status": "reset"}


# ── Marker recording endpoint (raw features + predictions per ceiling marker) ──

@router.post("/marker/record")
async def marker_record(req: dict):
    """Record raw CSI features + model predictions while user stands under a marker.

    Body: {"marker_id": "1"|"2"|...|"11", "duration_sec": 60, "label": "optional"}

    Pre-flight checks:
      - 7 nodes active, PPS >= 10, fresh window (< 10s)
      - _last_feat_dict non-empty with valid t_mid

    Saves JSONL to output/marker_recordings/marker_{id}_{ts}.jsonl
    Each line: full raw feature dict + predictions + marker ground truth
    """
    import asyncio, time, json, os

    marker_id = str(req.get("marker_id", ""))
    duration = int(req.get("duration_sec", 60))
    custom_label = req.get("label", "")

    if not marker_id:
        raise HTTPException(status_code=400, detail="marker_id required (1-11)")

    # Load marker positions from authoritative layout
    layout_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
        "output", "coord_zone_pipeline1", "garage_layout_authoritative_v2.json"
    )
    marker_info = None
    try:
        with open(layout_path) as f:
            layout = json.load(f)
        marker_info = layout.get("ceiling_markers", {}).get(marker_id)
    except Exception:
        pass

    if marker_info is None:
        raise HTTPException(status_code=400, detail=f"Unknown marker_id={marker_id}. Valid: 1-11")

    gt_x = marker_info["x"]
    gt_y = marker_info["y"]
    marker_label = marker_info.get("label", f"Marker {marker_id}")

    # ── PRE-FLIGHT CHECKS ──
    status = csi_prediction_service.current
    errors = []

    nodes_active = status.get("nodes_active", 0)
    if nodes_active < 7:
        errors.append(f"nodes_active={nodes_active}, need 7")

    pps = status.get("pps", 0)
    if pps < 10:
        errors.append(f"pps={pps}, need >= 10")

    window_age = status.get("window_age_sec", 999)
    if window_age > 10:
        errors.append(f"window_age={window_age}s, need < 10s")

    feat = csi_prediction_service._last_feat_dict
    if not feat or feat.get("t_mid") is None:
        errors.append("no feature data yet (_last_feat_dict empty)")

    if errors:
        return {"ok": False, "preflight_failed": True, "errors": errors}

    # ── SETUP OUTPUT ──
    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
        "output", "marker_recordings"
    )
    os.makedirs(out_dir, exist_ok=True)
    ts_start = int(time.time())
    filename = f"marker_{marker_id}_{ts_start}.jsonl"
    filepath = os.path.join(out_dir, filename)

    # ── RECORD ──
    collected = 0
    skipped_dup = 0
    last_t_mid = None
    t_end = time.time() + duration
    records = []

    while time.time() < t_end:
        feat = dict(csi_prediction_service._last_feat_dict)
        t_mid = feat.get("t_mid")

        if not feat or t_mid is None:
            await asyncio.sleep(1)
            continue

        if t_mid == last_t_mid:
            skipped_dup += 1
            await asyncio.sleep(0.5)
            continue

        last_t_mid = t_mid

        # Get current predictions
        cur = dict(csi_prediction_service.current)

        record = {
            "ts": time.time(),
            "marker_id": marker_id,
            "marker_label": marker_label,
            "gt_x": gt_x,
            "gt_y": gt_y,
            "custom_label": custom_label,
            # Raw CSI features (full dict)
            "features": feat,
            # Model predictions
            "binary": cur.get("binary"),
            "binary_confidence": cur.get("binary_confidence"),
            "coarse": cur.get("coarse"),
            "zone": cur.get("target_zone"),
            "pred_x": cur.get("target_x"),
            "pred_y": cur.get("target_y"),
            "coord_source": cur.get("coord_source", ""),
            "model_version": cur.get("model_version"),
            "nodes_active": cur.get("nodes_active"),
            "pps": cur.get("pps"),
            "window_age_sec": cur.get("window_age_sec"),
        }
        records.append(record)
        collected += 1
        await asyncio.sleep(2)

    # ── SAVE ──
    with open(filepath, "w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")

    # ── POST-FLIGHT VALIDATION ──
    validation = {
        "total_windows": collected,
        "unique_t_mids": len(set(r["features"].get("t_mid") for r in records)),
        "skipped_duplicates": skipped_dup,
        "duration_actual_sec": round(time.time() - ts_start, 1),
        "binary_occupied_pct": round(
            sum(1 for r in records if r["binary"] == "occupied") / max(collected, 1) * 100, 1
        ),
        "feature_keys_count": len(records[0]["features"]) if records else 0,
        "has_rssi": any("rssi" in k for k in (records[0]["features"].keys() if records else [])),
        "has_amplitude": any("amp" in k for k in (records[0]["features"].keys() if records else [])),
        "file": filepath,
        "file_size_kb": round(os.path.getsize(filepath) / 1024, 1) if os.path.exists(filepath) else 0,
    }

    ok = collected >= 5 and validation["unique_t_mids"] >= 5
    return {
        "ok": ok,
        "marker_id": marker_id,
        "marker_label": marker_label,
        "gt_x": gt_x,
        "gt_y": gt_y,
        "collected": collected,
        "validation": validation,
        "filepath": filepath,
    }


@router.post("/features/record")
async def features_record(req: dict):
    """Record raw CSI features for a given duration. No occupancy check.

    Body: {"duration_sec": 300, "label": "empty_baseline"}
    """
    import asyncio, time, json, os

    duration = int(req.get("duration_sec", 60))
    label = req.get("label", "unlabeled")

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
        "output", "marker_recordings"
    )
    os.makedirs(out_dir, exist_ok=True)
    ts_start = int(time.time())
    filepath = os.path.join(out_dir, f"{label}_{ts_start}.jsonl")

    collected = 0
    skipped_dup = 0
    last_t_mid = None
    t_end = time.time() + duration
    records = []

    while time.time() < t_end:
        feat = dict(csi_prediction_service._last_feat_dict)
        t_mid = feat.get("t_mid")
        if not feat or t_mid is None:
            await asyncio.sleep(1)
            continue
        if t_mid == last_t_mid:
            skipped_dup += 1
            await asyncio.sleep(0.5)
            continue
        last_t_mid = t_mid
        cur = dict(csi_prediction_service.current)
        record = {
            "ts": time.time(),
            "label": label,
            "features": feat,
            "binary": cur.get("binary"),
            "binary_confidence": cur.get("binary_confidence"),
            "nodes_active": cur.get("nodes_active"),
            "pps": cur.get("pps"),
        }
        records.append(record)
        collected += 1
        await asyncio.sleep(2)

    with open(filepath, "w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")

    return {
        "ok": collected >= 1,
        "label": label,
        "collected": collected,
        "skipped_duplicates": skipped_dup,
        "duration_sec": round(time.time() - ts_start, 1),
        "filepath": filepath,
        "file_size_kb": round(os.path.getsize(filepath) / 1024, 1) if os.path.exists(filepath) else 0,
    }


# ── Few-shot calibration storage endpoints (shadow-only packet persistence) ──


@router.get("/fewshot/status")
async def fewshot_calibration_status():
    """Get shadow-only few-shot calibration storage status."""
    return fewshot_calibration_storage_service.get_status()


@router.post("/fewshot/session/start")
async def fewshot_session_start(req: FewshotSessionStartRequest):
    """Start a shadow-only few-shot calibration packet session."""
    try:
        result = fewshot_calibration_storage_service.start_session(
            protocol_id=req.protocol_id,
            protocol_name=req.protocol_name,
            zone_scheme=req.zone_scheme,
            total_windows=req.total_windows,
            window_duration_sec=req.window_duration_sec,
            metadata=req.metadata,
            steps=[step.model_dump() for step in req.steps],
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return result


@router.post("/fewshot/session/step/start")
async def fewshot_session_step_start(req: FewshotStepLifecycleRequest):
    """Mark a few-shot calibration step as running."""
    try:
        result = fewshot_calibration_storage_service.start_step(
            step_id=req.step_id,
            started_at=req.started_at,
            metadata=req.metadata,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return result


@router.post("/fewshot/session/step/complete")
async def fewshot_session_step_complete(req: FewshotStepLifecycleRequest):
    """Mark a few-shot calibration step as completed."""
    try:
        result = fewshot_calibration_storage_service.complete_step(
            step_id=req.step_id,
            completed_at=req.completed_at,
            metadata=req.metadata,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return result


@router.post("/fewshot/session/finalize")
async def fewshot_session_finalize(req: FewshotSessionFinalizeRequest):
    """Finalize and persist the current few-shot calibration packet."""
    try:
        result = fewshot_calibration_storage_service.finalize_session(
            fit_result=req.fit_result,
            completed_at=req.completed_at,
            metadata=req.metadata,
            status=req.status,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return result


@router.post("/fewshot/session/reset")
async def fewshot_session_reset():
    """Cancel the current few-shot calibration packet session."""
    return fewshot_calibration_storage_service.reset(reason="api_reset")


@router.get("/fewshot/consumer/status")
async def fewshot_consumer_status():
    """Get shadow-only few-shot packet consumer status."""
    return fewshot_adaptation_consumer_service.get_status()


@router.get("/fewshot/consumer/packets")
async def fewshot_consumer_packets():
    """List finalized few-shot packets available for activation."""
    return {"packets": fewshot_adaptation_consumer_service.list_available_packets()}


@router.post("/fewshot/consumer/activate")
async def fewshot_consumer_activate(req: FewshotConsumerActivateRequest):
    """Activate a saved few-shot packet as the shadow adaptation consumer."""
    try:
        return fewshot_adaptation_consumer_service.activate(
            session_id=req.session_id,
            storage_path=req.storage_path,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/fewshot/consumer/deactivate")
async def fewshot_consumer_deactivate(req: FewshotConsumerDeactivateRequest):
    """Deactivate the shadow-only few-shot packet consumer."""
    return fewshot_adaptation_consumer_service.deactivate(reason=req.reason)


# ── V43 shadow hot-reload endpoints ─────────────────────────────────

@router.post("/shadow/enable")
async def shadow_v43_enable():
    """Enable V43 shadow at runtime without restarting the server."""
    result = csi_prediction_service.enable_v43_shadow()
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("detail", "unknown error"))
    return result


@router.post("/shadow/disable")
async def shadow_v43_disable():
    """Disable V43 shadow at runtime."""
    return csi_prediction_service.disable_v43_shadow()


@router.get("/shadow/status")
async def shadow_v43_status():
    """Get current V43 shadow state, agreement rate, and window count."""
    return csi_prediction_service.get_v43_shadow_status()


# ── Epoch4 position prediction endpoint ──────────────────────────────

_epoch4_model = None
_epoch4_meta = None
# v4.1 model (TEXT format, 56 features)
_V41_MODEL_PATH = PROJECT_ROOT / "output" / "epoch4_v41_model" / "v41_position_classifier.pkl"
_V41_META_PATH = PROJECT_ROOT / "output" / "epoch4_v41_model" / "v41_position_classifier_meta.json"
# Legacy model (binary format, kept as fallback)
_EPOCH4_MODEL_PATH = PROJECT_ROOT / "output" / "epoch4_position_model" / "epoch4_position_classifier.pkl"
_EPOCH4_META_PATH = PROJECT_ROOT / "output" / "epoch4_position_model" / "epoch4_position_classifier_meta.json"
_EPOCH4_NODE_IPS = [
    "192.168.0.137", "192.168.0.117", "192.168.0.143", "192.168.0.125",
    "192.168.0.110", "192.168.0.132", "192.168.0.153",
]
_EPOCH4_NSUB = 64
_EPOCH4_WIN = 7
_EPOCH4_LABELS = {}
_epoch4_model_version = None  # "v41" or "legacy"


def _load_epoch4_model():
    global _epoch4_model, _epoch4_meta, _EPOCH4_LABELS, _epoch4_model_version
    if _epoch4_model is not None:
        return _epoch4_model, _epoch4_meta

    # Try v4.1 model first
    if _V41_MODEL_PATH.exists():
        import pickle
        with open(_V41_MODEL_PATH, "rb") as f:
            bundle = pickle.load(f)
        _epoch4_model = bundle["model"]
        le = bundle["label_encoder"]
        _EPOCH4_LABELS = {i: str(c) for i, c in enumerate(le.classes_)}
        if _V41_META_PATH.exists():
            _epoch4_meta = json.loads(_V41_META_PATH.read_text())
        _epoch4_model_version = "v41"
        logger.info("Loaded v4.1 position model (%d classes)", len(_EPOCH4_LABELS))
        return _epoch4_model, _epoch4_meta

    # Fallback to legacy model
    if _EPOCH4_MODEL_PATH.exists():
        import joblib
        _epoch4_model = joblib.load(_EPOCH4_MODEL_PATH)
        if _EPOCH4_META_PATH.exists():
            _epoch4_meta = json.loads(_EPOCH4_META_PATH.read_text())
            if "classes" in _epoch4_meta:
                _EPOCH4_LABELS = {int(k): v for k, v in _epoch4_meta["classes"].items()}
        _epoch4_model_version = "legacy"
        logger.info("Loaded legacy position model")
        return _epoch4_model, _epoch4_meta

    return None, None


@router.post("/position/reload")
async def reload_position_model():
    """Force reload of position model (after retraining)."""
    global _epoch4_model, _epoch4_meta, _epoch4_model_version
    _epoch4_model = None
    _epoch4_meta = None
    _epoch4_model_version = None
    model, meta = _load_epoch4_model()
    if model is None:
        return {"status": "error", "message": "model file not found"}
    return {"status": "ok", "version": _epoch4_model_version, "classes": _EPOCH4_LABELS, "n_classes": len(_EPOCH4_LABELS)}


def _extract_v41_features(packets: dict, node_ips: list[str], win: int) -> tuple[list[float], list[str]]:
    """Extract 56-dim feature vector matching v4.1 training format.

    8 features per node: mean_rssi, std_rssi, mean_amp, std_amp, max_amp, low_amp, mid_amp, high_amp
    """
    import numpy as np
    fv: list[float] = []
    ready_nodes: list[str] = []

    for ip in node_ips:
        if ip not in packets or len(packets[ip]) < win:
            fv.extend([0.0] * 8)
            continue

        recent = packets[ip][-win:]
        ready_nodes.append(ip)
        rssis = np.array([float(r[1]) for r in recent], dtype=np.float64)
        amp_list = [np.asarray(r[2], dtype=np.float64) for r in recent]

        # Pad amplitudes to same length
        max_sc = max(len(a) for a in amp_list) if amp_list else 0
        if max_sc == 0:
            fv.extend([0.0] * 8)
            continue

        padded = np.zeros((len(amp_list), max_sc))
        for i, a in enumerate(amp_list):
            padded[i, :len(a)] = a

        mean_rssi = float(np.mean(rssis))
        std_rssi = float(np.std(rssis))
        mean_amp = float(np.mean(padded))
        std_amp = float(np.std(padded))
        max_amp = float(np.max(padded))
        third = max_sc // 3
        low_amp = float(np.mean(padded[:, :third])) if third > 0 else 0.0
        mid_amp = float(np.mean(padded[:, third:2*third])) if third > 0 else 0.0
        high_amp = float(np.mean(padded[:, 2*third:])) if third > 0 else 0.0

        fv.extend([mean_rssi, std_rssi, mean_amp, std_amp, max_amp, low_amp, mid_amp, high_amp])

    return fv, ready_nodes


def _extract_legacy_features(packets: dict, node_ips: list[str], win: int, nsub: int) -> tuple[list[float], list[str]]:
    """Extract legacy 258-dim feature vector for binary-format model."""
    import numpy as np
    fv: list[float] = []
    ready_nodes: list[str] = []

    for ip in node_ips:
        if ip not in packets or len(packets[ip]) < win:
            fv.extend([0.0] * (nsub * 4 + 2))
            continue

        recent = packets[ip][-win:]
        ready_nodes.append(ip)
        amps_raw = [r[2] for r in recent]
        phs_raw = [r[3] for r in recent]
        rssis = np.array([r[1] for r in recent], dtype=np.float32)

        amps = np.zeros((win, nsub), np.float32)
        phs = np.zeros((win, nsub), np.float32)
        for i in range(len(recent)):
            a_raw = np.asarray(amps_raw[i], dtype=np.float32)
            p_raw = np.asarray(phs_raw[i], dtype=np.float32)
            n = len(a_raw)
            if n == nsub:
                amps[i] = a_raw
                phs[i] = p_raw
            elif n > nsub:
                k = n // nsub
                usable = nsub * k
                amps[i] = a_raw[:usable].reshape(nsub, k).mean(axis=1)
                phs[i] = p_raw[:usable:k][:nsub]
            elif n > 0:
                amps[i, :n] = a_raw
                phs[i, :n] = p_raw

        fv.extend(amps.mean(0).tolist())
        fv.extend(amps.std(0).tolist())
        fv.extend(phs.mean(0).tolist())
        fv.extend(phs.std(0).tolist())
        fv.append(float(rssis.mean()) / 100.0)
        fv.append(float(rssis.mean() + 96) / 100.0)

    return fv, ready_nodes


@router.get("/position")
async def get_position_prediction():
    """Real-time position prediction using the best available model.

    v4.1 model: 56-dim features (mean_rssi, std_rssi, mean/std/max_amp, low/mid/high_amp per node)
    Legacy model: 258-dim features (amp/phase mean/std + rssi per node)
    """
    import numpy as np

    model, meta = _load_epoch4_model()
    if model is None:
        raise HTTPException(status_code=503, detail="position model not found")

    svc = csi_prediction_service
    packets = svc._packets

    if _epoch4_model_version == "v41":
        fv, ready_nodes = _extract_v41_features(packets, _EPOCH4_NODE_IPS, _EPOCH4_WIN)
    else:
        fv, ready_nodes = _extract_legacy_features(packets, _EPOCH4_NODE_IPS, _EPOCH4_WIN, _EPOCH4_NSUB)

    X = np.array(fv, np.float32).reshape(1, -1)
    raw_pred = model.predict(X)[0]
    proba = model.predict_proba(X)[0]

    # Handle both numeric (LabelEncoder) and string (direct) predictions
    if isinstance(raw_pred, (int, np.integer)):
        pred = int(raw_pred)
        label = _EPOCH4_LABELS.get(pred, f"class_{pred}")
        confidence = float(proba[pred])
    else:
        label = str(raw_pred)
        # Find index of predicted class in proba array
        pred_idx = list(model.classes_).index(raw_pred) if hasattr(model, 'classes_') else 0
        confidence = float(proba[pred_idx])

    top3_idx = np.argsort(proba)[::-1][:3]
    top3 = []
    for i in top3_idx:
        if _EPOCH4_LABELS:
            lbl = _EPOCH4_LABELS.get(int(i), str(model.classes_[i]) if hasattr(model, 'classes_') else f"class_{i}")
        else:
            lbl = str(model.classes_[i]) if hasattr(model, 'classes_') else f"class_{i}"
        top3.append({"label": lbl, "probability": round(float(proba[i]), 4)})

    node_info = {}
    for ip in _EPOCH4_NODE_IPS:
        if ip in packets and packets[ip]:
            last_pkt = packets[ip][-1]
            node_info[ip] = {
                "n_packets": len(packets[ip]),
                "amp_shape": len(last_pkt[2]),
                "rssi": float(last_pkt[1]),
            }
        else:
            node_info[ip] = {"n_packets": 0}

    return {
        "position": label,
        "confidence": round(confidence, 4),
        "top3": top3,
        "model_version": _epoch4_model_version,
        "nodes_ready": len(ready_nodes),
        "nodes_total": len(_EPOCH4_NODE_IPS),
        "window_size": _EPOCH4_WIN,
        "feature_dim": len(fv),
        "nodes": node_info,
    }


_EPOCH4_SNAPSHOTS_DIR = PROJECT_ROOT / "output" / "epoch4_live_snapshots"


class PositionSnapshotRequest(BaseModel):
    label: str = Field(..., description="Position label (e.g. center, door, empty, marker1)")
    window_size: int = Field(default=20, description="Packets per node to capture")


@router.post("/position/snapshot")
async def capture_position_snapshot(req: PositionSnapshotRequest):
    """Capture a labeled snapshot of current CSI buffer for model retraining.

    Call this while standing at a known position to collect training data
    that matches the exact runtime feature format (sanitized phase, etc).
    """
    import numpy as np

    svc = csi_prediction_service
    packets = svc._packets
    win = req.window_size

    snapshot_data = {}
    nodes_captured = 0
    for ip in _EPOCH4_NODE_IPS:
        if ip not in packets or len(packets[ip]) < win:
            snapshot_data[ip] = None
            continue
        recent = packets[ip][-win:]
        snapshot_data[ip] = {
            "rssi": [float(r[1]) for r in recent],
            "amp": [r[2].tolist() for r in recent],
            "phase": [r[3].tolist() for r in recent],
            "t_sec": [float(r[0]) for r in recent],
        }
        nodes_captured += 1

    _EPOCH4_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"snap_{req.label}_{ts}.json"
    fpath = _EPOCH4_SNAPSHOTS_DIR / fname

    record = {
        "label": req.label,
        "timestamp": ts,
        "window_size": win,
        "node_ips": _EPOCH4_NODE_IPS,
        "nodes_captured": nodes_captured,
        "data": snapshot_data,
    }
    fpath.write_text(json.dumps(record), encoding="utf-8")

    return {
        "status": "ok",
        "file": str(fpath),
        "label": req.label,
        "nodes_captured": nodes_captured,
        "nodes_total": len(_EPOCH4_NODE_IPS),
    }
