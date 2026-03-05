#!/usr/bin/env python3
"""
Generate SIGN using CORRECT Aqara V3.0 API rules
Based on: https://opendoc.aqara.com/en/docs/developmanual/apiIntroduction/signGenerationRules.html
"""

import hashlib
import time
import random
import aiohttp
import asyncio

# Credentials
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
ACCESS_TOKEN = "928a72b8088cac5c79473fca295d5523"
DEVICE_ID = "54EF4479E003"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign_correct(appid, keyid, nonce, time_str, accesstoken=None):
    """
    Generate SIGN according to Aqara V3.0 rules:
    1. Collect parameters: Accesstoken (optional), Appid, Keyid, Nonce, Time
    2. Sort by ASCII code
    3. Concatenate: param=value&param=value...
    4. Append appKey
    5. Convert to lowercase
    6. MD5 hash
    """
    
    # Step 1: Collect parameters (without accesstoken for some requests)
    params = {
        'Appid': appid,
        'Keyid': keyid,
        'Nonce': nonce,
        'Time': time_str,
    }
    
    # Add accesstoken if provided
    if accesstoken:
        params['Accesstoken'] = accesstoken
    
    # Step 2: Sort by ASCII code (alphabetically)
    sorted_keys = sorted(params.keys())
    
    # Step 3: Concatenate as param=value&param=value
    concat_str = '&'.join(f"{key}={params[key]}" for key in sorted_keys)
    
    # Step 4: Append appKey
    concat_str += APP_KEY
    
    # Step 5: Convert to lowercase
    concat_str = concat_str.lower()
    
    # Step 6: MD5 hash
    sign = hashlib.md5(concat_str.encode()).hexdigest()
    
    return sign, concat_str


async def test_api():
    """Test API with correct SIGN generation."""
    
    # Generate auth parameters
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    
    # Generate SIGN using correct method
    sign, sign_input = generate_sign_correct(
        appid=APP_ID,
        keyid=KEY_ID,
        nonce=nonce,
        time_str=timestamp,
        accesstoken=ACCESS_TOKEN
    )
    
    print("=" * 60)
    print("Testing Aqara V3.0 API with CORRECT SIGN generation")
    print("=" * 60)
    print(f"\n📡 URL: {API_URL}")
    print(f"🔑 AppID: {APP_ID}")
    print(f" Access Token: {ACCESS_TOKEN}")
    print(f"🆔 Device ID: {DEVICE_ID}")
    print()
    print(f"📝 SIGN Input String:")
    print(f"   {sign_input}")
    print(f"\n🔐 Generated SIGN: {sign}")
    print()
    
    # Headers
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
    
    # Test getting device list
    payload = {
        "intent": "config.device.getList",
        "data": {}
    }
    
    print("🔍 Testing intent: config.device.getList")
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
                
                if result.get('code') == 0:
                    print(f"\n✅ SUCCESS!")
                    devices = result.get('result', {}).get('deviceList', [])
                    print(f"Found {len(devices)} device(s)")
                    
                    for dev in devices:
                        print(f"  - {dev.get('name')} ({dev.get('did')})")
                    
                    return True
                else:
                    print(f"❌ Failed")
                    
                    if result.get('code') == 106:
                        print("\n⚠️  Signature still doesn't match!")
                        print("ClientSign vs ServerSign mismatch")
                    
                    return False
                        
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            return None
    
    return False


if __name__ == "__main__":
    print("\n🚀 Starting API test with correct SIGN...\n")
    result = asyncio.run(test_api())
    
    if result:
        print("\n✅ API is working with correct SIGN generation!")
    elif result is False:
        print("\n❌ Still failing - need to debug further")
    else:
        print("\n⚠️  Error occurred")
