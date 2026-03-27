#!/usr/bin/env python3
"""
CLI runner for the Dual Validation Service.

Validates video-annotated segments against CSI signal fingerprints.
Video is the PRIMARY truth source; CSI provides cross-validation.

Usage:
    python v1/scripts/run_dual_validation.py \
        --gold-dir output/garage_guided_review_dense1 \
        --captures-dir temp/captures \
        --output-dir output/dual_validation

    # With custom window size:
    python v1/scripts/run_dual_validation.py \
        --gold-dir output/garage_guided_review_dense1 \
        --captures-dir temp/captures \
        --output-dir output/dual_validation \
        --window-sec 3.0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on the Python path
PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from v1.src.services.dual_validation_service import DualValidationService


def main():
    parser = argparse.ArgumentParser(
        description="Dual Validation: video annotations vs CSI signal fingerprints",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Video is the PRIMARY truth source. CSI provides cross-validation.\n"
            "Conflicts are always recorded, never masked."
        ),
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        required=True,
        help=(
            "Directory containing gold-standard annotations "
            "(manual_annotations_v1.json files, searched recursively)"
        ),
    )
    parser.add_argument(
        "--captures-dir",
        type=Path,
        required=True,
        help="Directory containing CSI capture files (ndjson.gz)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for validated_segments.json and conflicts.json",
    )
    parser.add_argument(
        "--window-sec",
        type=float,
        default=2.0,
        help="Feature extraction window size in seconds (default: 2.0)",
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

    # Validate inputs
    if not gold_dir.exists():
        logging.error(f"Gold directory does not exist: {gold_dir}")
        sys.exit(1)
    if not captures_dir.exists():
        logging.error(f"Captures directory does not exist: {captures_dir}")
        sys.exit(1)

    # Run the pipeline
    logging.info("=" * 60)
    logging.info("Dual Validation Pipeline")
    logging.info("=" * 60)
    logging.info(f"  Gold dir:     {gold_dir}")
    logging.info(f"  Captures dir: {captures_dir}")
    logging.info(f"  Output dir:   {output_dir}")
    logging.info(f"  Window size:  {args.window_sec}s")
    logging.info("")

    svc = DualValidationService(
        gold_dir=gold_dir,
        captures_dir=captures_dir,
        feature_window_sec=args.window_sec,
    )

    # Step 1: Load gold annotations
    logging.info("[1/4] Loading gold annotations...")
    n_gold = svc.load_gold_annotations()
    if n_gold == 0:
        logging.error("No gold annotations found. Check --gold-dir path.")
        sys.exit(1)

    # Step 2: Load capture data
    logging.info("[2/4] Loading CSI capture data...")
    n_captures = svc.load_capture_data()
    if n_captures == 0:
        logging.warning(
            "No matching capture data found. Segments will have 'ambiguous' status. "
            "Check that --captures-dir contains ndjson.gz files matching the "
            "recording labels in the gold annotations."
        )

    # Step 3: Build zone fingerprints
    logging.info("[3/4] Building zone fingerprints from gold data...")
    fingerprints = svc.build_zone_fingerprints()
    if not fingerprints:
        logging.warning(
            "No zone fingerprints could be built. "
            "This may happen if no CSI data overlaps with gold annotations."
        )

    # Step 4: Validate all segments
    logging.info("[4/4] Validating segments...")
    results = svc.validate_all()

    # Save results
    validated_path, conflicts_path = svc.save_results(output_dir)

    # Print summary
    validated_doc, conflicts_doc = svc.get_output_bundle()
    summary = validated_doc["summary"]

    logging.info("")
    logging.info("=" * 60)
    logging.info("RESULTS SUMMARY")
    logging.info("=" * 60)
    logging.info(f"  Total segments:  {summary['total']}")
    logging.info(f"  Validated:       {summary['validated']}")
    logging.info(f"  Conflicts:       {summary['conflict']}")
    logging.info(f"  Ambiguous:       {summary['ambiguous']}")
    logging.info("")

    if fingerprints:
        logging.info("Zone fingerprints:")
        for zone_name, fp in sorted(fingerprints.items()):
            logging.info(f"  {zone_name}: {fp.n_windows} windows")

    if conflicts_doc["conflicts"]:
        logging.info("")
        logging.info(f"CONFLICTS ({len(conflicts_doc['conflicts'])}):")
        for c in conflicts_doc["conflicts"]:
            logging.info(
                f"  [{c['id']}] {c['recording_label']} "
                f"[{c['start_sec']:.0f}-{c['end_sec']:.0f}s]: "
                f"{c['conflict_reason']}"
            )

    logging.info("")
    logging.info(f"Output saved to: {output_dir}")
    logging.info(f"  - {validated_path.name}")
    logging.info(f"  - {conflicts_path.name}")


if __name__ == "__main__":
    main()
