#!/usr/bin/env python3
"""
Direct login using account.loginByPassword
Bypasses getAuthCode rate limit
"""

import aiohttp
import hashlib
import time
import random
import asyncio
import json

EMAIL = "arsenhandzan442@gmail.com"
PASSWORD = "Arsen2576525005@"  # From your earlier message

APP_ID = "14781250729668648963a0b3"
APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"

API_URL = "https://open-ger.aqara.com/v3.0/open/api"


def generate_sign(appid, keyid, nonce, time_str):
    """Generate SIGN without accesstoken."""
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


async def login_by_password():
    """Login directly with email and password."""
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print("=" * 60)
    print("Direct Login by Password")
    print("=" * 60)
    print(f"\n📧 Email: {EMAIL}")
    print(f"🔑 Password: {'*' * len(PASSWORD)}")
    print(f"🌍 Region: Europe (Germany)")
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
        "intent": "account.loginByPassword",
        "data": {
            "account": EMAIL,
            "password": PASSWORD,
        }
    }
    
    print("📋 Request:")
    print(f"   Intent: account.loginByPassword")
    print(f"   account: {EMAIL}")
    print(f"   password: [HIDDEN]")
    print()
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                result = await resp.json()
                
                print(f"📊 Response:")
                print(f"   Status: {resp.status}")
                print(f"   Code: {result.get('code')}")
                print(f"   Message: {result.get('message')}")
                print(f"   Detail: {result.get('messageDetail', 'N/A')}")
                print()
                
                if result.get('code') == 0:
                    print("✅ LOGIN SUCCESSFUL!")
                    
                    res_data = result.get('result', {})
                    access_token = res_data.get('accessToken')
                    refresh_token = res_data.get('refreshToken')
                    open_id = res_data.get('openId')
                    expires_in = res_data.get('expiresIn')
                    
                    if access_token:
                        print(f"\n🎫 Access Token: {access_token}")
                        print(f"🔄 Refresh Token: {refresh_token}")
                        print(f"⏰ Expires In: {expires_in} seconds")
                        print(f"🆔 Open ID: {open_id}")
                        
                        tokens = {
                            'email': EMAIL,
                            'access_token': access_token,
                            'refresh_token': refresh_token,
                            'open_id': open_id,
                            'expires_in': int(expires_in) if expires_in else 604800,
                            'login_time': int(time.time()),
                        }
                        
                        # Save to file
                        with open('/tmp/aqara_main_account_tokens.json', 'w') as f:
                            json.dump(tokens, f, indent=2)
                        
                        print(f"\n💾 Tokens saved to: /tmp/aqara_main_account_tokens.json")
                        
                        # Update .env
                        print("\n📝 Updating .env...")
                        import os
                        env_path = '/Users/arsen/Desktop/wifi-densepose/.env'
                        
                        with open(env_path, 'r') as f:
                            env_content = f.read()
                        
                        # Replace tokens
                        env_lines = env_content.split('\n')
                        new_env_lines = []
                        for line in env_lines:
                            if line.startswith('AQARA_ACCESS_TOKEN='):
                                new_env_lines.append(f'AQARA_ACCESS_TOKEN={access_token}')
                            elif line.startswith('AQARA_REFRESH_TOKEN='):
                                new_env_lines.append(f'AQARA_REFRESH_TOKEN={refresh_token}')
                            elif line.startswith('AQARA_OPEN_ID='):
                                new_env_lines.append(f'AQARA_OPEN_ID={open_id}')
                            elif line.startswith('AQARA_ACCESS_TOKEN_EXPIRES='):
                                from datetime import datetime, timedelta
                                expires_date = datetime.now() + timedelta(seconds=int(expires_in or 604800))
                                new_env_lines.append(f'AQARA_ACCESS_TOKEN_EXPIRES={expires_date.strftime("%Y-%m-%d %H:%M:%S")}')
                            else:
                                new_env_lines.append(line)
                        
                        with open(env_path, 'w') as f:
                            f.write('\n'.join(new_env_lines))
                        
                        print("✅ .env updated!")
                        
                        return tokens
                    else:
                        print("❌ No access token in response")
                        print(f"Result: {res_data}")
                        return None
                        
                else:
                    detail = result.get('messageDetail', '')
                    print(f"❌ Failed: {detail}")
                    
                    # Check error type
                    if 'duplicate request' in str(detail).lower():
                        print("\n⏳ Nonce collision - wait 1 minute and retry")
                    elif 'too frequently' in str(detail).lower():
                        print("\n⏳ Rate limited - wait 5-10 minutes")
                    
                    return None
                    
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            return None


if __name__ == "__main__":
    print("\n🚀 Logging in with main account...\n")
    result = asyncio.run(login_by_password())
    
    if result:
        print("\n" + "=" * 60)
        print("✅ SUCCESS!")
        print("=" * 60)
        print("\n📝 Next steps:")
        print("1. Restart Home Assistant: docker restart wifi-densepose-ha")
        print("2. Test token: python3 scripts/test_new_token.py")
        print("3. Check logs: docker logs wifi-densepose-ha | grep aqara")
    else:
        print("\n❌ Login failed")
