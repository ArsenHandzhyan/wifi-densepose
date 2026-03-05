#!/usr/bin/env python3
"""
Test ALL possible SIGN generation methods for Aqara API
Based on common API signature patterns
"""

import hashlib
import time
import urllib.parse

APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
KEY_ID = "K.1478125073038168064"
nonce = "123456"
timestamp = str(int(time.time() * 1000))

print("=" * 60)
print("Testing ALL possible SIGN generation methods")
print("=" * 60)
print(f"AppKey: {APP_KEY}")
print(f"Nonce: {nonce}")
print(f"Time: {timestamp}")
print()

methods = {}

# Method 1: MD5(appKey + nonce + time) - Standard
methods['MD5(appKey+nonce+time)'] = hashlib.md5(f"{APP_KEY}{nonce}{timestamp}".encode()).hexdigest()

# Method 2: MD5(nonce + time + appKey)
methods['MD5(nonce+time+appKey)'] = hashlib.md5(f"{nonce}{timestamp}{APP_KEY}".encode()).hexdigest()

# Method 3: MD5(time + nonce + appKey)
methods['MD5(time+nonce+appKey)'] = hashlib.md5(f"{timestamp}{nonce}{APP_KEY}".encode()).hexdigest()

# Method 4: MD5 with separators
methods['MD5(appKey_nonce_time)'] = hashlib.md5(f"{APP_KEY}_{nonce}_{timestamp}".encode()).hexdigest()

# Method 5: MD5 uppercase
sign5 = hashlib.md5(f"{APP_KEY}{nonce}{timestamp}".encode()).hexdigest().upper()
methods['MD5(appKey+nonce+time).UPPER'] = sign5

# Method 6: SHA256
methods['SHA256(appKey+nonce+time)'] = hashlib.sha256(f"{APP_KEY}{nonce}{timestamp}".encode()).hexdigest()

# Method 7: MD5 of URL encoded values
methods['MD5(urlencode)'] = hashlib.md5(f"keyid={KEY_ID}&nonce={nonce}&time={timestamp}".encode()).hexdigest()

# Method 8: MD5(sorted params)
params_str = "&".join(sorted([f"k={APP_KEY}", f"n={nonce}", f"t={timestamp}"]))
methods['MD5(sorted params)'] = hashlib.md5(params_str.encode()).hexdigest()

# Method 9: Multiple MD5 rounds
sign9 = hashlib.md5(f"{APP_KEY}{nonce}{timestamp}".encode()).hexdigest()
sign9 = hashlib.md5(sign9.encode()).hexdigest()
methods['MD5(MD5(appKey+nonce+time))'] = sign9

# Method 10: HMAC-MD5
import hmac
methods['HMAC-MD5'] = hmac.new(APP_KEY.encode(), f"{nonce}{timestamp}".encode(), hashlib.md5).hexdigest()

for i, (name, sign) in enumerate(methods.items(), 1):
    print(f"{i:2}. {name:35} → {sign}")

print()
print("=" * 60)
print("Compare these with ServerSign from API response")
print("ServerSign was: dfde741bc77d42d08c48318829e66e84")
print("=" * 60)
