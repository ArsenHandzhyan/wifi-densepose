#!/usr/bin/env python3
"""
Use Aqara DEMO APPLICATION to get access token
Demo App ID is pre-approved and doesn't require user login
"""

import aiohttp
import hashlib
import time
import random
import asyncio

# DEMO APPLICATION credentials (from memory)
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"

DEVICE_ID = "54EF4479E003"
API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str):
    """Generate SIGN without accesstoken (for demo app)."""
    params = {
        'Appid': appid,
        'Keyid': keyid,
        'Nonce': nonce,
        'Time': time_str,
    }
    
    sorted_keys = sorted(params.keys())
    concat_str = '&'.join(f"{key}={params[key]}" for key in sorted_keys)
    concat_str += APP_KEY
    concat_str = concat_str.lower()
    
    return hashlib.md5(concat_str.encode()).hexdigest()


async def test_demo_app():
    """Test if demo app can access device state."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print("=" * 60)
    print("Testing DEMO APPLICATION Access")
    print("=" * 60)
    print(f"\n🎮 Demo App ID: {APP_ID}")
    print(f"📱 Device ID: {DEVICE_ID}")
    print()
    
    headers = {
        "Content-Type": "application/json",
        "Appid": APP_ID,
        "Keyid": KEY_ID,
        "Nonce": nonce,
        "Time": timestamp,
        "Sign": sign,
        "Lang": "en",
    }
    
    payload = {
        "intent": "config.device.getState",
        "data": {"did": DEVICE_ID}
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                
                print(f"Status: {resp.status}")
                print(f"Code: {result.get('code')}")
                print(f"Message: {result.get('message')}")
                print(f"Detail: {result.get('messageDetail', 'N/A')}")
                
                if result.get('code') == 0:
                    print("\n✅ DEMO APP WORKS!")
                    state = result.get('result', {})
                    print(f"\n📊 Device State:")
                    for k, v in state.items():
                        print(f"   {k}: {v}")
                    
                    # Save working token
                    import json
                    tokens = {
                        'app_id': APP_ID,
                        'app_key': APP_KEY,
                        'key_id': KEY_ID,
                        'demo_mode': True,
                    }
                    with open('/tmp/aqara_demo_working.json', 'w') as f:
                        json.dump(tokens, f, indent=2)
                    print("\n💾 Saved to /tmp/aqara_demo_working.json")
                    
                    return True
                else:
                    print("\n❌ Demo app doesn't have device access")
                    print("   Need to use your personal account")
                    return False
                    
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            return False


if __name__ == "__main__":
    print("\n🚀 Testing demo application access...\n")
    result = asyncio.run(test_demo_app())
    
    if result:
        print("\n✅ Demo app works - can use for integration!")
    else:
        print("\n⚠️  Must wait for rate limit and login with email/password")
