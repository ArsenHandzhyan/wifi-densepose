"""Sensor platform for Aqara FP2."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR, DOMAIN
from .coordinator import AqaraDataCoordinator, extract_params

# FP2 zone resource IDs: "13.x.85" where x = zone index (1-30)
ZONE_PRESENCE_PREFIX = "13."
ZONE_PRESENCE_SUFFIX = ".85"
MAX_ZONES = 30


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Aqara FP2 sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    entities = [
        AqaraFp2LightSensor(coordinator, entry),
        AqaraFp2DistanceSensor(coordinator, entry),
        AqaraFp2ZoneCountSensor(coordinator, entry),
    ]

    # Discover zone sensors from current data
    if coordinator.data:
        params = extract_params(coordinator.data)
        for param in params:
            res_id = param.get("resId", "")
            zone_idx = _parse_zone_index(res_id)
            if zone_idx is not None:
                entities.append(
                    AqaraFp2ZonePresenceSensor(coordinator, entry, zone_idx)
                )

    async_add_entities(entities)


def _parse_zone_index(res_id: str) -> int | None:
    """Parse zone index from resource ID like '13.1.85'."""
    if not res_id.startswith(ZONE_PRESENCE_PREFIX):
        return None
    if not res_id.endswith(ZONE_PRESENCE_SUFFIX):
        return None
    middle = res_id[len(ZONE_PRESENCE_PREFIX) : -len(ZONE_PRESENCE_SUFFIX)]
    try:
        idx = int(middle)
        if 1 <= idx <= MAX_ZONES:
            return idx
    except ValueError:
        pass
    return None


class AqaraFp2LightSensor(CoordinatorEntity, SensorEntity):
    """Light level sensor for Aqara FP2."""

    _attr_has_entity_name = True
    _attr_translation_key = "light_level"
    _attr_native_unit_of_measurement = "lx"
    _attr_device_class = "illuminance"

    def __init__(self, coordinator: AqaraDataCoordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_light_level"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Aqara FP2",
            "manufacturer": "Aqara",
            "model": "FP2 Presence Sensor",
        }

    @property
    def native_value(self) -> float | None:
        """Return the light level in lux."""
        if not self.coordinator.data:
            return None

        params = extract_params(self.coordinator.data)
        for param in params:
            if param.get("resId") == "0.2.85":
                try:
                    return float(param.get("value", 0))
                except (ValueError, TypeError):
                    return None

        return None


class AqaraFp2DistanceSensor(CoordinatorEntity, SensorEntity):
    """Distance sensor for Aqara FP2."""

    _attr_has_entity_name = True
    _attr_translation_key = "distance"
    _attr_native_unit_of_measurement = "m"
    _attr_device_class = "distance"

    def __init__(self, coordinator: AqaraDataCoordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_distance"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Aqara FP2",
            "manufacturer": "Aqara",
            "model": "FP2 Presence Sensor",
        }

    @property
    def native_value(self) -> float | None:
        """Return the distance in meters."""
        if not self.coordinator.data:
            return None

        params = extract_params(self.coordinator.data)
        for param in params:
            if param.get("resId") == "0.3.85":
                try:
                    value = float(param.get("value", 0))
                    return round(value / 1000, 2)
                except (ValueError, TypeError):
                    return None

        return None


class AqaraFp2ZoneCountSensor(CoordinatorEntity, SensorEntity):
    """Total number of people detected across all zones."""

    _attr_has_entity_name = True
    _attr_translation_key = "zone_count"
    _attr_native_unit_of_measurement = "people"
    _attr_icon = "mdi:account-group"

    def __init__(self, coordinator: AqaraDataCoordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_zone_count"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Aqara FP2",
            "manufacturer": "Aqara",
            "model": "FP2 Presence Sensor",
        }

    @property
    def native_value(self) -> int | None:
        """Return number of zones with presence detected."""
        if not self.coordinator.data:
            return None

        params = extract_params(self.coordinator.data)
        count = 0
        for param in params:
            res_id = param.get("resId", "")
            if _parse_zone_index(res_id) is not None:
                if param.get("value") == "1":
                    count += 1
        return count


class AqaraFp2ZonePresenceSensor(CoordinatorEntity, SensorEntity):
    """Per-zone presence state sensor (reports 0/1 as int for easy graphing)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:motion-sensor"

    def __init__(
        self,
        coordinator: AqaraDataCoordinator,
        entry: ConfigEntry,
        zone_idx: int,
    ):
        """Initialize the zone sensor."""
        super().__init__(coordinator)
        self._zone_idx = zone_idx
        self._res_id = f"13.{zone_idx}.85"
        self._attr_unique_id = f"{entry.entry_id}_zone_{zone_idx}"
        self._attr_translation_key = f"zone_{zone_idx}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Aqara FP2",
            "manufacturer": "Aqara",
            "model": "FP2 Presence Sensor",
        }

    @property
    def name(self) -> str:
        """Return the name of the zone sensor."""
        return f"Zone {self._zone_idx}"

    @property
    def native_value(self) -> int | None:
        """Return 1 if presence detected in this zone, 0 otherwise."""
        if not self.coordinator.data:
            return None

        params = extract_params(self.coordinator.data)
        for param in params:
            if param.get("resId") == self._res_id:
                return 1 if param.get("value") == "1" else 0

        return 0
