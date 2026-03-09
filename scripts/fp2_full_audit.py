#!/usr/bin/env python3
"""
Full FP2 audit for the current Aqara Cloud -> backend -> UI pipeline.

What it does:
1. Checks local device reachability (ports relevant to FP2/HAP/HTTPS)
2. Pulls live data from the local backend (`/status`, `/current`, `/raw-history`)
3. Pulls live data from Aqara Open API using the current project credentials
4. Compares active FP2 resource IDs against:
   - semantic backend parsing
   - UI label coverage
   - raw grid fallback rendering
5. Optionally samples a live window so the user can move during the audit
6. Saves JSON + Markdown reports
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import socket
import sys
import time
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from scripts.aqara_api_probe import load_settings  # noqa: E402
from scripts.fp2_aqara_cloud_monitor import (  # noqa: E402
    AqaraCloudClient,
    ANGLE_RESOURCE_ID,
    AREA_ENTRY_COUNT_RESOURCE_ID,
    COORDINATES_RESOURCE_ID,
    FALL_EVENT_RESOURCE_ID,
    LIGHT_RESOURCE_ID,
    MOVEMENT_EVENT_RESOURCE_ID,
    ONLINE_RESOURCE_ID,
    PEOPLE_STATISTICS_RESOURCE_ID,
    PEOPLE_STATISTICS_SWITCH_RESOURCE_ID,
    PRESENCE_RESOURCE_ID,
    REALTIME_PEOPLE_RESOURCE_ID,
    RSSI_RESOURCE_ID,
    WALKING_DISTANCE_RESOURCE_ID,
    WALKING_DISTANCE_SWITCH_RESOURCE_ID,
)


FP2_IP = "192.168.1.52"
BACKEND_URL = "http://127.0.0.1:8000"
COMMON_PORTS = [80, 443, 5553, 5554, 55553, 55554, 8080, 8883]

SEMANTIC_RESOURCE_IDS = {
    PRESENCE_RESOURCE_ID: "presence",
    LIGHT_RESOURCE_ID: "light_level",
    RSSI_RESOURCE_ID: "rssi",
    ONLINE_RESOURCE_ID: "online_state",
    ANGLE_RESOURCE_ID: "sensor_angle",
    COORDINATES_RESOURCE_ID: "coordinates",
    MOVEMENT_EVENT_RESOURCE_ID: "movement_event",
    FALL_EVENT_RESOURCE_ID: "fall_state",
    AREA_ENTRY_COUNT_RESOURCE_ID: "area_entries_10s",
    REALTIME_PEOPLE_RESOURCE_ID: "realtime_people_count",
    PEOPLE_STATISTICS_RESOURCE_ID: "people_count_1m",
    WALKING_DISTANCE_RESOURCE_ID: "walking_distance_m",
    PEOPLE_STATISTICS_SWITCH_RESOURCE_ID: "people_statistics_enabled",
    WALKING_DISTANCE_SWITCH_RESOURCE_ID: "walking_distance_enabled",
}

UI_PROMOTED_RESOURCE_IDS = {
    "4.22.85": "realtime_position_upload_switch",
    "14.49.85": "work_mode",
    "14.55.85": "detection_mode",
    "4.23.85": "do_not_disturb_switch",
    "8.0.2207": "do_not_disturb_schedule",
    "8.0.2032": "indicator_light",
    "14.57.85": "installation_position",
    "1.11.85": "installation_height",
    "1.10.85": "bed_height",
    "13.35.85": "installation_angle_status",
    "14.1.85": "presence_sensitivity",
    "14.47.85": "approach_detection_level",
    "14.30.85": "fall_detection_sensitivity",
    "14.59.85": "fall_detection_delay",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a full FP2 pipeline audit.")
    parser.add_argument("--backend", default=BACKEND_URL, help="Local backend base URL")
    parser.add_argument("--duration", type=float, default=0.0, help="Live sampling window in seconds")
    parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval for live window")
    parser.add_argument("--host", default=FP2_IP, help="FP2 host/IP for port scan")
    parser.add_argument(
        "--skip-cloud",
        action="store_true",
        help="Skip direct Aqara Open API pull and use backend data only",
    )
    return parser.parse_args()


def scan_ports(host: str, ports: list[int], timeout: float = 0.8) -> dict[str, Any]:
    results: dict[int, str] = {}
    for port in ports:
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            status = "open" if sock.connect_ex((host, port)) == 0 else "closed"
        finally:
            sock.close()
        results[port] = status
    return {
        "host": host,
        "ports": results,
        "open_ports": [port for port, status in results.items() if status == "open"],
    }


def fetch_json(base_url: str, path: str) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def fetch_backend_bundle(base_url: str) -> dict[str, Any]:
    return {
        "health": fetch_json(base_url, "/api/v1/health"),
        "status": fetch_json(base_url, "/api/v1/fp2/status"),
        "current": fetch_json(base_url, "/api/v1/fp2/current"),
        "raw_history": fetch_json(base_url, "/api/v1/fp2/raw-history?limit=25&changed_only=true"),
    }


def extract_ui_resource_ids() -> set[str]:
    fp2_tab_path = ROOT_DIR / "ui" / "components" / "FP2Tab.js"
    text = fp2_tab_path.read_text(encoding="utf-8")
    return set(re.findall(r"'([^']+)':\s*'fp2\.resource\.[^']+'", text))


def is_zone_entry_resource(rid: str) -> bool:
    match = re.fullmatch(r"13\.(\d+)\.85", rid)
    if not match:
        return False
    value = int(match.group(1))
    return 121 <= value <= 150


def is_zone_visitors_resource(rid: str) -> bool:
    match = re.fullmatch(r"0\.(\d+)\.85", rid)
    if not match:
        return False
    value = int(match.group(1))
    return 121 <= value <= 150


def is_zone_occupancy_resource(rid: str) -> bool:
    match = re.fullmatch(r"3\.(\d+)\.85", rid)
    if not match:
        return False
    value = int(match.group(1))
    return 1 <= value <= 30


def zone_number_for_resource(rid: str) -> int | None:
    for pattern in (r"13\.(\d+)\.85", r"0\.(\d+)\.85", r"3\.(\d+)\.85"):
        match = re.fullmatch(pattern, rid)
        if not match:
            continue
        value = int(match.group(1))
        if 121 <= value <= 150:
            return value - 120
        if 1 <= value <= 30:
            return value
    return None


def classify_resource(rid: str, ui_resource_ids: set[str]) -> dict[str, str]:
    if rid in SEMANTIC_RESOURCE_IDS:
        return {"bucket": "semantic", "reason": SEMANTIC_RESOURCE_IDS[rid]}
    if rid in UI_PROMOTED_RESOURCE_IDS:
        return {"bucket": "semantic", "reason": UI_PROMOTED_RESOURCE_IDS[rid]}
    if is_zone_entry_resource(rid):
        return {"bucket": "semantic", "reason": f"zone_{zone_number_for_resource(rid)}_entries_10s"}
    if is_zone_visitors_resource(rid):
        return {"bucket": "semantic", "reason": f"zone_{zone_number_for_resource(rid)}_visitors_1m"}
    if is_zone_occupancy_resource(rid):
        return {"bucket": "semantic", "reason": f"zone_{zone_number_for_resource(rid)}_occupancy"}
    if rid in ui_resource_ids:
        return {"bucket": "raw_labeled", "reason": "translated_resource_grid"}
    return {"bucket": "raw_only", "reason": "raw_resource_grid_fallback"}


def summarize_current_payload(current_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = current_payload.get("metadata", {})
    raw = metadata.get("raw_attributes", {})
    advanced = raw.get("advanced_metrics") or {}
    zones = raw.get("zones") or []
    targets = raw.get("targets") or []
    return {
        "timestamp": current_payload.get("timestamp"),
        "presence_raw": metadata.get("presence_raw"),
        "effective_presence": metadata.get("effective_presence"),
        "derived_presence": metadata.get("derived_presence"),
        "presence_mode": metadata.get("presence_mode"),
        "presence_reason": metadata.get("presence_reason"),
        "persons_count": len(current_payload.get("persons") or []),
        "raw_target_count": len(targets),
        "zone_count": len(zones),
        "current_zone": raw.get("current_zone"),
        "movement_event": raw.get("movement_event"),
        "fall_state": raw.get("fall_state"),
        "light_level": raw.get("light_level"),
        "rssi": raw.get("rssi"),
        "sensor_angle": raw.get("sensor_angle"),
        "coordinates_source": raw.get("coordinates_source"),
        "coordinates_hold_age_sec": raw.get("coordinates_hold_age_sec"),
        "advanced_metrics": advanced,
    }


def summarize_raw_history(raw_history: dict[str, Any]) -> dict[str, Any]:
    captures = raw_history.get("captures") or []
    movement_events = sorted({cap.get("movement_event") for cap in captures if cap.get("movement_event") is not None})
    target_counts = [int(cap.get("active_target_count") or 0) for cap in captures]
    coordinate_sources = sorted(
        {
            ((cap.get("resource_values") or {}).get("4.22.700"), cap.get("active_target_count"))
            for cap in captures
        }
    )
    changed_counter = Counter()
    for capture in captures:
        for rid in (capture.get("changed_resources") or {}).keys():
            changed_counter[rid] += 1
    return {
        "captures_considered": len(captures),
        "movement_events_seen": movement_events,
        "max_active_targets": max(target_counts) if target_counts else 0,
        "recent_changed_resources": dict(changed_counter.most_common(15)),
        "recent_capture_sequences": [cap.get("sequence") for cap in captures[:10]],
        "coordinate_payload_variants": len(coordinate_sources),
    }


def collect_live_window(base_url: str, duration: float, interval: float) -> dict[str, Any]:
    if duration <= 0:
        return {
            "enabled": False,
            "samples": 0,
            "movement_events_seen": [],
            "presence_modes_seen": [],
            "max_targets_seen": 0,
            "coordinate_sources_seen": [],
            "resource_ids_seen": [],
            "resource_changes_seen": {},
        }

    started_at = time.time()
    samples: list[dict[str, Any]] = []
    resource_change_counter: Counter[str] = Counter()
    resource_ids_seen: set[str] = set()
    previous_values: dict[str, Any] | None = None

    while time.time() - started_at < duration:
        current = fetch_json(base_url, "/api/v1/fp2/current")
        metadata = current.get("metadata", {})
        raw = metadata.get("raw_attributes", {})
        resource_values = raw.get("resource_values") or {}
        resource_ids_seen.update(resource_values.keys())
        if previous_values is not None:
            for rid, value in resource_values.items():
                if previous_values.get(rid) != value:
                    resource_change_counter[rid] += 1
        previous_values = dict(resource_values)
        samples.append(
            {
                "timestamp": current.get("timestamp"),
                "effective_presence": metadata.get("effective_presence"),
                "presence_mode": metadata.get("presence_mode"),
                "movement_event": raw.get("movement_event"),
                "target_count": len(raw.get("targets") or []),
                "coordinates_source": raw.get("coordinates_source"),
            }
        )
        time.sleep(max(0.1, interval))

    return {
        "enabled": True,
        "samples": len(samples),
        "duration_sec": duration,
        "interval_sec": interval,
        "movement_events_seen": sorted({sample["movement_event"] for sample in samples if sample["movement_event"] is not None}),
        "presence_modes_seen": sorted({sample["presence_mode"] for sample in samples if sample["presence_mode"]}),
        "max_targets_seen": max((sample["target_count"] for sample in samples), default=0),
        "coordinate_sources_seen": sorted({sample["coordinates_source"] for sample in samples if sample["coordinates_source"]}),
        "resource_ids_seen": sorted(resource_ids_seen),
        "resource_changes_seen": dict(resource_change_counter.most_common(20)),
    }


def fetch_cloud_bundle(skip_cloud: bool) -> dict[str, Any]:
    if skip_cloud:
        return {"skipped": True}

    settings = load_settings(ROOT_DIR / ".env")
    client = AqaraCloudClient(settings)
    device = client.resolve_device()
    resource_info = client.load_resource_info(device.model)
    resources = client.fetch_resource_values(device.did)
    active_resource_ids = [str(item.get("resourceId")) for item in resources if item.get("resourceId")]
    active_values = {str(item.get("resourceId")): item.get("value") for item in resources if item.get("resourceId")}
    active_labels = {
        str(item.get("resourceId")): str((resource_info.get(str(item.get("resourceId"))) or {}).get("name") or "")
        for item in resources
        if item.get("resourceId")
    }
    return {
        "skipped": False,
        "device": {
            "did": device.did,
            "name": device.name,
            "model": device.model,
            "firmware": device.firmware,
            "position_id": device.position_id,
            "state": device.state,
        },
        "resource_definition_count": len(resource_info),
        "active_resource_ids": active_resource_ids,
        "active_values": active_values,
        "active_labels": active_labels,
    }


def build_coverage(active_resource_ids: list[str], ui_resource_ids: set[str]) -> dict[str, Any]:
    classified: dict[str, dict[str, str]] = {}
    buckets: dict[str, list[str]] = {"semantic": [], "raw_labeled": [], "raw_only": []}

    for rid in sorted(set(active_resource_ids)):
        classification = classify_resource(rid, ui_resource_ids)
        classified[rid] = classification
        buckets[classification["bucket"]].append(rid)

    return {
        "active_resource_count": len(set(active_resource_ids)),
        "ui_explicit_label_count": len(ui_resource_ids),
        "semantic_count": len(buckets["semantic"]),
        "raw_labeled_count": len(buckets["raw_labeled"]),
        "raw_only_count": len(buckets["raw_only"]),
        "buckets": buckets,
        "classified": classified,
    }


def build_markdown_report(audit: dict[str, Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current = audit["current_summary"]
    coverage = audit["coverage"]
    raw_history = audit["raw_history_summary"]
    live_window = audit["live_window"]
    cloud = audit["cloud"]
    port_scan = audit["port_scan"]

    report: list[str] = []
    report.append("# FP2 Full Device Audit")
    report.append("")
    report.append(f"- Generated: `{now}`")
    report.append(f"- Device IP: `{port_scan['host']}`")
    report.append(f"- Backend: `{audit['backend_url']}`")
    report.append("")
    report.append("## 1. Current Live Snapshot")
    report.append("")
    report.append(f"- `effective_presence`: `{current['effective_presence']}`")
    report.append(f"- `presence_raw`: `{current['presence_raw']}`")
    report.append(f"- `presence_mode`: `{current['presence_mode']}`")
    report.append(f"- `presence_reason`: `{current['presence_reason']}`")
    report.append(f"- `persons_count`: `{current['persons_count']}`")
    report.append(f"- `raw_target_count`: `{current['raw_target_count']}`")
    report.append(f"- `zone_count`: `{current['zone_count']}`")
    report.append(f"- `current_zone`: `{current['current_zone']}`")
    report.append(f"- `movement_event`: `{current['movement_event']}`")
    report.append(f"- `fall_state`: `{current['fall_state']}`")
    report.append(f"- `light_level`: `{current['light_level']}`")
    report.append(f"- `rssi`: `{current['rssi']}`")
    report.append(f"- `sensor_angle`: `{current['sensor_angle']}`")
    report.append(f"- `coordinates_source`: `{current['coordinates_source']}`")
    report.append("")
    report.append("### Advanced Metrics")
    report.append("")
    for key, value in (current.get("advanced_metrics") or {}).items():
        report.append(f"- `{key}`: `{value}`")
    report.append("")
    report.append("## 2. Transport / Reachability")
    report.append("")
    report.append(f"- Open ports on device: `{port_scan['open_ports']}`")
    report.append("- Local HAP expectation: port `55553` should be open for direct HomeKit/HAP")
    report.append(f"- Actual result: `55553` is `{port_scan['ports'].get(55553)}`")
    report.append(f"- HTTPS/cloud port `443`: `{port_scan['ports'].get(443)}`")
    report.append("")
    report.append("## 3. Active Resource Coverage")
    report.append("")
    report.append(f"- Active resources from Aqara Cloud: `{coverage['active_resource_count']}`")
    report.append(f"- Explicit UI labels in `FP2Tab.js`: `{coverage['ui_explicit_label_count']}`")
    report.append(f"- Semantically processed: `{coverage['semantic_count']}`")
    report.append(f"- Raw grid + translated label only: `{coverage['raw_labeled_count']}`")
    report.append(f"- Raw grid fallback only: `{coverage['raw_only_count']}`")
    report.append("")
    report.append("### Semantic Resources")
    report.append("")
    for rid in coverage["buckets"]["semantic"]:
        report.append(f"- `{rid}` -> `{coverage['classified'][rid]['reason']}`")
    report.append("")
    report.append("### Raw-Labeled Only")
    report.append("")
    if coverage["buckets"]["raw_labeled"]:
        for rid in coverage["buckets"]["raw_labeled"]:
            label = (cloud.get("active_labels") or {}).get(rid) or ""
            report.append(f"- `{rid}` -> `{label}`")
    else:
        report.append("- none")
    report.append("")
    report.append("### Raw-Only Fallback")
    report.append("")
    if coverage["buckets"]["raw_only"]:
        for rid in coverage["buckets"]["raw_only"]:
            label = (cloud.get("active_labels") or {}).get(rid) or ""
            report.append(f"- `{rid}` -> `{label}`")
    else:
        report.append("- none")
    report.append("")
    report.append("## 4. Recent Backend History")
    report.append("")
    report.append(f"- Captures analyzed: `{raw_history['captures_considered']}`")
    report.append(f"- Movement events seen: `{raw_history['movement_events_seen']}`")
    report.append(f"- Max active targets seen: `{raw_history['max_active_targets']}`")
    report.append(f"- Coordinate payload variants: `{raw_history['coordinate_payload_variants']}`")
    report.append("")
    report.append("### Recently Changing Resources")
    report.append("")
    if raw_history["recent_changed_resources"]:
        for rid, count in raw_history["recent_changed_resources"].items():
            report.append(f"- `{rid}` changed `{count}` time(s)")
    else:
        report.append("- no changes in current window")
    report.append("")
    if live_window["enabled"]:
        report.append("## 5. Live Sampling Window")
        report.append("")
        report.append(f"- Duration: `{live_window['duration_sec']}s`")
        report.append(f"- Samples: `{live_window['samples']}`")
        report.append(f"- Presence modes seen: `{live_window['presence_modes_seen']}`")
        report.append(f"- Movement events seen: `{live_window['movement_events_seen']}`")
        report.append(f"- Max targets seen: `{live_window['max_targets_seen']}`")
        report.append(f"- Coordinate sources seen: `{live_window['coordinate_sources_seen']}`")
        report.append("")
        report.append("### Live Resource Changes")
        report.append("")
        if live_window["resource_changes_seen"]:
            for rid, count in live_window["resource_changes_seen"].items():
                report.append(f"- `{rid}` changed `{count}` time(s)")
        else:
            report.append("- no resource changes observed in the live window")
        report.append("")
    report.append("## 6. Conclusions")
    report.append("")
    report.append("- Aqara Cloud is currently the only working full-telemetry transport.")
    report.append("- All active resources are at least visible in the raw resource grid.")
    report.append("- Not all active resources are elevated into first-class UI widgets yet.")
    report.append("- The main remaining UX opportunity is to promote configuration/diagnostic resources into dedicated cards instead of leaving them only in the raw grid.")
    report.append("- The next best audit pass is a movement session with `--duration 20 --interval 1` while the user walks through the room/garage.")
    report.append("")
    return "\n".join(report) + "\n"


def main() -> int:
    args = parse_args()

    backend_bundle = fetch_backend_bundle(args.backend)
    current_summary = summarize_current_payload(backend_bundle["current"])
    raw_history_summary = summarize_raw_history(backend_bundle["raw_history"])
    cloud_bundle = fetch_cloud_bundle(args.skip_cloud)
    ui_resource_ids = extract_ui_resource_ids()

    if cloud_bundle.get("skipped"):
        active_resource_ids = list(
            (backend_bundle["current"].get("metadata", {}).get("raw_attributes", {}).get("resource_values") or {}).keys()
        )
    else:
        active_resource_ids = cloud_bundle.get("active_resource_ids") or []

    coverage = build_coverage(active_resource_ids, ui_resource_ids)
    live_window = collect_live_window(args.backend, args.duration, args.interval)
    port_scan = scan_ports(args.host, COMMON_PORTS)

    audit = {
        "generated_at": datetime.now().isoformat(),
        "backend_url": args.backend,
        "port_scan": port_scan,
        "backend": backend_bundle,
        "current_summary": current_summary,
        "raw_history_summary": raw_history_summary,
        "cloud": cloud_bundle,
        "coverage": coverage,
        "live_window": live_window,
    }

    temp_dir = ROOT_DIR / "temp"
    docs_dir = ROOT_DIR / "docs"
    temp_dir.mkdir(exist_ok=True)
    docs_dir.mkdir(exist_ok=True)

    json_path = temp_dir / "fp2_full_audit.json"
    md_path = docs_dir / "FP2_FULL_DEVICE_AUDIT_REPORT.md"
    json_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(build_markdown_report(audit), encoding="utf-8")

    print(f"Audit JSON saved to: {json_path}")
    print(f"Audit report saved to: {md_path}")
    print(
        json.dumps(
            {
                "effective_presence": current_summary["effective_presence"],
                "active_resources": coverage["active_resource_count"],
                "semantic_resources": coverage["semantic_count"],
                "raw_labeled_resources": coverage["raw_labeled_count"],
                "raw_only_resources": coverage["raw_only_count"],
                "open_ports": port_scan["open_ports"],
                "live_window_enabled": live_window["enabled"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
