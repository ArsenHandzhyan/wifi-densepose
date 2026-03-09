"""
Persistent room layout storage for FP2 UI.

Stores the full room/template/layout payload as JSON in the configured database.
Falls back to SQLite automatically through the existing DatabaseManager failsafe.
"""

import json
from typing import Any, Dict, Optional

from sqlalchemy import text

from src.config.settings import Settings
from src.database.connection import get_database_manager


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

    def default_scope(self) -> str:
        device_id = (
            self.settings.fp2_device_id
            or self.settings.fp2_mac_address
            or self.settings.aqara_open_id
            or "default"
        )
        return f"fp2-room-config:{device_id}"

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return

        db_manager = get_database_manager(self.settings)
        async with db_manager.get_async_session() as session:
            await session.execute(text(self._CREATE_TABLE_SQL))
        self._schema_ready = True

    async def get_state(self, scope: Optional[str] = None) -> Optional[Dict[str, Any]]:
        await self.ensure_schema()
        resolved_scope = (scope or self.default_scope()).strip()
        db_manager = get_database_manager(self.settings)

        async with db_manager.get_async_session() as session:
            result = await session.execute(text(self._SELECT_SQL), {"scope": resolved_scope})
            row = result.mappings().first()

        if not row:
            return None

        payload = json.loads(row["payload"])
        return {
            "scope": row["scope"],
            "payload": payload,
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
            "storage_backend": "sqlite_fallback" if db_manager.is_using_sqlite_fallback() else "postgresql",
        }

    async def save_state(self, payload: Dict[str, Any], scope: Optional[str] = None) -> Dict[str, Any]:
        await self.ensure_schema()
        resolved_scope = (scope or self.default_scope()).strip()
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
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
