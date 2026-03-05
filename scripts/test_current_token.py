#!/usr/bin/env python3
"""
Test existing token with correct SIGN to verify it still works
If token is invalid, we need to wait for rate limit to expire
"""

import aiohttp
import hashlib
import time
import random
import asyncio

# Current token from .env (may be expired)
ACCESS_TOKEN = "928a72b8088cac5c79473fca295d5523"
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
DEVICE_ID = "54EF4479E003"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str, accesstoken):
    """Generate SIGN using correct Aqara V3.0 algorithm."""
    params = {
        'Accesstoken': accesstoken,
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


async def test_device_state():
    """Test getting device state with current token."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp, ACCESS_TOKEN)
    
    print("=" * 60)
    print("Testing Device State API")
    print("=" * 60)
    print(f"\n🔑 Access Token: {ACCESS_TOKEN[:16]}...{ACCESS_TOKEN[-8:]}")
    print(f"🆔 Device ID: {DEVICE_ID}")
    print(f"📝 SIGN: {sign}")
    print()
    
    headers = {
        "Content-Type": "application/json",
        "Accesstoken": ACCESS_TOKEN,
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
    
    print("🔍 Request: config.device.getState")
    print("-" * 60)
    
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
                print()
                
                if result.get('code') == 0:
                    print("✅ SUCCESS! Token is VALID!")
                    
                    state = result.get('result', {})
                    print(f"\n📊 Device State:")
                    for key, value in state.items():
                        print(f"   {key}: {value}")
                    
                    return True
                    
                elif result.get('code') == 403:
                    print("❌ Token EXPIRED or INVALID (403 Forbidden)")
                    print("\n⚠️  Need to obtain fresh token via login")
                    print("⏳ Wait for rate limit to expire first:")
                    print("   - config.auth.getAuthCode: ~10 minutes")
                    print("   - account.loginByPassword: ~5 minutes")
                    return False
                    
                else:
                    print(f"❌ API Error: {result.get('messageDetail')}")
                    return False
                        
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            return None
    
    return False


if __name__ == "__main__":
    print("\n🚀 Testing current access token...\n")
    result = asyncio.run(test_device_state())
    
    if result:
        print("\n✅ Current token is working!")
        print("Integration should start receiving data soon")
    elif result is False:
        print("\n❌ Token is invalid/expired")
        print("\n📝 Next steps:")
        print("1. Wait 10-15 minutes for rate limits to expire")
        print("2. Run: python3 scripts/get_auth_code.py")
        print("3. Or login via Aqara Home app to refresh tokens")
    else:
        print("\n⚠️  Error occurred during test")
