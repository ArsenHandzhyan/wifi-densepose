#!/usr/bin/env python3
"""
Get access token using virtual account
Uses CORRECT SIGN formula: MD5(sorted params + appKey) lowercase
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

# Virtual account created in previous step
VIRTUAL_ACCOUNT_ID = "arsenhandzan442@gmail.com"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str):
    """Generate SIGN WITHOUT accesstoken (for auth requests)."""
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


async def get_auth_code():
    """Step 1: Get authorization code for virtual account."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print("=" * 60)
    print("Step 1: Get Authorization Code")
    print("=" * 60)
    print(f"\n📧 Virtual Account: {VIRTUAL_ACCOUNT_ID}")
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
        "intent": "config.auth.getAuthCode",
        "data": {
            "account": VIRTUAL_ACCOUNT_ID,
            "accountType": 2,  # 2 = Virtual account
        }
    }
    
    async with aiohttp.ClientSession() as session:
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
                auth_code = result.get('result', {}).get('authCode')
                print(f"\n✅ Auth Code: {auth_code}")
                return auth_code
            else:
                print(f"❌ Failed: {result.get('messageDetail')}")
                return None


async def get_access_token(auth_code):
    """Step 2: Exchange auth code for access token."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print("\n" + "=" * 60)
    print("Step 2: Get Access Token")
    print("=" * 60)
    
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
        "intent": "config.auth.getToken",
        "data": {
            "authCode": auth_code,
            "account": VIRTUAL_ACCOUNT_ID,
            "accountType": 2,  # Virtual account
        }
    }
    
    async with aiohttp.ClientSession() as session:
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
                res_data = result.get('result', {})
                access_token = res_data.get('accessToken')
                refresh_token = res_data.get('refreshToken')
                open_id = res_data.get('openId')
                expires_in = res_data.get('expiresIn')
                
                print(f"\n🎫 Access Token: {access_token}")
                print(f"🔄 Refresh Token: {refresh_token}")
                print(f"⏰ Expires In: {expires_in} seconds")
                print(f"🆔 Open ID: {open_id}")
                
                return {
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'open_id': open_id,
                    'expires_in': int(expires_in) if expires_in else 604800,
                }
            else:
                print(f"❌ Failed: {result.get('messageDetail')}")
                return None


async def test_token(access_token):
    """Test the new access token."""
    print("\n" + "=" * 60)
    print("Testing New Access Token")
    print("=" * 60)
    
    DEVICE_ID = "54EF4479E003"
    
    # Generate SIGN WITH accesstoken
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    
    params = {
        'Accesstoken': access_token,
        'Appid': APP_ID,
        'Keyid': KEY_ID,
        'Nonce': nonce,
        'Time': timestamp,
    }
    sorted_keys = sorted(params.keys())
    concat_str = '&'.join(f"{key}={params[key]}" for key in sorted_keys)
    concat_str += APP_KEY
    concat_str = concat_str.lower()
    sign = hashlib.md5(concat_str.encode()).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        "Accesstoken": access_token,
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
                print("\n✅ TOKEN IS VALID!")
                print(f"\n📊 Device State:")
                state = result.get('result', {})
                for key, value in state.items():
                    print(f"   {key}: {value}")
                return True
            else:
                print(f"\n❌ Token test failed: {result.get('messageDetail')}")
                return False


if __name__ == "__main__":
    print("\n🚀 Getting access token via virtual account...\n")
    
    # Step 1: Get auth code
    auth_code = asyncio.run(get_auth_code())
    
    if not auth_code:
        print("\n❌ Failed to get auth code")
        exit(1)
    
    # Step 2: Get access token
    tokens = asyncio.run(get_access_token(auth_code))
    
    if not tokens:
        print("\n❌ Failed to get access token")
        exit(1)
    
    # Step 3: Test token
    test_result = asyncio.run(test_token(tokens['access_token']))
    
    if test_result:
        print("\n" + "=" * 60)
        print("✅ SUCCESS!")
        print("=" * 60)
        print(f"\n💾 Save these credentials:")
        print(f"\nAccess Token: {tokens['access_token']}")
        print(f"Refresh Token: {tokens['refresh_token']}")
        print(f"Expires In: {tokens['expires_in']} seconds")
        
        # Save to file
        with open('/tmp/aqara_virtual_account_tokens.json', 'w') as f:
            json.dump(tokens, f, indent=2)
        
        print(f"\n💾 Tokens saved to: /tmp/aqara_virtual_account_tokens.json")
        
        print(f"\n📝 Next steps:")
        print(f"1. Update .env with new access_token")
        print(f"2. Run: python3 scripts/refresh_aqara_tokens.py")
        print(f"3. Restart: docker restart wifi-densepose-ha")
        
    else:
        print("\n⚠️  Got token but test failed")
