#!/usr/bin/env python3
"""
Apply conflict resolutions and low-confidence salvage to manifest v19,
producing the final clean manifest v19_final_v1.

Inputs:
  - conflict_resolutions_v1.json (43 resolutions)
  - low_confidence_salvage_v1.json (4 salvageable)
  - video_teacher_manifest_v19_dual_validated_v1.json

Resolution logic:
  - rule3_boundary: set zone to resolved_zone ("boundary"), add dual_resolution fields
  - rule4_4node_door_ambiguous: set dual_ambiguous=true, add dual_resolution fields
  - rule2_trust_video: set dual_validated=true (video is correct), add dual_resolution fields
  - salvageable low-confidence: update zone and zone_source="csi_auto_salvage"

Match intervals by (session_label, start_sec, end_sec).
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

BASE = "/Users/arsen/Desktop/wifi-densepose"
RESOLUTIONS_PATH = os.path.join(BASE, "output/dual_validation/conflict_resolutions_v1.json")
SALVAGE_PATH = os.path.join(BASE, "output/dual_validation/low_confidence_salvage_v1.json")
MANIFEST_PATH = os.path.join(
    BASE, "output/video_curation/video_teacher_manifest_v19_dual_validated_v1.json"
)
OUTPUT_PATH = os.path.join(
    BASE, "output/video_curation/video_teacher_manifest_v19_final_v1.json"
)


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def main():
    # --- Load inputs ---
    print("Loading conflict resolutions...")
    resolutions_data = load_json(RESOLUTIONS_PATH)
    resolutions = resolutions_data["resolutions"]
    print(f"  {len(resolutions)} resolutions loaded")

    print("Loading low-confidence salvage...")
    salvage_data = load_json(SALVAGE_PATH)
    salvageable = salvage_data["salvageable"]
    print(f"  {len(salvageable)} salvageable intervals loaded")

    print("Loading manifest v19...")
    manifest = load_json(MANIFEST_PATH)
    intervals = manifest["intervals"]
    print(f"  {len(intervals)} intervals loaded")

    # --- Build resolution index: (recording_label, start_sec, end_sec) -> resolution ---
    res_index = {}
    for r in resolutions:
        key = (r["recording_label"], r["start_sec"], r["end_sec"])
        res_index[key] = r

    # --- Build salvage index: (recording_label, start_sec, end_sec) -> salvage entry ---
    salvage_index = {}
    for s in salvageable:
        key = (s["recording_label"], s["start_sec"], s["end_sec"])
        salvage_index[key] = s

    # --- Apply resolutions and salvage ---
    stats = defaultdict(int)
    resolution_applied = defaultdict(int)
    salvage_applied = 0

    for interval in intervals:
        session = interval.get("session_label", "")
        start = interval.get("start_sec", -1)
        end = interval.get("end_sec", -1)
        key = (session, start, end)

        # Check conflict resolutions
        if key in res_index:
            r = res_index[key]
            rule = r["resolution"]

            if rule == "rule3_boundary":
                # Set zone to "boundary", mark as resolved boundary
                interval["zone"] = r["resolved_zone"]  # "boundary"
                interval["dual_resolution"] = "boundary"
                interval["dual_resolution_rule"] = "rule3"
                interval["dual_resolution_reason"] = r["reason"]
                # Clear conflict flag if present
                if "dual_validation_conflict_reason" in interval:
                    interval["dual_resolved_conflict"] = interval.pop(
                        "dual_validation_conflict_reason"
                    )
                resolution_applied["rule3_boundary"] += 1

            elif rule == "rule4_4node_door_ambiguous":
                # Mark as ambiguous, keep original zone
                interval["dual_ambiguous"] = True
                interval["dual_resolution"] = "4node_ambiguous"
                interval["dual_resolution_rule"] = "rule4"
                interval["dual_resolution_reason"] = r["reason"]
                if "dual_validation_conflict_reason" in interval:
                    interval["dual_resolved_conflict"] = interval.pop(
                        "dual_validation_conflict_reason"
                    )
                resolution_applied["rule4_4node_door_ambiguous"] += 1

            elif rule == "rule2_trust_video":
                # Video label is correct, mark as validated
                interval["dual_validated"] = True
                interval["dual_resolution"] = "trust_video"
                interval["dual_resolution_rule"] = "rule2"
                interval["dual_resolution_reason"] = r["reason"]
                # Zone stays as video label (already correct)
                if "dual_validation_conflict_reason" in interval:
                    interval["dual_resolved_conflict"] = interval.pop(
                        "dual_validation_conflict_reason"
                    )
                resolution_applied["rule2_trust_video"] += 1

            else:
                resolution_applied[f"other_{rule}"] += 1

            stats["resolutions_matched"] += 1

        # Check salvage candidates
        if key in salvage_index:
            s = salvage_index[key]
            interval["zone"] = s["assigned_zone"]
            interval["zone_source"] = "csi_auto_salvage"
            interval["zone_confidence"] = s["confidence"]
            interval["zone_confidence_level"] = "salvageable"
            interval["zone_salvage_margin"] = s["margin"]
            salvage_applied += 1
            stats["salvage_matched"] += 1

    # --- Update manifest metadata ---
    manifest["schema_version"] = "v19_final"
    manifest["generated"] = datetime.now(timezone.utc).isoformat()
    manifest["agent"] = "APPLY_RESOLUTIONS_TO_MANIFEST"
    manifest["description"] = (
        f"v19 final: Applied {stats['resolutions_matched']} conflict resolutions "
        f"({resolution_applied.get('rule3_boundary', 0)} boundary, "
        f"{resolution_applied.get('rule4_4node_door_ambiguous', 0)} ambiguous, "
        f"{resolution_applied.get('rule2_trust_video', 0)} trust-video) "
        f"and {salvage_applied} low-confidence salvages to v19 dual-validated manifest."
    )
    manifest["v19_final_delta"] = {
        "resolutions_applied": dict(resolution_applied),
        "salvage_applied": salvage_applied,
        "total_modifications": stats["resolutions_matched"] + stats["salvage_matched"],
    }

    # Recompute stats
    allow_count = sum(1 for i in intervals if i.get("train_allowance") == "allow")
    dual_validated_count = sum(1 for i in intervals if i.get("dual_validated") is True)
    dual_ambiguous_count = sum(1 for i in intervals if i.get("dual_ambiguous") is True)
    boundary_count = sum(
        1 for i in intervals if i.get("dual_resolution") == "boundary"
    )
    trust_video_count = sum(
        1 for i in intervals if i.get("dual_resolution") == "trust_video"
    )

    manifest["stats"]["total_intervals"] = len(intervals)
    manifest["stats"]["v19_final_delta"] = {
        "resolutions_applied": stats["resolutions_matched"],
        "salvage_applied": salvage_applied,
        "dual_validated_intervals": dual_validated_count,
        "dual_ambiguous_intervals": dual_ambiguous_count,
        "dual_boundary_intervals": boundary_count,
        "dual_trust_video_intervals": trust_video_count,
    }

    # --- Write output ---
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    # --- Print summary ---
    print("\n" + "=" * 60)
    print("MANIFEST v19 FINAL - RESOLUTION SUMMARY")
    print("=" * 60)
    print(f"\nTotal intervals:       {len(intervals)}")
    print(f"\nConflict resolutions applied: {stats['resolutions_matched']}/{len(resolutions)}")
    for rule, count in sorted(resolution_applied.items()):
        print(f"  {rule:35s}: {count}")
    print(f"\nLow-confidence salvage applied: {salvage_applied}/{len(salvageable)}")
    print(f"\nPost-resolution stats:")
    print(f"  dual_validated=true:    {dual_validated_count}")
    print(f"  dual_ambiguous=true:    {dual_ambiguous_count}")
    print(f"  dual_resolution=boundary: {boundary_count}")
    print(f"  dual_resolution=trust_video: {trust_video_count}")
    print(f"  train_allowance=allow:  {allow_count}")

    # Unmatched resolutions
    matched_keys = set()
    for interval in intervals:
        key = (interval.get("session_label", ""), interval.get("start_sec", -1), interval.get("end_sec", -1))
        if key in res_index:
            matched_keys.add(key)
    unmatched = len(res_index) - len(matched_keys)
    if unmatched > 0:
        print(f"\n  WARNING: {unmatched} resolutions did not match any manifest interval!")
        for key in res_index:
            if key not in matched_keys:
                print(f"    - {key}")

    # Unmatched salvage
    matched_salvage = set()
    for interval in intervals:
        key = (interval.get("session_label", ""), interval.get("start_sec", -1), interval.get("end_sec", -1))
        if key in salvage_index:
            matched_salvage.add(key)
    unmatched_salvage = len(salvage_index) - len(matched_salvage)
    if unmatched_salvage > 0:
        print(f"\n  WARNING: {unmatched_salvage} salvage entries did not match any manifest interval!")
        for key in salvage_index:
            if key not in matched_salvage:
                print(f"    - {key}")

    print(f"\nOutput written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
