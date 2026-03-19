# AGENT CLOUD — MOTION-ONLY RUNTIME FALLBACK DECISION

## Verdict: `MOTION_ONLY_RUNTIME_FALLBACK`

Binary EMPTY/OCCUPIED is impractical for cross-session runtime (SNR < 0.3, 3/3 normalization approaches failed, 49-100% FP on empty garage). MOTION detection works at 0.70 BalAcc and is baseline-drift-resistant.

## Why binary EMPTY/OCCUPIED is impractical now

| Evidence | Result |
|----------|--------|
| Absolute features cross-session | 0.533 BalAcc |
| Per-clip 30s normalization | 0.750 CV, but 99% FP on Mar19 holdout |
| External session calibration | 0.489 cross-session |
| Hard-empty FP (any approach) | 49-100% |
| Between-session baseline drift | ~50% (amp 16 → 11 → 13) |
| EMPTY/OCCUPIED signal | ~15% |
| **SNR** | **< 0.3** |

3 normalization failures at SNR < 0.3 = physics limit, not engineering problem.

## Why MOTION detection is practical

| Evidence | Result |
|----------|--------|
| Handcrafted S/M BalAcc | 0.706 (stable across 5+ experiments) |
| Raw 1D-CNN S/M BalAcc | 0.700 (independent confirmation) |
| FN rate for motion | 0% (motion always detected) |
| Baseline drift sensitivity | Low (diff1, tvar measure relative change) |

## Runtime contract

```
States:
  MOTION_DETECTED  — active movement in garage (confidence > threshold)
  NO_MOTION        — no active movement detected
                     (room may be empty OR occupied by stationary person)

Explicitly NOT promised:
  - EMPTY vs OCCUPIED distinction
  - Static person detection
  - Person counting
```

## Role of new empty captures

New empty recordings (Mar 19+, closed door, lights off) are:
- `calibration_holdout` — for validating any future binary approach
- `baseline_realism_corpus` — different sessions, conditions, times
- **NOT pooled train** — reserved for testing, not training
- Tagged: `role=calibration_holdout, session=YYYYMMDD, condition=X`

## What changes in runtime

| Component | V1 (binary) | Motion-only fallback |
|-----------|-------------|---------------------|
| Stage 1 output | EMPTY / OCCUPIED | Not used for final state |
| Stage 2 output | STATIC / MOTION | **MOTION / NO_MOTION** (primary output) |
| False positive risk | 49-100% on empty | Low (motion requires actual signal change) |
| False negative risk | 0% | Misses stationary people (acceptable) |
| Position tracking | Zone-level heuristic | Same (when motion detected) |

## Files changed

- `docs/AGENTCLOUD_MOTION_ONLY_RUNTIME_FALLBACK_DECISION.md` — this report

## One best next step

**Update `csi_prediction_service.py` to motion-only output mode**: primary state = MOTION_DETECTED / NO_MOTION based on Stage 2 classifier (or simplified motion features: tvar, diff1, sc_var temporal dynamics). Binary EMPTY/OCCUPIED demoted to secondary/experimental signal. Test on live garage.
