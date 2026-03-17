#!/usr/bin/env python3
"""
YOLO-based person detection for video teacher keyframes.

Processes keyframes extracted from CSI capture sessions and produces
per-frame person counts, confidence scores, and motion scores via
frame differencing. Outputs both a global JSON results file and
per-label annotation CSVs compatible with the existing video teacher
annotation format.

Usage:
    python scripts/detect_persons_yolo.py [--model yolov8n.pt] [--conf 0.25] [--device cpu]
"""

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEYFRAMES_DIR = PROJECT_ROOT / "output" / "keyframes"
MANIFEST_PATH = KEYFRAMES_DIR / "manifest.json"
RESULTS_JSON = PROJECT_ROOT / "output" / "yolo_person_detection_results.json"
ANNOTATIONS_DIR = PROJECT_ROOT / "temp" / "video_teacher"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("detect_persons_yolo")


# ---------------------------------------------------------------------------
# YOLO loader
# ---------------------------------------------------------------------------
def load_yolo_model(model_name: str, device: str):
    """Load a YOLOv8 model, downloading weights if necessary."""
    try:
        from ultralytics import YOLO
    except ImportError:
        log.error(
            "ultralytics is not installed. "
            "Install it with: pip install ultralytics"
        )
        sys.exit(1)

    log.info("Loading YOLO model '%s' on device '%s' ...", model_name, device)
    try:
        model = YOLO(model_name)
        # Warm-up inference on a dummy image so first real call is fast.
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        model.predict(dummy, device=device, verbose=False)
    except Exception as exc:
        log.error("Failed to load YOLO model: %s", exc)
        sys.exit(1)

    log.info("YOLO model ready.")
    return model


# ---------------------------------------------------------------------------
# Frame differencing (motion score)
# ---------------------------------------------------------------------------
def compute_motion_score(prev_gray: np.ndarray | None, curr_gray: np.ndarray) -> float:
    """Return a 0-1 normalised motion score via absolute frame difference."""
    if prev_gray is None:
        return 0.0
    if prev_gray.shape != curr_gray.shape:
        prev_gray = cv2.resize(prev_gray, (curr_gray.shape[1], curr_gray.shape[0]))
    diff = cv2.absdiff(prev_gray, curr_gray)
    # Mean pixel change normalised to 0-1
    return float(np.mean(diff) / 255.0)


def classify_motion(score: float, person_count: int) -> str:
    """Map a motion score + person count to a motion_state label."""
    if person_count == 0:
        return "none"
    if score > 0.06:
        return "walking"
    if score > 0.02:
        return "micro"
    return "static"


# ---------------------------------------------------------------------------
# Per-frame detection
# ---------------------------------------------------------------------------
def detect_frame(model, frame_bgr: np.ndarray, conf_thresh: float, device: str):
    """
    Run YOLO on a single frame.

    Returns:
        person_count: int
        avg_confidence: float  (0.0 if no persons)
        boxes: list of [x1, y1, x2, y2, conf]
    """
    results = model.predict(
        frame_bgr,
        device=device,
        conf=conf_thresh,
        classes=[0],  # person class only
        verbose=False,
    )
    result = results[0]
    boxes_out = []
    confs = []
    for box in result.boxes:
        cls_id = int(box.cls[0])
        if cls_id != 0:
            continue
        conf = float(box.conf[0])
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        boxes_out.append([x1, y1, x2, y2, conf])
        confs.append(conf)

    person_count = len(boxes_out)
    avg_conf = float(np.mean(confs)) if confs else 0.0
    return person_count, avg_conf, boxes_out


# ---------------------------------------------------------------------------
# Process one label directory
# ---------------------------------------------------------------------------
def process_label(
    model,
    label: str,
    frame_paths: list[str],
    frame_timestamps: list[int],
    conf_thresh: float,
    device: str,
) -> list[dict]:
    """Process all keyframes for a single video label."""

    label_dir = KEYFRAMES_DIR / label
    if not label_dir.is_dir():
        log.warning("Keyframe directory missing for label '%s', skipping.", label)
        return []

    frame_results = []
    prev_gray = None

    for idx, fname in enumerate(frame_paths):
        fpath = label_dir / fname
        if not fpath.is_file():
            log.warning("  Missing frame: %s", fpath)
            frame_results.append({
                "filename": fname,
                "timestamp_sec": frame_timestamps[idx] if idx < len(frame_timestamps) else idx * 10,
                "person_count": 0,
                "avg_confidence": 0.0,
                "motion_score": 0.0,
                "motion_state": "none",
                "error": "frame_missing",
            })
            continue

        frame_bgr = cv2.imread(str(fpath))
        if frame_bgr is None:
            log.warning("  Could not decode: %s", fpath)
            frame_results.append({
                "filename": fname,
                "timestamp_sec": frame_timestamps[idx] if idx < len(frame_timestamps) else idx * 10,
                "person_count": 0,
                "avg_confidence": 0.0,
                "motion_score": 0.0,
                "motion_state": "none",
                "error": "decode_failed",
            })
            continue

        # Detect persons
        person_count, avg_conf, boxes = detect_frame(model, frame_bgr, conf_thresh, device)

        # Motion score via frame differencing
        curr_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        motion_score = compute_motion_score(prev_gray, curr_gray)
        prev_gray = curr_gray

        ts = frame_timestamps[idx] if idx < len(frame_timestamps) else idx * 10
        motion_state = classify_motion(motion_score, person_count)

        frame_results.append({
            "filename": fname,
            "timestamp_sec": ts,
            "person_count": person_count,
            "avg_confidence": round(avg_conf, 4),
            "motion_score": round(motion_score, 6),
            "motion_state": motion_state,
            "boxes": boxes,
        })

    return frame_results


# ---------------------------------------------------------------------------
# Write annotation CSV (compatible with existing format)
# ---------------------------------------------------------------------------
def write_annotation_csv(label: str, frame_results: list[dict]) -> Path:
    """
    Write a per-label annotation CSV matching the existing format:
    timestamp_sec,person_count,motion_state,zone_hint,position_x_cm,position_y_cm,posture_hint,notes
    """
    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ANNOTATIONS_DIR / f"{label}.yolo_annotations.csv"

    fieldnames = [
        "timestamp_sec",
        "person_count",
        "motion_state",
        "zone_hint",
        "position_x_cm",
        "position_y_cm",
        "posture_hint",
        "notes",
    ]

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for fr in frame_results:
            if fr.get("error"):
                note = f"yolo:error={fr['error']}"
            else:
                note = (
                    f"yolo:conf={fr['avg_confidence']:.3f};"
                    f"motion_score={fr['motion_score']:.4f};"
                    f"n_boxes={fr['person_count']}"
                )
            zone = "empty" if fr["person_count"] == 0 else "unknown"
            posture = "none" if fr["person_count"] == 0 else "unknown"
            writer.writerow({
                "timestamp_sec": fr["timestamp_sec"],
                "person_count": fr["person_count"],
                "motion_state": fr["motion_state"],
                "zone_hint": zone,
                "position_x_cm": 0,
                "position_y_cm": 0,
                "posture_hint": posture,
                "notes": note,
            })

    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Detect persons in video keyframes using YOLOv8."
    )
    parser.add_argument(
        "--model",
        default="yolov8n.pt",
        help="YOLO model name or path (default: yolov8n.pt)",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold for person detections (default: 0.25)",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Inference device: cpu, mps, cuda, 0, etc. (default: cpu)",
    )
    parser.add_argument(
        "--labels",
        nargs="*",
        default=None,
        help="Process only these labels (default: all from manifest)",
    )
    args = parser.parse_args()

    # --- Load manifest ---
    if not MANIFEST_PATH.is_file():
        log.error("Manifest not found at %s", MANIFEST_PATH)
        sys.exit(1)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    videos = manifest.get("videos", [])
    interval_sec = manifest.get("interval_sec", 10)

    if not videos:
        log.error("No videos found in manifest.")
        sys.exit(1)

    # Filter labels if requested
    if args.labels:
        label_set = set(args.labels)
        videos = [v for v in videos if v["label"] in label_set]
        if not videos:
            log.error("None of the requested labels found in manifest.")
            sys.exit(1)

    log.info(
        "Processing %d video(s), interval=%ds, conf_thresh=%.2f",
        len(videos),
        interval_sec,
        args.conf,
    )

    # --- Load model ---
    model = load_yolo_model(args.model, args.device)

    # --- Process each video ---
    all_results = {}
    summary_stats = {
        "total_frames": 0,
        "total_persons_detected": 0,
        "labels_processed": 0,
        "labels_skipped": 0,
    }
    t0 = time.time()

    for vidx, video in enumerate(videos):
        label = video["label"]
        frame_paths = video.get("frame_paths", [])
        frame_timestamps = video.get("frame_timestamps", [])

        # Fall back to computed timestamps if missing
        if not frame_timestamps:
            frame_timestamps = [i * interval_sec for i in range(len(frame_paths))]

        log.info(
            "[%d/%d] %s  (%d frames)",
            vidx + 1,
            len(videos),
            label,
            len(frame_paths),
        )

        frame_results = process_label(
            model, label, frame_paths, frame_timestamps, args.conf, args.device
        )

        if not frame_results:
            summary_stats["labels_skipped"] += 1
            continue

        summary_stats["labels_processed"] += 1
        summary_stats["total_frames"] += len(frame_results)
        summary_stats["total_persons_detected"] += sum(
            fr["person_count"] for fr in frame_results
        )

        # Strip bounding boxes for the JSON (keep it leaner); store separately
        results_lean = []
        for fr in frame_results:
            entry = {k: v for k, v in fr.items() if k != "boxes"}
            entry["n_boxes"] = len(fr.get("boxes", []))
            results_lean.append(entry)

        all_results[label] = {
            "frame_count": len(frame_results),
            "avg_person_count": round(
                np.mean([fr["person_count"] for fr in frame_results]), 2
            ),
            "max_person_count": max(fr["person_count"] for fr in frame_results),
            "avg_confidence": round(
                np.mean([fr["avg_confidence"] for fr in frame_results if fr["person_count"] > 0])
                if any(fr["person_count"] > 0 for fr in frame_results)
                else 0.0,
                4,
            ),
            "avg_motion_score": round(
                np.mean([fr["motion_score"] for fr in frame_results]), 6
            ),
            "frames": results_lean,
        }

        # Write per-label annotation CSV
        csv_path = write_annotation_csv(label, frame_results)
        log.info("  -> %s", csv_path.name)

    elapsed = time.time() - t0
    summary_stats["elapsed_sec"] = round(elapsed, 2)
    summary_stats["fps"] = round(
        summary_stats["total_frames"] / elapsed if elapsed > 0 else 0, 2
    )

    # --- Write global JSON ---
    output_payload = {
        "model": args.model,
        "conf_threshold": args.conf,
        "device": args.device,
        "summary": summary_stats,
        "results": all_results,
    }
    RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_JSON, "w") as f:
        json.dump(output_payload, f, indent=2)

    log.info("=" * 60)
    log.info("Done. %d labels, %d frames in %.1fs (%.1f fps)",
             summary_stats["labels_processed"],
             summary_stats["total_frames"],
             elapsed,
             summary_stats["fps"])
    log.info("Total person detections: %d", summary_stats["total_persons_detected"])
    log.info("Results JSON: %s", RESULTS_JSON)
    log.info("Annotation CSVs: %s/*.yolo_annotations.csv", ANNOTATIONS_DIR)


if __name__ == "__main__":
    main()
