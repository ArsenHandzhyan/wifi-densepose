#!/usr/bin/env python3
"""
Aqara FP2 Device Discovery - Working Version
Gets device list from Aqara Cloud API
"""

import asyncio
import hashlib
import json
import random
import time
import aiohttp

# Configuration
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
ACCESS_TOKEN = "928a72b8088cac5c79473fca295d5523"  # Europe token
API_DOMAIN = "open-ger.aqara.com"  # Europe


async def get_devices():
    """Get device list from Aqara Cloud API."""
    
    # Generate signature
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign_str = f"{APP_KEY}{nonce}{timestamp}"
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    
    # Build URL with query parameters
    base_url = f"https://{API_DOMAIN}/v3.0/open/api"
    params = {
        "appid": APP_ID,
        "keyid": KEY_ID,
        "nonce": nonce,
        "time": timestamp,
        "sign": sign,
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accesstoken": ACCESS_TOKEN,
    }
    
    payload = {
        "intent": "config.device.getList",
        "data": {}
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            # Make request with proper URL encoding
            async with session.post(
                base_url,
                params=params,
                headers=headers,
                json=payload
            ) as resp:
                result = await resp.json()
                
                print("=" * 60)
                print("AQARA CLOUD API - DEVICE LIST")
                print("=" * 60)
                print(f"\nResponse code: {result.get('code')}")
                print(f"Message: {result.get('message', 'Success')}")
                
                if result.get('code') == 0:
                    devices = result.get('result', {}).get('data', [])
                    
                    if not devices:
                        print("\n❌ No devices found!")
                        print("\nPossible reasons:")
                        print("1. FP2 not added to Aqara Home app yet")
                        print("2. Wrong account/region")
                        print("3. FP2 offline or in pairing mode")
                    else:
                        print(f"\n✅ Found {len(devices)} device(s):\n")
                        
                        for i, device in enumerate(devices, 1):
                            did = device.get('did', 'N/A')
                            name = device.get('deviceName', 'Unknown')
                            model = device.get('model', 'N/A')
                            state = device.get('state', 0)
                            
                            print(f"{i}. {name}")
                            print(f"   Device ID: {did}")
                            print(f"   Model: {model}")
                            print(f"   State: {'🟢 Online' if state == 1 else '🔴 Offline'}")
                            print()
                            
                            # Highlight FP2 devices
                            if 'fp2' in name.lower() or 'presence' in name.lower() or 'lumi.sensor_occupy' in model.lower():
                                print(f"   ⭐ THIS IS YOUR FP2!")
                                print(f"   → Use Device ID: {did} in Home Assistant integration")
                                print()
                    
                    return devices
                else:
                    print(f"\n❌ API Error: {result.get('messageDetail', 'Unknown error')}")
                    print("\nPossible solutions:")
                    print("1. Check if Access Token is valid")
                    print("2. Verify region (Europe/Germany)")
                    print("3. Check App Key in Aqara Dev Platform")
                    return []
                    
        except Exception as e:
            print(f"\n❌ Request failed: {e}")
            print("\nCheck your internet connection and try again.")
            return []


if __name__ == "__main__":
    print("\n📱 Fetching devices from Aqara Cloud...\n")
    asyncio.run(get_devices())
