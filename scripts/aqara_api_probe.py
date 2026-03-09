#!/usr/bin/env python3
"""
Unified Aqara Open API probe for this workspace.

This script replaces the old one-off experiments with a single CLI that:
  - reads credentials and tokens from .env
  - uses the verified sorted-params V3 signature
  - can refresh tokens
  - can request auth codes
  - can exchange auth codes for tokens
  - can probe device endpoints for the configured FP2

Examples:
  python3 scripts/aqara_api_probe.py status
  python3 scripts/aqara_api_probe.py probe
  python3 scripts/aqara_api_probe.py probe --refresh-first
  python3 scripts/aqara_api_probe.py get-auth-code
  python3 scripts/aqara_api_probe.py exchange-auth-code 123456
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any

import requests


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_OUTPUT_PATH = Path("/tmp/aqara_api_probe_last.json")


@dataclass
class Settings:
    env_path: Path
    aqara_email: str
    aqara_password: str
    api_domain: str
    app_id: str
    app_key: str
    key_id: str
    access_token: str
    refresh_token: str
    open_id: str
    device_id: str
    device_name: str
    model: str

    @property
    def api_url(self) -> str:
        return f"https://{self.api_domain}/v3.0/open/api"


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def load_settings(env_path: Path) -> Settings:
    env = load_dotenv(env_path)
    for key in (
        "AQARA_EMAIL",
        "AQARA_PASSWORD",
        "AQARA_API_DOMAIN",
        "AQARA_APP_ID",
        "AQARA_APP_KEY",
        "AQARA_KEY_ID",
        "AQARA_ACCESS_TOKEN",
        "AQARA_REFRESH_TOKEN",
        "AQARA_OPEN_ID",
        "AQARA_ACCESS_TOKEN_EXPIRES",
        "FP2_DEVICE_ID",
        "FP2_NAME",
        "FP2_MODEL",
        "FP2_FIRMWARE",
    ):
        value = os.environ.get(key)
        if value not in (None, ""):
            env[key] = value
    return Settings(
        env_path=env_path,
        aqara_email=env.get("AQARA_EMAIL", ""),
        aqara_password=env.get("AQARA_PASSWORD", ""),
        api_domain=env.get("AQARA_API_DOMAIN", "open-ger.aqara.com"),
        app_id=env.get("AQARA_APP_ID", ""),
        app_key=env.get("AQARA_APP_KEY", ""),
        key_id=env.get("AQARA_KEY_ID", ""),
        access_token=env.get("AQARA_ACCESS_TOKEN", ""),
        refresh_token=env.get("AQARA_REFRESH_TOKEN", ""),
        open_id=env.get("AQARA_OPEN_ID", ""),
        device_id=env.get("FP2_DEVICE_ID", ""),
        device_name=env.get("FP2_NAME", ""),
        model=env.get("FP2_MODEL", ""),
    )


def mask_secret(value: str, keep: int = 4) -> str:
    if not value:
        return "-"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def sign_headers(settings: Settings, access_token: str = "") -> dict[str, str]:
    nonce = str(random.randint(100000, 999999))
    timestamp = str(int(time.time() * 1000))
    params = {
        "Appid": settings.app_id,
        "Keyid": settings.key_id,
        "Nonce": nonce,
        "Time": timestamp,
    }
    if access_token:
        params["Accesstoken"] = access_token

    sign_input = "&".join(f"{key}={params[key]}" for key in sorted(params))
    sign = hashlib.md5(f"{sign_input}{settings.app_key}".lower().encode()).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "Appid": settings.app_id,
        "Keyid": settings.key_id,
        "Nonce": nonce,
        "Time": timestamp,
        "Sign": sign,
        "Lang": "en",
    }
    if access_token:
        headers["Accesstoken"] = access_token
    return headers


def api_call(
    settings: Settings,
    intent: str,
    data: dict[str, Any] | None = None,
    *,
    access_token: str = "",
    api_domain: str | None = None,
) -> tuple[int, dict[str, Any]]:
    url = f"https://{api_domain or settings.api_domain}/v3.0/open/api"
    response = requests.post(
        url,
        headers=sign_headers(settings, access_token),
        json={"intent": intent, "data": data or {}},
        timeout=20,
    )
    body = response.json()
    return response.status_code, body


def summarize_response(http_status: int, body: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "http_status": http_status,
        "code": body.get("code"),
        "message": body.get("message"),
        "messageDetail": body.get("messageDetail"),
    }
    result = body.get("result")
    summary["result_type"] = type(result).__name__
    if isinstance(result, dict):
        summary["result_keys"] = sorted(result.keys())
        for key in ("data", "deviceList", "list"):
            if isinstance(result.get(key), list):
                summary[f"{key}_len"] = len(result[key])
    elif isinstance(result, str):
        summary["result_preview"] = result[:120]
    return summary


def print_block(title: str, payload: dict[str, Any]) -> None:
    print(f"=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def write_env_updates(env_path: Path, updates: dict[str, str]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    pending = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _value = line.split("=", 1)
        if key in pending:
            new_lines.append(f"{key}={pending.pop(key)}")
        else:
            new_lines.append(line)
    for key, value in pending.items():
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def save_probe_output(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    status = {
        "env_path": str(settings.env_path),
        "api_url": settings.api_url,
        "aqara_email": settings.aqara_email,
        "app_id": settings.app_id,
        "key_id": settings.key_id,
        "access_token": mask_secret(settings.access_token),
        "refresh_token": mask_secret(settings.refresh_token),
        "open_id": mask_secret(settings.open_id),
        "device_id": settings.device_id,
        "device_name": settings.device_name,
        "model": settings.model,
    }
    print_block("status", status)
    return 0


def cmd_refresh(args: argparse.Namespace, settings: Settings) -> int:
    if not settings.refresh_token:
        print("AQARA_REFRESH_TOKEN is missing in .env", file=sys.stderr)
        return 1

    http_status, body = api_call(
        settings,
        "config.auth.refreshToken",
        {"refreshToken": settings.refresh_token},
    )
    summary = summarize_response(http_status, body)
    print_block("refreshToken", summary)

    if body.get("code") != 0:
        return 1

    result = body.get("result") or {}
    output = {
        "refreshToken": summary,
        "tokens": {
            "accessToken": mask_secret(result.get("accessToken", "")),
            "refreshToken": mask_secret(result.get("refreshToken", "")),
            "openId": mask_secret(result.get("openId", "")),
            "expiresIn": result.get("expiresIn"),
        },
    }
    save_probe_output(args.output, output)

    if args.write_env:
        expires_at = datetime.now() + timedelta(seconds=int(result.get("expiresIn", 0) or 0))
        updates = {
            "AQARA_ACCESS_TOKEN": result.get("accessToken", ""),
            "AQARA_REFRESH_TOKEN": result.get("refreshToken", ""),
            "AQARA_OPEN_ID": result.get("openId", ""),
            "AQARA_ACCESS_TOKEN_EXPIRES": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        write_env_updates(settings.env_path, updates)
        print(f"Updated {settings.env_path}")
    else:
        print("Dry run only; .env not modified. Use --write-env to persist tokens.")

    return 0


def cmd_get_auth_code(args: argparse.Namespace, settings: Settings) -> int:
    data: dict[str, Any] = {
        "account": args.account or settings.aqara_email,
        "accountType": args.account_type,
        "accessTokenValidity": args.access_token_validity,
    }
    if args.auth_type is not None:
        data["authType"] = args.auth_type

    http_status, body = api_call(settings, "config.auth.getAuthCode", data)
    summary = summarize_response(http_status, body)
    print_block("getAuthCode", summary)

    result = body.get("result")
    auth_code = result.get("authCode") if isinstance(result, dict) else None
    if auth_code:
        print(f"authCode: {auth_code}")
        save_probe_output(args.output, {"getAuthCode": summary, "authCode": auth_code})
        return 0
    return 1


def cmd_exchange_auth_code(args: argparse.Namespace, settings: Settings) -> int:
    data: dict[str, Any] = {"authCode": args.auth_code}
    account = args.account or settings.aqara_email
    if account:
        data["account"] = account
    if args.account_type is not None:
        data["accountType"] = args.account_type

    http_status, body = api_call(settings, "config.auth.getToken", data)
    summary = summarize_response(http_status, body)
    print_block("getToken", summary)

    if body.get("code") != 0:
        return 1

    result = body.get("result") or {}
    output = {
        "getToken": summary,
        "tokens": {
            "accessToken": mask_secret(result.get("accessToken", "")),
            "refreshToken": mask_secret(result.get("refreshToken", "")),
            "openId": mask_secret(result.get("openId", "")),
            "expiresIn": result.get("expiresIn"),
        },
    }
    save_probe_output(args.output, output)

    if args.write_env:
        expires_at = datetime.now() + timedelta(seconds=int(result.get("expiresIn", 0) or 0))
        updates = {
            "AQARA_ACCESS_TOKEN": result.get("accessToken", ""),
            "AQARA_REFRESH_TOKEN": result.get("refreshToken", ""),
            "AQARA_OPEN_ID": result.get("openId", ""),
            "AQARA_ACCESS_TOKEN_EXPIRES": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
        }
        write_env_updates(settings.env_path, updates)
        print(f"Updated {settings.env_path}")
    else:
        print("Dry run only; .env not modified. Use --write-env to persist tokens.")

    return 0


def cmd_login_password(args: argparse.Namespace, settings: Settings) -> int:
    payload = {
        "account": args.account or settings.aqara_email,
        "password": args.password or settings.aqara_password,
    }
    http_status, body = api_call(settings, "account.loginByPassword", payload)
    print_block("loginByPassword", summarize_response(http_status, body))
    return 0 if body.get("code") == 0 else 1


def cmd_probe(args: argparse.Namespace, settings: Settings) -> int:
    token = settings.access_token
    output: dict[str, Any] = {
        "api_url": settings.api_url,
        "device_id": settings.device_id,
        "device_name": settings.device_name,
        "model": settings.model,
        "region": args.region or settings.api_domain,
    }

    if args.refresh_first:
        refresh_status, refresh_body = api_call(
            settings,
            "config.auth.refreshToken",
            {"refreshToken": settings.refresh_token},
            api_domain=args.region,
        )
        output["refreshToken"] = summarize_response(refresh_status, refresh_body)
        if refresh_body.get("code") == 0:
            token = (refresh_body.get("result") or {}).get("accessToken", token)

    checks = [
        # Legacy/config intents that were previously used in this workspace.
        ("device.getList", "config.device.getList", {}),
        ("device.info", "config.device.info", {"did": settings.device_id}),
        ("device.getState", "config.device.getState", {"did": settings.device_id}),
        (
            "resource.query",
            "config.resource.query",
            {"did": settings.device_id, "resourceId": args.resource_id},
        ),
        # Current authorized-access intents from Aqara docs.
        (
            "query.device.info",
            "query.device.info",
            {"dids": [settings.device_id], "positionId": "", "pageNum": 1, "pageSize": 50},
        ),
        (
            "query.resource.info",
            "query.resource.info",
            {"model": settings.model} if settings.model else {},
        ),
        (
            "query.resource.value",
            "query.resource.value",
            {"resources": [{"subjectId": settings.device_id, "resourceIds": []}]},
        ),
    ]

    exit_code = 1
    for label, intent, data in checks:
        http_status, body = api_call(
            settings,
            intent,
            data,
            access_token=token,
            api_domain=args.region,
        )
        output[label] = summarize_response(http_status, body)
        if body.get("code") == 0:
            exit_code = 0
    save_probe_output(args.output, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return exit_code


def cmd_auth_matrix(args: argparse.Namespace, settings: Settings) -> int:
    account = args.account or settings.aqara_email
    password = args.password or settings.aqara_password
    tests = [
        ("account.loginByPassword", {"account": account, "password": password}),
        ("config.auth.getAuthCode", {"account": account, "accountType": 0}),
        ("config.auth.getToken", {"account": account, "accountType": 0}),
    ]
    output: dict[str, Any] = {"api_url": settings.api_url}
    success = False
    for intent, data in tests:
        http_status, body = api_call(settings, intent, data, api_domain=args.region)
        output[intent] = summarize_response(http_status, body)
        if body.get("code") == 0:
            success = True
    save_probe_output(args.output, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if success else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified Aqara Open API probe")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help=f"Path to .env (default: {DEFAULT_ENV_PATH})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Where to save the last probe JSON (default: {DEFAULT_OUTPUT_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show masked configuration loaded from .env")

    refresh = subparsers.add_parser("refresh", help="Refresh the current Aqara access token")
    refresh.add_argument("--write-env", action="store_true", help="Persist new tokens back to .env")

    auth_code = subparsers.add_parser("get-auth-code", help="Request an authCode")
    auth_code.add_argument("--account", default=None, help="Aqara account email")
    auth_code.add_argument("--account-type", type=int, default=0, help="0=Aqara account, 2=virtual account")
    auth_code.add_argument("--auth-type", type=int, default=None, help="Optional Aqara authType")
    auth_code.add_argument(
        "--access-token-validity",
        default="30d",
        help="Requested token validity window for getAuthCode",
    )

    exchange = subparsers.add_parser("exchange-auth-code", help="Exchange authCode for tokens")
    exchange.add_argument("auth_code", help="6-digit authCode returned by Aqara")
    exchange.add_argument("--account", default=None, help="Aqara account email")
    exchange.add_argument("--account-type", type=int, default=0, help="0=Aqara account, 2=virtual account")
    exchange.add_argument("--write-env", action="store_true", help="Persist new tokens back to .env")

    login = subparsers.add_parser("login-password", help="Try account.loginByPassword")
    login.add_argument("--account", default=None, help="Aqara account email")
    login.add_argument("--password", default=None, help="Aqara account password")

    probe = subparsers.add_parser("probe", help="Probe device endpoints with the configured token")
    probe.add_argument("--refresh-first", action="store_true", help="Refresh the token before probing")
    probe.add_argument("--region", default=None, help="Override API domain for this run")
    probe.add_argument("--resource-id", default="0.1.85", help="Resource ID for config.resource.query")

    matrix = subparsers.add_parser("auth-matrix", help="Run a compact auth capability matrix")
    matrix.add_argument("--account", default=None, help="Aqara account email")
    matrix.add_argument("--password", default=None, help="Aqara account password")
    matrix.add_argument("--region", default=None, help="Override API domain for this run")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = load_settings(args.env_file)

    commands = {
        "status": cmd_status,
        "refresh": cmd_refresh,
        "get-auth-code": cmd_get_auth_code,
        "exchange-auth-code": cmd_exchange_auth_code,
        "login-password": cmd_login_password,
        "probe": cmd_probe,
        "auth-matrix": cmd_auth_matrix,
    }
    return commands[args.command](args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
