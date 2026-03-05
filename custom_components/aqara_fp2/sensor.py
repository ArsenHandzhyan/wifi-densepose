"""Sensor platform for Aqara FP2."""

import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, CONF_REGION, CONF_ACCESS_TOKEN, CONF_DEVICE_ID, API_DOMAINS, SCAN_INTERVAL
from .binary_sensor import AqaraDataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Aqara FP2 sensors."""
    
    coordinator = AqaraDataCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()
    
    entities = [
        AqaraFp2LightSensor(coordinator, entry),
        AqaraFp2DistanceSensor(coordinator, entry),
    ]
    
    async_add_entities(entities, True)


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
        
        result = self.coordinator.data.get("result", {})
        params = result.get("params", [])
        
        for param in params:
            if param.get("resId") == "0.2.85":  # Light level resource ID
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
        
        result = self.coordinator.data.get("result", {})
        params = result.get("params", [])
        
        for param in params:
            if param.get("resId") == "0.3.85":  # Distance resource ID (example)
                try:
                    value = float(param.get("value", 0))
                    return round(value / 1000, 2)  # Convert mm to m
                except (ValueError, TypeError):
                    return None
        
        return None
