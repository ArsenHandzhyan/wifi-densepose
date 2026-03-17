#!/usr/bin/env python3
"""Canonical atomic CSI training capture with strict manifests and optional teacher media."""

from __future__ import annotations

import argparse
import atexit
import gzip
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from live_sensor_guard import fetch_json, format_health_report, verify_online_sensor_health


SCRIPT_VERSION = "atomic_capture_v1_2026-03-12"
ROOT = Path("/Users/arsen/Desktop/wifi-densepose")
OUT_DIR_DEFAULT = ROOT / "temp" / "captures"
VIDEO_TEACHER_OUT_DIR_DEFAULT = ROOT / "temp" / "video_teacher"
ROOM_CONFIG_DEFAULT = ROOT / "data" / "room-layouts" / "fp2-room-config-1773022408043.json"
FP2_MONITOR_CTL = ROOT / "scripts" / "fp2_cloud_monitor_ctl.py"
MAC_VIDEO_TEACHER_HOST_SCRIPT = ROOT / "scripts" / "mac_video_teacher_host.py"
PIXEL_VIDEO_TEACHER_HOST_SCRIPT = ROOT / "scripts" / "pixel_video_teacher_host.py"

TRAIN_PACKS: dict[str, dict[str, Any]] = {
    "breathing_pack": {
        "title": "Breathing Pack",
        "scenario": "breathing",
        "clips": [
            {"label_name": "quiet_static", "step_name": "quiet_static_pre", "duration_sec": 15, "prompt": "Стой спокойно и дыши тихо.", "person_count_expected": 1},
            {"label_name": "normal_breath", "step_name": "normal_breath", "duration_sec": 20, "prompt": "Стой спокойно и дыши естественно.", "person_count_expected": 1},
            {"label_name": "deep_breath", "step_name": "deep_breath", "duration_sec": 20, "prompt": "Стой спокойно и дыши глубже обычного.", "person_count_expected": 1},
            {"label_name": "quiet_static", "step_name": "quiet_static_post", "duration_sec": 15, "prompt": "Снова стой спокойно и дыши тихо.", "person_count_expected": 1},
        ],
    },
    "occupancy_pack": {
        "title": "Occupancy Pack",
        "scenario": "occupancy",
        "clips": [
            {"label_name": "empty_room", "step_name": "empty_room_pre", "duration_sec": 15, "prompt": "Оставь walkable-зону пустой.", "person_count_expected": 0},
            {"label_name": "quiet_static", "step_name": "quiet_static", "duration_sec": 18, "prompt": "Стой спокойно внутри walkable-зоны.", "person_count_expected": 1},
            {"label_name": "empty_room", "step_name": "empty_room_post", "duration_sec": 15, "prompt": "Снова оставь walkable-зону пустой.", "person_count_expected": 0},
        ],
    },
    "motion_micro_pack": {
        "title": "Motion Micro Pack",
        "scenario": "gross_motion",
        "clips": [
            {"label_name": "quiet_static", "step_name": "quiet_static", "duration_sec": 10, "prompt": "Коротко замри.", "person_count_expected": 1},
            {"label_name": "left_shift", "step_name": "left_shift", "duration_sec": 12, "prompt": "Сместись влево и замри.", "person_count_expected": 1},
            {"label_name": "right_shift", "step_name": "right_shift", "duration_sec": 12, "prompt": "Сместись вправо и замри.", "person_count_expected": 1},
            {"label_name": "step_forward", "step_name": "step_forward", "duration_sec": 12, "prompt": "Сделай шаг вперёд и замри.", "person_count_expected": 1},
            {"label_name": "step_back", "step_name": "step_back", "duration_sec": 12, "prompt": "Сделай шаг назад и замри.", "person_count_expected": 1},
            {"label_name": "bend_once", "step_name": "bend_once", "duration_sec": 10, "prompt": "Один раз наклонись и вернись в стойку.", "person_count_expected": 1},
            {"label_name": "walk_short", "step_name": "walk_short", "duration_sec": 16, "prompt": "Сделай короткую проходку по L-зоне и остановись.", "person_count_expected": 1},
        ],
    },
    "motion_context_replacement_pack": {
        "title": "Historical Context Replacement Pack",
        "scenario": "breathing_specificity",
        "clips": [
            {"label_name": "quiet_static", "step_name": "quiet_static_center_pre", "duration_sec": 12, "prompt": "В центральной точке стой спокойно и дыши тихо.", "person_count_expected": 1},
            {"label_name": "normal_breath", "step_name": "normal_breath_center_1", "duration_sec": 18, "prompt": "В центральной точке дыши естественно.", "person_count_expected": 1},
            {"label_name": "deep_breath", "step_name": "deep_breath_center", "duration_sec": 18, "prompt": "В центральной точке дыши глубже обычного.", "person_count_expected": 1},
            {"label_name": "normal_breath", "step_name": "normal_breath_center_2", "duration_sec": 18, "prompt": "В центральной точке снова дыши естественно.", "person_count_expected": 1},
            {"label_name": "quiet_static", "step_name": "quiet_static_offset", "duration_sec": 15, "prompt": "Перейди в offset-точку и замри.", "person_count_expected": 1},
            {"label_name": "normal_breath", "step_name": "normal_breath_offset_1", "duration_sec": 18, "prompt": "В offset-точке дыши естественно.", "person_count_expected": 1},
            {"label_name": "deep_breath", "step_name": "deep_breath_offset", "duration_sec": 18, "prompt": "В offset-точке дыши глубже обычного.", "person_count_expected": 1},
            {"label_name": "normal_breath", "step_name": "normal_breath_offset_2", "duration_sec": 18, "prompt": "В offset-точке снова дыши естественно.", "person_count_expected": 1},
            {"label_name": "quiet_static", "step_name": "quiet_static_center_post", "duration_sec": 12, "prompt": "Вернись в центральную точку и снова замри.", "person_count_expected": 1},
        ],
    },
    "agent6_postfix_exit_micro_pack": {
        "title": "Agent6 Postfix Fixed-Ceiling Narrow Exit Micro Pack",
        "scenario": "agent6_postfix_exit_micro_pack",
        "clips": [
            {
                "label_name": "empty_room",
                "step_name": "empty_room_outside_pre",
                "duration_sec": 14,
                "prompt": "Тихо стой снаружи за порогом. Не входи и не наклоняйся внутрь.",
                "person_count_expected": 0,
            },
            {
                "label_name": "occupied_exit_one_person",
                "step_name": "exit_center_to_door_clean",
                "duration_sec": 12,
                "prompt": "Начни в центре. После старта спокойно выйди к двери и полностью наружу.",
                "person_count_expected": 1,
            },
            {
                "label_name": "occupied_exit_one_person",
                "step_name": "near_door_immediate_exit",
                "duration_sec": 12,
                "prompt": "Начни в ближней внутренней точке у двери. После старта сразу выйди наружу без паузы.",
                "person_count_expected": 1,
            },
            {
                "label_name": "empty_room",
                "step_name": "empty_room_outside_post",
                "duration_sec": 14,
                "prompt": "Снова тихо стой снаружи за порогом. Не входи и не возвращайся.",
                "person_count_expected": 0,
            },
        ],
    },
    "agent6_postfix_exit_anchor_pair": {
        "title": "Agent6 Postfix Fixed-Ceiling Exit Anchor Pair",
        "scenario": "agent6_postfix_exit_micro_pack",
        "clips": [
            {
                "label_name": "empty_room",
                "step_name": "empty_room_outside_pre",
                "duration_sec": 14,
                "prompt": "Тихо стой снаружи за порогом. Не входи и не наклоняйся внутрь.",
                "person_count_expected": 0,
            },
            {
                "label_name": "empty_room",
                "step_name": "empty_room_outside_post",
                "duration_sec": 14,
                "prompt": "Снова тихо стой снаружи за порогом. Не входи и не возвращайся.",
                "person_count_expected": 0,
            },
        ],
    },
    "agent6_postfix_exit_positive_pair": {
        "title": "Agent6 Postfix Fixed-Ceiling Exit Positive Pair",
        "scenario": "agent6_postfix_exit_micro_pack",
        "clips": [
            {
                "label_name": "occupied_exit_one_person",
                "step_name": "exit_center_to_door_clean",
                "duration_sec": 12,
                "prompt": "Начни в центре. После старта спокойно выйди к двери и полностью наружу.",
                "person_count_expected": 1,
            },
            {
                "label_name": "occupied_exit_one_person",
                "step_name": "near_door_immediate_exit",
                "duration_sec": 12,
                "prompt": "Начни в ближней внутренней точке у двери. После старта сразу выйди наружу без паузы.",
                "person_count_expected": 1,
            },
        ],
    },
    "agent6_anchor_distance_calibration_session": {
        "title": "Agent6 Anchor Distance Calibration Session",
        "scenario": "agent6_anchor_distance_calibration_session",
        "clips": [
            {
                "label_name": "empty_room",
                "step_name": "outside_near_threshold",
                "duration_sec": 14,
                "prompt": "Стой снаружи прямо у порога. Не входи и не наклоняйся внутрь.",
                "person_count_expected": 0,
            },
            {
                "label_name": "empty_room",
                "step_name": "outside_half_step_back",
                "duration_sec": 14,
                "prompt": "Отойди на полшага назад от порога. Стой снаружи и не подходи к двери.",
                "person_count_expected": 0,
            },
            {
                "label_name": "empty_room",
                "step_name": "outside_one_step_back",
                "duration_sec": 14,
                "prompt": "Отойди на один полный шаг назад от порога. Стой спокойно снаружи.",
                "person_count_expected": 0,
            },
            {
                "label_name": "empty_room",
                "step_name": "outside_two_steps_back",
                "duration_sec": 14,
                "prompt": "Отойди на два шага назад от порога. Стой спокойно снаружи и не приближайся.",
                "person_count_expected": 0,
            },
        ],
    },
}

EVAL_SCENARIOS: dict[str, dict[str, Any]] = {
    "breathing_eval_cycle": {
        "title": "Breathing Eval Cycle",
        "scenario": "breathing_eval",
        "clips": [
            {"label_name": "quiet_static", "step_name": "quiet_static_start", "duration_sec": 15, "prompt": "Тихая статика.", "person_count_expected": 1},
            {"label_name": "normal_breath", "step_name": "normal_breath", "duration_sec": 20, "prompt": "Обычное дыхание.", "person_count_expected": 1},
            {"label_name": "deep_breath", "step_name": "deep_breath", "duration_sec": 20, "prompt": "Глубокое дыхание.", "person_count_expected": 1},
            {"label_name": "walk_short", "step_name": "walk_short", "duration_sec": 15, "prompt": "Короткая проходка по L-зоне.", "person_count_expected": 1},
            {"label_name": "quiet_static", "step_name": "quiet_static_end", "duration_sec": 15, "prompt": "Финальная тихая статика.", "person_count_expected": 1},
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture canonical short CSI clips through the always-on backend.")
    parser.add_argument("--mode", choices=["train_atomic", "eval_scenario", "compare", "teacher_capture"], required=True)
    parser.add_argument("--label-prefix", required=True, help="Run-level prefix for manifest and clip labels.")
    parser.add_argument("--program-id", default="", help="Optional catalog program id.")
    parser.add_argument("--program-title", default="", help="Optional human-readable program title.")
    parser.add_argument("--pack-id", default="", help="Optional starter-pack or eval-scenario id.")
    parser.add_argument("--scenario", default="", help="Scenario family name.")
    parser.add_argument("--step-name", default="", help="Single-clip step name.")
    parser.add_argument("--label-name", default="", help="Canonical atomic label name.")
    parser.add_argument("--prompt", default="", help="Operator prompt for this clip.")
    parser.add_argument("--duration-sec", type=float, default=0.0)
    parser.add_argument("--person-count-expected", type=int, default=-1)
    parser.add_argument("--space-id", default="garage")
    parser.add_argument("--dataset-epoch", default="")
    parser.add_argument("--geometry-label", default="")
    parser.add_argument("--historical-data-policy", default="")
    parser.add_argument("--room-config-path", default=str(ROOM_CONFIG_DEFAULT))
    parser.add_argument("--out-dir", default=str(OUT_DIR_DEFAULT))
    parser.add_argument("--countdown-sec", type=int, default=5)
    parser.add_argument("--disable-voice", action="store_true")
    parser.add_argument("--voice", default="")
    parser.add_argument("--raw-user-description", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--require-fp2", action="store_true")
    parser.add_argument("--video-teacher", action="store_true")
    parser.add_argument("--audio-teacher", action="store_true")
    parser.add_argument(
        "--video-backend",
        choices=["ffmpeg_avfoundation", "terminal_ffmpeg_avfoundation", "network_rtsp_ffmpeg"],
        default=os.getenv(
            "CSI_VIDEO_BACKEND",
            "terminal_ffmpeg_avfoundation" if sys.platform == "darwin" else "ffmpeg_avfoundation",
        ),
    )
    parser.add_argument("--video-device", default=os.getenv("CSI_VIDEO_DEVICE", "Fifine K420" if sys.platform == "darwin" else "1"))
    parser.add_argument("--audio-device", default="0")
    parser.add_argument("--video-device-name", default=os.getenv("CSI_VIDEO_DEVICE_NAME", "Fifine K420"))
    parser.add_argument("--video-source-url", default=os.getenv("CSI_VIDEO_SOURCE_URL", ""))
    parser.add_argument("--video-source-name", default=os.getenv("CSI_VIDEO_SOURCE_NAME", "Pixel 8 Pro"))
    parser.add_argument("--audio-device-name", default="")
    parser.add_argument("--video-width", type=int, default=1280)
    parser.add_argument("--video-height", type=int, default=720)
    parser.add_argument("--video-fps", type=int, default=int(os.getenv("CSI_VIDEO_FPS", "30")))
    parser.add_argument("--video-input-pixel-format", default=os.getenv("CSI_VIDEO_INPUT_PIXEL_FORMAT", "nv12"))
    parser.add_argument("--video-teacher-host", default=os.getenv("CSI_VIDEO_TEACHER_HOST", "mac_local"))
    parser.add_argument("--video-manifest-dir", default=str(VIDEO_TEACHER_OUT_DIR_DEFAULT))
    parser.add_argument("--pose-url", default="http://127.0.0.1:8000/api/v1/pose/current")
    parser.add_argument("--live-window-url", default="http://127.0.0.1:8000/api/v1/pose/live-window")
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/api/v1/health")
    parser.add_argument("--fp2-url", default="http://127.0.0.1:8000/api/v1/fp2/current")
    parser.add_argument("--capture-url", default="http://127.0.0.1:8000/api/v1/fp2/training/capture/live-csi")
    parser.add_argument("--timeout-sec", type=float, default=4.0)
    parser.add_argument("--live-window-seconds", type=float, default=4.0)
    parser.add_argument("--fp2-monitor-interval", type=float, default=3.0)
    parser.add_argument("--fp2-poll-interval", type=float, default=2.0)
    parser.add_argument("--require-live-fp2-coordinates", action="store_true")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def slugify(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value or "").strip().lower())
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_") or "clip"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def session_notes_path(out_dir: Path) -> Path:
    return out_dir / f"SESSION_NOTES_{datetime.now().strftime('%Y-%m-%d')}.md"


def append_session_note(out_dir: Path, title: str, lines: list[str]) -> None:
    note_path = session_notes_path(out_dir)
    existing = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    chunks: list[str] = []
    if not existing:
        chunks.append(f"# Session Notes {datetime.now().strftime('%Y-%m-%d')}\n\n")
    elif not existing.endswith("\n"):
        chunks.append("\n")
    chunks.append(f"## {title}\n")
    for line in lines:
        chunks.append(f"- {line}\n")
    chunks.append("\n")
    with note_path.open("a", encoding="utf-8") as handle:
        handle.write("".join(chunks))


def speak(text: str, *, enable_voice: bool, voice: str) -> None:
    print(text, flush=True)
    if not enable_voice:
        return
    cmd = ["say"]
    if voice:
        cmd.extend(["-v", voice])
    cmd.append(text)
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        pass


def countdown(seconds: int) -> None:
    for remaining in range(max(0, int(seconds)), 0, -1):
        print(f"Старт через {remaining}...", flush=True)
        time.sleep(1)


def post_json(url: str, payload: dict[str, Any], timeout_sec: float) -> tuple[bool, dict[str, Any] | None, str | None]:
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            raw = response.read().decode("utf-8")
        return True, json.loads(raw), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = exc.reason
        return False, None, f"HTTP {exc.code}: {body}"
    except urllib.error.URLError as exc:
        return False, None, f"URL error: {exc.reason}"
    except Exception as exc:
        return False, None, repr(exc)


def fp2_backend_base_url(fp2_url: str) -> str:
    parts = urllib.parse.urlsplit(fp2_url)
    if not parts.scheme or not parts.netloc:
        return "http://127.0.0.1:8000"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def ensure_fp2_monitor(fp2_url: str, *, owner: str, interval_sec: float) -> bool:
    cmd = [
        sys.executable,
        str(FP2_MONITOR_CTL),
        "start",
        "--backend",
        fp2_backend_base_url(fp2_url),
        "--interval",
        f"{max(1.0, float(interval_sec)):g}",
        "--full-snapshot-interval",
        "30",
        "--coordinate-keepalive-cooldown",
        "3",
        "--owner",
        owner,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        print(f"[fp2-monitor] failed: {completed.stderr.strip() or completed.stdout.strip()}", flush=True)
        return False
    try:
        payload = json.loads((completed.stdout or "{}").strip() or "{}")
    except json.JSONDecodeError:
        print(f"[fp2-monitor] unexpected output: {completed.stdout.strip()}", flush=True)
        return False
    if payload.get("started"):
        print(f"[fp2-monitor] started on demand (pid={payload.get('pid')})", flush=True)
        return True
    if payload.get("running"):
        print(f"[fp2-monitor] reusing existing monitor (pid={payload.get('pid')})", flush=True)
    return False


def stop_fp2_monitor() -> None:
    subprocess.run([sys.executable, str(FP2_MONITOR_CTL), "stop"], capture_output=True, text=True, check=False)


def infer_teacher_mode(*, require_fp2: bool, video_teacher: bool, audio_teacher: bool) -> str:
    if require_fp2 and video_teacher and audio_teacher:
        return "fp2_video_audio_teacher"
    if require_fp2 and video_teacher:
        return "fp2_video_teacher"
    if require_fp2:
        return "fp2_teacher"
    if video_teacher and audio_teacher:
        return "video_audio_teacher"
    if video_teacher:
        return "video_teacher"
    if audio_teacher:
        return "audio_teacher"
    return "none"


def load_room_context(room_config_path: Path, space_id: str) -> dict[str, Any]:
    payload = json.loads(room_config_path.read_text(encoding="utf-8"))
    active_profile_id = str(payload.get("activeRoomProfileId") or "")
    profiles = payload.get("customRoomProfiles") or []
    target_profile = None
    for profile in profiles:
        name = str(profile.get("name") or "").lower()
        if space_id == "garage" and ("гараж" in name or "garage" in name):
            target_profile = profile
            break
        if space_id == "room" and ("комнат" in name or "room" in name):
            target_profile = profile
            break
    if target_profile is None:
        target_profile = next((p for p in profiles if str(p.get("id")) == active_profile_id), profiles[0] if profiles else {})
    profile_id = str(target_profile.get("id") or active_profile_id or space_id)
    room_name = str(target_profile.get("name") or space_id)
    layouts = payload.get("roomProfileLayouts") or {}
    walkable = payload.get("roomProfileWalkableAreas") or {}
    calibration = payload.get("roomProfileCalibration") or {}
    active_layouts = list(layouts.get(profile_id) or [])
    active_walkable = list(walkable.get(profile_id) or walkable.get(space_id) or [])
    layout_ids = [str(item.get("id")) for item in active_layouts if item.get("id")]
    walkable_ids = [str(item.get("id")) for item in active_walkable if item.get("id")]
    topology_parts = [space_id, profile_id]
    if walkable_ids:
        topology_parts.extend(sorted(walkable_ids))
    if layout_ids:
        topology_parts.extend(sorted(layout_ids))
    topology_id = ":".join(topology_parts)
    return {
        "space_id": space_id,
        "room_profile": room_name,
        "room_profile_id": profile_id,
        "room_profile_width_cm": target_profile.get("widthCm"),
        "room_profile_depth_cm": target_profile.get("depthCm"),
        "topology_id": topology_id,
        "walkable_area_ids": walkable_ids,
        "layout_ids": layout_ids,
        "calibration": calibration.get(profile_id),
        "active_room_profile_id": active_profile_id,
    }


def parse_user_description(raw: str, clip: dict[str, Any], teacher_mode: str) -> dict[str, Any]:
    text = str(raw or clip.get("prompt") or "").strip()
    return {
        "text": text,
        "mode": clip.get("capture_mode"),
        "scenario": clip.get("scenario"),
        "step_name": clip.get("step_name"),
        "label_name": clip.get("label_name"),
        "person_count_expected": clip.get("person_count_expected"),
        "teacher_mode": teacher_mode,
        "tokens": [token for token in slugify(text).split("_") if token],
    }


def build_clip_specs(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.pack_id:
        library = TRAIN_PACKS if args.mode == "train_atomic" else EVAL_SCENARIOS if args.mode == "eval_scenario" else {}
        pack = library.get(args.pack_id)
        if not pack:
            raise SystemExit(f"Unknown pack_id for mode {args.mode}: {args.pack_id}")
        clips = []
        for item in pack.get("clips", []):
            clips.append(
                {
                    **item,
                    "scenario": pack.get("scenario") or args.scenario or args.mode,
                    "capture_mode": args.mode,
                }
            )
        return clips

    if not args.label_name:
        raise SystemExit("Single clip capture requires --label-name")
    if args.duration_sec <= 0:
        raise SystemExit("Single clip capture requires --duration-sec")
    return [
        {
            "label_name": args.label_name,
            "step_name": args.step_name or args.label_name,
            "duration_sec": float(args.duration_sec),
            "prompt": args.prompt or args.raw_user_description or args.label_name,
            "person_count_expected": None if args.person_count_expected < 0 else int(args.person_count_expected),
            "scenario": args.scenario or args.mode,
            "capture_mode": args.mode,
        }
    ]


def validate_durations(mode: str, clips: list[dict[str, Any]]) -> None:
    for clip in clips:
        duration = float(clip.get("duration_sec") or 0.0)
        if mode in {"train_atomic", "teacher_capture"} and duration > 30.0:
            raise SystemExit(f"Training clip exceeds 30 sec limit: {clip.get('step_name')} -> {duration}")
        if mode == "compare" and duration > 45.0:
            raise SystemExit(f"Compare clip is too long for canonical short capture: {clip.get('step_name')} -> {duration}")


def compact_fp2_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") or {}
    raw = metadata.get("raw_attributes") or {}
    persons = payload.get("persons") or []
    compact_persons = []
    for person in persons:
        bbox = person.get("bounding_box") or {}
        compact_persons.append(
            {
                "person_id": person.get("person_id"),
                "zone_id": person.get("zone_id"),
                "activity": person.get("activity"),
                "confidence": person.get("confidence"),
                "x": bbox.get("x"),
                "y": bbox.get("y"),
            }
        )
    if not compact_persons:
        raw_targets = raw.get("targets") or raw.get("coordinates") or raw.get("live_coordinates") or []
        for target in raw_targets:
            if not isinstance(target, dict):
                continue
            compact_persons.append(
                {
                    "person_id": target.get("target_id") or target.get("id"),
                    "zone_id": target.get("zone_id"),
                    "activity": target.get("activity"),
                    "confidence": target.get("confidence"),
                    "x": target.get("x"),
                    "y": target.get("y"),
                }
            )
    return {
        "timestamp": payload.get("timestamp"),
        "available": metadata.get("available"),
        "stale": metadata.get("stale"),
        "source": metadata.get("source"),
        "presence": metadata.get("effective_presence", metadata.get("presence")),
        "person_count": len(compact_persons),
        "coordinates_source": raw.get("coordinates_source"),
        "persons": compact_persons,
    }


def compact_pose_snapshot(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    metadata = payload.get("metadata") or {}
    persons = payload.get("persons") or []
    return {
        "timestamp": payload.get("timestamp"),
        "person_count": payload.get("person_count"),
        "presence": payload.get("presence"),
        "occupancy_state": payload.get("occupancy_state"),
        "occupancy_event": payload.get("occupancy_event"),
        "motion_state": payload.get("motion_state"),
        "activity": payload.get("activity"),
        "persons_len": len(persons),
        "presence_gate_reason": metadata.get("presence_gate_reason"),
        "presence_held": metadata.get("presence_held"),
        "occupancy_freshness": metadata.get("occupancy_freshness"),
        "occupancy_data_stale": metadata.get("occupancy_data_stale"),
        "occupancy_evidence_mode": metadata.get("occupancy_evidence_mode"),
        "occupancy_unconfirmed_target": metadata.get("occupancy_unconfirmed_target"),
        "live_source_count": metadata.get("live_source_count"),
        "live_total_packets": metadata.get("live_total_packets"),
        "live_last_packet_age_sec": metadata.get("live_last_packet_age_sec"),
        "runtime_session_id": payload.get("runtime_session_id"),
    }


class FP2TeacherPoller(threading.Thread):
    def __init__(self, *, url: str, interval_sec: float, timeout_sec: float, out_path: Path):
        super().__init__(daemon=True)
        self.url = url
        self.interval_sec = max(0.5, float(interval_sec))
        self.timeout_sec = timeout_sec
        self.out_path = out_path
        self._stop_event = threading.Event()
        self.records_written = 0
        self.ok = 0
        self.errors = 0

    def run(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(self.out_path, "wt", encoding="utf-8") as handle:
            next_poll = time.time()
            while not self._stop_event.is_set():
                now = time.time()
                if now < next_poll:
                    self._stop_event.wait(min(0.1, next_poll - now))
                    continue
                ok, payload, error = fetch_json(self.url, self.timeout_sec)
                event = {
                    "ts_iso": now_iso(),
                    "ok": ok,
                    "payload": compact_fp2_snapshot(payload) if ok and payload else None,
                    "error": error,
                }
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                self.records_written += 1
                if ok:
                    self.ok += 1
                else:
                    self.errors += 1
                next_poll += self.interval_sec

    def stop(self) -> None:
        self._stop_event.set()


def ffmpeg_backend_snapshot() -> dict[str, Any]:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return {
            "available": False,
            "ffmpeg_available": False,
            "avfoundation_available": False,
            "backend": None,
            "reason": "ffmpeg not found",
        }
    completed = subprocess.run([ffmpeg_path, "-hide_banner", "-devices"], capture_output=True, text=True, check=False)
    output = f"{completed.stdout}\n{completed.stderr}"
    return {
        "available": True,
        "ffmpeg_available": True,
        "avfoundation_available": "avfoundation" in output,
        "backend": "ffmpeg_avfoundation" if "avfoundation" in output else None,
        "ffmpeg_path": ffmpeg_path,
        "ffprobe_path": shutil.which("ffprobe"),
        "devices_output_excerpt": output[-2000:],
    }


def mac_video_teacher_host(command: str, *extra: str) -> tuple[bool, dict[str, Any] | None, str | None]:
    completed = subprocess.run(
        [sys.executable, str(MAC_VIDEO_TEACHER_HOST_SCRIPT), command, *extra],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return False, None, (completed.stderr or completed.stdout or f"{command} failed").strip()
    try:
        payload = json.loads((completed.stdout or "{}").strip() or "{}")
    except json.JSONDecodeError as exc:
        return False, None, f"{command} returned invalid json: {exc}"
    return True, payload, None


def pixel_video_teacher_host(command: str, *extra: str) -> tuple[bool, dict[str, Any] | None, str | None]:
    completed = subprocess.run(
        [sys.executable, str(PIXEL_VIDEO_TEACHER_HOST_SCRIPT), command, *extra],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return False, None, (completed.stderr or completed.stdout or f"{command} failed").strip()
    try:
        payload = json.loads((completed.stdout or "{}").strip() or "{}")
    except json.JSONDecodeError as exc:
        return False, None, f"{command} returned invalid json: {exc}"
    return True, payload, None


def redact_rtsp_url(url: str) -> str:
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


def tail_text(path: Path, *, limit_chars: int = 1200) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit_chars:]
    except OSError:
        return None


def start_terminal_video_recorder(
    *,
    capture_label: str,
    device_selector: str,
    fps: int,
    width: int,
    height: int,
    duration_sec: float,
    output_path: Path,
    input_pixel_format: str,
) -> dict[str, Any]:
    command_path = output_path.with_suffix(".teacher.command")
    log_path = output_path.with_suffix(".teacher.log")
    result_path = output_path.with_suffix(".teacher.result.json")
    completed = subprocess.run(
        [
            sys.executable,
            str(MAC_VIDEO_TEACHER_HOST_SCRIPT),
            "write-capture-command",
            "--command-path",
            str(command_path),
            "--video-path",
            str(output_path),
            "--log-path",
            str(log_path),
            "--result-path",
            str(result_path),
            "--device-selector",
            device_selector,
            "--width",
            str(width),
            "--height",
            str(height),
            "--fps",
            str(fps),
            "--pixel-format",
            input_pixel_format,
            "--duration-sec",
            f"{duration_sec:g}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "failed to prepare terminal video recorder").strip())
    opener = subprocess.run(["open", str(command_path)], capture_output=True, text=True, check=False)
    if opener.returncode != 0:
        raise RuntimeError((opener.stderr or opener.stdout or "failed to launch terminal video recorder").strip())
    return {
        "backend": "terminal_ffmpeg_avfoundation",
        "command_path": str(command_path),
        "log_path": str(log_path),
        "result_path": str(result_path),
        "video_path": str(output_path),
        "capture_label": capture_label,
    }


def finalize_terminal_video_recorder(handle: dict[str, Any], *, timeout_sec: float) -> tuple[dict[str, Any] | None, str | None]:
    result_path = Path(str(handle.get("result_path") or "")).expanduser()
    log_path = Path(str(handle.get("log_path") or "")).expanduser()
    deadline = time.time() + max(5.0, timeout_sec)
    while time.time() < deadline:
        if result_path.exists():
            break
        time.sleep(0.25)
    if not result_path.exists():
        log_tail = tail_text(log_path)
        return None, f"terminal video recorder did not finish in time{f'; log={log_tail}' if log_tail else ''}"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"failed to parse terminal video recorder result: {exc}"
    if int(payload.get("exit_code") or 0) != 0 or not payload.get("video_exists"):
        log_tail = tail_text(log_path)
        return payload, f"terminal video recorder failed: exit={payload.get('exit_code')} size={payload.get('video_size')}{f'; log={log_tail}' if log_tail else ''}"
    return payload, None


def probe_avfoundation(
    *,
    ffmpeg_path: str,
    input_name: str,
    fps: int,
    width: int,
    height: int,
    timeout_sec: float,
    video: bool,
    input_pixel_format: str | None = None,
) -> tuple[bool, str | None]:
    cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if video:
        cmd.extend(
            [
                "-f",
                "avfoundation",
            ]
        )
        if input_pixel_format:
            cmd.extend(["-pixel_format", input_pixel_format])
        cmd.extend(
            [
                "-framerate",
                str(fps),
                "-video_size",
                f"{width}x{height}",
                "-i",
                input_name,
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ]
        )
    else:
        cmd.extend(
            [
                "-f",
                "avfoundation",
                "-i",
                input_name,
                "-t",
                "0.5",
                "-f",
                "null",
                "-",
            ]
        )
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout_sec)
    if completed.returncode == 0:
        return True, None
    return False, (completed.stderr or completed.stdout or "probe failed").strip()


def build_video_command(
    *,
    ffmpeg_path: str,
    device: str,
    fps: int,
    width: int,
    height: int,
    duration_sec: float,
    output_path: Path,
    input_pixel_format: str | None,
) -> list[str]:
    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-f",
        "avfoundation",
    ]
    if input_pixel_format:
        cmd.extend(["-pixel_format", input_pixel_format])
    cmd.extend(
        [
        "-framerate",
        str(fps),
        "-video_size",
        f"{width}x{height}",
        "-i",
        f"{device}:none",
        "-t",
        f"{duration_sec:g}",
        "-an",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
        ]
    )
    return cmd


def build_rtsp_video_command(
    *,
    ffmpeg_path: str,
    source_url: str,
    fps: int,
    width: int,
    height: int,
    duration_sec: float,
    output_path: Path,
) -> list[str]:
    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
    return [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-rtsp_transport",
        "tcp",
        "-i",
        source_url,
        "-t",
        f"{duration_sec:g}",
        "-an",
        "-vf",
        scale_filter,
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def build_audio_command(
    *,
    ffmpeg_path: str,
    device: str,
    duration_sec: float,
    output_path: Path,
) -> list[str]:
    return [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-f",
        "avfoundation",
        "-i",
        f"none:{device}",
        "-t",
        f"{duration_sec:g}",
        "-vn",
        "-acodec",
        "aac",
        str(output_path),
    ]


def determine_person_count_reported(pose_payload: dict[str, Any] | None, fp2_payload: dict[str, Any] | None) -> int | None:
    if fp2_payload:
        return int(compact_fp2_snapshot(fp2_payload).get("person_count") or 0)
    if not pose_payload:
        return None
    person_count = pose_payload.get("person_count")
    if person_count is not None:
        try:
            return int(person_count)
        except (TypeError, ValueError):
            pass
    persons = pose_payload.get("persons") or []
    return len(persons) if persons else None


def perform_preflight(
    args: argparse.Namespace,
    *,
    require_fp2: bool,
    video_teacher: bool,
    audio_teacher: bool,
) -> dict[str, Any]:
    backend_ok, backend_payload, backend_error = fetch_json(args.health_url, args.timeout_sec)
    if not backend_ok or not backend_payload:
        return {"ok": False, "reason": f"Backend health unavailable: {backend_error}"}

    sensor_report = verify_online_sensor_health(
        pose_url=args.pose_url,
        live_window_url=args.live_window_url,
        fp2_url=args.fp2_url if require_fp2 else None,
        timeout_sec=args.timeout_sec,
        live_window_seconds=args.live_window_seconds,
        require_fp2=require_fp2,
        attempts=3,
        retry_delay_sec=1.0,
        require_live_fp2_coordinates=args.require_live_fp2_coordinates,
    )
    if not sensor_report.get("ok"):
        return {"ok": False, "reason": format_health_report(sensor_report), "sensor_report": sensor_report}

    pose_ok, pose_payload, pose_error = fetch_json(args.pose_url, args.timeout_sec)
    fp2_ok, fp2_payload, fp2_error = (True, None, None)
    if require_fp2:
        fp2_ok, fp2_payload, fp2_error = fetch_json(args.fp2_url, args.timeout_sec)
        if not fp2_ok or not fp2_payload:
            return {"ok": False, "reason": f"FP2 snapshot unavailable after preflight: {fp2_error}", "sensor_report": sensor_report}

    recorder_snapshot = ffmpeg_backend_snapshot()
    teacher_report = {
        "video_teacher_enabled": video_teacher,
        "audio_teacher_enabled": audio_teacher,
        "backend": recorder_snapshot,
        "video_probe": None,
        "audio_probe": None,
    }
    if video_teacher or audio_teacher:
        if not recorder_snapshot.get("ffmpeg_available"):
            return {"ok": False, "reason": "Teacher recording unavailable: ffmpeg not available", "sensor_report": sensor_report, "teacher_report": teacher_report}
        ffmpeg_path = str(recorder_snapshot.get("ffmpeg_path"))
        if video_teacher:
            if args.video_backend == "network_rtsp_ffmpeg":
                if not args.video_source_url:
                    return {
                        "ok": False,
                        "reason": "RTSP source url is required for network_rtsp_ffmpeg",
                        "sensor_report": sensor_report,
                        "teacher_report": teacher_report,
                    }
                probe_ok, probe_payload, probe_error = pixel_video_teacher_host(
                    "probe-rtsp",
                    "--url",
                    args.video_source_url,
                    "--timeout-sec",
                    str(max(2.0, args.timeout_sec)),
                )
                teacher_report["video_probe"] = {
                    "ok": probe_ok and bool(probe_payload and probe_payload.get("ok")),
                    "backend": args.video_backend,
                    "source_name": args.video_source_name,
                    "source_url_redacted": redact_rtsp_url(args.video_source_url),
                    "probe": probe_payload,
                    "error": probe_error,
                }
                if not probe_ok or not probe_payload or not probe_payload.get("ok"):
                    return {
                        "ok": False,
                        "reason": f"RTSP source probe failed: {probe_error or (probe_payload or {}).get('stderr') or 'probe failed'}",
                        "sensor_report": sensor_report,
                        "teacher_report": teacher_report,
                    }
            elif args.video_backend == "terminal_ffmpeg_avfoundation":
                device_ok, device_payload, device_error = mac_video_teacher_host("list-devices")
                status_ok, status_payload, status_error = mac_video_teacher_host("current-host-status")
                if not device_ok or not device_payload:
                    return {
                        "ok": False,
                        "reason": f"Camera device discovery failed: {device_error}",
                        "sensor_report": sensor_report,
                        "teacher_report": teacher_report,
                    }
                device_names = [str(item.get("name") or "") for item in device_payload.get("video_devices") or []]
                selector = args.video_device_name or args.video_device
                if selector not in device_names and args.video_device not in device_names:
                    return {
                        "ok": False,
                        "reason": f"Camera selector not found on Mac host: {selector}",
                        "sensor_report": sensor_report,
                        "teacher_report": teacher_report,
                    }
                teacher_report["video_probe"] = {
                    "ok": True,
                    "backend": args.video_backend,
                    "device": selector,
                    "device_names": device_names,
                    "current_host_camera_status": status_payload if status_ok else {"error": status_error},
                }
            else:
                if not recorder_snapshot.get("avfoundation_available"):
                    return {
                        "ok": False,
                        "reason": "Teacher recording unavailable: ffmpeg avfoundation backend not available",
                        "sensor_report": sensor_report,
                        "teacher_report": teacher_report,
                    }
                ok, error = probe_avfoundation(
                    ffmpeg_path=ffmpeg_path,
                    input_name=f"{args.video_device}:none",
                    fps=args.video_fps,
                    width=args.video_width,
                    height=args.video_height,
                    timeout_sec=max(2.0, args.timeout_sec),
                    video=True,
                    input_pixel_format=args.video_input_pixel_format or None,
                )
                teacher_report["video_probe"] = {"ok": ok, "error": error, "device": args.video_device}
                if not ok:
                    return {"ok": False, "reason": f"Camera probe failed: {error}", "sensor_report": sensor_report, "teacher_report": teacher_report}
        if audio_teacher:
            if not recorder_snapshot.get("avfoundation_available"):
                return {
                    "ok": False,
                    "reason": "Teacher recording unavailable: ffmpeg avfoundation backend not available for audio",
                    "sensor_report": sensor_report,
                    "teacher_report": teacher_report,
                }
            ok, error = probe_avfoundation(
                ffmpeg_path=ffmpeg_path,
                input_name=f"none:{args.audio_device}",
                fps=args.video_fps,
                width=args.video_width,
                height=args.video_height,
                timeout_sec=max(2.0, args.timeout_sec),
                video=False,
            )
            teacher_report["audio_probe"] = {"ok": ok, "error": error, "device": args.audio_device}
            if not ok:
                return {"ok": False, "reason": f"Microphone probe failed: {error}", "sensor_report": sensor_report, "teacher_report": teacher_report}

    return {
        "ok": True,
        "backend_health_snapshot": backend_payload,
        "csi_health_snapshot": sensor_report,
        "fp2_health_snapshot": compact_fp2_snapshot(fp2_payload) if fp2_payload else None,
        "pose_snapshot": pose_payload if pose_ok else None,
        "teacher_report": teacher_report,
    }


def start_recorder(cmd: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def finalize_recorder(proc: subprocess.Popen[str] | None) -> tuple[int | None, str | None]:
    if proc is None:
        return None, None
    try:
        _, stderr = proc.communicate(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, stderr = proc.communicate()
    return proc.returncode, (stderr or "").strip() or None


def trigger_live_csi_capture(args: argparse.Namespace, *, capture_label: str, duration_sec: float) -> dict[str, Any]:
    ok, payload, error = post_json(
        args.capture_url,
        {
            "label": capture_label,
            "duration_sec": duration_sec,
            "out_dir": args.out_dir,
        },
        timeout_sec=max(args.timeout_sec + duration_sec + 10.0, 15.0),
    )
    if not ok or not payload or not payload.get("ok"):
        raise RuntimeError(error or "live CSI capture request failed")
    return dict(payload.get("capture") or {})


def build_video_teacher_manifest(
    *,
    session_path: str,
    video_path: Path,
    camera_name: str,
    video_device: str,
    video_source_kind: str,
    video_source_url_redacted: str,
    label_prefix: str,
    capture_label: str,
    teacher_host: str,
    out_dir: Path,
) -> tuple[str | None, str | None, str | None]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "build_offline_video_teacher_manifest.py"),
        session_path,
        str(video_path),
        "--camera-name",
        camera_name,
        "--video-device",
        video_device,
        "--video-source-kind",
        video_source_kind,
        "--video-source-url-redacted",
        video_source_url_redacted,
        "--teacher-host",
        teacher_host,
        "--label-prefix",
        label_prefix,
        "--capture-label",
        capture_label,
        "--out-dir",
        str(out_dir),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return None, None, (completed.stderr.strip() or completed.stdout.strip() or "video teacher manifest build failed")

    manifest_path = None
    template_path = None
    for line in (completed.stdout or "").splitlines():
        if line.startswith("manifest:"):
            manifest_path = line.split(":", 1)[1].strip()
        elif line.startswith("template:"):
            template_path = line.split(":", 1)[1].strip()
    if not manifest_path or not template_path:
        return None, None, "video teacher manifest command did not report output paths"
    return manifest_path, template_path, None


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    clips = build_clip_specs(args)
    validate_durations(args.mode, clips)

    video_teacher_enabled = bool(args.video_teacher or args.mode == "teacher_capture")
    audio_teacher_enabled = bool(args.audio_teacher)
    require_fp2 = bool(args.require_fp2 or args.mode == "compare")
    teacher_mode = infer_teacher_mode(
        require_fp2=require_fp2,
        video_teacher=video_teacher_enabled,
        audio_teacher=audio_teacher_enabled,
    )
    room_context = load_room_context(Path(args.room_config_path), args.space_id)

    run_manifest_path = out_dir / f"{args.label_prefix}.manifest.json"
    run_manifest: dict[str, Any] = {
        "manifest_version": SCRIPT_VERSION,
        "run_id": args.label_prefix,
        "program_id": args.program_id or args.mode,
        "program_title": args.program_title or args.mode,
        "capture_mode": args.mode,
        "pack_id": args.pack_id or None,
        "scenario": args.scenario or (clips[0].get("scenario") if clips else None),
        "space_id": room_context["space_id"],
        "room_profile": room_context["room_profile"],
        "topology_id": room_context["topology_id"],
        "dataset_epoch": args.dataset_epoch or None,
        "geometry_label": args.geometry_label or None,
        "historical_data_policy": args.historical_data_policy or None,
        "teacher_mode": teacher_mode,
        "fp2_required": require_fp2,
        "video_teacher_enabled": video_teacher_enabled,
        "audio_teacher_enabled": audio_teacher_enabled,
        "room_context": room_context,
        "raw_user_description": args.raw_user_description or None,
        "notes": args.notes or None,
        "script_version": SCRIPT_VERSION,
        "created_at": now_iso(),
        "clips": [],
    }
    write_json(run_manifest_path, run_manifest)
    print(f"manifest: {run_manifest_path}", flush=True)

    started_fp2_monitor_here = False
    if require_fp2:
        started_fp2_monitor_here = ensure_fp2_monitor(
            args.fp2_url,
            owner=f"{args.mode}:{args.label_prefix}",
            interval_sec=args.fp2_monitor_interval,
        )
        if started_fp2_monitor_here:
            atexit.register(stop_fp2_monitor)
            time.sleep(1.5)

    enable_voice = not args.disable_voice
    try:
        for index, clip in enumerate(clips, start=1):
            total = len(clips)
            clip_step_name = str(clip.get("step_name") or clip.get("label_name") or f"clip_{index:02d}")
            clip_label_name = str(clip.get("label_name") or clip_step_name)
            clip_duration_sec = float(clip.get("duration_sec") or 0.0)
            prompt = str(clip.get("prompt") or clip_label_name)
            person_count_expected = clip.get("person_count_expected")
            capture_label = slugify(f"{args.label_prefix}_clip{index:02d}_{clip_step_name}")
            clip_manifest_path = out_dir / f"{capture_label}.clip.json"
            teacher_fp2_path = out_dir / f"{capture_label}.teacher_fp2.ndjson.gz"
            video_path = out_dir / f"{capture_label}.teacher.mp4"
            audio_path = out_dir / f"{capture_label}.teacher_audio.m4a"

            print(f"PROGRESS {index}/{total}: {clip_step_name}", flush=True)
            speak(f"Проверяю запись {index} из {total}.", enable_voice=enable_voice, voice=args.voice)
            preflight = perform_preflight(
                args,
                require_fp2=require_fp2,
                video_teacher=video_teacher_enabled,
                audio_teacher=audio_teacher_enabled,
            )
            if not preflight.get("ok"):
                raise SystemExit(f"preflight failed: {preflight.get('reason')}")

            pose_snapshot = preflight.get("pose_snapshot")
            fp2_snapshot = preflight.get("fp2_health_snapshot")
            pose_snapshot_compact = compact_pose_snapshot(pose_snapshot)
            person_count_reported = determine_person_count_reported(pose_snapshot, fp2_snapshot)
            if fp2_snapshot:
                person_count_reported_source = "fp2_current_snapshot.person_count"
                person_count_reported_semantics = "single_snapshot_fp2_person_count_pre_countdown"
            else:
                person_count_reported_source = "pose_current_snapshot.person_count"
                person_count_reported_semantics = "single_snapshot_live_runtime_person_count_pre_countdown"
            raw_user_description = args.raw_user_description or prompt
            parsed_user_description = parse_user_description(raw_user_description, clip, teacher_mode)
            video_device_name = None
            video_device_selector = None
            video_source_kind = None
            video_source_url_redacted = None
            if video_teacher_enabled:
                if args.video_backend == "network_rtsp_ffmpeg":
                    video_device_name = args.video_source_name or "Pixel 8 Pro"
                    video_device_selector = redact_rtsp_url(args.video_source_url)
                    video_source_kind = "rtsp"
                    video_source_url_redacted = redact_rtsp_url(args.video_source_url)
                else:
                    video_device_name = args.video_device_name or args.video_device
                    video_device_selector = args.video_device

            clip_manifest: dict[str, Any] = {
                "manifest_version": SCRIPT_VERSION,
                "capture_mode": args.mode,
                "program_id": args.program_id or args.mode,
                "program_title": args.program_title or args.mode,
                "clip_index": index,
                "clip_total": total,
                "capture_label": capture_label,
                "timestamp_start": None,
                "timestamp_end": None,
                "duration_sec": clip_duration_sec,
                "space_id": room_context["space_id"],
                "room_profile": room_context["room_profile"],
                "topology_id": room_context["topology_id"],
                "dataset_epoch": args.dataset_epoch or None,
                "geometry_label": args.geometry_label or None,
                "historical_data_policy": args.historical_data_policy or None,
                "label_name": clip_label_name,
                "scenario": clip.get("scenario"),
                "step_name": clip_step_name,
                "person_count_expected": person_count_expected,
                "person_count_reported": person_count_reported,
                "person_count_reported_source": person_count_reported_source,
                "person_count_reported_semantics": person_count_reported_semantics,
                "raw_user_description": raw_user_description,
                "parsed_user_description": parsed_user_description,
                "teacher_mode": teacher_mode,
                "fp2_required": require_fp2,
                "fp2_used": bool(require_fp2),
                "video_teacher_enabled": video_teacher_enabled,
                "video_file": str(video_path) if video_teacher_enabled else None,
                "audio_file": str(audio_path) if audio_teacher_enabled else None,
                "video_start_ts": None,
                "video_end_ts": None,
                "video_device_name": video_device_name if video_teacher_enabled else None,
                "video_device_selector": video_device_selector if video_teacher_enabled else None,
                "video_input_pixel_format": args.video_input_pixel_format if video_teacher_enabled else None,
                "video_recorder_backend": args.video_backend if video_teacher_enabled else None,
                "video_teacher_host": args.video_teacher_host if video_teacher_enabled else None,
                "video_source_kind": video_source_kind if video_teacher_enabled else None,
                "video_source_url_redacted": video_source_url_redacted if video_teacher_enabled else None,
                "video_host_command_file": None,
                "video_host_result_file": None,
                "video_log_file": None,
                "audio_device_name": args.audio_device_name or args.audio_device if audio_teacher_enabled else None,
                "camera_used": bool(video_teacher_enabled),
                "csi_health_snapshot": preflight.get("csi_health_snapshot"),
                "fp2_health_snapshot": fp2_snapshot,
                "pose_snapshot": pose_snapshot_compact,
                "backend_health_snapshot": preflight.get("backend_health_snapshot"),
                "capture_file": None,
                "summary_file": None,
                "teacher_fp2_file": str(teacher_fp2_path) if require_fp2 else None,
                "video_teacher_manifest_file": None,
                "video_teacher_annotations_file": None,
                "manifest_file": str(clip_manifest_path),
                "notes": args.notes or None,
                "script_version": SCRIPT_VERSION,
            }
            write_json(clip_manifest_path, clip_manifest)

            instruction = f"Клип {index}. {prompt}. Запись {int(round(clip_duration_sec))} секунд."
            speak(instruction, enable_voice=enable_voice, voice=args.voice)
            countdown(args.countdown_sec)
            speak("Старт.", enable_voice=enable_voice, voice=args.voice)

            video_proc = None
            audio_proc = None
            teacher_poller = None
            video_start_ts = None
            video_end_ts = None
            if video_teacher_enabled or audio_teacher_enabled:
                ffmpeg_path = str(preflight["teacher_report"]["backend"]["ffmpeg_path"])
                if video_teacher_enabled:
                    video_start_ts = now_iso()
                    if args.video_backend == "terminal_ffmpeg_avfoundation":
                        video_proc = start_terminal_video_recorder(
                            capture_label=capture_label,
                            device_selector=args.video_device_name or args.video_device,
                            fps=args.video_fps,
                            width=args.video_width,
                            height=args.video_height,
                            duration_sec=clip_duration_sec,
                            output_path=video_path,
                            input_pixel_format=args.video_input_pixel_format or "nv12",
                        )
                        clip_manifest["video_host_command_file"] = video_proc.get("command_path")
                        clip_manifest["video_host_result_file"] = video_proc.get("result_path")
                        clip_manifest["video_log_file"] = video_proc.get("log_path")
                        time.sleep(0.75)
                    elif args.video_backend == "network_rtsp_ffmpeg":
                        video_proc = start_recorder(
                            build_rtsp_video_command(
                                ffmpeg_path=ffmpeg_path,
                                source_url=args.video_source_url,
                                fps=args.video_fps,
                                width=args.video_width,
                                height=args.video_height,
                                duration_sec=clip_duration_sec,
                                output_path=video_path,
                            )
                        )
                        time.sleep(0.75)
                    else:
                        video_proc = start_recorder(
                            build_video_command(
                                ffmpeg_path=ffmpeg_path,
                                device=args.video_device,
                                fps=args.video_fps,
                                width=args.video_width,
                                height=args.video_height,
                                duration_sec=clip_duration_sec,
                                output_path=video_path,
                                input_pixel_format=args.video_input_pixel_format or None,
                            )
                        )
                if audio_teacher_enabled:
                    audio_proc = start_recorder(
                        build_audio_command(
                            ffmpeg_path=ffmpeg_path,
                            device=args.audio_device,
                            duration_sec=clip_duration_sec,
                            output_path=audio_path,
                        )
                    )
            if require_fp2:
                teacher_poller = FP2TeacherPoller(
                    url=args.fp2_url,
                    interval_sec=args.fp2_poll_interval,
                    timeout_sec=args.timeout_sec,
                    out_path=teacher_fp2_path,
                )
                teacher_poller.start()

            capture_started_at = now_iso()
            clip_manifest["timestamp_start"] = capture_started_at
            clip_manifest["video_start_ts"] = video_start_ts
            write_json(clip_manifest_path, clip_manifest)

            capture_error: str | None = None
            try:
                print(f"Запускаю запись {capture_label} на {int(round(clip_duration_sec))} секунд", flush=True)
                capture = trigger_live_csi_capture(args, capture_label=capture_label, duration_sec=clip_duration_sec)
                clip_manifest["capture_file"] = capture.get("data_path")
                clip_manifest["summary_file"] = capture.get("summary_path") or capture.get("data_path", "").replace(".ndjson.gz", ".summary.json")
                if int(capture.get("packet_count") or 0) <= 0:
                    raise RuntimeError("live CSI capture returned zero packets")
                print(f"capture: {clip_manifest['capture_file']}", flush=True)
                if clip_manifest["summary_file"]:
                    print(f"summary: {clip_manifest['summary_file']}", flush=True)
            except Exception as exc:
                capture_error = str(exc)
                clip_manifest.setdefault("notes", "")
                clip_manifest["notes"] = ((clip_manifest["notes"] or "") + f" capture_error={capture_error}").strip()
                raise
            finally:
                if teacher_poller is not None:
                    teacher_poller.stop()
                    teacher_poller.join(timeout=max(2.0, args.fp2_poll_interval + 1.0))
                    print(f"teacher_fp2: {teacher_fp2_path}", flush=True)
                if video_proc is not None:
                    if args.video_backend == "terminal_ffmpeg_avfoundation":
                        video_result, video_error = finalize_terminal_video_recorder(
                            video_proc,
                            timeout_sec=max(10.0, clip_duration_sec + 15.0),
                        )
                        if video_result:
                            clip_manifest["video_host_result_file"] = video_proc.get("result_path")
                            clip_manifest["video_log_file"] = video_proc.get("log_path")
                    else:
                        _, video_error = finalize_recorder(video_proc)
                    video_end_ts = now_iso()
                    if video_error:
                        clip_manifest.setdefault("notes", "")
                        clip_manifest["notes"] = ((clip_manifest["notes"] or "") + f" video_recorder={video_error}").strip()
                    print(f"video: {video_path}", flush=True)
                    if clip_manifest.get("capture_file") and video_path.exists():
                        manifest_path, template_path, manifest_error = build_video_teacher_manifest(
                            session_path=str(clip_manifest["capture_file"]),
                            video_path=video_path,
                            camera_name=clip_manifest.get("video_device_name") or args.video_device_name or args.video_device,
                            video_device=clip_manifest.get("video_device_selector") or args.video_device,
                            video_source_kind=clip_manifest.get("video_source_kind") or "",
                            video_source_url_redacted=clip_manifest.get("video_source_url_redacted") or "",
                            label_prefix=args.label_prefix,
                            capture_label=capture_label,
                            teacher_host=args.video_teacher_host,
                            out_dir=Path(args.video_manifest_dir).expanduser().resolve(),
                        )
                        if manifest_error:
                            clip_manifest.setdefault("notes", "")
                            clip_manifest["notes"] = ((clip_manifest["notes"] or "") + f" video_teacher_manifest={manifest_error}").strip()
                        else:
                            clip_manifest["video_teacher_manifest_file"] = manifest_path
                            clip_manifest["video_teacher_annotations_file"] = template_path
                            print(f"video_teacher_manifest: {manifest_path}", flush=True)
                            print(f"video_teacher_annotations: {template_path}", flush=True)
                if audio_proc is not None:
                    _, audio_error = finalize_recorder(audio_proc)
                    if audio_error:
                        clip_manifest.setdefault("notes", "")
                        clip_manifest["notes"] = ((clip_manifest["notes"] or "") + f" audio_recorder={audio_error}").strip()
                    print(f"audio: {audio_path}", flush=True)
                clip_manifest["timestamp_end"] = now_iso()
                clip_manifest["video_end_ts"] = video_end_ts
                write_json(clip_manifest_path, clip_manifest)

            print(f"clip_manifest: {clip_manifest_path}", flush=True)

            run_manifest["clips"].append(clip_manifest)
            write_json(run_manifest_path, run_manifest)
            speak("Стоп.", enable_voice=enable_voice, voice=args.voice)

        run_manifest["finished_at"] = now_iso()
        write_json(run_manifest_path, run_manifest)
        append_session_note(
            out_dir,
            f"Atomic Capture {args.label_prefix}",
            [
                f"mode={args.mode}",
                f"pack_id={args.pack_id or 'none'}",
                f"space={room_context['space_id']}",
                f"topology_id={room_context['topology_id']}",
                f"teacher_mode={teacher_mode}",
                f"clips={len(run_manifest['clips'])}",
                f"manifest={run_manifest_path}",
            ],
        )
        speak("Capture run завершён.", enable_voice=enable_voice, voice=args.voice)
        return 0
    finally:
        if started_fp2_monitor_here:
            stop_fp2_monitor()


if __name__ == "__main__":
    raise SystemExit(main())
