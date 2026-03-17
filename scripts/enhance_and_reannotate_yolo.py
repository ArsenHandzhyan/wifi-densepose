#!/Users/arsen/Desktop/wifi-densepose/venv/bin/python3
"""
Enhanced YOLO re-annotation pipeline for low-light garage keyframes.

Iterates all keyframe directories in output/keyframes/, applies low-light
enhancement (gamma + CLAHE + denoising), runs YOLOv8n on both original and
enhanced frames, and saves per-clip CSV annotations with motion scoring.
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEYFRAMES_DIR = PROJECT_ROOT / "output" / "keyframes"
MANIFEST_PATH = KEYFRAMES_DIR / "manifest.json"
OUTPUT_CSV_DIR = PROJECT_ROOT / "temp" / "video_teacher"
SUMMARY_PATH = PROJECT_ROOT / "output" / "enhanced_yolo_summary.json"


def enhance_low_light(img: np.ndarray) -> np.ndarray:
    """Enhance a low-light BGR image via gamma correction, CLAHE, and denoising."""
    # Step 1: Gamma correction (brighten dark areas)
    gamma = 0.3
    table = np.array(
        [(i / 255.0) ** (1.0 / gamma) * 255 for i in range(256)]
    ).astype("uint8")
    bright = cv2.LUT(img, table)

    # Step 2: CLAHE on L channel
    lab = cv2.cvtColor(bright, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    # Step 3: Light denoising
    enhanced = cv2.fastNlMeansDenoisingColored(enhanced, None, 8, 8, 7, 21)
    return enhanced


def detect_persons(model, img: np.ndarray, conf: float = 0.15):
    """Run YOLOv8 person detection. Returns (person_count, max_confidence)."""
    results = model(img, conf=conf, classes=[0], verbose=False)
    boxes = results[0].boxes
    if len(boxes) == 0:
        return 0, 0.0
    confs = boxes.conf.cpu().numpy()
    return int(len(confs)), float(confs.max())


def compute_motion_score(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """Compute normalized mean absolute difference between consecutive frames."""
    if prev_gray is None:
        return 0.0
    diff = cv2.absdiff(prev_gray, curr_gray)
    return float(diff.mean() / 255.0)


def discover_clip_dirs() -> list[tuple[str, Path, list[float]]]:
    """
    Discover all clip directories and their frame timestamps.
    Returns list of (clip_name, clip_dir, timestamps).
    """
    clips = []

    # Use manifest for timestamp info when available
    timestamps_map: dict[str, list[float]] = {}
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        for video in manifest.get("videos", []):
            label = video.get("label", "")
            ts = video.get("frame_timestamps", [])
            timestamps_map[label] = ts

    # Scan for actual directories with frames
    if not KEYFRAMES_DIR.exists():
        print(f"ERROR: Keyframes directory not found: {KEYFRAMES_DIR}")
        sys.exit(1)

    for entry in sorted(KEYFRAMES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        frames = sorted(entry.glob("frame_*.jpg"))
        if not frames:
            continue
        clip_name = entry.name
        # Get timestamps from manifest, or synthesize at 10s intervals
        ts = timestamps_map.get(clip_name, [i * 10.0 for i in range(len(frames))])
        # Ensure timestamp list matches frame count
        while len(ts) < len(frames):
            ts.append(ts[-1] + 10.0 if ts else len(ts) * 10.0)
        clips.append((clip_name, entry, ts))

    return clips


def process_clip(
    model, clip_name: str, clip_dir: Path, timestamps: list[float]
) -> dict:
    """
    Process a single clip: enhance frames, run YOLO, compute motion, save CSV.
    Returns per-clip stats dict.
    """
    frames = sorted(clip_dir.glob("frame_*.jpg"))
    if not frames:
        return {"total": 0, "original_person": 0, "enhanced_person": 0}

    # Ensure timestamps cover all frames
    while len(timestamps) < len(frames):
        timestamps.append(timestamps[-1] + 10.0 if timestamps else 0.0)

    csv_path = OUTPUT_CSV_DIR / f"{clip_name}.enhanced_yolo.csv"
    rows = []
    prev_gray = None
    original_person_frames = 0
    enhanced_person_frames = 0
    best_person_frames = 0

    for i, frame_path in enumerate(frames):
        img = cv2.imread(str(frame_path))
        if img is None:
            # Handle missing/corrupt frame
            rows.append(
                {
                    "timestamp_sec": timestamps[i],
                    "person_count_original": 0,
                    "person_count_enhanced": 0,
                    "person_count_best": 0,
                    "motion_state": "empty",
                    "confidence_max": 0.0,
                    "motion_score": 0.0,
                }
            )
            continue

        # Enhance
        enhanced = enhance_low_light(img)

        # YOLO on both
        orig_count, orig_conf = detect_persons(model, img)
        enh_count, enh_conf = detect_persons(model, enhanced)

        best_count = max(orig_count, enh_count)
        max_conf = max(orig_conf, enh_conf)

        # Motion score
        curr_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        motion_score = compute_motion_score(prev_gray, curr_gray)
        prev_gray = curr_gray

        # Motion state
        if best_count == 0:
            motion_state = "empty"
        elif motion_score < 0.02:
            motion_state = "static"
        else:
            motion_state = "walking"

        if orig_count > 0:
            original_person_frames += 1
        if enh_count > 0:
            enhanced_person_frames += 1
        if best_count > 0:
            best_person_frames += 1

        rows.append(
            {
                "timestamp_sec": round(timestamps[i], 2),
                "person_count_original": orig_count,
                "person_count_enhanced": enh_count,
                "person_count_best": best_count,
                "motion_state": motion_state,
                "confidence_max": round(max_conf, 4),
                "motion_score": round(motion_score, 6),
            }
        )

    # Write CSV
    fieldnames = [
        "timestamp_sec",
        "person_count_original",
        "person_count_enhanced",
        "person_count_best",
        "motion_state",
        "confidence_max",
        "motion_score",
    ]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "total": len(frames),
        "original_person": original_person_frames,
        "enhanced_person": enhanced_person_frames,
        "best_person": best_person_frames,
        "csv_path": str(csv_path),
    }


def main():
    print("=" * 70)
    print("Enhanced YOLO Re-Annotation Pipeline")
    print("=" * 70)

    # Ensure output directory exists
    OUTPUT_CSV_DIR.mkdir(parents=True, exist_ok=True)

    # Discover clips
    clips = discover_clip_dirs()
    total_frames = sum(len(list(d.glob("frame_*.jpg"))) for _, d, _ in clips)
    print(f"\nFound {len(clips)} clip directories with {total_frames} total frames")

    if not clips:
        print("ERROR: No keyframe directories found. Nothing to process.")
        sys.exit(1)

    # Load YOLO model once
    print("\nLoading YOLOv8n model...")
    t0 = time.time()
    from ultralytics import YOLO

    model = YOLO("yolov8n.pt")
    print(f"Model loaded in {time.time() - t0:.1f}s")

    # Process all clips
    print(f"\nProcessing {len(clips)} clips...\n")
    t_start = time.time()
    per_clip_stats = {}
    total_original = 0
    total_enhanced = 0
    total_best = 0
    total_count = 0

    for idx, (clip_name, clip_dir, timestamps) in enumerate(clips):
        stats = process_clip(model, clip_name, clip_dir, timestamps)
        per_clip_stats[clip_name] = stats

        total_count += stats["total"]
        total_original += stats["original_person"]
        total_enhanced += stats["enhanced_person"]
        total_best += stats.get("best_person", 0)

        # Print per-clip comparison
        n = stats["total"]
        o = stats["original_person"]
        e = stats["enhanced_person"]
        if n > 0:
            o_pct = 100.0 * o / n
            e_pct = 100.0 * e / n
            diff = e - o
            diff_pct = e_pct - o_pct
            sign = "+" if diff >= 0 else ""
            print(
                f"Clip: {clip_name[:50]:50s}  "
                f"Orig: {o:3d}/{n:3d} ({o_pct:5.1f}%)  "
                f"Enh: {e:3d}/{n:3d} ({e_pct:5.1f}%)  "
                f"Diff: {sign}{diff} ({sign}{diff_pct:.1f}%)"
            )

        # Progress every 10 clips
        if (idx + 1) % 10 == 0:
            elapsed = time.time() - t_start
            print(
                f"  --- Progress: {idx + 1}/{len(clips)} clips, "
                f"{elapsed:.0f}s elapsed ---"
            )

    elapsed_total = time.time() - t_start

    # Print overall summary
    print("\n" + "=" * 70)
    print("OVERALL SUMMARY")
    print("=" * 70)
    print(f"Total clips processed:      {len(clips)}")
    print(f"Total frames processed:     {total_count}")
    print(f"Original YOLO person frames: {total_original} "
          f"({100.0 * total_original / max(total_count, 1):.1f}%)")
    print(f"Enhanced YOLO person frames: {total_enhanced} "
          f"({100.0 * total_enhanced / max(total_count, 1):.1f}%)")
    print(f"Best (max) person frames:    {total_best} "
          f"({100.0 * total_best / max(total_count, 1):.1f}%)")
    improvement = total_enhanced - total_original
    imp_pct = 100.0 * improvement / max(total_count, 1)
    sign = "+" if improvement >= 0 else ""
    print(f"Improvement (enhanced-orig): {sign}{improvement} frames "
          f"({sign}{imp_pct:.1f}%)")
    print(f"Total runtime:              {elapsed_total:.1f}s")

    # Save summary JSON
    summary = {
        "total_frames": total_count,
        "total_clips": len(clips),
        "original_person_frames": total_original,
        "enhanced_person_frames": total_enhanced,
        "best_person_frames": total_best,
        "improvement_frames": improvement,
        "improvement_pct": round(imp_pct, 2),
        "runtime_sec": round(elapsed_total, 1),
        "per_clip": {
            name: {
                "total_frames": s["total"],
                "original_person_frames": s["original_person"],
                "enhanced_person_frames": s["enhanced_person"],
                "best_person_frames": s.get("best_person", 0),
            }
            for name, s in per_clip_stats.items()
        },
    }

    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to: {SUMMARY_PATH}")
    print(f"CSVs saved to:    {OUTPUT_CSV_DIR}/")


if __name__ == "__main__":
    main()
