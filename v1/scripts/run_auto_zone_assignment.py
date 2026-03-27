#!/usr/bin/env python3
"""
Auto Zone Assignment Pipeline.

Assigns zone labels to manifest intervals that have zone=unknown or zone=""
by matching their CSI features against gold zone fingerprints built from
the dual validation service.

Uses the same fingerprinting, normalization, and similarity logic as
run_mass_validation.py to ensure consistency.

Outputs:
  - auto_zone_assignments_v1.json  — per-interval assignments with confidence

Usage:
    python v1/scripts/run_auto_zone_assignment.py

    # Custom paths:
    python v1/scripts/run_auto_zone_assignment.py \
        --gold-dir output/garage_guided_review_dense1 \
        --captures-dir temp/captures \
        --output-dir output/dual_validation \
        --manifest output/video_curation/video_teacher_manifest_v18_batch04_ingest_v1.json

    # Process only first 5 sessions:
    python v1/scripts/run_auto_zone_assignment.py --limit 5

    # Process specific sessions:
    python v1/scripts/run_auto_zone_assignment.py \
        --sessions garage_live_20260324_1606 garage_freeform_20260324_1602
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
    normalize_session_features,
    FEATURE_WINDOW_SEC,
    CORE_NODE_IDS,
    SHADOW_NODE_IDS,
)
from v1.src.services.csi_node_inventory import NODE_IPS, NODE_NAMES

logger = logging.getLogger(__name__)


# ── Shadow IP detection (same logic as run_mass_validation.py) ────────

SHADOW_IPS = {
    str(e["ip"])
    for e in __import__(
        "v1.src.services.csi_node_inventory", fromlist=["CSI_NODE_INVENTORY"]
    ).CSI_NODE_INVENTORY
    if str(e["node_id"]) in SHADOW_NODE_IDS
}


# ── Node Count Detection ─────────────────────────────────────────────


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


# ── Manifest Loading ─────────────────────────────────────────────────


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
    Returns raw interval dicts preserving all original fields.
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

    return intervals


# ── Confidence Tagging ───────────────────────────────────────────────


def tag_confidence_level(
    best_sim: float,
    margin: float,
) -> str:
    """
    Tag the confidence level of a zone assignment.

    Returns:
        "high"   if sim > 0.3 and margin > 0.2
        "medium" if sim > 0.15 and margin > 0.1
        "low"    otherwise
    """
    if best_sim > 0.3 and margin > 0.2:
        return "high"
    elif best_sim > 0.15 and margin > 0.1:
        return "medium"
    else:
        return "low"


# ── Core Assignment Logic ────────────────────────────────────────────


def run_auto_zone_assignment(
    fingerprints: dict[str, ZoneFingerprint],
    feature_keys: list[str],
    unknown_intervals: list[dict],
    captures_dir: Path,
    window_sec: float = FEATURE_WINDOW_SEC,
    fingerprints_4node: dict[str, ZoneFingerprint] | None = None,
    feature_keys_4node: list[str] | None = None,
) -> list[dict]:
    """
    Assign zone labels to intervals with unknown zones.

    Groups intervals by session, loads CSI data once per session,
    extracts and normalizes features per-session, then finds the
    closest zone fingerprint for each interval.

    Args:
        fingerprints: Gold zone fingerprints (7-node).
        feature_keys: Canonical feature key ordering (7-node).
        unknown_intervals: List of raw manifest interval dicts with
            zone=unknown or zone="".
        captures_dir: Directory containing ndjson.gz capture files.
        window_sec: Feature extraction window size in seconds.
        fingerprints_4node: Gold zone fingerprints (4-node core only).
        feature_keys_4node: Feature key ordering for 4-node mode.

    Returns:
        List of assignment result dicts.
    """
    # Pre-compute normalization stats for both modes
    norm_stats_7 = compute_normalization_stats(fingerprints, feature_keys)
    norm_stats_4 = (
        compute_normalization_stats(fingerprints_4node, feature_keys_4node)
        if fingerprints_4node and feature_keys_4node
        else None
    )

    # Group intervals by session
    session_groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for idx, iv in enumerate(unknown_intervals):
        rec_label = iv.get("session_label", "") or iv.get("recording_label", "")
        if rec_label:
            session_groups[rec_label].append((idx, iv))

    all_assignments: list[dict] = []
    packets_cache: dict[str, list[dict]] = {}
    session_start_cache: dict[str, int] = {}
    total_sessions = len(session_groups)

    for sess_idx, (rec_label, iv_tuples) in enumerate(
        sorted(session_groups.items()), start=1
    ):
        t0 = time.time()
        logger.info(
            f"[{sess_idx}/{total_sessions}] Processing session '{rec_label}' "
            f"({len(iv_tuples)} unknown intervals)..."
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

        # ── Phase 1: Extract ALL windows for the entire session ──
        all_session_windows: list[tuple[int, list[dict[str, float]]]] = []

        for orig_idx, iv in iv_tuples:
            start_sec = float(iv.get("start_sec", 0))
            end_sec = float(iv.get("end_sec", 0))

            if packets and end_sec > start_sec:
                seg_features = extract_windows_for_segment(
                    packets, session_start_ns,
                    start_sec, end_sec,
                    window_sec,
                )
            else:
                seg_features = []

            all_session_windows.append((orig_idx, seg_features))

        # Collect all windows flat for normalization
        flat_windows: list[dict[str, float]] = []
        window_map: list[tuple[int, int]] = []  # (orig_idx, pos_in_flat)
        for orig_idx, wins in all_session_windows:
            for w in wins:
                window_map.append((orig_idx, len(flat_windows)))
                flat_windows.append(w)

        # Normalize across the entire session
        if flat_windows:
            normed_flat = normalize_session_features(flat_windows)
        else:
            normed_flat = []

        # Reassemble per-interval
        normed_per_interval: dict[int, list[dict[str, float]]] = defaultdict(list)
        for (orig_idx, _), nw in zip(window_map, normed_flat):
            normed_per_interval[orig_idx].append(nw)

        # ── Phase 2: Assign zone for each interval ──
        n_assigned = 0
        for orig_idx, iv in iv_tuples:
            start_sec = float(iv.get("start_sec", 0))
            end_sec = float(iv.get("end_sec", 0))
            original_zone = (iv.get("zone", "") or "").strip()

            seg_features = normed_per_interval.get(orig_idx, [])

            if not seg_features:
                assignment = {
                    "recording_label": rec_label,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "original_zone": original_zone,
                    "assigned_zone": None,
                    "confidence": 0.0,
                    "margin": 0.0,
                    "confidence_level": "none",
                    "all_similarities": {},
                    "n_csi_windows": 0,
                    "node_mode": mode_tag,
                    "zone_source": "csi_auto",
                    "skip_reason": "no CSI data available for segment time window",
                }
                all_assignments.append(assignment)
                continue

            # Average features across windows
            all_keys_set: set[str] = set()
            for feat in seg_features:
                all_keys_set.update(
                    k for k in feat.keys() if k != "_active_nodes"
                )

            avg_features: dict[str, float] = {}
            for key in all_keys_set:
                vals = [f.get(key, 0.0) for f in seg_features]
                avg_features[key] = float(sum(vals) / len(vals))

            feature_vec = np.array(
                [avg_features.get(k, 0.0) for k in sess_fk],
                dtype=np.float64,
            )

            closest_zone, best_sim, all_sims = find_closest_zone(
                feature_vec, sess_fp, sess_fk,
                norm_stats=sess_norm,
            )

            sorted_sims = sorted(all_sims.values(), reverse=True)
            margin = (
                (sorted_sims[0] - sorted_sims[1])
                if len(sorted_sims) >= 2
                else sorted_sims[0]
            )

            confidence_level = tag_confidence_level(best_sim, margin)
            n_assigned += 1

            assignment = {
                "recording_label": rec_label,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "original_zone": original_zone,
                "assigned_zone": closest_zone,
                "confidence": round(best_sim, 4),
                "margin": round(margin, 4),
                "confidence_level": confidence_level,
                "all_similarities": {
                    k: round(v, 4) for k, v in all_sims.items()
                },
                "n_csi_windows": len(seg_features),
                "node_mode": mode_tag,
                "zone_source": "csi_auto",
                "skip_reason": None,
            }
            all_assignments.append(assignment)

        elapsed = time.time() - t0
        logger.info(
            f"  -> {n_assigned} assigned, "
            f"{len(iv_tuples) - n_assigned} skipped (no CSI) "
            f"({elapsed:.1f}s)"
        )

    return all_assignments


# ── Output Serialization ─────────────────────────────────────────────


def save_outputs(
    assignments: list[dict],
    fingerprints: dict[str, ZoneFingerprint],
    manifest_path: Path,
    output_dir: Path,
) -> Path:
    """
    Save the auto zone assignment output JSON file.

    Returns:
        Path to the output file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Compute summary stats
    total = len(assignments)
    assigned = [a for a in assignments if a["assigned_zone"] is not None]
    skipped = [a for a in assignments if a["assigned_zone"] is None]

    # Per-zone counts
    zone_counts: dict[str, int] = defaultdict(int)
    zone_confidences: dict[str, list[float]] = defaultdict(list)
    confidence_level_counts: dict[str, int] = defaultdict(int)

    for a in assigned:
        zone = a["assigned_zone"]
        zone_counts[zone] += 1
        zone_confidences[zone].append(a["confidence"])
        confidence_level_counts[a["confidence_level"]] += 1

    per_zone_summary = {}
    for zone in sorted(zone_counts.keys()):
        confs = zone_confidences[zone]
        per_zone_summary[zone] = {
            "count": zone_counts[zone],
            "avg_confidence": round(float(np.mean(confs)), 4),
            "min_confidence": round(float(np.min(confs)), 4),
            "max_confidence": round(float(np.max(confs)), 4),
            "std_confidence": round(float(np.std(confs)), 4),
        }

    all_confs = [a["confidence"] for a in assigned]
    all_margins = [a["margin"] for a in assigned]

    doc = {
        "schema": "auto_zone_assignments_v1",
        "generated": now_iso,
        "manifest_source": str(manifest_path),
        "summary": {
            "total_unknown_intervals": total,
            "assigned": len(assigned),
            "skipped_no_csi": len(skipped),
            "assignment_rate": round(len(assigned) / max(total, 1), 4),
            "avg_confidence": round(
                float(np.mean(all_confs)), 4
            ) if all_confs else 0.0,
            "avg_margin": round(
                float(np.mean(all_margins)), 4
            ) if all_margins else 0.0,
            "confidence_levels": {
                "high": confidence_level_counts.get("high", 0),
                "medium": confidence_level_counts.get("medium", 0),
                "low": confidence_level_counts.get("low", 0),
            },
            "per_zone": per_zone_summary,
        },
        "gold_fingerprints": {
            zone: fp.to_dict() for zone, fp in sorted(fingerprints.items())
        },
        "assignments": assignments,
    }

    output_path = output_dir / "auto_zone_assignments_v1.json"
    with open(output_path, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    return output_path


# ── CLI Entrypoint ────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Auto Zone Assignment: assign zone labels to manifest intervals "
            "with zone=unknown using CSI fingerprint matching"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Uses gold zone fingerprints from dual validation to assign\n"
            "spatial zone labels (center, transition, door_passage_inside)\n"
            "to intervals that lack zone annotations.\n\n"
            "Output:\n"
            "  auto_zone_assignments_v1.json — per-interval assignments\n"
            "    with confidence scores and zone_source='csi_auto'"
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
    logging.info("Auto Zone Assignment Pipeline")
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
            "Cannot proceed with zone assignment."
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

    # ── Step 2: Load manifest and filter unknown-zone intervals ──
    logging.info(f"[2/4] Loading manifest intervals from {manifest_path.name}...")
    all_intervals = load_manifest_intervals(manifest_path)
    logging.info(f"  Loaded {len(all_intervals)} total intervals from manifest")

    # Filter to only unknown/empty zone intervals
    unknown_intervals = []
    for iv in all_intervals:
        zone = (iv.get("zone", "") or "").strip().lower()
        if zone in ("unknown", "", "unknown_handheld"):
            # Must have valid start/end
            start_sec = float(iv.get("start_sec", 0))
            end_sec = float(iv.get("end_sec", 0))
            if end_sec > start_sec:
                unknown_intervals.append(iv)

    logging.info(
        f"  Found {len(unknown_intervals)} intervals with zone=unknown or zone=''"
    )
    if not unknown_intervals:
        logging.info("No unknown-zone intervals to process. Nothing to do.")
        sys.exit(0)

    # Apply session filters
    if args.sessions:
        filtered = []
        for iv in unknown_intervals:
            rec_label = iv.get("session_label", "") or iv.get("recording_label", "")
            for s in args.sessions:
                if s == rec_label or s in rec_label:
                    filtered.append(iv)
                    break
        unknown_intervals = filtered
        logging.info(f"  After session filter: {len(unknown_intervals)} intervals")

    if args.limit:
        # Limit by number of unique sessions
        seen_sessions: set[str] = set()
        limited: list[dict] = []
        for iv in unknown_intervals:
            rec_label = iv.get("session_label", "") or iv.get("recording_label", "")
            seen_sessions.add(rec_label)
            if len(seen_sessions) <= args.limit:
                limited.append(iv)
        unknown_intervals = limited
        logging.info(
            f"  After limit: {len(unknown_intervals)} intervals "
            f"from {min(args.limit, len(seen_sessions))} sessions"
        )

    logging.info("")

    # ── Step 3: Run auto zone assignment ──
    logging.info(
        f"[3/4] Running auto zone assignment on {len(unknown_intervals)} intervals..."
    )
    t_start = time.time()

    assignments = run_auto_zone_assignment(
        fingerprints=fingerprints,
        feature_keys=feature_keys,
        unknown_intervals=unknown_intervals,
        captures_dir=captures_dir,
        window_sec=args.window_sec,
        fingerprints_4node=fingerprints_4node,
        feature_keys_4node=feature_keys_4node,
    )

    elapsed_total = time.time() - t_start
    logging.info(f"  Assignment completed in {elapsed_total:.1f}s")
    logging.info("")

    # ── Step 4: Save results ──
    logging.info("[4/4] Saving results...")
    output_path = save_outputs(
        assignments=assignments,
        fingerprints=fingerprints,
        manifest_path=manifest_path,
        output_dir=output_dir,
    )

    # ── Print summary ──
    assigned = [a for a in assignments if a["assigned_zone"] is not None]
    skipped = [a for a in assignments if a["assigned_zone"] is None]

    zone_counts: dict[str, int] = defaultdict(int)
    zone_confs: dict[str, list[float]] = defaultdict(list)
    conf_level_counts: dict[str, int] = defaultdict(int)

    for a in assigned:
        zone_counts[a["assigned_zone"]] += 1
        zone_confs[a["assigned_zone"]].append(a["confidence"])
        conf_level_counts[a["confidence_level"]] += 1

    logging.info("")
    logging.info("=" * 60)
    logging.info("RESULTS SUMMARY")
    logging.info("=" * 60)
    logging.info(f"  Total unknown intervals:  {len(assignments)}")
    logging.info(f"  Assigned:                 {len(assigned)}")
    logging.info(f"  Skipped (no CSI):         {len(skipped)}")
    logging.info(
        f"  Assignment rate:          "
        f"{len(assigned) / max(len(assignments), 1) * 100:.1f}%"
    )
    logging.info("")

    if assigned:
        all_confs = [a["confidence"] for a in assigned]
        all_margins = [a["margin"] for a in assigned]
        logging.info(f"  Avg confidence:  {np.mean(all_confs):.4f}")
        logging.info(f"  Avg margin:      {np.mean(all_margins):.4f}")
        logging.info("")
        logging.info("  Confidence levels:")
        logging.info(f"    High:    {conf_level_counts.get('high', 0)}")
        logging.info(f"    Medium:  {conf_level_counts.get('medium', 0)}")
        logging.info(f"    Low:     {conf_level_counts.get('low', 0)}")
        logging.info("")
        logging.info("  Per-zone assignments:")
        for zone in sorted(zone_counts.keys()):
            confs = zone_confs[zone]
            logging.info(
                f"    {zone:25s}: {zone_counts[zone]:4d} intervals  "
                f"(avg conf={np.mean(confs):.4f})"
            )

    logging.info("")
    logging.info(f"Output saved to: {output_path}")


if __name__ == "__main__":
    main()
