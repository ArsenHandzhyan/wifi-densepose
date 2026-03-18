# AGENT CLOUD — STATIC DIVERSITY PACK / STAGE2 RERUN

## Verdict: `STATIC_DIVERSITY_NOT_ENOUGH`

Diversity pack gave only +0.006 combined 3-class (0.630→0.636). Stage 2 S/M slightly degraded (0.706→0.697).

## STATIC diversity pack collected

10 clips, 74 new STATIC windows from existing recordings:

| Clip | Pose | Duration | Windows |
|------|------|----------|---------|
| clip04_stand_center | Standing center | 20s | 4 |
| clip05_stand_near_exit | Standing near exit | 20s | 4 |
| clip06_stand_deep | Standing deep garage | 20s | 4 |
| chunk0001_010147 | Static near camera | 30s | 6 |
| chunk0006_010427 | Sitting static | 19s | 3 |
| chunk0012_212543 | Quiet static (long) | 157s | 31 |
| structured_stand_arms | Arms moving (static body) | 30s | 6 |
| structured_static_exit | Static near exit | 30s | 6 |
| clip10_enter_walk_stand | Enter then stand | 25s | 5 (STATIC portion) |
| clip12_enter_stay | Enter then static | 25s | 5 (STATIC portion) |

Total: 6.3 min, 74 STATIC + 5 MOTION windows.

## Results

| Config | Stage 2 S/M | Combined 3-class |
|--------|-------------|------------------|
| Baseline (752 windows) | **0.706** | 0.630 |
| Enriched (822 windows, +70) | 0.697 | **0.636** |
| Previous best two-stage | — | 0.655 |
| V25 baseline | — | 0.610 |

## Why diversity pack didn't help more

1. **Scripted STATIC clips lack video curation**: The diversity pack clips have scripted labels (person_count_expected + step_name) but no video pipeline classification. They were added at `human_verified` tier based on script metadata, but without actual video confirmation of exact STATIC/MOTION boundaries.

2. **CSI features don't differentiate STATIC poses**: Standing center vs standing near exit vs sitting — all produce similar CSI signatures because CSI measures aggregate room perturbation, not body pose. More STATIC variety doesn't help if the CSI features can't distinguish poses.

3. **High CV variance (±0.116)**: The +0.006 improvement is within noise at this dataset size. Would need 3-5x more data for statistically significant comparison.

## Remaining bottleneck

The two-stage architecture is at its practical ceiling for handcrafted CSI features:
- **Stage 1**: 0.749 (CSI physics limit for STATIC/EMPTY discrimination)
- **Stage 2**: 0.706 (video-curated labels are good, but CSI features plateau)
- **Combined**: 0.630-0.655 (composition of two imperfect stages)

Further STATIC data won't help because the bottleneck is **feature expressiveness**, not data diversity. CSI amplitude statistics cannot reliably distinguish subtle body poses.

## Files changed

- `docs/AGENTCLOUD_STATIC_DIVERSITY_PACK_STAGE2_RERUN.md` — this report

## One best next step

**Freeze the two-stage handcrafted pipeline at 0.655** (the best snapshot from the original validated run). The handcrafted CSI feature ceiling has been reached through thorough exploration. The most impactful next step is a **fundamentally different feature approach**: raw CSI sequence models (1D-CNN or LSTM on per-packet amplitude time series) that can learn representations beyond hand-designed statistics. This requires the same labeled data but bypasses the feature engineering bottleneck.
