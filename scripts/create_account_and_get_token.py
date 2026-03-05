#!/usr/bin/env python3
"""
Create virtual account and get access token in one flow
Uses CORRECT SIGN formula verified by test_sign_without_token.py
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

# Use unique account ID
ACCOUNT_ID = f"ha_fp2_user_{int(time.time())}"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str):
    """Generate SIGN WITHOUT accesstoken."""
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


async def create_account_with_token():
    """Create virtual account and get access token immediately."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print("=" * 60)
    print("Creating Virtual Account with Access Token")
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
    
    payload = {
        "intent": "config.auth.createAccount",
        "data": {
            "accountId": ACCOUNT_ID,
            "remark": "Home Assistant FP2 Integration",
            "needAccessToken": True,  # Return access token immediately
            "accessTokenValidity": "30d",  # Valid for 30 days
        }
    }
    
    print("📋 Request:")
    print(f"   Intent: config.auth.createAccount")
    print(f"   needAccessToken: true")
    print(f"   accessTokenValidity: 30d")
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
                    print("✅ Virtual Account Created!")
                    
                    res_data = result.get('result', {})
                    open_id = res_data.get('openId')
                    access_token = res_data.get('accessToken')
                    refresh_token = res_data.get('refreshToken')
                    expires_in = res_data.get('expiresIn')
                    
                    if access_token:
                        print(f"\n🎫 Access Token: {access_token}")
                        print(f"🔄 Refresh Token: {refresh_token}")
                        print(f"⏰ Expires In: {expires_in} seconds")
                        print(f"🆔 Open ID: {open_id}")
                        
                        tokens = {
                            'account_id': ACCOUNT_ID,
                            'access_token': access_token,
                            'refresh_token': refresh_token,
                            'open_id': open_id,
                            'expires_in': int(expires_in) if expires_in else 2592000,
                            'created_at': int(time.time()),
                        }
                        
                        # Save to file
                        with open('/tmp/aqara_new_tokens.json', 'w') as f:
                            json.dump(tokens, f, indent=2)
                        
                        print(f"\n💾 Tokens saved to: /tmp/aqara_new_tokens.json")
                        
                        return tokens
                    else:
                        print("❌ No access token returned")
                        print(f"Result: {res_data}")
                        return None
                        
                else:
                    detail = result.get('messageDetail', '')
                    print(f"❌ Failed: {detail}")
                    
                    # Check if signature mismatch
                    if 'ClientSign' in detail and 'ServerSign' in detail:
                        import re
                        client_match = re.search(r'ClientSign:(\w+)', detail)
                        server_match = re.search(r'ServerSign:(\w+)', detail)
                        
                        if client_match and server_match:
                            print(f"\nSignature comparison:")
                            print(f"   ClientSign (ours): {client_match.group(1)}")
                            print(f"   ServerSign (theirs): {server_match.group(1)}")
                            print(f"   Our calculated: {sign}")
                            
                            if sign == server_match.group(1):
                                print("   ✅ Sign matches!")
                            else:
                                print("   ❌ Sign mismatch - algorithm needs fixing")
                    
                    return None
                    
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            return None


if __name__ == "__main__":
    print("\n🚀 Creating virtual account...\n")
    result = asyncio.run(create_account_with_token())
    
    if result:
        print("\n" + "=" * 60)
        print("✅ SUCCESS!")
        print("=" * 60)
        print("\n📝 Next steps:")
        print("1. Update .env with new credentials")
        print("2. Run: python3 scripts/refresh_aqara_tokens.py")
        print("3. Restart: docker restart wifi-densepose-ha")
        print("4. Test: python3 scripts/test_current_token.py")
    else:
        print("\n❌ Failed to create virtual account")
