#!/usr/bin/env python3
"""
Aqara FP2 Device Discovery - Fixed Version with proper AppID handling
"""

import asyncio
import hashlib
import json
import random
import time
import aiohttp

# Configuration - Europe Region
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
ACCESS_TOKEN = "928a72b8088cac5c79473fca295d5523"  # Europe token (valid until 2026-03-11)
API_DOMAIN = "open-ger.aqara.com"  # Europe


def generate_sign(nonce: str, timestamp: str) -> str:
    """Generate API signature."""
    sign_str = f"{APP_KEY}{nonce}{timestamp}"
    return hashlib.md5(sign_str.encode()).hexdigest()


async def get_devices():
    """Get device list from Aqara Cloud API with proper parameter handling."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(nonce, timestamp)
    
    base_url = f"https://{API_DOMAIN}/v3.0/open/api"
    
    # Build query parameters
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
    
    print("=" * 60)
    print("AQARA CLOUD API - DEVICE DISCOVERY")
    print("=" * 60)
    print(f"\n📡 Endpoint: https://{API_DOMAIN}")
    print(f"🔑 App ID: {APP_ID}")
    print(f"🎫 Access Token: {ACCESS_TOKEN[:8]}...{ACCESS_TOKEN[-8:]}")
    print(f"⏰ Timestamp: {timestamp}")
    print()
    
    async with aiohttp.ClientSession() as session:
        try:
            print("📡 Sending request to Aqara Cloud API...")
            
            # IMPORTANT: Pass parameters in URL query string, not just in params
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{base_url}?{query_string}"
            
            print(f"🔗 URL: {full_url[:100]}...")
            print()
            
            async with session.post(
                full_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                
                print(f"📊 Response Code: {result.get('code')}")
                print(f"💬 Message: {result.get('message', 'Success')}")
                
                if result.get('code') == 0:
                    devices = result.get('result', {}).get('data', [])
                    
                    if not devices:
                        print("\n❌ No devices found!")
                        print("\nPossible reasons:")
                        print("  1. FP2 not added to Aqara Home app yet")
                        print("  2. Wrong account/region (check if Germany/Europe)")
                        print("  3. Device offline or in pairing mode")
                        print("  4. Token expired (check validity)")
                    else:
                        print(f"\n✅ FOUND {len(devices)} DEVICE(S):\n")
                        
                        fp2_device = None
                        
                        for i, device in enumerate(devices, 1):
                            did = device.get('did', 'N/A')
                            name = device.get('deviceName', 'Unknown')
                            model = device.get('model', 'N/A')
                            state = device.get('state', 0)
                            
                            print(f"{i}. 📱 {name}")
                            print(f"   Device ID: {did}")
                            print(f"   Model: {model}")
                            print(f"   State: {'🟢 Online' if state == 1 else '🔴 Offline'}")
                            print()
                            
                            # Check if this is FP2
                            if ('fp2' in name.lower() or 
                                'presence' in name.lower() or 
                                'lumi.sensor_occupy' in model.lower() or
                                'agl1' in model.lower()):
                                fp2_device = device
                                print(f"   ⭐ THIS IS YOUR FP2!")
                                print(f"   → COPY Device ID: {did}")
                                print(f"   → Add this to Home Assistant integration config")
                                print()
                        
                        # Return FP2 device if found
                        return fp2_device
                    
                elif result.get('code') == 302:
                    print(f"\n❌ API Error 302: {result.get('messageDetail', 'Unknown error')}")
                    print("\n🔧 Troubleshooting:")
                    print("  1. Check if Access Token is valid and not expired")
                    print("  2. Verify region matches your Aqara Home app (Europe/Germany)")
                    print("  3. Check App Key in Aqara Dev Platform")
                    print("  4. Try refreshing the token")
                else:
                    print(f"\n❌ API Error: {result.get('messageDetail', 'Unknown error')}")
                    
                return None
                    
        except asyncio.TimeoutError:
            print("\n❌ Request timed out!")
            print("Check your internet connection and try again.")
        except Exception as e:
            print(f"\n❌ Request failed: {type(e).__name__}: {e}")
            print("\nCheck your internet connection and try again.")
        
        return None


if __name__ == "__main__":
    print("\n🚀 Starting Aqara FP2 Device Discovery...\n")
    result = asyncio.run(get_devices())
    
    if result:
        print("\n" + "=" * 60)
        print("✅ SUCCESS! FP2 device found!")
        print("=" * 60)
        print(f"\nDevice ID: {result.get('did')}")
        print(f"Name: {result.get('deviceName')}")
        print(f"Model: {result.get('model')}")
        print("\nNext steps:")
        print("1. Copy the Device ID above")
        print("2. In Home Assistant: Settings → Devices & Services")
        print("3. Find 'Aqara FP2 (europe)' integration")
        print("4. Click Configure and add the Device ID")
        print("5. Save and wait for entities to update")
    else:
        print("\n" + "=" * 60)
        print("❌ FAILED to find FP2 device")
        print("=" * 60)
        print("\nMake sure:")
        print("1. FP2 is added to Aqara Home app on your phone")
        print("2. FP2 is online (not blinking/pairing mode)")
        print("3. You're using the correct region (Europe/Germany)")
        print("4. Your Aqara account credentials are correct")
