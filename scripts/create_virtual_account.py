#!/usr/bin/env python3
"""
Create Virtual Account to get fresh tokens
Using EXACT API format from documentation
"""

import aiohttp
import hashlib
import time
import random
import asyncio
import json

APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"

# Try with user's email as virtual account ID
ACCOUNT_ID = "arsenhandzan442@gmail.com"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(nonce: str, timestamp: str) -> str:
    """Generate signature using Method 1 (standard)."""
    sign_str = f"{APP_KEY}{nonce}{timestamp}"
    return hashlib.md5(sign_str.encode()).hexdigest()


async def create_virtual_account():
    """Create virtual account and get access token."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(nonce, timestamp)
    
    print("=" * 60)
    print("Creating Virtual Account")
    print("=" * 60)
    print(f"\n📧 Account ID: {ACCOUNT_ID}")
    print(f"🔑 AppID: {APP_ID}")
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
    
    # Create virtual account request
    payload = {
        "intent": "config.auth.createAccount",
        "data": {
            "accountId": ACCOUNT_ID,
            "remark": "Home Assistant FP2 Integration",
            "needAccessToken": True,
            "accessTokenValidity": "7d",  # 7 days default
        }
    }
    
    print("📋 Request:")
    print(f"   Intent: config.auth.createAccount")
    print(f"   AccountId: {ACCOUNT_ID}")
    print()
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                
                print(f"📊 Response:")
                print(f"   Status: {resp.status}")
                print(f"   Code: {result.get('code')}")
                print(f"   Message: {result.get('message')}")
                print(f"   Detail: {result.get('messageDetail', 'N/A')}")
                print()
                
                if result.get('code') == 0:
                    print("✅ SUCCESS!")
                    account_result = result.get('result', {})
                    
                    print(f"\n🎫 Access Token: {account_result.get('accessToken')}")
                    print(f"🔄 Refresh Token: {account_result.get('refreshToken')}")
                    print(f"⏰ Expires In: {account_result.get('expiresIn')} seconds")
                    print(f"🆔 Open ID: {account_result.get('openId')}")
                    
                    # Save to file
                    tokens = {
                        'access_token': account_result.get('accessToken'),
                        'refresh_token': account_result.get('refreshToken'),
                        'open_id': account_result.get('openId'),
                        'expires_in': account_result.get('expiresIn'),
                        'account_id': ACCOUNT_ID,
                    }
                    
                    with open('/tmp/aqara_virtual_account.json', 'w') as f:
                        json.dump(tokens, f, indent=2)
                    
                    print(f"\n💾 Tokens saved to /tmp/aqara_virtual_account.json")
                    
                    return tokens
                    
                else:
                    print("❌ Failed to create virtual account")
                    
                    # Try to get auth code instead
                    if result.get('code') == 106 or 'illegal' in str(result.get('messageDetail', '')).lower():
                        print("\n⚠️  Signature mismatch (Code 106)")
                        print("This means the SIGN formula is incorrect")
                        print(f"ClientSign: {sign}")
                        print("Need to check exact Aqara SIGN generation rules")
                    
                    return None
                    
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            return None


if __name__ == "__main__":
    print("\n🚀 Starting virtual account creation...\n")
    result = asyncio.run(create_virtual_account())
    
    if result:
        print("\n✅ Virtual account created successfully!")
        print("\nNext steps:")
        print("1. Update .env with new access_token")
        print("2. Update Home Assistant config")
        print("3. Restart Home Assistant")
    else:
        print("\n❌ Failed - signature generation issue")
