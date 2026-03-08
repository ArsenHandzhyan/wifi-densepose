#!/usr/bin/env python3
"""
FP2 All Endpoints Real-time Monitor

This script monitors ALL resource endpoints of your FP2 device in real-time.
It shows which endpoints update when you move, breathe, or walk through the detection area.

Usage:
    python3 scripts/fp2_monitor_all_endpoints.py
    
Then move in front of your FP2 sensor and watch which endpoints change!
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parents[1]
AQARA_PROBE_PATH = ROOT_DIR / "scripts" / "aqara_api_probe.py"


def load_probe_module():
    spec = importlib.util.spec_from_file_location("aqara_api_probe", AQARA_PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {AQARA_PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = load_probe_module()


# Known FP2 resource IDs and their meanings
KNOWN_RESOURCES = {
    "3.51.85": "Presence (0/1)",
    "0.4.85": "Light Level (lux)",
    "8.0.2026": "RSSI (dBm)",
    "8.0.2045": "Online State (0/1)",
    "13.27.85": "Movement Event Code",
    "4.31.85": "Fall State Code",
    "8.0.2116": "Sensor Angle (degrees)",
    "13.120.85": "Total Target Count",
    "4.22.700": "Coordinates Payload (JSON)",
    # Zone occupancy resources (3.X.85 where X is zone number 1-30)
    # Zone target count resources (13.12X.85 where X is zone number 1-30)
}


@dataclass
class Settings:
    env_path: Path
    access_token: str
    refresh_token: str
    open_id: str
    api_domain: str
    device_id: str
    model: str = "lumi.motion.agl001"


def load_settings(env_path: Path) -> Settings:
    return probe.load_settings(env_path)


def refresh_access_token(settings: Settings) -> None:
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

    probe.write_env_updates(
        settings.env_path,
        {
            "AQARA_ACCESS_TOKEN": settings.access_token,
            "AQARA_REFRESH_TOKEN": settings.refresh_token,
            "AQARA_OPEN_ID": settings.open_id,
        },
    )
    print("✅ Access token refreshed")


def api_query(settings: Settings, intent: str, data: dict[str, Any]) -> dict[str, Any]:
    http_status, body = probe.api_call(
        settings,
        intent,
        data,
        access_token=settings.access_token,
    )
    
    if http_status == 200 and body.get("code") == 0:
        return body
    
    if http_status == 200 and body.get("code") == 108:
        refresh_access_token(settings)
        return api_query(settings, intent, data)
    
    raise RuntimeError(f"{intent} failed: {http_status} {body}")


def fetch_all_resources(settings: Settings, did: str) -> dict[str, Any]:
    """Fetch all resource values for the device."""
    body = api_query(
        settings,
        "query.resource.value",
        {"resources": [{"subjectId": did}]},
    )
    
    result = body.get("result") or []
    if not isinstance(result, list):
        raise RuntimeError("query.resource.value returned unexpected payload")
    
    # Convert to dict keyed by resource ID
    resources_dict = {}
    for item in result:
        resource_id = str(item.get("resourceId"))
        if resource_id:
            resources_dict[resource_id] = item
    
    return resources_dict


def format_resource_value(resource_id: str, item: dict[str, Any]) -> str:
    """Format resource value for display."""
    value = item.get("value")
    
    if resource_id == "4.22.700":  # Coordinates
        try:
            coords = json.loads(value) if isinstance(value, str) else value
            active = [c for c in coords if c.get("state") == "1" and (c.get("x", 0) != 0 or c.get("y", 0) != 0)]
            if active:
                return f"{len(active)} targets: {[(t['x'], t['y']) for t in active]}"
            return "0 active targets"
        except:
            return str(value)[:80]
    
    elif resource_id.startswith("3.") and resource_id.endswith(".85"):
        # Zone occupancy
        zone_num = resource_id.split(".")[1]
        status = "OCCUPIED" if value == "1" else "CLEAR"
        return f"Zone {zone_num}: {status}"
    
    elif resource_id.startswith("13.12") and resource_id.endswith(".85"):
        # Zone target count
        zone_num = resource_id.split(".")[1].replace("12", "")
        return f"Zone {zone_num}: {value} targets"
    
    else:
        # Standard resources
        label = KNOWN_RESOURCES.get(resource_id, "Unknown")
        return f"{value} ({label})"


def monitor_resources(settings: Settings, did: str, interval: float = 1.0):
    """Monitor all resources in real-time and show changes."""
    print("\n" + "="*80)
    print("🔍 FP2 ALL ENDPOINTS REAL-TIME MONITOR")
    print("="*80)
    print(f"Device: {did}")
    print(f"Model: {settings.model}")
    print(f"Monitoring interval: {interval}s")
    print("\n📋 INSTRUCTIONS:")
    print("  1. Move in front of your FP2 sensor")
    print("  2. Walk through the detection area")
    print("  3. Breathe heavily")
    print("  4. Watch which endpoints change!")
    print("\n⌨️  CONTROLS:")
    print("  - Press Ctrl+C to stop")
    print("="*80)
    print()
    
    previous_resources = None
    sample_count = 0
    
    try:
        while True:
            sample_count += 1
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            # Fetch current resources
            current_resources = fetch_all_resources(settings, did)
            
            # Detect changes
            changed_resources = []
            new_resources = []
            
            if previous_resources:
                for rid, curr_item in current_resources.items():
                    curr_value = curr_item.get("value")
                    curr_time = curr_item.get("timeStamp")
                    
                    if rid not in previous_resources:
                        new_resources.append((rid, curr_item))
                    else:
                        prev_item = previous_resources[rid]
                        prev_value = prev_item.get("value")
                        prev_time = prev_item.get("timeStamp")
                        
                        # Check if value or timestamp changed
                        if curr_value != prev_value or curr_time != prev_time:
                            changed_resources.append((rid, curr_item, prev_item))
            
            # Print summary
            print(f"\n{'='*80}")
            print(f"📊 Sample #{sample_count} @ {timestamp}")
            print(f"{'='*80}")
            
            if changed_resources:
                print(f"\n⚡ CHANGED RESOURCES ({len(changed_resources)}):")
                for rid, curr_item, prev_item in sorted(changed_resources, key=lambda x: x[0]):
                    curr_value = curr_item.get("value")
                    prev_value = prev_item.get("value")
                    formatted = format_resource_value(rid, curr_item)
                    
                    # Highlight important changes
                    if rid in ["13.27.85", "3.51.85", "4.22.700"]:
                        marker = "🔴"
                    elif rid.startswith("3.") or rid.startswith("13.12"):
                        marker = "🟡"
                    else:
                        marker = "⚪"
                    
                    print(f"  {marker} {rid}: {formatted}")
                    if rid == "4.22.700":  # Show full coordinates occasionally
                        try:
                            coords = json.loads(curr_value) if isinstance(curr_value, str) else curr_value
                            active = [c for c in coords if c.get("state") == "1"]
                            print(f"      Raw: {json.dumps(active, indent=2)[:200]}")
                        except:
                            pass
            
            elif new_resources:
                print(f"\n➕ NEW RESOURCES ({len(new_resources)}):")
                for rid, item in sorted(new_resources, key=lambda x: x[0]):
                    formatted = format_resource_value(rid, item)
                    print(f"  {rid}: {formatted}")
            
            else:
                print(f"\n⏸️  No changes detected")
            
            # Print all resources every 10 samples
            if sample_count % 10 == 0:
                print(f"\n📋 ALL RESOURCES ({len(current_resources)}):")
                for rid in sorted(current_resources.keys()):
                    item = current_resources[rid]
                    formatted = format_resource_value(rid, item)
                    label = KNOWN_RESOURCES.get(rid, "")
                    print(f"  {rid:15} → {formatted:50} {label}")
            
            # Update state
            previous_resources = current_resources
            
            # Wait before next sample
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Stopped by user after {sample_count} samples")
        print(f"Final resource count: {len(previous_resources) if previous_resources else 0}")


def main():
    parser = argparse.ArgumentParser(description="FP2 All Endpoints Real-time Monitor")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT_DIR / ".env",
        help="Path to project .env file",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Monitoring interval in seconds (default: 1.0)",
    )
    args = parser.parse_args()
    
    # Load settings
    settings = load_settings(args.env_file)
    
    # Resolve device DID
    print("🔍 Resolving FP2 device...")
    device = probe.resolve_fp2_device(settings)
    print(f"✅ Found: {device.did} ({device.name})")
    
    # Start monitoring
    monitor_resources(settings, device.did, interval=args.interval)


if __name__ == "__main__":
    main()
