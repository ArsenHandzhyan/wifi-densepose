# AGENTCLOUD2 — Pre-Integration Baseline Freeze

Generated: 2026-03-18
Purpose: Canonical snapshot of project state BEFORE any academic transfer ideas are integrated.
This document is the single source of truth for what existed prior to academic extraction.

---

## 1. Current Best Model

| Metric | Value | Source |
|--------|-------|--------|
| Binary BalAcc (EMPTY vs OCCUPIED) | **0.856** | V28 smooth, post-prediction k=7 |
| Binary BalAcc (raw, no smoothing) | 0.835 | V28 feat |
| Coarse 3-class (EMPTY/STATIC/MOTION) | 0.628 | V27 |
| Static/Motion separation | 0.682 | V26 |
| False positive rate (empty garage) | ~15% | V22+ (was 96% before) |
| Model type | HGB (HistGradientBoosting) | class_weight=balanced |
| Feature count | 40-106 optimal | MI-ranked, from 1844 candidates |
| Best saved model | `output/v25_best_model.pkl` | HGB_bal, 106 features, 2.3 MB |

## 2. Data Regime

| Item | Value |
|------|-------|
| Total corpus records | 378 clips |
| Clean core | 20 clips |
| Clean support | 46 clips |
| Weak label | 171 clips |
| Hard negative | 7 clips |
| Training windows (V22 dataset) | 2055 |
| Empty windows | ~1007 (after March 18 grind) |
| Visually annotated clips | 45 (March 18 only reliable) |
| CSI nodes | 4x ESP32 (node01-node04), ceiling-mounted |
| CSI format | 128 subcarriers, IQ int8, ~22 pps/node |
| Video teacher | Pixel 8 Pro RTSP, optional offline only |
| Evaluation | StratifiedGroupKFold, holdout by epoch |

## 3. Feature Engineering (Current)

### Per-node features (5-sec windows)
- mean, std, max, range of CSI amplitude
- pps (packets per second)
- temporal_var (variance across time within window)
- normalized_mean

### Cross-node features
- mean_std, mean_range, std_mean across nodes
- tvar_mean, tvar_max

### Aggregate features
- agg_mean, agg_std, agg_pps

### Temporal context (V28 addition)
- ctx3_mean: rolling mean over 3 previous windows (8 of top 10 features)
- delta from previous window

### V25 additions
- sc_var_std, sc_var_max (subcarrier variance)
- corr features (cross-node correlation)
- phase features

**Total candidates: 1844, MI-ranked to 40-106 optimal**

## 4. Known Physical Limits

- CSI baseline deviation: EMPTY ~0.65σ, STATIC ~0.95σ, MOTION ~1.15σ
- EMPTY/OCCUPIED boundary: ~0.85σ (clear separation)
- STATIC/MOTION overlap: 0.95σ vs 1.15σ (physical limit, hard to separate)
- Post-prediction smoothing (k=7) gives +4.1% — biggest single gain

## 5. Pipeline Architecture

- Input: `.ndjson.gz` CSI packets → 5-sec windowed feature extraction
- Labels: manual annotations (preferred) > scripted captures > YOLO (unreliable)
- Model: sklearn HGB with balanced class weights
- Evaluation: StratifiedGroupKFold, holdout by session epoch
- No neural network, no learned features, no end-to-end training
- No temporal sequence model — each window classified independently (except ctx3_mean)

## 6. Frozen Lines (v1 status)

| Line | Status | Owner |
|------|--------|-------|
| CSI Operator UI v1 | frozen, feedback-driven only | Agent 7 |
| Video teacher path | canonical v2, RTSP-based | Agent 5 |
| Offline corpus/exit-gate policy | mature, holdout-aware | Agent 6 |
| Entry/exit runtime path | support-only, threshold 0.996 frozen | Agent 4 |
| Four-node topology | canonical (node01-04), no changes | stable |

## 7. Entry/Exit State

- Runtime: support-only `entry_shadow/exit_shadow`, frozen threshold 0.996
- Offline baseline: `hard_empty + entry + exit + quiet_static_center`
- Canonical resolved-strong same-run reference: **still not reproducible**
- Known failure families: collapsed_with_unresolved_overlap, late_ramp_subthreshold_miss, ambiguous_multi_pulse_invalid_exit_before_entry, pre_assignment_multi_pulse_ambiguity
- exit_first_prebaseline_aliasing: downgraded to contamination-sensitive

## 8. Corpus Mining State (Agent 6)

- Best offline pipeline: `clean_support_hierarchy`
  - Presence F1: 0.871
  - Motion binary F1: 0.876
  - 3-class macro F1: 0.507
- Roles used: clean_core + clean_support
- Domain-aware: No (didn't help)
- Weak labels: hurt when added

## 9. What Has NOT Been Tried

- No neural network architectures (CNN, RNN, Transformer)
- No learned feature extraction (all features hand-crafted)
- No sequence models (no LSTM, no temporal attention)
- No subcarrier-level learned patterns (only aggregated stats)
- No cross-node attention or fusion beyond simple statistics
- No data augmentation
- No domain adaptation techniques
- No transfer learning from any external dataset

## 10. Known Blockers

1. STATIC/MOTION physical overlap in CSI signal (~0.2σ gap)
2. YOLO unreliable in dark garage (26.5% error rate)
3. Entry/exit semantic instability (5 failure families catalogued)
4. No canonical resolved-strong entry/exit reference yet
5. Small clean_core corpus (20 clips)
6. March 17 agent annotations proven unreliable

---

*This baseline freeze is the reference point. Any improvement from academic transfer must be measured against these numbers.*
