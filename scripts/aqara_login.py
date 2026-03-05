#!/usr/bin/env python3
"""
Aqara Login Script - Get fresh Access Token
Uses email/password to authenticate and get new tokens
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
API_DOMAIN = "open-ger.aqara.com"  # Germany/Europe

# User credentials
EMAIL = "arsenhandzan442@gmail.com"
PASSWORD = input("Enter your Aqara Home password: ")


def generate_sign(nonce: str, timestamp: str) -> str:
    """Generate API signature."""
    sign_str = f"{APP_KEY}{nonce}{timestamp}"
    return hashlib.md5(sign_str.encode()).hexdigest()


async def login():
    """Login to Aqara Cloud API and get access token."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(nonce, timestamp)
    
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
    }
    
    # Login intent
    payload = {
        "intent": "account.loginByPassword",
        "data": {
            "username": EMAIL,
            "password": PASSWORD,
        }
    }
    
    print("=" * 60)
    print("AQARA CLOUD API - LOGIN")
    print("=" * 60)
    print(f"\n📧 Email: {EMAIL}")
    print(f"🌍 Region: Germany (Europe)")
    print(f"📡 Endpoint: https://{API_DOMAIN}")
    print()
    
    async with aiohttp.ClientSession() as session:
        try:
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{base_url}?{query_string}"
            
            print("🔐 Sending login request...")
            
            async with session.post(
                full_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                
                print(f"\n📊 Response Code: {result.get('code')}")
                print(f"💬 Message: {result.get('message', 'Success')}")
                
                if result.get('code') == 0:
                    login_result = result.get('result', {})
                    
                    access_token = login_result.get('accessToken')
                    refresh_token = login_result.get('refreshToken')
                    user_id = login_result.get('userId')
                    
                    print("\n✅ LOGIN SUCCESSFUL!")
                    print("=" * 60)
                    print(f"\n🎫 Access Token:")
                    print(f"   {access_token}")
                    print(f"\n🔄 Refresh Token:")
                    print(f"   {refresh_token}")
                    print(f"\n👤 User ID:")
                    print(f"   {user_id}")
                    print()
                    print("=" * 60)
                    print("📝 UPDATE THESE IN YOUR INTEGRATION:")
                    print("=" * 60)
                    print(f"\nIn Home Assistant:")
                    print("1. Go to Settings → Devices & Services")
                    print("2. Find 'Aqara FP2 (europe)'")
                    print("3. Click Configure")
                    print("4. Update Access Token with the value above")
                    print()
                    
                    return {
                        'access_token': access_token,
                        'refresh_token': refresh_token,
                        'user_id': user_id
                    }
                    
                elif result.get('code') == 10001:
                    print("\n❌ Authentication failed!")
                    print("   - Check your email and password")
                    print("   - Make sure region is correct (Germany)")
                else:
                    print(f"\n❌ Error: {result.get('messageDetail', 'Unknown error')}")
                    
                return None
                    
        except asyncio.TimeoutError:
            print("\n❌ Request timed out!")
        except Exception as e:
            print(f"\n❌ Request failed: {type(e).__name__}: {e}")
        
        return None


if __name__ == "__main__":
    print("\n🚀 Starting Aqara Login...\n")
    result = asyncio.run(login())
    
    if result:
        print("\n✅ Done! Use the tokens above to update your integration.")
    else:
        print("\n❌ Login failed!")
