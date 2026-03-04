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
        self._stats = {
            "polls": 0,
            "successful": 0,
            "failed": 0,
            "last_poll_time": None,
            "last_error": None,
        }

    @property
    def ha_url(self) -> str:
        return self.settings.ha_url.rstrip("/")

    @property
    def headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.settings.ha_token:
            h["Authorization"] = f"Bearer {self.settings.ha_token}"
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

    async def fetch_snapshot(self, entity_id: Optional[str] = None) -> Optional[FP2Snapshot]:
        """Fetch current FP2 state from Home Assistant."""
        self._stats["polls"] += 1
        if self._session is None or self._session.closed:
            await self.initialize()

        selected_entity = entity_id or self.settings.fp2_entity_id
        url = f"{self.ha_url}/api/states/{selected_entity}"

        try:
            async with self._session.get(url, headers=self.headers) as resp:
                if resp.status == 401:
                    logger.error("HA auth failed — check HA_TOKEN")
                    return None
                if resp.status == 404:
                    logger.warning("Entity %s not found in HA", selected_entity)
                    return None
                resp.raise_for_status()
                data = await resp.json()
        except aiohttp.ClientError as exc:
            logger.debug("HA request failed: %s", exc)
            return None

        self._stats["successful"] += 1
        self._stats["last_poll_time"] = datetime.utcnow().isoformat()

        return self._parse_entity(data)

    # Also try to discover related zone entities
    async def fetch_all_fp2_entities(self) -> List[Dict[str, Any]]:
        """Fetch all entities that look like FP2 zones/targets."""
        if self._session is None or self._session.closed:
            await self.initialize()
        url = f"{self.ha_url}/api/states"
        try:
            async with self._session.get(url, headers=self.headers) as resp:
                resp.raise_for_status()
                states = await resp.json()
        except Exception:
            return []

        fp2_entities = []
        base_name = self.settings.fp2_entity_id.split(".")[-1].replace("_presence", "")
        for s in states:
            eid = s.get("entity_id", "")
            if base_name in eid or "fp2" in eid.lower():
                fp2_entities.append(s)
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
                last_updated = datetime.utcnow()

        zones = self._parse_zones(attrs)
        targets = self._parse_targets(attrs, zones)

        return FP2Snapshot(
            timestamp=last_updated or datetime.utcnow(),
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
                "timestamp": datetime.utcnow().isoformat(),
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
        return {
            "status": "healthy" if self._running else "stopped",
            "running": self._running,
            "ha_url": self.ha_url,
            "entity_id": self.settings.fp2_entity_id,
            "last_snapshot": self._last_snapshot.timestamp.isoformat() if self._last_snapshot else None,
            "presence": self._last_snapshot.presence if self._last_snapshot else None,
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
