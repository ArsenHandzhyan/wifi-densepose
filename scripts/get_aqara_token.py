#!/usr/bin/env python3
"""
Get fresh Access Token from Aqara Cloud API
Using email/password authentication with CORRECT SIGN generation
"""

import aiohttp
import hashlib
import time
import random
import asyncio
import json
from pathlib import Path

# Credentials from .env
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


async def login_by_password():
    """Login using email/password and get access token."""
    
    # Generate auth parameters
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    
    # Generate SIGN (without accesstoken for login request)
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp)
    
    print("=" * 60)
    print("Aqara Cloud API - Login by Password")
    print("=" * 60)
    print(f"\n📧 Email: {EMAIL}")
    print(f"🌍 Region: Europe (Germany)")
    print(f"📡 Endpoint: {API_URL}")
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
        "intent": "config.auth.getToken",
        "data": {
            "account": EMAIL,
            "accountType": 0,  # 0 = Aqara account
        }
    }
    
    print("🔐 Sending login request...")
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
                    print("✅ LOGIN SUCCESSFUL!")
                    
                    login_result = result.get('result', {})
                    access_token = login_result.get('accessToken')
                    refresh_token = login_result.get('refreshToken')
                    open_id = login_result.get('openId')
                    expires_in = login_result.get('expiresIn')
                    
                    print(f"\n🎫 Access Token: {access_token}")
                    print(f"🔄 Refresh Token: {refresh_token}")
                    print(f"⏰ Expires In: {expires_in} seconds")
                    print(f"🆔 Open ID: {open_id}")
                    
                    # Save to file
                    tokens = {
                        'email': EMAIL,
                        'access_token': access_token,
                        'refresh_token': refresh_token,
                        'open_id': open_id,
                        'expires_in': int(expires_in),
                        'timestamp': int(time.time()),
                    }
                    
                    tokens_file = Path('/tmp/aqara_fresh_tokens.json')
                    with open(tokens_file, 'w') as f:
                        json.dump(tokens, f, indent=2)
                    
                    print(f"\n💾 Tokens saved to: {tokens_file}")
                    
                    # Update Home Assistant config
                    await update_ha_config(access_token, refresh_token)
                    
                    return tokens
                    
                elif result.get('code') == 10001:
                    print("❌ Authentication failed!")
                    print("   - Check email and password")
                    print("   - Verify region (Germany/Europe)")
                    return None
                else:
                    print(f"❌ API Error: {result.get('messageDetail')}")
                    return None
                    
        except asyncio.TimeoutError:
            print("❌ Request timed out!")
            return None
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")
            return None


async def update_ha_config(access_token, refresh_token):
    """Update Home Assistant integration config with new tokens."""
    print("\n🔧 Updating Home Assistant configuration...")
    
    script = f"""
import json
from pathlib import Path

config_path = Path('/config/.storage/core.config_entries')
data = json.loads(config_path.read_text())

for entry in data['data']['entries']:
    if entry.get('domain') == 'aqara_fp2':
        entry['data']['access_token'] = '{access_token}'
        entry['data']['refresh_token'] = '{refresh_token}'
        print(f"✅ Updated entry: {{entry.get('entry_id')}}")
        break

config_path.write_text(json.dumps(data, indent=4))
print("✅ Home Assistant config updated successfully")
"""
    
    import subprocess
    result = subprocess.run(
        ['docker', 'exec', 'wifi-densepose-ha', 'python3', '-c', script],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print(result.stdout.strip())
    else:
        print(f"⚠️  Could not update HA config: {result.stderr}")


async def test_new_token(access_token):
    """Test the new access token by getting device list."""
    print("\n🧪 Testing new access token...")
    
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign = generate_sign(APP_ID, KEY_ID, nonce, timestamp, access_token)
    
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
        "intent": "config.device.getList",
        "data": {}
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
                
                if result.get('code') == 0:
                    print("✅ Token is VALID!")
                    devices = result.get('result', {}).get('deviceList', [])
                    print(f"📱 Found {len(devices)} device(s)")
                    
                    for dev in devices:
                        did = dev.get('did')
                        name = dev.get('name')
                        model = dev.get('model')
                        print(f"   - {name} ({did}) - {model}")
                    
                    return True
                else:
                    print(f"❌ Token test failed: {result.get('messageDetail')}")
                    return False
                    
        except Exception as e:
            print(f"❌ Error testing token: {e}")
            return False


if __name__ == "__main__":
    print("\n🚀 Starting Aqara login process...\n")
    
    # Step 1: Login
    tokens = asyncio.run(login_by_password())
    
    if tokens:
        print("\n" + "=" * 60)
        print("✅ SUCCESS!")
        print("=" * 60)
        
        # Step 2: Test token
        test_result = asyncio.run(test_new_token(tokens['access_token']))
        
        if test_result:
            print("\n🎉 All done!")
            print("\n📝 Next steps:")
            print("1. Restart Home Assistant:")
            print("   docker restart wifi-densepose-ha")
            print("\n2. Check logs:")
            print("   docker logs wifi-densepose-ha | grep aqara")
            print("\n3. Verify entities are updating in HA UI")
        else:
            print("\n⚠️  Token obtained but test failed - may need manual config update")
    else:
        print("\n❌ Login failed!")
