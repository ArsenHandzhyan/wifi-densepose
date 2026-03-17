#!/usr/bin/env python3
"""
V12 CSI Motion Pipeline — Rich Features + Honest Labels

KEY IDEA: Combine best of both research tracks:
  - Track A (v4 cache): 1844 rich features from 219 clips
  - Track B (v8): Honest label strategy (manual > scripted > YOLO-max)

The v4 cache already has scripted labels from step_name (__ln column).
We trust those because they come from controlled capture scripts.
We ALSO add the Track B manual annotations for longcap chunks and multi-person.

Experiments:
  1. All v4-cache clips with scripted labels (1844 features, ~219 clips)
  2. Top-N MI features (50, 100, 200, 400)
  3. Only ceiling_v2 epoch (most consistent data)
  4. Anomaly detection for STATIC
"""

import pickle, json, time, warnings, sys
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parents[1]
t0 = time.time()

print("=" * 70)
print("CSI Motion Pipeline v12 — Rich Features + Honest Labels")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ── 1. Load v4 cache ──────────────────────────────────────────────────────

print("\n[Phase 1] Loading v4 cache (1844 features, 6134 windows)...")
df = pickle.load(open(PROJECT / "output/csi_pipeline_v4_results/dataset_v4_cache.pkl", "rb"))
print(f"  Shape: {df.shape}")

meta_cols = [c for c in df.columns if c.startswith("__")]
feature_cols = [c for c in df.columns if not c.startswith("__")]
print(f"  Features: {len(feature_cols)}, Meta: {len(meta_cols)}")

# ── 2. Build honest labels ────────────────────────────────────────────────

print("\n[Phase 2] Building honest labels from __ln (step_name)...")

# Map step_name (__ln) to binary/coarse labels
def ln_to_labels(ln):
    """Convert __ln (step_name) to (binary, coarse) labels."""
    ln = ln.lower().strip()

    # EMPTY patterns
    if any(x in ln for x in ["empty", "empty_room", "empty_room_pre", "empty_room_post",
                              "empty_room_clean", "empty_room_settled",
                              "empty_baseline", "empty_recalibrated"]):
        return "EMPTY", "EMPTY"

    # STATIC patterns (person present, minimal movement)
    if any(x in ln for x in ["quiet_static", "static", "hold_object_static",
                              "lift_object_static", "normal_breath", "deep_breath",
                              "sit_down_hold", "stand_up_hold", "sit_down",
                              "occupied_sit", "occupied_stand", "breathing",
                              "reposition_object_rotate", "reposition_object_place",
                              "set_object_down", "place_obstacle"]):
        return "OCCUPIED", "STATIC"

    # MOTION patterns (active movement)
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

    # Multi-person patterns
    if any(x in ln for x in ["multiple_people", "two_person", "three_person", "four_person"]):
        return "OCCUPIED", "STATIC"  # reference captures were static

    # Fallback: if label contains "occupied" -> STATIC (conservative)
    if "occupied" in ln:
        return "OCCUPIED", "STATIC"

    return None, None  # unknown — skip

# Apply labels
df["binary"] = None
df["coarse"] = None
skipped = Counter()

for idx, row in df.iterrows():
    b, c = ln_to_labels(row["__ln"])
    if b is None:
        skipped[row["__ln"]] += 1
    df.at[idx, "binary"] = b
    df.at[idx, "coarse"] = c

# Drop unknowns
n_before = len(df)
df = df.dropna(subset=["binary"])
print(f"  Labeled: {len(df)}/{n_before} windows")
if skipped:
    print(f"  Skipped labels: {dict(skipped.most_common(10))}")

print(f"\n  Label distribution:")
print(f"    Binary: {dict(Counter(df['binary']))}")
print(f"    Coarse: {dict(Counter(df['coarse']))}")

# ── 3. Feature cleaning ───────────────────────────────────────────────────

print("\n[Phase 3] Cleaning features...")

# Drop constant/near-constant features
X = df[feature_cols].copy()
X = X.replace([np.inf, -np.inf], np.nan)
X = X.fillna(0)

# Drop features with near-zero variance
from sklearn.preprocessing import StandardScaler
variances = X.var()
low_var = variances[variances < 1e-10].index.tolist()
X = X.drop(columns=low_var)
feature_cols_clean = list(X.columns)
print(f"  Dropped {len(low_var)} near-zero variance features")
print(f"  Remaining features: {len(feature_cols_clean)}")

y_binary = df["binary"].values
y_coarse = df["coarse"].values
groups = df["__clip_id"].values

# ── 4. Feature selection with MI ──────────────────────────────────────────

print("\n[Phase 4] Mutual Information feature selection...")
from sklearn.feature_selection import mutual_info_classif
from sklearn.preprocessing import LabelEncoder

le = LabelEncoder()
y_enc = le.fit_transform(y_coarse)

# Compute MI for coarse task (most discriminative)
mi = mutual_info_classif(X, y_enc, random_state=42, n_neighbors=5)
mi_series = pd.Series(mi, index=feature_cols_clean).sort_values(ascending=False)

print(f"  Top 20 MI features:")
for i, (fname, mival) in enumerate(mi_series.head(20).items()):
    print(f"    {i+1:3d}. {fname:50s} MI={mival:.4f}")

# ── 5. Train models at different feature counts ──────────────────────────

print("\n[Phase 5] Training models...")
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, IsolationForest
from sklearn.metrics import balanced_accuracy_score, f1_score, classification_report, confusion_matrix
from sklearn.neural_network import MLPClassifier

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

FEATURE_COUNTS = [30, 50, 100, 200, 400, 800, len(feature_cols_clean)]
CV_SPLITS = 5

results = []

for n_feat in FEATURE_COUNTS:
    if n_feat > len(feature_cols_clean):
        n_feat = len(feature_cols_clean)

    top_feats = mi_series.head(n_feat).index.tolist()
    X_sel = X[top_feats].values

    print(f"\n  --- {n_feat} features ---")

    for task_name, y_task in [("binary", y_binary), ("coarse", y_coarse)]:
        le_task = LabelEncoder()
        y_enc_task = le_task.fit_transform(y_task)
        classes = le_task.classes_

        sgkf = StratifiedGroupKFold(n_splits=CV_SPLITS, shuffle=True, random_state=42)

        models = {
            "HGB": HistGradientBoostingClassifier(max_iter=300, max_depth=6, learning_rate=0.05, random_state=42),
            "RF": RandomForestClassifier(n_estimators=300, max_depth=12, random_state=42, n_jobs=-1),
        }
        if HAS_XGB:
            models["XGB"] = XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                                           use_label_encoder=False, eval_metric="mlogloss",
                                           random_state=42, verbosity=0)
        if HAS_LGB:
            models["LGB"] = LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                                            random_state=42, verbose=-1)

        best_ba = 0
        best_model_name = ""
        best_preds = None

        for mname, model in models.items():
            fold_ba = []
            all_preds = np.zeros(len(y_enc_task), dtype=int)

            for train_idx, test_idx in sgkf.split(X_sel, y_enc_task, groups):
                model_clone = type(model)(**model.get_params())
                model_clone.fit(X_sel[train_idx], y_enc_task[train_idx])
                preds = model_clone.predict(X_sel[test_idx])
                all_preds[test_idx] = preds
                ba = balanced_accuracy_score(y_enc_task[test_idx], preds)
                fold_ba.append(ba)

            mean_ba = np.mean(fold_ba)
            std_ba = np.std(fold_ba)
            f1 = f1_score(y_enc_task, all_preds, average="macro")

            if mean_ba > best_ba:
                best_ba = mean_ba
                best_model_name = mname
                best_preds = all_preds
                best_std = std_ba
                best_f1 = f1

            results.append({
                "n_feat": n_feat, "task": task_name, "model": mname,
                "bal_acc": mean_ba, "std": std_ba, "f1": f1
            })

        print(f"    {task_name:8s}: best={best_model_name} BalAcc={best_ba:.3f}+-{best_std:.3f} F1={best_f1:.3f}")

        # Print confusion for best config
        if n_feat == 200 or n_feat == len(feature_cols_clean):
            print(f"      Confusion ({best_model_name}, {task_name}):")
            cm = confusion_matrix(y_enc_task, best_preds)
            print(f"      Classes: {list(classes)}")
            for row in cm:
                print(f"      {row}")
            print(classification_report(y_enc_task, best_preds, target_names=classes, digits=3))

# ── 6. STATIC/MOTION subproblem ──────────────────────────────────────────

print("\n[Phase 6] Hierarchical STATIC/MOTION (occupied only)...")
mask_occ = y_binary == "OCCUPIED"
X_occ = X.loc[mask_occ]
y_sm = y_coarse[mask_occ]
groups_occ = groups[mask_occ]

for n_feat in [100, 200, 400]:
    top_feats = mi_series.head(n_feat).index.tolist()
    X_sel = X_occ[top_feats].values
    le_sm = LabelEncoder()
    y_enc_sm = le_sm.fit_transform(y_sm)

    sgkf = StratifiedGroupKFold(n_splits=CV_SPLITS, shuffle=True, random_state=42)

    models = {
        "HGB": HistGradientBoostingClassifier(max_iter=300, max_depth=6, learning_rate=0.05, random_state=42),
        "XGB": XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                             use_label_encoder=False, eval_metric="logloss",
                             random_state=42, verbosity=0) if HAS_XGB else None,
    }
    models = {k: v for k, v in models.items() if v is not None}

    best_ba = 0
    best_name = ""
    for mname, model in models.items():
        fold_ba = []
        for train_idx, test_idx in sgkf.split(X_sel, y_enc_sm, groups_occ):
            m = type(model)(**model.get_params())
            m.fit(X_sel[train_idx], y_enc_sm[train_idx])
            preds = m.predict(X_sel[test_idx])
            fold_ba.append(balanced_accuracy_score(y_enc_sm[test_idx], preds))
        ba = np.mean(fold_ba)
        if ba > best_ba:
            best_ba = ba
            best_name = mname
    print(f"  {n_feat:4d} feats: {best_name} STATIC/MOTION BalAcc={best_ba:.3f}")

# ── 7. Epoch-specific analysis ────────────────────────────────────────────

print("\n[Phase 7] Epoch-specific results...")
for epoch in df["__epoch"].unique():
    mask_ep = df["__epoch"] == epoch
    X_ep = X.loc[mask_ep]
    y_ep_b = y_binary[mask_ep]
    y_ep_c = y_coarse[mask_ep]
    g_ep = groups[mask_ep]

    if len(np.unique(y_ep_b)) < 2 or len(np.unique(g_ep)) < CV_SPLITS:
        print(f"  {epoch}: skipped (not enough classes/groups)")
        continue

    top_feats = mi_series.head(200).index.tolist()
    X_sel = X_ep[top_feats].values

    # Binary
    le_b = LabelEncoder()
    y_enc_b = le_b.fit_transform(y_ep_b)
    sgkf = StratifiedGroupKFold(n_splits=min(CV_SPLITS, len(np.unique(g_ep))), shuffle=True, random_state=42)
    fold_ba = []
    for train_idx, test_idx in sgkf.split(X_sel, y_enc_b, g_ep):
        m = HistGradientBoostingClassifier(max_iter=300, max_depth=6, learning_rate=0.05, random_state=42)
        m.fit(X_sel[train_idx], y_enc_b[train_idx])
        fold_ba.append(balanced_accuracy_score(y_enc_b[test_idx], m.predict(X_sel[test_idx])))
    ba_b = np.mean(fold_ba)

    # Coarse
    le_c = LabelEncoder()
    y_enc_c = le_c.fit_transform(y_ep_c)
    if len(np.unique(y_enc_c)) >= 2:
        fold_ba_c = []
        for train_idx, test_idx in sgkf.split(X_sel, y_enc_c, g_ep):
            m = HistGradientBoostingClassifier(max_iter=300, max_depth=6, learning_rate=0.05, random_state=42)
            m.fit(X_sel[train_idx], y_enc_c[train_idx])
            fold_ba_c.append(balanced_accuracy_score(y_enc_c[test_idx], m.predict(X_sel[test_idx])))
        ba_c = np.mean(fold_ba_c)
    else:
        ba_c = 0

    dist_b = dict(Counter(y_ep_b))
    dist_c = dict(Counter(y_ep_c))
    print(f"  {epoch:25s}: {len(X_ep):5d} win, binary={ba_b:.3f}, coarse={ba_c:.3f}")
    print(f"    binary dist: {dist_b}")
    print(f"    coarse dist: {dist_c}")

# ── 8. Anomaly detection (EMPTY baseline → detect STATIC) ────────────────

print("\n[Phase 8] Anomaly detection for STATIC...")
top200 = mi_series.head(200).index.tolist()

X_empty = X.loc[y_binary == "EMPTY", top200].values
X_static = X.loc[y_coarse == "STATIC", top200].values
X_motion = X.loc[y_coarse == "MOTION", top200].values

if len(X_empty) > 50:
    iso = IsolationForest(contamination=0.15, random_state=42, n_estimators=200)
    iso.fit(X_empty)

    # Score all windows
    for name, Xsub in [("EMPTY", X_empty), ("STATIC", X_static), ("MOTION", X_motion)]:
        preds = iso.predict(Xsub)
        n_anomaly = (preds == -1).sum()
        print(f"  {name:8s}: {n_anomaly}/{len(Xsub)} anomalies ({100*n_anomaly/len(Xsub):.1f}%)")

    # Use as STATIC detector: anomaly on EMPTY model = presence
    X_occ_anom = np.vstack([X_static, X_motion])
    y_occ_anom = np.array(["STATIC"]*len(X_static) + ["MOTION"]*len(X_motion))
    preds_occ = iso.predict(X_occ_anom)
    detected = preds_occ == -1

    # Among detected anomalies, what fraction is STATIC vs MOTION?
    for cls in ["STATIC", "MOTION"]:
        mask_cls = y_occ_anom == cls
        recall = detected[mask_cls].sum() / mask_cls.sum()
        print(f"  Anomaly recall for {cls}: {recall:.3f} ({detected[mask_cls].sum()}/{mask_cls.sum()})")

# ── 9. Summary ────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("FINAL SUMMARY — v12 Rich Features + Honest Labels")
print("=" * 70)

res_df = pd.DataFrame(results)
for task in ["binary", "coarse"]:
    task_res = res_df[res_df["task"] == task]
    best_row = task_res.loc[task_res["bal_acc"].idxmax()]
    print(f"  {task:8s}: BEST = {best_row['model']} @ {int(best_row['n_feat'])} feats -> "
          f"BalAcc={best_row['bal_acc']:.3f}+-{best_row['std']:.3f} F1={best_row['f1']:.3f}")

# Save results
outdir = PROJECT / "output" / "csi_pipeline_v12_results"
outdir.mkdir(parents=True, exist_ok=True)
res_df.to_csv(outdir / "v12_sweep_results.csv", index=False)

# Save summary JSON
summary = {
    "pipeline": "v12_rich_honest",
    "timestamp": time.strftime("%Y%m%d_%H%M%S"),
    "total_windows": len(df),
    "total_features": len(feature_cols_clean),
    "total_clips": int(df["__clip_id"].nunique()),
    "label_dist_binary": dict(Counter(y_binary)),
    "label_dist_coarse": dict(Counter(y_coarse)),
    "results": results,
    "runtime_sec": time.time() - t0,
}
with open(outdir / "results_summary_v12.json", "w") as f:
    json.dump(summary, f, indent=2, default=str)

elapsed = time.time() - t0
print(f"\nTotal runtime: {elapsed:.1f}s ({elapsed/60:.1f} min)")
print("Done.")
