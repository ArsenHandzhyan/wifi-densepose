#!/usr/bin/env python3
"""
Analyze low-confidence auto-zone assignments and identify salvageable ones.

Loads auto_zone_assignments_v1.json, filters low-confidence entries,
applies relaxed promotion rules (margin > 0.15), and outputs salvageable
assignments plus summary stats.
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone

INPUT_PATH = Path(__file__).resolve().parents[2] / "output" / "dual_validation" / "auto_zone_assignments_v1.json"
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "output" / "dual_validation" / "low_confidence_salvage_v1.json"

MARGIN_THRESHOLD = 0.15  # promote if margin > this even with low absolute similarity


def load_assignments(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return [a for a in data["assignments"] if a.get("skip_reason") is None]


def filter_low_confidence(assignments: list[dict]) -> list[dict]:
    return [a for a in assignments if a.get("confidence_level") == "low"]


def compute_stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
        "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
    }


def analyze_and_salvage(low: list[dict]) -> dict:
    # --- Zone distribution ---
    zone_counts = Counter(a["assigned_zone"] for a in low)
    zone_stats = {}
    for zone in sorted(zone_counts.keys()):
        subset = [a for a in low if a["assigned_zone"] == zone]
        zone_stats[zone] = {
            "count": len(subset),
            "similarity": compute_stats([a["confidence"] for a in subset]),
            "margin": compute_stats([a["margin"] for a in subset]),
        }

    # --- Session distribution ---
    session_counts = Counter(a["recording_label"] for a in low)
    session_stats = {s: c for s, c in session_counts.most_common()}

    # --- Overall distributions ---
    all_sims = [a["confidence"] for a in low]
    all_margins = [a["margin"] for a in low]

    # --- Margin buckets ---
    buckets = [(0.0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30), (0.30, 1.0)]
    margin_histogram = {}
    for lo_b, hi_b in buckets:
        key = f"[{lo_b:.2f}, {hi_b:.2f})"
        margin_histogram[key] = len([a for a in low if lo_b <= a["margin"] < hi_b])

    # --- Salvageable: margin > threshold ---
    salvageable = sorted(
        [a for a in low if a["margin"] > MARGIN_THRESHOLD],
        key=lambda x: -x["margin"],
    )
    not_salvageable = [a for a in low if a["margin"] <= MARGIN_THRESHOLD]

    # --- Borderline: margin in [0.10, 0.15] (near-miss) ---
    borderline = sorted(
        [a for a in low if 0.10 <= a["margin"] <= MARGIN_THRESHOLD],
        key=lambda x: -x["margin"],
    )

    salvageable_zone_counts = Counter(a["assigned_zone"] for a in salvageable)

    summary = {
        "total_low_confidence": len(low),
        "salvageable_count": len(salvageable),
        "not_salvageable_count": len(not_salvageable),
        "borderline_count": len(borderline),
        "margin_threshold": MARGIN_THRESHOLD,
        "salvage_rate": round(len(salvageable) / len(low), 4) if low else 0,
        "similarity_distribution": compute_stats(all_sims),
        "margin_distribution": compute_stats(all_margins),
        "margin_histogram": margin_histogram,
        "per_zone": zone_stats,
        "per_session": session_stats,
        "salvageable_by_zone": dict(salvageable_zone_counts.most_common()),
    }

    return {
        "schema": "low_confidence_salvage_v1",
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": str(INPUT_PATH),
        "summary": summary,
        "salvageable": salvageable,
        "borderline_near_miss": borderline,
    }


def print_report(result: dict) -> None:
    s = result["summary"]
    print("=" * 70)
    print("LOW-CONFIDENCE AUTO-ZONE ANALYSIS")
    print("=" * 70)
    print()
    print(f"Total low-confidence assignments: {s['total_low_confidence']}")
    print(f"Margin threshold for salvage:     {s['margin_threshold']}")
    print(f"Salvageable (margin > threshold): {s['salvageable_count']} ({s['salvage_rate']*100:.1f}%)")
    print(f"Borderline [0.10, 0.15]:          {s['borderline_count']}")
    print(f"Not salvageable:                  {s['not_salvageable_count']}")
    print()

    print("--- Similarity distribution ---")
    sd = s["similarity_distribution"]
    print(f"  min={sd['min']}, max={sd['max']}, mean={sd['mean']}, median={sd['median']}, stdev={sd['stdev']}")
    print()

    print("--- Margin distribution ---")
    md = s["margin_distribution"]
    print(f"  min={md['min']}, max={md['max']}, mean={md['mean']}, median={md['median']}, stdev={md['stdev']}")
    print()

    print("--- Margin histogram ---")
    for bucket, count in s["margin_histogram"].items():
        bar = "#" * count
        print(f"  {bucket}: {count:3d} {bar}")
    print()

    print("--- Per-zone breakdown ---")
    for zone, zs in s["per_zone"].items():
        print(f"  {zone}: {zs['count']} assignments")
        print(f"    similarity: mean={zs['similarity']['mean']}, stdev={zs['similarity']['stdev']}")
        print(f"    margin:     mean={zs['margin']['mean']}, stdev={zs['margin']['stdev']}")
    print()

    print("--- Per-session breakdown ---")
    for sess, count in s["per_session"].items():
        print(f"  {sess}: {count}")
    print()

    print("--- Salvageable assignments (margin > 0.15) ---")
    if result["salvageable"]:
        for a in result["salvageable"]:
            print(
                f"  {a['recording_label']} [{a['start_sec']:.0f}-{a['end_sec']:.0f}s] "
                f"-> {a['assigned_zone']}, sim={a['confidence']:.4f}, margin={a['margin']:.4f}, "
                f"n_win={a['n_csi_windows']}"
            )
    else:
        print("  (none)")
    print()

    print("--- Borderline near-miss (margin 0.10-0.15) ---")
    if result["borderline_near_miss"]:
        for a in result["borderline_near_miss"]:
            print(
                f"  {a['recording_label']} [{a['start_sec']:.0f}-{a['end_sec']:.0f}s] "
                f"-> {a['assigned_zone']}, sim={a['confidence']:.4f}, margin={a['margin']:.4f}, "
                f"n_win={a['n_csi_windows']}"
            )
    else:
        print("  (none)")
    print()


def main():
    if not INPUT_PATH.exists():
        print(f"ERROR: Input not found: {INPUT_PATH}", file=sys.stderr)
        sys.exit(1)

    assignments = load_assignments(INPUT_PATH)
    low = filter_low_confidence(assignments)
    print(f"Loaded {len(assignments)} assigned intervals, {len(low)} low-confidence")

    result = analyze_and_salvage(low)
    print_report(result)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved salvage results to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
