#!/usr/bin/env python3
"""
Aqara Cloud API клиент для FP2.
Полный auth flow: getAuthCode -> getToken -> getDeviceList.

Использование:
  1. python3 fp2_aqara_api_simple.py          # получить authCode на email
  2. python3 fp2_aqara_api_simple.py <code>   # ввести код и получить токен + устройства
"""

import hashlib
import json
import os
import random
import sys
import time

import requests

# === Configuration ===
APP_ID  = "14781250729668648963a0b3"
APP_KEY = "v5ync4u82ju7va3x1hap6ayp5tz1tanq"
KEY_ID  = "K.1478125073029779456"  # China Mainland key

DOMAIN   = "open-cn.aqara.com"    # China Mainland server
BASE_URL = f"https://{DOMAIN}/v3.0/open/api"

# Aqara account (accountType=0)
ACCOUNT      = "arsenhandzan442@gmail.com"
ACCOUNT_TYPE = 0

# Token cache file (saves across runs)
TOKEN_FILE = os.path.join(os.path.dirname(__file__), ".aqara_token.json")


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------

def generate_sign(access_token: str, nonce: str, timestamp: str) -> str:
    """
    Aqara Sign formula (v3.0):
    - With token:    md5( lowercase( Accesstoken=<t>&Appid=<a>&Keyid=<k>&Nonce=<n>&Time=<ts><AppKey> ) )
    - Without token: md5( lowercase( Appid=<a>&Keyid=<k>&Nonce=<n>&Time=<ts><AppKey> ) )
    """
    if access_token:
        sign_str = (
            f"Accesstoken={access_token}"
            f"&Appid={APP_ID}"
            f"&Keyid={KEY_ID}"
            f"&Nonce={nonce}"
            f"&Time={timestamp}"
            f"{APP_KEY}"
        ).lower()
    else:
        sign_str = (
            f"Appid={APP_ID}"
            f"&Keyid={KEY_ID}"
            f"&Nonce={nonce}"
            f"&Time={timestamp}"
            f"{APP_KEY}"
        ).lower()
    return hashlib.md5(sign_str.encode()).hexdigest()


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def api(intent: str, data: dict = None, access_token: str = "") -> dict:
    """Send a single request to Aqara Cloud API."""
    nonce     = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    sign      = generate_sign(access_token, nonce, timestamp)

    headers = {
        "Content-Type": "application/json",
        "Appid":        APP_ID,
        "Keyid":        KEY_ID,
        "Nonce":        nonce,
        "Time":         timestamp,
        "Sign":         sign,
    }
    if access_token:
        headers["Accesstoken"] = access_token

    payload = {"intent": intent, "data": data or {}}

    resp = requests.post(BASE_URL, headers=headers, json=payload, timeout=10)
    result = resp.json()
    return result


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------

def load_token() -> dict | None:
    """Load cached token from disk."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        # Check not expired (with 60s margin)
        if data.get("expires_at", 0) > time.time() + 60:
            return data
    return None


def save_token(access_token: str, refresh_token: str, expires_in: int):
    """Save token to disk."""
    data = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "expires_at":    time.time() + int(expires_in),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"   💾 Токен сохранён в {TOKEN_FILE}")


def refresh_saved_token(refresh_token: str) -> dict | None:
    """Try to refresh expired access token."""
    print("🔄 Обновляем accessToken через refreshToken...")
    result = api("config.auth.refreshToken", {"refreshToken": refresh_token})
    if result.get("code") == 0:
        r = result["result"]
        save_token(r["accessToken"], r["refreshToken"], int(r["expiresIn"]))
        return r
    print(f"   ❌ refreshToken не сработал: {result}")
    return None


# ---------------------------------------------------------------------------
# Auth flow
# ---------------------------------------------------------------------------

def step1_request_auth_code():
    """Step 1: Request authCode – sent to user's email."""
    print(f"\n📧 Запрашиваем authCode для {ACCOUNT}...")
    result = api(
        "config.auth.getAuthCode",
        {
            "account":             ACCOUNT,
            "accountType":         ACCOUNT_TYPE,
            "accessTokenValidity": "30d",
        },
    )
    if result.get("code") == 0:
        print("✅ authCode отправлен на email. Проверь почту и запусти:")
        print(f"   python3 {sys.argv[0]} <authCode>")
    else:
        print(f"❌ Ошибка getAuthCode: {result}")


def step2_get_token(auth_code: str):
    """Step 2: Exchange authCode for accessToken."""
    print(f"\n🔑 Получаем токен по authCode={auth_code}...")
    result = api(
        "config.auth.getToken",
        {
            "authCode":    auth_code,
            "account":     ACCOUNT,
            "accountType": ACCOUNT_TYPE,
        },
    )
    if result.get("code") != 0:
        print(f"❌ Ошибка getToken: {result}")
        return None

    r = result["result"]
    save_token(r["accessToken"], r["refreshToken"], int(r["expiresIn"]))
    print(f"✅ accessToken получен! Действителен {int(r['expiresIn'])//86400} дней.")
    return r


# ---------------------------------------------------------------------------
# Device listing
# ---------------------------------------------------------------------------

def list_devices(access_token: str):
    """Fetch all devices and highlight FP2."""
    print("\n📱 Запрашиваем список устройств...")
    result = api("config.device.getList", {}, access_token=access_token)

    if result.get("code") != 0:
        print(f"❌ Ошибка getList: {result.get('message')} | {result.get('messageDetail')}")
        return

    devices = result.get("result", {}).get("data", [])
    if not devices:
        print("⚠️  Устройства не найдены (список пуст)")
        return

    print(f"\n✅ Найдено устройств: {len(devices)}\n")
    fp2 = None

    for d in devices:
        did   = d.get("did",        "N/A")
        name  = d.get("deviceName", "Unknown")
        model = d.get("model",      "Unknown")
        state = d.get("state",      0)
        online = "🟢 Online" if state == 1 else "🔴 Offline"

        print(f"  📦 {name}")
        print(f"     DID:    {did}")
        print(f"     Model:  {model}")
        print(f"     State:  {online}")
        print()

        if "FP2" in model.upper() or "fp2" in name.lower() or "presence" in name.lower():
            fp2 = d

    if fp2:
        print("=" * 60)
        print("  ✅ FP2 НАЙДЕН!")
        print("=" * 60)
        did = fp2["did"]
        print(f"  DID:   {did}")
        print(f"  Model: {fp2.get('model')}")
        print(f"  Name:  {fp2.get('deviceName')}\n")

        # Get detailed state
        state_result = api("config.device.getState", {"did": did}, access_token=access_token)
        print("Детальное состояние FP2:")
        print(json.dumps(state_result, indent=2, ensure_ascii=False))
    else:
        print("⚠️  FP2 не найден среди устройств")
        print("   Убедись, что FP2 добавлен в тот же аккаунт Aqara:", ACCOUNT)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  AQARA FP2 - CLOUD API CLIENT")
    print(f"  Server: {DOMAIN}")
    print("=" * 60)

    # If authCode passed as argument → get token
    if len(sys.argv) == 2:
        auth_code = sys.argv[1].strip()
        token_data = step2_get_token(auth_code)
        if token_data:
            list_devices(token_data["accessToken"])
        return

    # Try cached token
    cached = load_token()
    if cached:
        print("\n✅ Используем сохранённый токен.")
        list_devices(cached["access_token"])
        return

    # Try refresh if expired
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            old = json.load(f)
        refreshed = refresh_saved_token(old.get("refresh_token", ""))
        if refreshed:
            list_devices(refreshed["accessToken"])
            return

    # Use known valid token from portal (valid until 2026-03-11)
    KNOWN_TOKEN = "4c33a1ce745fa1ae7aaffd7087a7115e"
    print("\n🔑 Используем токен из портала...")
    list_devices(KNOWN_TOKEN)

    # No valid token → start auth flow
    step1_request_auth_code()


if __name__ == "__main__":
    main()
