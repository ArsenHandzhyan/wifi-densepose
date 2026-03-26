# AGENT CLOUD — FROZEN TWO-STAGE RUNTIME DEPLOYMENT

## Model bundle

**File**: `output/frozen_twostage_runtime_v1.pkl` (2.3 MB)
**Format**: Compatible with existing `CsiPredictionService.load_model()`
**Frozen date**: 2026-03-19

## Runtime composition

```
UDP CSI packets (4 nodes, ~90 pps)
    |
    v
5-sec window → 79 features
    |
    v
Stage 1: HGB_bal → P(OCCUPIED)
    |
    ├── P < 0.50 → EMPTY (done)
    |
    └── P ≥ 0.50 → Stage 2: HGB_bal → STATIC / MOTION
                        |
                        └── Position estimation (zone-level)
```

**Stage 2 is only invoked when Stage 1 says OCCUPIED.** This is enforced in `predict_window()` at line 354.

## Integration

The existing `CsiPredictionService` already implements two-stage logic:
- `self.binary_model` = Stage 1 (EMPTY/OCCUPIED)
- `self.coarse_model` = Stage 2 (STATIC/MOTION)
- `if bin_pred == 1 and self.coarse_model is not None:` gates Stage 2

Only change needed: `MODEL_PATH` now points to `frozen_twostage_runtime_v1.pkl`.

## Frozen offline evidence

| Metric | Value | Source |
|--------|-------|--------|
| Stage 1 binary BalAcc | 0.749 | StratifiedGroupKFold(5) on 1524 windows, 114 clips |
| Stage 2 S/M BalAcc | 0.706 | StratifiedGroupKFold(5) on 752 windows, 95 clips |
| Combined 3-class BalAcc | 0.655 | Two-stage composition CV |
| Binary with smoothing | 0.856 | Post-prediction temporal smoothing k=7 |

## Primary runtime contract (updated 2026-03-19)

**PRIMARY OUTPUT: motion_state**
- `MOTION_DETECTED` — active movement in room (S/M BalAcc 0.706, drift-resistant)
- `NO_MOTION` — no active movement detected (may be empty OR stationary person)

**SECONDARY/EXPERIMENTAL (internal telemetry only, not product claims):**
- `binary`: empty/occupied — unreliable cross-session (SNR < 0.3, 49-100% FP on empty)
- `coarse`: empty/static/motion — internal state, not validated cross-session

## Telemetry contract

Every prediction is logged to `temp/runtime_telemetry.ndjson`:

```json
{"ts": 1773900000.0, "window_t": 15.0, "motion_state": "MOTION_DETECTED", "motion_conf": 0.712, "binary": "occupied", "binary_conf": 0.823, "coarse": "motion", "coarse_conf": 0.712, "nodes": 4, "pps": 88.4, "zone": "center"}
```

**Primary fields:**
- `motion_state`: MOTION_DETECTED / NO_MOTION (only reliable cross-session output)
- `motion_conf`: confidence (0-1)

**Secondary/debug fields:**
- `binary`: Stage 1 (empty/occupied) — experimental, not primary
- `coarse`: Stage 2 (empty/static/motion) — internal
- `nodes`, `pps`, `zone`: diagnostics

## Allowed runtime claims

- Motion detection (MOTION_DETECTED / NO_MOTION) — 0.706 BalAcc, drift-resistant
- Zone-level position (door/center/deep) — heuristic, approximate

## Prohibited runtime claims

- Binary EMPTY/OCCUPIED as primary reliable output (SNR < 0.3, not cross-session stable)
- Static person detection as reliable feature (CSI physics limit)
- Person counting beyond 1
- Sub-meter localization
- Breathing/pulse detection

## Expected failure modes

1. **STATIC person classified as EMPTY** (~42% of the time): CSI physics limit. Person standing still creates minimal perturbation.
2. **Empty room classified as OCCUPIED** (~9% false positive): Environmental noise, appliances, HVAC.
3. **MOTION/STATIC confusion on slow walking**: Threshold-dependent. Very slow movement may be classified as STATIC.
4. **Node dropout**: If < 3 nodes active, cross-node features degrade. Model still works but accuracy drops.

## Files changed

- `v1/src/services/csi_prediction_service.py` — MODEL_PATH updated, telemetry added
- `output/frozen_twostage_runtime_v1.pkl` — new frozen model bundle
- `docs/AGENTCLOUD_FROZEN_TWOSTAGE_RUNTIME_DEPLOYMENT.md` — this doc
