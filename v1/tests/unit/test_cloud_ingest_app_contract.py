from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[3]
V1_ROOT = ROOT / "v1"
for candidate in (V1_ROOT, ROOT):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)

import cloud_ingest_app as ingest_app
from src.services.runbot_cloud_ingest_service import parse_cloud_csi_csv_record


def _sample_csi_csv_line() -> str:
    iq_values = " ".join(str(index) for index in range(1, 81))
    return (
        "CSI_DATA,station,3c:0f:02:d9:80:98,aa:bb:cc:dd:ee:ff,-62,"
        "0,0,0,0,0,0,0,0,0,-95,0,6,0,80,"
        f'"[{iq_values}]"'
    )


def _sample_payload() -> dict[str, object]:
    return {
        "schema_version": "runbot-csi-cloud-uplink-v1",
        "node_id": "node01",
        "topology_id": "garage:test",
        "topology_profile": "garage_ceiling_v2_runtime",
        "layout_epoch": "garage_ceiling_v2",
        "firmware_channel": "stable",
        "install_label": "garage_node01",
        "batch_size": 1,
        "sent_at_ms": 1775432101234,
        "records": [
            {
                "captured_at_ms": 1775432100123,
                "source_mac": "aa:bb:cc:dd:ee:ff",
                "rssi": -62,
                "channel": 6,
                "format": "esp32_csi_csv_v1",
                "csi_csv": _sample_csi_csv_line(),
            }
        ],
    }


def test_parse_cloud_csi_csv_record_extracts_signal_arrays():
    parsed = parse_cloud_csi_csv_record(_sample_csi_csv_line())

    assert parsed["channel"] == 6
    assert parsed["rssi"] == -62.0
    assert parsed["noise_floor"] == -95.0
    assert parsed["num_subcarriers"] == 40


def test_health_contract(monkeypatch):
    monkeypatch.setenv("RUNBOT_CSI_CLOUD_INGEST_ENABLED", "1")
    with TestClient(ingest_app.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "runbot-cloud-ingest"


def test_cloud_ingest_rejects_missing_secret(monkeypatch):
    monkeypatch.setenv("RUNBOT_CSI_CLOUD_INGEST_ENABLED", "1")
    monkeypatch.delenv("RUNBOT_CSI_CLOUD_INGEST_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("RUNBOT_CSI_CLOUD_INGEST_API_KEY", raising=False)

    with TestClient(ingest_app.app) as client:
        response = client.post("/api/v1/csi/cloud-ingest", json=_sample_payload())

    assert response.status_code == 503
    assert response.json()["detail"] == "RunBot cloud ingest auth is not configured"


def test_cloud_ingest_accepts_bearer_token(monkeypatch):
    monkeypatch.setenv("RUNBOT_CSI_CLOUD_INGEST_ENABLED", "1")
    monkeypatch.setenv("RUNBOT_CSI_CLOUD_INGEST_AUTH_TOKEN", "token-123")
    monkeypatch.delenv("RUNBOT_CSI_CLOUD_INGEST_API_KEY", raising=False)

    captured: dict[str, object] = {}

    async def fake_ingest_batch(payload: dict[str, object], **kwargs):
        captured["payload"] = payload
        captured.update(kwargs)
        return {
            "schema_version": payload["schema_version"],
            "node_id": payload["node_id"],
            "accepted_records": 1,
            "duplicate_records": 0,
            "rejected_records": 0,
            "batch_size": 1,
            "errors": [],
        }

    monkeypatch.setattr(ingest_app.runbot_cloud_ingest_service, "ingest_batch", fake_ingest_batch)

    with TestClient(ingest_app.app) as client:
        response = client.post(
            "/api/v1/csi/cloud-ingest",
            json=_sample_payload(),
            headers={
                "Authorization": "Bearer token-123",
                "X-Forwarded-For": "203.0.113.10",
                "User-Agent": "pytest-cloud-ingest",
            },
        )

    assert response.status_code == 200
    assert response.json()["accepted_records"] == 1
    assert captured["client_ip"] == "203.0.113.10"
