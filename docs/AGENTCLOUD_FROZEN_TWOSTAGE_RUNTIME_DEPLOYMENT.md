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

## Telemetry contract

Every prediction is logged to `temp/runtime_telemetry.ndjson`:

```json
{"ts": 1773900000.0, "window_t": 15.0, "binary": "occupied", "binary_conf": 0.823, "coarse": "motion", "coarse_conf": 0.712, "nodes": 4, "pps": 88.4, "zone": "center"}
```

**Fields logged**:
- `ts`: wall-clock timestamp (Unix epoch)
- `window_t`: window end time (seconds since capture start)
- `binary`: Stage 1 prediction (empty/occupied)
- `binary_conf`: Stage 1 confidence (0-1)
- `coarse`: Stage 2 prediction (empty/static/motion)
- `coarse_conf`: Stage 2 confidence (0-1)
- `nodes`: active CSI nodes count
- `pps`: packets per second
- `zone`: position zone (empty/door/center/deep)

**Failure analysis**: grep telemetry for `binary_conf < 0.6` to find uncertain predictions. These are candidates for manual review.

## Allowed runtime claims

- Binary presence detection (EMPTY/OCCUPIED) — 0.749 BalAcc, 0.856 with smoothing
- 3-class state (EMPTY/STATIC/MOTION) — 0.655 BalAcc, experimental
- Zone-level position (door/center/deep) — heuristic, not validated

## Prohibited runtime claims

- Person counting beyond 1 (not validated)
- Activity recognition beyond motion/static
- Sub-meter localization
- Multi-room detection
- Breathing/pulse detection (not in this model)

## Expected failure modes

1. **STATIC person classified as EMPTY** (~42% of the time): CSI physics limit. Person standing still creates minimal perturbation.
2. **Empty room classified as OCCUPIED** (~9% false positive): Environmental noise, appliances, HVAC.
3. **MOTION/STATIC confusion on slow walking**: Threshold-dependent. Very slow movement may be classified as STATIC.
4. **Node dropout**: If < 3 nodes active, cross-node features degrade. Model still works but accuracy drops.

## Files changed

- `v1/src/services/csi_prediction_service.py` — MODEL_PATH updated, telemetry added
- `output/frozen_twostage_runtime_v1.pkl` — new frozen model bundle
- `docs/AGENTCLOUD_FROZEN_TWOSTAGE_RUNTIME_DEPLOYMENT.md` — this doc
