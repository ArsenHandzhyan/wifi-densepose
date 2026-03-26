"""Aqara FP2 Cloud Integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import COORDINATOR, DOMAIN, PLATFORMS
from .coordinator import AqaraDataCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aqara FP2 from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = AqaraDataCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        COORDINATOR: coordinator,
    }
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
