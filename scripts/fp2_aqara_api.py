#!/usr/bin/env python3
"""
Aqara Cloud API клиент для FP2 Presence Sensor.

Использует Aqara Open API для получения данных с FP2.
"""

import asyncio
import hashlib
import json
import random
import time
from typing import Any, Dict, List, Optional

import aiohttp

# === Configuration ===
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"  # Europe
ACCESS_TOKEN = "a234cd38d5c388b23fc5fe8975eb5bc3"

# Server endpoints
DOMAINS = {
    "China": "open-cn.aqara.com",
    "Europe": "open-ger.aqara.com",
    "USA": "open-usa.aqara.com",
    "Russia": "open-rus.aqara.com",
    "Singapore": "open-sgp.aqara.com",
    "Korea": "open-kor.aqara.com",
}

DOMAIN = DOMAINS["Europe"]  # Выберите ваш регион
BASE_URL = f"https://{DOMAIN}/v3.0/open/api"


class AqaraAPI:
    """Aqara Cloud API client."""

    def __init__(self, app_id: str, app_key: str, key_id: str, access_token: str):
        self.app_id = app_id
        self.app_key = app_key
        self.key_id = key_id
        self.access_token = access_token
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    def _generate_sign(self, nonce: str, timestamp: str) -> str:
        """Generate API signature."""
        sign_str = f"{self.app_key}{nonce}{timestamp}"
        return hashlib.md5(sign_str.encode()).hexdigest()

    async def _request(self, intent: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make API request."""
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))

        # Build full URL with query params
        params = {
            "appid": self.app_id,
            "keyid": self.key_id,
            "nonce": nonce,
            "time": timestamp,
            "sign": self._generate_sign(nonce, timestamp),
        }
        
        # Build URL manually to ensure proper encoding
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{BASE_URL}?{query_string}"

        # Request body
        payload = {
            "intent": intent,
            "data": data or {},
        }

        # Headers with AccessToken
        headers = {
            "Content-Type": "application/json",
            "Accesstoken": self.access_token,
        }

        async with self.session.post(url, headers=headers, json=payload) as resp:
            result = await resp.json()
            return result

    async def get_devices(self) -> List[Dict[str, Any]]:
        """Get list of devices."""
        result = await self._request("config.device.getList")
        if result.get("code") == 0:
            return result.get("result", {}).get("data", [])
        print(f"Error getting devices: {result}")
        return []

    async def get_device_state(self, device_id: str) -> Dict[str, Any]:
        """Get device state."""
        result = await self._request(
            "config.device.getState", {"did": device_id}
        )
        return result

    async def query_resource(self, device_id: str, resource_id: str) -> Dict[str, Any]:
        """Query device resource (e.g., occupancy, light level)."""
        result = await self._request(
            "config.resource.query",
            {
                "did": device_id,
                "resourceId": resource_id,
            },
        )
        return result


async def main():
    """Main function."""
    print("=" * 60)
    print("  AQARA FP2 - CLOUD API CLIENT")
    print("=" * 60)
    print()

    # Check if App Key is set
    if not APP_KEY:
        print("❌ ОШИБКА: Нужно указать APP_KEY!")
        print()
        print("Получите App Key:")
        print("1. Перейдите в DEMO APPLICATION")
        print("2. Нажмите 'Key management'")
        print("3. Скопируйте App Key")
        print()
        print("Затем обновите переменную APP_KEY в этом скрипте")
        return

    async with AqaraAPI(APP_ID, APP_KEY, KEY_ID, ACCESS_TOKEN) as api:
        print("📱 Получаем список устройств...")
        devices = await api.get_devices()

        if not devices:
            print("❌ Устройства не найдены")
            return

        print(f"✅ Найдено {len(devices)} устройств:")
        print()

        fp2_device = None

        for device in devices:
            did = device.get("did", "N/A")
            name = device.get("deviceName", "Unknown")
            model = device.get("model", "Unknown")
            state = device.get("state", 0)

            print(f"  📦 {name}")
            print(f"     ID: {did}")
            print(f"     Model: {model}")
            print(f"     State: {'🟢 Online' if state == 1 else '🔴 Offline'}")
            print()

            # Find FP2
            if "FP2" in model.upper() or "presence" in name.lower():
                fp2_device = device

        if fp2_device:
            print("=" * 60)
            print("  FP2 НАЙДЕН!")
            print("=" * 60)
            print()

            did = fp2_device.get("did")
            print(f"Запрашиваем состояние FP2 ({did})...")

            state = await api.get_device_state(did)
            print(f"Состояние: {json.dumps(state, indent=2)}")

            # Query common resources
            resources = [
                "0.1.85",  # occupancy
                "0.2.85",  # light level
                "0.3.85",  # motion
            ]

            print()
            print("📊 Данные сенсоров:")
            for res_id in resources:
                result = await api.query_resource(did, res_id)
                print(f"  {res_id}: {result}")

        else:
            print("⚠️  FP2 не найден в списке устройств")
            print()
            print("Убедитесь что:")
            print("1. FP2 добавлен в Aqara Home")
            print("2. FP2 онлайн")
            print("3. Используется правильный аккаунт")


if __name__ == "__main__":
    asyncio.run(main())
