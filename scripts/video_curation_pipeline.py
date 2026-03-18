#!/usr/bin/env python3
"""
Video Curation Pipeline v1 — Quality review, auto-segmentation, label tiers, synthetic expansion.

Designed for the WiFi DensePose project's offline video teacher workflow.
Processes .teacher.mp4 files from temp/captures/, computes per-5s-window features
(brightness, frame_diff, optical_flow), classifies segments, and exports a structured
label manifest compatible with the CSI motion pipeline.

Usage:
    # Full pipeline on all teacher videos
    python scripts/video_curation_pipeline.py

    # Limit to first N videos
    python scripts/video_curation_pipeline.py --limit 10

    # Include synthetic expansion
    python scripts/video_curation_pipeline.py --synthetic

    # Dry run (no output written)
    python scripts/video_curation_pipeline.py --dry-run

    # Specific clip
    python scripts/video_curation_pipeline.py --clip longcap_chunk0001_20260318_143115
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAPTURES_DIR = PROJECT_ROOT / "temp" / "captures"
VIDEO_TEACHER_DIR = PROJECT_ROOT / "temp" / "video_teacher"
OUTPUT_DIR = PROJECT_ROOT / "output" / "video_curation"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WINDOW_SEC = 5  # Must match CSI feature extraction window
FPS_SAMPLE = 2  # Frames per second to sample (for speed — not every frame)

# Brightness thresholds (0-255 grayscale mean)
BRIGHTNESS_DARK = 25       # Below this = too dark for reliable YOLO
BRIGHTNESS_USABLE = 40     # Above this = usable for auto-annotation

# Frame diff thresholds (normalized 0-1)
# Candidate v1 frozen after full-corpus pass on 2026-03-18:
#   EMPTY:  frame_diff < 0.003 and flow < 0.03
#   STATIC: frame_diff in [0.003, 0.007) and flow in [0.03, 0.08)
#   MOTION: frame_diff > 0.007 or flow > 0.08
FDIFF_EMPTY_MAX = 0.003
FDIFF_STATIC_MAX = 0.007
FDIFF_MOTION_MIN = 0.007

# Optical flow thresholds (mean magnitude in pixels)
FLOW_EMPTY_MAX = 0.03
FLOW_STATIC_MAX = 0.08
FLOW_MOTION_MIN = 0.08

THRESHOLDS_CANDIDATE_V1 = {
    "frame_diff": {
        "empty_lt": FDIFF_EMPTY_MAX,
        "static_gte": FDIFF_EMPTY_MAX,
        "static_lt": FDIFF_STATIC_MAX,
        "motion_gt": FDIFF_MOTION_MIN,
    },
    "flow": {
        "empty_lt": FLOW_EMPTY_MAX,
        "static_gte": FLOW_EMPTY_MAX,
        "static_lt": FLOW_STATIC_MAX,
        "motion_gt": FLOW_MOTION_MIN,
    },
}

# EMPTY boundary guard — narrow post-label mitigation only.
EMPTY_BOUNDARY_FDIFF_GUARD_MIN = 0.0024
EMPTY_BOUNDARY_FLOW_GUARD_MIN = 0.024
EMPTY_BOUNDARY_OCCUPIED_STATIC_MARKERS = (
    "four_person",
    "standing_still",
    "stand_",
    "_stand",
    "breath",
    "sit",
    "lie",
    "kneel",
    "squat",
    "static_test",
    "static_deep",
)


# ---------------------------------------------------------------------------
# Label tiers
# ---------------------------------------------------------------------------
LABEL_TIERS = {
    "human_verified": 1.0,
    "strong_teacher": 0.85,
    "weak_auto": 0.5,
    "synthetic": 0.3,
    "reject": 0.0,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class VideoQuality:
    path: str
    readable: bool = False
    duration_sec: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    brightness_mean: float = 0.0
    brightness_std: float = 0.0
    quality_class: str = "unknown"  # good, dark, corrupt, too_short
    error: str = ""


@dataclass
class WindowFeatures:
    window_start_sec: float = 0.0
    window_end_sec: float = 0.0
    brightness_mean: float = 0.0
    brightness_std: float = 0.0
    frame_diff_energy: float = 0.0
    frame_diff_std: float = 0.0
    flow_magnitude_mean: float = 0.0
    flow_magnitude_std: float = 0.0
    n_frames_sampled: int = 0


@dataclass
class WindowLabel:
    clip_id: str = ""
    window_start_sec: float = 0.0
    window_end_sec: float = 0.0
    label: str = ""  # EMPTY, STATIC, MOTION, ENTRY_EXIT
    label_tier: str = ""
    confidence: float = 0.0
    source_video: str = ""
    source_csi: str = ""
    synthetic: bool = False
    synthetic_method: str | None = None
    brightness_mean: float = 0.0
    frame_diff_energy: float = 0.0
    flow_magnitude_mean: float = 0.0
    yolo_person_count: int | None = None
    segment_class: str = ""  # CLEAR_EMPTY, CLEAR_MOTION, CLEAR_STATIC, AMBIGUOUS, REJECT
    provenance: str = "auto_pipeline_v1"
    notes: str = ""


# ---------------------------------------------------------------------------
# Video probing
# ---------------------------------------------------------------------------
def probe_video(video_path: Path) -> VideoQuality:
    """Probe a video file for quality metrics using ffprobe and OpenCV."""
    vq = VideoQuality(path=str(video_path))

    # Check readability with ffprobe
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration:stream=width,height,r_frame_rate,codec_name",
                "-of", "json",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            vq.quality_class = "corrupt"
            vq.error = "ffprobe failed"
            return vq

        info = json.loads(result.stdout)
        fmt = info.get("format", {})
        streams = info.get("streams", [])

        vq.duration_sec = float(fmt.get("duration", 0))
        vq.readable = True

        for s in streams:
            if s.get("codec_name") in ("h264", "h265", "hevc", "vp8", "vp9", "av1", "mpeg4"):
                vq.width = int(s.get("width", 0))
                vq.height = int(s.get("height", 0))
                rfr = s.get("r_frame_rate", "30/1")
                if "/" in str(rfr):
                    num, den = str(rfr).split("/")
                    vq.fps = float(num) / max(1, float(den))
                else:
                    vq.fps = float(rfr)
                break

    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as e:
        vq.quality_class = "corrupt"
        vq.error = str(e)
        return vq

    if vq.duration_sec < 3.0:
        vq.quality_class = "too_short"
        return vq

    # Sample a few frames for brightness
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        vq.quality_class = "corrupt"
        vq.error = "cv2.VideoCapture failed"
        return vq

    brightness_samples = []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_indices = np.linspace(0, max(1, total_frames - 1), min(20, total_frames), dtype=int)

    for idx in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ret, frame = cap.read()
        if ret and frame is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness_samples.append(float(gray.mean()))

    cap.release()

    if brightness_samples:
        vq.brightness_mean = float(np.mean(brightness_samples))
        vq.brightness_std = float(np.std(brightness_samples))

    # Classify
    if vq.brightness_mean < BRIGHTNESS_DARK:
        vq.quality_class = "dark"
    else:
        vq.quality_class = "good"

    return vq


# ---------------------------------------------------------------------------
# Window feature extraction
# ---------------------------------------------------------------------------
def extract_window_features(video_path: Path, window_start: float, window_end: float) -> WindowFeatures:
    """Extract brightness, frame_diff, and optical flow features for a time window."""
    wf = WindowFeatures(window_start_sec=window_start, window_end_sec=window_end)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return wf

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start_frame = int(window_start * fps)
    end_frame = int(window_end * fps)

    # Sample frames within window
    n_samples = max(2, int((window_end - window_start) * FPS_SAMPLE))
    sample_frames = np.linspace(start_frame, max(start_frame + 1, end_frame - 1), n_samples, dtype=int)

    brightness_vals = []
    frame_diffs = []
    flow_mags = []
    prev_gray = None

    for frame_idx in sample_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_idx))
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Downsample for speed
        small_gray = cv2.resize(gray, (160, 120))

        brightness_vals.append(float(small_gray.mean()))

        if prev_gray is not None:
            # Frame difference
            diff = cv2.absdiff(small_gray, prev_gray)
            frame_diffs.append(float(diff.mean()) / 255.0)

            # Optical flow (Farneback)
            try:
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, small_gray, None,
                    pyr_scale=0.5, levels=2, winsize=11,
                    iterations=2, poly_n=5, poly_sigma=1.1,
                    flags=0,
                )
                mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
                flow_mags.append(float(mag.mean()))
            except cv2.error:
                pass

        prev_gray = small_gray
        wf.n_frames_sampled += 1

    cap.release()

    if brightness_vals:
        wf.brightness_mean = float(np.mean(brightness_vals))
        wf.brightness_std = float(np.std(brightness_vals))
    if frame_diffs:
        wf.frame_diff_energy = float(np.mean(frame_diffs))
        wf.frame_diff_std = float(np.std(frame_diffs))
    if flow_mags:
        wf.flow_magnitude_mean = float(np.mean(flow_mags))
        wf.flow_magnitude_std = float(np.std(flow_mags))

    return wf


# ---------------------------------------------------------------------------
# Segment classification
# ---------------------------------------------------------------------------
def classify_segment(wf: WindowFeatures) -> tuple[str, str, float]:
    """
    Classify a window into segment class and auto-label.

    Returns: (segment_class, label, confidence)
      segment_class: CLEAR_EMPTY, CLEAR_STATIC, CLEAR_MOTION, AMBIGUOUS, REJECT
      label: EMPTY, STATIC, MOTION
      confidence: 0.0-1.0
    """
    # Reject very dark windows
    if wf.brightness_mean < BRIGHTNESS_DARK and wf.n_frames_sampled > 0:
        # Even in dark, very low frame diff = likely empty
        if wf.frame_diff_energy < FDIFF_EMPTY_MAX:
            return "REJECT", "EMPTY", 0.3
        return "REJECT", "UNKNOWN", 0.0

    # Insufficient frames
    if wf.n_frames_sampled < 2:
        return "REJECT", "UNKNOWN", 0.0

    # Clear empty: very low frame diff AND very low flow
    if wf.frame_diff_energy < FDIFF_EMPTY_MAX and wf.flow_magnitude_mean < FLOW_EMPTY_MAX:
        conf = min(0.95, 0.7 + 0.25 * (1.0 - wf.frame_diff_energy / max(FDIFF_EMPTY_MAX, 1e-6)))
        return "CLEAR_EMPTY", "EMPTY", conf

    # Clear motion: high frame diff OR high flow (changed from AND — both are valid signals)
    if wf.frame_diff_energy > FDIFF_MOTION_MIN or wf.flow_magnitude_mean > FLOW_MOTION_MIN:
        both = wf.frame_diff_energy > FDIFF_MOTION_MIN and wf.flow_magnitude_mean > FLOW_MOTION_MIN
        conf = min(0.95, 0.8 if both else 0.7)
        return "CLEAR_MOTION", "MOTION", conf

    # Clear static: low-to-moderate frame diff and low-to-moderate flow, but NOT empty-level
    if (
        FDIFF_EMPTY_MAX <= wf.frame_diff_energy < FDIFF_STATIC_MAX
        and FLOW_EMPTY_MAX <= wf.flow_magnitude_mean < FLOW_STATIC_MAX
    ):
        conf = 0.6  # Static is the hardest to distinguish
        return "CLEAR_STATIC", "STATIC", conf

    # Moderate frame diff zone — between static and motion thresholds
    if FDIFF_STATIC_MAX <= wf.frame_diff_energy <= FDIFF_MOTION_MIN:
        # Use flow as tiebreaker
        if wf.flow_magnitude_mean > FLOW_MOTION_MIN:
            return "CLEAR_MOTION", "MOTION", 0.65
        elif wf.flow_magnitude_mean < FLOW_STATIC_MAX:
            return "AMBIGUOUS", "STATIC", 0.4
        else:
            return "AMBIGUOUS", "UNKNOWN", 0.3

    return "AMBIGUOUS", "UNKNOWN", 0.3


def clip_has_occupied_static_marker(clip_id: str) -> bool:
    clip_id = clip_id.lower()
    return any(token in clip_id for token in EMPTY_BOUNDARY_OCCUPIED_STATIC_MARKERS)


def should_downgrade_empty_boundary(
    clip_id: str,
    final_label: str,
    segment_class: str,
    frame_diff_energy: float,
    flow_magnitude_mean: float,
    yolo_person_count: int | None,
) -> bool:
    """Guard against ultra-static occupied scenes leaking into clean EMPTY."""
    if final_label != "EMPTY" or segment_class != "CLEAR_EMPTY":
        return False

    if yolo_person_count is not None and yolo_person_count > 0:
        return True

    if clip_has_occupied_static_marker(clip_id):
        return (
            frame_diff_energy >= EMPTY_BOUNDARY_FDIFF_GUARD_MIN
            or flow_magnitude_mean >= EMPTY_BOUNDARY_FLOW_GUARD_MIN
        )

    return False


def assign_label_tier(segment_class: str, brightness: float, has_yolo: bool = False) -> str:
    """Assign a label tier based on segment clarity and evidence quality."""
    if segment_class.startswith("CLEAR_") and brightness >= BRIGHTNESS_USABLE:
        if has_yolo:
            return "strong_teacher"
        return "strong_teacher"  # frame_diff + flow agreement is strong enough

    if segment_class.startswith("CLEAR_") and brightness >= BRIGHTNESS_DARK:
        return "weak_auto"

    if segment_class == "AMBIGUOUS":
        return "weak_auto"

    return "reject"


# ---------------------------------------------------------------------------
# YOLO integration (optional)
# ---------------------------------------------------------------------------
def try_load_yolo_annotations(clip_id: str) -> dict[float, int] | None:
    """
    Try to load existing YOLO annotations for a clip.
    Returns {timestamp_sec: person_count} or None.
    """
    csv_path = VIDEO_TEACHER_DIR / f"{clip_id}.yolo_annotations.csv"
    if not csv_path.exists():
        return None

    import csv
    result = {}
    try:
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = float(row.get("timestamp_sec", 0))
                count = int(row.get("person_count", row.get("yolo_person_count", 0)))
                result[ts] = count
    except Exception:
        return None

    return result if result else None


def get_yolo_count_for_window(yolo_data: dict[float, int] | None, start: float, end: float) -> int | None:
    """Get average YOLO person count for a time window."""
    if yolo_data is None:
        return None

    counts = []
    for ts, count in yolo_data.items():
        if start <= ts < end:
            counts.append(count)

    if not counts:
        return None
    return int(round(np.mean(counts)))


# ---------------------------------------------------------------------------
# Visual annotations integration
# ---------------------------------------------------------------------------
def try_load_visual_annotations(clip_id: str) -> list[tuple[float, float, int, str]] | None:
    """Try to load human visual annotations from visual_annotations_v22."""
    try:
        # Import the module
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from visual_annotations_v22 import VISUAL_ANNOTATIONS
        if clip_id in VISUAL_ANNOTATIONS:
            return VISUAL_ANNOTATIONS[clip_id]
    except ImportError:
        pass
    return None


def get_visual_label_for_window(
    annotations: list[tuple[float, float, int, str]] | None,
    start: float, end: float,
) -> tuple[str, int] | None:
    """Get human-verified label for a window. Returns (motion_type, person_count) or None."""
    if annotations is None:
        return None

    center = (start + end) / 2.0
    for seg_start, seg_end, count, motion in annotations:
        if seg_start <= center < seg_end:
            return (motion, count)
    return None


# ---------------------------------------------------------------------------
# Synthetic expansion
# ---------------------------------------------------------------------------
def generate_synthetic_variants(
    label: WindowLabel,
    video_path: Path,
    n_variants: int = 2,
) -> list[WindowLabel]:
    """
    Generate synthetic variants of a labeled window.
    Only safe operations that preserve semantic meaning.
    """
    variants = []
    duration = label.window_end_sec - label.window_start_sec

    for i in range(n_variants):
        method = random.choice(["temporal_crop", "speed_perturbation"])
        variant = WindowLabel(**{k: v for k, v in asdict(label).items()})
        variant.synthetic = True
        variant.label_tier = "synthetic"
        variant.confidence = min(label.confidence * 0.6, 0.3)
        variant.provenance = "synthetic_pipeline_v1"

        if method == "temporal_crop":
            # Shift window by +-0.5 to +-1.5 seconds
            shift = random.uniform(-1.5, 1.5)
            new_start = max(0, label.window_start_sec + shift)
            new_end = new_start + duration
            variant.window_start_sec = round(new_start, 2)
            variant.window_end_sec = round(new_end, 2)
            variant.synthetic_method = f"temporal_crop:shift={shift:.2f}s"

        elif method == "speed_perturbation":
            # Conceptual: note that actual playback speed change would need
            # to re-extract features. Here we simulate by stretching the window.
            speed = random.uniform(0.85, 1.15)
            new_duration = duration / speed
            variant.window_end_sec = round(variant.window_start_sec + new_duration, 2)
            variant.synthetic_method = f"speed_perturbation:factor={speed:.2f}"

        variant.notes = f"synthetic from {label.clip_id}@{label.window_start_sec}s"
        variants.append(variant)

    return variants


# ---------------------------------------------------------------------------
# Entry/exit transition detection
# ---------------------------------------------------------------------------
def detect_entry_exit_transitions(
    windows: list[tuple[WindowFeatures, str, str, float]],
) -> list[int]:
    """
    Detect windows that likely contain entry/exit events.
    Look for sharp jumps in frame_diff_energy between adjacent windows.

    Returns list of window indices where transitions occur.
    """
    transitions = []
    for i in range(1, len(windows)):
        prev_fdiff = windows[i - 1][0].frame_diff_energy
        curr_fdiff = windows[i][0].frame_diff_energy
        prev_label = windows[i - 1][2]
        curr_label = windows[i][2]

        # Transition: label changed AND significant energy jump
        if prev_label != curr_label and prev_label != "UNKNOWN" and curr_label != "UNKNOWN":
            ratio = max(curr_fdiff, 1e-6) / max(prev_fdiff, 1e-6)
            if ratio > 3.0 or ratio < 0.33:
                transitions.append(i)

    return transitions


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def process_clip(
    video_path: Path,
    include_synthetic: bool = False,
) -> tuple[VideoQuality, list[WindowLabel]]:
    """Process a single clip through the full pipeline."""
    clip_id = video_path.stem.replace(".teacher", "")

    # Step 1: Quality check
    vq = probe_video(video_path)
    if not vq.readable or vq.quality_class == "corrupt":
        return vq, []

    # Step 2: Load existing annotations
    yolo_data = try_load_yolo_annotations(clip_id)
    visual_annotations = try_load_visual_annotations(clip_id)

    # Step 3: CSI file lookup
    csi_path = CAPTURES_DIR / f"{clip_id}.ndjson.gz"
    csi_str = str(csi_path) if csi_path.exists() else ""

    # Step 4: Extract features for each 5-second window
    n_windows = max(1, int(vq.duration_sec / WINDOW_SEC))
    window_data: list[tuple[WindowFeatures, str, str, float]] = []

    for w in range(n_windows):
        start = w * WINDOW_SEC
        end = min(start + WINDOW_SEC, vq.duration_sec)
        if end - start < 2.0:
            break

        wf = extract_window_features(video_path, start, end)
        seg_class, auto_label, auto_conf = classify_segment(wf)
        window_data.append((wf, seg_class, auto_label, auto_conf))

    # Step 5: Detect entry/exit transitions
    transitions = detect_entry_exit_transitions(window_data)

    # Step 6: Build final labels
    labels: list[WindowLabel] = []
    for idx, (wf, seg_class, auto_label, auto_conf) in enumerate(window_data):
        start = idx * WINDOW_SEC
        end = min(start + WINDOW_SEC, vq.duration_sec)

        # Check human annotations first (highest tier)
        visual = get_visual_label_for_window(visual_annotations, start, end)
        yolo_count = get_yolo_count_for_window(yolo_data, start, end)

        # Determine final label
        if visual is not None:
            motion_type, person_count = visual
            if motion_type == "empty":
                final_label = "EMPTY"
            elif motion_type == "walking":
                final_label = "MOTION"
            else:
                final_label = "STATIC"
            tier = "human_verified"
            confidence = 1.0
        else:
            final_label = auto_label
            tier = assign_label_tier(seg_class, wf.brightness_mean, has_yolo=yolo_data is not None)

            # Boost confidence if YOLO agrees
            confidence = auto_conf
            if yolo_count is not None:
                if yolo_count == 0 and final_label == "EMPTY":
                    confidence = min(0.95, confidence + 0.15)
                    if tier == "weak_auto":
                        tier = "strong_teacher"
                elif yolo_count > 0 and final_label in ("STATIC", "MOTION"):
                    confidence = min(0.90, confidence + 0.10)
                elif yolo_count == 0 and final_label in ("STATIC", "MOTION"):
                    # Disagreement — YOLO says empty but frame_diff says occupied
                    confidence = max(0.2, confidence - 0.2)
                    tier = "weak_auto"

        # Mark entry/exit transitions
        if idx in transitions:
            final_label = "ENTRY_EXIT" if final_label != "EMPTY" else final_label
            confidence = min(confidence, 0.7)

        notes = ""
        if visual is None and should_downgrade_empty_boundary(
            clip_id=clip_id,
            final_label=final_label,
            segment_class=seg_class,
            frame_diff_energy=wf.frame_diff_energy,
            flow_magnitude_mean=wf.flow_magnitude_mean,
            yolo_person_count=yolo_count,
        ):
            final_label = "UNKNOWN"
            seg_class = "AMBIGUOUS"
            tier = "weak_auto"
            confidence = min(confidence, 0.35)
            notes = "boundary_guard:empty_downgraded"

        wl = WindowLabel(
            clip_id=clip_id,
            window_start_sec=round(start, 2),
            window_end_sec=round(end, 2),
            label=final_label,
            label_tier=tier,
            confidence=round(confidence, 3),
            source_video=str(video_path),
            source_csi=csi_str,
            brightness_mean=round(wf.brightness_mean, 1),
            frame_diff_energy=round(wf.frame_diff_energy, 6),
            flow_magnitude_mean=round(wf.flow_magnitude_mean, 3),
            yolo_person_count=yolo_count,
            segment_class=seg_class,
            notes=notes,
        )
        labels.append(wl)

    # Step 7: Synthetic expansion (only for clear segments)
    if include_synthetic:
        clear_labels = [l for l in labels if l.segment_class.startswith("CLEAR_") and l.label != "UNKNOWN"]
        for lbl in clear_labels:
            variants = generate_synthetic_variants(lbl, video_path, n_variants=2)
            labels.extend(variants)

    return vq, labels


def main():
    parser = argparse.ArgumentParser(description="Video Curation Pipeline v1")
    parser.add_argument("--limit", type=int, default=0, help="Limit to first N videos (0=all)")
    parser.add_argument("--clip", type=str, default="", help="Process only this clip ID")
    parser.add_argument("--synthetic", action="store_true", help="Include synthetic expansion")
    parser.add_argument("--dry-run", action="store_true", help="No output written")
    parser.add_argument("--output-dir", type=str, default=str(OUTPUT_DIR), help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    print("=" * 70)
    print("Video Curation Pipeline v1")
    print("=" * 70)
    print(f"Captures dir: {CAPTURES_DIR}")
    print(f"Output dir:   {output_dir}")
    print(f"Synthetic:    {args.synthetic}")
    print()

    # Discover videos
    all_videos = sorted(CAPTURES_DIR.glob("*.teacher.mp4"))
    if args.clip:
        all_videos = [v for v in all_videos if args.clip in v.stem]
    if args.limit > 0:
        all_videos = all_videos[:args.limit]

    print(f"Found {len(all_videos)} teacher videos to process")
    print()

    # Process
    all_quality: list[dict] = []
    all_labels: list[dict] = []
    stats = {
        "total_videos": len(all_videos),
        "quality": {"good": 0, "dark": 0, "corrupt": 0, "too_short": 0},
        "segments": {"CLEAR_EMPTY": 0, "CLEAR_STATIC": 0, "CLEAR_MOTION": 0, "AMBIGUOUS": 0, "REJECT": 0},
        "labels": {"EMPTY": 0, "STATIC": 0, "MOTION": 0, "ENTRY_EXIT": 0, "UNKNOWN": 0},
        "tiers": {"human_verified": 0, "strong_teacher": 0, "weak_auto": 0, "synthetic": 0, "reject": 0},
        "total_windows": 0,
        "total_duration_sec": 0,
        "thresholds_candidate_v1": copy.deepcopy(THRESHOLDS_CANDIDATE_V1),
        "post_label_guards": ["empty_boundary_guard_v1"],
        "canonical_contract": "thresholds_candidate_v1 + empty_boundary_guard_v1",
    }

    t0 = time.time()

    for i, video_path in enumerate(all_videos):
        clip_id = video_path.stem.replace(".teacher", "")
        progress = f"[{i+1}/{len(all_videos)}]"
        print(f"{progress} {clip_id}...", end=" ", flush=True)

        vq, labels = process_clip(video_path, include_synthetic=args.synthetic)

        # Update stats
        stats["quality"][vq.quality_class] = stats["quality"].get(vq.quality_class, 0) + 1
        stats["total_duration_sec"] += vq.duration_sec

        all_quality.append(asdict(vq))

        for lbl in labels:
            if not lbl.synthetic:
                stats["segments"][lbl.segment_class] = stats["segments"].get(lbl.segment_class, 0) + 1
                stats["labels"][lbl.label] = stats["labels"].get(lbl.label, 0) + 1
                stats["total_windows"] += 1
            stats["tiers"][lbl.label_tier] = stats["tiers"].get(lbl.label_tier, 0) + 1
            all_labels.append(asdict(lbl))

        n_real = sum(1 for l in labels if not l.synthetic)
        n_synth = sum(1 for l in labels if l.synthetic)
        synth_str = f" +{n_synth}syn" if n_synth else ""
        print(f"q={vq.quality_class} dur={vq.duration_sec:.0f}s bright={vq.brightness_mean:.0f} windows={n_real}{synth_str}")

    elapsed = time.time() - t0

    # Print summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Videos processed:    {stats['total_videos']}")
    print(f"Total duration:      {stats['total_duration_sec']:.0f}s ({stats['total_duration_sec']/60:.1f} min)")
    print(f"Total windows:       {stats['total_windows']}")
    print(f"Processing time:     {elapsed:.1f}s")
    print()
    print("Video Quality:")
    for k, v in stats["quality"].items():
        print(f"  {k:12s}: {v:4d}")
    print()
    print("Segment Classes:")
    for k, v in stats["segments"].items():
        pct = 100.0 * v / max(1, stats["total_windows"])
        print(f"  {k:15s}: {v:4d} ({pct:5.1f}%)")
    print()
    print("Label Distribution:")
    for k, v in stats["labels"].items():
        pct = 100.0 * v / max(1, stats["total_windows"])
        print(f"  {k:12s}: {v:4d} ({pct:5.1f}%)")
    print()
    print("Label Tiers:")
    total_tier = sum(stats["tiers"].values())
    for k, v in stats["tiers"].items():
        pct = 100.0 * v / max(1, total_tier)
        print(f"  {k:16s}: {v:4d} ({pct:5.1f}%)")

    # Write outputs
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Quality report
        qpath = output_dir / "quality_report.json"
        qpath.write_text(json.dumps(all_quality, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nQuality report: {qpath}")

        # Labels manifest
        lpath = output_dir / "labels_manifest.json"
        lpath.write_text(json.dumps(all_labels, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Labels manifest: {lpath} ({len(all_labels)} entries)")

        # Stats
        stats["generated_at"] = datetime.now().isoformat()
        stats["elapsed_sec"] = round(elapsed, 1)
        spath = output_dir / "pipeline_stats.json"
        spath.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Pipeline stats:  {spath}")

        # Compact CSV for quick review
        csvpath = output_dir / "labels_compact.csv"
        with open(csvpath, "w", newline="") as f:
            import csv
            writer = csv.writer(f)
            writer.writerow([
                "clip_id", "start", "end", "label", "tier", "confidence",
                "segment_class", "brightness", "fdiff", "flow", "yolo", "synthetic",
            ])
            for lbl in all_labels:
                writer.writerow([
                    lbl["clip_id"],
                    lbl["window_start_sec"],
                    lbl["window_end_sec"],
                    lbl["label"],
                    lbl["label_tier"],
                    lbl["confidence"],
                    lbl["segment_class"],
                    lbl["brightness_mean"],
                    lbl["frame_diff_energy"],
                    lbl["flow_magnitude_mean"],
                    lbl["yolo_person_count"] if lbl["yolo_person_count"] is not None else "",
                    lbl["synthetic"],
                ])
        print(f"Compact CSV:     {csvpath}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
