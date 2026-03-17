#!/usr/bin/env python3
"""
V15 CSI Motion Pipeline — Hyperparameter Tuning on V4 Cache

Strategy: The v4 cache has 6105 honestly-labeled windows from 218 clips
with 1844 features. Previous best on this data was Binary=0.709 (RF_bal, 400 MI feats).

Track B got 0.80 with just 27 clips + 40 features. Why?
  - More balanced labels (122 empty windows out of 876 = 14% vs our 1355/6105 = 22%)
  - Simpler features → less overfitting on small test folds
  - Key: their EMPTY windows come from dedicated empty recordings

Approach v15:
  1. Aggressive hyperparameter search (RandomizedSearchCV within GroupKFold)
  2. Try threshold tuning on binary probability
  3. Try SMOTE/undersampling for class balance
  4. Feature selection: try f_classif, chi2, and combination
  5. Try boosting with early stopping
  6. Cross-validate at clip level (not window level)
"""

import pickle, json, time, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter
from sklearn.feature_selection import mutual_info_classif, f_classif
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import (HistGradientBoostingClassifier, RandomForestClassifier,
                               GradientBoostingClassifier, ExtraTreesClassifier)
from sklearn.metrics import balanced_accuracy_score, f1_score, classification_report, confusion_matrix
from sklearn.calibration import CalibratedClassifierCV

warnings.filterwarnings("ignore")

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except: HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGB = True
except: HAS_LGB = False

PROJECT = Path(__file__).resolve().parents[1]
t0 = time.time()

print("=" * 70)
print("CSI Motion Pipeline v15 — Hyperparameter Tuning")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ── Load and label ────────────────────────────────────────────────────────

df = pickle.load(open(PROJECT / "output/csi_pipeline_v4_results/dataset_v4_cache.pkl", "rb"))
feature_cols = [c for c in df.columns if not c.startswith("__")]

def ln_to_labels(ln):
    ln = ln.lower().strip()
    if any(x in ln for x in ["empty", "empty_room"]):
        return "EMPTY", "EMPTY"
    if any(x in ln for x in ["quiet_static", "static", "hold_object", "lift_object",
                              "normal_breath", "deep_breath", "sit_down", "stand_up",
                              "occupied_sit", "occupied_stand", "breathing",
                              "reposition_object_rotate", "reposition_object_place",
                              "set_object_down", "place_obstacle",
                              "multiple_people", "two_person", "three_person", "four_person",
                              "squat_hold", "lie_down", "kneel", "reach_high",
                              "stand_center", "stand_doorway"]):
        return "OCCUPIED", "STATIC"
    if any(x in ln for x in ["walk", "entry", "exit", "step_forward", "step_back",
                              "left_shift", "right_shift", "corridor", "fast_walk",
                              "slow_walk", "stop_and_go", "diagonal", "bend",
                              "carry_object", "move_obstacle", "loop_around", "linger",
                              "doorway_linger", "reposition_object_cross",
                              "occupied_entry", "occupied_exit",
                              "small_step", "transition", "side_step", "squat_stand"]):
        return "OCCUPIED", "MOTION"
    if "occupied" in ln:
        return "OCCUPIED", "STATIC"
    return None, None

df["binary"] = None
df["coarse"] = None
for idx, row in df.iterrows():
    b, c = ln_to_labels(row["__ln"])
    df.at[idx, "binary"] = b
    df.at[idx, "coarse"] = c

df = df.dropna(subset=["binary"])

X_all = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
y_binary = df["binary"].values
y_coarse = df["coarse"].values
groups = df["__clip_id"].values

print(f"Windows: {len(df)}, Clips: {df['__clip_id'].nunique()}")
print(f"Binary: {dict(Counter(y_binary))}")
print(f"Coarse: {dict(Counter(y_coarse))}")

# ── Load MI cache ─────────────────────────────────────────────────────────

mi_cache = PROJECT / "output/csi_pipeline_v12_results/mi_cache.pkl"
mi_series = pickle.load(open(mi_cache, "rb"))
print(f"MI cache loaded ({len(mi_series)} features)")

# ── Also compute f_classif for comparison ─────────────────────────────────

print("\nComputing f_classif scores...")
le = LabelEncoder()
y_enc_c = le.fit_transform(y_coarse)
f_scores, f_pvals = f_classif(X_all, y_enc_c)
f_series = pd.Series(f_scores, index=feature_cols).sort_values(ascending=False)
f_series = f_series.replace([np.inf, -np.inf, np.nan], 0)

# Combined ranking: average rank of MI and f_classif
mi_rank = mi_series.rank(ascending=False)
f_rank = f_series.rank(ascending=False)
combined_rank = (mi_rank + f_rank) / 2
combined_rank = combined_rank.sort_values()

print(f"Top 10 combined-rank features:")
for i, (fname, rank) in enumerate(combined_rank.head(10).items()):
    print(f"  {i+1:3d}. {fname:50s} rank={rank:.1f}")

# ══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 1: Hyperparameter sweep on binary
# ══════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("EXPERIMENT 1: Hyperparameter sweep on BINARY")
print("=" * 70)

CV = 5

# Feature selection methods
feat_selectors = {
    "MI_100": mi_series.head(100).index.tolist(),
    "MI_200": mi_series.head(200).index.tolist(),
    "MI_400": mi_series.head(400).index.tolist(),
    "F_100": f_series.head(100).index.tolist(),
    "F_200": f_series.head(200).index.tolist(),
    "Comb_100": combined_rank.head(100).index.tolist(),
    "Comb_200": combined_rank.head(200).index.tolist(),
    "Comb_400": combined_rank.head(400).index.tolist(),
}

le_b = LabelEncoder()
y_b = le_b.fit_transform(y_binary)

best_overall_ba = 0
best_config = ""

for fs_name, feats in feat_selectors.items():
    X_sel = X_all[feats].values

    configs = {
        "RF_500_15_bal": RandomForestClassifier(
            n_estimators=500, max_depth=15, class_weight="balanced",
            min_samples_leaf=2, random_state=42, n_jobs=-1),
        "RF_1000_20_bal": RandomForestClassifier(
            n_estimators=1000, max_depth=20, class_weight="balanced",
            min_samples_leaf=1, random_state=42, n_jobs=-1),
        "RF_500_10_bal": RandomForestClassifier(
            n_estimators=500, max_depth=10, class_weight="balanced",
            min_samples_leaf=5, random_state=42, n_jobs=-1),
        "ET_500_15_bal": ExtraTreesClassifier(
            n_estimators=500, max_depth=15, class_weight="balanced",
            min_samples_leaf=2, random_state=42, n_jobs=-1),
        "HGB_500_8_bal": HistGradientBoostingClassifier(
            max_iter=500, max_depth=8, learning_rate=0.03,
            class_weight="balanced", random_state=42),
        "HGB_1000_6_01": HistGradientBoostingClassifier(
            max_iter=1000, max_depth=6, learning_rate=0.01,
            class_weight="balanced", random_state=42),
    }
    if HAS_XGB:
        configs["XGB_500_8_03"] = XGBClassifier(
            n_estimators=500, max_depth=8, learning_rate=0.03,
            use_label_encoder=False, eval_metric="logloss",
            scale_pos_weight=len(y_b[y_b==1])/max(1, len(y_b[y_b==0])),
            random_state=42, verbosity=0)
        configs["XGB_1000_6_01"] = XGBClassifier(
            n_estimators=1000, max_depth=6, learning_rate=0.01,
            use_label_encoder=False, eval_metric="logloss",
            scale_pos_weight=len(y_b[y_b==1])/max(1, len(y_b[y_b==0])),
            random_state=42, verbosity=0)
    if HAS_LGB:
        configs["LGB_500_8_bal"] = LGBMClassifier(
            n_estimators=500, max_depth=8, learning_rate=0.03,
            class_weight="balanced", random_state=42, verbose=-1)

    best_ba_fs = 0
    best_cfg_fs = ""
    sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)

    for cfg_name, model in configs.items():
        fold_ba = []
        for train_idx, test_idx in sgkf.split(X_sel, y_b, groups):
            m = type(model)(**model.get_params())
            m.fit(X_sel[train_idx], y_b[train_idx])
            fold_ba.append(balanced_accuracy_score(y_b[test_idx], m.predict(X_sel[test_idx])))
        ba = np.mean(fold_ba)
        if ba > best_ba_fs:
            best_ba_fs = ba
            best_cfg_fs = cfg_name
            best_std_fs = np.std(fold_ba)

    print(f"  {fs_name:12s}: {best_cfg_fs:20s} BalAcc={best_ba_fs:.3f}+-{best_std_fs:.3f}")

    if best_ba_fs > best_overall_ba:
        best_overall_ba = best_ba_fs
        best_config = f"{fs_name} + {best_cfg_fs}"

print(f"\n  BEST BINARY: {best_config} -> BalAcc={best_overall_ba:.3f}")

# ══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 2: Same for COARSE
# ══════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("EXPERIMENT 2: Hyperparameter sweep on COARSE")
print("=" * 70)

le_c = LabelEncoder()
y_c = le_c.fit_transform(y_coarse)

best_overall_ba_c = 0
best_config_c = ""

for fs_name in ["MI_100", "MI_200", "Comb_200", "Comb_400"]:
    feats = feat_selectors[fs_name]
    X_sel = X_all[feats].values

    configs = {
        "RF_500_15_bal": RandomForestClassifier(
            n_estimators=500, max_depth=15, class_weight="balanced",
            min_samples_leaf=2, random_state=42, n_jobs=-1),
        "RF_1000_20": RandomForestClassifier(
            n_estimators=1000, max_depth=20,
            min_samples_leaf=1, random_state=42, n_jobs=-1),
        "ET_500_15_bal": ExtraTreesClassifier(
            n_estimators=500, max_depth=15, class_weight="balanced",
            min_samples_leaf=2, random_state=42, n_jobs=-1),
        "HGB_500_8_bal": HistGradientBoostingClassifier(
            max_iter=500, max_depth=8, learning_rate=0.03,
            class_weight="balanced", random_state=42),
        "HGB_1000_6_01_bal": HistGradientBoostingClassifier(
            max_iter=1000, max_depth=6, learning_rate=0.01,
            class_weight="balanced", random_state=42),
    }
    if HAS_XGB:
        configs["XGB_500_8"] = XGBClassifier(
            n_estimators=500, max_depth=8, learning_rate=0.03,
            use_label_encoder=False, eval_metric="mlogloss",
            random_state=42, verbosity=0)

    best_ba_fs = 0
    best_cfg_fs = ""
    sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)

    for cfg_name, model in configs.items():
        fold_ba = []
        all_preds = np.zeros(len(y_c), dtype=int)
        for train_idx, test_idx in sgkf.split(X_sel, y_c, groups):
            m = type(model)(**model.get_params())
            m.fit(X_sel[train_idx], y_c[train_idx])
            preds = m.predict(X_sel[test_idx])
            all_preds[test_idx] = preds
            fold_ba.append(balanced_accuracy_score(y_c[test_idx], preds))
        ba = np.mean(fold_ba)
        if ba > best_ba_fs:
            best_ba_fs = ba
            best_cfg_fs = cfg_name
            best_std_fs = np.std(fold_ba)
            best_preds_c = all_preds

    print(f"  {fs_name:12s}: {best_cfg_fs:20s} BalAcc={best_ba_fs:.3f}+-{best_std_fs:.3f}")

    if best_ba_fs > best_overall_ba_c:
        best_overall_ba_c = best_ba_fs
        best_config_c = f"{fs_name} + {best_cfg_fs}"
        final_preds_c = best_preds_c

print(f"\n  BEST COARSE: {best_config_c} -> BalAcc={best_overall_ba_c:.3f}")
cm = confusion_matrix(y_c, final_preds_c)
print(f"  Classes: {list(le_c.classes_)}")
for row in cm:
    print(f"  {row}")
print(classification_report(y_c, final_preds_c, target_names=le_c.classes_, digits=3))

# ══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 3: Probability threshold tuning for Binary
# ══════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("EXPERIMENT 3: Probability threshold tuning (Binary)")
print("=" * 70)

# Use best feature set
best_fs_name = best_config.split(" + ")[0] if " + " in best_config else "Comb_400"
feats = feat_selectors.get(best_fs_name, feat_selectors["Comb_400"])
X_sel = X_all[feats].values

sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)
all_probs = np.zeros((len(y_b), 2))
all_preds_default = np.zeros(len(y_b), dtype=int)

for train_idx, test_idx in sgkf.split(X_sel, y_b, groups):
    m = RandomForestClassifier(n_estimators=1000, max_depth=20,
                                class_weight="balanced", random_state=42, n_jobs=-1)
    m.fit(X_sel[train_idx], y_b[train_idx])
    all_probs[test_idx] = m.predict_proba(X_sel[test_idx])
    all_preds_default[test_idx] = m.predict(X_sel[test_idx])

ba_default = balanced_accuracy_score(y_b, all_preds_default)
print(f"  Default threshold (0.5): BalAcc={ba_default:.3f}")

# Sweep thresholds
best_thresh = 0.5
best_ba_thresh = ba_default

for thresh in np.arange(0.2, 0.8, 0.02):
    preds_t = (all_probs[:, 1] >= thresh).astype(int)
    ba_t = balanced_accuracy_score(y_b, preds_t)
    if ba_t > best_ba_thresh:
        best_ba_thresh = ba_t
        best_thresh = thresh

print(f"  Best threshold: {best_thresh:.2f} -> BalAcc={best_ba_thresh:.3f}")

# Show confusion at best threshold
preds_best_t = (all_probs[:, 1] >= best_thresh).astype(int)
cm = confusion_matrix(y_b, preds_best_t)
print(f"  Classes: {list(le_b.classes_)}")
for row in cm:
    print(f"  {row}")
print(classification_report(y_b, preds_best_t, target_names=le_b.classes_, digits=3))

# ══════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════

elapsed = time.time() - t0
print("\n" + "=" * 70)
print("FINAL SUMMARY v15")
print("=" * 70)
print(f"  Binary best:  {best_config} -> BalAcc={best_overall_ba:.3f}")
print(f"  Coarse best:  {best_config_c} -> BalAcc={best_overall_ba_c:.3f}")
print(f"  Binary+thresh: {best_thresh:.2f} -> BalAcc={best_ba_thresh:.3f}")
print(f"  Runtime: {elapsed:.1f}s ({elapsed/60:.1f} min)")
print("=" * 70)
