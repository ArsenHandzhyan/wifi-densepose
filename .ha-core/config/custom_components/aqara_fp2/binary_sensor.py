"""Binary sensor platform for Aqara FP2."""

import logging
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    COORDINATOR,
    DOMAIN,
    RESOURCE_GLOBAL_OCCUPANCY,
    ZONE_OCCUPANCY_PREFIX,
    ZONE_OCCUPANCY_SUFFIX,
)
from .coordinator import AqaraDataCoordinator, extract_params
from .payload_parser import extract_targets

_LOGGER = logging.getLogger(__name__)

MAX_ZONES = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Aqara FP2 binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    entities = [
        AqaraFp2OccupancySensor(coordinator, entry),
    ]

    # Add per-zone binary occupancy sensors
    if coordinator.data:
        params = extract_params(coordinator.data)
        for param in params:
            res_id = param.get("resId", "")
            zone_idx = _parse_zone_index(res_id)
            if zone_idx is not None:
                entities.append(
                    AqaraFp2ZoneOccupancySensor(coordinator, entry, zone_idx)
                )

    async_add_entities(entities)


def _parse_zone_index(res_id: str) -> int | None:
    """Parse zone index from resource ID like '13.1.85'."""
    if not res_id.startswith(ZONE_OCCUPANCY_PREFIX):
        return None
    if not res_id.endswith(ZONE_OCCUPANCY_SUFFIX):
        return None
    middle = res_id[len(ZONE_OCCUPANCY_PREFIX) : -len(ZONE_OCCUPANCY_SUFFIX)]
    try:
        idx = int(middle)
        if 1 <= idx <= MAX_ZONES:
            return idx
    except ValueError:
        pass
    return None


class AqaraFp2OccupancySensor(CoordinatorEntity, BinarySensorEntity):
    """Global occupancy binary sensor for Aqara FP2."""

    _attr_has_entity_name = True
    _attr_translation_key = "occupancy"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: AqaraDataCoordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_occupancy"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Aqara FP2",
            "manufacturer": "Aqara",
            "model": "FP2 Presence Sensor",
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if occupancy is detected."""
        if not self.coordinator.data:
            return None

        params = extract_params(self.coordinator.data)
        for param in params:
            if param.get("resId") == RESOURCE_GLOBAL_OCCUPANCY:
                return param.get("value") == "1"

        return False

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose structured target/zone metadata for downstream consumers."""
        if not self.coordinator.data:
            return None

        params = extract_params(self.coordinator.data)
        zones = []
        target_count = 0
        for param in params:
            res_id = param.get("resId", "")
            zone_idx = _parse_zone_index(res_id)
            if zone_idx is None:
                continue
            occupied = param.get("value") == "1"
            if occupied:
                target_count += 1
            zones.append(
                {
                    "id": f"zone_{zone_idx}",
                    "name": f"Zone {zone_idx}",
                    "occupied": occupied,
                    "target_count": 1 if occupied else 0,
                }
            )

        targets = extract_targets(params)
        if targets:
            target_count = len(targets)

        return {
            "occupancy": bool(self.is_on),
            "target_count": target_count,
            "zones": zones,
            "targets": targets,
            "aqara_param_count": len(params),
        }


class AqaraFp2ZoneOccupancySensor(CoordinatorEntity, BinarySensorEntity):
    """Per-zone occupancy binary sensor for Aqara FP2."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(
        self,
        coordinator: AqaraDataCoordinator,
        entry: ConfigEntry,
        zone_idx: int,
    ):
        """Initialize the zone occupancy sensor."""
        super().__init__(coordinator)
        self._zone_idx = zone_idx
        self._res_id = f"13.{zone_idx}.85"
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_idx}_occupancy"
        self._attr_translation_key = f"zone_{zone_idx}_occupancy"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Aqara FP2",
            "manufacturer": "Aqara",
            "model": "FP2 Presence Sensor",
        }

    @property
    def name(self) -> str:
        """Return the name of the zone sensor."""
        return f"Zone {self._zone_idx} Occupancy"

    @property
    def is_on(self) -> bool | None:
        """Return true if presence detected in this zone."""
        if not self.coordinator.data:
            return None

        params = extract_params(self.coordinator.data)
        for param in params:
            if param.get("resId") == self._res_id:
                return param.get("value") == "1"

        return False
