#!/usr/bin/env python3
"""Test different signature generation methods"""

import hashlib
import time

APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
nonce = "123456"
timestamp = str(int(time.time() * 1000))

print("Testing signature generation methods:")
print("=" * 60)
print(f"AppKey: {APP_KEY}")
print(f"Nonce: {nonce}")
print(f"Time: {timestamp}")
print()

# Method 1: appKey + nonce + time (current)
sign1 = hashlib.md5(f"{APP_KEY}{nonce}{timestamp}".encode()).hexdigest()
print(f"Method 1 (appKey+nonce+time): {sign1}")

# Method 2: nonce + time + appKey
sign2 = hashlib.md5(f"{nonce}{timestamp}{APP_KEY}".encode()).hexdigest()
print(f"Method 2 (nonce+time+appKey): {sign2}")

# Method 3: appKey + time + nonce
sign3 = hashlib.md5(f"{APP_KEY}{timestamp}{nonce}".encode()).hexdigest()
print(f"Method 3 (appKey+time+nonce): {sign3}")

# Method 4: MD5 of concatenated string with separators
sign4 = hashlib.md5(f"{APP_KEY}_{nonce}_{timestamp}".encode()).hexdigest()
print(f"Method 4 (appKey_nonce_time): {sign4}")

# Method 5: SHA256 instead of MD5
sign5 = hashlib.sha256(f"{APP_KEY}{nonce}{timestamp}".encode()).hexdigest()
print(f"Method 5 (SHA256): {sign5}")

print()
print("=" * 60)
print("Current implementation uses Method 1")
print("But error shows ClientSign != ServerSign")
print("Need to check Aqara documentation for exact formula")
