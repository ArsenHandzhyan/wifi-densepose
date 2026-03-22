from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "v1" / "src" / "services" / "csi_recording_service.py"
MODULE_SPEC = importlib.util.spec_from_file_location("recording_contract_smoke_service", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"Unable to load recording service module from {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(MODULE)
CsiRecordingService = MODULE.CsiRecordingService


class RecordingContractSmokeTest(unittest.TestCase):
    def make_service(self) -> CsiRecordingService:
        return CsiRecordingService()

    def test_recording_summary_contract_exposes_teacher_truth_fields(self) -> None:
        service = self.make_service()
        service.session_label = "summary_contract_smoke"
        service.with_video = True
        service.video_required = True
        service.teacher_source_kind = "mac_camera"
        service.teacher_source_name = "Mac Camera"
        service.teacher_device_name = "Камера MacBook Pro"
        service._session_started_at_iso = "2026-03-20T23:30:00"
        service._teacher_truth_started_at = 10.0
        service._teacher_truth_ended_at = 14.0
        service._teacher_last_growth_at = 14.0
        service._stop_reason = "operator_stop"

        summary = service._build_session_summary(
            4.0,
            {
                "video_path": "/tmp/mac_camera.teacher.mp4",
                "video_exists": True,
                "video_bytes": 8192,
                "video_duration_sec": 4.0,
                "exit_code": 0,
            },
        )

        truth_summary = summary["truth_summary"]
        self.assertEqual(truth_summary["teacher_source_kind"], "mac_camera")
        self.assertEqual(truth_summary["truth_coverage_duration_sec"], 4.0)
        self.assertEqual(truth_summary["coverage_status"], "full")
        self.assertEqual(summary["labeling_verdict"]["code"], "video_backed_session_ready")
        self.assertTrue(summary["labeling_verdict"]["suitable_for_labeling"])

    def test_mac_camera_finalize_requests_stop_and_records_cleanup(self) -> None:
        service = self.make_service()

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            video_path = temp_root / "mac_camera.teacher.mp4"
            result_path = temp_root / "mac_camera.teacher.result.json"
            pid_path = temp_root / "mac_camera.teacher.pid"
            stop_path = temp_root / "mac_camera.teacher.stop"

            video_path.write_bytes(b"0" * 8192)
            result_path.write_text(
                json.dumps(
                    {
                        "status": "completed",
                        "exit_code": 0,
                        "actual_duration_sec": 3.25,
                    }
                ),
                encoding="utf-8",
            )
            pid_path.write_text("4242\n", encoding="utf-8")

            service._teacher_handle = {
                "kind": "mac_camera",
                "backend": "terminal_ffmpeg_avfoundation",
                "video_path": str(video_path),
                "result_path": str(result_path),
                "pid_path": str(pid_path),
                "stop_path": str(stop_path),
                "command_path": str(temp_root / "mac_camera.teacher.command"),
                "ready_path": str(temp_root / "mac_camera.teacher.ready.json"),
                "log_path": str(temp_root / "mac_camera.teacher.log"),
            }
            service._teacher_last_growth_at = 123.0

            wait_calls: list[tuple[int, float]] = []
            signal_calls: list[tuple[int, int]] = []

            service._read_pid_file = lambda path: 4242
            service._process_exists = lambda pid: True
            service._wait_for_process_exit = lambda pid, timeout_sec: wait_calls.append((pid, timeout_sec)) or True
            service._signal_process = lambda pid, sig: signal_calls.append((pid, sig))
            service._wait_for_file_stable = lambda path, timeout_sec, stable_window_sec: (True, path.stat().st_size)
            service._probe_media_duration = lambda path: 3.25

            teacher_finalize = service._finalize_teacher_recorder_sync(failed_start=False)

            self.assertTrue(stop_path.exists())
            self.assertEqual(stop_path.read_text(encoding="utf-8"), "stop\n")
            self.assertEqual(wait_calls, [(4242, 6.0)])
            self.assertEqual(signal_calls, [])
            self.assertEqual(teacher_finalize["source_kind"], "mac_camera")
            self.assertEqual(teacher_finalize["result_payload"]["status"], "completed")
            self.assertEqual(teacher_finalize["video_duration_sec"], 3.25)
            self.assertTrue(teacher_finalize["stop_cleanup"]["stop_requested"])
            self.assertTrue(teacher_finalize["stop_cleanup"]["process_exited"])
            self.assertTrue(teacher_finalize["stop_cleanup"]["video_stable"])
            self.assertIsNone(teacher_finalize["stop_cleanup"]["signal_sent"])
            self.assertIsNone(teacher_finalize["stop_cleanup"]["force_signal"])


if __name__ == "__main__":
    unittest.main()
