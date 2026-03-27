#!/usr/bin/env python3
"""
Prepare zone-aware training manifest from v19 dual-validated intervals.

Filters manifest v19 to only dual_validated=true + train_allowance=allow,
groups by zone and video_truth_class, normalises zone names into canonical
buckets (door / center / deep / transition / other), and writes a training
manifest enriched with zone metadata for zone-aware feature engineering.

Output:
  output/train_runs/v19_zone_aware/training_manifest_v19.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT / "output" / "video_curation" / "video_teacher_manifest_v19_dual_validated_v1.json"
OUTPUT_DIR = PROJECT / "output" / "train_runs" / "v19_zone_aware"
OUTPUT_MANIFEST = OUTPUT_DIR / "training_manifest_v19.json"

# ── Canonical zone mapping ────────────────────────────────────────
# Many raw zone labels are fine-grained crossing descriptions.
# We collapse them into 4 training-relevant canonical zones.
ZONE_CANONICAL_MAP: dict[str, str] = {
    "door": "door",
    "center": "center",
    "center_near_camera": "center",
    "center_right": "center",
    "center_crossing": "transition",
    "center_to_center_right": "transition",
    "center_to_far": "transition",
    "center_to_left": "transition",
    "center_to_right": "transition",
    "center_to_right_to_left": "transition",
    "left_center_right": "transition",
    "transition": "transition",
    "mixed": "transition",
    "garage": "center",        # full-garage = center fallback
    "s7_garage": "center",     # s7 session = center fallback
}

# Allowed activity classes for binary model training
ALLOWED_CLASSES = {"EMPTY", "STATIC", "MOTION"}


def canonical_zone(raw_zone: str) -> str:
    """Map raw zone name to canonical zone bucket."""
    return ZONE_CANONICAL_MAP.get(raw_zone, "other")


def main() -> None:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    intervals = manifest.get("intervals", [])
    print(f"Loaded manifest v19: {len(intervals)} total intervals")

    # ── Step 1: Filter to dual_validated=true AND train_allowance=allow ──
    eligible = [
        iv for iv in intervals
        if iv.get("dual_validated") is True
        and iv.get("train_allowance") == "allow"
    ]
    print(f"After filter (dual_validated=true + allow): {len(eligible)} intervals")

    # ── Step 2: Filter to allowed training classes ──
    training = [iv for iv in eligible if iv.get("video_truth_class") in ALLOWED_CLASSES]
    dropped_class = len(eligible) - len(training)
    if dropped_class:
        dropped_classes = Counter(
            iv.get("video_truth_class") for iv in eligible
            if iv.get("video_truth_class") not in ALLOWED_CLASSES
        )
        print(f"Dropped {dropped_class} intervals with non-training classes: {dict(dropped_classes)}")
    print(f"Training-eligible intervals: {len(training)}")

    # ── Step 3: Enrich with canonical zone ──
    for iv in training:
        iv["zone_canonical"] = canonical_zone(iv.get("zone", "other"))

    # ── Step 4: Distribution analysis ──
    print("\n" + "=" * 70)
    print("DISTRIBUTION: intervals per class per canonical zone")
    print("=" * 70)

    # Count: zone x class
    zone_class_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    zone_class_secs: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for iv in training:
        z = iv["zone_canonical"]
        c = iv["video_truth_class"]
        zone_class_count[z][c] += 1
        zone_class_secs[z][c] += iv.get("duration_sec", 0.0)

    all_zones = sorted(zone_class_count.keys())
    all_classes = sorted(ALLOWED_CLASSES)

    # Table header
    header = f"{'Zone':<14}" + "".join(f"{'#' + c:<14}" for c in all_classes) + f"{'Total':<10}"
    print(header)
    print("-" * len(header))

    total_intervals = 0
    for z in all_zones:
        row = f"{z:<14}"
        z_total = 0
        for c in all_classes:
            n = zone_class_count[z][c]
            row += f"{n:<14}"
            z_total += n
        row += f"{z_total:<10}"
        total_intervals += z_total
        print(row)

    print("-" * len(header))
    # Totals row
    row = f"{'TOTAL':<14}"
    for c in all_classes:
        col_total = sum(zone_class_count[z][c] for z in all_zones)
        row += f"{col_total:<14}"
    row += f"{total_intervals:<10}"
    print(row)

    # Duration table
    print(f"\n{'=' * 70}")
    print("DURATION (seconds) per class per canonical zone")
    print("=" * 70)

    header_s = f"{'Zone':<14}" + "".join(f"{c + ' (s)':<14}" for c in all_classes) + f"{'Total (s)':<12}"
    print(header_s)
    print("-" * len(header_s))

    total_seconds = 0.0
    for z in all_zones:
        row = f"{z:<14}"
        z_total_s = 0.0
        for c in all_classes:
            s = zone_class_secs[z][c]
            row += f"{s:<14.1f}"
            z_total_s += s
        row += f"{z_total_s:<12.1f}"
        total_seconds += z_total_s
        print(row)

    print("-" * len(header_s))
    row = f"{'TOTAL':<14}"
    for c in all_classes:
        col_total_s = sum(zone_class_secs[z][c] for z in all_zones)
        row += f"{col_total_s:<14.1f}"
    row += f"{total_seconds:<12.1f}"
    print(row)

    # ── Step 5: Raw zone breakdown ──
    print(f"\n{'=' * 70}")
    print("RAW zone label breakdown (before canonical mapping)")
    print("=" * 70)
    raw_zone_counts = Counter(iv.get("zone", "?") for iv in training)
    for rz, cnt in raw_zone_counts.most_common():
        canonical = canonical_zone(rz)
        print(f"  {rz:<30} -> {canonical:<12}  ({cnt} intervals)")

    # ── Step 6: Zone confidence stats ──
    print(f"\n{'=' * 70}")
    print("Zone confidence distribution")
    print("=" * 70)
    confs = [iv.get("zone_confidence", 0) for iv in training if iv.get("zone_confidence") is not None]
    if confs:
        import statistics
        print(f"  min:    {min(confs):.4f}")
        print(f"  median: {statistics.median(confs):.4f}")
        print(f"  mean:   {statistics.mean(confs):.4f}")
        print(f"  max:    {max(confs):.4f}")
        high = sum(1 for c in confs if c >= 0.5)
        print(f"  >=0.5 confidence: {high}/{len(confs)} ({100*high/len(confs):.1f}%)")

    # ── Step 7: Per-session coverage ──
    sessions = Counter(iv["session_label"] for iv in training)
    print(f"\n{'=' * 70}")
    print(f"Unique sessions contributing: {len(sessions)}")
    print(f"Top 10 sessions by interval count:")
    for s, cnt in sessions.most_common(10):
        dur = sum(iv["duration_sec"] for iv in training if iv["session_label"] == s)
        print(f"  {s:<55} {cnt:>3} intervals  {dur:>7.1f}s")

    # ── Step 8: Write training manifest ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_manifest = {
        "schema_version": "v19_zone_aware_training",
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(MANIFEST_PATH.name),
        "filter_criteria": {
            "dual_validated": True,
            "train_allowance": "allow",
            "allowed_classes": sorted(ALLOWED_CLASSES),
        },
        "canonical_zone_map": ZONE_CANONICAL_MAP,
        "stats": {
            "total_intervals": len(training),
            "total_duration_sec": round(total_seconds, 2),
            "by_class": {
                c: sum(zone_class_count[z][c] for z in all_zones)
                for c in all_classes
            },
            "by_class_seconds": {
                c: round(sum(zone_class_secs[z][c] for z in all_zones), 2)
                for c in all_classes
            },
            "by_zone": {
                z: sum(zone_class_count[z][c] for c in all_classes)
                for z in all_zones
            },
            "by_zone_seconds": {
                z: round(sum(zone_class_secs[z][c] for c in all_classes), 2)
                for z in all_zones
            },
            "by_zone_class": {
                z: {c: zone_class_count[z][c] for c in all_classes if zone_class_count[z][c] > 0}
                for z in all_zones
            },
            "unique_sessions": len(sessions),
        },
        "intervals": training,
    }

    with open(OUTPUT_MANIFEST, "w") as f:
        json.dump(output_manifest, f, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"WRITTEN: {OUTPUT_MANIFEST}")
    print(f"  {len(training)} intervals, {total_seconds:.1f}s total validated training data")
    print(f"  Ready for zone-aware retraining pipeline")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
