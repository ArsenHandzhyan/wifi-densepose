"""CSI Real-Time Prediction & Recording API Router."""

import logging
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional, List

from ...services.csi_prediction_service import csi_prediction_service
from ...services.csi_recording_service import csi_recording_service
from ...services.recording_truth_hardening import build_truth_hardening_report
from ...services.tts_service import get_tts_service
from ...services.zone_calibration_service import zone_calibration_service
from ...services.csi_node_inventory import list_csi_nodes
from ...services.fewshot_calibration_storage_service import fewshot_calibration_storage_service
from ...services.fewshot_adaptation_consumer_service import fewshot_adaptation_consumer_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CSI Prediction"])
PROJECT_ROOT = Path(__file__).resolve().parents[4]
TTS_HELPER = PROJECT_ROOT / "scripts" / "tts_helper.py"
GARAGE_ZONE_REVIEW_PACKET_SCRIPT = PROJECT_ROOT / "scripts" / "init_garage_zone_review_packet.py"
_tts_helper_lock = threading.Lock()
_tts_helper_proc: subprocess.Popen | None = None


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


@router.get("/status")
async def csi_status():
    """Current CSI prediction status with history."""
    return csi_prediction_service.get_status()


@router.get("/models")
async def csi_models():
    """List runtime-ready CSI models supported by the current loader."""
    models = csi_prediction_service.list_runtime_ready_models()
    default_item = next((item for item in models if item.get("is_default")), None)
    active_item = next((item for item in models if item.get("is_active")), None)
    return {
        "models": models,
        "active_model_id": csi_prediction_service.current.get("model_id") or (active_item.get("model_id") if active_item else None),
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


@router.post("/start")
async def csi_start():
    """Start CSI prediction (load model + start UDP listener)."""
    if csi_prediction_service._running:
        return {"status": "already_running"}

    if not csi_prediction_service.binary_model:
        ok = csi_prediction_service.load_model()
        if not ok:
            raise HTTPException(status_code=500, detail="Model not found. Train with scripts/train_v21_save_model.py")

    try:
        import asyncio
        await csi_prediction_service.start_udp_listener()
        asyncio.create_task(csi_prediction_service.prediction_loop(interval=2.0))
        return {"status": "started", "model_version": csi_prediction_service.current.get("model_version")}
    except OSError as e:
        if "Address already in use" in str(e):
            raise HTTPException(status_code=409, detail="UDP port 5005 is already in use. Stop other CSI capture processes first.")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def csi_stop():
    """Stop CSI prediction."""
    await csi_prediction_service.stop()
    return {"status": "stopped"}


@router.get("/nodes")
async def csi_nodes():
    """Check ESP32 node health."""
    import aiohttp
    nodes = []

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
        for node in list_csi_nodes():
            name = str(node["node_id"])
            ip = str(node["ip"])
            try:
                async with session.get(f"http://{ip}:8080/api/v1/status") as resp:
                    data = await resp.json()
                    nodes.append({
                        "name": name,
                        "ip": ip,
                        "status": "up",
                        "role": node.get("role", "unknown"),
                        "required": bool(node.get("required")),
                        "position_known": bool(node.get("position_known")),
                        "uptime": data.get("uptime_sec", 0),
                        "errors": data.get("send_errors", 0),
                    })
            except Exception:
                nodes.append({
                    "name": name,
                    "ip": ip,
                    "status": "down",
                    "role": node.get("role", "unknown"),
                    "required": bool(node.get("required")),
                    "position_known": bool(node.get("position_known")),
                })

    return {"nodes": nodes}


# ── Recording endpoints ────────────────────────────────────────

@router.post("/record/start")
async def record_start(req: RecordingStartRequest):
    """Start recording CSI data (parallel with live prediction)."""
    # Ensure prediction is running (UDP listener active)
    if not csi_prediction_service._running:
        if not csi_prediction_service.binary_model:
            csi_prediction_service.load_model()
        import asyncio
        try:
            await csi_prediction_service.start_udp_listener()
            asyncio.create_task(csi_prediction_service.prediction_loop(interval=2.0))
        except OSError as e:
            if "Address already in use" not in str(e):
                raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@router.post("/record/stop")
async def record_stop():
    """Stop recording and flush all data."""
    result = await csi_recording_service.stop_recording()
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Not recording"))
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
            _spawn_tts_helper(["speak", req.text])
            payload = {"ok": True, "backend": "elevenlabs"}
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
    tts.stop()
    return {"ok": True, "stopped_helper": stopped_helper}


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
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@router.post("/zone/calibrate/stop")
async def zone_calibrate_stop():
    """Stop the current zone capture phase."""
    result = zone_calibration_service.stop_zone_capture()
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@router.post("/zone/calibrate/fit")
async def zone_calibrate_fit():
    """Fit NearestCentroid classifier on collected calibration windows.

    Requires at least 2 zones with >= 2 windows each.
    Shadow-only: does NOT affect V5 production output.
    """
    result = zone_calibration_service.fit()
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@router.post("/zone/calibrate/reset")
async def zone_calibrate_reset():
    """Reset all zone calibration state."""
    zone_calibration_service.reset()
    return {"ok": True, "status": "reset"}


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
