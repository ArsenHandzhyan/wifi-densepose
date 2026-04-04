import pytest
import sys
import json

from src.services import csi_recording_service as csi_recording_module
from src.services.csi_recording_service import CsiRecordingService


def make_service() -> CsiRecordingService:
    return CsiRecordingService()


def test_resolve_teacher_source_defaults_to_platform_teacher():
    service = make_service()

    cfg = service._resolve_teacher_source(
        with_video=True,
        video_required=None,
        teacher_source_kind=None,
        teacher_source_url=None,
        teacher_source_name=None,
        teacher_device=None,
        teacher_device_name=None,
        teacher_input_pixel_format=None,
        teacher_start_timeout_sec=None,
    )

    expected_kind = "mac_camera" if sys.platform == "darwin" else "rtsp_teacher"
    assert cfg["kind"] == expected_kind
    assert cfg["video_requested"] is True
    assert cfg["video_required"] is True
    if expected_kind == "rtsp_teacher":
        assert cfg["source_url"] == "rtsp://admin:admin@192.168.1.148:8554/live"
        assert cfg["source_url_redacted"] == "rtsp://192.168.1.148:8554/live"
    else:
        assert cfg["source_name"] == "Mac Camera"
        assert cfg["device_name"]


def test_resolve_teacher_source_rejects_required_video_without_source():
    service = make_service()

    with pytest.raises(ValueError, match="video_required=true"):
        service._resolve_teacher_source(
            with_video=False,
            video_required=True,
            teacher_source_kind="none",
            teacher_source_url=None,
            teacher_source_name=None,
            teacher_device=None,
            teacher_device_name=None,
            teacher_input_pixel_format=None,
            teacher_start_timeout_sec=None,
        )


def test_build_session_summary_marks_partial_video_as_unsuitable():
    service = make_service()
    service.session_label = "partial_video_case"
    service.with_video = True
    service.video_required = True
    service.teacher_source_kind = "phone_rtsp"
    service.teacher_source_name = "Phone RTSP"
    service._session_started_at_iso = "2026-03-20T21:00:00"
    service._teacher_truth_started_at = 100.0
    service._teacher_truth_ended_at = 105.0
    service._teacher_last_growth_at = 105.0
    service._teacher_failure_reason = "teacher truth stalled"
    service._teacher_degraded = True
    service._stop_reason = "teacher_source_lost:teacher truth stalled"

    summary = service._build_session_summary(
        10.0,
        {
            "video_path": "/tmp/partial.teacher.mp4",
            "video_exists": True,
            "video_bytes": 2048,
            "video_duration_sec": 5.2,
            "exit_code": 0,
        },
    )

    assert summary["session_status"] == "degraded"
    assert summary["truth_summary"]["coverage_status"] == "partial"
    assert summary["truth_summary"]["full_session_duration_sec"] == 10.0
    assert summary["truth_summary"]["real_video_duration_sec"] == 5.2
    assert summary["truth_summary"]["truth_coverage_duration_sec"] == 5.2
    assert summary["labeling_verdict"]["suitable_for_labeling"] is False
    assert summary["labeling_verdict"]["code"] == "partial_video_coverage"


def test_build_session_summary_marks_full_required_video_as_ready():
    service = make_service()
    service.session_label = "full_video_case"
    service.with_video = True
    service.video_required = True
    service.teacher_source_kind = "rtsp_teacher"
    service.teacher_source_name = "RTSP Teacher"
    service._session_started_at_iso = "2026-03-20T21:05:00"
    service._teacher_truth_started_at = 200.0
    service._teacher_truth_ended_at = 210.0
    service._teacher_last_growth_at = 210.0

    summary = service._build_session_summary(
        10.0,
        {
            "video_path": "/tmp/full.teacher.mp4",
            "video_exists": True,
            "video_bytes": 4096,
            "video_duration_sec": 10.0,
            "exit_code": 0,
        },
    )

    assert summary["session_status"] == "completed"
    assert summary["truth_summary"]["coverage_status"] == "full"
    assert summary["labeling_verdict"]["suitable_for_labeling"] is True
    assert summary["labeling_verdict"]["code"] == "video_backed_session_ready"


def test_get_status_exposes_last_summary_aliases_for_ui_refresh():
    service = make_service()
    service.session_label = "saved_case"
    service._last_stop_result = {
        "label": "saved_case",
        "stop_reason": "completed",
        "session_status": "completed",
    }
    service._session_summary = {
        "label": "saved_case",
        "truth_summary": {"teacher_video_exists": True},
        "labeling_verdict": {"suitable_for_labeling": True},
    }

    status = service.get_status()

    assert status["recording"] is False
    assert status["last_result"] == status["lastStopResult"]
    assert status["last_session_summary"] == status["lastSessionSummary"]
    assert status["lastStopResult"]["label"] == "saved_case"
    assert status["lastSessionSummary"]["label"] == "saved_case"


@pytest.mark.asyncio
async def test_start_recording_returns_structured_conflict_code_when_already_recording():
    service = make_service()
    service.recording = True

    result = await service.start_recording(label="already_running_case")

    assert result["ok"] is False
    assert result["error_code"] == "already_recording"
    assert result["error"] == "Already recording"


@pytest.mark.asyncio
async def test_start_recording_returns_structured_invalid_teacher_config_code():
    service = make_service()

    result = await service.start_recording(
        label="invalid_teacher_case",
        with_video=False,
        video_required=True,
        teacher_source_kind="none",
    )

    assert result["ok"] is False
    assert result["error_code"] == "invalid_teacher_config"
    assert "video_required=true" in result["error"]


@pytest.mark.asyncio
async def test_stop_recording_is_idempotent_without_active_session():
    service = make_service()

    result = await service.stop_recording()

    assert result["ok"] is True
    assert result["status"] == "already_stopped"
    assert result["already_stopped"] is True
    assert result["message"] == "Recording service is already inactive"


def test_get_status_recovers_last_session_summary_from_disk(monkeypatch, tmp_path):
    summary_path = tmp_path / "recovered_case.recording_summary.json"
    payload = {
        "label": "recovered_case",
        "session_status": "completed",
        "stop_reason": "backend_shutdown",
        "duration_sec": 300.0,
        "total_chunks": 5,
        "total_packets": 1612,
        "node_packets": {"192.168.1.137": 400},
        "truth_summary": {"with_video": False},
        "labeling_verdict": {"suitable_for_labeling": True},
    }
    summary_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(csi_recording_module, "CAPTURE_DIR", tmp_path)

    service = make_service()
    status = service.get_status()

    assert status["recording"] is False
    assert status["status"] == "completed"
    assert status["status_scope"] == "last_session"
    assert status["status_reason"] == "backend_shutdown"
    assert status["last_session_summary"]["label"] == "recovered_case"
    assert status["lastStopResult"]["session_summary_path"] == str(summary_path)
    assert status["lastStopResult"]["recovered_from_disk"] is True
