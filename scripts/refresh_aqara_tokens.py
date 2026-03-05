#!/usr/bin/env python3
"""
Refresh Aqara API Tokens and Update Home Assistant Configuration
"""

import asyncio
import hashlib
import json
import random
import time
import aiohttp
from pathlib import Path

# Load credentials from .env
from dotenv import load_dotenv
import os

load_dotenv()

# Configuration
APP_ID = os.getenv('AQARA_APP_ID')
APP_KEY = os.getenv('AQARA_APP_KEY')
KEY_ID = os.getenv('AQARA_KEY_ID')
API_DOMAIN = os.getenv('AQARA_API_DOMAIN', 'open-ger.aqara.com')

EMAIL = os.getenv('AQARA_EMAIL')
PASSWORD = os.getenv('AQARA_PASSWORD')


def generate_sign(nonce: str, timestamp: str) -> str:
    """Generate API signature."""
    sign_str = f"{APP_KEY}{nonce}{timestamp}"
    return hashlib.md5(sign_str.encode()).hexdigest()


async def refresh_tokens():
    """Login to Aqara Cloud API and get fresh access tokens."""
    
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
    
    payload = {
        "intent": "account.loginByPassword",
        "data": {
            "username": EMAIL,
            "password": PASSWORD,
        }
    }
    
    print("=" * 60)
    print("🔄 REFRESHING AQARA API TOKENS")
    print("=" * 60)
    print(f"\n📧 Email: {EMAIL}")
    print(f"🌍 Region: {API_DOMAIN}")
    print()
    
    async with aiohttp.ClientSession() as session:
        try:
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            full_url = f"{base_url}?{query_string}"
            
            print("🔐 Authenticating with Aqara Cloud...")
            
            async with session.post(
                full_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()
                
                if result.get('code') == 0:
                    login_result = result.get('result', {})
                    
                    new_access_token = login_result.get('accessToken')
                    new_refresh_token = login_result.get('refreshToken')
                    user_id = login_result.get('userId')
                    
                    print("✅ Authentication successful!")
                    print(f"\n🎫 New Access Token: {new_access_token[:16]}...{new_access_token[-8:]}")
                    print(f"🔄 New Refresh Token: {new_refresh_token[:16]}...{new_refresh_token[-8:]}")
                    
                    # Update .env file
                    update_env_file(new_access_token, new_refresh_token)
                    
                    # Update Home Assistant configuration
                    update_ha_config(new_access_token, new_refresh_token)
                    
                    print("\n✅ Tokens updated successfully!")
                    print("\n⚠️  IMPORTANT: Restart Home Assistant to apply changes:")
                    print("   docker restart wifi-densepose-ha")
                    
                    return True
                    
                else:
                    print(f"❌ Authentication failed: {result.get('messageDetail')}")
                    return False
                    
        except Exception as e:
            print(f"❌ Error: {e}")
            return False


def update_env_file(access_token: str, refresh_token: str):
    """Update .env file with new tokens."""
    env_path = Path('/Users/arsen/Desktop/wifi-densepose/.env')
    
    if env_path.exists():
        content = env_path.read_text()
        
        # Update access token
        old_token_line = [l for l in content.split('\n') if 'AQARA_ACCESS_TOKEN=' in l]
        if old_token_line:
            content = content.replace(old_token_line[0], f'AQARA_ACCESS_TOKEN={access_token}')
        
        # Update refresh token
        old_refresh_line = [l for l in content.split('\n') if 'AQARA_REFRESH_TOKEN=' in l]
        if old_refresh_line:
            content = content.replace(old_refresh_line[0], f'AQARA_REFRESH_TOKEN={refresh_token}')
        
        env_path.write_text(content)
        print("✅ Updated .env file")


def update_ha_config(access_token: str, refresh_token: str):
    """Update Home Assistant config_entries with new tokens."""
    import subprocess
    
    config_path = "/config/.storage/core.config_entries"
    
    # Create Python script to run in Docker container
    script = f"""
import json
from pathlib import Path

config_path = Path('{config_path}')
data = json.loads(config_path.read_text())

for entry in data['data']['entries']:
    if entry.get('domain') == 'aqara_fp2':
        entry['data']['access_token'] = '{access_token}'
        entry['data']['refresh_token'] = '{refresh_token}'
        print(f"Updated entry: {{entry.get('entry_id')}}")
        break

config_path.write_text(json.dumps(data, indent=4))
print("✅ Home Assistant config updated")
"""
    
    # Execute in Docker container
    result = subprocess.run(
        ['docker', 'exec', 'wifi-densepose-ha', 'python3', '-c', script],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("✅ Updated Home Assistant configuration")
    else:
        print(f"⚠️  Could not update HA config: {result.stderr}")


if __name__ == "__main__":
    print("\n🚀 Starting token refresh...\n")
    success = asyncio.run(refresh_tokens())
    
    if success:
        print("\n" + "=" * 60)
        print("✅ DONE!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Restart Home Assistant:")
        print("   docker restart wifi-densepose-ha")
        print("\n2. Check logs:")
        print("   docker logs wifi-densepose-ha | grep aqara")
        print("\n3. Verify entities are updating in Home Assistant UI")
    else:
        print("\n❌ Failed to refresh tokens")
