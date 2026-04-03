from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[3]
V1_ROOT = ROOT / "v1"
for candidate in (ROOT, V1_ROOT):
    text = str(candidate)
    if text not in sys.path:
        sys.path.insert(0, text)

from src.app import app
from src.api.dependencies import get_fp2_service
from src.services.fp2_service import FP2Service, FP2Snapshot, FP2Target, FP2Zone
from src.services.runtime_uptime import utc_now


def _build_snapshot(*, presence: bool = True) -> FP2Snapshot:
    return FP2Snapshot(
        timestamp=utc_now(),
        presence=presence,
        zones=[
            FP2Zone(
                zone_id="garage",
                name="Garage",
                occupied=presence,
                target_count=1 if presence else 0,
            )
        ],
        targets=[
            FP2Target(
                target_id="person_1",
                zone_id="garage",
                confidence=0.95,
            )
        ]
        if presence
        else [],
        raw_attributes={"source": "test"},
    )


class StubFP2Service:
    def __init__(
        self,
        *,
        enabled: bool = True,
        fetched_snapshot: FP2Snapshot | None = None,
        cached_snapshot: FP2Snapshot | None = None,
        last_error: str | None = None,
    ) -> None:
        self.settings = SimpleNamespace(
            fp2_enabled=enabled,
            fp2_entity_id="binary_sensor.fp2_presence",
            fp2_poll_interval=0.1,
        )
        self.last_snapshot = cached_snapshot
        self.last_error = last_error
        self._fetched_snapshot = fetched_snapshot

    async def fetch_snapshot(self, entity_id: str | None = None) -> FP2Snapshot | None:
        return self._fetched_snapshot

    def snapshot_to_pose_data(self, snapshot: FP2Snapshot | None = None):
        snap = snapshot or self.last_snapshot
        if snap is None:
            return {
                "timestamp": utc_now().isoformat(),
                "frame_id": "fp2_no_data",
                "persons": [],
                "zone_summary": {},
                "processing_time_ms": 0,
                "metadata": {"source": "fp2", "presence": False},
            }

        return {
            "timestamp": snap.timestamp.isoformat(),
            "frame_id": f"fp2_{int(snap.timestamp.timestamp() * 1000)}",
            "persons": [
                {
                    "person_id": target.target_id,
                    "confidence": target.confidence,
                    "zone_id": target.zone_id,
                    "timestamp": snap.timestamp.isoformat(),
                }
                for target in snap.targets
            ],
            "zone_summary": {
                zone.zone_id: max(zone.target_count, 1)
                for zone in snap.zones
                if zone.occupied
            },
            "processing_time_ms": 0,
            "metadata": {
                "source": "fp2",
                "presence": snap.presence,
            },
        }


class _FakeResponse:
    def __init__(self, *, status: int, payload):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"http {self.status}")


class _FakeSession:
    def __init__(self, *, get_responses, post_responses):
        self._get_responses = list(get_responses)
        self._post_responses = list(post_responses)
        self.closed = False

    def get(self, *args, **kwargs):
        return self._get_responses.pop(0)

    def post(self, *args, **kwargs):
        return self._post_responses.pop(0)


def test_fp2_current_returns_structured_503_when_upstream_is_unavailable_without_cache(monkeypatch) -> None:
    monkeypatch.setenv("WIFI_DENSEPOSE_ALLOW_MULTI_BACKEND", "1")
    app.dependency_overrides[get_fp2_service] = lambda: StubFP2Service(
        fetched_snapshot=None,
        cached_snapshot=None,
        last_error="ha_auth_failed",
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/fp2/current")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    payload = response.json()
    detail = payload["error"]["message"]
    assert detail["error"] == "fp2_upstream_unavailable"
    assert detail["upstream_available"] is False
    assert detail["cached_snapshot_available"] is False
    assert detail["last_error"] == "ha_auth_failed"


def test_fp2_current_marks_cached_payload_as_stale_when_upstream_fetch_fails(monkeypatch) -> None:
    monkeypatch.setenv("WIFI_DENSEPOSE_ALLOW_MULTI_BACKEND", "1")
    cached_snapshot = _build_snapshot()
    app.dependency_overrides[get_fp2_service] = lambda: StubFP2Service(
        fetched_snapshot=None,
        cached_snapshot=cached_snapshot,
        last_error="ha_request_timeout",
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/fp2/current?entity_id=sensor.fp2_custom")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    metadata = payload["metadata"]
    assert metadata["fp2_state"] == "stale_cache"
    assert metadata["stale"] is True
    assert metadata["upstream_available"] is False
    assert metadata["entity_id"] == "sensor.fp2_custom"
    assert metadata["last_error"] == "ha_request_timeout"
    assert metadata["cached_snapshot_timestamp"] == cached_snapshot.timestamp.isoformat()


def test_fp2_current_marks_fresh_snapshot_as_upstream_available(monkeypatch) -> None:
    monkeypatch.setenv("WIFI_DENSEPOSE_ALLOW_MULTI_BACKEND", "1")
    fresh_snapshot = _build_snapshot()
    app.dependency_overrides[get_fp2_service] = lambda: StubFP2Service(
        fetched_snapshot=fresh_snapshot,
        cached_snapshot=None,
        last_error=None,
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/fp2/current")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    metadata = payload["metadata"]
    assert metadata["fp2_state"] == "fresh"
    assert metadata["stale"] is False
    assert metadata["upstream_available"] is True
    assert metadata["entity_id"] == "binary_sensor.fp2_presence"


def test_fp2_status_reports_degraded_when_only_cached_snapshot_is_available() -> None:
    service = FP2Service(
        settings=SimpleNamespace(
            fp2_enabled=True,
            ha_url="http://ha.local",
            ha_token="token",
            fp2_entity_id="binary_sensor.fp2_presence",
            fp2_poll_interval=1.0,
        )
    )
    service._running = True
    service._last_snapshot = _build_snapshot()
    service._stats["last_error"] = "ha_request_timeout"

    status = asyncio.run(service.get_status())

    assert status["status"] == "degraded"
    assert status["upstream_available"] is False
    assert status["stale"] is True
    assert "cached" in status["message"].lower()


def test_fp2_status_reports_upstream_unavailable_without_cached_snapshot() -> None:
    service = FP2Service(
        settings=SimpleNamespace(
            fp2_enabled=True,
            ha_url="http://ha.local",
            ha_token="token",
            fp2_entity_id="binary_sensor.fp2_presence",
            fp2_poll_interval=1.0,
        )
    )
    service._running = True
    service._stats["last_error"] = "ha_auth_failed"

    status = asyncio.run(service.get_status())

    assert status["status"] == "upstream_unavailable"
    assert status["upstream_available"] is False
    assert status["stale"] is False
    assert status["message"] == "ha_auth_failed"


def test_fp2_snapshot_to_pose_data_preserves_structured_target_coordinates() -> None:
    service = FP2Service(
        settings=SimpleNamespace(
            fp2_enabled=True,
            ha_url="http://ha.local",
            ha_token="token",
            fp2_entity_id="binary_sensor.aqara_fp2",
            fp2_poll_interval=1.0,
        )
    )

    snapshot = service._parse_entity(
        {
            "entity_id": "binary_sensor.aqara_fp2",
            "state": "on",
            "last_updated": utc_now().isoformat(),
            "attributes": {
                "targets": [
                    {
                        "id": "0",
                        "zone_id": "range_0",
                        "x": 88.0,
                        "y": 104.0,
                        "activity": "standing",
                    }
                ],
                "zones": [
                    {
                        "id": "zone_1",
                        "name": "Zone 1",
                        "occupied": False,
                        "target_count": 0,
                    }
                ],
            },
        }
    )

    payload = service.snapshot_to_pose_data(snapshot)

    assert len(payload["persons"]) == 1
    assert payload["persons"][0]["bounding_box"]["x"] == 88.0
    assert payload["persons"][0]["bounding_box"]["y"] == 104.0
    assert payload["persons"][0]["zone_id"] == "range_0"


def test_fp2_fetch_snapshot_refreshes_ha_access_token_on_401() -> None:
    service = FP2Service(
        settings=SimpleNamespace(
            fp2_enabled=True,
            ha_url="http://ha.local",
            ha_token="",
            ha_refresh_token="refresh-token",
            ha_client_id="http://ha.local/",
            fp2_entity_id="binary_sensor.aqara_fp2",
            fp2_poll_interval=1.0,
        )
    )
    service._session = _FakeSession(
        post_responses=[
            _FakeResponse(
                status=200,
                payload={"access_token": "fresh-ha-token"},
            )
        ],
        get_responses=[
            _FakeResponse(status=200, payload={"entity_id": "binary_sensor.aqara_fp2", "state": "on", "attributes": {}}),
        ],
    )

    snapshot = asyncio.run(service.fetch_snapshot())

    assert snapshot is not None
    assert snapshot.presence is True
    assert service.headers["Authorization"] == "Bearer fresh-ha-token"


def test_fp2_fetch_snapshot_retries_after_401_when_refresh_credentials_exist() -> None:
    service = FP2Service(
        settings=SimpleNamespace(
            fp2_enabled=True,
            ha_url="http://ha.local",
            ha_token="expired-token",
            ha_refresh_token="refresh-token",
            ha_client_id="http://ha.local/",
            fp2_entity_id="binary_sensor.aqara_fp2",
            fp2_poll_interval=1.0,
        )
    )
    service._session = _FakeSession(
        post_responses=[
            _FakeResponse(
                status=200,
                payload={"access_token": "refreshed-token"},
            )
        ],
        get_responses=[
            _FakeResponse(status=401, payload={"message": "unauthorized"}),
            _FakeResponse(status=200, payload={"entity_id": "binary_sensor.aqara_fp2", "state": "off", "attributes": {}}),
        ],
    )

    snapshot = asyncio.run(service.fetch_snapshot())

    assert snapshot is not None
    assert snapshot.presence is False
    assert service.headers["Authorization"] == "Bearer refreshed-token"


def test_fp2_fetch_snapshot_rejects_unknown_entity_state_as_non_live() -> None:
    service = FP2Service(
        settings=SimpleNamespace(
            fp2_enabled=True,
            ha_url="http://ha.local",
            ha_token="valid-token",
            ha_refresh_token="",
            ha_client_id="",
            fp2_entity_id="binary_sensor.aqara_fp2",
            fp2_poll_interval=1.0,
        )
    )
    service._session = _FakeSession(
        post_responses=[],
        get_responses=[
            _FakeResponse(
                status=200,
                payload={
                    "entity_id": "binary_sensor.aqara_fp2",
                    "state": "unknown",
                    "attributes": {"friendly_name": "Aqara FP2"},
                },
            )
        ],
    )

    snapshot = asyncio.run(service.fetch_snapshot())

    assert snapshot is None
    assert service.last_error == "fp2_entity_state_unknown:binary_sensor.aqara_fp2"
