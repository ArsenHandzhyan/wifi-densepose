"""
Unified CSI Recording Service
==============================
Records CSI data in parallel with live prediction.
Features:
- Pre-flight checks: all 4 ESP32 nodes + explicit teacher source probe
- Strict video-backed gate: CSI recording starts only after teacher truth is alive
- Post-start CSI signal gate: CSI-dead starts auto-abort within first seconds
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

from .recording_truth_hardening import (
    build_truth_hardening_report,
    build_zone_review_autowire_status,
    normalize_motion_type,
)
from .csi_management_probe import (
    build_csi_probe_timeout,
    infer_csi_status_schema,
    probe_csi_node_status,
)
from .csi_node_inventory import CORE_NODE_IPS, NODE_IPS, NODE_NAMES

logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parents[3]
CAPTURE_DIR = PROJECT / "temp" / "captures"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

MAC_VIDEO_TEACHER_HOST_SCRIPT = PROJECT / "scripts" / "mac_video_teacher_host.py"
PIXEL_VIDEO_TEACHER_HOST_SCRIPT = PROJECT / "scripts" / "pixel_video_teacher_host.py"
GARAGE_ZONE_REVIEW_PACKET_SCRIPT = PROJECT / "scripts" / "init_garage_zone_review_packet.py"

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
POST_START_SIGNAL_GRACE_SEC = float(os.getenv("CSI_POST_START_SIGNAL_GRACE_SEC", "20.0"))
POST_START_SIGNAL_MIN_ACTIVE_CORE_NODES = int(os.getenv("CSI_POST_START_MIN_ACTIVE_CORE_NODES", "3"))
POST_START_SIGNAL_MIN_PACKETS = int(os.getenv("CSI_POST_START_MIN_PACKETS", "3"))
POST_START_SIGNAL_MIN_PPS = float(os.getenv("CSI_POST_START_MIN_PPS", "0.3"))


class CsiRecordingService:
    def __init__(self):
        self.recording = False
        self.session_label = ""
        self.chunk_sec = 60
        self.with_video = False
        self.video_required = False
        self.voice_prompt_enabled = True
        self.voice_cues: list[dict[str, Any]] = []
        self.person_count: int | None = None
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
        self._startup_guard_task: asyncio.Task | None = None
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
        self._truth_hardening: dict[str, Any] | None = None
        self._startup_signal_guard: dict[str, Any] | None = None
        self._rf_manifest_nodes: dict[str, dict[str, Any]] = {}

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
        stream_health = {}
        try:
            from .csi_prediction_service import csi_prediction_service
            stream_health = csi_prediction_service.get_node_health()
        except Exception:
            stream_health = {}
        async with aiohttp.ClientSession(timeout=build_csi_probe_timeout()) as session:
            probe_results = await asyncio.gather(
                *(probe_csi_node_status(session, ip) for ip in CORE_NODE_IPS)
            )

        for ip, probe in zip(CORE_NODE_IPS, probe_results):
            name = NODE_NAMES.get(ip, ip)
            stream = stream_health.get(name, {})
            if probe.get("ok"):
                data = probe.get("data") or {}
                results["nodes"][name] = {
                    "ip": ip,
                    "ok": True,
                    "uptime": data.get("uptime_sec", 0),
                    "firmware": data.get("firmware_version", data.get("version", data.get("fw", "?"))),
                    "send_errors": data.get("send_errors", data.get("send_errors_total", 0)),
                    "runtime_mode": data.get("runtime_mode"),
                    "connected_ssid": data.get("connected_ssid"),
                    "connected_bssid": data.get("connected_bssid"),
                    "primary_channel": data.get("primary_channel"),
                    "secondary_channel": data.get("secondary_channel"),
                    "authmode": data.get("authmode"),
                    "tx_power_dbm": data.get("tx_power_dbm"),
                    "stream_status": stream.get("status"),
                    "last_seen_sec": stream.get("last_seen_sec"),
                }
                nodes_ok += 1
            else:
                results["nodes"][name] = {
                    "ip": ip,
                    "ok": False,
                    "error": probe.get("error"),
                    "error_type": probe.get("error_type"),
                    "stream_status": stream.get("status"),
                    "last_seen_sec": stream.get("last_seen_sec"),
                }

        if nodes_ok < 3:
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

    def _snapshot_rf_manifest_node(self, name: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        status_schema = payload.get("status_schema")
        if status_schema is None:
            status_schema = infer_csi_status_schema(payload)
        return {
            "ip": payload.get("ip"),
            "ok": bool(payload.get("ok")),
            "runtime_mode": payload.get("runtime_mode"),
            "connected_ssid": payload.get("connected_ssid"),
            "connected_bssid": payload.get("connected_bssid"),
            "primary_channel": payload.get("primary_channel"),
            "secondary_channel": payload.get("secondary_channel"),
            "authmode": payload.get("authmode"),
            "tx_power_dbm": payload.get("tx_power_dbm"),
            "status_schema": status_schema,
            "firmware": payload.get("firmware"),
            "management_error": payload.get("error") or payload.get("management_error"),
        }

    def _seed_rf_manifest_from_preflight(self) -> None:
        nodes = self._preflight.get("nodes") if isinstance(self._preflight, dict) else {}
        if not isinstance(nodes, dict):
            self._rf_manifest_nodes = {}
            return
        self._rf_manifest_nodes = {
            str(name): self._snapshot_rf_manifest_node(str(name), payload)
            for name, payload in nodes.items()
            if isinstance(payload, dict)
        }

    def _rf_manifest_probe_targets(self) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        seen: set[str] = set()

        nodes = self._preflight.get("nodes") if isinstance(self._preflight, dict) else {}
        if isinstance(nodes, dict):
            for name, payload in nodes.items():
                if not isinstance(payload, dict):
                    continue
                ip = str(payload.get("ip") or "").strip()
                if not ip or ip in seen:
                    continue
                seen.add(ip)
                targets.append((str(name), ip))

        for ip in NODE_IPS:
            if int(self._node_packet_counts.get(ip, 0) or 0) <= 0 or ip in seen:
                continue
            seen.add(ip)
            targets.append((NODE_NAMES.get(ip, ip), ip))

        return targets

    async def _refresh_rf_manifest_snapshot(self) -> None:
        targets = self._rf_manifest_probe_targets()
        if not targets:
            return

        import aiohttp

        async with aiohttp.ClientSession(timeout=build_csi_probe_timeout(total_sec=4.0)) as session:
            probe_results = await asyncio.gather(
                *(
                    probe_csi_node_status(
                        session,
                        ip,
                        attempts=3,
                        retry_delay_sec=0.35,
                    )
                    for _, ip in targets
                )
            )

        for (name, ip), probe in zip(targets, probe_results):
            existing = self._rf_manifest_nodes.get(name) or {}
            if probe.get("ok"):
                data = probe.get("data") or {}
                payload = {
                    "ip": ip,
                    "ok": True,
                    "runtime_mode": data.get("runtime_mode"),
                    "connected_ssid": data.get("connected_ssid"),
                    "connected_bssid": data.get("connected_bssid"),
                    "primary_channel": data.get("primary_channel"),
                    "secondary_channel": data.get("secondary_channel"),
                    "authmode": data.get("authmode"),
                    "tx_power_dbm": data.get("tx_power_dbm"),
                    "status_schema": infer_csi_status_schema(data),
                    "firmware": data.get("firmware_version", data.get("version", data.get("fw", "?"))),
                }
                self._rf_manifest_nodes[name] = self._snapshot_rf_manifest_node(name, payload)
                continue

            if existing.get("ok"):
                continue

            self._rf_manifest_nodes[name] = {
                **self._snapshot_rf_manifest_node(name, {"ip": ip}),
                "management_error": probe.get("error"),
            }

    def _build_rf_manifest(self) -> dict[str, Any]:
        nodes = self._rf_manifest_nodes
        if not isinstance(nodes, dict) or not nodes:
            preflight_nodes = self._preflight.get("nodes") if isinstance(self._preflight, dict) else {}
            nodes = preflight_nodes if isinstance(preflight_nodes, dict) else {}

        node_entries: dict[str, Any] = {}
        ok_nodes = 0
        value_sets: dict[str, set[str]] = {
            "runtime_mode": set(),
            "connected_ssid": set(),
            "connected_bssid": set(),
            "primary_channel": set(),
            "secondary_channel": set(),
            "authmode": set(),
            "tx_power_dbm": set(),
        }

        for name, payload in nodes.items():
            if not isinstance(payload, dict):
                continue
            node_entry = {
                "ip": payload.get("ip"),
                "ok": bool(payload.get("ok")),
                "runtime_mode": payload.get("runtime_mode"),
                "connected_ssid": payload.get("connected_ssid"),
                "connected_bssid": payload.get("connected_bssid"),
                "primary_channel": payload.get("primary_channel"),
                "secondary_channel": payload.get("secondary_channel"),
                "authmode": payload.get("authmode"),
                "tx_power_dbm": payload.get("tx_power_dbm"),
            }
            node_entries[str(name)] = node_entry
            if not node_entry["ok"]:
                continue
            ok_nodes += 1
            for key in value_sets:
                value = node_entry.get(key)
                if value is None or value == "":
                    continue
                value_sets[key].add(str(value))

        consensus: dict[str, Any] = {}
        mismatches: dict[str, list[str]] = {}
        for key, values in value_sets.items():
            if not values:
                consensus[key] = None
                continue
            if len(values) == 1:
                only = next(iter(values))
                if key in {"primary_channel", "secondary_channel"}:
                    try:
                        consensus[key] = int(only)
                    except ValueError:
                        consensus[key] = only
                elif key == "tx_power_dbm":
                    try:
                        consensus[key] = float(only)
                    except ValueError:
                        consensus[key] = only
                else:
                    consensus[key] = only
            else:
                consensus[key] = None
                mismatches[key] = sorted(values)

        return {
            "source": "preflight_node_status_enriched",
            "ok_nodes": ok_nodes,
            "node_count": len(node_entries),
            "consensus": consensus,
            "mismatches": mismatches,
            "nodes": node_entries,
        }

    # ── Voice prompts ──────────────────────────────────────────────

    def _say(self, text: str):
        """Speak text using ElevenLabs TTS only (no macOS say fallback)."""
        try:
            from v1.src.services.tts_service import get_tts_service
            tts = get_tts_service()
            if tts.available:
                tts.speak(text, block=False)
                return
        except Exception as exc:
            logger.warning("ElevenLabs TTS failed: %s", exc)

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

    def _build_startup_signal_snapshot(self) -> dict[str, Any]:
        chunk_elapsed = max(time.time() - self._chunk_start, 0.0)
        chunk_packets = len(self._chunk_packets)
        active_core_nodes = sum(1 for ip in CORE_NODE_IPS if self._node_packet_counts.get(ip, 0) > 0)
        active_nodes = sum(1 for ip in NODE_IPS if self._node_packet_counts.get(ip, 0) > 0)
        return {
            "checked_at": datetime.now().isoformat(),
            "grace_sec": POST_START_SIGNAL_GRACE_SEC,
            "chunk_elapsed_sec": round(chunk_elapsed, 2),
            "chunk_packets": chunk_packets,
            "chunk_pps": round(chunk_packets / max(chunk_elapsed, 0.1), 2),
            "total_packets": self._total_packets,
            "active_core_nodes": active_core_nodes,
            "active_nodes": active_nodes,
            "node_packets": dict(self._node_packet_counts),
            "thresholds": {
                "min_active_core_nodes": POST_START_SIGNAL_MIN_ACTIVE_CORE_NODES,
                "min_packets": POST_START_SIGNAL_MIN_PACKETS,
                "min_pps": POST_START_SIGNAL_MIN_PPS,
            },
        }

    def _startup_signal_guard_ok(self, snapshot: dict[str, Any]) -> bool:
        return (
            int(snapshot.get("active_core_nodes") or 0) >= POST_START_SIGNAL_MIN_ACTIVE_CORE_NODES
            and int(snapshot.get("chunk_packets") or 0) >= POST_START_SIGNAL_MIN_PACKETS
            and float(snapshot.get("chunk_pps") or 0.0) >= POST_START_SIGNAL_MIN_PPS
        )

    async def _startup_signal_guard_loop(self, session_token: int):
        await asyncio.sleep(max(1.0, POST_START_SIGNAL_GRACE_SEC))
        if not self.recording or self._session_token != session_token:
            return

        snapshot = self._build_startup_signal_snapshot()
        if self._startup_signal_guard_ok(snapshot):
            snapshot["status"] = "passed"
            self._startup_signal_guard = snapshot
            logger.info(
                "Post-start CSI guard passed: label=%s core_nodes=%s packets=%s pps=%.2f",
                self.session_label,
                snapshot["active_core_nodes"],
                snapshot["chunk_packets"],
                snapshot["chunk_pps"],
            )
            return

        snapshot["status"] = "failed"
        snapshot["reason"] = "csi_dead_on_start"
        self._startup_signal_guard = snapshot
        logger.warning(
            "Post-start CSI guard failed: label=%s core_nodes=%s packets=%s pps=%.2f",
            self.session_label,
            snapshot["active_core_nodes"],
            snapshot["chunk_packets"],
            snapshot["chunk_pps"],
        )
        await self.stop_recording(
            voice_prompt=True,
            reason=(
                "csi_dead_on_start:"
                f"core_nodes={snapshot['active_core_nodes']},"
                f"packets={snapshot['chunk_packets']},"
                f"pps={snapshot['chunk_pps']}"
            ),
            failure_prompt="CSI сигнал не пошёл. Запись остановлена.",
        )

    # ── Recording control ─────────────────────────────────────────

    async def start_recording(
        self,
        label: str,
        chunk_sec: int = 60,
        with_video: bool = False,
        person_count: int | None = None,
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
            return self._build_start_error_result(
                "Already recording",
                error_code="already_recording",
            )

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
            return self._build_start_error_result(
                str(exc),
                error_code="invalid_teacher_config",
            )

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
                return self._build_start_error_result(
                    pf.get("error", "Pre-flight failed"),
                    error_code="recording_preflight_failed",
                    preflight=pf,
                )
        else:
            pf = {
                "ok": True,
                "timestamp": datetime.now().isoformat(),
                "teacher": self._probe_teacher_source_sync(teacher_cfg),
            }
            self._preflight = pf

        self._reset_runtime_state()
        self._seed_rf_manifest_from_preflight()
        self._session_token += 1
        self.session_label = label
        self.chunk_sec = chunk_sec
        self.with_video = teacher_cfg["video_requested"]
        self.video_required = teacher_cfg["video_required"]
        self.voice_prompt_enabled = bool(voice_prompt)
        self.voice_cues = list(voice_cues or [])
        self.person_count = person_count
        if person_count is None:
            logger.warning(
                "person_count not specified for session %s — "
                "metadata will record person_count_expected=null. "
                "Downstream truth layers may flag this as ambiguous. "
                "Pass explicit person_count to avoid this warning.",
                label,
            )
        self.motion_type = normalize_motion_type(motion_type, person_count=person_count)
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
                return self._build_start_error_result(
                    f"Teacher source start failed: {exc}",
                    error_code="teacher_source_start_failed",
                    preflight=self._preflight,
                )

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
                return self._build_start_error_result(
                    f"Teacher source unavailable at start: {error}",
                    error_code="teacher_source_unavailable_at_start",
                    preflight=self._preflight,
                    teacher_status=sample,
                )

        self.recording = True
        self._session_start = time.time()
        self._session_started_at_iso = datetime.now().isoformat()
        self._session_summary_path = CAPTURE_DIR / f"{self.session_label}.recording_summary.json"

        # Start first chunk
        self._start_new_chunk()
        self._startup_signal_guard = {
            "status": "pending",
            "grace_sec": POST_START_SIGNAL_GRACE_SEC,
            "thresholds": {
                "min_active_core_nodes": POST_START_SIGNAL_MIN_ACTIVE_CORE_NODES,
                "min_packets": POST_START_SIGNAL_MIN_PACKETS,
                "min_pps": POST_START_SIGNAL_MIN_PPS,
            },
        }

        if self.with_video:
            self._teacher_monitor_task = asyncio.create_task(self._teacher_monitor_loop(self._session_token))
        self._startup_guard_task = asyncio.create_task(self._startup_signal_guard_loop(self._session_token))
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
                return {
                    **self._last_stop_result,
                    "already_stopped": True,
                    "message": "Recording service is already inactive",
                }
            return {
                "ok": True,
                "status": "already_stopped",
                "already_stopped": True,
                "message": "Recording service is already inactive",
            }

        self.recording = False
        self._teacher_stop_requested = True
        if reason:
            self._stop_reason = reason
        voice_enabled = self.voice_prompt_enabled if voice_prompt is None else bool(voice_prompt)

        await self._cancel_background_tasks()

        await self._refresh_rf_manifest_snapshot()

        # Flush current chunk (even if < chunk_sec)
        self._flush_chunk(final=True)

        teacher_finalize = await asyncio.to_thread(self._finalize_teacher_recorder_sync, False)
        self._video_proc = None
        duration = time.time() - self._session_start

        session_summary = self._build_session_summary(duration, teacher_finalize)
        zone_review_packet_path = await asyncio.to_thread(
            self._normalize_and_persist_session_summary_sync,
            session_summary,
        )

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
            "truth_hardening": session_summary.get("truth_hardening"),
            "zone_review_packet_path": session_summary.get("zone_review_packet_path") or zone_review_packet_path,
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
                    "192.168.0.137": 1137,
                    "192.168.0.117": 1117,
                    "192.168.0.143": 1143,
                    "192.168.0.125": 1125,
                    "192.168.0.110": 1110,
                    "192.168.0.132": 1132,
                    "192.168.0.153": 1153,
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
            "rf_manifest": self._build_rf_manifest(),
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
                    ready_text = ready_path.read_text(encoding="utf-8")
                    if ready_text.strip():
                        sample["ready_payload"] = json.loads(ready_text)
                        sample["ready"] = True
                except Exception as exc:
                    proc = handle.get("proc")
                    process_running = proc is not None and proc.poll() is None
                    # Treat a transient empty/partial ready file as "not ready yet"
                    # while the teacher process is still starting up.
                    if process_running and ready_path.stat().st_size == 0:
                        sample["error"] = "teacher ready payload not written yet"
                    else:
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

        if self._stop_reason and self._stop_reason.startswith("csi_dead_on_start"):
            session_status = "failed"
            verdict = {
                "code": "csi_dead_on_start",
                "suitable_for_labeling": False,
                "reason": "CSI signal did not become live during the post-start guard window.",
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
            "startup_signal_guard": self._startup_signal_guard,
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
            "startup_signal_guard": self._startup_signal_guard,
            "teacher": teacher_finalize,
            "truth_summary": truth_summary,
            "labeling_verdict": verdict,
            "notes": self.notes,
            "person_count_expected": self.person_count,
            "motion_type": self.motion_type,
            "space_id": self.space_id,
            "rf_manifest": self._build_rf_manifest(),
        }

    def _current_truth_coverage_sec(self, end_time: float | None) -> float:
        if not self._teacher_truth_started_at:
            return 0.0
        effective_end = end_time or self._teacher_last_growth_at or time.time()
        return max(0.0, float(effective_end) - float(self._teacher_truth_started_at))

    def _persist_session_summary_sync(self, session_summary: dict[str, Any]) -> None:
        if not self._session_summary_path:
            return
        with self._session_summary_path.open("w", encoding="utf-8") as handle:
            json.dump(session_summary, handle, indent=2, ensure_ascii=False)

    def _normalize_and_persist_session_summary_sync(self, session_summary: dict[str, Any]) -> str | None:
        zone_review_packet_path = str(session_summary.get("zone_review_packet_path") or "").strip() or None
        if zone_review_packet_path:
            existing_path = Path(zone_review_packet_path).expanduser()
            if not existing_path.exists():
                zone_review_packet_path = None
                session_summary.pop("zone_review_packet_path", None)
            else:
                zone_review_packet_path = str(existing_path)
                session_summary["zone_review_packet_path"] = zone_review_packet_path

        # Persist an initial summary before packet bootstrap so the helper script
        # always sees a coherent stop payload.
        self._persist_session_summary_sync(session_summary)

        if not zone_review_packet_path:
            zone_review_packet_path = self._maybe_generate_zone_review_packet_sync(session_summary)
            if zone_review_packet_path:
                session_summary["zone_review_packet_path"] = zone_review_packet_path

        session_summary["truth_hardening"] = build_truth_hardening_report(
            session_summary,
            zone_review_packet_path=zone_review_packet_path,
        )
        self._truth_hardening = session_summary["truth_hardening"]
        self._session_summary = session_summary
        self._persist_session_summary_sync(session_summary)
        return zone_review_packet_path

    def _maybe_generate_zone_review_packet_sync(self, session_summary: dict[str, Any]) -> str | None:
        if not self._session_summary_path:
            return None
        zone_review_status = build_zone_review_autowire_status(session_summary)
        self._truth_hardening = build_truth_hardening_report(session_summary)
        if not zone_review_status.get("eligible"):
            logger.info(
                "Garage zone review packet autowire skipped for %s: %s",
                self.session_label,
                ", ".join(zone_review_status.get("blockers") or [zone_review_status.get("reason") or "not_eligible"]),
            )
            return None
        if not GARAGE_ZONE_REVIEW_PACKET_SCRIPT.exists():
            logger.warning("Garage zone review packet script missing: %s", GARAGE_ZONE_REVIEW_PACKET_SCRIPT)
            return None

        try:
            completed = subprocess.run(
                [
                    HOST_SCRIPT_PYTHON,
                    str(GARAGE_ZONE_REVIEW_PACKET_SCRIPT),
                    "--summary",
                    str(self._session_summary_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            logger.warning("Garage zone review packet bootstrap failed: %s", exc)
            return None

        if completed.returncode != 0:
            logger.warning(
                "Garage zone review packet bootstrap exited with code %s: %s",
                completed.returncode,
                (completed.stderr or completed.stdout).strip(),
            )
            return None

        packet_path = (completed.stdout or "").strip().splitlines()
        if not packet_path:
            logger.warning("Garage zone review packet bootstrap returned no output for %s", self.session_label)
            return None
        packet_path_str = packet_path[-1].strip()
        if not packet_path_str:
            return None
        packet_path_obj = Path(packet_path_str).expanduser()
        if not packet_path_obj.exists():
            logger.warning("Garage zone review packet path does not exist: %s", packet_path_obj)
            return None
        self._truth_hardening = build_truth_hardening_report(
            session_summary,
            zone_review_packet_path=str(packet_path_obj),
        )
        return str(packet_path_obj)

    async def _cancel_background_tasks(self):
        current = asyncio.current_task()
        tasks: list[asyncio.Task] = []
        for attr in ("_teacher_monitor_task", "_startup_guard_task", "_voice_cue_task"):
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
        self._startup_signal_guard = None
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
        self._truth_hardening = None
        self._rf_manifest_nodes = {}

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

    def _build_start_error_result(self, error: str, *, error_code: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": error,
            "error_code": error_code,
        }
        payload.update(extra)
        return payload

    # ── Status ────────────────────────────────────────────────────

    def _resolve_recording_lifecycle_status(
        self,
        *,
        recording_active: bool,
        last_stop_result: dict[str, Any] | None,
        last_session_summary: dict[str, Any] | None,
    ) -> dict[str, str]:
        guard = self._startup_signal_guard if isinstance(self._startup_signal_guard, dict) else {}
        guard_status = str(guard.get("status") or "").strip().lower()

        if recording_active:
            if guard_status in {"pending", "starting", "probing"}:
                return {
                    "status": "starting",
                    "status_reason": "awaiting_startup_signal_guard",
                    "status_scope": "current_runtime",
                    "status_message": "Recording started and is waiting for the post-start CSI guard.",
                }
            if self._teacher_degraded or self._teacher_auto_stopped or self._teacher_failure_reason:
                return {
                    "status": "degraded",
                    "status_reason": "teacher_degraded",
                    "status_scope": "current_runtime",
                    "status_message": "Recording is active, but teacher truth is degraded.",
                }
            return {
                "status": "recording",
                "status_reason": "capture_active",
                "status_scope": "current_runtime",
                "status_message": "CSI recording is active.",
            }

        if isinstance(last_session_summary, dict):
            session_status = str(last_session_summary.get("session_status") or "").strip()
            if session_status:
                stop_reason = (
                    str(last_session_summary.get("stop_reason") or "").strip()
                    or str((last_stop_result or {}).get("stop_reason") or "").strip()
                )
                status_reason = stop_reason or f"last_session_{session_status}"
                return {
                    "status": session_status,
                    "status_reason": status_reason,
                    "status_scope": "last_session",
                    "status_message": f"Last recording session finished with status {session_status}.",
                }

        if isinstance(last_stop_result, dict):
            last_status = str(last_stop_result.get("status") or "").strip()
            if last_status == "already_stopped":
                return {
                    "status": "inactive",
                    "status_reason": "already_stopped",
                    "status_scope": "idle",
                    "status_message": "Recording service is already inactive.",
                }

        return {
            "status": "inactive",
            "status_reason": "no_active_recording",
            "status_scope": "idle",
            "status_message": "Recording service is inactive.",
        }

    def _recover_last_session_summary_from_disk(self) -> tuple[dict[str, Any] | None, str | None]:
        try:
            candidates = sorted(
                CAPTURE_DIR.glob("*.recording_summary.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None, None

        for path in candidates:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload, str(path)
        return None, None

    def _build_last_stop_result_from_summary(
        self,
        session_summary: dict[str, Any],
        *,
        summary_path: str | None,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "label": session_summary.get("label"),
            "duration_sec": session_summary.get("duration_sec"),
            "total_chunks": session_summary.get("total_chunks"),
            "total_packets": session_summary.get("total_packets"),
            "node_packets": session_summary.get("node_packets"),
            "last_chunk": None,
            "status": session_summary.get("session_status"),
            "stop_reason": session_summary.get("stop_reason"),
            "session_summary_path": summary_path,
            "truth_summary": session_summary.get("truth_summary"),
            "labeling_verdict": session_summary.get("labeling_verdict"),
            "truth_hardening": session_summary.get("truth_hardening"),
            "zone_review_packet_path": session_summary.get("zone_review_packet_path"),
            "recovered_from_disk": True,
        }

    def get_status(self) -> dict:
        """Get recording status for API/UI."""
        last_stop_result = self._last_stop_result
        last_session_summary = self._session_summary
        if not self.recording and last_session_summary is None:
            last_session_summary, summary_path = self._recover_last_session_summary_from_disk()
            if last_session_summary is not None:
                self._session_summary = last_session_summary
                if self._session_summary_path is None and summary_path:
                    self._session_summary_path = Path(summary_path)
                if last_stop_result is None:
                    last_stop_result = self._build_last_stop_result_from_summary(
                        last_session_summary,
                        summary_path=summary_path,
                    )
                    self._last_stop_result = last_stop_result
        lifecycle = self._resolve_recording_lifecycle_status(
            recording_active=bool(self.recording),
            last_stop_result=last_stop_result,
            last_session_summary=last_session_summary,
        )
        if not self.recording:
            return {
                "recording": False,
                **lifecycle,
                "preflight": self._preflight,
                "startup_signal_guard": self._startup_signal_guard,
                "last_result": last_stop_result,
                "lastStopResult": last_stop_result,
                "last_session_summary": last_session_summary,
                "lastSessionSummary": last_session_summary,
            }

        elapsed = time.time() - self._session_start
        chunk_elapsed = time.time() - self._chunk_start
        chunk_packets = len(self._chunk_packets)

        last_growth_age_sec = None
        if self._teacher_last_growth_at is not None:
            last_growth_age_sec = round(time.time() - self._teacher_last_growth_at, 2)

        return {
            "recording": True,
            **lifecycle,
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
            "startup_signal_guard": self._startup_signal_guard,
            "last_result": last_stop_result,
            "lastStopResult": last_stop_result,
            "last_session_summary": last_session_summary,
            "lastSessionSummary": last_session_summary,
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
