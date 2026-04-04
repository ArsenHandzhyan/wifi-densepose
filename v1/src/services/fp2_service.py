"""
Aqara FP2 mmWave sensor integration via Home Assistant REST API.

Polls HA for FP2 entity states, converts zone/presence data
into the wifi-densepose pipeline format (pose-like structures).
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

import aiohttp

from src.config.settings import Settings
from src.services.runtime_uptime import utc_now

logger = logging.getLogger(__name__)


@dataclass
class FP2Zone:
    """A zone detected by the FP2 sensor."""
    zone_id: str
    name: str
    occupied: bool
    target_count: int = 0
    last_updated: Optional[datetime] = None


@dataclass
class FP2Target:
    """A target (person) detected by the FP2 sensor."""
    target_id: str
    zone_id: str
    x: float = 0.0
    y: float = 0.0
    distance: float = 0.0
    angle: float = 0.0
    activity: str = "unknown"
    confidence: float = 0.8


@dataclass
class FP2Snapshot:
    """Complete FP2 sensor snapshot at a point in time."""
    timestamp: datetime
    presence: bool
    zones: List[FP2Zone]
    targets: List[FP2Target]
    raw_attributes: Dict[str, Any] = field(default_factory=dict)


class FP2Service:
    """Service that integrates Aqara FP2 sensor data via Home Assistant."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._last_snapshot: Optional[FP2Snapshot] = None
        self._listeners: List[asyncio.Queue] = []
        self._ha_token = settings.ha_token
        self._stats = {
            "polls": 0,
            "successful": 0,
            "failed": 0,
            "last_poll_time": None,
            "last_error": None,
        }

    @property
    def last_snapshot(self) -> Optional[FP2Snapshot]:
        return self._last_snapshot

    @property
    def last_error(self) -> Optional[str]:
        return self._stats.get("last_error")

    @property
    def ha_url(self) -> str:
        return self.settings.ha_url.rstrip("/")

    @property
    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._ha_token:
            h["Authorization"] = f"Bearer {self._ha_token}"
        return h

    # ── lifecycle ────────────────────────────────────────────────

    async def initialize(self):
        """Create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        logger.info("FP2 service initialized (HA URL: %s)", self.ha_url)

    async def start(self):
        """Start the polling loop."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("FP2 polling started (interval=%.1fs)", self.settings.fp2_poll_interval)

    async def shutdown(self):
        """Stop polling and close session."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("FP2 service shut down")

    # ── polling ─────────────────────────────────────────────────

    async def _poll_loop(self):
        """Continuously poll HA for FP2 state."""
        while self._running:
            try:
                snapshot = await self.fetch_snapshot()
                if snapshot:
                    self._last_snapshot = snapshot
                    await self._notify_listeners(snapshot)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._stats["failed"] += 1
                self._stats["last_error"] = str(exc)
                logger.error("FP2 poll error: %s", exc)
            await asyncio.sleep(self.settings.fp2_poll_interval)

    def _record_fetch_failure(self, message: str) -> None:
        """Record a handled upstream fetch failure without throwing."""
        self._stats["failed"] += 1
        self._stats["last_error"] = message

    async def fetch_snapshot(self, entity_id: Optional[str] = None) -> Optional[FP2Snapshot]:
        """Fetch current FP2 state from Home Assistant."""
        self._stats["polls"] += 1
        if self._session is None or self._session.closed:
            await self.initialize()
        await self._ensure_ha_token()

        selected_entity = entity_id or self.settings.fp2_entity_id
        url = f"{self.ha_url}/api/states/{selected_entity}"

        try:
            async with self._session.get(url, headers=self.headers) as resp:
                if resp.status == 401:
                    refreshed = await self._refresh_ha_access_token()
                    if refreshed:
                        async with self._session.get(url, headers=self.headers) as retry_resp:
                            if retry_resp.status == 401:
                                message = "ha_auth_failed"
                                self._record_fetch_failure(message)
                                logger.error("HA auth failed after refresh attempt")
                                return None
                            if retry_resp.status == 404:
                                message = f"fp2_entity_not_found:{selected_entity}"
                                self._record_fetch_failure(message)
                                logger.warning("Entity %s not found in HA", selected_entity)
                                return None
                            retry_resp.raise_for_status()
                            data = await retry_resp.json()
                    else:
                        message = "ha_auth_failed"
                        self._record_fetch_failure(message)
                        logger.error("HA auth failed — check HA_TOKEN / HA_REFRESH_TOKEN")
                        return None
                if resp.status == 404:
                    message = f"fp2_entity_not_found:{selected_entity}"
                    self._record_fetch_failure(message)
                    logger.warning("Entity %s not found in HA", selected_entity)
                    return None
                if resp.status != 401:
                    resp.raise_for_status()
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            self._record_fetch_failure(str(exc))
            logger.debug("HA request failed: %s", exc)
            return None

        entity_state = str(data.get("state", "")).lower()
        if entity_state in {"unknown", "unavailable"}:
            message = f"fp2_entity_state_{entity_state}:{selected_entity}"
            self._record_fetch_failure(message)
            logger.warning(
                "FP2 entity %s returned non-live state %s",
                selected_entity,
                entity_state,
            )
            return None

        self._stats["successful"] += 1
        self._stats["last_poll_time"] = utc_now().isoformat()
        self._stats["last_error"] = None

        return self._parse_entity(data)

    # Also try to discover related zone entities
    async def fetch_all_fp2_entities(self) -> List[Dict[str, Any]]:
        """Fetch all entities that look like FP2 zones/targets."""
        if self._session is None or self._session.closed:
            await self.initialize()
        await self._ensure_ha_token()
        url = f"{self.ha_url}/api/states"
        try:
            async with self._session.get(url, headers=self.headers) as resp:
                if resp.status == 401 and await self._refresh_ha_access_token():
                    async with self._session.get(url, headers=self.headers) as retry_resp:
                        retry_resp.raise_for_status()
                        states = await retry_resp.json()
                    return self._filter_fp2_entities(states)
                resp.raise_for_status()
                states = await resp.json()
        except Exception:
            return []
        return self._filter_fp2_entities(states)

    async def _ensure_ha_token(self) -> None:
        """Ensure we have an access token when refresh credentials are available."""
        if self._ha_token:
            return
        await self._refresh_ha_access_token()

    async def _refresh_ha_access_token(self) -> bool:
        """Refresh Home Assistant access token from refresh token."""
        if self._session is None or self._session.closed:
            await self.initialize()
        if not self.settings.ha_refresh_token or not self.settings.ha_client_id:
            return False

        token_url = f"{self.ha_url}/auth/token"
        data = {
            "grant_type": "refresh_token",
            "client_id": self.settings.ha_client_id,
            "refresh_token": self.settings.ha_refresh_token,
        }
        try:
            async with self._session.post(
                token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status != 200:
                    logger.error("HA token refresh failed with HTTP %s", resp.status)
                    return False
                payload = await resp.json()
        except aiohttp.ClientError as exc:
            logger.error("HA token refresh request failed: %s", exc)
            return False

        access_token = payload.get("access_token")
        if not access_token:
            logger.error("HA token refresh response missing access_token")
            return False
        self._ha_token = access_token
        return True

    def _filter_fp2_entities(self, states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return entities that match the FP2 naming pattern."""
        fp2_entities = []
        base_name = self.settings.fp2_entity_id.split(".")[-1].replace("_presence", "")
        for state in states:
            entity_id = state.get("entity_id", "")
            if base_name in entity_id or "fp2" in entity_id.lower():
                fp2_entities.append(state)
        return fp2_entities

    async def recommend_entity_id(self) -> Optional[str]:
        """Pick the most informative FP2-related entity automatically."""
        entities = await self.fetch_all_fp2_entities()
        if not entities:
            return None

        def score(entity: Dict[str, Any]) -> int:
            entity_id = (entity.get("entity_id") or "").lower()
            attrs = entity.get("attributes") or {}
            domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
            s = 0

            # Prefer sensors over helpers/toggles
            if domain == "sensor":
                s += 50
            elif domain == "binary_sensor":
                s += 40
            elif domain == "select":
                s += 20
            elif domain == "input_boolean":
                s -= 20

            # Prefer entities with zone/target-like metadata
            if "zones" in attrs:
                s += 40
            if "targets" in attrs:
                s += 40
            if "target_count" in attrs:
                s += 15
            if "current_zone" in attrs or "zone" in attrs:
                s += 25
            if "occupancy" in attrs or "presence" in entity_id:
                s += 10

            # Penalize clearly synthetic/manual helper
            if "input_boolean.fp2_presence" in entity_id:
                s -= 30
            return s

        entities_sorted = sorted(entities, key=score, reverse=True)
        return entities_sorted[0].get("entity_id")

    # ── parsing ─────────────────────────────────────────────────

    def _parse_entity(self, data: Dict[str, Any]) -> FP2Snapshot:
        """Parse a HA entity state dict into an FP2Snapshot."""
        attrs = data.get("attributes", {})
        state = data.get("state", "off")
        presence = state in ("on", "home", "detected")

        last_updated = None
        if lu := data.get("last_updated"):
            try:
                last_updated = datetime.fromisoformat(lu.replace("Z", "+00:00"))
            except Exception:
                last_updated = utc_now()

        zones = self._parse_zones(attrs)
        targets = self._parse_targets(attrs, zones)

        return FP2Snapshot(
            timestamp=last_updated or utc_now(),
            presence=presence,
            zones=zones,
            targets=targets,
            raw_attributes=attrs,
        )

    def _parse_zones(self, attrs: Dict[str, Any]) -> List[FP2Zone]:
        """Extract zone info from entity attributes."""
        zones: List[FP2Zone] = []

        # FP2 via HomeKit often exposes zones as separate entities,
        # but attributes may contain zone-related info too.
        zone_data = attrs.get("zones", [])
        if isinstance(zone_data, list):
            for i, z in enumerate(zone_data):
                if isinstance(z, dict):
                    zones.append(FP2Zone(
                        zone_id=z.get("id", f"zone_{i}"),
                        name=z.get("name", f"Zone {i}"),
                        occupied=z.get("occupied", False),
                        target_count=z.get("target_count", 0),
                    ))

        # If no structured zone data, create a single default zone
        if not zones:
            zones.append(FP2Zone(
                zone_id="default",
                name="FP2 Detection Area",
                occupied=attrs.get("occupancy", False) or bool(attrs.get("detection", False)),
                target_count=int(attrs.get("target_count", 0)) if attrs.get("target_count") else 0,
            ))

        return zones

    def _parse_targets(self, attrs: Dict[str, Any], zones: List[FP2Zone]) -> List[FP2Target]:
        """Extract detected targets/persons from attributes."""
        targets: List[FP2Target] = []

        target_data = attrs.get("targets", [])
        if isinstance(target_data, list):
            for i, t in enumerate(target_data):
                if isinstance(t, dict):
                    targets.append(FP2Target(
                        target_id=t.get("id", f"person_{i}"),
                        zone_id=t.get("zone_id", zones[0].zone_id if zones else "default"),
                        x=float(t.get("x", 0)),
                        y=float(t.get("y", 0)),
                        distance=float(t.get("distance", 0)),
                        angle=float(t.get("angle", 0)),
                        activity=t.get("activity", "standing"),
                    ))

        # If FP2 just says presence=True but no structured targets,
        # synthesize one target per occupied zone.
        if not targets:
            for z in zones:
                if z.occupied:
                    count = max(z.target_count, 1)
                    for j in range(count):
                        targets.append(FP2Target(
                            target_id=f"person_{z.zone_id}_{j}",
                            zone_id=z.zone_id,
                            activity="standing",
                        ))

        return targets

    # ── conversion to pipeline format ───────────────────────────

    def snapshot_to_pose_data(self, snapshot: Optional[FP2Snapshot] = None) -> Dict[str, Any]:
        """Convert FP2 snapshot into wifi-densepose pose format.

        This produces data compatible with the /api/v1/pose/current response
        so the front-end can consume FP2 and WiFi-CSI data interchangeably.
        """
        snap = snapshot or self._last_snapshot
        if snap is None:
            return {
                "timestamp": utc_now().isoformat(),
                "frame_id": "fp2_no_data",
                "persons": [],
                "zone_summary": {},
                "processing_time_ms": 0,
                "metadata": {"source": "fp2", "presence": False},
            }

        persons = []
        for t in snap.targets:
            persons.append({
                "person_id": t.target_id,
                "confidence": t.confidence,
                "bounding_box": {
                    "x": t.x,
                    "y": t.y,
                    "width": 0.15,
                    "height": 0.4,
                },
                "keypoints": [],  # FP2 doesn't provide skeleton keypoints
                "segmentation": None,
                "zone_id": t.zone_id,
                "activity": t.activity,
                "distance": t.distance,
                "angle": t.angle,
                "timestamp": snap.timestamp.isoformat(),
            })

        zone_summary = {}
        for z in snap.zones:
            if z.occupied:
                zone_summary[z.zone_id] = max(z.target_count, 1)

        return {
            "timestamp": snap.timestamp.isoformat(),
            "frame_id": f"fp2_{int(snap.timestamp.timestamp() * 1000)}",
            "persons": persons,
            "zone_summary": zone_summary,
            "processing_time_ms": 0,
            "metadata": {
                "source": "fp2",
                "presence": snap.presence,
                "sensor": "aqara_fp2",
                "raw_attributes": snap.raw_attributes,
            },
        }

    # ── subscribers ─────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        """Subscribe to real-time FP2 snapshots."""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """Remove a subscription."""
        if q in self._listeners:
            self._listeners.remove(q)

    async def _notify_listeners(self, snapshot: FP2Snapshot):
        """Push snapshot to all subscribers."""
        for q in list(self._listeners):
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:
                pass  # drop if consumer is slow

    # ── status ──────────────────────────────────────────────────

    async def get_status(self) -> Dict[str, Any]:
        if not self.settings.fp2_enabled:
            status = "disabled"
            message = "FP2 integration is disabled"
            upstream_available = False
            stale = False
        elif self.last_error and self.last_snapshot is not None:
            status = "degraded"
            message = "Serving cached FP2 snapshot because upstream is unavailable"
            upstream_available = False
            stale = True
        elif self.last_error:
            status = "upstream_unavailable"
            message = self.last_error
            upstream_available = False
            stale = False
        elif self._running and self.last_snapshot is not None:
            status = "healthy"
            message = "FP2 polling is healthy"
            upstream_available = True
            stale = False
        elif self._running:
            status = "initializing"
            message = "Waiting for first FP2 snapshot"
            upstream_available = None
            stale = False
        elif self.last_snapshot is not None:
            status = "inactive"
            message = "FP2 polling is stopped; cached snapshot is available"
            upstream_available = None
            stale = True
        else:
            status = "inactive"
            message = "FP2 polling is not running"
            upstream_available = None
            stale = False

        return {
            "status": status,
            "running": self._running,
            "message": message,
            "upstream_available": upstream_available,
            "stale": stale,
            "ha_url": self.ha_url,
            "entity_id": self.settings.fp2_entity_id,
            "last_snapshot": self.last_snapshot.timestamp.isoformat() if self.last_snapshot else None,
            "presence": self.last_snapshot.presence if self.last_snapshot else None,
            "stats": self._stats,
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "sensor": "Aqara FP2 mmWave",
            "integration": "Home Assistant REST API",
            "ha_url": self.ha_url,
            "entity_id": self.settings.fp2_entity_id,
            "poll_interval": self.settings.fp2_poll_interval,
        }
