# Video Curation Pipeline v1

**Agent**: CLOUD
**Date**: 2026-03-18
**Branch**: `codex/agent-cloud-video-curation`

## Pipeline Overview

The Video Curation Pipeline automates offline video teacher annotation for the WiFi DensePose project. It processes `.teacher.mp4` files captured alongside CSI data, extracts per-5-second-window visual features, classifies segments by confidence, and exports a structured label manifest for CSI model training.

### Problem Statement

- YOLO is unreliable in the dark garage (18% miss rate, 8% phantom detections)
- Enhanced YOLO (gamma+CLAHE) paradoxically worsens detection (83% -> 17%)
- Manual annotation is accurate but does not scale (only 30 clips annotated in v22)
- 96% false positive on empty garage due to extreme class imbalance (48 EMPTY vs 1297 OCCUPIED)
- Need a pipeline that separates "high confidence" labels from "ambiguous" ones

### Design Principles

1. **Trust hierarchy**: human_verified > strong_teacher > weak_auto > synthetic > reject
2. **Conservative classification**: when in doubt, mark AMBIGUOUS, not CLEAR
3. **Multi-signal fusion**: brightness + frame_diff + optical_flow + YOLO + human annotations
4. **Compatibility**: 5-second windows matching CSI feature extraction pipeline
5. **Provenance tracking**: every label records its source and confidence

## Data Flow

```
temp/captures/*.teacher.mp4
        |
        v
  [1] Quality Check (ffprobe + brightness sampling)
        |
        v
  [2] Per-Window Feature Extraction (5s windows)
      - brightness_mean, brightness_std
      - frame_diff_energy (cv2.absdiff)
      - optical_flow_magnitude (Farneback)
        |
        v
  [3] Segment Classification
      - CLEAR_EMPTY, CLEAR_STATIC, CLEAR_MOTION
      - AMBIGUOUS, REJECT
        |
        v
  [4] Label Fusion
      - Check visual_annotations_v22 (human tier)
      - Check YOLO annotations (boost/degrade confidence)
      - Detect entry/exit transitions
        |
        v
  [5] Synthetic Expansion (optional)
      - temporal_crop: shift window +-1.5s
      - speed_perturbation: stretch/compress 0.85x-1.15x
        |
        v
  output/video_curation/
    - labels_manifest.json  (full export)
    - labels_compact.csv    (quick review)
    - quality_report.json   (video quality audit)
    - pipeline_stats.json   (aggregate statistics)
```

## Label Tiers

| Tier | Confidence | Source | Use Case |
|------|-----------|--------|----------|
| `human_verified` | 1.0 | Visual inspection of keyframes | Training + validation |
| `strong_teacher` | 0.85 | Frame_diff + flow agree, brightness > 40, optionally YOLO agrees | Training |
| `weak_auto` | 0.5 | Only one signal or dark frame or ambiguous zone | Training with soft labels |
| `synthetic` | 0.3 | Temporal/speed augmentation of clear segments | Training (data augmentation) |
| `reject` | 0.0 | Corrupt, too dark, contradictory signals | Excluded |

## Segment Classification Logic

### Inputs per 5-second window

| Feature | How computed | Downsampled |
|---------|-------------|-------------|
| `brightness_mean` | Mean of grayscale pixels, averaged over sampled frames | 160x120 |
| `frame_diff_energy` | cv2.absdiff between consecutive frames, normalized 0-1 | 160x120 |
| `flow_magnitude_mean` | Farneback optical flow magnitude, averaged | 160x120 |

### Classification thresholds

| Segment Class | Frame Diff | Optical Flow | Label |
|---------------|-----------|--------------|-------|
| CLEAR_EMPTY | < 0.003 | < 0.06 px | EMPTY |
| CLEAR_STATIC | 0.003 - 0.006 | < 0.06 px | STATIC |
| CLEAR_MOTION | > 0.008 OR flow > 0.08 | (OR logic) | MOTION |
| AMBIGUOUS | Between thresholds | Mixed signals | UNKNOWN |
| REJECT | Any | brightness < 25 | UNKNOWN |

### Entry/Exit Detection

Adjacent windows where:
- Label changes (e.g., EMPTY -> MOTION)
- frame_diff ratio > 3x between windows

These windows get `label=ENTRY_EXIT` with capped confidence of 0.7.

## Export Contract

Each record in `labels_manifest.json`:

```json
{
    "clip_id": "longcap_chunk0001_20260318_143115",
    "window_start_sec": 0.0,
    "window_end_sec": 5.0,
    "label": "MOTION",
    "label_tier": "human_verified",
    "confidence": 1.0,
    "source_video": "temp/captures/longcap_chunk0001_20260318_143115.teacher.mp4",
    "source_csi": "temp/captures/longcap_chunk0001_20260318_143115.ndjson.gz",
    "synthetic": false,
    "synthetic_method": null,
    "brightness_mean": 42.3,
    "frame_diff_energy": 0.028,
    "flow_magnitude_mean": 2.1,
    "yolo_person_count": 1,
    "segment_class": "CLEAR_MOTION",
    "provenance": "auto_pipeline_v1",
    "notes": ""
}
```

## Synthetic Expansion

Only applied to `CLEAR_*` segments to preserve label integrity.

| Method | Parameters | Semantic preservation |
|--------|-----------|----------------------|
| `temporal_crop` | Window shift +-0.5 to +-1.5 seconds | Yes - same activity, slightly different frame selection |
| `speed_perturbation` | Window duration * (0.85 to 1.15) | Yes - same activity, different tempo |

All synthetic labels get `label_tier=synthetic`, `confidence <= 0.3`, `synthetic=true`.

## Usage

```bash
# Full pipeline on all teacher videos
python scripts/video_curation_pipeline.py

# Limit to first N videos
python scripts/video_curation_pipeline.py --limit 15

# With synthetic expansion
python scripts/video_curation_pipeline.py --synthetic

# Specific clip only
python scripts/video_curation_pipeline.py --clip longcap_chunk0001_20260318_143115

# Dry run
python scripts/video_curation_pipeline.py --dry-run
```

## What Works Now

1. Quality probing of all 100+ teacher.mp4 files (ffprobe + brightness)
2. Per-5s-window feature extraction (brightness, frame_diff, optical_flow)
3. Automatic segment classification with 5 tiers
4. Integration with visual_annotations_v22.py (human labels)
5. Integration with existing YOLO annotation CSVs
6. Entry/exit transition detection
7. Synthetic expansion (temporal_crop, speed_perturbation)
8. Structured JSON + CSV export

## Calibration Results (2026-03-19)

### Initial failure: MOTION = 0.4%

The initial thresholds were too strict for dark garage video:
- `FDIFF_MOTION_MIN = 0.025` — real walking produces only 0.007-0.014
- `FLOW_MOTION_MIN = 1.5` — real walking produces only 0.12-0.37
- AND logic required both signals — but in dark video, either may be weak

### Calibration data (from real clips)

| State | frame_diff | optical_flow |
|-------|-----------|-------------|
| EMPTY | ~0.002 | ~0.02 |
| STATIC (4 ppl standing) | 0.002-0.005 | 0.02-0.05 |
| MOTION (3 ppl walking) | 0.007-0.014 | 0.12-0.37 |

### Calibrated thresholds

| Parameter | Before | After | Reason |
|-----------|--------|-------|--------|
| FDIFF_STATIC_MAX | 0.012 | **0.006** | Static micromotion boundary |
| FDIFF_MOTION_MIN | 0.025 | **0.008** | Real walking threshold |
| FLOW_STATIC_MAX | 0.5 | **0.06** | Static flow cap |
| FLOW_MOTION_MIN | 1.5 | **0.08** | Real walking flow |
| Motion logic | AND | **OR** | Either signal sufficient |

### Cross-validation vs visual annotations (32 clips, 349 windows)

| Metric | Value |
|--------|-------|
| **Overall agreement** | **97.7%** (341/349) |
| EMPTY recall | 100% |
| STATIC recall | 96.6% |
| MOTION recall | 100% |
| EMPTY precision | 100% |
| STATIC precision | 100% |
| MOTION precision | 90.1% |

All 8 errors: pipeline marks STATIC as MOTION (micromotion/breathing misclassified).

### Full corpus results (138 videos, 1534 windows)

| Segment Class | Before | After |
|--------------|--------|-------|
| CLEAR_MOTION | 0.4% (1) | **36.8% (565)** |
| CLEAR_STATIC | 68.5% (165) | 45.5% (698) |
| CLEAR_EMPTY | 13.7% (33) | 10.8% (166) |
| AMBIGUOUS | 17.4% (42) | **6.7% (103)** |

### CSI model training with video-curated labels

Video-curated labels used directly as CSI ground truth gave Binary=0.576 (worse than V25's 0.827).
Root cause: temporal misalignment between video timestamps and CSI timestamps.

**Conclusion**: Video pipeline is excellent for curation/review (97.7% accuracy) but
video-derived labels should be used to **validate** CSI annotations, not replace them.
Best use: mine CLEAR_EMPTY windows from long captures to fix class imbalance.

## What is Hypothesis / Next Phase

1. **Active learning loop**: Sort AMBIGUOUS windows by frame_diff, present top-N to human for quick review.

2. **Better empty detection**: Pipeline can mine long captures for high-confidence empty windows.

3. **YOLO replacement**: Train a small binary presence/absence classifier on garage-specific keyframes.

4. **Temporal alignment**: Solve CSI-video timestamp misalignment to enable direct video-to-CSI labeling.
