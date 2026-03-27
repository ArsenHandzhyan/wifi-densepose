import pytest

from src.services.csi_recording_service import CsiRecordingService


def make_service() -> CsiRecordingService:
    return CsiRecordingService()


def test_resolve_teacher_source_defaults_to_legacy_rtsp_teacher():
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

    assert cfg["kind"] == "rtsp_teacher"
    assert cfg["video_requested"] is True
    assert cfg["video_required"] is True
    assert cfg["source_url"] == "rtsp://admin:admin@192.168.1.148:8554/live"
    assert cfg["source_url_redacted"] == "rtsp://192.168.1.148:8554/live"


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
    assert summary["truth_summary"]["truth_coverage_duration_sec"] == 5.0
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
