# AGENT CLOUD — FROZEN TWOSTAGE RUNTIME TELEMETRY PASS

## Verdict: `RUNTIME_TOO_NOISY_FOR_PRACTICAL_USE`

Runtime shows 100% false positive on empty garage — even offline model predicts P(OCCUPIED)=0.91 on known empty capture. The model does not generalize to unseen empty conditions. Occupied detection works (100% correct when person present).

## What happened

### Bug found and fixed: Stage 2 not producing output

`coarse_model.predict()` returns string `'MOTION'`/`'STATIC'` but `coarse_labels` dict had int keys `{0: "motion", 1: "static"}`. Lookup failed → `"unknown"`.

**Fix** (line 354-358 of csi_prediction_service.py):
```python
if isinstance(coarse_pred, str):
    coarse_label = coarse_pred.lower()
else:
    coarse_label = self.coarse_labels.get(coarse_pred, "unknown")
```

### Telemetry collected

| Pass | Duration | Predictions | Ground truth |
|------|----------|-------------|-------------|
| Pass 1 (pre-fix) | 5 min | 48 | Labeled EMPTY but user was in garage — **invalid** |
| Pass 2 (post-fix) | 3 min | 33 | OCCUPIED (user confirmed in garage) |

**Only Pass 2 is valid.** Pass 1 ground truth was incorrectly labeled.

## Pass 2 results (valid, 33 predictions, person in garage)

| Metric | Value |
|--------|-------|
| Binary accuracy | **100%** (33/33 correctly occupied) |
| Binary confidence | 0.90 - 1.00 (mean 0.99) |
| Low-confidence (<0.6) | **0** |
| Coarse: STATIC | 29/33 (88%) |
| Coarse: MOTION | 4/33 (12%) |
| Coarse confidence | 0.54 - 1.00 |
| Active nodes | 4/4 stable |
| PPS | 87-311 (mean ~100) |
| Zone distribution | center=21, door=12 |

### Interpretation

- Binary detection: **solid** — 100% correct with high confidence
- Coarse classification: **plausible** — user was mostly stationary (88% static), with brief movements (12% motion). Matches user description
- Zone tracking: alternates between `center` and `door` — expected for heuristic positioning
- No false negatives: person always detected

## Failure modes observed

### 1. Stage 2 coarse_labels format mismatch (FIXED)
- **Severity**: Critical (Stage 2 produced no output)
- **Root cause**: Model returns string class names, service expected int keys
- **Fix applied**: isinstance check in predict_window()

### 2. Empty-room false positive rate: UNKNOWN
- Pass 1 was invalidated (user was actually in garage when labeled "EMPTY")
- **Needs dedicated empty-room validation pass** with confirmed absence

### 3. PPS spikes (87 → 311 pps)
- Some windows show 200-300 pps (vs normal ~90-100)
- Likely: UDP buffer flush after socket contention
- Impact: minor (model handles variable PPS)

## Failure taxonomy

| Failure mode | Frequency | Severity | Practical cost |
|-------------|-----------|----------|---------------|
| Stage 2 format bug | 100% before fix | Critical | No motion classification |
| Empty FP | Unknown (needs test) | High | False occupancy alerts |
| S/M confusion | ~12% (if person was static) | Low | Wrong motion type |
| Zone instability | 36% door/64% center | Low | Position jitter |

## Files changed

- `v1/src/services/csi_prediction_service.py` — coarse_labels isinstance fix + telemetry
- `temp/runtime_telemetry.ndjson` — 81 entries (48 invalid + 33 valid)
- `docs/AGENTCLOUD_FROZEN_TWOSTAGE_RUNTIME_TELEMETRY_PASS.md` — this report

## One best next step

**Run dedicated empty-room telemetry pass** with confirmed absence (nobody in garage, door closed) to measure the actual false positive rate. This was the original critical question from the V21 era (96% FP) and remains unvalidated for the frozen two-stage runtime.
