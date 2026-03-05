"""Binary sensor platform for Aqara FP2."""

import asyncio
from datetime import timedelta
import logging
import aiohttp
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from .const import DOMAIN, CONF_REGION, CONF_ACCESS_TOKEN, CONF_DEVICE_ID, API_DOMAINS, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Aqara FP2 binary sensors."""
    
    coordinator = AqaraDataCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()
    
    entities = [
        AqaraFp2OccupancySensor(coordinator, entry),
    ]
    
    async_add_entities(entities, True)


class AqaraDataCoordinator(DataUpdateCoordinator):
    """Data update coordinator for Aqara FP2."""

    def __init__(self, hass: HomeAssistant, config: dict):
        """Initialize the coordinator."""
        self.hass = hass
        self.config = config
        self.region = config.get(CONF_REGION, "europe")
        self.access_token = config.get(CONF_ACCESS_TOKEN)
        self.device_id = config.get(CONF_DEVICE_ID)  # Optional now
        
        # Get API endpoint
        self.api_domain = API_DOMAINS.get(self.region, API_DOMAINS["europe"])
        self.base_url = f"https://{self.api_domain}/v3.0/open/api"
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,  # Already timedelta
        )

    async def _async_update_data(self):
        """Fetch data from Aqara API."""
        try:
            async with aiohttp.ClientSession() as session:
                # Try different intent formats
                intents_to_try = [
                    "config.device.getState",  # Standard format
                    "device.getState",  # Short format
                    "getDeviceState",  # CamelCase
                    "Config.device.getState",  # Capitalized
                ]
                
                for intent in intents_to_try:
                    result = await self._request(session, intent, {
                        "did": self.device_id
                    })
                    
                    if result and result.get("code") == 0:
                        _LOGGER.info(f"Success with intent: {intent}")
                        return result.get("result", {})
                    else:
                        _LOGGER.debug(f"Failed with intent: {intent} - {result}")
                
                # If all failed, log error
                _LOGGER.error(f"All intents failed for device {self.device_id}")
                return {}
                    
        except Exception as err:
            _LOGGER.error(f"Error fetching data: {err}")
            return {}

    async def _request(self, session: aiohttp.ClientSession, intent: str, data: dict = None):
        """Make API request following Aqara V3.0 API specification."""
        import hashlib
        import time
        import random
        
        # App credentials
        app_id = "14781250729668648963a0b3"
        app_key = "uyx84zj5aym4itdkibvecakrfakm8nlp"
        key_id = "K.1478125073038168064"
        
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))
        
        # Generate signature using CORRECT Aqara V3.0 method
        # 1. Collect params: Accesstoken, Appid, Keyid, Nonce, Time
        # 2. Sort alphabetically
        # 3. Concatenate: param=value&param=value
        # 4. Append appKey
        # 5. Lowercase
        # 6. MD5 hash
        params = {
            'Accesstoken': self.access_token,
            'Appid': app_id,
            'Keyid': key_id,
            'Nonce': nonce,
            'Time': timestamp,
        }
        sorted_keys = sorted(params.keys())
        concat_str = '&'.join(f"{key}={params[key]}" for key in sorted_keys)
        concat_str += app_key
        concat_str = concat_str.lower()
        sign = hashlib.md5(concat_str.encode()).hexdigest()
        
        # IMPORTANT: All auth parameters go in HEADERS, not URL!
        headers = {
            "Content-Type": "application/json",
            "Accesstoken": self.access_token,
            "Appid": app_id,
            "Keyid": key_id,
            "Nonce": nonce,
            "Time": timestamp,
            "Sign": sign,
            "Lang": "en",  # Optional but recommended
        }
        
        # URL without query parameters
        url = self.base_url
        
        # Request body with intent and data
        payload = {
            "intent": intent,
            "data": data or {},
        }
        
        _LOGGER.debug(f"URL: {url}")
        _LOGGER.debug(f"Headers: Appid={app_id}, Nonce={nonce}")
        _LOGGER.debug(f"Intent: {intent}")
        _LOGGER.debug(f"Data: {data}")
        
        async with session.post(url, headers=headers, json=payload) as resp:
            result = await resp.json()
            _LOGGER.debug(f"Response code: {result.get('code')}")
            _LOGGER.debug(f"Response msg: {result.get('messageDetail')}")
            return result


class AqaraFp2OccupancySensor(CoordinatorEntity, BinarySensorEntity):
    """Occupancy binary sensor for Aqara FP2."""

    _attr_has_entity_name = True
    _attr_translation_key = "occupancy"

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
        
        # Parse occupancy status from API response
        # This depends on the actual API response structure
        result = self.coordinator.data.get("result", {})
        params = result.get("params", [])
        
        for param in params:
            if param.get("resId") == "0.1.85":  # Occupancy resource ID
                return param.get("value") == "1"
        
        return False
