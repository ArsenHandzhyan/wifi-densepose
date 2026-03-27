#!/usr/bin/env python3
"""
Mass Corpus Dual Validation Pipeline.

Loads gold zone fingerprints once, then validates ALL labeled intervals
from the video teacher manifest against CSI signal patterns.

Outputs:
  - mass_validation_results_v1.json   — all results
  - mass_conflicts_v1.json            — only conflicts with reasons
  - mass_validation_summary_v1.json   — stats per session

Usage:
    python v1/scripts/run_mass_validation.py

    # Process only first 5 sessions:
    python v1/scripts/run_mass_validation.py --limit 5

    # Process specific sessions:
    python v1/scripts/run_mass_validation.py \
        --sessions garage_live_20260324_1606 garage_freeform_20260324_1602

    # Custom paths:
    python v1/scripts/run_mass_validation.py \
        --gold-dir output/garage_guided_review_dense1 \
        --captures-dir temp/captures \
        --output-dir output/dual_validation \
        --manifest output/video_curation/video_teacher_manifest_v18_batch04_ingest_v1.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Ensure project root is on the Python path
PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from v1.src.services.dual_validation_service import (
    DualValidationService,
    ZoneFingerprint,
    build_fingerprint_feature_keys,
    compute_normalization_stats,
    extract_windows_for_segment,
    find_capture_files,
    find_closest_zone,
    load_ndjson_capture,
    _normalize_zone_label,
    FEATURE_WINDOW_SEC,
    SIMILARITY_AMBIGUOUS_THRESHOLD,
    SIMILARITY_VALIDATED_THRESHOLD,
    MARGIN_AMBIGUOUS_THRESHOLD,
    CORE_NODE_IDS,
    SHADOW_NODE_IDS,
)
from v1.src.services.csi_node_inventory import NODE_IPS, NODE_NAMES

logger = logging.getLogger(__name__)


# ── Zone Label Mapping ────────────────────────────────────────────────
# Maps manifest zone labels to the 3 fingerprint zones.
# Labels not in this map cannot be zone-validated (binary-only).
ZONE_MAP = {
    "center": "center",
    "center_near_camera": "center",
    "center_to_right": "center",
    "center_right": "center",
    "center_to_far": "center",
    "center_to_left": "center",
    "center_to_center_right": "center",
    "center_crossing": "center",
    "center_to_near_camera": "center",
    "center_left_near_entrance": "center",
    "center_to_right_to_left": "center",
    "left_center_right": "center",
    "center_to_door": "transition",
    "door_to_center": "transition",
    "far_area_to_door": "transition",
    "center_door_to_right": "transition",
    "door": "door_passage_inside",
    "door_zone": "door_passage_inside",
    "door_area": "door_passage_inside",
    "door_zone_occluded": "door_passage_inside",
    "door_to_left": "door_passage_inside",
    "door_to_left_near_camera": "door_passage_inside",
    "transition": "transition",
    "mixed": "mixed",
    # Binary labels — not zone-validatable, mark as special
    "garage": "center",  # whole-garage = center approximation
    "s7_garage": "center",
}

# Labels that are binary (occupancy) and can't be zone-validated
BINARY_ONLY_LABELS = {
    "static", "motion", "empty", "unknown", "unknown_handheld",
    "no_video", "entry_exit", "mixed_motion_static", "multi_candidate",
    "occupied_single", "no_visible_person", "setup", "high_motion_exit",
}


# ── Manifest Discovery ────────────────────────────────────────────────


def find_latest_manifest(curation_dir: Path) -> Path | None:
    """
    Find the latest video_teacher_manifest_v*.json in the curation directory.

    Prefers the v18 batch04 ingest, then falls back to the highest
    version number found.
    """
    preferred = curation_dir / "video_teacher_manifest_v18_batch04_ingest_v1.json"
    if preferred.exists():
        return preferred

    # Search for all manifest files, pick highest version
    candidates = sorted(
        curation_dir.glob("video_teacher_manifest_v*.json"),
        key=lambda p: p.name,
        reverse=True,
    )
    # Filter out summary/handoff files — we want ingest or plain manifests
    for c in candidates:
        if "summary" in c.name or "handoff" in c.name:
            continue
        return c

    return None


def load_manifest_intervals(manifest_path: Path) -> list[dict]:
    """
    Load intervals from a video teacher manifest.

    Handles both dict-with-intervals and plain-list formats.
    Normalises field names to the canonical set used by the validation
    pipeline: recording_label, start_sec, end_sec, label.
    """
    with open(manifest_path) as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        intervals = raw.get("intervals", raw.get("segments", []))
    elif isinstance(raw, list):
        intervals = raw
    else:
        logger.error(f"Unexpected manifest format in {manifest_path}")
        return []

    # Normalise field names for downstream consumption
    normalised = []
    for iv in intervals:
        rec_label = iv.get("session_label", "") or iv.get("recording_label", "")
        if not rec_label:
            continue

        # Determine zone label. Manifests have "zone" (spatial) and
        # "video_truth_class" (binary occupancy). For dual validation
        # we need the spatial zone mapped to fingerprint zones.
        raw_zone = (iv.get("zone", "") or "").lower().strip()
        raw_binary = (iv.get("video_truth_class", "") or "").lower().strip()

        start_sec = float(iv.get("start_sec", 0))
        end_sec = float(iv.get("end_sec", 0))

        # Skip degenerate intervals (end_sec=-1 means whole-session)
        if end_sec <= start_sec:
            continue

        # Map zone to fingerprint zone
        mapped_zone = ZONE_MAP.get(raw_zone)
        is_binary_only = raw_zone in BINARY_ONLY_LABELS or (
            not raw_zone or raw_zone == "unknown"
        )

        if mapped_zone:
            label = mapped_zone
            zone_mappable = True
        elif is_binary_only:
            label = raw_binary if raw_binary else raw_zone
            zone_mappable = False
        else:
            # Unknown zone — try mapping, else mark as unmappable
            label = raw_zone
            zone_mappable = False

        normalised.append({
            "recording_label": rec_label,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "label": label,
            "raw_zone": raw_zone,
            "raw_binary": raw_binary,
            "zone_mappable": zone_mappable,
            "train_allowance": iv.get("train_allowance", "unknown"),
            "csi_cleanliness": iv.get("csi_cleanliness", "unknown"),
            "person_count": iv.get("person_count", None),
            "scenario_type": iv.get("scenario_type", ""),
            "canonical_status": iv.get("canonical_status", "active"),
        })

    return normalised


# ── Node Count Detection ─────────────────────────────────────────────

SHADOW_IPS = {
    str(e["ip"]) for e in __import__("v1.src.services.csi_node_inventory", fromlist=["CSI_NODE_INVENTORY"]).CSI_NODE_INVENTORY
    if str(e["node_id"]) in SHADOW_NODE_IDS
}


def detect_node_count(packets: list[dict], sample_limit: int = 500) -> int:
    """
    Detect whether a capture session uses 4 or 7 nodes.

    Samples first `sample_limit` packets and checks for shadow node IPs.
    Returns 7 if any shadow node is present, else 4.
    """
    for pkt in packets[:sample_limit]:
        if pkt.get("src_ip", "") in SHADOW_IPS:
            return 7
    return 4


# ── Session Grouping ──────────────────────────────────────────────────


def group_intervals_by_session(
    intervals: list[dict],
) -> dict[str, list[dict]]:
    """Group manifest intervals by recording_label."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for iv in intervals:
        groups[iv["recording_label"]].append(iv)
    return dict(groups)


# ── Mass Validation Core ─────────────────────────────────────────────


def run_mass_validation(
    fingerprints: dict[str, ZoneFingerprint],
    feature_keys: list[str],
    session_intervals: dict[str, list[dict]],
    captures_dir: Path,
    window_sec: float = FEATURE_WINDOW_SEC,
    fingerprints_4node: dict[str, ZoneFingerprint] | None = None,
    feature_keys_4node: list[str] | None = None,
) -> tuple[list[dict], dict[str, dict]]:
    """
    Validate all sessions against pre-built fingerprints.

    Automatically detects 4-node vs 7-node sessions and uses
    the appropriate fingerprint set for each.

    Args:
        fingerprints: Gold zone fingerprints (7-node).
        feature_keys: Canonical feature key ordering (7-node).
        session_intervals: Dict of recording_label -> list of interval dicts.
        captures_dir: Directory containing ndjson.gz capture files.
        window_sec: Feature extraction window size in seconds.
        fingerprints_4node: Gold zone fingerprints (4-node core only).
        feature_keys_4node: Feature key ordering for 4-node mode.

    Returns:
        (all_results, per_session_summary)
    """
    # Pre-compute normalization stats for both modes
    norm_stats_7 = compute_normalization_stats(fingerprints, feature_keys)
    norm_stats_4 = (
        compute_normalization_stats(fingerprints_4node, feature_keys_4node)
        if fingerprints_4node and feature_keys_4node
        else None
    )

    all_results: list[dict] = []
    session_summaries: dict[str, dict] = {}
    total_sessions = len(session_intervals)
    packets_cache: dict[str, list[dict]] = {}
    session_start_cache: dict[str, int] = {}

    for sess_idx, (rec_label, intervals) in enumerate(
        sorted(session_intervals.items()), start=1
    ):
        t0 = time.time()
        logger.info(
            f"[{sess_idx}/{total_sessions}] Processing session '{rec_label}' "
            f"({len(intervals)} intervals)..."
        )

        # Load packets if not cached
        if rec_label not in packets_cache:
            capture_files = find_capture_files(captures_dir, rec_label)
            if capture_files:
                all_pkts: list[dict] = []
                for cf in capture_files:
                    all_pkts.extend(load_ndjson_capture(cf))
                all_pkts.sort(key=lambda p: int(p.get("ts_ns", 0)))
                packets_cache[rec_label] = all_pkts
                if all_pkts:
                    session_start_cache[rec_label] = int(all_pkts[0]["ts_ns"])
                logger.debug(
                    f"  Loaded {len(all_pkts)} packets from "
                    f"{len(capture_files)} chunk(s)"
                )
            else:
                packets_cache[rec_label] = []
                logger.debug(f"  No capture files found for '{rec_label}'")

        packets = packets_cache.get(rec_label, [])
        session_start_ns = session_start_cache.get(rec_label, 0)

        # Detect node count and select appropriate fingerprints
        n_nodes = detect_node_count(packets) if packets else 4
        if n_nodes == 4 and fingerprints_4node and feature_keys_4node:
            sess_fp = fingerprints_4node
            sess_fk = feature_keys_4node
            sess_norm = norm_stats_4
            mode_tag = "4node"
        else:
            sess_fp = fingerprints
            sess_fk = feature_keys
            sess_norm = norm_stats_7
            mode_tag = "7node"

        logger.debug(f"  Using {mode_tag} fingerprints ({n_nodes} nodes detected)")

        status_counts: dict[str, int] = defaultdict(int)
        session_results: list[dict] = []

        # ── Phase 1: Extract ALL windows for the entire session ──
        # Then normalize per-session to remove domain shift.
        from v1.src.services.dual_validation_service import normalize_session_features

        all_session_windows: list[tuple[int, list[dict[str, float]]]] = []
        mappable_indices: list[int] = []

        for iv_idx, interval in enumerate(intervals):
            zone_mappable = interval.get("zone_mappable", True)
            if not zone_mappable:
                all_session_windows.append((iv_idx, []))
                continue

            start_sec = interval["start_sec"]
            end_sec = interval["end_sec"]

            if packets and end_sec > start_sec:
                seg_features = extract_windows_for_segment(
                    packets, session_start_ns,
                    start_sec, end_sec,
                    window_sec,
                )
            else:
                seg_features = []

            all_session_windows.append((iv_idx, seg_features))
            if seg_features:
                mappable_indices.append(iv_idx)

        # Collect all windows flat for normalization
        flat_windows = []
        window_map: list[tuple[int, int]] = []  # (iv_idx, pos_in_flat)
        for iv_idx, wins in all_session_windows:
            for w in wins:
                window_map.append((iv_idx, len(flat_windows)))
                flat_windows.append(w)

        # Normalize across the entire session
        if flat_windows:
            normed_flat = normalize_session_features(flat_windows)
        else:
            normed_flat = []

        # Reassemble per-interval
        normed_per_interval: dict[int, list[dict[str, float]]] = defaultdict(list)
        for (iv_idx, _), nw in zip(window_map, normed_flat):
            normed_per_interval[iv_idx].append(nw)

        # ── Phase 2: Validate each interval ──
        for iv_idx, interval in enumerate(intervals):
            video_label = interval["label"]
            start_sec = interval["start_sec"]
            end_sec = interval["end_sec"]
            seg_id = f"{rec_label}_seg_{iv_idx:04d}"
            zone_mappable = interval.get("zone_mappable", True)

            # Skip zone validation for binary-only labels
            if not zone_mappable:
                result = {
                    "id": seg_id,
                    "recording_label": rec_label,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "video_label": video_label,
                    "raw_zone": interval.get("raw_zone", ""),
                    "raw_binary": interval.get("raw_binary", ""),
                    "train_allowance": interval.get("train_allowance", "unknown"),
                    "csi_cleanliness": interval.get("csi_cleanliness", "unknown"),
                    "person_count": interval.get("person_count"),
                    "n_csi_windows": 0,
                    "csi_closest_zone": None,
                    "csi_similarity": 0.0,
                    "csi_similarity_to_video_zone": 0.0,
                    "status": "skipped_no_zone",
                    "conflict_reason": (
                        f"binary-only label '{video_label}' (zone='{interval.get('raw_zone', '')}') "
                        f"cannot be zone-validated against fingerprints"
                    ),
                }
                session_results.append(result)
                status_counts["skipped_no_zone"] += 1
                continue

            seg_features = normed_per_interval.get(iv_idx, [])

            # Run validation
            if not seg_features:
                validation = {
                    "csi_closest_zone": None,
                    "csi_similarity": 0.0,
                    "csi_similarity_to_video_zone": 0.0,
                    "all_similarities": {},
                    "status": "ambiguous",
                    "conflict_reason": "no CSI data available for segment time window",
                }
            else:
                # Average features across windows
                all_keys_set: set[str] = set()
                for feat in seg_features:
                    all_keys_set.update(
                        k for k in feat.keys() if k != "_active_nodes"
                    )

                avg_features: dict[str, float] = {}
                for key in all_keys_set:
                    vals = [f.get(key, 0.0) for f in seg_features]
                    avg_features[key] = float(
                        sum(vals) / len(vals)
                    )

                feature_vec = np.array(
                    [avg_features.get(k, 0.0) for k in sess_fk],
                    dtype=np.float64,
                )

                closest_zone, best_sim, all_sims = find_closest_zone(
                    feature_vec, sess_fp, sess_fk,
                    norm_stats=sess_norm,
                )

                norm_video = _normalize_zone_label(video_label)
                norm_closest = _normalize_zone_label(closest_zone)

                video_zone_sim = all_sims.get(
                    norm_video, all_sims.get(video_label, 0.0)
                )
                sorted_sims = sorted(all_sims.values(), reverse=True)
                margin = (
                    (sorted_sims[0] - sorted_sims[1])
                    if len(sorted_sims) >= 2
                    else sorted_sims[0]
                )

                if norm_video == "mixed":
                    status = "validated"
                    conflict_reason = None
                elif norm_video == norm_closest:
                    if best_sim >= SIMILARITY_AMBIGUOUS_THRESHOLD:
                        status = "validated"
                        conflict_reason = None
                    else:
                        status = "ambiguous"
                        conflict_reason = (
                            f"video and CSI agree on {video_label} but "
                            f"similarity is low (sim={best_sim:.3f})"
                        )
                else:
                    if best_sim < SIMILARITY_AMBIGUOUS_THRESHOLD:
                        status = "ambiguous"
                        conflict_reason = (
                            f"CSI signal too weak to validate "
                            f"(best sim={best_sim:.3f} to {closest_zone})"
                        )
                    elif margin < MARGIN_AMBIGUOUS_THRESHOLD:
                        status = "ambiguous"
                        conflict_reason = (
                            f"video={video_label} but CSI is ambiguous "
                            f"between zones (margin={margin:.3f})"
                        )
                    else:
                        status = "conflict"
                        conflict_reason = (
                            f"video={video_label} but CSI fingerprint "
                            f"matches {closest_zone} "
                            f"(sim={best_sim:.3f} vs {video_zone_sim:.3f})"
                        )

                validation = {
                    "csi_closest_zone": closest_zone,
                    "csi_similarity": round(best_sim, 4),
                    "csi_similarity_to_video_zone": round(video_zone_sim, 4),
                    "all_similarities": {
                        k: round(v, 4) for k, v in all_sims.items()
                    },
                    "status": status,
                    "conflict_reason": conflict_reason,
                }

            result = {
                "id": seg_id,
                "recording_label": rec_label,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "video_label": video_label,
                "node_mode": mode_tag,
                "train_allowance": interval.get("train_allowance", "unknown"),
                "csi_cleanliness": interval.get("csi_cleanliness", "unknown"),
                "person_count": interval.get("person_count"),
                "n_csi_windows": len(seg_features),
                **validation,
            }
            session_results.append(result)
            status_counts[validation["status"]] += 1

        all_results.extend(session_results)

        elapsed = time.time() - t0
        session_summaries[rec_label] = {
            "n_intervals": len(intervals),
            "n_with_csi": sum(1 for r in session_results if r["n_csi_windows"] > 0),
            "validated": status_counts.get("validated", 0),
            "conflict": status_counts.get("conflict", 0),
            "ambiguous": status_counts.get("ambiguous", 0),
            "skipped_no_zone": status_counts.get("skipped_no_zone", 0),
            "elapsed_sec": round(elapsed, 2),
        }

        logger.info(
            f"  -> validated={status_counts.get('validated', 0)} "
            f"conflict={status_counts.get('conflict', 0)} "
            f"ambiguous={status_counts.get('ambiguous', 0)} "
            f"({elapsed:.1f}s)"
        )

    return all_results, session_summaries


# ── Output Serialization ─────────────────────────────────────────────


def save_outputs(
    all_results: list[dict],
    session_summaries: dict[str, dict],
    fingerprints: dict[str, ZoneFingerprint],
    manifest_path: Path,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    """
    Save the three output JSON files.

    Returns:
        (results_path, conflicts_path, summary_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Global status counts
    status_counts: dict[str, int] = defaultdict(int)
    for r in all_results:
        status_counts[r["status"]] += 1

    # ── mass_validation_results_v1.json ──
    results_doc = {
        "schema": "mass_validation_results_v1",
        "generated": now_iso,
        "manifest_source": str(manifest_path),
        "summary": {
            "total_intervals": len(all_results),
            "total_sessions": len(session_summaries),
            "validated": status_counts.get("validated", 0),
            "conflict": status_counts.get("conflict", 0),
            "ambiguous": status_counts.get("ambiguous", 0),
        },
        "gold_fingerprints": {
            zone: fp.to_dict() for zone, fp in fingerprints.items()
        },
        "results": all_results,
    }
    results_path = output_dir / "mass_validation_results_v1.json"
    with open(results_path, "w") as f:
        json.dump(results_doc, f, indent=2, ensure_ascii=False)

    # ── mass_conflicts_v1.json ──
    conflicts = [r for r in all_results if r["status"] == "conflict"]
    conflicts_doc = {
        "schema": "mass_validation_conflicts_v1",
        "generated": now_iso,
        "manifest_source": str(manifest_path),
        "total_conflicts": len(conflicts),
        "conflicts": [
            {
                "id": c["id"],
                "recording_label": c["recording_label"],
                "start_sec": c["start_sec"],
                "end_sec": c["end_sec"],
                "video_label": c["video_label"],
                "train_allowance": c.get("train_allowance", "unknown"),
                "person_count": c.get("person_count"),
                "csi_closest_zone": c["csi_closest_zone"],
                "csi_similarity": c["csi_similarity"],
                "csi_similarity_to_video_zone": c.get(
                    "csi_similarity_to_video_zone", 0.0
                ),
                "conflict_reason": c["conflict_reason"],
            }
            for c in conflicts
        ],
    }
    conflicts_path = output_dir / "mass_conflicts_v1.json"
    with open(conflicts_path, "w") as f:
        json.dump(conflicts_doc, f, indent=2, ensure_ascii=False)

    # ── mass_validation_summary_v1.json ──
    summary_doc = {
        "schema": "mass_validation_summary_v1",
        "generated": now_iso,
        "manifest_source": str(manifest_path),
        "global_summary": {
            "total_intervals": len(all_results),
            "total_sessions": len(session_summaries),
            "validated": status_counts.get("validated", 0),
            "conflict": status_counts.get("conflict", 0),
            "ambiguous": status_counts.get("ambiguous", 0),
            "conflict_rate": round(
                status_counts.get("conflict", 0) / max(len(all_results), 1), 4
            ),
        },
        "per_session": session_summaries,
    }
    summary_path = output_dir / "mass_validation_summary_v1.json"
    with open(summary_path, "w") as f:
        json.dump(summary_doc, f, indent=2, ensure_ascii=False)

    return results_path, conflicts_path, summary_path


# ── CLI Entrypoint ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Mass Corpus Dual Validation: validate all manifest intervals "
            "against gold CSI zone fingerprints"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Video is the PRIMARY truth source. CSI provides cross-validation.\n"
            "Conflicts are always recorded, never masked.\n\n"
            "Outputs three files to --output-dir:\n"
            "  mass_validation_results_v1.json  — all results\n"
            "  mass_conflicts_v1.json           — conflicts only\n"
            "  mass_validation_summary_v1.json  — per-session stats"
        ),
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=Path("output/garage_guided_review_dense1"),
        help=(
            "Directory containing gold-standard annotations "
            "(manual_annotations_v1.json files, searched recursively). "
            "Default: output/garage_guided_review_dense1"
        ),
    )
    parser.add_argument(
        "--captures-dir",
        type=Path,
        default=Path("temp/captures"),
        help=(
            "Directory containing CSI capture files (ndjson.gz). "
            "Default: temp/captures"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/dual_validation"),
        help=(
            "Output directory for result JSON files. "
            "Default: output/dual_validation"
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Path to video teacher manifest JSON. "
            "Default: auto-detect latest in output/video_curation/"
        ),
    )
    parser.add_argument(
        "--window-sec",
        type=float,
        default=2.0,
        help="Feature extraction window size in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N sessions (for testing)",
    )
    parser.add_argument(
        "--sessions",
        nargs="+",
        default=None,
        help="Process only these specific recording labels",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Resolve paths relative to project root if not absolute
    gold_dir = args.gold_dir if args.gold_dir.is_absolute() else PROJECT / args.gold_dir
    captures_dir = (
        args.captures_dir
        if args.captures_dir.is_absolute()
        else PROJECT / args.captures_dir
    )
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else PROJECT / args.output_dir
    )

    # Resolve manifest path
    if args.manifest:
        manifest_path = (
            args.manifest
            if args.manifest.is_absolute()
            else PROJECT / args.manifest
        )
    else:
        curation_dir = PROJECT / "output" / "video_curation"
        manifest_path = find_latest_manifest(curation_dir)
        if manifest_path is None:
            logging.error(
                f"No video teacher manifest found in {curation_dir}. "
                f"Use --manifest to specify one explicitly."
            )
            sys.exit(1)

    # Validate inputs
    if not gold_dir.exists():
        logging.error(f"Gold directory does not exist: {gold_dir}")
        sys.exit(1)
    if not captures_dir.exists():
        logging.error(f"Captures directory does not exist: {captures_dir}")
        sys.exit(1)
    if not manifest_path.exists():
        logging.error(f"Manifest does not exist: {manifest_path}")
        sys.exit(1)

    # ── Banner ──
    logging.info("=" * 60)
    logging.info("Mass Corpus Dual Validation Pipeline")
    logging.info("=" * 60)
    logging.info(f"  Gold dir:     {gold_dir}")
    logging.info(f"  Captures dir: {captures_dir}")
    logging.info(f"  Output dir:   {output_dir}")
    logging.info(f"  Manifest:     {manifest_path.name}")
    logging.info(f"  Window size:  {args.window_sec}s")
    if args.limit:
        logging.info(f"  Limit:        {args.limit} sessions")
    if args.sessions:
        logging.info(f"  Sessions:     {args.sessions}")
    logging.info("")

    # ── Step 1: Build gold fingerprints ──
    logging.info("[1/4] Loading gold annotations and building zone fingerprints...")
    svc = DualValidationService(
        gold_dir=gold_dir,
        captures_dir=captures_dir,
        feature_window_sec=args.window_sec,
    )
    n_gold = svc.load_gold_annotations()
    if n_gold == 0:
        logging.error("No gold annotations found. Check --gold-dir path.")
        sys.exit(1)

    n_captures = svc.load_capture_data()
    if n_captures == 0:
        logging.warning(
            "No CSI capture data matched gold annotations. "
            "Fingerprints may be empty."
        )

    fingerprints = svc.build_zone_fingerprints()
    if not fingerprints:
        logging.error(
            "No zone fingerprints could be built from gold data. "
            "Cannot proceed with mass validation."
        )
        sys.exit(1)

    feature_keys = svc.feature_keys
    fingerprints_4node = getattr(svc, "fingerprints_4node", None)
    feature_keys_4node = getattr(svc, "feature_keys_4node", None)
    logging.info(
        f"  Built {len(fingerprints)} zone fingerprints: "
        f"{', '.join(f'{z}({fp.n_windows}w)' for z, fp in sorted(fingerprints.items()))}"
    )
    logging.info("")

    # ── Step 2: Load manifest intervals ──
    logging.info(f"[2/4] Loading manifest intervals from {manifest_path.name}...")
    all_intervals = load_manifest_intervals(manifest_path)
    logging.info(f"  Loaded {len(all_intervals)} valid intervals from manifest")

    # Group by session
    session_intervals = group_intervals_by_session(all_intervals)
    logging.info(f"  Across {len(session_intervals)} unique sessions")

    # Apply filters
    if args.sessions:
        filtered = {}
        for s in args.sessions:
            if s in session_intervals:
                filtered[s] = session_intervals[s]
            else:
                # Partial match
                for key in session_intervals:
                    if s in key:
                        filtered[key] = session_intervals[key]
        session_intervals = filtered
        logging.info(
            f"  Filtered to {len(session_intervals)} sessions matching --sessions"
        )

    if args.limit and len(session_intervals) > args.limit:
        keys = sorted(session_intervals.keys())[: args.limit]
        session_intervals = {k: session_intervals[k] for k in keys}
        logging.info(f"  Limited to first {args.limit} sessions")

    total_intervals = sum(len(v) for v in session_intervals.values())
    logging.info(f"  Will validate {total_intervals} intervals across "
                 f"{len(session_intervals)} sessions")
    logging.info("")

    # ── Step 3: Mass validation ──
    logging.info("[3/4] Running mass validation...")
    t_start = time.time()

    all_results, session_summaries = run_mass_validation(
        fingerprints=fingerprints,
        feature_keys=feature_keys,
        session_intervals=session_intervals,
        captures_dir=captures_dir,
        window_sec=args.window_sec,
        fingerprints_4node=fingerprints_4node,
        feature_keys_4node=feature_keys_4node,
    )

    elapsed_total = time.time() - t_start
    logging.info(f"  Mass validation completed in {elapsed_total:.1f}s")
    logging.info("")

    # ── Step 4: Save outputs ──
    logging.info("[4/4] Saving results...")
    results_path, conflicts_path, summary_path = save_outputs(
        all_results=all_results,
        session_summaries=session_summaries,
        fingerprints=fingerprints,
        manifest_path=manifest_path,
        output_dir=output_dir,
    )

    # ── Print summary ──
    status_counts: dict[str, int] = defaultdict(int)
    for r in all_results:
        status_counts[r["status"]] += 1

    n_conflicts = status_counts.get("conflict", 0)

    logging.info("")
    logging.info("=" * 60)
    logging.info("MASS VALIDATION RESULTS")
    logging.info("=" * 60)
    logging.info(f"  Total sessions:   {len(session_summaries)}")
    logging.info(f"  Total intervals:  {len(all_results)}")
    logging.info(f"  Validated:        {status_counts.get('validated', 0)}")
    logging.info(f"  Conflicts:        {n_conflicts}")
    logging.info(f"  Ambiguous:        {status_counts.get('ambiguous', 0)}")
    logging.info(
        f"  Conflict rate:    "
        f"{n_conflicts / max(len(all_results), 1) * 100:.1f}%"
    )
    logging.info("")

    if fingerprints:
        logging.info("Zone fingerprints:")
        for zone_name, fp in sorted(fingerprints.items()):
            logging.info(f"  {zone_name}: {fp.n_windows} windows")

    # Show top conflicting sessions
    conflict_sessions = sorted(
        [
            (label, s["conflict"])
            for label, s in session_summaries.items()
            if s["conflict"] > 0
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    if conflict_sessions:
        logging.info("")
        logging.info(f"Sessions with conflicts ({len(conflict_sessions)}):")
        for label, n in conflict_sessions[:10]:
            s = session_summaries[label]
            logging.info(
                f"  {label}: {n} conflicts / {s['n_intervals']} intervals"
            )
        if len(conflict_sessions) > 10:
            logging.info(f"  ... and {len(conflict_sessions) - 10} more")

    logging.info("")
    logging.info(f"Output saved to: {output_dir}")
    logging.info(f"  - {results_path.name}")
    logging.info(f"  - {conflicts_path.name}")
    logging.info(f"  - {summary_path.name}")
    logging.info(f"  Elapsed: {elapsed_total:.1f}s")


if __name__ == "__main__":
    main()
