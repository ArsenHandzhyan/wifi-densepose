# AGENT CLOUD — TWO-STAGE CSI SUPERVISION DESIGN

## Why single-source video supervision is not the right goal

Video and CSI have a fundamental modality mismatch for one specific state:

| State | Video detects? | CSI detects? | Agreement |
|-------|---------------|-------------|-----------|
| EMPTY | Yes | Yes | Both agree |
| MOTION | Yes | Yes | Both agree |
| **STATIC** | **Yes** (shape/contour) | **Marginal** (0.95σ overlaps EMPTY 0.65σ) | **Disagree** |

When video says "person standing still" and CSI says "looks empty", neither is wrong — they sense different physical phenomena. Forcing video labels onto CSI for EMPTY/OCCUPIED creates unlearnable training signal (proven: Binary=0.592 vs 0.827 with scripted labels).

But for STATIC vs MOTION, video labels **outperform** scripted labels (0.706 vs 0.653). Video can see the difference between standing and walking; CSI features partially can too, but need the video supervision to learn it.

**Conclusion**: Use each label source where it has authority.

---

## Two-Stage Supervision Design

```
CSI 5-sec window (79 features)
        |
        v
  ┌─────────────────────────┐
  │  STAGE 1: EMPTY/OCCUPIED │
  │  Labels: scripted/manual  │
  │  Model: HGB_bal           │
  │  Target: BalAcc ≥ 0.82    │
  └────────────┬──────────────┘
               |
       ┌───────┴───────┐
       |               |
    EMPTY           OCCUPIED
    (done)             |
                       v
              ┌────────────────────┐
              │ STAGE 2: STATIC/MOTION │
              │ Labels: video-curated   │
              │ Model: HGB_bal          │
              │ Target: BalAcc ≥ 0.70   │
              └────────────────────┘
                       |
               ┌───────┴───────┐
               |               |
            STATIC          MOTION
```

### Stage 1: EMPTY / OCCUPIED

| Property | Value |
|----------|-------|
| **Label source** | Scripted CSI captures (person_count_expected in summary.json) + manual annotations (visual_annotations_v22.py) |
| **Label authority** | `CANONICAL` — these labels define EMPTY/OCCUPIED ground truth |
| **Available data** | 34 empty clips + 68 occupied clips + 30 min empty garage (Mar 18) |
| **Features** | Full 79-feature stack (V25) |
| **Model** | HGB with class_weight=balanced, 500 iter, lr=0.05, depth=6 |
| **CV** | StratifiedGroupKFold(5) by clip_id |
| **Proven baseline** | **0.827** (V25) |
| **Minimum benchmark** | BalAcc ≥ 0.82 |
| **Post-processing** | Temporal smoothing k=3-7 → up to 0.856 |
| **Main risk** | STATIC person misclassified as EMPTY (~42% of STATIC errors) |

**Video-curated labels are NOT used here.** They may be used for validation/audit only.

### Stage 2: STATIC / MOTION

| Property | Value |
|----------|-------|
| **Label source** | Video-curated pipeline (output/video_curation/labels_compact.csv), tiers human_verified + strong_teacher only |
| **Label authority** | `SUPERVISORY` — video labels define S/M truth for OCCUPIED windows |
| **Available data** | 845 high-quality windows (464 STATIC + 288 MOTION), 108 clips |
| **Input** | Only windows classified as OCCUPIED by Stage 1 |
| **Features** | Same 79-feature stack, possibly with Stage 1 probability as extra feature |
| **Model** | HGB with class_weight=balanced |
| **CV** | StratifiedGroupKFold(5) by clip_id |
| **Proven baseline** | **0.706** (V29-full S/M) |
| **Minimum benchmark** | BalAcc ≥ 0.70 |
| **Main risk** | False OCCUPIED from Stage 1 fed into Stage 2 (error cascade) |

**Scripted labels are NOT used for S/M.** They lack motion type granularity.

---

## Label source rules

### CANONICAL (must not be overridden)

| Label source | Valid for | Reason |
|-------------|-----------|--------|
| Scripted CSI (person_count_expected=0) | EMPTY | Physical absence confirmed by capture script |
| Scripted CSI (person_count_expected>0) | OCCUPIED | Physical presence confirmed by capture script |
| Manual annotation (visual_annotations_v22.py) | EMPTY/OCCUPIED + S/M | Human visual confirmation |
| 30-min empty garage (Mar 18) | EMPTY | Recorded with nobody in room |

### SUPERVISORY (valid with tier check)

| Label source | Valid for | Tier requirement |
|-------------|-----------|-----------------|
| Video-curated (human_verified) | STATIC/MOTION | Always valid |
| Video-curated (strong_teacher) | STATIC/MOTION | Valid (frame_diff + flow agree) |
| Video-curated (weak_auto) | — | NOT used for training |

### PROHIBITED

| Label source | Prohibited for | Reason |
|-------------|----------------|--------|
| Video-curated (any tier) | EMPTY/OCCUPIED | Modality mismatch — video sees static person, CSI does not |
| CSI-derived labels | Anything | Circular labeling |
| YOLO-only labels | EMPTY assertion | YOLO misses static people in dark (18% miss rate) |

---

## Expected combined performance

| Metric | Single-stage (V25) | Two-stage (projected) | Source |
|--------|-------------------|----------------------|--------|
| EMPTY/OCCUPIED | 0.827 | **0.827** (same) | Stage 1 unchanged |
| STATIC/MOTION | 0.653 | **0.706** (+8%) | Stage 2 with video labels |
| 3-class (E/S/M) | 0.610 | **~0.72** (estimated) | Composition |
| With smoothing | 0.856 | **~0.87** (estimated) | Both stages + k=7 |

The 3-class estimate: if Stage 1 correctly separates EMPTY 82.7% of the time, and Stage 2 correctly separates S/M 70.6% of the time, the composed 3-class accuracy is approximately `0.827 * 1/3 + 0.827 * 0.706 * 2/3 ≈ 0.72`.

---

## Training manifest contract

Each training window must declare:

```json
{
  "clip_id": "longcap_chunk0001_20260318_143115",
  "window_start_sec": 0,
  "stage1_label": "OCCUPIED",
  "stage1_source": "scripted",
  "stage1_confidence": 1.0,
  "stage2_label": "MOTION",
  "stage2_source": "video_curated",
  "stage2_tier": "strong_teacher",
  "stage2_confidence": 0.85,
  "features": [79 floats]
}
```

Stage 1 training uses only `stage1_label` + `stage1_source`.
Stage 2 training uses only `stage2_label` + `stage2_tier`, filtered to OCCUPIED windows.

---

## Implementation stub

```python
# Two-stage CSI classifier (offline)
class TwoStageCSIClassifier:
    def __init__(self, stage1_model, stage2_model, threshold=0.5):
        self.stage1 = stage1_model  # EMPTY/OCCUPIED
        self.stage2 = stage2_model  # STATIC/MOTION
        self.threshold = threshold

    def predict(self, X):
        """Returns 3-class: EMPTY, STATIC, MOTION"""
        # Stage 1
        proba1 = self.stage1.predict_proba(X)
        occ_idx = list(self.stage1.classes_).index("OCCUPIED")
        is_occupied = proba1[:, occ_idx] > self.threshold

        # Stage 2 (only on occupied)
        results = np.full(len(X), "EMPTY", dtype=object)
        if is_occupied.any():
            preds2 = self.stage2.predict(X[is_occupied])
            results[is_occupied] = preds2

        return results

    def predict_with_smoothing(self, X, k=5):
        """With temporal smoothing for streaming use."""
        raw = self.predict(X)
        # Map to numeric: EMPTY=0, STATIC=1, MOTION=2
        num = np.array([{"EMPTY":0,"STATIC":1,"MOTION":2}[r] for r in raw])
        # Smooth: majority vote in window of k
        smoothed = np.array([
            np.round(np.mean(num[max(0,i-k//2):i+k//2+1]))
            for i in range(len(num))
        ]).astype(int)
        return np.array([{0:"EMPTY",1:"STATIC",2:"MOTION"}[s] for s in smoothed])
```

---

## Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Error cascade (Stage 1 OCCUPIED → Stage 2 wrong) | False STATIC/MOTION on empty room | Temporal smoothing + Stage 1 threshold tuning |
| Stage 2 data limited (845 windows) | Overfitting on S/M | StratifiedGroupKFold + regularization |
| STATIC recall still low (~58%) | Missed stationary people | Accept as physics limit; focus on MOTION accuracy |
| Stage 1/2 threshold interaction | Sensitivity to threshold choice | Grid search on validation set |
