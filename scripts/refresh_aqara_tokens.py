#!/usr/bin/env python3
"""Repair Aqara interface-auth tokens and persist them into HA/local env."""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import hashlib
import json
import os
import random
import subprocess
import time
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path("/Users/arsen/Desktop/wifi-densepose")
ENV_PATH = REPO_ROOT / ".env"
HA_CONFIG_ENTRIES_PATH = REPO_ROOT / ".ha-core/config/.storage/core.config_entries"
HA_DOCKER_CONTAINER = os.getenv("HA_DOCKER_CONTAINER", "wifi-densepose-ha")

DEFAULT_APP_ID = "14781250729668648963a0b3"
DEFAULT_APP_KEY = "uyx84zj5aym4itdkibvecakrfakm8nlp"
DEFAULT_KEY_ID = "K.1478125073038168064"
API_DOMAIN = os.getenv("AQARA_API_DOMAIN", "open-ger.aqara.com")
API_URL = f"https://{API_DOMAIN}/v3.0/open/api"


def get_ha_volume_config_entries_path() -> Path | None:
    """Resolve the persistent HA config_entries path from the Docker mount."""
    result = subprocess.run(
        ["docker", "inspect", HA_DOCKER_CONTAINER, "--format", "{{json .Mounts}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    try:
        mounts = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    for mount in mounts:
        if mount.get("Destination") != "/config":
            continue
        source = mount.get("Source")
        if not source:
            continue
        candidate = Path(source) / ".storage/core.config_entries"
        return candidate
    return None


def is_ha_container_running() -> bool:
    """Return whether the HA container is currently running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", HA_DOCKER_CONTAINER],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def update_ha_config_via_docker_cp(
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    app_id: str | None = None,
    app_key: str | None = None,
    key_id: str | None = None,
) -> bool:
    """Update HA config entry by copying the storage file out/in of the container."""
    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / "core.config_entries"
        copy_out = subprocess.run(
            [
                "docker",
                "cp",
                f"{HA_DOCKER_CONTAINER}:/config/.storage/core.config_entries",
                str(local_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if copy_out.returncode != 0 or not local_path.exists():
            return False

        payload = json.loads(local_path.read_text())
        changed = False
        for entry in payload.get("data", {}).get("entries", []):
            if entry.get("domain") != "aqara_fp2":
                continue
            entry["data"] = merge_aqara_entry_data(
                entry.get("data", {}),
                access_token=access_token,
                refresh_token=refresh_token,
                app_id=app_id,
                app_key=app_key,
                key_id=key_id,
            )
            changed = True
            break

        if not changed:
            return False

        local_path.write_text(json.dumps(payload, indent=4))
        copy_in = subprocess.run(
            [
                "docker",
                "cp",
                str(local_path),
                f"{HA_DOCKER_CONTAINER}:/config/.storage/core.config_entries",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return copy_in.returncode == 0


def mask(value: str | None, *, head: int = 6, tail: int = 4) -> str:
    """Mask a secret-like string for logs."""
    if not value:
        return "<empty>"
    if len(value) <= head + tail:
        return value
    return f"{value[:head]}...{value[-tail:]}"


def unique_nonempty(values: list[str | None]) -> list[str]:
    """Keep only unique non-empty strings preserving order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def load_ha_entry_data() -> dict[str, Any]:
    """Read the live Aqara FP2 config entry from local HA storage."""
    volume_path = get_ha_volume_config_entries_path()
    if volume_path and volume_path.exists():
        payload = json.loads(volume_path.read_text())
        for entry in payload.get("data", {}).get("entries", []):
            if entry.get("domain") == "aqara_fp2":
                return dict(entry.get("data", {}))

    docker_payload = run_ha_python(
        """
import json
from pathlib import Path
p = Path('/config/.storage/core.config_entries')
d = json.loads(p.read_text())
for entry in d.get('data', {}).get('entries', []):
    if entry.get('domain') == 'aqara_fp2':
        print(json.dumps(entry.get('data', {})))
        break
""".strip()
    )
    if docker_payload:
        return json.loads(docker_payload)

    if not HA_CONFIG_ENTRIES_PATH.exists():
        return {}
    payload = json.loads(HA_CONFIG_ENTRIES_PATH.read_text())
    for entry in payload.get("data", {}).get("entries", []):
        if entry.get("domain") == "aqara_fp2":
            return dict(entry.get("data", {}))
    return {}


def merge_aqara_entry_data(
    existing: dict[str, Any],
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    app_id: str | None = None,
    app_key: str | None = None,
    key_id: str | None = None,
) -> dict[str, Any]:
    """Return updated HA config-entry data for Aqara FP2."""
    merged = dict(existing)
    if access_token:
        merged["access_token"] = access_token
    if refresh_token:
        merged["refresh_token"] = refresh_token
    if app_id:
        merged["app_id"] = app_id
    if app_key:
        merged["app_key"] = app_key
    if key_id:
        merged["key_id"] = key_id
    return merged


def update_ha_config(
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    app_id: str | None = None,
    app_key: str | None = None,
    key_id: str | None = None,
) -> bool:
    """Update live HA config entry on disk."""
    volume_path = get_ha_volume_config_entries_path()
    if volume_path and volume_path.exists():
        payload = json.loads(volume_path.read_text())
        changed = False
        for entry in payload.get("data", {}).get("entries", []):
            if entry.get("domain") != "aqara_fp2":
                continue
            entry["data"] = merge_aqara_entry_data(
                entry.get("data", {}),
                access_token=access_token,
                refresh_token=refresh_token,
                app_id=app_id,
                app_key=app_key,
                key_id=key_id,
            )
            changed = True
            break

        if changed:
            volume_path.write_text(json.dumps(payload, indent=4))
            print("✅ Updated persistent Home Assistant Aqara FP2 config entry")
            return True

    if update_ha_config_via_docker_cp(
        access_token=access_token,
        refresh_token=refresh_token,
        app_id=app_id,
        app_key=app_key,
        key_id=key_id,
    ):
        print("✅ Updated persistent Home Assistant Aqara FP2 config entry via docker cp")
        return True

    script = f"""
import json
from pathlib import Path
p = Path('/config/.storage/core.config_entries')
d = json.loads(p.read_text())
changed = False
for entry in d.get('data', {{}}).get('entries', []):
    if entry.get('domain') != 'aqara_fp2':
        continue
    data = dict(entry.get('data', {{}}))
    if {bool(access_token)!r}:
        data['access_token'] = {access_token!r}
    if {bool(refresh_token)!r}:
        data['refresh_token'] = {refresh_token!r}
    if {bool(app_id)!r}:
        data['app_id'] = {app_id!r}
    if {bool(app_key)!r}:
        data['app_key'] = {app_key!r}
    if {bool(key_id)!r}:
        data['key_id'] = {key_id!r}
    entry['data'] = data
    changed = True
    break
if changed:
    p.write_text(json.dumps(d, indent=4))
    print('UPDATED')
""".strip()
    docker_result = run_ha_python(script)
    if docker_result == "UPDATED":
        print("✅ Updated live Home Assistant Aqara FP2 config entry")
        return True

    if not HA_CONFIG_ENTRIES_PATH.exists():
        print("⚠️  HA config_entries file not found, skipping local HA update")
        return False

    payload = json.loads(HA_CONFIG_ENTRIES_PATH.read_text())
    changed = False
    for entry in payload.get("data", {}).get("entries", []):
        if entry.get("domain") != "aqara_fp2":
            continue
        entry["data"] = merge_aqara_entry_data(
            entry.get("data", {}),
            access_token=access_token,
            refresh_token=refresh_token,
            app_id=app_id,
            app_key=app_key,
            key_id=key_id,
        )
        changed = True
        break

    if not changed:
        print("⚠️  Aqara FP2 config entry not found in HA storage")
        return False

    HA_CONFIG_ENTRIES_PATH.write_text(json.dumps(payload, indent=4))
    print("✅ Updated repo-local HA Aqara FP2 config entry")
    return True


def update_env_file(
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
    key_id: str | None = None,
) -> bool:
    """Update selected Aqara values in local .env."""
    if not ENV_PATH.exists():
        print("⚠️  Local .env not found, skipping env update")
        return False

    content = ENV_PATH.read_text()
    replacements = {
        "AQARA_ACCESS_TOKEN": access_token,
        "AQARA_REFRESH_TOKEN": refresh_token,
        "AQARA_KEY_ID": key_id,
    }
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        for key, value in replacements.items():
            if value and line.startswith(f"{key}="):
                lines[idx] = f"{key}={value}"
    ENV_PATH.write_text("\n".join(lines) + "\n")
    print("✅ Updated local .env Aqara values")
    return True


def build_signed_headers(
    *,
    app_id: str,
    app_key: str,
    key_id: str,
    access_token: str | None = None,
) -> dict[str, str]:
    """Build Aqara V3 signed headers."""
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    params = {
        "Appid": app_id,
        "Keyid": key_id,
        "Nonce": nonce,
        "Time": timestamp,
    }
    if access_token:
        params["Accesstoken"] = access_token

    concat = "&".join(f"{key}={params[key]}" for key in sorted(params)) + app_key
    sign = hashlib.md5(concat.lower().encode()).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "Appid": app_id,
        "Keyid": key_id,
        "Nonce": nonce,
        "Time": timestamp,
        "Sign": sign,
        "Lang": "en",
    }
    if access_token:
        headers["Accesstoken"] = access_token
    return headers


def run_ha_python(code: str) -> str | None:
    """Execute a small Python snippet inside the HA container."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            HA_DOCKER_CONTAINER,
            "python3",
            "-c",
            code,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


async def aqara_request(
    *,
    intent: str,
    data: dict[str, Any],
    app_id: str,
    app_key: str,
    key_id: str,
    access_token: str | None = None,
) -> dict[str, Any]:
    """Perform a signed Aqara API request."""
    headers = build_signed_headers(
        app_id=app_id,
        app_key=app_key,
        key_id=key_id,
        access_token=access_token,
    )
    async with aiohttp.ClientSession() as session:
        async with session.post(
            API_URL,
            headers=headers,
            json={"intent": intent, "data": data},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            payload = await response.json(content_type=None)
            payload["_http_status"] = response.status
            return payload


async def try_refresh_token(
    *,
    app_id: str,
    app_key: str,
    key_candidates: list[str],
    refresh_candidates: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Try to refresh with known refresh tokens and key candidates."""
    for key_id in key_candidates:
        for refresh_token in refresh_candidates:
            result = await aqara_request(
                intent="config.auth.refreshToken",
                data={"refreshToken": refresh_token},
                app_id=app_id,
                app_key=app_key,
                key_id=key_id,
            )
            code = result.get("code")
            if code == 0:
                return result, key_id
            print(
                "⚠️  refresh failed:",
                f"key_id={key_id}",
                f"refresh={mask(refresh_token)}",
                f"code={code}",
                f"detail={result.get('msgDetails') or result.get('messageDetail')}",
            )
    return None, None


async def request_auth_code(
    *,
    account: str,
    app_id: str,
    app_key: str,
    key_candidates: list[str],
) -> str | None:
    """Request an Aqara auth code to be sent to the account email."""
    for key_id in key_candidates:
        result = await aqara_request(
            intent="config.auth.getAuthCode",
            data={
                "account": account,
                "accountType": 0,
                "accessTokenValidity": "7d",
            },
            app_id=app_id,
            app_key=app_key,
            key_id=key_id,
        )
        code = result.get("code")
        if code == 0:
            print(
                "✅ Aqara auth code requested successfully.",
                f"key_id={key_id}",
                "Проверь email Aqara и затем запусти этот скрипт с --auth-code.",
            )
            return key_id
        print(
            "⚠️  auth-code request failed:",
            f"key_id={key_id}",
            f"code={code}",
            f"detail={result.get('msgDetails') or result.get('messageDetail')}",
        )
    return None


async def exchange_auth_code(
    *,
    auth_code: str,
    account: str,
    app_id: str,
    app_key: str,
    key_id: str,
) -> dict[str, Any]:
    """Exchange auth code for fresh access and refresh tokens."""
    return await aqara_request(
        intent="config.auth.getToken",
        data={
            "authCode": auth_code,
            "account": account,
            "accountType": 0,
        },
        app_id=app_id,
        app_key=app_key,
        key_id=key_id,
    )


def restart_home_assistant() -> None:
    """Restart local Home Assistant container."""
    subprocess.run(["docker", "restart", HA_DOCKER_CONTAINER], check=False)


def stop_home_assistant() -> None:
    """Stop local Home Assistant container."""
    subprocess.run(["docker", "stop", HA_DOCKER_CONTAINER], check=False)


def start_home_assistant() -> None:
    """Start local Home Assistant container."""
    subprocess.run(["docker", "start", HA_DOCKER_CONTAINER], check=False)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-code", default=os.getenv("AQARA_AUTH_CODE"))
    parser.add_argument("--restart-ha", action="store_true")
    args = parser.parse_args()

    ha_entry = load_ha_entry_data()
    app_id = os.getenv("AQARA_APP_ID") or ha_entry.get("app_id") or DEFAULT_APP_ID
    app_key = os.getenv("AQARA_APP_KEY") or ha_entry.get("app_key") or DEFAULT_APP_KEY
    key_candidates = unique_nonempty(
        [
            os.getenv("AQARA_KEY_ID"),
            ha_entry.get("key_id"),
            DEFAULT_KEY_ID,
        ]
    )
    refresh_candidates = unique_nonempty(
        [
            ha_entry.get("refresh_token"),
            os.getenv("AQARA_REFRESH_TOKEN"),
        ]
    )
    account = os.getenv("AQARA_EMAIL")

    print("=" * 60)
    print("AQARA TOKEN REPAIR")
    print("=" * 60)
    print(f"API domain: {API_DOMAIN}")
    print(f"App ID: {app_id}")
    print(f"Key candidates: {', '.join(key_candidates)}")
    print(f"Refresh candidates: {len(refresh_candidates)}")
    print()

    was_running = is_ha_container_running()
    stopped_for_persistent_update = args.restart_ha and was_running
    if stopped_for_persistent_update:
        print("🛑 Stopping Home Assistant container before persistent config update...")
        stop_home_assistant()

    chosen_key_id: str | None = None
    token_result: dict[str, Any] | None = None

    if args.auth_code:
        chosen_key_id = key_candidates[0]
        token_result = await exchange_auth_code(
            auth_code=args.auth_code,
            account=account,
            app_id=app_id,
            app_key=app_key,
            key_id=chosen_key_id,
        )
        if token_result.get("code") != 0:
            print(
                "❌ auth-code exchange failed:",
                token_result.get("msgDetails") or token_result.get("messageDetail"),
            )
            if stopped_for_persistent_update:
                print("🔄 Restoring Home Assistant container after failed auth-code exchange...")
                start_home_assistant()
            return 1
    else:
        token_result, chosen_key_id = await try_refresh_token(
            app_id=app_id,
            app_key=app_key,
            key_candidates=key_candidates,
            refresh_candidates=refresh_candidates,
        )

    if token_result is None:
        requested_key = await request_auth_code(
            account=account,
            app_id=app_id,
            app_key=app_key,
            key_candidates=key_candidates,
        )
        if requested_key:
            update_ha_config(app_id=app_id, app_key=app_key, key_id=requested_key)
            if stopped_for_persistent_update:
                print("🔄 Restoring Home Assistant container after auth-code request...")
                start_home_assistant()
            return 2
        print("❌ Unable to refresh token or request auth code.")
        if stopped_for_persistent_update:
            print("🔄 Restoring Home Assistant container after unsuccessful refresh flow...")
            start_home_assistant()
        return 1

    result_payload = token_result.get("result", {})
    access_token = result_payload.get("accessToken")
    refresh_token = result_payload.get("refreshToken")
    if not access_token or not refresh_token:
        print("❌ Aqara response did not include fresh tokens.")
        if stopped_for_persistent_update:
            print("🔄 Restoring Home Assistant container after incomplete token response...")
            start_home_assistant()
        return 1

    print("✅ Obtained fresh Aqara tokens")
    print(f"Access token: {mask(access_token)}")
    print(f"Refresh token: {mask(refresh_token)}")

    update_env_file(
        access_token=access_token,
        refresh_token=refresh_token,
        key_id=chosen_key_id,
    )
    update_ha_config(
        access_token=access_token,
        refresh_token=refresh_token,
        app_id=app_id,
        app_key=app_key,
        key_id=chosen_key_id,
    )

    if args.restart_ha:
        print("🔄 Starting Home Assistant container with updated persistent config...")
        start_home_assistant()
    elif not args.restart_ha and was_running:
        print("ℹ️  Home Assistant was left running; note that hot config-entry edits may be overwritten on shutdown.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
