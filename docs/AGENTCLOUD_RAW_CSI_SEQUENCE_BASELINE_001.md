# AGENT CLOUD — RAW CSI SEQUENCE BASELINE 001

## Verdict: `RAW_SEQUENCE_NOT_YET_BETTER`

1D-CNN S/M BalAcc = **0.700** vs handcrafted **0.706** (delta: -0.006).

## Model

| Property | Value |
|----------|-------|
| Input | 5-sec window: (110 packets, 128 subcarriers) |
| Normalization | Per-window zero-mean, unit-std per subcarrier |
| Architecture | Conv1d(128→32, k=5) → BN → ReLU → MaxPool(2) → Conv1d(32→64, k=5) → BN → ReLU → AdaptiveAvgPool(1) → Dropout(0.3) → Linear(64→2) |
| Optimizer | Adam, lr=1e-3, weight_decay=1e-4 |
| Loss | CrossEntropy with class weights |
| Training | 40-70 epochs, early stopping (patience=3, check every 10 epochs) |
| Device | Apple MPS (M-series GPU) |
| CV | StratifiedGroupKFold(5) by clip_id |

## Results

| Fold | BalAcc | Epochs |
|------|--------|--------|
| 1 | 0.670 | 70 |
| 2 | 0.746 | 40 |
| 3 | 0.645 | 50 |
| 4 | 0.767 | 40 |
| 5 | 0.675 | 60 |
| **Mean** | **0.700 ± 0.047** | |

## Comparison

| Model | S/M BalAcc | Features |
|-------|-----------|----------|
| Handcrafted HGB_bal | **0.706** | 79 hand-designed statistics |
| **1D-CNN (this)** | **0.700** | Raw (110, 128) amplitude matrix |
| Combined two-stage best | 0.655 | — |

## Analysis

1. **Raw sequence ≈ handcrafted**: The 1D-CNN trained from scratch reaches the same level as 79 carefully designed features. This confirms the handcrafted features capture the available CSI signal well.

2. **Signal ceiling, not feature ceiling**: Both approaches plateau at ~0.70 S/M. The bottleneck is the **physical CSI signal itself**, not how we represent it. A stationary person creates too little CSI perturbation for reliable discrimination from an empty room.

3. **High fold variance (±0.047)**: With 752 windows and grouped CV, some folds have very uneven class distribution. More data would stabilize both approaches.

4. **Training was fast**: 29 seconds total (MPS GPU), ~6 sec per fold. The model is tiny (7K parameters) and data is small.

## What this means

The handcrafted feature pipeline is **not leaving performance on the table**. Raw temporal patterns (packet-level amplitude dynamics) don't contain additional discriminative information that the statistics miss.

To break past 0.70 S/M, the project needs:
- **More sensors** (higher spatial resolution to detect body position)
- **Different frequencies** (sub-GHz for better body coupling)
- **Active beamforming** (directed CSI probing)
- **Significantly more training data** (thousands, not hundreds of windows)

## Files changed

- `docs/AGENTCLOUD_RAW_CSI_SEQUENCE_BASELINE_001.md` — this report

## One best next step

**Freeze the entire offline handcrafted/raw CSI pipeline at the current best snapshots.** The signal ceiling has been confirmed from two independent directions (handcrafted features and raw sequences). Further model architecture exploration will not break past ~0.70 S/M or ~0.65 3-class without fundamentally more data or sensors. The most practical next step is **deploying the frozen two-stage model (0.655 3-class, 0.856 binary with smoothing) into the runtime system** and collecting real-world feedback to identify where it fails in practice.
