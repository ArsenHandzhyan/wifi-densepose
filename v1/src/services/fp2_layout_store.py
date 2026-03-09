"""
Persistent room layout storage for FP2 UI.

Stores the full room/template/layout payload as JSON in the configured database.
Falls back to SQLite automatically through the existing DatabaseManager failsafe.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.config.settings import Settings
from src.database.connection import get_database_manager

logger = logging.getLogger(__name__)


class FP2LayoutStoreService:
    """Persist and retrieve FP2 room layout state."""

    _CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS fp2_layout_state (
        scope TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """

    _UPSERT_SQL = """
    INSERT INTO fp2_layout_state (scope, payload, created_at, updated_at)
    VALUES (:scope, :payload, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT(scope) DO UPDATE SET
        payload = excluded.payload,
        updated_at = CURRENT_TIMESTAMP
    """

    _SELECT_SQL = """
    SELECT scope, payload, created_at, updated_at
    FROM fp2_layout_state
    WHERE scope = :scope
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._schema_ready = False
        self._file_fallback_path = Path("/tmp/fp2_layout_state.json")

    def default_scope(self) -> str:
        device_id = (
            self.settings.fp2_device_id
            or self.settings.fp2_mac_address
            or self.settings.aqara_open_id
            or "default"
        )
        return f"fp2-room-config:{device_id}"

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_file_state(self) -> Dict[str, Any]:
        if not self._file_fallback_path.exists():
            return {}
        try:
            payload = json.loads(self._file_fallback_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning("Failed to read FP2 layout fallback file %s: %s", self._file_fallback_path, exc)
            return {}

    def _write_file_state(self, state: Dict[str, Any]) -> None:
        try:
            self._file_fallback_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_fallback_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to write FP2 layout fallback file %s: %s", self._file_fallback_path, exc)

    def _get_file_scope_state(self, scope: str) -> Optional[Dict[str, Any]]:
        root = self._read_file_state()
        scopes = root.get("scopes") if isinstance(root.get("scopes"), dict) else {}
        scope_state = scopes.get(scope)
        if not isinstance(scope_state, dict):
            return None
        payload = scope_state.get("payload")
        return {
            "scope": scope,
            "payload": payload if isinstance(payload, dict) else {},
            "created_at": scope_state.get("created_at"),
            "updated_at": scope_state.get("updated_at"),
            "storage_backend": "file_fallback",
        }

    def _save_file_scope_state(self, payload: Dict[str, Any], scope: str) -> Dict[str, Any]:
        root = self._read_file_state()
        scopes = root.get("scopes") if isinstance(root.get("scopes"), dict) else {}
        previous = scopes.get(scope) if isinstance(scopes.get(scope), dict) else {}
        created_at = previous.get("created_at") or self._timestamp()
        updated_at = self._timestamp()
        scopes[scope] = {
            "payload": payload,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        root["scopes"] = scopes
        self._write_file_state(root)
        return {
            "scope": scope,
            "payload": payload,
            "created_at": created_at,
            "updated_at": updated_at,
            "storage_backend": "file_fallback",
        }

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        db_manager = get_database_manager(self.settings)
        async with db_manager.get_async_session() as session:
            await session.execute(text(self._CREATE_TABLE_SQL))
        self._schema_ready = True

    async def get_state(self, scope: Optional[str] = None) -> Optional[Dict[str, Any]]:
        resolved_scope = (scope or self.default_scope()).strip()
        try:
            await self.ensure_schema()
            db_manager = get_database_manager(self.settings)

            async with db_manager.get_async_session() as session:
                result = await session.execute(text(self._SELECT_SQL), {"scope": resolved_scope})
                row = result.mappings().first()

            if not row:
                return self._get_file_scope_state(resolved_scope)

            payload = json.loads(row["payload"])
            return {
                "scope": row["scope"],
                "payload": payload,
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
                "storage_backend": "sqlite_fallback" if db_manager.is_using_sqlite_fallback() else "postgresql",
            }
        except Exception as exc:
            logger.warning("FP2 layout DB read failed, using file fallback: %s", exc)
            return self._get_file_scope_state(resolved_scope)

    async def save_state(self, payload: Dict[str, Any], scope: Optional[str] = None) -> Dict[str, Any]:
        resolved_scope = (scope or self.default_scope()).strip()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            await self.ensure_schema()
            db_manager = get_database_manager(self.settings)

            async with db_manager.get_async_session() as session:
                await session.execute(text(self._UPSERT_SQL), {"scope": resolved_scope, "payload": serialized})
                result = await session.execute(text(self._SELECT_SQL), {"scope": resolved_scope})
                row = result.mappings().first()

            return {
                "scope": row["scope"],
                "payload": payload,
                "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
                "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
                "storage_backend": "sqlite_fallback" if db_manager.is_using_sqlite_fallback() else "postgresql",
            }
        except Exception as exc:
            logger.warning("FP2 layout DB write failed, using file fallback: %s", exc)
            return self._save_file_scope_state(payload, resolved_scope)
