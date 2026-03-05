#!/usr/bin/env python3
"""
Direct Local API Connection to FP2 Device
Bypass Aqara Cloud and connect directly to device IP
"""

import asyncio
import aiohttp
import json

FP2_IP = "192.168.1.52"
FP2_PORT = 80  # Standard HTTP port

async def get_device_info():
    """Try to get device info via local API."""
    
    urls_to_try = [
        f"http://{FP2_IP}:{FP2_PORT}/api/v1/device/info",
        f"http://{FP2_IP}:{FP2_PORT}/v1/device",
        f"http://{FP2_IP}:{FP2_PORT}/device/status",
        f"http://{FP2_IP}:{FP2_PORT}/status",
    ]
    
    headers = {
        "Content-Type": "application/json",
    }
    
    async with aiohttp.ClientSession() as session:
        for url in urls_to_try:
            try:
                print(f"\n🔍 Trying: {url}")
                
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    print(f"✅ Status: {resp.status}")
                    result = await resp.json()
                    print(f"📊 Response: {json.dumps(result, indent=2)}")
                    return result
                    
            except asyncio.TimeoutError:
                print(f"⏱️  Timeout: {url}")
            except Exception as e:
                print(f"❌ Error: {type(e).__name__}: {e}")
    
    print("\n❌ Could not connect to FP2 device locally")
    return None


if __name__ == "__main__":
    print("=" * 60)
    print("🔌 Testing Direct Local Connection to FP2")
    print("=" * 60)
    print(f"\n📍 Device IP: {FP2_IP}")
    print(f"📍 Port: {FP2_PORT}")
    print()
    
    result = asyncio.run(get_device_info())
    
    if result:
        print("\n✅ Success! Device found!")
    else:
        print("\n❌ Device not responding on local network")
        print("\n💡 FP2 may only work through Aqara Cloud API")
