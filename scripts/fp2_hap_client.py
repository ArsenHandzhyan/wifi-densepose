#!/usr/bin/env python3
"""Minimal local HAP tooling for Aqara FP2.

This script is intentionally split into two pragmatic stages:
1. `list` and `watch` to discover the real local HomeKit characteristics.
2. `monitor` to push a normalized subset into the existing `/api/v1/fp2/push`.

The first stage matters because Aqara FP2 often exposes less data via public
HomeKit/HAP than via the Aqara phone app.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path
from typing import Any

import requests
from aiohomekit import Controller, hkjson
from aiohomekit.characteristic_cache import CharacteristicCacheFile
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

from aiohomekit.zeroconf import ZeroconfServiceListener

ROOT_DIR = Path(__file__).resolve().parents[1]
PAIRING_PATH = ROOT_DIR / ".fp2_pairing.json"
CHAR_CACHE_PATH = ROOT_DIR / ".fp2_hap_charmap.json"
PAIRING_CODE_PATH = ROOT_DIR / ".fp2_homekit_code"

logger = logging.getLogger("fp2_hap_client")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local HAP tooling for Aqara FP2")
    parser.add_argument(
        "--pairing-file",
        type=Path,
        default=PAIRING_PATH,
        help="Path to .fp2_pairing.json",
    )
    parser.add_argument(
        "--alias",
        default="fp2",
        help="Local alias for the pairing",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show current local HAP readiness")
    subparsers.add_parser("set-code", help="Save the FP2 HomeKit code locally")
    pair_parser = subparsers.add_parser("pair", help="Create a fresh local HomeKit pairing")
    pair_parser.add_argument(
        "--device-id",
        help="HomeKit accessory id from discovery, e.g. 54:ef:44:79:e0:03",
    )
    pair_parser.add_argument(
        "--pin",
        help="HomeKit setup code in XXX-XX-XXX format; falls back to saved code or prompt",
    )
    pair_parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Discovery timeout in seconds when locating the accessory",
    )
    pair_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing pairing file after creating a timestamped backup",
    )

    list_parser = subparsers.add_parser("list", help="List all local HAP accessories and characteristics")
    list_parser.add_argument(
        "--output",
        choices=["compact", "json"],
        default="compact",
        help="Output format",
    )

    discover_parser = subparsers.add_parser("discover", help="Discover local HomeKit HAP devices via mDNS")
    discover_parser.add_argument(
        "--timeout",
        type=float,
        default=8.0,
        help="Discovery window in seconds",
    )

    watch_parser = subparsers.add_parser("watch", help="Subscribe to specific HAP characteristics")
    watch_parser.add_argument(
        "-c",
        "--characteristic",
        dest="characteristics",
        action="append",
        required=True,
        help="Characteristic in aid.iid form; repeatable",
    )
    watch_parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Fallback poll interval in seconds",
    )

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Push a normalized local HAP subset to backend",
    )
    monitor_parser.add_argument(
        "--backend",
        default="http://127.0.0.1:8000",
        help="Backend base URL",
    )
    monitor_parser.add_argument(
        "--presence-char",
        required=True,
        help="Presence/occupancy characteristic in aid.iid form",
    )
    monitor_parser.add_argument(
        "--light-char",
        help="Optional light level characteristic in aid.iid form",
    )
    monitor_parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Local HAP polling interval in seconds",
    )

    return parser


def setup_logging(level: str) -> None:
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def load_pairing_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Pairing file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Pairing file must contain a JSON object: {path}")
    if "AccessoryPairingID" not in payload:
        raise ValueError(f"Invalid pairing file: missing AccessoryPairingID in {path}")
    payload.setdefault("Connection", "IP")
    return payload


def save_pairing_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(hkjson.dumps_indented(payload), encoding="utf-8")
    os.chmod(path, 0o600)


def backup_pairing_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_path = path.with_name(f"{path.stem}.backup.{int(time.time())}{path.suffix}")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    os.chmod(backup_path, 0o600)
    return backup_path


def normalize_pairing_code(raw_value: str) -> str:
    digits = "".join(ch for ch in str(raw_value or "") if ch.isdigit())
    if len(digits) != 8:
        raise ValueError("HomeKit code must contain exactly 8 digits")
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


def load_pairing_code(path: Path = PAIRING_CODE_PATH) -> str | None:
    if not path.exists():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return None
    if not value:
        return None
    try:
        return normalize_pairing_code(value)
    except ValueError:
        return value


def prompt_and_save_pairing_code(path: Path = PAIRING_CODE_PATH) -> str:
    first = getpass.getpass("HomeKit code: ").strip()
    second = getpass.getpass("Repeat HomeKit code: ").strip()
    if first != second:
        raise ValueError("Codes do not match")
    normalized = normalize_pairing_code(first)
    path.write_text(normalized + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return normalized


def parse_char_id(raw_value: str) -> tuple[int, int]:
    try:
        aid_str, iid_str = raw_value.split(".", 1)
        return int(aid_str), int(iid_str)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid characteristic id: {raw_value}. Expected aid.iid") from exc


def format_char_id(aid: int, iid: int) -> str:
    return f"{aid}.{iid}"


class HAPSession:
    def __init__(self, pairing_path: Path, alias: str) -> None:
        self.pairing_path = pairing_path
        self.alias = alias
        self.pairing_payload = load_pairing_payload(pairing_path)
        self.zeroconf = AsyncZeroconf()
        self.listener = ZeroconfServiceListener()
        self.browser: AsyncServiceBrowser | None = None
        self.controller = Controller(
            async_zeroconf_instance=self.zeroconf,
            char_cache=CharacteristicCacheFile(CHAR_CACHE_PATH),
        )
        self.pairing = None

    async def __aenter__(self) -> "HAPSession":
        self.browser = AsyncServiceBrowser(
            self.zeroconf.zeroconf,
            ["_hap._tcp.local.", "_hap._udp.local."],
            listener=self.listener,
        )
        await self.controller.async_start()
        self.pairing = self.controller.load_pairing(self.alias, dict(self.pairing_payload))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self.pairing is not None:
                with contextlib.suppress(Exception):
                    await self.pairing.close()
        finally:
            await self.controller.async_stop()
            if self.browser is not None:
                await self.browser.async_cancel()
            await self.zeroconf.async_close()


class ControllerSession:
    def __init__(self) -> None:
        self.zeroconf = AsyncZeroconf()
        self.browser: AsyncServiceBrowser | None = None
        self.controller = Controller(
            async_zeroconf_instance=self.zeroconf,
            char_cache=CharacteristicCacheFile(CHAR_CACHE_PATH),
        )

    async def __aenter__(self) -> "ControllerSession":
        self.browser = AsyncServiceBrowser(
            self.zeroconf.zeroconf,
            ["_hap._tcp.local.", "_hap._udp.local."],
            listener=ZeroconfServiceListener(),
        )
        await self.controller.async_start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.controller.async_stop()
        if self.browser is not None:
            await self.browser.async_cancel()
        await self.zeroconf.async_close()


def check_tcp_endpoint(host: str, port: int, timeout: float = 1.5) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


async def cmd_status(args: argparse.Namespace) -> int:
    pairing = load_pairing_payload(args.pairing_file)
    host = pairing.get("AccessoryIP")
    port = int(pairing.get("AccessoryPort") or 0)
    pairing_code = load_pairing_code()

    print(f"Pairing file: {args.pairing_file}")
    print(f"Saved pairing id: {pairing.get('AccessoryPairingID')}")
    print(f"Saved endpoint: {host}:{port}")
    print(f"Saved HomeKit code: {'yes' if pairing_code else 'no'}")
    print(f"TCP {port}: {'open' if host and port and check_tcp_endpoint(host, port) else 'closed'}")
    print(f"TCP 443: {'open' if host and check_tcp_endpoint(host, 443) else 'closed'}")
    print("mDNS discovery:")
    discover_args = argparse.Namespace(timeout=5.0)
    await cmd_discover(discover_args)
    return 0


async def cmd_set_code(_: argparse.Namespace) -> int:
    normalized = prompt_and_save_pairing_code()
    print(f"Saved HomeKit code: {normalized}")
    return 0


def dump_accessories_compact(data: list[dict[str, Any]]) -> None:
    for accessory in data:
        aid = accessory["aid"]
        print(f"Accessory {aid}")
        for service in accessory.get("services", []):
            service_iid = service["iid"]
            service_type = service["type"]
            print(f"  Service {aid}.{service_iid}  {service_type}")
            for characteristic in service.get("characteristics", []):
                iid = characteristic["iid"]
                value = characteristic.get("value")
                description = characteristic.get("description", "")
                perms = ",".join(characteristic.get("perms", []))
                char_type = characteristic["type"]
                print(
                    f"    {aid}.{iid}  {description or '-'}  "
                    f"type={char_type} perms=[{perms}] value={value!r}"
                )


async def discover_devices(timeout: float) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    zeroconf = AsyncZeroconf()
    controller = Controller(async_zeroconf_instance=zeroconf)
    browser = AsyncServiceBrowser(
        zeroconf.zeroconf,
        ["_hap._tcp.local.", "_hap._udp.local."],
        listener=ZeroconfServiceListener(),
    )
    try:
        await controller.async_start()
        started = time.time()
        async for discovery in controller.async_discover(timeout):
            desc = discovery.description
            device_id = getattr(desc, "id", "").lower()
            if not device_id or device_id in seen:
                continue
            seen[device_id] = discovery
            if time.time() - started >= timeout:
                break
    finally:
        await controller.async_stop()
        await browser.async_cancel()
        await zeroconf.async_close()
    return seen


async def cmd_list(args: argparse.Namespace) -> int:
    async with HAPSession(args.pairing_file, args.alias) as session:
        data = await session.pairing.list_accessories_and_characteristics()
        if args.output == "json":
            print(hkjson.dumps_indented(data))
        else:
            dump_accessories_compact(data)
    return 0


async def cmd_discover(args: argparse.Namespace) -> int:
    seen = await discover_devices(args.timeout)
    for device_id, discovery in seen.items():
        desc = discovery.description
        payload = {
            "name": getattr(desc, "name", ""),
            "id": device_id,
            "model": getattr(desc, "model", ""),
            "address": getattr(desc, "address", ""),
            "addresses": getattr(desc, "addresses", []),
            "port": getattr(desc, "port", None),
            "category": str(getattr(desc, "category", "")),
            "status_flags": str(getattr(desc, "status_flags", "")),
            "paired": discovery.paired,
        }
        print(hkjson.dumps_indented(payload))
    if not seen:
        print("No HAP devices discovered")
    return 0


async def cmd_pair(args: argparse.Namespace) -> int:
    if args.pairing_file.exists() and not args.overwrite:
        raise FileExistsError(
            f"Pairing file already exists: {args.pairing_file}. "
            "Pass --overwrite to replace it after creating a backup."
        )

    pin = args.pin or load_pairing_code() or prompt_and_save_pairing_code()
    pin = normalize_pairing_code(pin)

    async with ControllerSession() as session:
        discovery = None
        if args.device_id:
            discovery = await session.controller.async_find(args.device_id.lower(), timeout=args.timeout)
        else:
            seen: dict[str, Any] = {}
            async for candidate in session.controller.async_discover(args.timeout):
                desc = candidate.description
                device_id = getattr(desc, "id", "").lower()
                if not device_id or device_id in seen:
                    continue
                seen[device_id] = candidate
            candidates = [d for d in seen.values() if not d.paired]
            if not candidates:
                raise RuntimeError(
                    "No unpaired HAP devices discovered. "
                    "Put FP2 into HomeKit pairing mode and retry."
                )
            if len(candidates) > 1:
                device_ids = ", ".join(sorted(getattr(d.description, "id", "?") for d in candidates))
                raise RuntimeError(
                    "Multiple unpaired HAP devices discovered. "
                    f"Retry with --device-id one of: {device_ids}"
                )
            discovery = candidates[0]

        desc = discovery.description
        logger.info(
            "Starting HomeKit pairing with %s (%s)",
            getattr(desc, "name", "") or "unknown",
            getattr(desc, "id", "") or "unknown",
        )

        finish_pairing = await discovery.async_start_pairing(args.alias)
        await finish_pairing(pin)

        pairing = session.controller.aliases.get(args.alias)
        if pairing is None:
            raise RuntimeError(f"Pairing succeeded but alias {args.alias!r} was not registered")

        backup_path = backup_pairing_file(args.pairing_file) if args.overwrite else None
        save_pairing_payload(args.pairing_file, pairing.pairing_data)
        if backup_path:
            logger.info("Previous pairing was backed up to %s", backup_path)

        print(f"Saved pairing: {args.pairing_file}")
        print(f"Accessory id: {pairing.pairing_data.get('AccessoryPairingID')}")
        print(
            "Endpoint: "
            f"{pairing.pairing_data.get('AccessoryIP')}:{pairing.pairing_data.get('AccessoryPort')}"
        )
    return 0


async def cmd_watch(args: argparse.Namespace) -> int:
    watched = [parse_char_id(raw) for raw in args.characteristics]
    stop_event = asyncio.Event()

    def _handle_signal(*_: Any) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            asyncio.get_running_loop().add_signal_handler(sig, _handle_signal)

    async with HAPSession(args.pairing_file, args.alias) as session:
        def handler(data: dict[tuple[int, int], dict[str, Any]]) -> None:
            if not data:
                logger.info("HAP keepalive/availability event")
                return
            flattened = {
                format_char_id(aid, iid): payload
                for (aid, iid), payload in sorted(data.items())
                if (aid, iid) in watched
            }
            if flattened:
                print(hkjson.dumps_indented(flattened))

        session.pairing.dispatcher_connect(handler)
        await session.pairing.subscribe(watched)

        while not stop_event.is_set():
            polled = await session.pairing.get_characteristics(watched)
            handler(polled)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=args.poll_interval)
            except asyncio.TimeoutError:
                continue

    return 0


def normalize_presence(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "occupied"}
    return False


def normalize_light(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def cmd_monitor(args: argparse.Namespace) -> int:
    presence_char = parse_char_id(args.presence_char)
    watched = [presence_char]
    light_char = parse_char_id(args.light_char) if args.light_char else None
    if light_char:
        watched.append(light_char)

    logger.info(
        "Starting local HAP monitor for %s via %s",
        args.alias,
        args.pairing_file,
    )

    async with HAPSession(args.pairing_file, args.alias) as session:
        while True:
            data = await session.pairing.get_characteristics(watched)
            presence_payload = data.get(presence_char, {})
            light_payload = data.get(light_char, {}) if light_char else {}
            presence = normalize_presence(presence_payload.get("value"))
            light_level = normalize_light(light_payload.get("value")) if light_char else None

            payload = {
                "timestamp": time.time(),
                "presence": presence,
                "zones": [
                    {
                        "zone_id": "detection_area",
                        "name": "Detection Area",
                        "occupied": presence,
                        "target_count": 0,
                    }
                ],
                "targets": [],
                "light_level": light_level,
                "source": "hap_direct",
                "raw_attributes": {
                    "source": "hap_direct",
                    "transport": "hap_direct",
                    "push_time": time.time(),
                    "characteristics": {
                        format_char_id(aid, iid): value
                        for (aid, iid), value in sorted(data.items())
                    },
                },
                "device": {
                    "transport": "HomeKit / HAP",
                },
                "connection": {
                    "transport": "hap_direct",
                    "state": "live",
                },
            }

            response = requests.post(
                f"{args.backend.rstrip('/')}/api/v1/fp2/push",
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            logger.info(
                "Pushed local HAP snapshot: presence=%s light=%s",
                presence,
                light_level if light_level is not None else "-",
            )
            await asyncio.sleep(args.poll_interval)


async def async_main(args: argparse.Namespace) -> int:
    if args.command == "status":
        return await cmd_status(args)
    if args.command == "set-code":
        return await cmd_set_code(args)
    if args.command == "pair":
        return await cmd_pair(args)
    if args.command == "discover":
        return await cmd_discover(args)
    if args.command == "list":
        return await cmd_list(args)
    if args.command == "watch":
        return await cmd_watch(args)
    if args.command == "monitor":
        return await cmd_monitor(args)
    raise ValueError(f"Unsupported command: {args.command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.log_level)
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.error("HAP client failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
