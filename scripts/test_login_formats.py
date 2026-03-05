#!/usr/bin/env python3
"""
Try different login request formats to find working one
"""

import aiohttp
import hashlib
import time
import random
import asyncio

EMAIL = "arsenhandzan442@gmail.com"
PASSWORD = "Arsen2576525005@"

APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str):
    """Generate SIGN."""
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


async def test_login_format(format_name, payload_data):
    """Test specific login format."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print(f"\n{'='*60}")
    print(f"Testing: {format_name}")
    print(f"{'='*60}")
    
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
        "intent": "account.loginByPassword",
        "data": payload_data,
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
                
                code = result.get('code')
                message = result.get('message', '')
                
                print(f"Code: {code}")
                print(f"Message: {message}")
                
                if code == 0:
                    print(f"\n✅ SUCCESS with format: {format_name}!")
                    print(f"Result: {result.get('result', {})}")
                    return True
                else:
                    detail = result.get('messageDetail', '')
                    print(f"Detail: {detail[:200] if detail else 'N/A'}")
                    return False
                    
        except Exception as e:
            print(f"❌ Error: {e}")
            return False


async def main():
    print("\n🚀 Testing different login request formats...\n")
    
    # Format 1: account + password (strings)
    format1 = {
        "account": EMAIL,
        "password": PASSWORD,
    }
    
    # Format 2: email + pwd
    format2 = {
        "email": EMAIL,
        "pwd": PASSWORD,
    }
    
    # Format 3: accountType + account + password
    format3 = {
        "accountType": 0,
        "account": EMAIL,
        "password": PASSWORD,
    }
    
    # Format 4: Just account (no password - uses auth code)
    format4 = {
        "account": EMAIL,
        "accountType": 0,
    }
    
    formats = [
        ("account+password", format1),
        ("email+pwd", format2),
        ("accountType+account+password", format3),
        ("account+accountType (no password)", format4),
    ]
    
    for name, data in formats:
        success = await test_login_format(name, data)
        if success:
            print(f"\n🎯 Found working format: {name}")
            return
    
    print("\n⚠️  All formats failed")
    print("\n💡 Alternative: Login via Aqara Home app on phone")


if __name__ == "__main__":
    asyncio.run(main())
