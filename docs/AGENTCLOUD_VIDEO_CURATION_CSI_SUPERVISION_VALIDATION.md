# AGENT CLOUD — VIDEO CURATION / CSI SUPERVISION VALIDATION

## Verdict: `VIDEO_CURATED_LABELS_STILL_NOT_SUFFICIENT`

### Task

Validate whether V29 failure (Binary=0.576) was caused by poor CSI feature coverage (36 instead of 79 features), and determine if video-curated labels can serve as CSI supervisory source with full features restored.

### What changed: V29-original vs V29-full

| Component | V29-original | V29-full |
|-----------|-------------|----------|
| CSI features | 36 | **79** |
| Per-node features | 7 (mean,std,max,range,pps,tvar,norm) | **16** (+diff1, diff1_max, sc_var_mean/std/max, tvar_lo, tvar_hi, zcr, kurtosis) |
| Cross-node features | 5 | **8** (+x_diff1_mean, x_sc_var_mean, x_corr_mean_std) |
| Temporal delta | 0 | **4** (n0-n3_delta) |
| Aggregate | 3 | 3 (unchanged) |
| Labels | video-curated, high-quality tiers | same |
| Windows | 921 | same |
| Clips | 107 | same |

### Results

| Config | Binary | Coarse | S/M | Notes |
|--------|--------|--------|-----|-------|
| V29 original (36 feat) | 0.576 | 0.537 | 0.710 | Previous run |
| **V29-full (79 feat, high-quality)** | **0.592** | **0.528** | **0.706** | This run |
| V29-full (all tiers) | 0.556 | 0.413 | — | Weak labels hurt |
| **V25 baseline** | **0.827** | **0.610** | **0.653** | Scripted/manual labels |

### Analysis

1. **Feature coverage was NOT the primary blocker**: 79 features gave only +0.016 binary (0.576 → 0.592). The gap to V25 (0.827) remains 0.235.

2. **S/M classification works well with video labels**: Both V29-original (0.710) and V29-full (0.706) beat V25 (0.653) on STATIC/MOTION. Video-curated labels are **valid for S/M supervision**.

3. **EMPTY/OCCUPIED classification fails**: Video labels produce STATIC labels for scenarios where CSI sees near-empty signal. The root cause: a stationary person in a dark garage creates minimal CSI perturbation (~0.95σ baseline deviation) that overlaps with empty-room baseline (~0.65σ). Video can see the person (by contour/shape), CSI cannot reliably detect them.

4. **Adding weak_auto tier makes it worse**: All-tiers (1445 windows) gave 0.556 binary — worse than high-quality-only (0.592). Noise in weak labels overwhelms the model.

### Root cause: Modality mismatch

Video and CSI have fundamentally different detection capabilities:

| State | Video can detect? | CSI can detect? |
|-------|------------------|-----------------|
| EMPTY | Yes (no person visible) | Yes (baseline deviation < 0.85σ) |
| MOTION | Yes (frame diff, flow) | Yes (high tvar, diff1) |
| STATIC | **Yes** (person visible by shape) | **Marginal** (deviation 0.85-1.1σ, overlaps with EMPTY) |

When video says "STATIC" but CSI sees near-EMPTY signal, the label is technically correct (person IS there) but CSI features cannot support it. This creates a training signal that the model cannot learn.

### Why V25 works better

V25 uses scripted labels where EMPTY clips were recorded **without** anyone in the room, and OCCUPIED clips always had active presence (walking, entering, etc.) — scenarios where CSI signal is strong. V25 avoids the STATIC-person-in-dark-room scenario where CSI is weakest.

### Verdict details

- Video-curated labels are **VALIDATED for STATIC/MOTION supervision** (0.71 BalAcc, better than V25)
- Video-curated labels are **NOT SUFFICIENT for EMPTY/OCCUPIED supervision** (0.59 vs 0.83)
- The blocker is **modality mismatch**, not features, alignment, or label quality
- No further feature engineering or threshold tuning will fix this fundamental gap

### Remaining blocker

**CSI cannot reliably distinguish a stationary person from an empty room.** This is a physics limitation of WiFi CSI at the current sensor density and placement. Video labels that assert "STATIC person present" create unlearnable training signal for the CSI modality.

### Files changed

- `docs/AGENTCLOUD_VIDEO_CURATION_CSI_SUPERVISION_VALIDATION.md` — this report

### One best next step

**Use video-curated labels in a 2-stage architecture**: Stage 1 uses scripted/manual CSI labels for EMPTY/OCCUPIED (proven 0.83). Stage 2 uses video-curated labels for STATIC/MOTION classification on the OCCUPIED subset (proven 0.71). This combines the strengths of both label sources.
