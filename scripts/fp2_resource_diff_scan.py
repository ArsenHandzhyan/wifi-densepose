#!/usr/bin/env python3
"""
Deep scan Aqara FP2 resource changes during live movement.

This script:
  - refreshes Aqara Open API tokens
  - resolves the configured FP2 device DID
  - loads full resource definitions for the FP2 model
  - samples live resource values repeatedly
  - prints only resource IDs whose values changed

Use it while the user moves in front of the sensor to discover hidden
movement/point-tracking channels beyond the currently mapped resources.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import random
import sys
import time
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
AQARA_PROBE_PATH = ROOT_DIR / "scripts" / "aqara_api_probe.py"
DEFAULT_OUTPUT_PATH = Path("/tmp/fp2_resource_diff_scan_last.json")


def load_probe_module():
    spec = importlib.util.spec_from_file_location("aqara_api_probe", AQARA_PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {AQARA_PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = load_probe_module()


@dataclass
class ScanContext:
    settings: Any
    did: str
    model: str
    resource_info: dict[str, dict[str, Any]]


def refresh_access_token(settings: Any, *, persist: bool = True) -> None:
    http_status, body = probe.api_call(
        settings,
        "config.auth.refreshToken",
        {"refreshToken": settings.refresh_token},
    )
    if http_status != 200 or body.get("code") != 0:
        raise RuntimeError(f"refreshToken failed: {http_status} {body}")

    result = body.get("result") or {}
    settings.access_token = result.get("accessToken", settings.access_token)
    settings.refresh_token = result.get("refreshToken", settings.refresh_token)
    settings.open_id = result.get("openId", settings.open_id)

    if persist:
        probe.write_env_updates(
            settings.env_path,
            {
                "AQARA_ACCESS_TOKEN": settings.access_token,
                "AQARA_REFRESH_TOKEN": settings.refresh_token,
                "AQARA_OPEN_ID": settings.open_id,
            },
        )


def api_query(settings: Any, intent: str, data: dict[str, Any]) -> dict[str, Any]:
    attempts = 0
    while attempts < 4:
        http_status, body = probe.api_call(
            settings,
            intent,
            data,
            access_token=settings.access_token,
        )
        if http_status == 200 and body.get("code") == 0:
            return body

        if http_status == 200 and body.get("code") == 108:
            refresh_access_token(settings, persist=True)
            attempts += 1
            continue

        # Aqara occasionally rejects back-to-back calls with duplicate request.
        if http_status == 200 and body.get("code") == 302 and "duplicate request" in str(body).lower():
            time.sleep(1.1 + random.random() * 0.6)
            attempts += 1
            continue

        raise RuntimeError(f"{intent} failed: {http_status} {body}")

    raise RuntimeError(f"{intent} failed after retries")


def resolve_device(settings: Any) -> tuple[str, str]:
    body = api_query(
        settings,
        "query.device.info",
        {"dids": [], "positionId": "", "pageNum": 1, "pageSize": 200},
    )
    items = ((body.get("result") or {}).get("data") or [])
    needle = (settings.device_id or "").lower()

    for item in items:
        candidate = str(item.get("did", "")).lower()
        if needle and candidate.endswith(needle):
            return item.get("did"), item.get("model") or settings.model

    for item in items:
        if item.get("model") == settings.model:
            return item.get("did"), item.get("model")

    raise RuntimeError(f"Unable to resolve FP2 DID from {len(items)} devices")


def load_resource_info(settings: Any, model: str) -> dict[str, dict[str, Any]]:
    body = api_query(settings, "query.resource.info", {"model": model})
    return {
        item["resourceId"]: item
        for item in (body.get("result") or [])
        if item.get("resourceId")
    }


def fetch_resource_values(settings: Any, did: str) -> dict[str, dict[str, Any]]:
    body = api_query(
        settings,
        "query.resource.value",
        {"resources": [{"subjectId": did}]},
    )
    return {
        item["resourceId"]: item
        for item in (body.get("result") or [])
        if item.get("resourceId")
    }


def resource_label(meta: dict[str, Any]) -> str:
    return (
        meta.get("description")
        or meta.get("resourceName")
        or meta.get("name")
        or ""
    )


def compact_value(value: Any) -> Any:
    if isinstance(value, str):
        raw = value.strip()
        if (raw.startswith("{") and raw.endswith("}")) or (raw.startswith("[") and raw.endswith("]")):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return value
    return value


def diff_snapshots(
    previous: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    resource_info: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    all_resource_ids = sorted(set(previous) | set(current))
    for resource_id in all_resource_ids:
        prev_item = previous.get(resource_id) or {}
        curr_item = current.get(resource_id) or {}
        prev_value = prev_item.get("value")
        curr_value = curr_item.get("value")
        if str(prev_value) == str(curr_value):
            continue

        meta = resource_info.get(resource_id) or {}
        changed.append(
            {
                "resource_id": resource_id,
                "label": resource_label(meta),
                "value": compact_value(curr_value),
                "previous_value": compact_value(prev_value),
                "timestamp": curr_item.get("timeStamp"),
                "previous_timestamp": prev_item.get("timeStamp"),
            }
        )
    return changed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan live FP2 resource changes")
    parser.add_argument("--env-file", type=Path, default=ROOT_DIR / ".env", help="Path to .env")
    parser.add_argument("--samples", type=int, default=15, help="Number of samples to capture")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between samples")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Where to save JSON results")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = probe.load_settings(args.env_file)

    # Leave a gap before the first signed request so repeated scans do not hit
    # Aqara duplicate-request protection. Start with the current access token and
    # refresh only if Aqara returns code 108, because stale refresh tokens can
    # fail even when the access token is still valid.
    time.sleep(1.3)
    did, model = resolve_device(settings)
    resource_info = load_resource_info(settings, model)
    baseline = fetch_resource_values(settings, did)

    print(f"FP2 DID: {did}")
    print(f"Model:   {model}")
    print(f"Live resources in baseline: {len(baseline)}")
    print("MOVE_NOW")

    history: list[dict[str, Any]] = []
    previous = baseline
    for index in range(args.samples):
        current = fetch_resource_values(settings, did)
        changed = diff_snapshots(previous, current, resource_info)
        print(f"[{index:02d}] changed={len(changed)}")
        for row in changed:
            print(json.dumps(row, ensure_ascii=False))
        history.append(
            {
                "sample_index": index,
                "captured_at": time.time(),
                "changed": changed,
            }
        )
        previous = current
        time.sleep(args.interval)

    args.output.write_text(
        json.dumps(
            {
                "did": did,
                "model": model,
                "samples": history,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"Saved scan report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
