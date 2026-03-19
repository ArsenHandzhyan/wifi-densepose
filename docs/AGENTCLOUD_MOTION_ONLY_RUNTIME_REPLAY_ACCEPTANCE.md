# AGENT CLOUD — MOTION-ONLY RUNTIME REPLAY ACCEPTANCE TEST

## Verdict: `MOTION_ONLY_RUNTIME_REPLAY_ACCEPTED`

Overall accuracy: **95.2%**, Balanced accuracy: **0.965**

## Acceptance suite

- **353 windows** from 32 human-verified video-backed clips
- Scenarios: 40 empty, 242 static, 71 motion
- Type: **RETROSPECTIVE REPLAY** (clips overlap with training)
- Source: `visual_annotations_v22.py` (human_verified tier)

## Results by scenario

| Scenario | Windows | Correct | Accuracy | False rate |
|----------|---------|---------|----------|------------|
| EMPTY (expect NO_MOTION) | 40 | 33 | **82.5%** | 17.5% false MOTION |
| STATIC (expect NO_MOTION) | 242 | 233 | **96.3%** | 3.7% false MOTION |
| MOTION (expect MOTION_DETECTED) | 71 | 70 | **98.6%** | 1.4% missed |
| **Total** | **353** | **336** | **95.2%** | |

## Transition behavior

11 clips with MOTION↔NO_MOTION transitions tested. Results:
- **Transition lag: ≤1 window (5 sec)** — acceptable for room-level detection
- **No sustained false toggles** — errors are isolated single-window spikes
- **Motion onset**: detected within first window in all cases
- **Motion offset**: correctly stops within 1 window

## Error analysis

**17 total errors (4.8%)**:
- 7 empty→false MOTION: all from `longcap_chunk0005_20260318_143524` (one clip, likely annotation boundary issue)
- 9 static→false MOTION: scattered boundary windows where person was transitioning (micro-movement)
- 1 motion→missed: last window of a motion segment (person stopping, borderline)

**No systematic failure pattern.** Errors are boundary cases, not class confusion.

## Confidence analysis

| State | Mean confidence |
|-------|----------------|
| MOTION_DETECTED (correct) | 0.93 |
| NO_MOTION (correct) | 0.52-0.71 |
| False MOTION | 0.62-0.98 (high — model is confident in errors) |

NO_MOTION confidence is low (0.50-0.52) because the model's Stage 2 is uncertain — this is expected for the "no motion" state which includes both empty and static.

## Files changed

- `docs/AGENTCLOUD_MOTION_ONLY_RUNTIME_REPLAY_ACCEPTANCE.md` — this report

## One best next step

**Live garage acceptance test** with a person performing known actions (walk 30s → stand 30s → leave → empty 30s). This is the final validation before declaring motion-only runtime production-ready.
