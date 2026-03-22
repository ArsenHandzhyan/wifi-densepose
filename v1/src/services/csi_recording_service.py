"""
Unified CSI Recording Service
==============================
Records CSI data in parallel with live prediction.
Features:
- Pre-flight checks: all 4 ESP32 nodes + explicit teacher source probe
- Strict video-backed gate: CSI recording starts only after teacher truth is alive
- Voice prompts: Russian macOS 'say' for start/stop/failure and optional cues
- Parallel operation: feeds packets to prediction service simultaneously
- Truthful summary: session duration, real video duration, truth coverage, labeling verdict
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parents[3]
CAPTURE_DIR = PROJECT / "temp" / "captures"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

MAC_VIDEO_TEACHER_HOST_SCRIPT = PROJECT / "scripts" / "mac_video_teacher_host.py"
PIXEL_VIDEO_TEACHER_HOST_SCRIPT = PROJECT / "scripts" / "pixel_video_teacher_host.py"

# Core 4-node set (used for preflight — these must be present)
CORE_NODE_IPS = sorted(["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137"])
# All recordable nodes (core + shadow nodes like node05/node06)
NODE_IPS = sorted(CORE_NODE_IPS + ["192.168.1.33", "192.168.1.77"])
NODE_NAMES = {
    "192.168.1.137": "node01",
    "192.168.1.117": "node02",
    "192.168.1.101": "node03",
    "192.168.1.125": "node04",
    "192.168.1.33": "node05",
    "192.168.1.77": "node06",
}
RTSP_URL = "rtsp://admin:admin@192.168.1.148:8554/live"

KNOWN_TEACHER_SOURCE_KINDS = {"none", "rtsp_teacher", "mac_camera", "phone_rtsp", "pixel_rtsp", "mac_camera_terminal"}
DEFAULT_TEACHER_START_TIMEOUT_SEC = 12.0
DEFAULT_TEACHER_STALL_TIMEOUT_SEC = 8.0
DEFAULT_TERMINAL_CAMERA_DEVICE = os.getenv("CSI_MAC_CAMERA_DEVICE", "0")
DEFAULT_TERMINAL_CAMERA_PIXEL_FORMAT = "nv12"
MAX_VIDEO_RECORDING_SEC = 7200
MIN_VIDEO_READY_BYTES = 4096
HOST_SCRIPT_PYTHON = (
    os.getenv("CSI_HOST_SCRIPT_PYTHON")
    or ("/opt/homebrew/bin/python3" if Path("/opt/homebrew/bin/python3").exists() else None)
    or shutil.which("python3")
    or sys.executable
)


class CsiRecordingService:
    def __init__(self):
        self.recording = False
        self.session_label = ""
        self.chunk_sec = 60
        self.with_video = False
        self.video_required = False
        self.voice_prompt_enabled = True
        self.voice_cues: list[dict[str, Any]] = []
        self.person_count = 0
        self.motion_type = ""
        self.space_id = "garage"
        self.notes = ""

        self.teacher_source_kind = "none"
        self.teacher_source_name: str | None = None
        self.teacher_source_url: str | None = None
        self.teacher_source_url_redacted: str | None = None
        self.teacher_device: str | None = None
        self.teacher_device_name: str | None = None
        self.teacher_input_pixel_format = DEFAULT_TERMINAL_CAMERA_PIXEL_FORMAT
        self.teacher_start_timeout_sec = DEFAULT_TEACHER_START_TIMEOUT_SEC
        self.teacher_stall_timeout_sec = DEFAULT_TEACHER_STALL_TIMEOUT_SEC

        # Current chunk state
        self._chunk_num = 0
        self._chunk_start = 0.0
        self._chunk_packets: list[tuple[int, str, bytes]] = []
        self._session_start = 0.0
        self._session_started_at_iso: str | None = None
        self._total_packets = 0
        self._total_chunks = 0
        self._node_packet_counts = defaultdict(int)
        self._last_saved_chunk: dict[str, Any] | None = None

        # Teacher video runtime state
        self._video_proc: subprocess.Popen[str] | None = None
        self._video_path: Path | None = None
        self._teacher_handle: dict[str, Any] | None = None
        self._teacher_monitor_task: asyncio.Task | None = None
        self._voice_cue_task: asyncio.Task | None = None
        self._session_token = 0
        self._teacher_ready = False
        self._teacher_degraded = False
        self._teacher_stop_requested = False
        self._teacher_failure_reason: str | None = None
        self._teacher_auto_stopped = False
        self._teacher_truth_started_at: float | None = None
        self._teacher_truth_ended_at: float | None = None
        self._teacher_last_growth_at: float | None = None
        self._teacher_last_file_size = 0
        self._teacher_last_sample: dict[str, Any] | None = None

        # Pre-flight and summary state
        self._preflight: dict[str, Any] = {}
        self._session_summary: dict[str, Any] | None = None
        self._session_summary_path: Path | None = None
        self._last_stop_result: dict[str, Any] | None = None
        self._stop_reason: str | None = None

        # Voice prompt subprocess
        self._say_proc: subprocess.Popen[bytes] | None = None

    # ── Pre-flight checks ──────────────────────────────────────────

    async def preflight_check(
        self,
        check_video: bool = False,
        *,
        video_required: bool | None = None,
        teacher_source_kind: str | None = None,
        teacher_source_url: str | None = None,
        teacher_source_name: str | None = None,
        teacher_device: str | None = None,
        teacher_device_name: str | None = None,
        teacher_input_pixel_format: str | None = None,
        teacher_start_timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        """Check all devices before recording. Returns detailed status."""
        results: dict[str, Any] = {
            "ok": True,
            "nodes": {},
            "video": {"available": False, "checked": check_video},
            "teacher": None,
            "timestamp": datetime.now().isoformat(),
        }

        try:
            teacher_cfg = self._resolve_teacher_source(
                with_video=check_video,
                video_required=video_required,
                teacher_source_kind=teacher_source_kind,
                teacher_source_url=teacher_source_url,
                teacher_source_name=teacher_source_name,
                teacher_device=teacher_device,
                teacher_device_name=teacher_device_name,
                teacher_input_pixel_format=teacher_input_pixel_format,
                teacher_start_timeout_sec=teacher_start_timeout_sec,
            )
        except ValueError as exc:
            results["ok"] = False
            results["error"] = str(exc)
            results["teacher"] = {
                "requested": bool(check_video or video_required),
                "video_required": bool(video_required),
                "source_kind": teacher_source_kind or "none",
                "available": False,
                "error": str(exc),
            }
            self._preflight = results
            return results

        # Check core ESP32 nodes (preflight does not require shadow nodes)
        import aiohttp

        nodes_ok = 0
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
            for ip in CORE_NODE_IPS:
                name = NODE_NAMES.get(ip, ip)
                try:
                    async with session.get(f"http://{ip}:8080/api/v1/status") as resp:
                        data = await resp.json()
                        results["nodes"][name] = {
                            "ip": ip,
                            "ok": True,
                            "uptime": data.get("uptime_sec", 0),
                            "firmware": data.get("firmware_version", "?"),
                            "send_errors": data.get("send_errors", 0),
                        }
                        nodes_ok += 1
                except Exception as exc:
                    results["nodes"][name] = {
                        "ip": ip,
                        "ok": False,
                        "error": str(exc),
                    }

        if nodes_ok < 4:
            results["ok"] = False
            results["error"] = f"Only {nodes_ok}/4 nodes responding"

        teacher_report = await asyncio.to_thread(self._probe_teacher_source_sync, teacher_cfg)
        results["teacher"] = teacher_report
        results["video"] = {
            "available": bool(teacher_cfg["video_requested"] and teacher_report.get("available")),
            "checked": bool(teacher_cfg["video_requested"]),
            "required": bool(teacher_cfg["video_required"]),
            "source_kind": teacher_cfg["kind"],
            "error": teacher_report.get("error"),
        }

        if teacher_cfg["video_required"] and not teacher_report.get("available"):
            teacher_error = teacher_report.get("error") or "Teacher video unavailable"
            if results.get("error"):
                results["error"] = f"{results['error']} | {teacher_error}"
            else:
                results["error"] = teacher_error
            results["ok"] = False

        self._preflight = results
        return results

    # ── Voice prompts ──────────────────────────────────────────────

    def _say(self, text: str):
        """Speak text using macOS say (Russian voice)."""
        try:
            self._say_proc = subprocess.Popen(
                ["say", "-v", "Milena", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            logger.warning("Voice prompt failed: %s", exc)

    async def _voice_cue_loop(self, session_token: int):
        ordered_cues = sorted(
            [cue for cue in self.voice_cues if str(cue.get("text") or "").strip()],
            key=lambda cue: float(cue.get("at_sec") or 0.0),
        )
        for cue in ordered_cues:
            if not self.recording or self._session_token != session_token:
                return
            target_sec = max(0.0, float(cue.get("at_sec") or 0.0))
            while self.recording and self._session_token == session_token:
                remaining = target_sec - (time.time() - self._session_start)
                if remaining <= 0:
                    break
                await asyncio.sleep(min(0.25, remaining))
            if self.recording and self._session_token == session_token:
                self._say(str(cue.get("text")).strip())

    # ── Recording control ─────────────────────────────────────────

    async def start_recording(
        self,
        label: str,
        chunk_sec: int = 60,
        with_video: bool = False,
        person_count: int = 0,
        motion_type: str = "",
        notes: str = "",
        voice_prompt: bool = True,
        skip_preflight: bool = False,
        *,
        video_required: bool | None = None,
        teacher_source_kind: str | None = None,
        teacher_source_url: str | None = None,
        teacher_source_name: str | None = None,
        teacher_device: str | None = None,
        teacher_device_name: str | None = None,
        teacher_input_pixel_format: str | None = None,
        teacher_start_timeout_sec: float | None = None,
        voice_cues: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Start a new recording session."""
        if self.recording:
            return {"ok": False, "error": "Already recording"}

        try:
            teacher_cfg = self._resolve_teacher_source(
                with_video=with_video,
                video_required=video_required,
                teacher_source_kind=teacher_source_kind,
                teacher_source_url=teacher_source_url,
                teacher_source_name=teacher_source_name,
                teacher_device=teacher_device,
                teacher_device_name=teacher_device_name,
                teacher_input_pixel_format=teacher_input_pixel_format,
                teacher_start_timeout_sec=teacher_start_timeout_sec,
            )
        except ValueError as exc:
            if voice_prompt:
                self._say("Teacher video настроен неверно. Запись не начата.")
            return {"ok": False, "error": str(exc)}

        if not skip_preflight:
            pf = await self.preflight_check(
                check_video=teacher_cfg["video_requested"],
                video_required=teacher_cfg["video_required"],
                teacher_source_kind=teacher_cfg["kind"],
                teacher_source_url=teacher_cfg.get("source_url"),
                teacher_source_name=teacher_cfg.get("source_name"),
                teacher_device=teacher_cfg.get("device"),
                teacher_device_name=teacher_cfg.get("device_name"),
                teacher_input_pixel_format=teacher_cfg.get("input_pixel_format"),
                teacher_start_timeout_sec=teacher_cfg.get("start_timeout_sec"),
            )
            if not pf["ok"]:
                if voice_prompt and teacher_cfg["video_required"]:
                    self._say("Teacher video недоступно. Запись не начата.")
                return {"ok": False, "error": pf.get("error", "Pre-flight failed"), "preflight": pf}
        else:
            pf = {
                "ok": True,
                "timestamp": datetime.now().isoformat(),
                "teacher": self._probe_teacher_source_sync(teacher_cfg),
            }
            self._preflight = pf

        self._reset_runtime_state()
        self._session_token += 1
        self.session_label = label
        self.chunk_sec = chunk_sec
        self.with_video = teacher_cfg["video_requested"]
        self.video_required = teacher_cfg["video_required"]
        self.voice_prompt_enabled = bool(voice_prompt)
        self.voice_cues = list(voice_cues or [])
        self.person_count = person_count
        self.motion_type = motion_type
        self.notes = notes

        self.teacher_source_kind = teacher_cfg["kind"]
        self.teacher_source_name = teacher_cfg.get("source_name")
        self.teacher_source_url = teacher_cfg.get("source_url")
        self.teacher_source_url_redacted = teacher_cfg.get("source_url_redacted")
        self.teacher_device = teacher_cfg.get("device")
        self.teacher_device_name = teacher_cfg.get("device_name")
        self.teacher_input_pixel_format = teacher_cfg.get("input_pixel_format", DEFAULT_TERMINAL_CAMERA_PIXEL_FORMAT)
        self.teacher_start_timeout_sec = float(teacher_cfg.get("start_timeout_sec") or DEFAULT_TEACHER_START_TIMEOUT_SEC)

        if self.with_video:
            try:
                handle = await asyncio.to_thread(self._start_teacher_recorder_sync, teacher_cfg)
            except Exception as exc:
                if self.voice_prompt_enabled:
                    self._say("Teacher video не стартовал. Запись не начата.")
                return {"ok": False, "error": f"Teacher source start failed: {exc}", "preflight": self._preflight}

            self._teacher_handle = handle
            self._video_proc = handle.get("proc")
            video_path_value = handle.get("video_path")
            self._video_path = Path(str(video_path_value)).expanduser().resolve() if video_path_value else None

            ready, sample = await self._await_teacher_ready(self.teacher_start_timeout_sec)
            if not ready:
                await asyncio.to_thread(self._finalize_teacher_recorder_sync, True)
                self._teacher_handle = None
                self._video_proc = None
                if self.voice_prompt_enabled:
                    self._say("Teacher video не поднялся. Запись не начата.")
                error = sample.get("error") or "teacher truth layer did not become active in time"
                return {
                    "ok": False,
                    "error": f"Teacher source unavailable at start: {error}",
                    "preflight": self._preflight,
                    "teacher_status": sample,
                }

        self.recording = True
        self._session_start = time.time()
        self._session_started_at_iso = datetime.now().isoformat()
        self._session_summary_path = CAPTURE_DIR / f"{self.session_label}.recording_summary.json"

        # Start first chunk
        self._start_new_chunk()

        if self.with_video:
            self._teacher_monitor_task = asyncio.create_task(self._teacher_monitor_loop(self._session_token))
        if self.voice_prompt_enabled and self.voice_cues:
            self._voice_cue_task = asyncio.create_task(self._voice_cue_loop(self._session_token))

        if self.voice_prompt_enabled:
            self._say(f"Запись начата. {label}")

        logger.info(
            "Recording started: %s, chunk=%ss, video=%s, teacher=%s",
            label,
            chunk_sec,
            self.with_video,
            self.teacher_source_kind,
        )
        return {
            "ok": True,
            "label": label,
            "chunk_sec": chunk_sec,
            "with_video": self.with_video,
            "video_required": self.video_required,
            "teacher_source_kind": self.teacher_source_kind,
            "teacher_source_name": self.teacher_source_name,
            "teacher_source_url_redacted": self.teacher_source_url_redacted,
            "teacher_device_name": self.teacher_device_name,
            "session_start": self._session_started_at_iso,
        }

    async def stop_recording(
        self,
        voice_prompt: Optional[bool] = None,
        *,
        reason: str | None = None,
        failure_prompt: str | None = None,
    ) -> dict:
        """Stop recording and flush current chunk."""
        if not self.recording:
            if self._last_stop_result:
                return {**self._last_stop_result, "already_stopped": True}
            return {"ok": False, "error": "Not recording"}

        self.recording = False
        self._teacher_stop_requested = True
        if reason:
            self._stop_reason = reason
        voice_enabled = self.voice_prompt_enabled if voice_prompt is None else bool(voice_prompt)

        await self._cancel_background_tasks()

        # Flush current chunk (even if < chunk_sec)
        self._flush_chunk(final=True)

        teacher_finalize = await asyncio.to_thread(self._finalize_teacher_recorder_sync, False)
        self._video_proc = None
        duration = time.time() - self._session_start

        session_summary = self._build_session_summary(duration, teacher_finalize)
        self._session_summary = session_summary
        if self._session_summary_path:
            with self._session_summary_path.open("w", encoding="utf-8") as handle:
                json.dump(session_summary, handle, indent=2, ensure_ascii=False)

        if voice_enabled:
            if failure_prompt:
                self._say(failure_prompt)
            else:
                self._say(
                    f"Запись завершена. {self._total_chunks} чанков, {self._total_packets} пакетов."
                )

        result = {
            "ok": True,
            "label": self.session_label,
            "duration_sec": round(duration, 1),
            "total_chunks": self._total_chunks,
            "total_packets": self._total_packets,
            "node_packets": dict(self._node_packet_counts),
            "last_chunk": self._last_saved_chunk,
            "status": session_summary["session_status"],
            "stop_reason": session_summary.get("stop_reason"),
            "session_summary_path": str(self._session_summary_path) if self._session_summary_path else None,
            "truth_summary": session_summary["truth_summary"],
            "labeling_verdict": session_summary["labeling_verdict"],
        }
        self._last_stop_result = result
        logger.info("Recording stopped: %s", result)
        return result

    # ── Packet ingestion (called from prediction service) ──────────

    def ingest_packet(self, raw_data: bytes, addr: tuple):
        """Called for every UDP packet when recording is active.
        This runs in the main event loop — must be fast."""
        if not self.recording:
            return

        ip = addr[0]
        if ip not in NODE_IPS:
            return

        ts_ns = int(time.time() * 1e9)
        self._chunk_packets.append((ts_ns, ip, raw_data))
        self._total_packets += 1
        self._node_packet_counts[ip] += 1

        # Check if chunk time exceeded
        elapsed = time.time() - self._chunk_start
        if elapsed >= self.chunk_sec:
            self._flush_chunk()
            self._start_new_chunk()

    # ── Chunk management ──────────────────────────────────────────

    def _start_new_chunk(self):
        """Start a new recording chunk."""
        self._chunk_num += 1
        self._chunk_start = time.time()
        self._chunk_packets = []

    def _flush_chunk(self, final: bool = False):
        """Save current chunk to disk. Crash-resilient — one file per chunk."""
        if not self._chunk_packets:
            if final:
                logger.info("Final flush: no packets to save")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        chunk_label = f"{self.session_label}_chunk{self._chunk_num:04d}_{ts}"

        # Save CSI data as ndjson.gz
        csi_path = CAPTURE_DIR / f"{chunk_label}.ndjson.gz"
        with gzip.open(csi_path, "wt") as handle:
            for ts_ns, ip, raw_data in self._chunk_packets:
                port = {
                    "192.168.1.137": 1137,
                    "192.168.1.117": 1117,
                    "192.168.1.101": 1101,
                    "192.168.1.125": 1125,
                    "192.168.1.33": 1033,
                }.get(ip, 0)
                record = {
                    "ts_ns": ts_ns,
                    "src_ip": ip,
                    "src_port": port,
                    "payload_b64": base64.b64encode(raw_data).decode(),
                }
                handle.write(json.dumps(record) + "\n")

        duration = time.time() - self._chunk_start
        pkt_count = len(self._chunk_packets)
        node_counts = defaultdict(int)
        for _, ip, _ in self._chunk_packets:
            node_counts[ip] += 1

        summary = {
            "label": chunk_label,
            "session_label": self.session_label,
            "chunk_num": self._chunk_num,
            "duration_sec": round(duration, 1),
            "packet_count": pkt_count,
            "pps": round(pkt_count / max(duration, 0.1), 1),
            "sources": {ip: node_counts.get(ip, 0) for ip in NODE_IPS},
            "nodes_active": sum(1 for ip in NODE_IPS if node_counts.get(ip, 0) > 0),
            "person_count_expected": self.person_count,
            "motion_type": self.motion_type,
            "space_id": self.space_id,
            "notes": self.notes,
            "with_video": self.with_video,
            "video_required": self.video_required,
            "teacher_source_kind": self.teacher_source_kind,
            "teacher_source_name": self.teacher_source_name,
            "truth_coverage_sec_so_far": round(self._current_truth_coverage_sec(time.time()), 1),
            "teacher_degraded": self._teacher_degraded,
            "teacher_failure_reason": self._teacher_failure_reason,
            "is_final_chunk": final,
            "recorded_at": datetime.now().isoformat(),
        }

        summary_path = CAPTURE_DIR / f"{chunk_label}.summary.json"
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2, ensure_ascii=False)

        # Also save clip.json for pipeline compatibility
        clip = {
            "label": chunk_label,
            "person_count_expected": self.person_count,
            "motion_type": self.motion_type,
            "duration_sec": round(duration, 1),
            "space_id": self.space_id,
            "teacher_source_kind": self.teacher_source_kind,
            "with_video": self.with_video,
            "video_required": self.video_required,
        }
        clip_path = CAPTURE_DIR / f"{chunk_label}.clip.json"
        with clip_path.open("w", encoding="utf-8") as handle:
            json.dump(clip, handle, indent=2, ensure_ascii=False)

        self._last_saved_chunk = {
            "label": chunk_label,
            "data_path": str(csi_path),
            "summary_path": str(summary_path),
            "clip_path": str(clip_path),
            "packet_count": pkt_count,
            "nodes_active": summary["nodes_active"],
            "duration_sec": round(duration, 1),
        }

        self._total_chunks += 1

        logger.info(
            "Chunk %s saved: %s pkts, %.0fs, %s/%s nodes → %s",
            self._chunk_num,
            pkt_count,
            duration,
            summary["nodes_active"],
            len(NODE_IPS),
            csi_path.name,
        )

        # Reset for next chunk
        self._chunk_packets = []

    # ── Teacher source helpers ───────────────────────────────────

    def _resolve_teacher_source(
        self,
        *,
        with_video: bool,
        video_required: bool | None,
        teacher_source_kind: str | None,
        teacher_source_url: str | None,
        teacher_source_name: str | None,
        teacher_device: str | None,
        teacher_device_name: str | None,
        teacher_input_pixel_format: str | None,
        teacher_start_timeout_sec: float | None,
    ) -> dict[str, Any]:
        requested = bool(with_video or (teacher_source_kind and teacher_source_kind != "none") or video_required)
        strict_video_required = requested if video_required is None else bool(video_required)
        raw_kind = (teacher_source_kind or "").strip()
        if raw_kind == "mac_camera_terminal":
            raw_kind = "mac_camera"
        kind = raw_kind or (("mac_camera" if sys.platform == "darwin" else "rtsp_teacher") if requested else "none")
        if kind not in KNOWN_TEACHER_SOURCE_KINDS:
            raise ValueError(
                f"Unsupported teacher_source_kind={kind}. Expected one of {sorted(KNOWN_TEACHER_SOURCE_KINDS)}"
            )
        if kind == "none" and strict_video_required:
            raise ValueError("video_required=true requires teacher_source_kind != 'none'")

        cfg: dict[str, Any] = {
            "kind": kind,
            "video_requested": requested and kind != "none",
            "video_required": strict_video_required and kind != "none",
            "start_timeout_sec": max(
                4.0,
                float(teacher_start_timeout_sec or DEFAULT_TEACHER_START_TIMEOUT_SEC),
            ),
        }
        if kind in {"rtsp_teacher", "phone_rtsp", "pixel_rtsp"}:
            source_url = (teacher_source_url or RTSP_URL).strip()
            if not source_url:
                raise ValueError(f"{kind} requires teacher_source_url or a configured default RTSP_URL")
            cfg["source_url"] = source_url
            default_source_name = "Pixel 8 Pro" if kind == "pixel_rtsp" else ("Phone RTSP" if kind == "phone_rtsp" else "RTSP Teacher")
            cfg["source_name"] = (teacher_source_name or default_source_name).strip()
            cfg["source_url_redacted"] = self._redact_rtsp_url(source_url)
        elif kind == "mac_camera":
            cfg["device"] = str(teacher_device or DEFAULT_TERMINAL_CAMERA_DEVICE).strip() or DEFAULT_TERMINAL_CAMERA_DEVICE
            cfg["device_name"] = (
                str(teacher_device_name or teacher_device or DEFAULT_TERMINAL_CAMERA_DEVICE).strip()
                or DEFAULT_TERMINAL_CAMERA_DEVICE
            )
            cfg["source_name"] = "Mac Camera"
            cfg["input_pixel_format"] = (
                str(teacher_input_pixel_format or DEFAULT_TERMINAL_CAMERA_PIXEL_FORMAT).strip()
                or DEFAULT_TERMINAL_CAMERA_PIXEL_FORMAT
            )
        else:
            cfg["source_name"] = "none"
        return cfg

    def _probe_teacher_source_sync(self, teacher_cfg: dict[str, Any]) -> dict[str, Any]:
        report: dict[str, Any] = {
            "requested": bool(teacher_cfg.get("video_requested")),
            "video_required": bool(teacher_cfg.get("video_required")),
            "source_kind": teacher_cfg["kind"],
            "source_name": teacher_cfg.get("source_name"),
            "source_url_redacted": teacher_cfg.get("source_url_redacted"),
            "device": teacher_cfg.get("device"),
            "device_name": teacher_cfg.get("device_name"),
            "available": teacher_cfg["kind"] == "none",
            "startup_verification_required": teacher_cfg["kind"] != "none",
            "backend": None,
            "probe": None,
            "error": None,
        }
        if teacher_cfg["kind"] == "none":
            return report

        if teacher_cfg["kind"] in {"rtsp_teacher", "phone_rtsp", "pixel_rtsp"}:
            ok, payload, error = self._run_json_script(
                PIXEL_VIDEO_TEACHER_HOST_SCRIPT,
                "probe-rtsp",
                "--url",
                str(teacher_cfg["source_url"]),
                "--timeout-sec",
                "4.0",
            )
            report["backend"] = "network_rtsp_ffmpeg"
            report["probe"] = payload
            report["available"] = bool(ok and payload and payload.get("ok"))
            if not report["available"]:
                report["error"] = error or ((payload or {}).get("stderr")) or "RTSP probe failed"
            return report

        if teacher_cfg["kind"] == "mac_camera":
            status_ok, status_payload, status_error = self._run_json_script(
                MAC_VIDEO_TEACHER_HOST_SCRIPT,
                "source-status",
                "--device-selector",
                str(teacher_cfg.get("device_name") or teacher_cfg.get("device") or ""),
            )
            report["backend"] = "terminal_ffmpeg_avfoundation"
            report["probe"] = status_payload if status_ok else {"error": status_error}
            if not status_ok or not status_payload:
                report["error"] = status_error or "Mac camera source-status failed"
                return report
            report["available"] = bool(status_payload.get("available"))
            device_payload = status_payload.get("device") or {}
            report["device"] = str(device_payload.get("index") or teacher_cfg.get("device") or "")
            report["device_name"] = str(device_payload.get("name") or teacher_cfg.get("device_name") or "")
            if not report["available"]:
                report["error"] = (
                    status_payload.get("reason")
                    or "Mac camera unavailable"
                )
            return report

        report["error"] = f"Unhandled teacher source kind: {teacher_cfg['kind']}"
        return report

    def _start_teacher_recorder_sync(self, teacher_cfg: dict[str, Any]) -> dict[str, Any]:
        ffmpeg_path = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        if not Path(ffmpeg_path).exists():
            raise RuntimeError("ffmpeg not found")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_path = CAPTURE_DIR / f"{self.session_label}_{ts}.teacher.mp4"
        if teacher_cfg["kind"] in {"rtsp_teacher", "phone_rtsp", "pixel_rtsp"}:
            proc = subprocess.Popen(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-y",
                    "-rtsp_transport",
                    "tcp",
                    "-i",
                    str(teacher_cfg["source_url"]),
                    "-t",
                    str(MAX_VIDEO_RECORDING_SEC),
                    "-an",
                    "-c:v",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(video_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            return {
                "kind": teacher_cfg["kind"],
                "backend": "network_rtsp_ffmpeg",
                "proc": proc,
                "video_path": str(video_path),
                "source_url_redacted": teacher_cfg.get("source_url_redacted"),
                "source_name": teacher_cfg.get("source_name"),
            }

        if teacher_cfg["kind"] == "mac_camera":
            command_path = video_path.with_suffix(".teacher.command")
            log_path = video_path.with_suffix(".teacher.log")
            result_path = video_path.with_suffix(".teacher.result.json")
            pid_path = video_path.with_suffix(".teacher.pid")
            ready_path = video_path.with_suffix(".teacher.ready.json")
            stop_path = video_path.with_suffix(".teacher.stop")
            completed = subprocess.run(
                [
                    HOST_SCRIPT_PYTHON,
                    str(MAC_VIDEO_TEACHER_HOST_SCRIPT),
                    "write-session-command",
                    "--command-path",
                    str(command_path),
                    "--video-path",
                    str(video_path),
                    "--log-path",
                    str(log_path),
                    "--result-path",
                    str(result_path),
                    "--pid-path",
                    str(pid_path),
                    "--ready-path",
                    str(ready_path),
                    "--stop-path",
                    str(stop_path),
                    "--device-selector",
                    str(teacher_cfg.get("device") or teacher_cfg.get("device_name")),
                    "--pixel-format",
                    str(teacher_cfg.get("input_pixel_format") or DEFAULT_TERMINAL_CAMERA_PIXEL_FORMAT),
                    "--max-duration-sec",
                    str(MAX_VIDEO_RECORDING_SEC),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    (completed.stderr or completed.stdout or "failed to prepare terminal video recorder").strip()
                )
            launched_ok, launched_payload, launched_error = self._run_json_script(
                MAC_VIDEO_TEACHER_HOST_SCRIPT,
                "launch-terminal-command",
                "--command-path",
                str(command_path),
            )
            if not launched_ok or not launched_payload or not launched_payload.get("ok"):
                raise RuntimeError(launched_error or (launched_payload or {}).get("stderr") or "failed to launch terminal video recorder")
            return {
                "kind": teacher_cfg["kind"],
                "backend": "terminal_ffmpeg_avfoundation",
                "video_path": str(video_path),
                "command_path": str(command_path),
                "log_path": str(log_path),
                "result_path": str(result_path),
                "pid_path": str(pid_path),
                "ready_path": str(ready_path),
                "stop_path": str(stop_path),
                "device": teacher_cfg.get("device"),
                "device_name": teacher_cfg.get("device_name"),
                "source_name": teacher_cfg.get("source_name"),
                "launch": launched_payload,
            }

        raise RuntimeError(f"Unsupported teacher source kind: {teacher_cfg['kind']}")

    async def _await_teacher_ready(self, timeout_sec: float) -> tuple[bool, dict[str, Any]]:
        deadline = time.time() + max(4.0, float(timeout_sec))
        last_sample: dict[str, Any] = {"ready": False, "error": "teacher source did not start"}
        while time.time() < deadline:
            sample = self._sample_teacher_handle()
            last_sample = sample
            if sample.get("ready"):
                self._teacher_ready = True
                self._teacher_truth_started_at = sample.get("last_growth_at") or time.time()
                self._teacher_last_growth_at = self._teacher_truth_started_at
                self._teacher_last_file_size = int(sample.get("video_size") or 0)
                self._teacher_last_sample = sample
                return True, sample
            if sample.get("fatal"):
                return False, sample
            await asyncio.sleep(0.5)
        if not last_sample.get("error"):
            last_sample["error"] = "teacher source did not produce live video in time"
        return False, last_sample

    async def _teacher_monitor_loop(self, session_token: int):
        while self.recording and self._session_token == session_token:
            sample = self._sample_teacher_handle()
            self._teacher_last_sample = sample

            if sample.get("fatal"):
                await self._handle_teacher_failure(sample.get("error") or "teacher recorder exited unexpectedly")
                return

            last_growth_at = sample.get("last_growth_at")
            if (
                self._teacher_ready
                and last_growth_at
                and not self._teacher_stop_requested
                and time.time() - float(last_growth_at) > self.teacher_stall_timeout_sec
            ):
                await self._handle_teacher_failure(
                    f"teacher truth stalled for {time.time() - float(last_growth_at):.1f}s"
                )
                return

            await asyncio.sleep(1.0)

    async def _handle_teacher_failure(self, reason: str):
        if self._teacher_failure_reason:
            return
        logger.warning("Teacher source failure detected: %s", reason)
        self._teacher_failure_reason = reason
        self._teacher_degraded = True
        self._teacher_ready = False
        self._teacher_truth_ended_at = self._teacher_last_growth_at or time.time()
        if self.video_required and self.recording:
            self._teacher_auto_stopped = True
            await self.stop_recording(
                voice_prompt=True,
                reason=f"teacher_source_lost:{reason}",
                failure_prompt="Teacher video потеряно. Запись остановлена.",
            )

    def _sample_teacher_handle(self) -> dict[str, Any]:
        handle = self._teacher_handle or {}
        sample: dict[str, Any] = {
            "source_kind": handle.get("kind"),
            "backend": handle.get("backend"),
            "video_path": handle.get("video_path"),
            "video_exists": False,
            "video_size": 0,
            "ready": False,
            "fatal": False,
            "error": None,
            "last_growth_at": self._teacher_last_growth_at,
            "degraded": self._teacher_degraded,
            "failure_reason": self._teacher_failure_reason,
        }
        ready_path_value = handle.get("ready_path")
        if ready_path_value:
            ready_path = Path(str(ready_path_value)).expanduser()
            if ready_path.exists():
                try:
                    sample["ready_payload"] = json.loads(ready_path.read_text(encoding="utf-8"))
                    sample["ready"] = True
                except Exception as exc:
                    sample["error"] = f"invalid teacher ready payload: {exc}"
                    sample["fatal"] = True
                    return sample
        path_value = handle.get("video_path")
        path = Path(str(path_value)).expanduser() if path_value else None
        if path and path.exists():
            size = path.stat().st_size
            sample["video_exists"] = True
            sample["video_size"] = size
            if size > self._teacher_last_file_size:
                self._teacher_last_file_size = size
                self._teacher_last_growth_at = time.time()
            sample["last_growth_at"] = self._teacher_last_growth_at
            sample["ready"] = size >= MIN_VIDEO_READY_BYTES

        proc = handle.get("proc")
        if proc is not None:
            returncode = proc.poll()
            sample["process_running"] = returncode is None
            sample["returncode"] = returncode
            if returncode is not None and not self._teacher_stop_requested:
                sample["fatal"] = True
                sample["error"] = f"teacher recorder exited rc={returncode}"
                return sample

        result_path_value = handle.get("result_path")
        if result_path_value:
            result_path = Path(str(result_path_value)).expanduser()
            if result_path.exists():
                try:
                    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    sample["fatal"] = True
                    sample["error"] = f"invalid terminal recorder result: {exc}"
                    return sample
                sample["result_payload"] = result_payload
                status = str(result_payload.get("status") or "").strip()
                if not self._teacher_stop_requested and status and status != "completed":
                    sample["fatal"] = True
                    sample["error"] = f"terminal recorder {status}: {result_payload.get('failure_reason') or 'unknown'}"
                    return sample
                if not self._teacher_stop_requested and status == "completed":
                    sample["fatal"] = True
                    sample["error"] = "terminal recorder finished unexpectedly before recording stop"
                    return sample

        return sample

    def _finalize_teacher_recorder_sync(self, failed_start: bool) -> dict[str, Any]:
        handle = self._teacher_handle
        if not handle:
            return {
                "source_kind": self.teacher_source_kind,
                "video_path": str(self._video_path) if self._video_path else None,
                "video_exists": False,
                "video_bytes": 0,
                "video_duration_sec": None,
                "exit_code": None,
                "result_payload": None,
            }

        result_payload = None
        stderr_excerpt = None
        exit_code = None
        cleanup = {
            "stop_requested": False,
            "pid": None,
            "signal_sent": None,
            "force_signal": None,
            "process_exited": None,
            "video_stable": None,
        }

        if handle.get("proc") is not None:
            proc: subprocess.Popen[str] = handle["proc"]
            if proc.poll() is None:
                proc.terminate()
                try:
                    _, stderr_excerpt = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _, stderr_excerpt = proc.communicate()
            else:
                _, stderr_excerpt = proc.communicate()
            exit_code = proc.returncode

        stop_path_value = handle.get("stop_path")
        if stop_path_value and not failed_start:
            stop_path = Path(str(stop_path_value)).expanduser()
            stop_path.write_text("stop\n", encoding="utf-8")
            cleanup["stop_requested"] = True

        pid_path_value = handle.get("pid_path")
        pid = None
        if pid_path_value:
            pid_path = Path(str(pid_path_value)).expanduser()
            pid = self._read_pid_file(pid_path)
            cleanup["pid"] = pid
        if pid and self._process_exists(pid):
            if failed_start:
                cleanup["signal_sent"] = "SIGTERM"
                self._signal_process(pid, signal.SIGTERM)
                cleanup["process_exited"] = self._wait_for_process_exit(pid, 3.0)
            else:
                cleanup["process_exited"] = self._wait_for_process_exit(pid, 6.0)
                if not cleanup["process_exited"]:
                    cleanup["signal_sent"] = "SIGINT"
                    self._signal_process(pid, signal.SIGINT)
                    cleanup["process_exited"] = self._wait_for_process_exit(pid, 4.0)
                if not cleanup["process_exited"]:
                    cleanup["force_signal"] = "SIGTERM"
                    self._signal_process(pid, signal.SIGTERM)
                    cleanup["process_exited"] = self._wait_for_process_exit(pid, 3.0)
                if not cleanup["process_exited"]:
                    cleanup["force_signal"] = "SIGKILL"
                    self._signal_process(pid, signal.SIGKILL)
                    cleanup["process_exited"] = self._wait_for_process_exit(pid, 2.0)

        result_path = Path(str(handle.get("result_path"))).expanduser()
        deadline = time.time() + (3.0 if failed_start else 12.0)
        while time.time() < deadline:
            if result_path.exists() and result_path.stat().st_size > 0:
                try:
                    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
                    exit_code = result_payload.get("exit_code")
                    break
                except Exception as exc:
                    stderr_excerpt = f"failed to parse terminal result: {exc}"
            time.sleep(0.25)

        video_path = Path(str(handle.get("video_path"))).expanduser()
        video_exists = video_path.exists()
        video_bytes = video_path.stat().st_size if video_exists else 0
        if video_exists:
            stable, stable_size = self._wait_for_file_stable(video_path, timeout_sec=3.0, stable_window_sec=1.0)
            cleanup["video_stable"] = stable
            video_bytes = stable_size
        else:
            cleanup["video_stable"] = True
        video_duration_sec = self._probe_media_duration(video_path) if video_exists else None
        if result_payload and result_payload.get("actual_duration_sec") is not None:
            try:
                video_duration_sec = float(result_payload.get("actual_duration_sec"))
            except (TypeError, ValueError):
                pass

        stop_integrity_failure = None
        if cleanup["process_exited"] is False:
            stop_integrity_failure = "teacher_process_alive_after_stop"
        elif cleanup["video_stable"] is False:
            stop_integrity_failure = "teacher_video_file_still_growing_after_stop"
        if stop_integrity_failure:
            self._teacher_degraded = True
            self._teacher_failure_reason = self._teacher_failure_reason or stop_integrity_failure
            stderr_excerpt = ((stderr_excerpt or "") + f"\n{stop_integrity_failure}").strip()
            if result_payload is None:
                result_payload = {
                    "status": "degraded",
                    "failure_reason": stop_integrity_failure,
                    "stop_requested": cleanup["stop_requested"],
                    "stop_signal_sent": cleanup["signal_sent"],
                    "stop_force_signal": cleanup["force_signal"],
                    "exit_code": exit_code,
                }

        if self._teacher_truth_ended_at is None and self._teacher_last_growth_at is not None:
            self._teacher_truth_ended_at = self._teacher_last_growth_at
        if video_duration_sec and self._teacher_truth_started_at is None:
            self._teacher_truth_started_at = self._session_start or time.time()

        return {
            "source_kind": handle.get("kind"),
            "backend": handle.get("backend"),
            "video_path": str(video_path),
            "video_exists": video_exists,
            "video_bytes": video_bytes,
            "video_duration_sec": round(float(video_duration_sec), 3) if video_duration_sec is not None else None,
            "exit_code": exit_code,
            "stderr_excerpt": (stderr_excerpt or "").strip()[-1000:] or None,
            "result_payload": result_payload,
            "log_path": handle.get("log_path"),
            "command_path": handle.get("command_path"),
            "ready_path": handle.get("ready_path"),
            "stop_path": handle.get("stop_path"),
            "stop_cleanup": cleanup,
        }

    def _build_session_summary(self, session_duration_sec: float, teacher_finalize: dict[str, Any]) -> dict[str, Any]:
        session_duration_sec = max(0.0, float(session_duration_sec))
        real_video_duration_sec = teacher_finalize.get("video_duration_sec")

        wall_coverage_sec = self._current_truth_coverage_sec(self._teacher_truth_ended_at or time.time())
        if wall_coverage_sec <= 0 and real_video_duration_sec:
            wall_coverage_sec = float(real_video_duration_sec)

        truth_candidates = []
        if wall_coverage_sec > 0:
            truth_candidates.append(float(wall_coverage_sec))
        if real_video_duration_sec is not None and float(real_video_duration_sec) > 0:
            truth_candidates.append(float(real_video_duration_sec))
        truth_coverage_sec = max(truth_candidates) if truth_candidates else 0.0
        if session_duration_sec > 0:
            truth_coverage_sec = min(session_duration_sec, truth_coverage_sec)
        coverage_ratio = round(truth_coverage_sec / session_duration_sec, 3) if session_duration_sec > 0 else 0.0

        coverage_status = "not_required"
        if self.with_video:
            if truth_coverage_sec <= 0.1 or not teacher_finalize.get("video_exists"):
                coverage_status = "missing"
            elif (truth_coverage_sec + 2.0 >= session_duration_sec or coverage_ratio >= 0.995) and not self._teacher_failure_reason:
                coverage_status = "full"
            else:
                coverage_status = "partial"

        if self.video_required:
            if coverage_status == "full":
                session_status = "completed"
                verdict = {
                    "code": "video_backed_session_ready",
                    "suitable_for_labeling": True,
                    "reason": "Teacher video covered the whole session.",
                }
            elif coverage_status == "partial":
                session_status = "degraded"
                verdict = {
                    "code": "partial_video_coverage",
                    "suitable_for_labeling": False,
                    "reason": "Teacher video covered only part of the session.",
                }
            else:
                session_status = "failed"
                verdict = {
                    "code": "video_truth_missing",
                    "suitable_for_labeling": False,
                    "reason": "Video-backed truth layer was required but missing.",
                }
        else:
            if coverage_status == "partial":
                session_status = "degraded"
                verdict = {
                    "code": "optional_video_partial",
                    "suitable_for_labeling": False,
                    "reason": "Optional teacher video degraded during the session.",
                }
            else:
                session_status = "completed"
                verdict = {
                    "code": "csi_recording_completed" if not self.with_video else "optional_video_ok",
                    "suitable_for_labeling": coverage_status in {"not_required", "full"},
                    "reason": "CSI session completed." if not self.with_video else "Optional video remained available.",
                }

        truth_summary = {
            "with_video": self.with_video,
            "video_required": self.video_required,
            "teacher_source_kind": self.teacher_source_kind,
            "teacher_source_name": self.teacher_source_name,
            "teacher_source_url_redacted": self.teacher_source_url_redacted,
            "teacher_device_name": self.teacher_device_name,
            "teacher_video_path": teacher_finalize.get("video_path"),
            "teacher_video_exists": teacher_finalize.get("video_exists"),
            "teacher_video_bytes": teacher_finalize.get("video_bytes"),
            "teacher_video_exit_code": teacher_finalize.get("exit_code"),
            "teacher_start_confirmed": bool(self._teacher_truth_started_at),
            "teacher_lost_mid_session": bool(self._teacher_failure_reason),
            "teacher_failure_reason": self._teacher_failure_reason,
            "teacher_auto_stopped": self._teacher_auto_stopped,
            "teacher_degraded": self._teacher_degraded,
            "full_session_duration_sec": round(session_duration_sec, 3),
            "real_video_duration_sec": round(float(real_video_duration_sec), 3) if real_video_duration_sec is not None else None,
            "truth_coverage_duration_sec": round(truth_coverage_sec, 3),
            "truth_coverage_ratio": coverage_ratio,
            "coverage_status": coverage_status,
            "coverage_started_at": self._time_to_iso(self._teacher_truth_started_at),
            "coverage_ended_at": self._time_to_iso(self._teacher_truth_ended_at),
        }

        return {
            "label": self.session_label,
            "session_status": session_status,
            "stop_reason": self._stop_reason,
            "started_at": self._session_started_at_iso,
            "ended_at": datetime.now().isoformat(),
            "duration_sec": round(session_duration_sec, 3),
            "total_chunks": self._total_chunks,
            "total_packets": self._total_packets,
            "node_packets": dict(self._node_packet_counts),
            "preflight": self._preflight,
            "teacher": teacher_finalize,
            "truth_summary": truth_summary,
            "labeling_verdict": verdict,
            "notes": self.notes,
            "person_count_expected": self.person_count,
            "motion_type": self.motion_type,
            "space_id": self.space_id,
        }

    def _current_truth_coverage_sec(self, end_time: float | None) -> float:
        if not self._teacher_truth_started_at:
            return 0.0
        effective_end = end_time or self._teacher_last_growth_at or time.time()
        return max(0.0, float(effective_end) - float(self._teacher_truth_started_at))

    async def _cancel_background_tasks(self):
        current = asyncio.current_task()
        tasks: list[asyncio.Task] = []
        for attr in ("_teacher_monitor_task", "_voice_cue_task"):
            task = getattr(self, attr)
            if task is None:
                continue
            if task is current:
                setattr(self, attr, None)
                continue
            if not task.done():
                task.cancel()
                tasks.append(task)
            setattr(self, attr, None)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _reset_runtime_state(self):
        self.recording = False
        self._chunk_num = 0
        self._chunk_start = 0.0
        self._chunk_packets = []
        self._session_start = 0.0
        self._session_started_at_iso = None
        self._total_packets = 0
        self._total_chunks = 0
        self._node_packet_counts = defaultdict(int)
        self._last_saved_chunk = None

        self._video_proc = None
        self._video_path = None
        self._teacher_handle = None
        self._teacher_ready = False
        self._teacher_degraded = False
        self._teacher_stop_requested = False
        self._teacher_failure_reason = None
        self._teacher_auto_stopped = False
        self._teacher_truth_started_at = None
        self._teacher_truth_ended_at = None
        self._teacher_last_growth_at = None
        self._teacher_last_file_size = 0
        self._teacher_last_sample = None

        self._session_summary = None
        self._session_summary_path = None
        self._last_stop_result = None
        self._stop_reason = None

    def _run_json_script(self, script_path: Path, *args: str) -> tuple[bool, dict[str, Any] | None, str | None]:
        completed = subprocess.run(
            [HOST_SCRIPT_PYTHON, str(script_path), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return False, None, (completed.stderr or completed.stdout or f"{script_path.name} failed").strip()
        try:
            payload = json.loads((completed.stdout or "{}").strip() or "{}")
        except json.JSONDecodeError as exc:
            return False, None, f"{script_path.name} returned invalid json: {exc}"
        return True, payload, None

    def _match_mac_camera_device(self, payload: dict[str, Any], target: str) -> dict[str, Any] | None:
        target = str(target or "").strip()
        devices = payload.get("video_devices") or []
        for item in devices:
            index = str(item.get("index") or "").strip()
            name = str(item.get("name") or "").strip()
            if target in {index, name}:
                return item
        return None

    def _redact_rtsp_url(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(str(url or "").strip())
        if not parsed.scheme or not parsed.netloc:
            return str(url or "").strip()
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        netloc = f"{hostname}{port}"
        path = parsed.path or ""
        if parsed.query:
            path = f"{path}?…"
        return urllib.parse.urlunsplit((parsed.scheme, netloc, path, "", ""))

    def _read_pid_file(self, pid_path: Path) -> int | None:
        if not pid_path.exists():
            return None
        try:
            return int(pid_path.read_text(encoding="utf-8").strip())
        except Exception:
            return None

    def _process_exists(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _signal_process(self, pid: int, sig: int) -> bool:
        try:
            os.kill(pid, sig)
            return True
        except ProcessLookupError:
            return False
        except OSError as exc:
            logger.warning("Failed to signal pid=%s sig=%s: %s", pid, sig, exc)
            return False

    def _wait_for_process_exit(self, pid: int, timeout_sec: float) -> bool:
        deadline = time.time() + max(0.1, float(timeout_sec))
        while time.time() < deadline:
            if not self._process_exists(pid):
                return True
            time.sleep(0.25)
        return not self._process_exists(pid)

    def _wait_for_file_stable(self, path: Path, *, timeout_sec: float = 3.0, stable_window_sec: float = 1.0) -> tuple[bool, int]:
        if not path.exists():
            return True, 0
        last_size = path.stat().st_size
        stable_since = time.time()
        deadline = time.time() + max(stable_window_sec, float(timeout_sec))
        while time.time() < deadline:
            time.sleep(0.25)
            size = path.stat().st_size if path.exists() else 0
            if size != last_size:
                last_size = size
                stable_since = time.time()
                continue
            if time.time() - stable_since >= stable_window_sec:
                return True, last_size
        return False, last_size

    def _probe_media_duration(self, path: Path) -> float | None:
        ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
        if not Path(ffprobe).exists():
            return None
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return None
        try:
            return float((completed.stdout or "").strip())
        except ValueError:
            return None

    def _time_to_iso(self, value: float | None) -> str | None:
        if value is None:
            return None
        return datetime.fromtimestamp(value).isoformat()

    # ── Status ────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get recording status for API/UI."""
        if not self.recording:
            return {
                "recording": False,
                "preflight": self._preflight,
                "last_result": self._last_stop_result,
                "last_session_summary": self._session_summary,
            }

        elapsed = time.time() - self._session_start
        chunk_elapsed = time.time() - self._chunk_start
        chunk_packets = len(self._chunk_packets)

        last_growth_age_sec = None
        if self._teacher_last_growth_at is not None:
            last_growth_age_sec = round(time.time() - self._teacher_last_growth_at, 2)

        return {
            "recording": True,
            "label": self.session_label,
            "elapsed_sec": round(elapsed, 1),
            "chunk_num": self._chunk_num,
            "chunk_elapsed_sec": round(chunk_elapsed, 1),
            "chunk_packets": chunk_packets,
            "chunk_pps": round(chunk_packets / max(chunk_elapsed, 0.1), 1),
            "total_packets": self._total_packets,
            "total_chunks": self._total_chunks,
            "with_video": self.with_video,
            "video_required": self.video_required,
            "teacher_source_kind": self.teacher_source_kind,
            "teacher_source_name": self.teacher_source_name,
            "teacher_source_url_redacted": self.teacher_source_url_redacted,
            "teacher_device_name": self.teacher_device_name,
            "person_count": self.person_count,
            "motion_type": self.motion_type,
            "node_packets": dict(self._node_packet_counts),
            "preflight": self._preflight,
            "teacher_status": {
                "ready": self._teacher_ready,
                "degraded": self._teacher_degraded,
                "auto_stopped": self._teacher_auto_stopped,
                "failure_reason": self._teacher_failure_reason,
                "truth_coverage_sec": round(self._current_truth_coverage_sec(time.time()), 2),
                "last_growth_age_sec": last_growth_age_sec,
                "video_path": str(self._video_path) if self._video_path else None,
                "sample": self._teacher_last_sample,
            },
        }


# Singleton
csi_recording_service = CsiRecordingService()
