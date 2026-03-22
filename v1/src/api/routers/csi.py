"""CSI Real-Time Prediction & Recording API Router."""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from ...services.csi_prediction_service import csi_prediction_service
from ...services.csi_recording_service import csi_recording_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CSI Prediction"])


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
    person_count: int = 0
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
    ips = {
        "node01": "192.168.1.137",
        "node02": "192.168.1.117",
        "node03": "192.168.1.101",
        "node04": "192.168.1.125",
        "node06": "192.168.1.77",
    }

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
        for name, ip in ips.items():
            try:
                async with session.get(f"http://{ip}:8080/api/v1/status") as resp:
                    data = await resp.json()
                    nodes.append({"name": name, "ip": ip, "status": "up",
                                  "uptime": data.get("uptime_sec", 0),
                                  "errors": data.get("send_errors", 0)})
            except Exception:
                nodes.append({"name": name, "ip": ip, "status": "down"})

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
    return result


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
