"""
Local CSI training orchestration endpoints.

These endpoints are intentionally local-first and are disabled on Render.
They launch the existing local capture/training scripts and expose a simple
status API for the UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import get_csi_training_store_service
from src.api.dependencies import get_hardware_service_from_request
from src.services.csi_run_viewer import build_run_viewer
from src.services.csi_training_store import CSITrainingStoreService
from src.services.hardware_service import HardwareService


router = APIRouter()
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
_CAPTURES_DIR = _PROJECT_ROOT / "temp" / "captures"
_MODELS_DIR = _PROJECT_ROOT / "temp" / "models"
_DOCS_DIR = _PROJECT_ROOT / "docs"
_GUIDED_REVIEW_DIR = _PROJECT_ROOT / "output" / "garage_guided_review_dense1"
_SCRIPT_PYTHON = os.getenv("CSI_TRAINING_PYTHON", "python3")
_RUN_LOCK = asyncio.Lock()
_ACTIVE_RUN: dict[str, Any] | None = None
_RUN_HISTORY: deque[dict[str, Any]] = deque(maxlen=20)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_execution_available() -> tuple[bool, str | None]:
    if os.getenv("RENDER"):
        return False, "Local training execution is disabled on Render."
    if not _SCRIPTS_DIR.exists():
        return False, f"Scripts directory not found: {_SCRIPTS_DIR}"
    return True, None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "capture"


def _program(
    *,
    program_id: str,
    title: str,
    summary: str,
    stage: Any,
    recommended_order: float,
    expected_duration_sec: int,
    tags: list[str],
    mode: str | None = None,
    script: str = "atomic",
    default_label_prefix: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    scenario: str | None = None,
    step_name: str | None = None,
    label_name: str | None = None,
    prompt: str | None = None,
    person_count_expected: int | None = None,
    pack_id: str | None = None,
    require_fp2: bool = False,
    video_teacher_enabled: bool = False,
    audio_teacher_enabled: bool = False,
    type_: str = "capture",
) -> dict[str, Any]:
    return {
        "id": program_id,
        "title": title,
        "summary": summary,
        "type": type_,
        "script": script,
        "mode": mode,
        "stage": stage,
        "recommended_order": recommended_order,
        "default_label_prefix": default_label_prefix or program_id,
        "expected_duration_sec": expected_duration_sec,
        "tags": list(tags),
        "steps": list(steps or []),
        "scenario": scenario,
        "step_name": step_name,
        "label_name": label_name,
        "prompt": prompt,
        "person_count_expected": person_count_expected,
        "pack_id": pack_id,
        "require_fp2": require_fp2,
        "video_teacher_enabled": video_teacher_enabled,
        "audio_teacher_enabled": audio_teacher_enabled,
    }


PROGRAMS: dict[str, dict[str, Any]] = {
    "train_empty_room": _program(
        program_id="train_empty_room",
        title="Atomic: empty_room",
        summary="Короткий negative clip без человека. Канонический training capture для occupancy baseline.",
        mode="train_atomic",
        stage=1,
        recommended_order=1.0,
        default_label_prefix="train_empty_room",
        expected_duration_sec=20,
        tags=["train_atomic", "empty", "occupancy"],
        scenario="occupancy",
        step_name="empty_room",
        label_name="empty_room",
        prompt="Выйди из гаража и оставь walkable-зону пустой.",
        person_count_expected=0,
        steps=[{"name": "empty_room", "seconds": 15, "prompt": "Выйди из гаража и оставь walkable-зону пустой"}],
    ),
    "train_quiet_static": _program(
        program_id="train_quiet_static",
        title="Atomic: quiet_static",
        summary="Короткий неподвижный clip для quiet/static anchor и breathing/occupancy разделения.",
        mode="train_atomic",
        stage=1,
        recommended_order=1.1,
        default_label_prefix="train_quiet_static",
        expected_duration_sec=24,
        tags=["train_atomic", "quiet_static", "breathing", "occupancy"],
        scenario="breathing",
        step_name="quiet_static",
        label_name="quiet_static",
        prompt="Стой спокойно, дыши ровно и тихо, без лишних движений.",
        person_count_expected=1,
        steps=[{"name": "quiet_static", "seconds": 18, "prompt": "Стой спокойно, дыши ровно и тихо"}],
    ),
    "train_normal_breath": _program(
        program_id="train_normal_breath",
        title="Atomic: normal_breath",
        summary="Короткий clip спокойного дыхания без жестов и перестроений позы.",
        mode="train_atomic",
        stage=1,
        recommended_order=1.2,
        default_label_prefix="train_normal_breath",
        expected_duration_sec=26,
        tags=["train_atomic", "breathing", "normal"],
        scenario="breathing",
        step_name="normal_breath",
        label_name="normal_breath",
        prompt="Стой спокойно и дыши естественно, без глубоких вдохов.",
        person_count_expected=1,
        steps=[{"name": "normal_breath", "seconds": 20, "prompt": "Стой спокойно и дыши естественно"}],
    ),
    "train_deep_breath": _program(
        program_id="train_deep_breath",
        title="Atomic: deep_breath",
        summary="Короткий clip глубокого дыхания без смены положения тела.",
        mode="train_atomic",
        stage=1,
        recommended_order=1.3,
        default_label_prefix="train_deep_breath",
        expected_duration_sec=26,
        tags=["train_atomic", "breathing", "deep"],
        scenario="breathing",
        step_name="deep_breath",
        label_name="deep_breath",
        prompt="Стой спокойно и дыши глубже обычного, но без движений корпусом.",
        person_count_expected=1,
        steps=[{"name": "deep_breath", "seconds": 20, "prompt": "Дыши глубже обычного без движений корпусом"}],
    ),
    "train_left_shift": _program(
        program_id="train_left_shift",
        title="Atomic: left_shift",
        summary="Одно короткое контролируемое смещение влево внутри walkable-зоны.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.0,
        default_label_prefix="train_left_shift",
        expected_duration_sec=20,
        tags=["train_atomic", "motion", "shift"],
        scenario="gross_motion",
        step_name="left_shift",
        label_name="left_shift",
        prompt="Сместись влево на один короткий шаг и замри.",
        person_count_expected=1,
        steps=[{"name": "left_shift", "seconds": 12, "prompt": "Сместись влево на один короткий шаг и замри"}],
    ),
    "train_right_shift": _program(
        program_id="train_right_shift",
        title="Atomic: right_shift",
        summary="Одно короткое контролируемое смещение вправо внутри walkable-зоны.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.1,
        default_label_prefix="train_right_shift",
        expected_duration_sec=20,
        tags=["train_atomic", "motion", "shift"],
        scenario="gross_motion",
        step_name="right_shift",
        label_name="right_shift",
        prompt="Сместись вправо на один короткий шаг и замри.",
        person_count_expected=1,
        steps=[{"name": "right_shift", "seconds": 12, "prompt": "Сместись вправо на один короткий шаг и замри"}],
    ),
    "train_step_forward": _program(
        program_id="train_step_forward",
        title="Atomic: step_forward",
        summary="Один короткий шаг вперёд к датчику и пауза.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.2,
        default_label_prefix="train_step_forward",
        expected_duration_sec=20,
        tags=["train_atomic", "motion", "step"],
        scenario="gross_motion",
        step_name="step_forward",
        label_name="step_forward",
        prompt="Сделай один короткий шаг вперёд и замри.",
        person_count_expected=1,
        steps=[{"name": "step_forward", "seconds": 12, "prompt": "Сделай один короткий шаг вперёд и замри"}],
    ),
    "train_step_back": _program(
        program_id="train_step_back",
        title="Atomic: step_back",
        summary="Один короткий шаг назад от датчика и пауза.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.3,
        default_label_prefix="train_step_back",
        expected_duration_sec=20,
        tags=["train_atomic", "motion", "step"],
        scenario="gross_motion",
        step_name="step_back",
        label_name="step_back",
        prompt="Сделай один короткий шаг назад и замри.",
        person_count_expected=1,
        steps=[{"name": "step_back", "seconds": 12, "prompt": "Сделай один короткий шаг назад и замри"}],
    ),
    "train_sit_down": _program(
        program_id="train_sit_down",
        title="Atomic: sit_down",
        summary="Одна короткая контролируемая посадка.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.4,
        default_label_prefix="train_sit_down",
        expected_duration_sec=22,
        tags=["train_atomic", "transition", "sit"],
        scenario="transition",
        step_name="sit_down",
        label_name="sit_down",
        prompt="Из стойки медленно сядь и замри в конце.",
        person_count_expected=1,
        steps=[{"name": "sit_down", "seconds": 14, "prompt": "Медленно сядь и замри в конце"}],
    ),
    "train_stand_up": _program(
        program_id="train_stand_up",
        title="Atomic: stand_up",
        summary="Один короткий подъём из сидячего положения.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.5,
        default_label_prefix="train_stand_up",
        expected_duration_sec=22,
        tags=["train_atomic", "transition", "stand"],
        scenario="transition",
        step_name="stand_up",
        label_name="stand_up",
        prompt="Из сидячего положения медленно встань и замри.",
        person_count_expected=1,
        steps=[{"name": "stand_up", "seconds": 14, "prompt": "Медленно встань и замри"}],
    ),
    "train_bend_once": _program(
        program_id="train_bend_once",
        title="Atomic: bend_once",
        summary="Один короткий наклон без ходьбы.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.6,
        default_label_prefix="train_bend_once",
        expected_duration_sec=20,
        tags=["train_atomic", "motion", "bend"],
        scenario="gross_motion",
        step_name="bend_once",
        label_name="bend_once",
        prompt="Один раз наклонись и вернись в стойку.",
        person_count_expected=1,
        steps=[{"name": "bend_once", "seconds": 12, "prompt": "Один раз наклонись и вернись в стойку"}],
    ),
    "train_walk_short": _program(
        program_id="train_walk_short",
        title="Atomic: walk_short",
        summary="Короткая проходка только по разрешённой L-зоне.",
        mode="train_atomic",
        stage=2,
        recommended_order=2.7,
        default_label_prefix="train_walk_short",
        expected_duration_sec=24,
        tags=["train_atomic", "motion", "walk"],
        scenario="gross_motion",
        step_name="walk_short",
        label_name="walk_short",
        prompt="Сделай короткую проходку по разрешённой L-зоне и остановись.",
        person_count_expected=1,
        steps=[{"name": "walk_short", "seconds": 16, "prompt": "Сделай короткую проходку по L-зоне и остановись"}],
    ),
    "pack_breathing": _program(
        program_id="pack_breathing",
        title="Starter Pack: breathing",
        summary="Набор коротких atomic clips для breathing: quiet_static, normal_breath, deep_breath, quiet_static.",
        mode="train_atomic",
        stage=3,
        recommended_order=3.0,
        default_label_prefix="pack_breathing",
        expected_duration_sec=96,
        tags=["starter_pack", "train_atomic", "breathing"],
        pack_id="breathing_pack",
        scenario="breathing",
        steps=[
            {"name": "quiet_static_pre", "seconds": 15, "prompt": "Стой спокойно и дыши тихо"},
            {"name": "normal_breath", "seconds": 20, "prompt": "Дыши естественно"},
            {"name": "deep_breath", "seconds": 20, "prompt": "Дыши глубже обычного"},
            {"name": "quiet_static_post", "seconds": 15, "prompt": "Снова стой спокойно и дыши тихо"},
        ],
    ),
    "pack_occupancy": _program(
        program_id="pack_occupancy",
        title="Starter Pack: occupancy",
        summary="Набор коротких clips для occupancy: empty_room, quiet_static, empty_room.",
        mode="train_atomic",
        stage=3,
        recommended_order=3.1,
        default_label_prefix="pack_occupancy",
        expected_duration_sec=72,
        tags=["starter_pack", "train_atomic", "occupancy"],
        pack_id="occupancy_pack",
        scenario="occupancy",
        steps=[
            {"name": "empty_room_pre", "seconds": 15, "prompt": "Оставь walkable-зону пустой"},
            {"name": "quiet_static", "seconds": 18, "prompt": "Стой спокойно в зоне"},
            {"name": "empty_room_post", "seconds": 15, "prompt": "Снова оставь walkable-зону пустой"},
        ],
    ),
    "pack_motion_micro": _program(
        program_id="pack_motion_micro",
        title="Starter Pack: motion micro",
        summary="Набор коротких micro-motion clips без длинных смешанных сценариев.",
        mode="train_atomic",
        stage=3,
        recommended_order=3.2,
        default_label_prefix="pack_motion_micro",
        expected_duration_sec=102,
        tags=["starter_pack", "train_atomic", "motion"],
        pack_id="motion_micro_pack",
        scenario="gross_motion",
        steps=[
            {"name": "quiet_static", "seconds": 10, "prompt": "Короткая статика"},
            {"name": "left_shift", "seconds": 12, "prompt": "Сместись влево"},
            {"name": "right_shift", "seconds": 12, "prompt": "Сместись вправо"},
            {"name": "step_forward", "seconds": 12, "prompt": "Шаг вперёд"},
            {"name": "step_back", "seconds": 12, "prompt": "Шаг назад"},
            {"name": "bend_once", "seconds": 10, "prompt": "Один наклон"},
            {"name": "walk_short", "seconds": 16, "prompt": "Короткая проходка"},
        ],
    ),
    "eval_breathing_cycle": _program(
        program_id="eval_breathing_cycle",
        title="Eval Scenario: breathing cycle",
        summary="Короткий evaluation-ready сценарий для breathing без хаотичных миксов.",
        mode="eval_scenario",
        stage=4,
        recommended_order=4.0,
        default_label_prefix="eval_breathing_cycle",
        expected_duration_sec=100,
        tags=["eval_scenario", "breathing", "validation"],
        pack_id="breathing_eval_cycle",
        scenario="breathing_eval",
        steps=[
            {"name": "quiet_static", "seconds": 15, "prompt": "Тихая статика"},
            {"name": "normal_breath", "seconds": 20, "prompt": "Обычное дыхание"},
            {"name": "deep_breath", "seconds": 20, "prompt": "Глубокое дыхание"},
            {"name": "walk_short", "seconds": 15, "prompt": "Короткая проходка"},
            {"name": "quiet_static_end", "seconds": 15, "prompt": "Финальная тихая статика"},
        ],
    ),
    "compare_short_walk": _program(
        program_id="compare_short_walk",
        title="Compare: short walk",
        summary="Короткий compare clip для CSI vs FP2 по разрешённой L-зоне. FP2 включается только на время записи.",
        mode="compare",
        stage=5,
        recommended_order=5.0,
        default_label_prefix="compare_short_walk",
        expected_duration_sec=26,
        tags=["compare", "fp2_reference", "motion"],
        scenario="gross_motion_compare",
        step_name="walk_short_compare",
        label_name="walk_short",
        prompt="Сделай короткую проходку по разрешённой L-зоне и остановись.",
        person_count_expected=1,
        require_fp2=True,
        steps=[{"name": "walk_short_compare", "seconds": 16, "prompt": "Короткая проходка по L-зоне"}],
    ),
    "teacher_quiet_static_video": _program(
        program_id="teacher_quiet_static_video",
        title="Teacher: quiet_static + laptop video",
        summary="Atomic clip тихой статики с optional video/audio teacher с ноутбука. Не является runtime path.",
        mode="teacher_capture",
        stage=6,
        recommended_order=6.0,
        default_label_prefix="teacher_quiet_static_video",
        expected_duration_sec=24,
        tags=["teacher_capture", "video_teacher", "breathing"],
        scenario="breathing_teacher",
        step_name="quiet_static_teacher",
        label_name="quiet_static",
        prompt="Стой спокойно и дыши тихо для короткой teacher-записи.",
        person_count_expected=1,
        video_teacher_enabled=True,
        steps=[{"name": "quiet_static_teacher", "seconds": 18, "prompt": "Стой спокойно и дыши тихо"}],
    ),
    "rebuild_baselines": _program(
        program_id="rebuild_baselines",
        title="Пересчитать baseline",
        summary="Пересобирает leakage-safe baseline suite и обновляет сводный report в docs.",
        stage=7,
        recommended_order=7.0,
        expected_duration_sec=10,
        tags=["analysis", "models", "report"],
        script="suite",
        mode=None,
        type_="analysis",
    ),
}


class TrainingRunStartRequest(BaseModel):
    program_id: str = Field(..., description="Program identifier from catalog.")
    space_id: str | None = Field(default=None, description="Persistent space identifier.")
    label_prefix: str | None = Field(default=None, description="Optional custom label prefix.")
    countdown_sec: int = Field(default=5, ge=0, le=30)
    enable_voice: bool = Field(default=True)
    raw_user_description: str | None = Field(default=None, description="Optional free-form user description for manifest.")
    notes: str | None = Field(default=None, description="Optional operator notes for manifest.")
    video_teacher_enabled: bool = Field(default=False)
    audio_teacher_enabled: bool = Field(default=False)
    require_fp2: bool | None = Field(default=None, description="Optional override for FP2 requirement.")


class TrainingSpaceSelectRequest(BaseModel):
    space_id: str = Field(..., description="Persistent space identifier.")


class LiveCSICaptureRequest(BaseModel):
    label: str = Field(..., description="Capture label for output files.")
    duration_sec: float = Field(..., gt=0.5, le=180.0)
    out_dir: str | None = Field(default=None, description="Optional output directory override.")


class VideoTeacherAnnotationsSaveRequest(BaseModel):
    recording_label: str = Field(..., description="Recording label.")
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    review_output_dir: str | None = None
    is_gold: bool | None = None


def _program_catalog() -> list[dict[str, Any]]:
    return [
        {
            **program,
            "steps": list(program.get("steps", [])),
        }
        for program in sorted(PROGRAMS.values(), key=lambda item: item["recommended_order"])
    ]


def _space_prefix(space: dict[str, Any]) -> str:
    return _slugify(space.get("capture_prefix") or space.get("id") or "space")


def _space_by_id(space_id: str, spaces: list[dict[str, Any]]) -> dict[str, Any] | None:
    for space in spaces:
        if str(space.get("id")) == str(space_id):
            return space
    return None


def _serialize_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    now_ts = datetime.now(timezone.utc).timestamp()
    started_ts = run.get("started_timestamp")
    expected = run.get("expected_duration_sec")
    progress = run.get("progress_value")
    if progress is None and expected and started_ts:
        progress = min(1.0, max(0.0, (now_ts - started_ts) / expected))

    return {
        "id": run["id"],
        "space_id": run.get("space_id"),
        "space_name": run.get("space_name"),
        "program_id": run["program_id"],
        "program_title": run["program_title"],
        "program_type": run["program_type"],
        "status": run["status"],
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "label_prefix": run.get("label_prefix"),
        "countdown_sec": run.get("countdown_sec"),
        "enable_voice": run.get("enable_voice"),
        "capture_mode": run.get("capture_mode"),
        "pack_id": run.get("pack_id"),
        "require_fp2": run.get("require_fp2"),
        "video_teacher_enabled": run.get("video_teacher_enabled"),
        "audio_teacher_enabled": run.get("audio_teacher_enabled"),
        "expected_duration_sec": expected,
        "progress": round(progress, 4) if progress is not None else None,
        "current_step_index": run.get("current_step_index"),
        "current_step_name": run.get("current_step_name"),
        "current_prompt": run.get("current_prompt"),
        "latest_capture_label": run.get("latest_capture_label"),
        "pid": run.get("pid"),
        "return_code": run.get("return_code"),
        "logs": list(run.get("logs", [])),
        "artifacts": list(run.get("artifacts", [])),
        "error": run.get("error"),
    }


def _serialize_run_summary(run: dict[str, Any] | None) -> dict[str, Any] | None:
    public = _serialize_run(run)
    if public is None:
        return None
    public["logs"] = []
    public["artifacts"] = []
    public["current_prompt"] = None
    public["current_step_name"] = None
    public["current_step_index"] = None
    public["latest_capture_label"] = None
    public["progress"] = None
    return public


def _discover_capture_artifacts(label_prefix: str) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    manifest_path = _CAPTURES_DIR / f"{label_prefix}.manifest.json"
    if manifest_path.exists():
        artifacts.append({"kind": "manifest", "path": str(manifest_path)})
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = None
        if isinstance(manifest, dict):
            if isinstance(manifest.get("clips"), list):
                for clip in manifest.get("clips", []):
                    if not isinstance(clip, dict):
                        continue
                    for field_name, kind in [
                        ("manifest_file", "clip_manifest"),
                        ("capture_file", "capture"),
                        ("summary_file", "summary"),
                        ("teacher_fp2_file", "teacher_fp2"),
                        ("video_file", "video"),
                        ("video_teacher_manifest_file", "video_teacher_manifest"),
                        ("video_teacher_annotations_file", "video_teacher_annotations"),
                        ("audio_file", "audio"),
                    ]:
                        path_value = clip.get(field_name)
                        if path_value:
                            artifacts.append({"kind": kind, "path": str(path_value), "label": clip.get("capture_label")})
            for step in manifest.get("steps", []):
                label = step.get("label")
                if not label:
                    continue
                for path in sorted(_CAPTURES_DIR.glob(f"*_{label}.ndjson.gz"))[-1:]:
                    artifacts.append({"kind": "capture", "path": str(path), "label": label})
                for path in sorted(_CAPTURES_DIR.glob(f"*_{label}.summary.json"))[-1:]:
                    artifacts.append({"kind": "summary", "path": str(path), "label": label})
                for path in sorted(_CAPTURES_DIR.glob(f"*_{label}.compare.ndjson.gz"))[-1:]:
                    artifacts.append({"kind": "compare", "path": str(path), "label": label})
                for path in sorted(_CAPTURES_DIR.glob(f"*_{label}.compare.summary.json"))[-1:]:
                    artifacts.append({"kind": "compare_summary", "path": str(path), "label": label})
    return artifacts


def _analysis_artifacts() -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in [
        _DOCS_DIR / "LEAKAGE_SAFE_BASELINE_SUITE_2026-03-10.md",
        _DOCS_DIR / "LEAKAGE_SAFE_BASELINE_SUITE_2026-03-10.json",
        _MODELS_DIR / "breathing_feature_ablation_tuned_2026-03-10.md",
        _MODELS_DIR / "breathing_feature_ablation_tuned_2026-03-10.json",
        _MODELS_DIR / "breathing_feature_ablation_tuned_2026-03-10.ranking.csv",
    ]:
        if path.exists():
            artifacts.append({"kind": "report", "path": str(path)})
    return artifacts


def _latest_artifact_mtime(artifacts: list[dict[str, Any]]) -> float | None:
    latest: float | None = None
    for artifact in artifacts:
        path_value = artifact.get("path")
        if not path_value:
            continue
        path = Path(str(path_value))
        if not path.exists():
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        latest = mtime if latest is None else max(latest, mtime)
    return latest


def _resolve_review_output_dir(recording_label: str, review_output_dir: str | None) -> Path:
    if review_output_dir:
        path = Path(review_output_dir).expanduser().resolve()
        if _GUIDED_REVIEW_DIR not in path.parents and path != _GUIDED_REVIEW_DIR:
            raise HTTPException(status_code=400, detail="review_output_dir outside allowed review directory")
        return path
    if not _GUIDED_REVIEW_DIR.exists():
        raise HTTPException(status_code=404, detail="review directory not found")
    matches: list[Path] = []
    for viewer_data_path in _GUIDED_REVIEW_DIR.rglob("viewer_data.json"):
        try:
            payload = json.loads(viewer_data_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(payload.get("recording_label")) == recording_label:
            matches.append(viewer_data_path.parent)
    if not matches:
        raise HTTPException(status_code=404, detail="review session not found")
    return matches[0]


def _save_annotations_db(
    *,
    recording_label: str,
    output_dir: Path,
    annotations: list[dict[str, Any]],
    is_gold: bool,
) -> Path:
    db_path = _GUIDED_REVIEW_DIR / "annotations.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_teacher_annotations (
                recording_label TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                annotations_count INTEGER NOT NULL,
                output_dir TEXT NOT NULL,
                is_gold INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL
            )
            """
        )
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(video_teacher_annotations)")}
        except sqlite3.Error:
            columns = set()
        if "is_gold" not in columns:
            conn.execute("ALTER TABLE video_teacher_annotations ADD COLUMN is_gold INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            INSERT INTO video_teacher_annotations
            (recording_label, updated_at, annotations_count, output_dir, is_gold, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(recording_label) DO UPDATE SET
                updated_at=excluded.updated_at,
                annotations_count=excluded.annotations_count,
                output_dir=excluded.output_dir,
                is_gold=excluded.is_gold,
                payload_json=excluded.payload_json
            """,
            (
                recording_label,
                _utc_now_iso(),
                len(annotations),
                str(output_dir),
                1 if is_gold else 0,
                json.dumps(
                    {
                        "recording_label": recording_label,
                        "annotations": annotations,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _pid_alive(pid: Any) -> bool:
    if pid in {None, "", 0}:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def _run_artifacts(run: dict[str, Any]) -> list[dict[str, Any]]:
    if run.get("program_type") == "capture" and run.get("label_prefix"):
        return _discover_capture_artifacts(str(run["label_prefix"]))
    if run.get("program_id") == "rebuild_baselines":
        return _analysis_artifacts()
    return list(run.get("artifacts", []))


def _artifacts_indicate_completion(run: dict[str, Any], artifacts: list[dict[str, Any]]) -> bool:
    if not artifacts:
        return False
    started_at = run.get("started_at")
    if not started_at:
        return True
    try:
        started_ts = datetime.fromisoformat(str(started_at)).timestamp()
    except ValueError:
        return True
    latest_mtime = _latest_artifact_mtime(artifacts)
    if latest_mtime is None:
        return False
    return latest_mtime >= started_ts - 2


async def _reconcile_stale_recent_runs(
    recent_runs: list[dict[str, Any]],
    training_store: CSITrainingStoreService,
) -> list[dict[str, Any]]:
    changed = False
    for run in recent_runs:
        if run.get("status") != "running":
            continue
        if _pid_alive(run.get("pid")):
            continue

        artifacts = _run_artifacts(run)
        run["artifacts"] = artifacts
        run["finished_at"] = run.get("finished_at") or _utc_now_iso()
        if _artifacts_indicate_completion(run, artifacts):
            run["status"] = "completed"
            run["return_code"] = 0 if run.get("return_code") is None else run.get("return_code")
            if not run.get("logs"):
                run["logs"] = [{"ts": _utc_now_iso(), "stream": "system", "line": "Фоновый прогон завершён; статус восстановлен из артефактов."}]
        else:
            run["status"] = "failed"
            run["error"] = run.get("error") or "Фоновый процесс больше не активен, а завершённые артефакты не найдены."
            if not run.get("logs"):
                run["logs"] = [{"ts": _utc_now_iso(), "stream": "system", "line": "Прогон потерян: активный процесс не найден."}]

        await training_store.save_run(run)
        changed = True

    return recent_runs if not changed else await training_store.list_runs(
        space_id=recent_runs[0].get("space_id") if recent_runs else None,
        limit=len(recent_runs) or 20,
    )


def _build_command(
    program: dict[str, Any],
    request: TrainingRunStartRequest,
    label_prefix: str,
    selected_space: dict[str, Any],
) -> list[str]:
    if program["script"] == "atomic":
        cmd = [
            _SCRIPT_PYTHON,
            "-u",
            str(_SCRIPTS_DIR / "run_atomic_csi_training_capture.py"),
            "--mode",
            str(program["mode"]),
            "--label-prefix",
            label_prefix,
            "--program-id",
            str(program["id"]),
            "--program-title",
            str(program["title"]),
            "--space-id",
            str(selected_space.get("id") or "garage"),
            "--countdown-sec",
            str(request.countdown_sec),
        ]
        if program.get("scenario"):
            cmd.extend(["--scenario", str(program["scenario"])])
        if program.get("pack_id"):
            cmd.extend(["--pack-id", str(program["pack_id"])])
        if program.get("step_name"):
            cmd.extend(["--step-name", str(program["step_name"])])
        if program.get("label_name"):
            cmd.extend(["--label-name", str(program["label_name"])])
        if program.get("prompt"):
            cmd.extend(["--prompt", str(program["prompt"])])
        if program.get("person_count_expected") is not None:
            cmd.extend(["--person-count-expected", str(program["person_count_expected"])])
        steps = program.get("steps") or []
        if len(steps) == 1 and steps[0].get("seconds") is not None:
            cmd.extend(["--duration-sec", str(steps[0]["seconds"])])
        if request.raw_user_description:
            cmd.extend(["--raw-user-description", request.raw_user_description])
        if request.notes:
            cmd.extend(["--notes", request.notes])
        require_fp2 = program.get("require_fp2") if request.require_fp2 is None else bool(request.require_fp2)
        if require_fp2:
            cmd.append("--require-fp2")
        if bool(program.get("video_teacher_enabled")) or request.video_teacher_enabled:
            cmd.append("--video-teacher")
        if bool(program.get("audio_teacher_enabled")) or request.audio_teacher_enabled:
            cmd.append("--audio-teacher")
        if not request.enable_voice:
            cmd.append("--disable-voice")
        return cmd
    if program["script"] == "suite":
        return [
            _SCRIPT_PYTHON,
            "-u",
            str(_SCRIPTS_DIR / "run_leakage_safe_baseline_suite.py"),
        ]
    raise RuntimeError(f"Unsupported program script: {program['script']}")


async def _consume_lines(run: dict[str, Any], stream: asyncio.StreamReader, stream_name: str) -> None:
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        run["logs"].append({"ts": _utc_now_iso(), "stream": stream_name, "line": text})
        if text.startswith("Шаг "):
            match = re.match(r"Шаг\s+(\d+)\.\s*(.+)$", text)
            if match:
                run["current_step_index"] = int(match.group(1))
                run["current_prompt"] = match.group(2)
        elif text.startswith("PROGRESS "):
            match = re.match(r"PROGRESS\s+(\d+)/(\d+):\s*(.+)$", text)
            if match:
                current = int(match.group(1))
                total = max(1, int(match.group(2)))
                run["progress_value"] = min(1.0, max(0.0, current / total))
                run["current_step_index"] = current
                run["current_step_name"] = match.group(3)
                run["current_prompt"] = match.group(3)
        elif text.startswith("Запускаю запись "):
            match = re.match(r"Запускаю запись\s+(.+?)\s+на\s+(\d+)\s+секунд", text)
            if match:
                run["latest_capture_label"] = match.group(1)
        elif text.startswith("Запускаю сравнение "):
            match = re.match(r"Запускаю сравнение\s+(.+?)\s+на\s+(\d+)\s+секунд", text)
            if match:
                run["latest_capture_label"] = match.group(1)
        elif text.startswith("manifest: "):
            run["artifacts"].append({"kind": "manifest", "path": text.split(": ", 1)[1]})
        elif re.match(r"^(capture|summary|teacher_fp2|video|audio|clip_manifest|video_teacher_manifest|video_teacher_annotations):\s+", text):
            kind, path = text.split(":", 1)
            run["artifacts"].append({"kind": kind.strip(), "path": path.strip()})
        elif re.match(r"^(json|md|csv):\s+", text):
            kind, path = text.split(":", 1)
            run["artifacts"].append({"kind": kind.strip(), "path": path.strip()})


async def _wait_for_completion(
    run: dict[str, Any],
    process: asyncio.subprocess.Process,
    training_store: CSITrainingStoreService,
) -> None:
    global _ACTIVE_RUN

    return_code = await process.wait()
    run["return_code"] = return_code
    run["finished_at"] = _utc_now_iso()
    run["status"] = "completed" if return_code == 0 else "failed"
    run["progress_value"] = 1.0 if return_code == 0 else run.get("progress_value")
    if return_code != 0 and not run.get("error"):
        run["error"] = f"Process exited with code {return_code}"

    if run["program_type"] == "capture" and run.get("label_prefix"):
        run["artifacts"] = _discover_capture_artifacts(run["label_prefix"])
    elif run["program_id"] == "rebuild_baselines":
        run["artifacts"] = _analysis_artifacts()

    public_copy = _serialize_run(run)
    if public_copy is not None:
        _RUN_HISTORY.appendleft(public_copy)
        await training_store.save_run(public_copy)

    async with _RUN_LOCK:
        if _ACTIVE_RUN and _ACTIVE_RUN.get("id") == run["id"]:
            _ACTIVE_RUN = None


@router.get("/catalog")
async def training_catalog(
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    available, reason = _local_execution_available()
    await training_store.ensure_backfilled()
    space_state = await training_store.list_spaces_with_stats()
    return {
        "local_execution_available": available,
        "reason": reason,
        "programs": _program_catalog(),
        "active_space_id": space_state["active_space_id"],
        "spaces": space_state["spaces"],
    }


@router.get("/status")
async def training_status(
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    available, reason = _local_execution_available()
    space_state = await training_store.list_spaces_with_stats()
    active_space_id = space_state["active_space_id"]
    recent_runs = await training_store.list_runs(space_id=active_space_id, limit=20)
    if _ACTIVE_RUN is None and recent_runs:
        recent_runs = await _reconcile_stale_recent_runs(recent_runs, training_store)
        space_state = await training_store.list_spaces_with_stats()
        active_space_id = space_state["active_space_id"]
    return {
        "local_execution_available": available,
        "reason": reason,
        "active_run": _serialize_run(_ACTIVE_RUN),
        "recent_runs": [item for item in (_serialize_run_summary(run) for run in recent_runs) if item is not None],
        "active_space_id": active_space_id,
        "spaces": space_state["spaces"],
    }


@router.get("/spaces")
async def training_spaces(
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    return await training_store.list_spaces_with_stats()


@router.post("/capture/live-csi")
async def capture_live_csi_clip(
    payload: LiveCSICaptureRequest,
    hardware_service: HardwareService = Depends(get_hardware_service_from_request),
) -> dict[str, Any]:
    available, reason = _local_execution_available()
    if not available:
        raise HTTPException(status_code=409, detail=reason)
    try:
        summary = await hardware_service.record_live_csi_capture(
            label=_slugify(payload.label),
            duration_sec=payload.duration_sec,
            out_dir=payload.out_dir,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "ok": True,
        "capture": summary,
    }


@router.post("/spaces/active")
async def set_active_training_space(
    payload: TrainingSpaceSelectRequest,
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    space_state = await training_store.list_spaces_with_stats()
    selected_space = _space_by_id(payload.space_id, space_state["spaces"])
    if not selected_space:
        raise HTTPException(status_code=404, detail=f"Unknown space_id: {payload.space_id}")
    await training_store.set_active_space_id(selected_space["id"])
    updated_state = await training_store.list_spaces_with_stats()
    return {
        "active_space_id": updated_state["active_space_id"],
        "spaces": updated_state["spaces"],
    }


@router.post("/runs")
async def start_training_run(
    payload: TrainingRunStartRequest,
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    global _ACTIVE_RUN

    available, reason = _local_execution_available()
    if not available:
        raise HTTPException(status_code=409, detail=reason)

    program = PROGRAMS.get(payload.program_id)
    if not program:
        raise HTTPException(status_code=404, detail=f"Unknown program_id: {payload.program_id}")

    space_state = await training_store.list_spaces_with_stats()
    resolved_space_id = payload.space_id or space_state["active_space_id"]
    selected_space = _space_by_id(resolved_space_id, space_state["spaces"])
    if not selected_space:
        raise HTTPException(status_code=404, detail=f"Unknown space_id: {resolved_space_id}")

    async with _RUN_LOCK:
        if _ACTIVE_RUN and _ACTIVE_RUN.get("status") in {"starting", "running"}:
            raise HTTPException(status_code=409, detail="Another local training run is already active.")

        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_prefix = program.get("default_label_prefix") or program["id"]
        custom_suffix = payload.label_prefix.strip() if payload.label_prefix else ""
        base_prefix = custom_suffix or default_prefix
        label_prefix = _slugify(f"{_space_prefix(selected_space)}_{base_prefix}_{suffix}")
        command = _build_command(program, payload, label_prefix, selected_space)

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(_PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        run = {
            "id": uuid.uuid4().hex[:12],
            "space_id": selected_space["id"],
            "space_name": selected_space["name"],
            "program_id": program["id"],
            "program_title": program["title"],
            "program_type": program["type"],
            "status": "running",
            "started_at": _utc_now_iso(),
            "started_timestamp": datetime.now(timezone.utc).timestamp(),
            "finished_at": None,
            "label_prefix": label_prefix if program["type"] == "capture" else None,
            "countdown_sec": payload.countdown_sec,
            "enable_voice": payload.enable_voice,
            "capture_mode": program.get("mode"),
            "pack_id": program.get("pack_id"),
            "require_fp2": program.get("require_fp2") if payload.require_fp2 is None else bool(payload.require_fp2),
            "video_teacher_enabled": bool(program.get("video_teacher_enabled")) or payload.video_teacher_enabled,
            "audio_teacher_enabled": bool(program.get("audio_teacher_enabled")) or payload.audio_teacher_enabled,
            "expected_duration_sec": program.get("expected_duration_sec"),
            "current_step_index": None,
            "current_step_name": None,
            "current_prompt": None,
            "latest_capture_label": None,
            "pid": process.pid,
            "return_code": None,
            "logs": deque(maxlen=80),
            "artifacts": [],
            "error": None,
            "command": command,
        }
        _ACTIVE_RUN = run
        await training_store.set_active_space_id(selected_space["id"])

        asyncio.create_task(_consume_lines(run, process.stdout, "stdout"))
        asyncio.create_task(_consume_lines(run, process.stderr, "stderr"))
        asyncio.create_task(_wait_for_completion(run, process, training_store))

    serialized = _serialize_run(run)
    if serialized is not None:
        await training_store.save_run(serialized)

    return {"run": serialized}


@router.get("/runs/current")
async def current_training_run(
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    await training_store.ensure_backfilled()
    return {"run": _serialize_run(_ACTIVE_RUN)}


@router.get("/runs/{run_id}")
async def training_run_details(
    run_id: str,
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    await training_store.ensure_backfilled()
    run = await training_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}")
    if run.get("status") == "running" and not _pid_alive(run.get("pid")):
        reconciled = await _reconcile_stale_recent_runs([run], training_store)
        run = reconciled[0] if reconciled else run
    return {"run": _serialize_run(run)}


@router.get("/runs/{run_id}/viewer")
async def training_run_viewer(
    run_id: str,
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    await training_store.ensure_backfilled()
    run = await training_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Unknown run_id: {run_id}")
    if run.get("status") == "running":
        return {
            "run_id": run_id,
            "viewer": {
                "available": False,
                "reason": "Viewer будет доступен после завершения записи.",
            },
        }
    if str(run.get("program_id") or "").startswith("compare_"):
        return {
            "run_id": run_id,
            "viewer": {
                "available": False,
                "reason": "Для compare-прогонов основной результат лежит в compare.summary.json и compare.ndjson.gz.",
            },
        }
    try:
        viewer = await asyncio.to_thread(build_run_viewer, run)
    except FileNotFoundError as exc:
        viewer = {
            "available": False,
            "reason": str(exc),
        }
    except Exception as exc:
        logger.exception("Failed to build run viewer for %s", run_id)
        viewer = {
            "available": False,
            "reason": f"Viewer generation failed: {exc}",
        }
    return {"run_id": run_id, "viewer": viewer}


@router.post("/video_teacher_annotations/save")
async def save_video_teacher_annotations(payload: VideoTeacherAnnotationsSaveRequest) -> dict[str, Any]:
    available, reason = _local_execution_available()
    if not available:
        raise HTTPException(status_code=400, detail=reason)
    output_dir = _resolve_review_output_dir(payload.recording_label, payload.review_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_gold = False
    existing_path = output_dir / "manual_annotations_v1.json"
    if existing_path.exists():
        try:
            existing_payload = json.loads(existing_path.read_text(encoding="utf-8"))
            existing_gold = bool(existing_payload.get("gold_standard"))
        except Exception:
            existing_gold = False
    is_gold = existing_gold if payload.is_gold is None else bool(payload.is_gold)
    out_path = output_dir / "manual_annotations_v1.json"
    out_path.write_text(
        json.dumps(
            {
                "recording_label": payload.recording_label,
                "annotations": payload.annotations,
                "gold_standard": is_gold,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    db_path = _save_annotations_db(
        recording_label=payload.recording_label,
        output_dir=output_dir,
        annotations=payload.annotations,
        is_gold=is_gold,
    )
    return {
        "status": "ok",
        "recording_label": payload.recording_label,
        "annotations_count": len(payload.annotations),
        "is_gold": is_gold,
        "output_dir": str(output_dir),
        "file_path": str(out_path),
        "db_path": str(db_path),
    }


@router.post("/runs/current/stop")
async def stop_current_training_run(
    training_store: CSITrainingStoreService = Depends(get_csi_training_store_service),
) -> dict[str, Any]:
    global _ACTIVE_RUN

    async with _RUN_LOCK:
        if not _ACTIVE_RUN or _ACTIVE_RUN.get("status") not in {"starting", "running"}:
            raise HTTPException(status_code=404, detail="No active training run.")
        pid = _ACTIVE_RUN.get("pid")
        if pid is None:
            raise HTTPException(status_code=500, detail="Active run has no process id.")
        try:
            os.kill(pid, 15)
        except ProcessLookupError as exc:
            raise HTTPException(status_code=404, detail="Active process no longer exists.") from exc
        _ACTIVE_RUN["status"] = "stopping"
        _ACTIVE_RUN["error"] = "Stopped by user request"
        serialized = _serialize_run(_ACTIVE_RUN)
        if serialized is not None:
            await training_store.save_run(serialized)
        return {"run": serialized}
