#!/usr/bin/env python3
"""
Test Aqara API using EXACT format from documentation
"""

import aiohttp
import hashlib
import time
import random
import asyncio

# Credentials from .env
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
ACCESS_TOKEN = "928a72b8088cac5c79473fca295d5523"
DEVICE_ID = "54EF4479E003"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


async def test_api():
    """Test API with exact format from documentation."""
    
    # Generate auth parameters
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign_str = f"{APP_KEY}{nonce}{timestamp}"
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    
    print("=" * 60)
    print("Testing Aqara V3.0 API")
    print("=" * 60)
    print(f"\n📡 URL: {API_URL}")
    print(f"🔑 AppID: {APP_ID}")
    print(f" Access Token: {ACCESS_TOKEN}")
    print(f"🆔 Device ID: {DEVICE_ID}")
    print()
    
    # Headers EXACTLY as in documentation
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
    
    print("📋 Headers:")
    for k, v in headers.items():
        print(f"   {k}: {v[:20]}..." if len(v) > 20 else f"   {k}: {v}")
    print()
    
    # Test different intents
    intents = [
        ("config.device.getList", {}),  # Get all devices
        ("config.device.info", {"did": DEVICE_ID}),  # Get device info
        ("config.device.getState", {"did": DEVICE_ID}),  # Get device state
    ]
    
    async with aiohttp.ClientSession() as session:
        for intent, data in intents:
            print(f"\n🔍 Testing intent: {intent}")
            print("-" * 60)
            
            payload = {
                "intent": intent,
                "data": data,
            }
            
            try:
                async with session.post(API_URL, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    result = await resp.json()
                    
                    print(f"Status: {resp.status}")
                    print(f"Code: {result.get('code')}")
                    print(f"Message: {result.get('message')}")
                    print(f"Detail: {result.get('messageDetail', 'N/A')}")
                    
                    if result.get('code') == 0:
                        print(f"\n✅ SUCCESS!")
                        print(f"Result: {result.get('result', {})}")
                        return True
                    else:
                        print(f"❌ Failed")
                        
            except Exception as e:
                print(f"❌ Error: {type(e).__name__}: {e}")
    
    print("\n" + "=" * 60)
    print("❌ All intents failed")
    print("=" * 60)
    return False


if __name__ == "__main__":
    print("\n🚀 Starting API test...\n")
    result = asyncio.run(test_api())
    
    if result:
        print("\n✅ API is working!")
    else:
        print("\n❌ API still not working - problem is on Aqara side")
