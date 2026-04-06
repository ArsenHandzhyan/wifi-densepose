"""Direct cloud ingest for RunBot CSI node firmware batches."""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
from sqlalchemy import select

from src.config.settings import get_settings
from src.database.connection import get_database_manager
from src.database.models import CSIData, Device, DeviceStatus

from .csi_node_inventory import MAC_TO_NODE_ID, NODE_ID_TO_DEFAULT_IP, NODE_ID_TO_MAC

logger = logging.getLogger(__name__)


def _channel_to_frequency_hz(channel: int | None) -> float:
    if channel is None or channel <= 0:
        return 2_437_000_000.0
    if 1 <= channel <= 13:
        return float(2_412_000_000 + (channel - 1) * 5_000_000)
    if channel == 14:
        return 2_484_000_000.0
    if 36 <= channel <= 177:
        return float(5_000_000_000 + channel * 5_000_000)
    return 2_437_000_000.0


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_cloud_csi_csv_record(line: str) -> dict[str, Any]:
    """Parse a firmware CSI CSV line into amplitude/phase arrays and metadata."""
    if not isinstance(line, str):
        raise ValueError("csi_csv_missing")

    normalized = line.strip()
    if "CSI_DATA" not in normalized:
        raise ValueError("csi_csv_invalid_prefix")

    parts = normalized.split(",")
    node_mac = parts[2].strip().lower() if len(parts) > 2 else ""
    source_mac_csv = parts[3].strip().lower() if len(parts) > 3 else ""
    rssi = _coerce_float(parts[4] if len(parts) > 4 else None)
    noise_floor = _coerce_float(parts[14] if len(parts) > 14 else None)
    channel = _coerce_int(parts[16] if len(parts) > 16 else None)

    start = normalized.find('"[')
    end = normalized.find(']"', start)
    if start < 0 or end < 0:
        raise ValueError("csi_iq_block_missing")

    csi_str = normalized[start + 2 : end]
    try:
        iq_values = [int(chunk) for chunk in csi_str.replace(",", " ").split()]
    except ValueError as exc:
        raise ValueError("csi_iq_parse_failed") from exc

    pair_count = len(iq_values) // 2
    if pair_count < 40:
        raise ValueError("csi_vector_too_short")

    iq_array = np.array(iq_values[: pair_count * 2], dtype=np.float32).reshape(-1, 2)
    amplitude = np.sqrt(iq_array[:, 0] ** 2 + iq_array[:, 1] ** 2)
    phase = np.arctan2(iq_array[:, 1], iq_array[:, 0])

    try:
        from .csi_phase_sanitization import sanitize_phase_vector

        phase = sanitize_phase_vector(phase)
    except Exception:
        logger.debug("cloud ingest phase sanitization unavailable", exc_info=True)

    return {
        "node_mac": node_mac,
        "source_mac_csv": source_mac_csv,
        "rssi": rssi,
        "noise_floor": noise_floor,
        "channel": channel,
        "amplitude": amplitude.astype(np.float32),
        "phase": phase.astype(np.float32),
        "num_subcarriers": int(amplitude.size),
    }


class RunbotCloudIngestService:
    """Persist batched direct-cloud CSI payloads into the canonical CSI DB."""

    def __init__(self) -> None:
        self._db_manager = None
        self._device_id_cache: dict[str, Any] = {}

    async def ingest_batch(
        self,
        payload: dict[str, Any],
        *,
        client_ip: str | None = None,
        forwarded_for: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        schema_version = str(payload.get("schema_version") or "").strip()
        if schema_version != "runbot-csi-cloud-uplink-v1":
            raise ValueError("schema_version_invalid")

        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            raise ValueError("node_id_missing")

        records = payload.get("records") or []
        if not isinstance(records, list) or not records:
            raise ValueError("records_missing")

        db_manager = await self._ensure_db_manager()
        accepted_records = 0
        rejected_records = 0
        duplicate_records = 0
        errors: list[str] = []

        async with db_manager.get_async_session() as session:
            device_id = await self._ensure_device_id(
                session,
                node_id=node_id,
                client_ip=client_ip,
                forwarded_for=forwarded_for,
                payload=payload,
            )

            for index, record in enumerate(records, start=1):
                try:
                    saved = await self._ingest_record(
                        session,
                        device_id=device_id,
                        node_id=node_id,
                        payload=payload,
                        record=record,
                        record_index=index,
                        client_ip=client_ip,
                        forwarded_for=forwarded_for,
                        user_agent=user_agent,
                    )
                    if saved:
                        accepted_records += 1
                    else:
                        duplicate_records += 1
                except Exception as exc:
                    rejected_records += 1
                    if len(errors) < 10:
                        errors.append(f"record_{index}:{type(exc).__name__}:{exc}")

        return {
            "schema_version": schema_version,
            "node_id": node_id,
            "accepted_records": accepted_records,
            "duplicate_records": duplicate_records,
            "rejected_records": rejected_records,
            "batch_size": len(records),
            "errors": errors,
        }

    async def _ensure_db_manager(self):
        if self._db_manager is not None:
            return self._db_manager

        settings = get_settings()
        self._db_manager = get_database_manager(settings)
        await self._db_manager.initialize()
        return self._db_manager

    async def _ensure_device_id(
        self,
        session: Any,
        *,
        node_id: str,
        client_ip: str | None,
        forwarded_for: str | None,
        payload: dict[str, Any],
    ) -> Any:
        cached_id = self._device_id_cache.get(node_id)
        if cached_id is not None:
            return cached_id

        mac_address = NODE_ID_TO_MAC.get(node_id)
        if not mac_address:
            raise ValueError(f"unknown_node_id:{node_id}")

        with session.no_autoflush:
            result = await session.execute(select(Device).where(Device.mac_address == mac_address))
        device = result.scalar_one_or_none()

        config_payload = dict(device.config or {}) if device and isinstance(device.config, dict) else {}
        cloud_payload = dict(config_payload.get("cloud") or {}) if isinstance(config_payload.get("cloud"), dict) else {}
        cloud_payload.update(
            {
                "enabled": True,
                "transport": "direct_cloud",
                "topology_id": payload.get("topology_id"),
                "topology_profile": payload.get("topology_profile"),
                "layout_epoch": payload.get("layout_epoch"),
                "firmware_channel": payload.get("firmware_channel"),
                "install_label": payload.get("install_label"),
                "last_client_ip": client_ip,
                "last_forwarded_for": forwarded_for,
                "last_ingest_at_ms": int(time.time() * 1000),
            }
        )
        config_payload["cloud"] = cloud_payload

        canonical_ip = NODE_ID_TO_DEFAULT_IP.get(node_id)
        if device is None:
            device = Device(
                name=node_id,
                device_type="csi_node",
                mac_address=mac_address,
                ip_address=canonical_ip,
                status=DeviceStatus.ACTIVE.value,
                description="RunBot Wi-Fi CSI node created by direct cloud ingest.",
                capabilities=["csi", "cloud_uplink"],
                tags=["runbot", "direct_cloud"],
                config=config_payload,
            )
            session.add(device)
        else:
            device.name = node_id
            device.device_type = "csi_node"
            if canonical_ip:
                device.ip_address = canonical_ip
            device.status = DeviceStatus.ACTIVE.value
            device.config = config_payload
            if not device.capabilities:
                device.capabilities = ["csi", "cloud_uplink"]
            if not device.tags:
                device.tags = ["runbot", "direct_cloud"]

        await session.flush()
        self._device_id_cache[node_id] = device.id
        return device.id

    async def _ingest_record(
        self,
        session: Any,
        *,
        device_id: Any,
        node_id: str,
        payload: dict[str, Any],
        record: dict[str, Any],
        record_index: int,
        client_ip: str | None,
        forwarded_for: str | None,
        user_agent: str | None,
    ) -> bool:
        record_format = str(record.get("format") or "esp32_csi_csv_v1").strip()
        if record_format != "esp32_csi_csv_v1":
            raise ValueError("unsupported_record_format")

        parsed = parse_cloud_csi_csv_record(str(record.get("csi_csv") or ""))
        parsed_node_id = MAC_TO_NODE_ID.get(parsed["node_mac"])
        if parsed_node_id and parsed_node_id != node_id:
            raise ValueError(f"node_id_mismatch:{parsed_node_id}")

        captured_at_ms = _coerce_int(record.get("captured_at_ms"))
        if captured_at_ms is None:
            captured_at_ms = _coerce_int(payload.get("sent_at_ms")) or int(time.time() * 1000)
        timestamp_ns = int(captured_at_ms) * 1_000_000
        sequence_number = _coerce_int(record.get("sequence_number")) or int(record_index)

        with session.no_autoflush:
            duplicate = await session.execute(
                select(CSIData.id).where(
                    CSIData.device_id == device_id,
                    CSIData.sequence_number == sequence_number,
                    CSIData.timestamp_ns == timestamp_ns,
                )
            )
        if duplicate.scalar_one_or_none() is not None:
            return False

        rssi = _coerce_float(record.get("rssi"))
        if rssi is None:
            rssi = parsed["rssi"]
        noise_floor = parsed["noise_floor"]
        channel = _coerce_int(record.get("channel"))
        if channel is None:
            channel = parsed["channel"]

        snr = None
        if rssi is not None and noise_floor is not None:
            snr = float(rssi - noise_floor)

        amplitude = parsed["amplitude"]
        phase = parsed["phase"]
        metadata = {
            "ingestion_mode": "direct_cloud_uplink",
            "parser": "esp32_csv_cloud",
            "transport_schema": payload.get("schema_version"),
            "topology_id": payload.get("topology_id"),
            "topology_profile": payload.get("topology_profile"),
            "layout_epoch": payload.get("layout_epoch"),
            "firmware_channel": payload.get("firmware_channel"),
            "install_label": payload.get("install_label"),
            "batch_size": payload.get("batch_size"),
            "sent_at_ms": payload.get("sent_at_ms"),
            "captured_at_ms": captured_at_ms,
            "channel": channel,
            "source_mac": str(record.get("source_mac") or parsed["source_mac_csv"] or "").strip().lower() or None,
            "node_mac": parsed["node_mac"] or None,
            "client_ip": client_ip,
            "forwarded_for": forwarded_for,
            "canonical_ip": NODE_ID_TO_DEFAULT_IP.get(node_id),
            "amp_mean": round(float(np.mean(amplitude)), 6),
            "phase_std": round(float(np.std(phase)) if phase.size > 1 else 0.0, 6),
        }
        if user_agent:
            metadata["user_agent"] = user_agent

        session.add(
            CSIData(
                device_id=device_id,
                session_id=None,
                sequence_number=sequence_number,
                timestamp_ns=timestamp_ns,
                amplitude=amplitude.tolist(),
                phase=phase.tolist(),
                frequency=float(_channel_to_frequency_hz(channel)),
                bandwidth=20_000_000.0,
                rssi=rssi,
                snr=snr,
                noise_floor=noise_floor,
                tx_antenna=None,
                rx_antenna=None,
                num_subcarriers=int(parsed["num_subcarriers"]),
                processing_status="completed",
                is_valid=True,
                meta_data=metadata,
            )
        )
        return True


runbot_cloud_ingest_service = RunbotCloudIngestService()
