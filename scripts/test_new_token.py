#!/usr/bin/env python3
"""Test NEW virtual account token"""

import aiohttp
import hashlib
import time
import random
import asyncio

# NEW token from virtual account
ACCESS_TOKEN = "5265202030367e84eb5dd318d3c63604"
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
DEVICE_ID = "54EF4479E003"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str, accesstoken):
    """Generate SIGN with accesstoken."""
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


async def test():
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp, ACCESS_TOKEN)
    
    print("=" * 60)
    print("Testing NEW Virtual Account Token")
    print("=" * 60)
    print(f"\nToken: {ACCESS_TOKEN}")
    print(f"Device: {DEVICE_ID}")
    print(f"SIGN: {sign}")
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
    
    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, headers=headers, json=payload, timeout=10) as resp:
            result = await resp.json()
            
            print(f"Code: {result.get('code')}")
            print(f"Message: {result.get('message')}")
            print(f"Detail: {result.get('messageDetail', 'N/A')}")
            
            if result.get('code') == 0:
                print("\n✅ TOKEN WORKS!")
                state = result.get('result', {})
                for k, v in state.items():
                    print(f"  {k}: {v}")
            else:
                print("\n❌ Token doesn't have device access")
                print("(Virtual account not linked to FP2)")


if __name__ == "__main__":
    asyncio.run(test())
