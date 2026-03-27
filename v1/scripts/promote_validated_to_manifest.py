#!/usr/bin/env python3
"""
Promote dual-validated intervals into manifest v19.

Steps:
  1. Load manifest v18 (767 intervals)
  2. Load mass_validation_results_v1.json
  3. Annotate matching intervals with dual_validation fields
  4. Auto-ingest 7-node sessions from temp/captures/
  5. Write v19 manifest + summary
"""

import json
import os
import re
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_V18 = PROJECT_ROOT / "output" / "video_curation" / "video_teacher_manifest_v18_batch04_ingest_v1.json"
VALIDATION_RESULTS = PROJECT_ROOT / "output" / "dual_validation" / "mass_validation_results_v1.json"
CAPTURES_DIR = PROJECT_ROOT / "temp" / "captures"
OUTPUT_DIR = PROJECT_ROOT / "output" / "video_curation"
OUT_MANIFEST = OUTPUT_DIR / "video_teacher_manifest_v19_dual_validated_v1.json"
OUT_SUMMARY = OUTPUT_DIR / "video_teacher_manifest_v19_dual_validated_summary_v1.json"


def load_json(path: Path) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  wrote {path}")


def get_session_label(interval: dict) -> str:
    """Return the session identifier regardless of key name."""
    return interval.get("session_label", interval.get("session", ""))


def build_interval_key(session_label: str, start_sec, end_sec) -> str:
    return f"{session_label}||{float(start_sec)}||{float(end_sec)}"


# ------------------------------------------------------------------
# 1  Load inputs
# ------------------------------------------------------------------
def load_inputs():
    print("[1] Loading inputs ...")
    manifest = load_json(MANIFEST_V18)
    validation = load_json(VALIDATION_RESULTS)
    print(f"  manifest v18: {len(manifest['intervals'])} intervals")
    print(f"  validation: {len(validation['results'])} results "
          f"({validation['summary']['validated']} validated, "
          f"{validation['summary']['conflict']} conflict, "
          f"{validation['summary']['ambiguous']} ambiguous)")
    return manifest, validation


# ------------------------------------------------------------------
# 2  Index validation results by (recording_label, start_sec, end_sec)
# ------------------------------------------------------------------
def index_validation(validation: dict) -> dict:
    """Build lookup: key -> validation result."""
    idx = {}
    for r in validation["results"]:
        key = build_interval_key(r["recording_label"], r["start_sec"], r["end_sec"])
        idx[key] = r
    return idx


# ------------------------------------------------------------------
# 3  Annotate manifest intervals with dual-validation fields
# ------------------------------------------------------------------
def annotate_intervals(manifest: dict, val_index: dict):
    print("[2] Annotating manifest intervals with dual-validation fields ...")
    stats = Counter()

    for interval in manifest["intervals"]:
        sl = get_session_label(interval)
        key = build_interval_key(sl, interval["start_sec"], interval["end_sec"])
        vr = val_index.get(key)

        if vr is None:
            # No validation result for this interval (not in validation scope)
            stats["no_validation_match"] += 1
            continue

        status = vr["status"]

        if status == "validated":
            interval["dual_validated"] = True
            interval["dual_validation_zone"] = vr["csi_closest_zone"]
            interval["dual_validation_similarity"] = vr["csi_similarity"]
            stats["validated"] += 1

        elif status == "conflict":
            interval["dual_validated"] = False
            interval["dual_validation_conflict_reason"] = vr["conflict_reason"]
            interval["dual_validation_zone"] = vr.get("csi_closest_zone")
            interval["dual_validation_similarity"] = vr.get("csi_similarity", 0.0)
            stats["conflict"] += 1

        elif status == "ambiguous":
            interval["dual_validated"] = False
            interval["dual_validation_conflict_reason"] = vr["conflict_reason"]
            interval["dual_validation_zone"] = vr.get("csi_closest_zone")
            interval["dual_validation_similarity"] = vr.get("csi_similarity", 0.0)
            stats["ambiguous"] += 1

        elif status.startswith("skipped"):
            # skipped_no_zone etc. -- leave unannotated
            stats["skipped"] += 1

        else:
            stats[f"unknown_{status}"] += 1

    print(f"  annotation stats: {dict(stats)}")
    return stats


# ------------------------------------------------------------------
# 4  Discover and ingest 7-node sessions from temp/captures/
# ------------------------------------------------------------------
def discover_7node_sessions() -> list[str]:
    """Return unique 7-node session labels from temp/captures/."""
    if not CAPTURES_DIR.exists():
        print(f"  WARNING: {CAPTURES_DIR} does not exist, skipping 7-node ingest")
        return []

    files = os.listdir(CAPTURES_DIR)
    pattern = re.compile(r"(7node|vnext7)", re.IGNORECASE)
    seven_node_files = [f for f in files if pattern.search(f)]

    sessions = set()

    # Sessions from recording_summary.json files
    for f in seven_node_files:
        if f.endswith(".recording_summary.json"):
            sessions.add(f.replace(".recording_summary.json", ""))

    # Sessions from ndjson.gz files (may not have recording_summary)
    for f in seven_node_files:
        if f.endswith(".ndjson.gz"):
            base = f.replace(".ndjson.gz", "")
            # Handle chunk pattern: <session>_chunk####_<timestamp>
            chunk_match = re.match(r"^(.+?)_chunk\d+_", base)
            if chunk_match:
                sessions.add(chunk_match.group(1))
            else:
                sessions.add(base)

    return sorted(sessions)


def ingest_7node_sessions(manifest: dict) -> dict:
    """Add 7-node sessions to manifest, deduplicating against existing."""
    print("[3] Discovering 7-node sessions from temp/captures/ ...")
    sessions = discover_7node_sessions()
    print(f"  found {len(sessions)} unique 7-node sessions")

    # Build set of existing session labels for dedup
    existing_labels = set()
    for interval in manifest["intervals"]:
        existing_labels.add(get_session_label(interval))

    added = []
    skipped_dedup = []

    for session_label in sessions:
        if session_label in existing_labels:
            skipped_dedup.append(session_label)
            continue

        new_interval = {
            "session_label": session_label,
            "start_sec": 0,
            "end_sec": -1,
            "duration_sec": -1,
            "video_truth_class": "UNKNOWN",
            "scenario_type": "7node_capture",
            "pose": "unknown",
            "zone": "unknown",
            "person_count": -1,
            "video_confidence": 0.0,
            "video_review_density": "none",
            "csi_cleanliness": "clean",
            "train_allowance": "pending_review",
            "canonical_status": "active",
            "provenance": "7node_auto_ingest",
            "source_artifact": "temp/captures/",
            "notes": "7-node session auto-ingested, needs video review and timing"
        }
        manifest["intervals"].append(new_interval)
        existing_labels.add(session_label)
        added.append(session_label)

    ingest_stats = {
        "discovered": len(sessions),
        "added": len(added),
        "skipped_dedup": len(skipped_dedup),
        "added_labels": added,
        "skipped_labels": skipped_dedup,
    }
    print(f"  added {len(added)} new sessions, skipped {len(skipped_dedup)} (already in manifest)")
    return ingest_stats


# ------------------------------------------------------------------
# 5  Rebuild stats
# ------------------------------------------------------------------
def rebuild_stats(manifest: dict) -> dict:
    intervals = manifest["intervals"]
    by_train = Counter()
    by_class = Counter()
    by_class_sec = Counter()
    by_person = Counter()
    by_person_sec = Counter()
    allow_sec = 0.0
    trim_sec = 0.0
    total_sec = 0.0

    for iv in intervals:
        ta = iv.get("train_allowance", "unknown")
        by_train[ta] += 1

        dur = iv.get("duration_sec", iv.get("end_sec", 0) - iv.get("start_sec", 0))
        if dur == -1:
            dur = 0  # whole-session placeholder
        total_sec += dur

        vtc = iv.get("video_truth_class", "UNKNOWN")

        if ta == "allow":
            by_class[vtc] += 1
            by_class_sec[vtc] += dur
            allow_sec += dur
            pc = iv.get("person_count", -1)
            by_person[str(pc)] += 1
            by_person_sec[str(pc)] += dur
        elif ta == "trim_allow":
            trim_sec += dur

    return {
        "total_intervals": len(intervals),
        "by_train_allowance": dict(by_train),
        "allow_seconds": round(allow_sec, 3),
        "trim_allow_seconds": round(trim_sec, 3),
        "total_seconds_all": round(total_sec, 3),
        "allow_by_class": dict(by_class),
        "allow_by_class_seconds": {k: round(v, 3) for k, v in by_class_sec.items()},
        "allow_by_person_count": dict(by_person),
        "allow_by_person_count_seconds": {k: round(v, 3) for k, v in by_person_sec.items()},
    }


# ------------------------------------------------------------------
# 6  Build and write outputs
# ------------------------------------------------------------------
def build_v19(manifest: dict, annotation_stats: dict, ingest_stats: dict):
    now = datetime.now(timezone.utc).isoformat()

    # Update header
    manifest["schema_version"] = "v19_dual_validated"
    manifest["generated"] = now
    manifest["agent"] = "PROMOTE_VALIDATED_TO_MANIFEST"
    manifest["description"] = (
        f"v19: dual-validation annotations on v18 intervals. "
        f"{annotation_stats.get('validated', 0)} intervals marked dual_validated=true, "
        f"{annotation_stats.get('conflict', 0)} conflict, "
        f"{annotation_stats.get('ambiguous', 0)} ambiguous. "
        f"{ingest_stats['added']} new 7-node sessions auto-ingested (pending review)."
    )

    # Add v19 note to truth_policy
    if "truth_policy" in manifest:
        manifest["truth_policy"]["dual_validation_v19_note"] = (
            "dual_validated=true means CSI fingerprint matched video-derived zone label. "
            "dual_validated=false with conflict_reason indicates CSI-video zone disagreement. "
            "7-node sessions added as pending_review placeholders."
        )

    # Add provenance log entry
    if "provenance_log" not in manifest:
        manifest["provenance_log"] = []
    manifest["provenance_log"].append({
        "version": "v19",
        "date": now,
        "action": "dual_validation_annotation_and_7node_ingest",
        "validated_count": annotation_stats.get("validated", 0),
        "conflict_count": annotation_stats.get("conflict", 0),
        "ambiguous_count": annotation_stats.get("ambiguous", 0),
        "seven_node_added": ingest_stats["added"],
        "seven_node_skipped_dedup": ingest_stats["skipped_dedup"],
    })

    # Rebuild stats
    manifest["stats"] = rebuild_stats(manifest)
    # Add v19-specific delta
    manifest["stats"]["v19_delta"] = {
        "dual_validated_intervals": annotation_stats.get("validated", 0),
        "dual_conflict_intervals": annotation_stats.get("conflict", 0),
        "dual_ambiguous_intervals": annotation_stats.get("ambiguous", 0),
        "seven_node_sessions_added": ingest_stats["added"],
    }

    return manifest


def build_summary(annotation_stats: dict, ingest_stats: dict, manifest: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()

    # Collect dual-validated intervals for quick reference
    validated_intervals = []
    conflict_intervals = []
    for iv in manifest["intervals"]:
        if iv.get("dual_validated") is True:
            validated_intervals.append({
                "session_label": get_session_label(iv),
                "start_sec": iv["start_sec"],
                "end_sec": iv["end_sec"],
                "video_truth_class": iv.get("video_truth_class"),
                "zone": iv.get("zone"),
                "dual_validation_zone": iv.get("dual_validation_zone"),
                "dual_validation_similarity": iv.get("dual_validation_similarity"),
                "train_allowance": iv.get("train_allowance"),
            })
        elif iv.get("dual_validated") is False:
            conflict_intervals.append({
                "session_label": get_session_label(iv),
                "start_sec": iv["start_sec"],
                "end_sec": iv["end_sec"],
                "video_truth_class": iv.get("video_truth_class"),
                "zone": iv.get("zone"),
                "dual_validation_zone": iv.get("dual_validation_zone"),
                "dual_validation_similarity": iv.get("dual_validation_similarity"),
                "dual_validation_conflict_reason": iv.get("dual_validation_conflict_reason"),
                "train_allowance": iv.get("train_allowance"),
            })

    return {
        "schema": "v19_dual_validated_summary",
        "generated": now,
        "source_manifest": str(MANIFEST_V18),
        "source_validation": str(VALIDATION_RESULTS),
        "annotation_stats": dict(annotation_stats),
        "ingest_stats": ingest_stats,
        "manifest_stats": manifest["stats"],
        "validated_intervals": validated_intervals,
        "conflict_intervals": conflict_intervals,
        "seven_node_sessions_added": ingest_stats["added_labels"],
    }


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
AUTO_ZONE_RESULTS = PROJECT_ROOT / "output" / "dual_validation" / "auto_zone_assignments_v1.json"


def apply_auto_zone(manifest: dict) -> int:
    """Merge auto-zone assignments into intervals with zone=unknown."""
    if not AUTO_ZONE_RESULTS.exists():
        print("  [auto-zone] No auto_zone_assignments_v1.json found, skipping")
        return 0

    az_raw = load_json(AUTO_ZONE_RESULTS)
    assignments = az_raw.get("assignments", [])

    # Index by (recording_label, start_sec, end_sec)
    az_index = {}
    for a in assignments:
        if a.get("assigned_zone") and a.get("confidence_level") in ("high", "medium"):
            key = build_interval_key(
                a["recording_label"], a["start_sec"], a["end_sec"]
            )
            az_index[key] = a

    enriched = 0
    for iv in manifest["intervals"]:
        zone = (iv.get("zone", "") or "").strip().lower()
        if zone not in ("unknown", "", "unknown_handheld"):
            continue
        sl = get_session_label(iv)
        key = build_interval_key(sl, iv["start_sec"], iv["end_sec"])
        az = az_index.get(key)
        if az:
            iv["zone"] = az["assigned_zone"]
            iv["zone_source"] = "csi_auto"
            iv["zone_confidence"] = az["confidence"]
            iv["zone_confidence_level"] = az["confidence_level"]
            enriched += 1

    print(f"  [auto-zone] Enriched {enriched} intervals with CSI-derived zone labels "
          f"(high/medium confidence only, from {len(az_index)} candidates)")
    return enriched


def main():
    print("=" * 60)
    print("Promote dual-validated intervals to manifest v19")
    print("=" * 60)

    manifest, validation = load_inputs()
    val_index = index_validation(validation)
    annotation_stats = annotate_intervals(manifest, val_index)
    ingest_stats = ingest_7node_sessions(manifest)

    # Auto-zone enrichment
    print("[3b] Applying auto-zone assignments ...")
    n_auto_zone = apply_auto_zone(manifest)
    annotation_stats["auto_zone_enriched"] = n_auto_zone

    print("[4] Building v19 manifest ...")
    manifest = build_v19(manifest, annotation_stats, ingest_stats)

    print("[5] Writing outputs ...")
    save_json(OUT_MANIFEST, manifest)

    summary = build_summary(annotation_stats, ingest_stats, manifest)
    save_json(OUT_SUMMARY, summary)

    print()
    print(f"Done. v19 manifest: {len(manifest['intervals'])} total intervals")
    print(f"  dual_validated=true:  {annotation_stats.get('validated', 0)}")
    print(f"  dual_validated=false: {annotation_stats.get('conflict', 0) + annotation_stats.get('ambiguous', 0)}")
    print(f"  7-node sessions:     {ingest_stats['added']} added")


if __name__ == "__main__":
    main()
