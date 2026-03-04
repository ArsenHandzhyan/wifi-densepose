#!/usr/bin/env python3
"""
Aqara FP2 клиент с использованием официального SDK.

Документация: https://github.com/aqara/aqara-iot-py-sdk
"""

import json
from aqara_iot import AqaraOpenAPI, AqaraTokenInfo

# === Configuration ===
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"  # Europe
ACCESS_TOKEN = "a234cd38d5c388b23fc5fe8975eb5bc3"

# Country code: Europe
COUNTRY_CODE = "Europe"


def main():
    """Main function."""
    print("=" * 60)
    print("  AQARA FP2 - SDK CLIENT")
    print("=" * 60)
    print()

    # Initialize SDK
    print("🔌 Подключаемся к Aqara Cloud...")
    
    try:
        # Create API instance with country code
        api = AqaraOpenAPI(country_code=COUNTRY_CODE)
        
        # Override with our credentials
        api.app_id = APP_ID
        api.app_key = APP_KEY
        api.key_id = KEY_ID
        
        # Set token directly
        api.access_token = ACCESS_TOKEN
        
        print("✅ Подключение успешно!")
        print()
        
        # Get devices
        print("📱 Получаем список устройств...")
        
        # Use the post method
        result = api.post("/v3.0/open/api", {
            "intent": "config.device.getList",
            "data": {}
        })
        print(f"Ответ: {json.dumps(result, indent=2) if result else 'None'}")
        
        if not result or result.get("code") != 0:
            print(f"❌ Ошибка API: {result}")
            return
        
        devices = result.get("result", {}).get("data", [])
        
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
            
            state = api.query("config.device.getState", {"did": did})
            print(f"Состояние: {json.dumps(state, indent=2) if state else 'None'}")
            
        else:
            print("⚠️  FP2 не найден в списке устройств")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
