#!/usr/bin/env python3
"""
Automatic conflict resolution for dual-validation pipeline.

Rules:
  1. CSI similarity > 0.5 AND zone_source == "csi_auto" => trust CSI over auto-zone
  2. CSI similarity < 0.1 (very weak match) => trust video label
  3. Adjacent zones (center<->transition, transition<->door) => mark as "boundary"
  4. 4-node session + conflict involves door_passage_inside => downgrade to "ambiguous"

Loads:
  - mass_conflicts_v1.json (43 conflicts)
  - mass_validation_results_v1.json (for node_mode lookup)
  - video_teacher_manifest_v19_dual_validated_v1.json (for zone_source lookup)

Outputs:
  - conflict_resolutions_v1.json
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

BASE = "/Users/arsen/Desktop/wifi-densepose"
CONFLICTS_PATH = os.path.join(BASE, "output/dual_validation/mass_conflicts_v1.json")
RESULTS_PATH = os.path.join(BASE, "output/dual_validation/mass_validation_results_v1.json")
MANIFEST_PATH = os.path.join(
    BASE, "output/video_curation/video_teacher_manifest_v19_dual_validated_v1.json"
)
OUTPUT_PATH = os.path.join(BASE, "output/dual_validation/conflict_resolutions_v1.json")

# Adjacent zone pairs (undirected)
ADJACENT_PAIRS = {
    frozenset({"center", "transition"}),
    frozenset({"transition", "door_passage_inside"}),
}


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def build_node_mode_index(results: list[dict]) -> dict[str, str]:
    """Map conflict id -> node_mode from validation results."""
    return {r["id"]: r.get("node_mode", "unknown") for r in results}


def build_zone_source_index(manifest: dict) -> dict[tuple, str]:
    """Map (session_label, start_sec) -> zone_source from manifest intervals."""
    index = {}
    for entry in manifest.get("intervals", []):
        # Manifest uses "session_label"; conflicts use "recording_label" (same value)
        key = (entry.get("session_label", ""), entry.get("start_sec", -1))
        index[key] = entry.get("zone_source", "video")
    return index


def are_adjacent(zone_a: str, zone_b: str) -> bool:
    return frozenset({zone_a, zone_b}) in ADJACENT_PAIRS


def apply_rules(
    conflicts: list[dict],
    node_mode_index: dict[str, str],
    zone_source_index: dict[tuple, str],
) -> list[dict]:
    """Apply resolution rules in priority order. Returns list of resolved conflicts."""

    rule_counts = defaultdict(int)
    resolutions = []

    for c in conflicts:
        cid = c["id"]
        video_zone = c["video_label"]
        csi_zone = c["csi_closest_zone"]
        csi_sim = c["csi_similarity"]
        csi_sim_to_video = c.get("csi_similarity_to_video_zone", None)
        node_mode = node_mode_index.get(cid, "unknown")
        zone_source = zone_source_index.get(
            (c["recording_label"], c["start_sec"]), "video"
        )

        resolution = {
            "id": cid,
            "recording_label": c["recording_label"],
            "start_sec": c["start_sec"],
            "end_sec": c["end_sec"],
            "video_label": video_zone,
            "csi_closest_zone": csi_zone,
            "csi_similarity": csi_sim,
            "csi_similarity_to_video_zone": csi_sim_to_video,
            "node_mode": node_mode,
            "zone_source": zone_source,
            "train_allowance": c.get("train_allowance", "exclude"),
        }

        # --- Rule 1: High-confidence CSI overrides auto-assigned zone ---
        if csi_sim > 0.5 and zone_source == "csi_auto":
            resolution["resolved_zone"] = csi_zone
            resolution["resolution"] = "rule1_csi_override"
            resolution["reason"] = (
                f"CSI similarity {csi_sim:.3f} > 0.5 and zone was auto-assigned; "
                f"trusting CSI zone '{csi_zone}' over auto-zone '{video_zone}'"
            )
            rule_counts["rule1_csi_override"] += 1
            resolutions.append(resolution)
            continue

        # --- Rule 2: Very weak CSI match => trust video ---
        if csi_sim < 0.1:
            resolution["resolved_zone"] = video_zone
            resolution["resolution"] = "rule2_trust_video"
            resolution["reason"] = (
                f"CSI similarity {csi_sim:.3f} < 0.1 (very weak); "
                f"trusting video label '{video_zone}'"
            )
            rule_counts["rule2_trust_video"] += 1
            resolutions.append(resolution)
            continue

        # --- Rule 3: Adjacent zones => boundary ---
        if are_adjacent(video_zone, csi_zone):
            resolution["resolved_zone"] = "boundary"
            resolution["resolution"] = "rule3_boundary"
            resolution["reason"] = (
                f"'{video_zone}' and '{csi_zone}' are adjacent zones; "
                f"marking as boundary (ambiguous edge region)"
            )
            rule_counts["rule3_boundary"] += 1
            resolutions.append(resolution)
            continue

        # --- Rule 4: 4-node + door_passage_inside => ambiguous ---
        if node_mode == "4node" and "door_passage_inside" in (video_zone, csi_zone):
            resolution["resolved_zone"] = "ambiguous"
            resolution["resolution"] = "rule4_4node_door_ambiguous"
            resolution["reason"] = (
                f"4-node session cannot reliably distinguish door_passage_inside; "
                f"downgrading conflict '{video_zone}' vs '{csi_zone}' to ambiguous"
            )
            rule_counts["rule4_4node_door_ambiguous"] += 1
            resolutions.append(resolution)
            continue

        # --- No rule matched => unresolved ---
        resolution["resolved_zone"] = None
        resolution["resolution"] = "unresolved"
        resolution["reason"] = (
            f"No automatic rule applies (sim={csi_sim:.3f}, "
            f"zones={video_zone}->{csi_zone}, node_mode={node_mode})"
        )
        rule_counts["unresolved"] += 1
        resolutions.append(resolution)

    return resolutions, dict(rule_counts)


def main():
    print("Loading conflicts...")
    conflicts_data = load_json(CONFLICTS_PATH)
    conflicts = conflicts_data["conflicts"]
    print(f"  {len(conflicts)} conflicts loaded")

    print("Loading validation results...")
    results_data = load_json(RESULTS_PATH)
    node_mode_index = build_node_mode_index(results_data["results"])
    print(f"  {len(node_mode_index)} result entries indexed for node_mode")

    print("Loading manifest for zone_source...")
    manifest_data = load_json(MANIFEST_PATH)
    zone_source_index = build_zone_source_index(manifest_data)
    print(f"  {len(zone_source_index)} manifest entries indexed for zone_source")

    print("\nApplying conflict resolution rules...")
    resolutions, rule_counts = apply_rules(conflicts, node_mode_index, zone_source_index)

    # --- Summary statistics ---
    print("\n" + "=" * 60)
    print("CONFLICT RESOLUTION SUMMARY")
    print("=" * 60)
    total = len(conflicts)
    resolved = sum(1 for r in resolutions if r["resolution"] != "unresolved")

    print(f"\nTotal conflicts:  {total}")
    print(f"Auto-resolved:    {resolved}")
    print(f"Unresolved:       {total - resolved}")
    print(f"\nResolution rate:  {resolved/total*100:.1f}%")

    print("\nPer-rule breakdown:")
    rule_order = [
        "rule1_csi_override",
        "rule2_trust_video",
        "rule3_boundary",
        "rule4_4node_door_ambiguous",
        "unresolved",
    ]
    for rule in rule_order:
        count = rule_counts.get(rule, 0)
        desc = {
            "rule1_csi_override": "R1: CSI>0.5 + auto-zone => trust CSI",
            "rule2_trust_video": "R2: CSI<0.1 (weak)     => trust video",
            "rule3_boundary": "R3: Adjacent zones     => boundary",
            "rule4_4node_door_ambiguous": "R4: 4-node + door      => ambiguous",
            "unresolved": "    No rule matched    => unresolved",
        }.get(rule, rule)
        print(f"  {desc}: {count:3d} ({count/total*100:5.1f}%)")

    # --- Resolved zone distribution ---
    zone_dist = defaultdict(int)
    for r in resolutions:
        z = r["resolved_zone"] or "UNRESOLVED"
        zone_dist[z] += 1
    print("\nResolved zone distribution:")
    for zone, count in sorted(zone_dist.items(), key=lambda x: -x[1]):
        print(f"  {zone:25s}: {count}")

    # --- Train allowance impact ---
    allow_resolved = sum(
        1
        for r in resolutions
        if r["train_allowance"] == "allow" and r["resolution"] != "unresolved"
    )
    allow_total = sum(1 for r in resolutions if r["train_allowance"] == "allow")
    print(f"\nTrainable intervals resolved: {allow_resolved}/{allow_total}")

    # --- Write output ---
    output = {
        "schema": "conflict_resolutions_v1",
        "generated": datetime.now(timezone.utc).isoformat(),
        "source_conflicts": CONFLICTS_PATH,
        "source_results": RESULTS_PATH,
        "source_manifest": MANIFEST_PATH,
        "total_conflicts": total,
        "auto_resolved": resolved,
        "unresolved": total - resolved,
        "resolution_rate": round(resolved / total * 100, 1),
        "rule_counts": rule_counts,
        "rules_applied": [
            {
                "rule": "rule1_csi_override",
                "description": "CSI similarity > 0.5 AND zone_source == csi_auto => trust CSI zone",
                "threshold": "csi_similarity > 0.5",
            },
            {
                "rule": "rule2_trust_video",
                "description": "CSI similarity < 0.1 (very weak fingerprint match) => trust video label",
                "threshold": "csi_similarity < 0.1",
            },
            {
                "rule": "rule3_boundary",
                "description": "Adjacent zones (center<->transition, transition<->door) => mark as boundary",
                "adjacent_pairs": [
                    ["center", "transition"],
                    ["transition", "door_passage_inside"],
                ],
            },
            {
                "rule": "rule4_4node_door_ambiguous",
                "description": "4-node session + door_passage_inside conflict => downgrade to ambiguous",
                "condition": "node_mode == 4node AND either zone is door_passage_inside",
            },
        ],
        "resolutions": resolutions,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nOutput written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
