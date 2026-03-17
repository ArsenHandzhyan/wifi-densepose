#!/usr/bin/env python3
"""
V13 CSI Motion Pipeline — Ceiling-V2 Focused + Tuned

Key insights from v12:
  - 400 features is optimal for binary (0.708)
  - 50 features is optimal for coarse (0.673)
  - RF dominates across all tasks
  - STATIC/MOTION best at 100 features with XGB (0.760)
  - garage_ceiling_v2 epoch has binary=0.692 but coarse=0.463 (STATIC hard)
  - early epoch has coarse=0.789 (STATIC easier with different topology)

Strategy v13:
  1. Focus on ceiling_v2 epoch only (most data, target deployment)
  2. Try class weighting to help EMPTY recall
  3. Tune hyperparameters for best config from v12
  4. Try calibrated ensemble of best models
  5. Try oversampling EMPTY class
  6. Per-epoch normalization (remove epoch shift)
"""

import pickle, json, time, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter
from sklearn.feature_selection import mutual_info_classif
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import (HistGradientBoostingClassifier, RandomForestClassifier,
                               VotingClassifier, IsolationForest)
from sklearn.metrics import balanced_accuracy_score, f1_score, classification_report, confusion_matrix
from sklearn.calibration import CalibratedClassifierCV

warnings.filterwarnings("ignore")

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except:
    HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGB = True
except:
    HAS_LGB = False

PROJECT = Path(__file__).resolve().parents[1]
t0 = time.time()

print("=" * 70)
print("CSI Motion Pipeline v13 — Ceiling-V2 Focused + Tuned")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ── Load v4 cache ─────────────────────────────────────────────────────────

df = pickle.load(open(PROJECT / "output/csi_pipeline_v4_results/dataset_v4_cache.pkl", "rb"))
meta_cols = [c for c in df.columns if c.startswith("__")]
feature_cols = [c for c in df.columns if not c.startswith("__")]

# ── Label mapping ─────────────────────────────────────────────────────────

def ln_to_labels(ln):
    ln = ln.lower().strip()
    if any(x in ln for x in ["empty", "empty_room"]):
        return "EMPTY", "EMPTY"
    if any(x in ln for x in ["quiet_static", "static", "hold_object_static",
                              "lift_object_static", "normal_breath", "deep_breath",
                              "sit_down_hold", "stand_up_hold", "sit_down",
                              "occupied_sit", "occupied_stand", "breathing",
                              "reposition_object_rotate", "reposition_object_place",
                              "set_object_down", "place_obstacle",
                              "multiple_people", "two_person", "three_person", "four_person"]):
        return "OCCUPIED", "STATIC"
    if any(x in ln for x in ["walk", "entry", "exit", "step_forward", "step_back",
                              "left_shift", "right_shift", "corridor", "fast_walk",
                              "slow_walk", "stop_and_go", "diagonal", "bend",
                              "carry_object_entry", "carry_object_walk",
                              "carry_object_stop", "carry_object_cross",
                              "move_obstacle", "loop_around", "linger",
                              "doorway_linger", "reposition_object_cross",
                              "occupied_entry", "occupied_exit",
                              "small_step", "transition"]):
        return "OCCUPIED", "MOTION"
    if "occupied" in ln:
        return "OCCUPIED", "STATIC"
    # NEW: map previously skipped labels
    if any(x in ln for x in ["side_step", "squat_stand", "stand_up", "kneel",
                              "reach_high", "stand_center", "stand_doorway",
                              "squat_hold", "lie_down"]):
        return "OCCUPIED", "MOTION"  # these all involve body movement
    return None, None

df["binary"] = None
df["coarse"] = None
for idx, row in df.iterrows():
    b, c = ln_to_labels(row["__ln"])
    df.at[idx, "binary"] = b
    df.at[idx, "coarse"] = c

df = df.dropna(subset=["binary"])
print(f"Total labeled: {len(df)} windows, {df['__clip_id'].nunique()} clips")

# ── Feature prep ──────────────────────────────────────────────────────────

X_all = df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0)
y_binary = df["binary"].values
y_coarse = df["coarse"].values
groups = df["__clip_id"].values
epochs = df["__epoch"].values

print(f"Binary: {dict(Counter(y_binary))}")
print(f"Coarse: {dict(Counter(y_coarse))}")

# ── MI feature selection (reuse from v12 if cached) ───────────────────────

print("\n[Phase 1] MI feature selection...")
mi_cache = PROJECT / "output/csi_pipeline_v12_results/mi_cache.pkl"

le = LabelEncoder()
y_enc = le.fit_transform(y_coarse)

if mi_cache.exists():
    mi_series = pickle.load(open(mi_cache, "rb"))
    print("  Loaded MI cache")
else:
    mi = mutual_info_classif(X_all.values, y_enc, random_state=42, n_neighbors=5)
    mi_series = pd.Series(mi, index=feature_cols).sort_values(ascending=False)
    mi_cache.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(mi_series, open(mi_cache, "wb"))
    print("  Computed and cached MI")

# ── Experiment 1: All data, class-weighted models ─────────────────────────

print("\n" + "=" * 70)
print("EXPERIMENT 1: All data, class-weighted models")
print("=" * 70)

CV_SPLITS = 5

for n_feat in [50, 100, 200, 400]:
    top_feats = mi_series.head(n_feat).index.tolist()
    X_sel = X_all[top_feats].values

    print(f"\n  --- {n_feat} features ---")
    for task_name, y_task in [("binary", y_binary), ("coarse", y_coarse)]:
        le_t = LabelEncoder()
        y_t = le_t.fit_transform(y_task)

        sgkf = StratifiedGroupKFold(n_splits=CV_SPLITS, shuffle=True, random_state=42)

        models = {
            "RF_bal": RandomForestClassifier(n_estimators=500, max_depth=15,
                                             class_weight="balanced", random_state=42, n_jobs=-1),
            "HGB_bal": HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                       class_weight="balanced", random_state=42),
            "RF": RandomForestClassifier(n_estimators=500, max_depth=15, random_state=42, n_jobs=-1),
        }
        if HAS_XGB:
            # Compute sample weights for XGB
            class_counts = Counter(y_t)
            n_samples = len(y_t)
            n_classes = len(class_counts)
            scale_pos = {}
            for cls, cnt in class_counts.items():
                scale_pos[cls] = n_samples / (n_classes * cnt)

            models["XGB_w"] = XGBClassifier(
                n_estimators=500, max_depth=8, learning_rate=0.03,
                use_label_encoder=False, eval_metric="mlogloss",
                random_state=42, verbosity=0)

        best_ba = 0
        best_name = ""
        for mname, model in models.items():
            fold_ba = []
            all_preds = np.zeros(len(y_t), dtype=int)

            for train_idx, test_idx in sgkf.split(X_sel, y_t, groups):
                m = type(model)(**model.get_params())

                if mname == "XGB_w":
                    sw = np.array([scale_pos[c] for c in y_t[train_idx]])
                    m.fit(X_sel[train_idx], y_t[train_idx], sample_weight=sw)
                else:
                    m.fit(X_sel[train_idx], y_t[train_idx])

                preds = m.predict(X_sel[test_idx])
                all_preds[test_idx] = preds
                fold_ba.append(balanced_accuracy_score(y_t[test_idx], preds))

            mean_ba = np.mean(fold_ba)
            if mean_ba > best_ba:
                best_ba = mean_ba
                best_name = mname
                best_preds = all_preds
                best_std = np.std(fold_ba)
                best_f1 = f1_score(y_t, all_preds, average="macro")

        print(f"    {task_name:8s}: {best_name:10s} BalAcc={best_ba:.3f}+-{best_std:.3f} F1={best_f1:.3f}")

        if n_feat == 100 and task_name == "coarse":
            print(f"      Classes: {list(le_t.classes_)}")
            cm = confusion_matrix(y_t, best_preds)
            for row in cm:
                print(f"      {row}")
            print(classification_report(y_t, best_preds, target_names=le_t.classes_, digits=3))

# ── Experiment 2: Ceiling-V2 only ────────────────────────────────────────

print("\n" + "=" * 70)
print("EXPERIMENT 2: Ceiling-V2 epoch only")
print("=" * 70)

mask_cv2 = epochs == "garage_ceiling_v2"
X_cv2 = X_all.loc[mask_cv2]
y_cv2_b = y_binary[mask_cv2]
y_cv2_c = y_coarse[mask_cv2]
g_cv2 = groups[mask_cv2]

print(f"  Windows: {len(X_cv2)}, Clips: {len(np.unique(g_cv2))}")
print(f"  Binary: {dict(Counter(y_cv2_b))}")
print(f"  Coarse: {dict(Counter(y_cv2_c))}")

# Recompute MI for ceiling_v2 specifically
print("  Computing MI for ceiling_v2...")
le_cv2 = LabelEncoder()
y_cv2_enc = le_cv2.fit_transform(y_cv2_c)
mi_cv2 = mutual_info_classif(X_cv2.values, y_cv2_enc, random_state=42, n_neighbors=5)
mi_cv2_series = pd.Series(mi_cv2, index=feature_cols).sort_values(ascending=False)

print(f"  Top 10 MI features (ceiling_v2):")
for i, (fname, mival) in enumerate(mi_cv2_series.head(10).items()):
    print(f"    {i+1:3d}. {fname:50s} MI={mival:.4f}")

for n_feat in [30, 50, 100, 200, 400]:
    top_feats = mi_cv2_series.head(n_feat).index.tolist()
    X_sel = X_cv2[top_feats].values

    print(f"\n  --- {n_feat} features ---")
    for task_name, y_task in [("binary", y_cv2_b), ("coarse", y_cv2_c)]:
        le_t = LabelEncoder()
        y_t = le_t.fit_transform(y_task)

        n_splits = min(CV_SPLITS, len(np.unique(g_cv2)))
        sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)

        models = {
            "RF_bal": RandomForestClassifier(n_estimators=500, max_depth=15,
                                             class_weight="balanced", random_state=42, n_jobs=-1),
            "HGB_bal": HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                       class_weight="balanced", random_state=42),
        }
        if HAS_XGB:
            models["XGB"] = XGBClassifier(n_estimators=500, max_depth=8, learning_rate=0.03,
                                           use_label_encoder=False, eval_metric="mlogloss",
                                           random_state=42, verbosity=0)

        best_ba = 0
        best_name = ""
        for mname, model in models.items():
            fold_ba = []
            all_preds = np.zeros(len(y_t), dtype=int)
            for train_idx, test_idx in sgkf.split(X_sel, y_t, g_cv2):
                m = type(model)(**model.get_params())
                m.fit(X_sel[train_idx], y_t[train_idx])
                preds = m.predict(X_sel[test_idx])
                all_preds[test_idx] = preds
                fold_ba.append(balanced_accuracy_score(y_t[test_idx], preds))

            mean_ba = np.mean(fold_ba)
            if mean_ba > best_ba:
                best_ba = mean_ba
                best_name = mname
                best_preds = all_preds
                best_std = np.std(fold_ba)
                best_f1 = f1_score(y_t, all_preds, average="macro")

        print(f"    {task_name:8s}: {best_name:10s} BalAcc={best_ba:.3f}+-{best_std:.3f} F1={best_f1:.3f}")

        if n_feat == 100:
            cm = confusion_matrix(y_t, best_preds)
            print(f"      Classes: {list(le_t.classes_)}")
            for row in cm:
                print(f"      {row}")

# ── Experiment 3: Epoch-normalized features ──────────────────────────────

print("\n" + "=" * 70)
print("EXPERIMENT 3: Epoch-normalized features (remove epoch shift)")
print("=" * 70)

X_normed = X_all.copy()
for epoch in df["__epoch"].unique():
    mask = epochs == epoch
    scaler = StandardScaler()
    X_normed.loc[mask] = scaler.fit_transform(X_normed.loc[mask]).astype(np.float32)

# Use top MI features from global
for n_feat in [50, 100, 200]:
    top_feats = mi_series.head(n_feat).index.tolist()
    X_sel = X_normed[top_feats].values

    print(f"\n  --- {n_feat} features (epoch-normalized) ---")
    for task_name, y_task in [("binary", y_binary), ("coarse", y_coarse)]:
        le_t = LabelEncoder()
        y_t = le_t.fit_transform(y_task)

        sgkf = StratifiedGroupKFold(n_splits=CV_SPLITS, shuffle=True, random_state=42)

        models = {
            "RF_bal": RandomForestClassifier(n_estimators=500, max_depth=15,
                                             class_weight="balanced", random_state=42, n_jobs=-1),
            "HGB_bal": HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                       class_weight="balanced", random_state=42),
        }
        if HAS_XGB:
            models["XGB"] = XGBClassifier(n_estimators=500, max_depth=8, learning_rate=0.03,
                                           use_label_encoder=False, eval_metric="mlogloss",
                                           random_state=42, verbosity=0)

        best_ba = 0
        best_name = ""
        for mname, model in models.items():
            fold_ba = []
            for train_idx, test_idx in sgkf.split(X_sel, y_t, groups):
                m = type(model)(**model.get_params())
                m.fit(X_sel[train_idx], y_t[train_idx])
                preds = m.predict(X_sel[test_idx])
                fold_ba.append(balanced_accuracy_score(y_t[test_idx], preds))
            mean_ba = np.mean(fold_ba)
            if mean_ba > best_ba:
                best_ba = mean_ba
                best_name = mname
                best_std = np.std(fold_ba)

        print(f"    {task_name:8s}: {best_name:10s} BalAcc={best_ba:.3f}+-{best_std:.3f}")

# ── Experiment 4: STATIC/MOTION subproblem deep dive ────────────────────

print("\n" + "=" * 70)
print("EXPERIMENT 4: STATIC/MOTION deep dive (occupied only)")
print("=" * 70)

mask_occ = y_binary == "OCCUPIED"
X_occ = X_all.loc[mask_occ]
y_sm = y_coarse[mask_occ]
g_occ = groups[mask_occ]

le_sm = LabelEncoder()
y_sm_enc = le_sm.fit_transform(y_sm)

# Recompute MI for this subproblem
print("  Computing MI for STATIC/MOTION...")
mi_sm = mutual_info_classif(X_occ.values, y_sm_enc, random_state=42, n_neighbors=5)
mi_sm_series = pd.Series(mi_sm, index=feature_cols).sort_values(ascending=False)

print(f"  Top 10 STATIC/MOTION discriminative features:")
for i, (fname, mival) in enumerate(mi_sm_series.head(10).items()):
    print(f"    {i+1:3d}. {fname:50s} MI={mival:.4f}")

for n_feat in [30, 50, 100, 200, 400]:
    top_feats = mi_sm_series.head(n_feat).index.tolist()
    X_sel = X_occ[top_feats].values

    sgkf = StratifiedGroupKFold(n_splits=CV_SPLITS, shuffle=True, random_state=42)

    models = {
        "RF_bal": RandomForestClassifier(n_estimators=500, max_depth=15,
                                         class_weight="balanced", random_state=42, n_jobs=-1),
        "HGB_bal": HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                   class_weight="balanced", random_state=42),
    }
    if HAS_XGB:
        models["XGB"] = XGBClassifier(n_estimators=500, max_depth=8, learning_rate=0.03,
                                       use_label_encoder=False, eval_metric="logloss",
                                       random_state=42, verbosity=0)

    best_ba = 0
    best_name = ""
    for mname, model in models.items():
        fold_ba = []
        all_preds = np.zeros(len(y_sm_enc), dtype=int)
        for train_idx, test_idx in sgkf.split(X_sel, y_sm_enc, g_occ):
            m = type(model)(**model.get_params())
            m.fit(X_sel[train_idx], y_sm_enc[train_idx])
            preds = m.predict(X_sel[test_idx])
            all_preds[test_idx] = preds
            fold_ba.append(balanced_accuracy_score(y_sm_enc[test_idx], preds))
        mean_ba = np.mean(fold_ba)
        if mean_ba > best_ba:
            best_ba = mean_ba
            best_name = mname
            best_std = np.std(fold_ba)
            best_preds_sm = all_preds

    print(f"  {n_feat:4d} feats: {best_name:10s} BalAcc={best_ba:.3f}+-{best_std:.3f}")

    if n_feat == 100:
        cm = confusion_matrix(y_sm_enc, best_preds_sm)
        print(f"    Classes: {list(le_sm.classes_)}")
        for row in cm:
            print(f"    {row}")
        print(classification_report(y_sm_enc, best_preds_sm, target_names=le_sm.classes_, digits=3))

# ── Summary ───────────────────────────────────────────────────────────────

elapsed = time.time() - t0
print("\n" + "=" * 70)
print(f"v13 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min)")
print("=" * 70)
