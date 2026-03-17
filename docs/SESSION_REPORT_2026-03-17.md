# Session Report — 2026-03-17

## Summary

Full-day session: data collection, annotation, model training, and pipeline evaluation for WiFi CSI-based human sensing. Main outcome: **binary presence detection at 80% balanced accuracy** using manual ground truth — first honest, cross-session evaluation result.

## Hardware Verified

| Component | Status | Details |
|-----------|--------|---------|
| ESP32 node01 | OK | 192.168.1.137, HTTP :8080, ~23 pps |
| ESP32 node02 | OK | 192.168.1.117, HTTP :8080, ~23 pps |
| ESP32 node03 | OK | 192.168.1.101, HTTP :8080, ~23 pps |
| ESP32 node04 | OK | 192.168.1.125, HTTP :8080, ~23 pps |
| Pixel 8 Pro | OK | RTSP rtsp://admin:admin@192.168.1.148:8554/live, 640x480 H264 |
| Mac host | OK | 192.168.1.132, UDP:5005 receiver |

All nodes send CSI to 192.168.1.132:5005, WiFi channel 6. Firmware: RunBot CSI Node v0.2.0. Nodes required reboot via `POST /api/v1/reboot` to recover from stale state at session start.

## Data Collected

### Capture Sessions

| Session | Time | Chunks | Duration | Packets | Video | Notes |
|---------|------|--------|----------|---------|-------|-------|
| Multi-person tests | 20:10-20:19 | 4 clips | 226s | ~20K | Yes | 3p static, 4p static, 3p freeform, 2p freeform |
| Long capture #1 | 20:30-21:28 | 12x5min | 58 min | 425K | Yes | 1 person freeform, exit event in chunk 9 |
| Long capture #2 | 22:12-22:21 | 9x1min | 8.9 min | 47K | Partial | 1 person, video died chunks 8-9 (phone battery) |
| Empty garage | 22:32-22:35 | 1 clip | 180s | 16.5K | No | Dedicated empty recording, CSI-only |

**Total corpus**: 426 summaries, 505 CSI files, 55 videos, 27 high-quality clips (4 nodes, >10s).

### Keyframes & YOLO Detection

- Extracted 1331 keyframes (1fps) across 52 video labels
- Ran YOLOv8n on all keyframes: 1065 person detections
- Generated `.yolo_annotations.csv` for all 51 video labels

## Model Evolution — Critical Findings

### The Circular Labeling Problem (V5)

V5 used CSI-derived features to generate labels, then trained a CSI model on those same labels. This creates a model that learns to predict its own features — fundamentally flawed. **Result**: 0.54 binary balanced accuracy, 0.41 3-class.

**Rule: NEVER use CSI features to generate ground truth labels for CSI models.**

### Frame Differencing as Ground Truth (V6)

V6 used video frame-to-frame pixel change as motion ground truth. In the dark garage, frame differencing is unreliable — low contrast between consecutive frames even when a person walks. **Result**: 0.50-0.54 binary, 0.32-0.41 3-class.

**Rule: Frame differencing works for motion detection but cannot distinguish empty room from static person.**

### Manual Annotations Work (V7)

V7 used human-verified annotations from visual keyframe analysis (7 clips with segment-level labels). **Result**: 0.89 binary — huge jump. But only 222 windows, 12 empty.

**Rule: Manual human annotations are the gold standard. Even 7 clips beat 53 with automated labels.**

### Honest Evaluation with Diverse Empty Data (V8)

V8 added the dedicated empty garage recording (3 min, different session). Binary dropped from 0.90 to 0.80 — revealing that V7's 0.89 was inflated because all empty windows came from one session.

**V8 binary 0.80 is the honest, cross-session result.**

### YOLO Limitations in Dark Garage (V9)

YOLO detection results in the garage:
- **4 people standing**: detected 0 (too dark)
- **3 people standing**: detected 1 out of 3
- **1 person walking**: detected 0-4 across frames (noisy)
- **Empty room**: correctly detected 0

YOLO's median person count = 0 for many occupied clips → mislabels present as empty → model collapses.

**Rule: In dark environments, only trust YOLO when it SEES people (positive detection). YOLO's absence of detection does NOT mean room is empty.**

V9 with corrected YOLO labels: binary 0.80, 3-class 0.44 (YOLO motion labels are too noisy for static/walking distinction).

### Final Model Comparison

| Version | Script | Ground Truth | Clips | Windows | Binary BalAcc | 3-class BalAcc |
|---------|--------|-------------|-------|---------|---------------|----------------|
| V5 | `csi_motion_pipeline_v5.py` | CSI-derived | 38 | 8061 | 0.54 | 0.41 |
| V5-cascade | `csi_motion_pipeline_v5_cascade.py` | CSI-derived | 38 | 8061 | — | 0.41 |
| V6 (framediff) | `csi_motion_pipeline_v6_framediff.py` | Video frame-diff | 53 | 4599 | 0.50 | 0.32 |
| V7 (manual) | `build_manual_annotations_and_train_v7.py` | Human manual | 7 | 222 | 0.89 | 0.48 |
| **V8** | **`csi_motion_pipeline_v8_full_corpus.py`** | **Manual+YOLO** | **27** | **876** | **0.80** | **0.63** |
| V9 | `csi_motion_pipeline_v9_all_sources.py` | Manual+YOLO+clip | 27 | 876 | 0.80 | 0.44 |
| V10 | `csi_motion_pipeline_v10_corrected_gt.py` | Manual+YOLO motion_score | 27 | 876 | 0.80 | 0.47 |

**Best model**: V8 — `output/v8_full_corpus_model_20260317_223719.pkl`

### V10 Lesson: YOLO motion_score Cannot Replace Manual Annotations

V10 used YOLO per-frame `motion_score` (bbox area change between frames, threshold 0.015) to auto-classify each 5s window as walking vs static for all chunks without manual annotations. Result: binary stayed at 0.80 but 3-class dropped from 0.63 to 0.47. The motion_scores in dark garage are too small (all <0.04) and noisy to reliably separate walking from static. **Manual segment-level annotation remains the only reliable way to label motion state.**

## What Does NOT Work

1. **CSI-derived labels** — circular, model predicts its own features
2. **Frame differencing as presence detector** — can't distinguish empty from static person
3. **HOG person detector** — 0.0 avg persons, completely failed in dark garage
4. **YOLO in dark garage for absence detection** — misses static people regularly
5. **YOLO motion_score for static/walking** — too noisy, all below 0.04
6. **pixel8pro scripted clips for CSI training** — they have VIDEO ONLY, no CSI data (24 clips wasted)
7. **YOLO motion_score for walking/static auto-labeling** — per-frame bbox area changes are <0.04 in dark garage, too noisy to threshold (V10: 3-class dropped 0.63→0.47)

## What DOES Work

1. **Manual keyframe annotation** — reliable ground truth, even 7 clips dramatically improve accuracy
2. **YOLO for positive presence detection** — when it sees someone, it's likely right (conf > 0.25)
3. **CSI temporal variance features** — top discriminators for motion vs static
4. **Cross-node spread features** — differentiate presence from empty
5. **Baseline normalization** — per-session first-window normalization handles RF drift
6. **StratifiedGroupKFold with groups=clip_id** — honest CV that prevents data leakage
7. **5-second windows** — good balance between temporal resolution and feature stability
8. **Long capture daemon with chunks** — reliable multi-hour recording with auto-recovery

## Feature Engineering (40 features, V8)

Per node (x4): mean, std, max, range, pps, temporal_var, baseline_normalized_mean
Cross-node (x5): mean_std, mean_range, std_mean, tvar_mean, tvar_max
Aggregate (x3): agg_mean, agg_std, agg_pps
Temporal context (x4): delta from previous window per node

Top discriminators: `n*_tvar` (temporal variance), `x_tvar_max` (cross-node temporal variance max), `n*_norm` (baseline-normalized amplitude).

## Ready-to-Use Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/long_capture_daemon.py` | Background CSI+video capture | `venv/bin/python3 scripts/long_capture_daemon.py --hours 2 --chunk-sec 60` |
| `scripts/run_session3_full_pack.sh` | 12 structured clips with voice prompts | `bash scripts/run_session3_full_pack.sh` |
| `scripts/detect_persons_yolo.py` | YOLO person detection on keyframes | `venv/bin/python3 scripts/detect_persons_yolo.py --conf 0.25` |
| `scripts/extract_keyframes_for_annotation.py` | Extract 1fps JPEGs from videos | Auto-run |
| `scripts/csi_motion_pipeline_v8_full_corpus.py` | Train best model | `venv/bin/python3 scripts/csi_motion_pipeline_v8_full_corpus.py` |
| `scripts/csi_motion_pipeline_v9_all_sources.py` | Train with all sources (experimental) | Same |

## Next Steps (Priority Order)

1. **More diverse empty recordings** — record empty garage at different times of day, with door open/closed, lights on/off. Current bottleneck: only 48/876 empty windows.
2. **Run session3 pack** — `run_session3_full_pack.sh` has 12 structured clips (3x empty, 3x static, 3x motion, 3x entry/exit) never executed. Will give clean, balanced dataset.
3. **Manual annotation of remaining long capture chunks** — chunks 2-8, 10, 12 from session 1 have video but no manual annotations. Agent can visually analyze keyframes.
4. **Better lighting for YOLO** — even a small LED light would dramatically improve YOLO accuracy for automated annotation.
5. **Multi-person structured captures** — need 2/3/4 person sessions with known entry/exit times for person count model.
6. **Real-time inference pipeline** — integrate V8 model into live CSI stream for real-time presence detection.
7. **Backend fix** — `v1/src/app.py` has import errors from another agent's changes. Low priority.

## Anti-Patterns for Future Agents

**DO NOT:**
- Train CSI model using CSI-derived labels (circular)
- Trust YOLO absence detection in dark environments
- Use pixel8pro clips for CSI training (no CSI data in those files)
- Use frame differencing as sole presence indicator
- Skip `StratifiedGroupKFold` with `groups=clip_id` — plain CV leaks data between windows of the same clip
- Record without checking all 4 nodes are sending (`lsof -ti :5005` to check port, `/api/v1/status` per node)
- Run long captures without chunk splitting — single file corruption loses everything

**DO:**
- Check nodes via HTTP API before every recording session
- Use manual annotations as primary ground truth
- Record dedicated empty-room clips each session (different RF baseline)
- Use 5-second windows with temporal context features
- Normalize amplitude by per-session baseline
- Keep `person_count_expected` in summary.json for all scripted captures
- Store all captures in `temp/captures/` with `.ndjson.gz`, `.summary.json`, `.clip.json`
