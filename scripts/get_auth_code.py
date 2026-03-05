#!/usr/bin/env python3
"""
Get Auth Code first, then exchange for Access Token
Two-step authentication flow
"""

import aiohttp
import hashlib
import time
import random
import asyncio
import json

EMAIL = "arsenhandzan442@gmail.com"
PASSWORD = "Arsen2576525005@"
APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str, accesstoken=None):
    """Generate SIGN using correct Aqara V3.0 algorithm."""
    params = {
        'Appid': appid,
        'Keyid': keyid,
        'Nonce': nonce,
        'Time': time_str,
    }
    
    if accesstoken:
        params['Accesstoken'] = accesstoken
    
    sorted_keys = sorted(params.keys())
    concat_str = '&'.join(f"{key}={params[key]}" for key in sorted_keys)
    concat_str += APP_KEY
    concat_str = concat_str.lower()
    
    return hashlib.md5(concat_str.encode()).hexdigest()


async def get_auth_code():
    """Step 1: Get authorization code using account credentials."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print("=" * 60)
    print("Step 1: Getting Authorization Code")
    print("=" * 60)
    print(f"\n📧 Email: {EMAIL}")
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
    
    # Try different intents to get auth code
    intents_to_try = [
        ("config.auth.getAuthCode", {"account": EMAIL, "accountType": 0}),
        ("account.loginByPassword", {"username": EMAIL, "password": PASSWORD}),
    ]
    
    async with aiohttp.ClientSession() as session:
        for intent_name, intent_data in intents_to_try:
            print(f"\n🔍 Trying intent: {intent_name}")
            print("-" * 60)
            
            payload = {
                "intent": intent_name,
                "data": intent_data
            }
            
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
                    print(f"Message: {result.get('message', 'Success')}")
                    
                    if result.get('code') == 0:
                        print(f"\n✅ SUCCESS with {intent_name}!")
                        
                        res_data = result.get('result', {})
                        print(f"Full result: {res_data}")
                        
                        # Check what we got
                        if 'authCode' in res_data and res_data['authCode']:
                            print(f"🎫 Auth Code: {res_data['authCode']}")
                            return res_data
                        
                        elif 'accessToken' in res_data:
                            print(f"🎫 Access Token: {res_data['accessToken'][:16]}...")
                            print(f"🔄 Refresh Token: {res_data['refreshToken'][:16]}...")
                            return res_data
                        else:
                            print("⚠️  No auth code or access token in response")
                    
                    else:
                        print(f"❌ Failed: {result.get('messageDetail', 'Unknown error')}")
                        
            except Exception as e:
                print(f"❌ Error: {type(e).__name__}: {e}")
    
    print("\n❌ All authentication methods failed")
    return None


if __name__ == "__main__":
    print("\n🚀 Starting two-step authentication...\n")
    result = asyncio.run(get_auth_code())
    
    if result:
        print("\n" + "=" * 60)
        print("✅ Authentication successful!")
        print("=" * 60)
        
        if 'accessToken' in result:
            print("\n🎉 Got access token directly!")
            print(f"Access Token: {result['accessToken']}")
            print(f"Refresh Token: {result['refreshToken']}")
            print(f"Open ID: {result.get('openId')}")
            print(f"Expires In: {result.get('expiresIn')} seconds")
