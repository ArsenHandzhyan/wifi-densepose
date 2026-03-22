"""
Fast local persistence for CSI training runs.

Uses a dedicated local SQLite database plus a mirrored JSON registry file.
This keeps the training console independent from any remote/shared database and
matches the local-first workflow for guided CSI capture.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config.settings import Settings

logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class CSITrainingStoreService:
    _ACTIVE_SPACE_KEY = "active_space_id"
    _BACKFILL_MARKER_KEY = "capture_backfill_v4"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._schema_ready = False
        self._backfill_done = False
        self._capture_dir = (_PROJECT_ROOT / self.settings.temp_storage_path).resolve() / "captures"
        self._room_layout_dir = (_PROJECT_ROOT / self.settings.data_storage_path).resolve() / "room-layouts"
        self._file_fallback_path = (_PROJECT_ROOT / self.settings.data_storage_path).resolve() / "csi_training_registry.json"
        self._sqlite_path = (_PROJECT_ROOT / self.settings.data_storage_path).resolve() / "csi_training_registry.sqlite3"

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _connect(self) -> sqlite3.Connection:
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        def _init() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS csi_training_state (
                        key TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS csi_training_runs (
                        run_id TEXT PRIMARY KEY,
                        space_id TEXT NOT NULL,
                        space_name TEXT NOT NULL,
                        program_id TEXT NOT NULL,
                        program_title TEXT NOT NULL,
                        program_type TEXT NOT NULL,
                        label_prefix TEXT,
                        status TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_csi_training_runs_space_started
                    ON csi_training_runs (space_id, started_at DESC)
                    """
                )
                conn.commit()

        await asyncio.to_thread(_init)
        self._schema_ready = True

    def _read_file_state(self) -> dict[str, Any]:
        if not self._file_fallback_path.exists():
            return {"state": {}, "runs": {}}
        try:
            payload = json.loads(self._file_fallback_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("state", {})
                payload.setdefault("runs", {})
                return payload
        except Exception as exc:
            logger.warning("Failed to read CSI training registry %s: %s", self._file_fallback_path, exc)
        return {"state": {}, "runs": {}}

    def _write_file_state(self, state: dict[str, Any]) -> None:
        try:
            self._file_fallback_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_fallback_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to write CSI training registry %s: %s", self._file_fallback_path, exc)

    def _mirror_state_to_file(self, key: str, payload: dict[str, Any]) -> None:
        root = self._read_file_state()
        state = root.get("state") if isinstance(root.get("state"), dict) else {}
        state[key] = payload
        root["state"] = state
        self._write_file_state(root)

    def _mirror_run_to_file(self, run: dict[str, Any]) -> None:
        root = self._read_file_state()
        runs = root.get("runs") if isinstance(root.get("runs"), dict) else {}
        runs[run["id"]] = run
        root["runs"] = runs
        self._write_file_state(root)

    def _mirror_all_runs_to_file(self, runs_payload: list[dict[str, Any]]) -> None:
        root = self._read_file_state()
        root["runs"] = {
            str(run["id"]): run
            for run in runs_payload
            if isinstance(run, dict) and run.get("id")
        }
        self._write_file_state(root)

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "").strip().lower())
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or "space"

    def _canonical_space_id(self, candidate: str, name: str | None = None) -> str:
        raw = f"{candidate or ''} {name or ''}".lower()
        if "гараж" in raw or "garage" in raw:
            return "garage"
        if "комнат" in raw or "room" in raw or "дом" in raw or "home" in raw:
            return "room"
        return self._slugify(name or candidate or "space")

    def _space_capture_prefix(self, space_id: str) -> str:
        if space_id in {"garage", "room"}:
            return space_id
        return self._slugify(space_id)

    def _discover_spaces(self) -> list[dict[str, Any]]:
        spaces: dict[str, dict[str, Any]] = {
            "garage": {
                "id": "garage",
                "name": "Гараж",
                "capture_prefix": "garage",
                "source": "builtin",
                "width_cm": 420,
                "depth_cm": 500,
            },
            "room": {
                "id": "room",
                "name": "Комната",
                "capture_prefix": "room",
                "source": "builtin",
                "width_cm": 460,
                "depth_cm": 380,
            },
        }

        latest_export = None
        try:
            exports = sorted(self._room_layout_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
            latest_export = exports[-1] if exports else None
        except Exception:
            latest_export = None

        if latest_export and latest_export.exists():
            try:
                payload = json.loads(latest_export.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to parse room layout export %s: %s", latest_export, exc)
                payload = {}

            for profile in payload.get("customRoomProfiles", []) or []:
                if not isinstance(profile, dict):
                    continue
                name = str(profile.get("name") or "").strip() or "Пространство"
                space_id = self._canonical_space_id(str(profile.get("id") or ""), name)
                current = spaces.get(space_id, {})
                spaces[space_id] = {
                    "id": space_id,
                    "name": name,
                    "capture_prefix": self._space_capture_prefix(space_id),
                    "source": "layout_export",
                    "profile_id": profile.get("id"),
                    "width_cm": int(profile.get("widthCm") or current.get("width_cm") or 0) or None,
                    "depth_cm": int(profile.get("depthCm") or current.get("depth_cm") or 0) or None,
                    "active_profile_id": payload.get("activeRoomProfileId"),
                }

        return [spaces[key] for key in sorted(spaces.keys())]

    async def _load_state_value(self, key: str) -> Optional[dict[str, Any]]:
        await self.ensure_schema()

        def _read() -> Optional[dict[str, Any]]:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM csi_training_state WHERE key = ?",
                    (key,),
                ).fetchone()
            if row:
                payload = json.loads(row["payload"])
                return payload if isinstance(payload, dict) else None
            return None

        try:
            payload = await asyncio.to_thread(_read)
            if payload:
                self._mirror_state_to_file(key, payload)
                return payload
        except Exception as exc:
            logger.warning("CSI training state read failed, using file mirror: %s", exc)

        state = self._read_file_state().get("state", {})
        payload = state.get(key)
        return payload if isinstance(payload, dict) else None

    async def _save_state_value(self, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_schema()

        def _write() -> None:
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO csi_training_state (key, payload, created_at, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, serialized),
                )
                conn.commit()

        try:
            await asyncio.to_thread(_write)
            self._mirror_state_to_file(key, payload)
            backend = "sqlite_local"
        except Exception as exc:
            logger.warning("CSI training state write failed, using file mirror only: %s", exc)
            self._mirror_state_to_file(key, payload)
            backend = "file_mirror_only"

        return {"key": key, "payload": payload, "storage_backend": backend}

    async def get_active_space_id(self) -> str:
        payload = await self._load_state_value(self._ACTIVE_SPACE_KEY)
        return str((payload or {}).get("space_id") or "garage")

    async def set_active_space_id(self, space_id: str) -> dict[str, Any]:
        return await self._save_state_value(
            self._ACTIVE_SPACE_KEY,
            {"space_id": space_id, "updated_at": self._timestamp()},
        )

    def _normalize_run_record(self, run: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "id": str(run.get("id") or run.get("run_id") or ""),
            "space_id": str(run.get("space_id") or "garage"),
            "space_name": str(run.get("space_name") or "Гараж"),
            "program_id": str(run.get("program_id") or "legacy_capture"),
            "program_title": str(run.get("program_title") or run.get("program_id") or "Архивный захват"),
            "program_type": str(run.get("program_type") or "capture"),
            "status": str(run.get("status") or "completed"),
            "label_prefix": run.get("label_prefix"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "countdown_sec": run.get("countdown_sec"),
            "enable_voice": run.get("enable_voice"),
            "capture_mode": run.get("capture_mode"),
            "pack_id": run.get("pack_id"),
            "require_fp2": run.get("require_fp2"),
            "video_teacher_enabled": run.get("video_teacher_enabled"),
            "audio_teacher_enabled": run.get("audio_teacher_enabled"),
            "expected_duration_sec": run.get("expected_duration_sec"),
            "current_step_index": run.get("current_step_index"),
            "current_step_name": run.get("current_step_name"),
            "current_prompt": run.get("current_prompt"),
            "latest_capture_label": run.get("latest_capture_label"),
            "pid": run.get("pid"),
            "return_code": run.get("return_code"),
            "logs": list(run.get("logs", [])),
            "artifacts": list(run.get("artifacts", [])),
            "error": run.get("error"),
            "import_source": run.get("import_source"),
        }
        if not normalized["id"]:
            raise ValueError("Run record is missing id")
        return normalized

    async def save_run(self, run: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_run_record(run)
        await self.ensure_schema()

        def _write() -> None:
            serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO csi_training_runs (
                        run_id, space_id, space_name, program_id, program_title, program_type,
                        label_prefix, status, started_at, finished_at, payload, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(run_id) DO UPDATE SET
                        space_id = excluded.space_id,
                        space_name = excluded.space_name,
                        program_id = excluded.program_id,
                        program_title = excluded.program_title,
                        program_type = excluded.program_type,
                        label_prefix = excluded.label_prefix,
                        status = excluded.status,
                        started_at = excluded.started_at,
                        finished_at = excluded.finished_at,
                        payload = excluded.payload,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        normalized["id"],
                        normalized["space_id"],
                        normalized["space_name"],
                        normalized["program_id"],
                        normalized["program_title"],
                        normalized["program_type"],
                        normalized["label_prefix"],
                        normalized["status"],
                        normalized["started_at"],
                        normalized["finished_at"],
                        serialized,
                    ),
                )
                conn.commit()

        try:
            await asyncio.to_thread(_write)
            normalized["storage_backend"] = "sqlite_local"
        except Exception as exc:
            logger.warning("CSI training SQLite write failed, using file mirror only: %s", exc)
            normalized["storage_backend"] = "file_mirror_only"

        self._mirror_run_to_file(normalized)
        return normalized

    async def delete_run(self, run_id: str) -> None:
        await self.ensure_schema()

        def _delete() -> None:
            with self._connect() as conn:
                conn.execute("DELETE FROM csi_training_runs WHERE run_id = ?", (run_id,))
                conn.commit()

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:
            logger.warning("CSI training SQLite delete failed for %s: %s", run_id, exc)

        root = self._read_file_state()
        runs = root.get("runs") if isinstance(root.get("runs"), dict) else {}
        if run_id in runs:
            runs.pop(run_id, None)
            root["runs"] = runs
            self._write_file_state(root)

    async def list_runs(self, *, space_id: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        await self.ensure_schema()

        def _read() -> list[dict[str, Any]]:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT payload
                    FROM csi_training_runs
                    ORDER BY COALESCE(started_at, finished_at, created_at) DESC, run_id DESC
                    """
                ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                payload = json.loads(row["payload"])
                if isinstance(payload, dict):
                    result.append(payload)
            return result

        rows: list[dict[str, Any]] = []
        try:
            rows = await asyncio.to_thread(_read)
            if rows:
                self._mirror_all_runs_to_file(rows)
        except Exception as exc:
            logger.warning("CSI training SQLite read failed, using file mirror: %s", exc)

        if not rows:
            runs = self._read_file_state().get("runs", {})
            rows = [value for value in runs.values() if isinstance(value, dict)]

        if space_id:
            rows = [row for row in rows if str(row.get("space_id") or "") == space_id]

        rows.sort(key=lambda item: str(item.get("started_at") or item.get("finished_at") or ""), reverse=True)
        return rows[:limit]

    async def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        await self.ensure_schema()

        def _read() -> Optional[dict[str, Any]]:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT payload FROM csi_training_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            if not row:
                return None
            payload = json.loads(row["payload"])
            return payload if isinstance(payload, dict) else None

        try:
            payload = await asyncio.to_thread(_read)
            if payload:
                return payload
        except Exception as exc:
            logger.warning("CSI training SQLite single-run read failed, using file mirror: %s", exc)

        runs = self._read_file_state().get("runs", {})
        payload = runs.get(run_id) if isinstance(runs, dict) else None
        return payload if isinstance(payload, dict) else None

    def _space_from_label(self, label: str, spaces: list[dict[str, Any]]) -> tuple[str, str]:
        text_value = str(label or "")
        for space in spaces:
            capture_prefix = str(space.get("capture_prefix") or "")
            name = str(space.get("name") or "")
            if capture_prefix and text_value.startswith(f"{capture_prefix}_"):
                return space["id"], space["name"]
            if name and name.lower() in text_value.lower():
                return space["id"], space["name"]

        if text_value.startswith("empty_room_take"):
            return "garage", "Гараж"
        if text_value.startswith("room_") or "baseline_2node_start" in text_value or "room_4node" in text_value:
            return "room", "Комната"
        if "garage" in text_value.lower():
            return "garage", "Гараж"
        if "room" in text_value.lower():
            return "room", "Комната"
        return "garage", "Гараж"

    def _program_from_label(self, label: str, scenario: Optional[str] = None) -> tuple[str, str]:
        scenario_value = str(scenario or "").strip()
        if scenario_value == "motion":
            return "motion_basic", "Базовые движения"
        if scenario_value in {
            "empty_room", "presence_static", "walking", "sit_stand", "breathing",
        }:
            mapping = {
                "empty_room": ("empty_room", "Пустое помещение"),
                "presence_static": ("presence_static", "Статика человека"),
                "walking": ("walking", "Ходьба"),
                "sit_stand": ("sit_stand", "Сесть и встать"),
                "breathing": ("breathing", "Дыхание"),
            }
            return mapping[scenario_value]

        label_value = str(label or "")
        if "presence_static" in label_value:
            return "presence_static", "Статика человека"
        if "presence_motion" in label_value:
            return "motion_basic", "Базовые движения"
        if "walking" in label_value or "_walking_" in label_value or "_walk_" in label_value:
            return "walking", "Ходьба"
        if "sit_stand" in label_value:
            return "sit_stand", "Сесть и встать"
        if "breathing" in label_value:
            return "breathing", "Дыхание"
        if "empty_room" in label_value:
            return "empty_room", "Пустое помещение"
        if "rebuild" in label_value:
            return "rebuild_baselines", "Пересчитать baseline"
        return "legacy_capture", "Архивный захват"

    def _stable_import_id(self, prefix: str, source_path: Path) -> str:
        digest = hashlib.sha1(str(source_path).encode("utf-8")).hexdigest()[:12]
        return f"{prefix}:{digest}"

    def _artifact_list_for_label(self, label: str, manifest_path: Optional[Path] = None) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        if manifest_path and manifest_path.exists():
            artifacts.append({"kind": "manifest", "path": str(manifest_path)})
        for path in sorted(self._capture_dir.glob(f"*_{label}.ndjson.gz"))[-1:]:
            artifacts.append({"kind": "capture", "path": str(path), "label": label})
        for path in sorted(self._capture_dir.glob(f"*_{label}.summary.json"))[-1:]:
            artifacts.append({"kind": "summary", "path": str(path), "label": label})
        for path in sorted(self._capture_dir.glob(f"{label}.clip.json"))[-1:]:
            artifacts.append({"kind": "clip_manifest", "path": str(path), "label": label})
        for path in sorted(self._capture_dir.glob(f"{label}.teacher_fp2.ndjson.gz"))[-1:]:
            artifacts.append({"kind": "teacher_fp2", "path": str(path), "label": label})
        for path in sorted(self._capture_dir.glob(f"{label}.teacher.mp4"))[-1:]:
            artifacts.append({"kind": "video", "path": str(path), "label": label})
        for path in sorted(self._capture_dir.glob(f"{label}.teacher_audio.m4a"))[-1:]:
            artifacts.append({"kind": "audio", "path": str(path), "label": label})
        return artifacts

    async def ensure_backfilled(self) -> None:
        if self._backfill_done:
            return

        marker = await self._load_state_value(self._BACKFILL_MARKER_KEY)
        existing_runs = await self.list_runs(limit=2000)
        if marker and marker.get("done") and existing_runs:
            self._backfill_done = True
            return

        spaces = self._discover_spaces()
        imported = 0
        existing_runs = await self.list_runs(limit=4000)
        existing_runs_by_id = {
            str(run.get("id") or ""): run
            for run in existing_runs
            if str(run.get("id") or "")
        }
        existing_direct_runs_by_label = {
            str(run.get("label_prefix") or ""): run
            for run in existing_runs
            if str(run.get("label_prefix") or "")
            and not str(run.get("import_source") or "").endswith(".manifest.json")
        }

        def _merge_artifacts(existing: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
            merged: list[dict[str, Any]] = []
            seen: set[str] = set()
            for artifact in list(existing or []) + list(extra or []):
                if not isinstance(artifact, dict):
                    continue
                signature = json.dumps(
                    {
                        "kind": artifact.get("kind"),
                        "path": artifact.get("path"),
                        "label": artifact.get("label"),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                )
                if signature in seen:
                    continue
                seen.add(signature)
                merged.append(artifact)
            return merged

        manifest_labels: set[str] = set()
        atomic_clip_labels: set[str] = set()
        duplicate_manifest_run_ids: list[str] = []
        for manifest_path in sorted(self._capture_dir.glob("*.manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(manifest, dict):
                continue

            label_prefix = str(manifest.get("label_prefix") or manifest.get("run_id") or manifest_path.stem)
            manifest_labels.add(label_prefix)
            artifacts = [{"kind": "manifest", "path": str(manifest_path)}]
            started_at = str(manifest.get("created_at") or manifest.get("started_at") or datetime.fromtimestamp(manifest_path.stat().st_mtime, tz=timezone.utc).isoformat())
            finished_at = str(manifest.get("finished_at") or started_at)

            if isinstance(manifest.get("clips"), list):
                space_id = str(manifest.get("space_id") or "garage")
                selected_space = next((space for space in spaces if space["id"] == space_id), None)
                space_name = str(manifest.get("room_profile") or (selected_space or {}).get("name") or space_id)
                program_id = str(manifest.get("program_id") or "train_atomic")
                program_title = str(manifest.get("program_title") or program_id)
                for clip in manifest.get("clips", []) or []:
                    if not isinstance(clip, dict):
                        continue
                    capture_label = str(clip.get("capture_label") or "")
                    if capture_label:
                        manifest_labels.add(capture_label)
                        atomic_clip_labels.add(capture_label)
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
                existing_direct = existing_direct_runs_by_label.get(label_prefix)
                manifest_run_id = self._stable_import_id("manifest", manifest_path)
                if existing_direct:
                    merged_run = dict(existing_direct)
                    merged_run.update(
                        {
                            "space_id": space_id,
                            "space_name": space_name,
                            "program_id": program_id,
                            "program_title": program_title,
                            "program_type": "capture",
                            "capture_mode": manifest.get("capture_mode"),
                            "pack_id": manifest.get("pack_id"),
                            "require_fp2": manifest.get("fp2_required"),
                            "video_teacher_enabled": manifest.get("video_teacher_enabled"),
                            "audio_teacher_enabled": manifest.get("audio_teacher_enabled"),
                            "status": "completed",
                            "label_prefix": label_prefix,
                            "started_at": merged_run.get("started_at") or started_at,
                            "finished_at": finished_at,
                            "artifacts": _merge_artifacts(list(merged_run.get("artifacts") or []), artifacts),
                        }
                    )
                    await self.save_run(merged_run)
                    existing_direct_runs_by_label[label_prefix] = merged_run
                    if manifest_run_id in existing_runs_by_id:
                        duplicate_manifest_run_ids.append(manifest_run_id)
                else:
                    await self.save_run(
                        {
                            "id": manifest_run_id,
                            "space_id": space_id,
                            "space_name": space_name,
                            "program_id": program_id,
                            "program_title": program_title,
                            "program_type": "capture",
                            "capture_mode": manifest.get("capture_mode"),
                            "pack_id": manifest.get("pack_id"),
                            "require_fp2": manifest.get("fp2_required"),
                            "video_teacher_enabled": manifest.get("video_teacher_enabled"),
                            "audio_teacher_enabled": manifest.get("audio_teacher_enabled"),
                            "status": "completed",
                            "label_prefix": label_prefix,
                            "started_at": started_at,
                            "finished_at": finished_at,
                            "logs": [],
                            "artifacts": artifacts,
                            "import_source": str(manifest_path),
                        }
                    )
                    imported += 1
                continue

            space_id, space_name = self._space_from_label(label_prefix, spaces)
            program_id, program_title = self._program_from_label(label_prefix, str(manifest.get("scenario") or ""))
            for step in manifest.get("steps", []) or []:
                if not isinstance(step, dict):
                    continue
                step_label = str(step.get("label") or "")
                if step_label:
                    artifacts.extend(self._artifact_list_for_label(step_label))
            await self.save_run(
                {
                    "id": self._stable_import_id("manifest", manifest_path),
                    "space_id": space_id,
                    "space_name": space_name,
                    "program_id": program_id,
                    "program_title": program_title,
                    "program_type": "capture",
                    "status": "completed",
                    "label_prefix": label_prefix,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "logs": [],
                    "artifacts": artifacts,
                    "import_source": str(manifest_path),
                }
            )
            imported += 1

        for summary_path in sorted(self._capture_dir.glob("*.summary.json")):
            stem = summary_path.name.removesuffix(".summary.json")
            label = stem.split("_", 1)[1] if re.match(r"^\d{8}-\d{6}_", stem) else stem
            if "_step" in label or label in manifest_labels or label.startswith("fp2_") or label.startswith("dryrun_"):
                continue
            space_id, space_name = self._space_from_label(label, spaces)
            program_id, program_title = self._program_from_label(label)
            started_at = datetime.fromtimestamp(summary_path.stat().st_mtime, tz=timezone.utc).isoformat()
            await self.save_run(
                {
                    "id": self._stable_import_id("summary", summary_path),
                    "space_id": space_id,
                    "space_name": space_name,
                    "program_id": program_id,
                    "program_title": program_title,
                    "program_type": "capture",
                    "status": "completed",
                    "label_prefix": label,
                    "started_at": started_at,
                    "finished_at": started_at,
                    "logs": [],
                    "artifacts": self._artifact_list_for_label(label) or [{"kind": "summary", "path": str(summary_path), "label": label}],
                    "import_source": str(summary_path),
                }
            )
            imported += 1

        duplicate_atomic_summary_run_ids = [
            str(run.get("id") or "")
            for run in existing_runs
            if str(run.get("import_source") or "").endswith(".summary.json")
            and str(run.get("label_prefix") or "") in atomic_clip_labels
        ]
        for run_id in duplicate_atomic_summary_run_ids:
            if run_id:
                await self.delete_run(run_id)
        for run_id in duplicate_manifest_run_ids:
            if run_id:
                await self.delete_run(run_id)

        await self._save_state_value(
            self._BACKFILL_MARKER_KEY,
            {
                "done": True,
                "imported_runs": imported,
                "deleted_duplicate_summary_runs": len(duplicate_atomic_summary_run_ids),
                "deleted_duplicate_manifest_runs": len(duplicate_manifest_run_ids),
                "updated_at": self._timestamp(),
            },
        )
        self._backfill_done = True

    async def list_spaces_with_stats(self) -> dict[str, Any]:
        await self.ensure_backfilled()
        spaces = self._discover_spaces()
        active_space_id = await self.get_active_space_id()
        runs = await self.list_runs(limit=2000)
        by_space: dict[str, list[dict[str, Any]]] = {}
        for run in runs:
            by_space.setdefault(str(run.get("space_id") or "garage"), []).append(run)

        for space in spaces:
            space_runs = by_space.get(space["id"], [])
            completed_runs = [run for run in space_runs if run.get("status") == "completed"]
            program_counts: dict[str, int] = {}
            for run in completed_runs:
                program_id = str(run.get("program_id") or "unknown")
                program_counts[program_id] = program_counts.get(program_id, 0) + 1
            last_run = space_runs[0] if space_runs else None
            space["stats"] = {
                "total_runs": len(space_runs),
                "completed_runs": len(completed_runs),
                "program_counts": program_counts,
                "last_run_at": (last_run or {}).get("finished_at") or (last_run or {}).get("started_at"),
            }
            space["is_active"] = space["id"] == active_space_id

        if active_space_id not in {space["id"] for space in spaces} and spaces:
            active_space_id = spaces[0]["id"]

        return {
            "active_space_id": active_space_id,
            "spaces": spaces,
        }
