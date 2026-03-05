#!/usr/bin/env python3
"""
Test SIGN generation WITHOUT accesstoken parameter
For authentication requests (login, create account, etc.)
"""

import hashlib
import time
import random
import aiohttp
import asyncio

APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign_without_token(appid, keyid, nonce, time_str):
    """Generate SIGN WITHOUT accesstoken (for auth requests)."""
    
    # Method 1: Only 4 params (no accesstoken)
    params1 = {
        'Appid': appid,
        'Keyid': keyid,
        'Nonce': nonce,
        'Time': time_str,
    }
    
    sorted_keys = sorted(params1.keys())
    concat_str = '&'.join(f"{key}={params1[key]}" for key in sorted_keys)
    concat_str += APP_KEY
    concat_str = concat_str.lower()
    
    sign1 = hashlib.md5(concat_str.encode()).hexdigest()
    
    # Method 2: Maybe appKey is not included when no token?
    concat_str2 = '&'.join(f"{key}={params1[key]}" for key in sorted_keys)
    sign2 = hashlib.md5(concat_str2.lower().encode()).hexdigest()
    
    # Method 3: Different order?
    params3 = f"appid={appid}&keyid={keyid}&nonce={nonce}&time={time_str}{APP_KEY}"
    sign3 = hashlib.md5(params3.lower().encode()).hexdigest()
    
    return sign1, sign2, sign3, concat_str


async def test_create_account():
    """Test creating virtual account with different SIGN methods."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    
    sign1, sign2, sign3, input_str = generate_sign_without_token(APP_ID, KEY_ID, nonce, timestamp)
    
    print("=" * 60)
    print("Testing Virtual Account Creation")
    print("=" * 60)
    print(f"\nInput string: {input_str}")
    print(f"\nMethod 1 (with appKey): {sign1}")
    print(f"Method 2 (no appKey):    {sign2}")
    print(f"Method 3 (direct):       {sign3}")
    print()
    
    # Try all three methods
    for i, sign in enumerate([sign1, sign2, sign3], 1):
        print(f"\n🔍 Testing Method {i}...")
        print("-" * 60)
        
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
            "intent": "config.auth.createAccount",
            "data": {
                "accountId": f"test_user_{int(time.time())}",
                "remark": "Test account",
                "needAccessToken": False,
            }
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
                    
                    if result.get('code') == 0:
                        print(f"\n✅ SUCCESS with Method {i}!")
                        print(f"Result: {result.get('result', {})}")
                        return True
                    else:
                        detail = result.get('messageDetail', 'Unknown')
                        print(f"❌ Failed: {detail}")
                        
                        # Check if it's signature mismatch
                        if 'ClientSign' in str(detail) and 'ServerSign' in str(detail):
                            import re
                            client_match = re.search(r'ClientSign:(\w+)', detail)
                            server_match = re.search(r'ServerSign:(\w+)', detail)
                            
                            if client_match and server_match:
                                print(f"ClientSign: {client_match.group(1)}")
                                print(f"ServerSign: {server_match.group(1)}")
                                print(f"Our Sign:   {sign}")
                                
                                if sign == server_match.group(1):
                                    print("✅ Our sign matches ServerSign!")
                                else:
                                    print("❌ Sign mismatch - wrong algorithm")
                        
            except Exception as e:
                print(f"❌ Error: {type(e).__name__}: {e}")
    
    print("\n❌ All methods failed")
    return False


if __name__ == "__main__":
    print("\n🚀 Testing SIGN methods without accesstoken...\n")
    result = asyncio.run(test_create_account())
    
    if result:
        print("\n✅ Found correct SIGN method!")
    else:
        print("\n❌ Need more investigation")
