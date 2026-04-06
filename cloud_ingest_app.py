"""Minimal ASGI app for RunBot direct cloud ingest."""

from __future__ import annotations

import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

V1_ROOT = Path(__file__).resolve().parent / "v1"
ROOT = Path(__file__).resolve().parent
v1_path = str(V1_ROOT)
root_path = str(ROOT)
sys.path[:] = [entry for entry in sys.path if entry != root_path]
if v1_path not in sys.path:
    sys.path.insert(0, v1_path)
for module_name in [name for name in list(sys.modules) if name == "src" or name.startswith("src.")]:
    sys.modules.pop(module_name, None)

from src.services.runbot_cloud_ingest_service import runbot_cloud_ingest_service

logger = logging.getLogger(__name__)
app = FastAPI(title="RunBot Cloud Ingest", version="1.0.0")


class RunbotCloudIngestRecordRequest(BaseModel):
    captured_at_ms: int = Field(..., description="Node-local capture timestamp in milliseconds")
    source_mac: str = Field(..., description="MAC of the CSI source/AP observed by the node")
    rssi: float | None = Field(default=None, description="Observed RSSI in dBm")
    channel: int | None = Field(default=None, description="Observed Wi-Fi channel")
    format: Literal["esp32_csi_csv_v1"] = Field(default="esp32_csi_csv_v1")
    csi_csv: str = Field(..., description="Raw CSI_DATA CSV line produced by the node firmware")


class RunbotCloudIngestBatchRequest(BaseModel):
    schema_version: Literal["runbot-csi-cloud-uplink-v1"]
    node_id: str
    topology_id: str | None = None
    topology_profile: str | None = None
    layout_epoch: str | None = None
    firmware_channel: str | None = None
    install_label: str | None = None
    batch_size: int | None = None
    sent_at_ms: int | None = None
    records: list[RunbotCloudIngestRecordRequest]


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _extract_bearer_token(raw_authorization: str | None) -> str | None:
    if not raw_authorization:
        return None
    try:
        scheme, token = raw_authorization.split(" ", 1)
    except ValueError:
        return None
    if scheme.strip().lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _require_cloud_ingest_auth(request: Request) -> None:
    if not _env_enabled("RUNBOT_CSI_CLOUD_INGEST_ENABLED", True):
        raise HTTPException(status_code=503, detail="RunBot cloud ingest endpoint is disabled")

    expected_token = str(os.getenv("RUNBOT_CSI_CLOUD_INGEST_AUTH_TOKEN", "")).strip()
    expected_api_key = str(os.getenv("RUNBOT_CSI_CLOUD_INGEST_API_KEY", "")).strip()
    if not expected_token and not expected_api_key:
        raise HTTPException(status_code=503, detail="RunBot cloud ingest auth is not configured")

    provided_token = _extract_bearer_token(request.headers.get("authorization"))
    provided_api_key = request.headers.get("x-api-key") or request.headers.get("apikey")

    if expected_token and provided_token and secrets.compare_digest(provided_token, expected_token):
        return
    if expected_api_key and provided_api_key and secrets.compare_digest(provided_api_key, expected_api_key):
        return
    raise HTTPException(status_code=401, detail="Invalid RunBot cloud ingest credentials")


def _extract_request_ip(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = None
    if forwarded_for:
        client_ip = forwarded_for.split(",", 1)[0].strip() or None
    if client_ip is None and request.client is not None:
        client_ip = request.client.host
    return client_ip, forwarded_for


@app.get("/")
@app.get("/health")
@app.get("/health/live")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "service": "runbot-cloud-ingest",
        "ingest_enabled": _env_enabled("RUNBOT_CSI_CLOUD_INGEST_ENABLED", True),
    }


@app.post("/api/v1/csi/cloud-ingest")
async def runbot_cloud_ingest(payload: RunbotCloudIngestBatchRequest, request: Request):
    _require_cloud_ingest_auth(request)
    client_ip, forwarded_for = _extract_request_ip(request)
    try:
        summary = await runbot_cloud_ingest_service.ingest_batch(
            payload.model_dump(),
            client_ip=client_ip,
            forwarded_for=forwarded_for,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("RunBot cloud ingest failed")
        raise HTTPException(status_code=500, detail=f"cloud_ingest_failed:{type(exc).__name__}") from exc

    return {
        "ok": True,
        "ingestion_mode": "direct_cloud_uplink",
        "client_ip": client_ip,
        **summary,
    }
