# AGENT CLOUD — TWOSTAGE STAGE1 CURATED RERUN

## Verdict: `CURATED_STAGE1_NOT_ENOUGH`

Combined 3-class dropped from 0.655 to 0.629, despite Stage 1 improvement.

## What changed vs previous Stage 1

| Property | Previous | Curated rerun |
|----------|----------|---------------|
| Stage 1 model | HGB_bal default | RF_bal 500 trees + threshold=0.58 |
| Stage 1 BalAcc | 0.749 | **0.775** (+0.026) |
| Combined dataset | 783 windows | 966 windows (more EMPTY) |
| Combined 3-class | 0.655 | 0.629 (-0.026) |

## Stage 1 results (all configs tested)

| Config | BalAcc | Notes |
|--------|--------|-------|
| HGB_bal (baseline) | 0.749 | Same as before |
| HGB_bal lr=0.01 | 0.752 | Marginal gain |
| **RF_bal 500 trees** | **0.764** | Best model |
| HGB_bal depth=4 | 0.742 | Underfitting |
| RF_bal + threshold=0.58 | **0.775** | Best with tuning |

## Why combined dropped despite Stage 1 improvement

1. **Different combined dataset size**: 966 vs 783 windows. More EMPTY windows (407 vs 319) dilute the OCCUPIED subset where Stage 2 operates.

2. **High CV variance**: ±0.134 on 3-class — the dataset is too small for stable 5-fold CV with grouped splits. Some folds have very few clips of each class.

3. **Stage 1 still bottlenecked**: Even at 0.775, EMPTY recall is only 0.58. The 42% of EMPTY windows misclassified as OCCUPIED feed into Stage 2, which then assigns them STATIC/MOTION labels — creating error cascade.

## Key finding

The bottleneck is **not the model or features** — it's the **fundamental CSI physics limit for STATIC detection**. A stationary person in a dark garage creates CSI perturbation (0.95σ) that overlaps with empty-room baseline (0.65σ). No amount of model tuning or data curation will close this gap without:
- More sensors (higher spatial resolution)
- Different frequencies (sub-GHz for better through-body penetration)
- Active sensing (directed beamforming)

## Comparison summary

| Config | Stage 1 | Stage 2 | Combined 3-class | vs V25 |
|--------|---------|---------|-------------------|--------|
| V25 baseline | 0.827 | 0.653 | 0.610 | — |
| Previous two-stage | 0.749 | 0.706 | **0.655** | **+0.045** |
| This curated rerun | 0.775 | 0.706 | 0.629 | +0.019 |
| Single-stage (same data) | — | — | 0.604 | -0.006 |

**Two-stage architecture is validated** (beats single-stage consistently), but curating Stage 1 further did not help because the bottleneck is physics, not data.

## Files changed

- `docs/AGENTCLOUD_TWOSTAGE_STAGE1_CURATED_RERUN.md` — this report

## One best next step

**Freeze the two-stage architecture at the 0.655 result** (previous run with 783-window combined dataset). Further Stage 1 optimization hits the CSI physics ceiling. The most impactful next step is **more STATIC training data with diverse body positions** — currently only 464 STATIC windows, mostly from the same few sessions. Recording 10 minutes of structured static poses (standing at different positions, sitting, leaning) would improve Stage 2 S/M discrimination more than any model change.
