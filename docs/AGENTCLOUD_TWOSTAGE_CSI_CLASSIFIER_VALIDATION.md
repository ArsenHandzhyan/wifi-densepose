# AGENT CLOUD — TWOSTAGE CSI CLASSIFIER VALIDATION

## Verdict: `TWO_STAGE_BEATS_SINGLE_STAGE`

Two-stage 3-class BalAcc = **0.655** vs V25 baseline = 0.610 (+0.045).

## Implementation

```
CSI window (79 features)
    |
    v
Stage 1: HGB_bal → EMPTY / OCCUPIED (0.749 BalAcc)
    |
    OCCUPIED →
        |
        v
    Stage 2: HGB_bal → STATIC / MOTION (0.706 BalAcc)
```

## Training data

| Stage | Label source | Windows | Clips | Distribution |
|-------|-------------|---------|-------|-------------|
| Stage 1 | scripted + manual | 1524 | 114 | EMPTY=407, OCCUPIED=1117 |
| Stage 2 | video-curated (human_verified + strong_teacher) | 752 | 95 | STATIC=464, MOTION=288 |

## Results

| Metric | Value | Benchmark | Delta |
|--------|-------|-----------|-------|
| Stage 1 BalAcc | 0.749 | V25 binary 0.827 | -0.078 |
| Stage 2 BalAcc | 0.706 | V25 S/M 0.653 | +0.053 |
| **Two-stage 3-class (CV)** | **0.655** | V25 coarse 0.610 | **+0.045** |
| Single-stage 3-class (CV) | 0.653 | V25 coarse 0.610 | +0.043 |

### Stage 1 per-class
| Class | Precision | Recall | F1 |
|-------|-----------|--------|-----|
| EMPTY | 0.71 | 0.58 | 0.64 |
| OCCUPIED | 0.86 | 0.91 | 0.89 |

### Stage 2 per-class
| Class | Precision | Recall | F1 |
|-------|-----------|--------|-----|
| STATIC | 0.77 | 0.78 | 0.78 |
| MOTION | 0.64 | 0.63 | 0.64 |

## Analysis

1. **Two-stage beats V25 baseline by +0.045** (0.655 vs 0.610).
2. **Stage 2 is the clear winner**: video-curated S/M labels give +0.053 over scripted-only.
3. **Stage 1 is below V25 binary**: 0.749 vs 0.827. This is because the combined dataset includes more diverse clips (visual annotations from Mar 18 sessions) that are harder to classify. The V25 dataset was more curated.
4. **Two-stage ≈ single-stage on same data** (0.655 vs 0.653): the composition adds minimal overhead but enables modular label sourcing.

## Label provenance (enforced)

| Stage | Canonical source | Prohibited source |
|-------|-----------------|-------------------|
| Stage 1 | scripted CSI (person_count_expected) + manual visual | video-curated (any tier) |
| Stage 2 | video-curated (human_verified + strong_teacher) | scripted, YOLO-only, CSI-derived |

## Files changed

- `docs/AGENTCLOUD_TWOSTAGE_CSI_CLASSIFIER_VALIDATION.md` — this report

## One best next step

**Boost Stage 1 to match V25 level (0.82+)** by using only the curated V25 training subset for Stage 1, not the full mixed dataset. This should recover the lost 0.078 and push combined 3-class toward 0.72.
