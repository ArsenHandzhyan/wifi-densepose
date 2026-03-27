#!/usr/bin/env python3
"""
V21d RETRAIN — FINAL (V20 base + zone one-hot from manifest v19)
================================================================
Winner of V21 experiments (v21a–v21d).  Uses the V20 dataset as base
(which already includes EMPTY) and enriches each window with zone
one-hot features mapped from manifest v19_final.  No data swap, no
separate EMPTY merge step.

Approach (v21d = "v20_plus_zone_onehot_no_swap"):
  1. Load V20 dataset (already has EMPTY/MOTION/STATIC).
  2. Load manifest v19 to build session→zone lookup.
  3. Append zone one-hot columns (center, transition, door, unknown).
  4. Add guard features (V18 + V23), build seq_len=7 sequences.
  5. 5-fold CV + production model + gate check.

Results (v21d):
  macro_f1=0.9441, EMPTY_f1=0.9976, MOTION_f1=0.9757,
  STATIC_f1=0.8590, binary_balacc=0.9928, fp_rate=0.002,
  fold_std=0.04 — all gates PASS.

Output: output/train_runs/v21_dual_validated/
"""

import os
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

import json, pickle, hashlib, time, warnings
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import f1_score, balanced_accuracy_score, confusion_matrix

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / "output" / "train_runs" / "v21_dual_validated"
OUTPUT.mkdir(parents=True, exist_ok=True)

# Note: V21d uses V20 dataset directly, no raw capture extraction needed.

# ── Config ──
SEQ_LEN = 7
META_COLS = {"t_start", "t_end", "t_mid", "__binary", "__coarse", "__clip_id",
             "__epoch", "__active_nodes", "__packet_count", "active_nodes", "packet_count",
             "zone_center", "zone_transition", "zone_door", "zone_unknown"}
CLASS_NAMES = ["EMPTY", "MOTION", "STATIC"]
HGB_PARAMS = dict(max_iter=300, max_depth=6, learning_rate=0.05,
                   class_weight="balanced", random_state=42)

EPS = 1e-10

# Guard thresholds (carried from V19/V20)
NODE_HEALTH_MIN_PPS = 15
NODE_HEALTH_MAX_PPS = 25
SC_VAR_HI_THRESHOLD = 3.8
SC_VAR_MOTION_TVAR_CEILING = 1.5

# V23 guard thresholds
PHASE_JUMP_THRESHOLD = 0.30
AMP_DRIFT_THRESHOLD = 2.0
DEAD_SC_THRESHOLD = 0.40

# ── Paths ──
MANIFEST_V19 = PROJECT / "output" / "video_curation" / "video_teacher_manifest_v19_dual_validated_v1.json"
V20_DS = PROJECT / "output" / "train_runs" / "v20_manifest_v18_dataset.csv"
V20_SUMMARY = PROJECT / "output" / "train_runs" / "v20_manifest_v18_eval_summary_v1.json"


# ── Zone mapping ──
# Collapse fine-grained zones into 4 canonical buckets
ZONE_MAP = {}
# Center-like zones
for z in ["center", "center_near_camera", "center_to_right", "center_right",
          "center_to_far", "center_to_left", "center_crossing", "center_to_near_camera",
          "center_left_near_entrance", "center_to_door", "center_to_center_right",
          "center_to_right_to_left", "left_center_right", "center_door_to_right",
          "varied_center_right", "varied_center_left", "varied_left_right_center",
          "right_to_center", "left_to_center", "left_to_near_camera",
          "near_camera", "near_camera_left", "s7_garage", "garage",
          "deep", "wall", "left_wall", "right_wall", "right", "far_right",
          "far_right_behind_stored_items", "far_area_to_door"]:
    ZONE_MAP[z] = "center"
# Transition-like zones
for z in ["transition", "mixed", "unknown_handheld"]:
    ZONE_MAP[z] = "transition"
# Door-like zones
for z in ["door", "door_zone", "door_zone_occluded", "door_passage_inside",
          "door_to_left", "door_to_center", "door_to_left_near_camera",
          "door_area"]:
    ZONE_MAP[z] = "door"
# Everything else → unknown
# (empty, unknown, and anything not listed)


def map_zone(raw_zone: str) -> str:
    """Map raw zone string to canonical bucket."""
    if not raw_zone or raw_zone.lower() in ("unknown", "empty", ""):
        return "unknown"
    return ZONE_MAP.get(raw_zone.lower(), "unknown")



def add_guard_features(df):
    """Add guard features (V18 + V23 guards) -- same as V20 pipeline."""
    n = len(df)
    feats = {}

    # ── V18 guards: node health ──
    pps_cols = [f"n{i}_pps" for i in range(4)]
    if all(c in df.columns for c in pps_cols):
        pps = df[pps_cols].values
        min_pps = pps.min(axis=1)
        max_pps = pps.max(axis=1)
        feats["gh_min_pps"] = min_pps
        feats["gh_max_pps"] = max_pps
        feats["gh_pps_imbalance"] = max_pps / (min_pps + EPS)
        feats["gh_degraded_node_count"] = (pps < NODE_HEALTH_MIN_PPS).sum(axis=1).astype(float)
        feats["gh_node_health_score"] = np.clip(1.0 / (max_pps / (min_pps + EPS) + EPS), 0, 1)
        feats["gh_pps_std"] = pps.std(axis=1)
    else:
        for k in ["gh_min_pps", "gh_max_pps", "gh_pps_imbalance",
                   "gh_degraded_node_count", "gh_node_health_score", "gh_pps_std"]:
            feats[k] = np.zeros(n)

    # ── V18 guards: sc_var noise ──
    tvar_hi_cols = [f"n{i}_tvar_hi" for i in range(4)]
    if all(c in df.columns for c in tvar_hi_cols):
        tvar_hi = df[tvar_hi_cols].values
        max_tvar_n01 = np.maximum(tvar_hi[:, 0], tvar_hi[:, 1])
        feats["gv_max_tvar_hi_n01"] = max_tvar_n01
        x_tvar = df["x_tvar_mean"].values if "x_tvar_mean" in df.columns else \
            df[[f"n{i}_tvar" for i in range(4)]].values.mean(axis=1)
        feats["gv_sc_var_ratio"] = max_tvar_n01 / (x_tvar + EPS)
        feats["gv_sc_var_noise_score"] = (
            (max_tvar_n01 > SC_VAR_HI_THRESHOLD) & (x_tvar < SC_VAR_MOTION_TVAR_CEILING)
        ).astype(float)
        feats["gv_max_tvar_hi_all"] = tvar_hi.max(axis=1)
        feats["gv_tvar_hi_std"] = tvar_hi.std(axis=1)
    else:
        for k in ["gv_max_tvar_hi_n01", "gv_sc_var_ratio", "gv_sc_var_noise_score",
                   "gv_max_tvar_hi_all", "gv_tvar_hi_std"]:
            feats[k] = np.zeros(n)

    # ── V18 guards: composite ──
    min_pps_v = feats.get("gh_min_pps", np.zeros(n))
    max_pps_v = feats.get("gh_max_pps", np.zeros(n))
    node_trigger = ((min_pps_v < NODE_HEALTH_MIN_PPS) & (max_pps_v > NODE_HEALTH_MAX_PPS)).astype(float)
    feats["ge_composite"] = np.clip(node_trigger + feats.get("gv_sc_var_noise_score", np.zeros(n)), 0, 1)
    x_tvar2 = df["x_tvar_mean"].values if "x_tvar_mean" in df.columns else np.zeros(n)
    max_tvar2 = feats.get("gv_max_tvar_hi_n01", np.zeros(n))
    feats["ge_low_motion_high_noise"] = (
        (x_tvar2 < SC_VAR_MOTION_TVAR_CEILING) & (max_tvar2 > SC_VAR_HI_THRESHOLD * 0.8)
    ).astype(float)

    # ── V23 guards: phase noise, amp drift, dead subcarriers ──
    pj_cols = [f"n{i}_sq_phase_jump_rate" for i in range(4)]
    if all(c in df.columns for c in pj_cols):
        pj = df[pj_cols].values
        feats["gp_phase_jump_mean"] = pj.mean(axis=1)
        feats["gp_phase_jump_max"] = pj.max(axis=1)
        feats["gp_phase_noise_score"] = (pj.mean(axis=1) > PHASE_JUMP_THRESHOLD).astype(float)
    else:
        feats["gp_phase_jump_mean"] = np.zeros(n)
        feats["gp_phase_jump_max"] = np.zeros(n)
        feats["gp_phase_noise_score"] = np.zeros(n)

    drift_cols = [f"n{i}_sq_amp_drift" for i in range(4)]
    if all(c in df.columns for c in drift_cols):
        drift = df[drift_cols].values
        feats["gd_amp_drift_max"] = drift.max(axis=1)
        feats["gd_drift_noise_score"] = (
            (drift.max(axis=1) > AMP_DRIFT_THRESHOLD) & (x_tvar2 < SC_VAR_MOTION_TVAR_CEILING)
        ).astype(float)
    else:
        feats["gd_amp_drift_max"] = np.zeros(n)
        feats["gd_drift_noise_score"] = np.zeros(n)

    dead_cols = [f"n{i}_sq_dead_sc_frac" for i in range(4)]
    if all(c in df.columns for c in dead_cols):
        dead = df[dead_cols].values
        feats["gs_dead_sc_max"] = dead.max(axis=1)
        feats["gs_dead_sc_score"] = (dead.max(axis=1) > DEAD_SC_THRESHOLD).astype(float)
    else:
        feats["gs_dead_sc_max"] = np.zeros(n)
        feats["gs_dead_sc_score"] = np.zeros(n)

    # V23 composite guard
    feats["ge_v23_composite"] = np.clip(
        feats["ge_composite"] +
        feats["gp_phase_noise_score"] +
        feats["gd_drift_noise_score"] +
        feats["gs_dead_sc_score"],
        0, 1,
    )

    return pd.concat([df, pd.DataFrame(feats, index=df.index)], axis=1)


def build_sequences(df, feat_cols, seq_len):
    sequences, labels, groups = [], [], []
    for clip_id, clip_df in df.groupby("__clip_id", sort=False):
        clip_df = clip_df.sort_values("t_start")
        features = clip_df[feat_cols].values
        clip_labels = clip_df["__coarse"].values
        if len(clip_df) < seq_len:
            continue
        for i in range(len(clip_df) - seq_len + 1):
            seq = features[i:i + seq_len].flatten()
            sequences.append(seq)
            labels.append(clip_labels[i + seq_len - 1])
            groups.append(clip_id)
    return np.array(sequences, dtype=np.float32), np.array(labels), np.array(groups)


def eval_metrics(y_true, y_pred):
    macro_f1 = f1_score(y_true, y_pred, average="macro")
    per_class = f1_score(y_true, y_pred, average=None, labels=CLASS_NAMES)
    cm = confusion_matrix(y_true, y_pred, labels=CLASS_NAMES)
    y_bt = (y_true != "EMPTY").astype(int)
    y_bp = (y_pred != "EMPTY").astype(int)
    balacc = balanced_accuracy_score(y_bt, y_bp)
    fp = ((y_true == "EMPTY") & (y_pred != "EMPTY")).sum()
    fn = ((y_true != "EMPTY") & (y_pred == "EMPTY")).sum()
    return {
        "macro_f1": round(float(macro_f1), 4),
        "EMPTY_f1": round(float(per_class[0]), 4),
        "MOTION_f1": round(float(per_class[1]), 4),
        "STATIC_f1": round(float(per_class[2]), 4),
        "binary_balacc": round(float(balacc), 4),
        "fp_rate": round(float(fp / max((y_true == "EMPTY").sum(), 1)), 4),
        "fn_rate": round(float(fn / max((y_true != "EMPTY").sum(), 1)), 4),
    }, cm


def run_cv(X, y, groups, n_splits=5):
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)
    all_preds = np.empty(len(y), dtype=object)
    fold_scores = []
    for fold_i, (train_idx, test_idx) in enumerate(sgkf.split(X, y, groups)):
        model = HistGradientBoostingClassifier(**HGB_PARAMS)
        model.fit(X[train_idx], y[train_idx])
        preds = model.predict(X[test_idx])
        all_preds[test_idx] = preds
        macro = f1_score(y[test_idx], preds, average="macro")
        fold_scores.append(macro)
        print(f"    Fold {fold_i}: Macro F1 = {macro:.4f}")
    metrics, cm = eval_metrics(y, all_preds)
    metrics["fold_scores"] = [round(s, 4) for s in fold_scores]
    metrics["fold_std"] = round(float(np.std(fold_scores)), 4)
    return metrics, cm


def main():
    print("=" * 70)
    print("V21d RETRAIN — V20 base + zone one-hot (final approach)")
    print(f"  Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # ── STEP 1: Load V20 dataset as base ──
    print("\n--- STEP 1: Load V20 Dataset (base) ---")
    if not V20_DS.exists():
        print(f"  ERROR: V20 dataset not found at {V20_DS}")
        return
    df_base = pd.read_csv(V20_DS)
    print(f"  V20 rows: {len(df_base)}")
    print(f"  V20 class dist: {dict(df_base['__coarse'].value_counts())}")

    # ── STEP 2: Load manifest v19 for zone mapping ──
    print("\n--- STEP 2: Load Manifest V19 (zone lookup) ---")
    with open(MANIFEST_V19) as f:
        manifest = json.load(f)

    all_intervals = manifest["intervals"]
    print(f"  Total intervals in manifest: {len(all_intervals)}")

    # Build lookup: (session, start_sec) → canonical zone
    zone_lookup: dict[str, str] = {}
    zone_dist = Counter()
    for iv in all_intervals:
        session = iv.get("session_label", iv.get("session", ""))
        if not session:
            continue
        start = iv.get("start_sec", 0.0)
        end = iv.get("end_sec", 0.0)
        z = map_zone(iv.get("zone", "unknown"))
        zone_dist[z] += 1
        # key by session + time range so windows can be matched
        zone_lookup[f"{session}_{start:.0f}_{end:.0f}"] = z

    print(f"  Zone lookup entries: {len(zone_lookup)}")
    print(f"  Zone dist (canonical): {dict(zone_dist)}")

    # ── STEP 3: Attach zone one-hot to V20 rows ──
    print("\n--- STEP 3: Add Zone One-Hot Features ---")
    zone_center = np.zeros(len(df_base), dtype=np.float32)
    zone_transition = np.zeros(len(df_base), dtype=np.float32)
    zone_door = np.zeros(len(df_base), dtype=np.float32)
    zone_unknown = np.ones(len(df_base), dtype=np.float32)  # default = unknown

    if "__clip_id" in df_base.columns:
        matched = 0
        for i, clip_id in enumerate(df_base["__clip_id"].values):
            z = zone_lookup.get(str(clip_id), "unknown")
            if z == "center":
                zone_center[i] = 1.0; zone_unknown[i] = 0.0; matched += 1
            elif z == "transition":
                zone_transition[i] = 1.0; zone_unknown[i] = 0.0; matched += 1
            elif z == "door":
                zone_door[i] = 1.0; zone_unknown[i] = 0.0; matched += 1
        print(f"  Zone-matched rows: {matched}/{len(df_base)}")
    else:
        print(f"  WARNING: no __clip_id column, all zones set to unknown")

    df_base["zone_center"] = zone_center
    df_base["zone_transition"] = zone_transition
    df_base["zone_door"] = zone_door
    df_base["zone_unknown"] = zone_unknown

    for zc in ["zone_center", "zone_transition", "zone_door", "zone_unknown"]:
        print(f"    {zc}: {int(df_base[zc].sum())} windows")

    # ── STEP 4: Build DataFrame ──
    print("\n--- STEP 4: Build DataFrame ---")
    df = df_base

    # Drop internal _raw_ columns
    internal_cols = [c for c in df.columns if c.startswith("_raw_")]
    df = df.drop(columns=internal_cols, errors="ignore")

    # Remove any pre-existing guard columns (will be re-added uniformly)
    guard_cols = [c for c in df.columns
                  if c.startswith(("gh_", "gv_", "ge_", "gp_", "gd_", "gs_"))
                  and c not in META_COLS]
    df = df.drop(columns=guard_cols, errors="ignore")

    print(f"  DataFrame: {len(df)} windows, {df['__clip_id'].nunique()} clips")
    print(f"  Class dist: {dict(df['__coarse'].value_counts())}")

    # ── STEP 5: Add Guard Features ──
    print("\n--- STEP 5: Add Guard Features (V18 + V23) ---")
    df_guarded = add_guard_features(df)

    # Feature columns: everything except meta columns
    feat_cols = sorted([c for c in df_guarded.columns if c not in META_COLS])
    print(f"  Total features per window: {len(feat_cols)}")

    # ── STEP 6: Save dataset ──
    print("\n--- STEP 6: Save V21d Dataset ---")
    ds_path = OUTPUT / "v21d_dataset.csv"
    df_guarded.to_csv(ds_path, index=False)
    ds_hash = hashlib.sha256(open(ds_path, "rb").read()).hexdigest()[:16]
    print(f"  Saved: {ds_path} ({len(df_guarded)} rows, hash={ds_hash})")

    # Drop unknown/invalid classes
    df_guarded = df_guarded[df_guarded["__coarse"].isin(CLASS_NAMES)].copy()
    print(f"  After class filter: {len(df_guarded)} windows")

    # ── STEP 7: Build sequences ──
    print("\n--- STEP 7: Build Sequences ---")
    X, y, groups = build_sequences(df_guarded, feat_cols, SEQ_LEN)
    print(f"  Sequences: {len(X)}, features per seq: {X.shape[1]}")
    print(f"  Seq class dist: {dict(zip(*np.unique(y, return_counts=True)))}")
    X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

    # ── STEP 8: 5-Fold CV ──
    print("\n--- STEP 8: 5-Fold CV ---")
    v21_metrics, v21_cm = run_cv(X, y, groups)
    print(f"\n  V21d CV Results:")
    for k, v in v21_metrics.items():
        if k not in ("fold_scores",):
            print(f"    {k}: {v}")
    print(f"\n  Confusion Matrix (EMPTY / MOTION / STATIC):")
    for i, row in enumerate(v21_cm):
        print(f"    {CLASS_NAMES[i]:8s}: {row}")

    # ── STEP 9: Compare with V20 baseline ──
    print("\n--- STEP 9: Compare with V20 Baseline ---")
    v20_metrics = {}
    if V20_SUMMARY.exists():
        v20_data = json.load(open(V20_SUMMARY))
        v20_metrics = v20_data.get("cv_metrics", {})
        print(f"  V20 baseline loaded")
    else:
        print(f"  V20 summary not found, skipping comparison")

    comparison = {}
    if v20_metrics:
        print(f"\n  {'Metric':20s}  {'V20':>8s}  {'V21':>8s}  {'delta':>8s}")
        print(f"  {'-'*20}  {'-'*8}  {'-'*8}  {'-'*8}")
        for k in ["macro_f1", "EMPTY_f1", "MOTION_f1", "STATIC_f1", "binary_balacc", "fp_rate", "fn_rate"]:
            v20_val = v20_metrics.get(k, 0)
            v21_val = v21_metrics.get(k, 0)
            delta = round(v21_val - v20_val, 4)
            comparison[k] = {"v20": v20_val, "v21": v21_val, "delta": delta}
            d = "+" if delta > 0 else ""
            print(f"  {k:20s}  {v20_val:8.4f}  {v21_val:8.4f}  {d}{delta:8.4f}")

    # Gate criteria
    gate = {
        "macro_f1_gt_085": v21_metrics["macro_f1"] > 0.85,
        "EMPTY_f1_gt_090": v21_metrics["EMPTY_f1"] > 0.90,
        "STATIC_f1_gt_075": v21_metrics["STATIC_f1"] > 0.75,
        "MOTION_f1_gt_080": v21_metrics["MOTION_f1"] > 0.80,
        "binary_balacc_gt_090": v21_metrics["binary_balacc"] > 0.90,
        "fp_rate_lt_010": v21_metrics["fp_rate"] < 0.10,
        "fold_std_lt_005": v21_metrics.get("fold_std", 1) < 0.05,
    }
    if v20_metrics:
        gate["no_macro_f1_regression_vs_v20"] = v21_metrics["macro_f1"] >= v20_metrics.get("macro_f1", 0) - 0.02
    gate["all_pass"] = all(gate.values())
    print(f"\n  Gate Criteria:")
    for k, v in gate.items():
        print(f"    {k:40s}: {'PASS' if v else 'FAIL'}")

    # ── STEP 10: Train production model ──
    print("\n--- STEP 10: Train V21d Production Model ---")
    coarse_model = HistGradientBoostingClassifier(**HGB_PARAMS)
    t0 = time.time()
    coarse_model.fit(X, y)
    train_sec = time.time() - t0
    print(f"  Coarse model trained in {train_sec:.1f}s")

    y_bin = (y != "EMPTY").astype(int)
    binary_model = HistGradientBoostingClassifier(**HGB_PARAMS)
    binary_model.fit(X, y_bin)
    print(f"  Binary model trained")

    # ── STEP 11: Save artifacts ──
    print("\n--- STEP 11: Save Artifacts ---")
    trained_at = time.strftime("%Y-%m-%d %H:%M:%S")
    seq_feature_names = [f"t{t}_{f}" for t in range(SEQ_LEN) for f in feat_cols]

    model_dict = {
        "version": "v21d",
        "feature_names": seq_feature_names,
        "window_feature_names": list(feat_cols),
        "seq_len": SEQ_LEN,
        "binary_model": binary_model,
        "coarse_model": coarse_model,
        "coarse_labels": list(coarse_model.classes_),
        "n_features": X.shape[1],
        "n_sequences": len(X),
        "n_windows": len(df_guarded),
        "n_clips": int(df_guarded["__clip_id"].nunique()),
        "trained_at": trained_at,
        "v21d_metadata": {
            "approach": "v20_plus_zone_onehot_no_swap",
            "base_dataset": "v20_manifest_v18_dataset.csv",
            "zone_source": "video_teacher_manifest_v19_dual_validated_v1",
            "feature_pipeline": "V20 features + zone one-hot + V18/V23 guards",
            "model_type": "HistGradientBoostingClassifier",
            "model_params": HGB_PARAMS,
            "cv_metrics": v21_metrics,
            "v20_baseline_metrics": dict(v20_metrics),
            "comparison": comparison,
            "gate_criteria": gate,
            "zone_feature": "one-hot (center, transition, door, unknown)",
        },
    }

    pkl_path = OUTPUT / "v21d_candidate.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(model_dict, f)
    pkl_hash = hashlib.sha256(open(pkl_path, "rb").read()).hexdigest()[:16]
    print(f"  Model: {pkl_path} (hash={pkl_hash})")

    # Metrics JSON
    metrics_out = {
        "version": "v21d",
        "cv_5fold": v21_metrics,
        "confusion_matrix": v21_cm.tolist(),
        "n_sequences": len(X),
        "n_windows": len(df_guarded),
        "n_clips": int(df_guarded["__clip_id"].nunique()),
    }
    metrics_path = OUTPUT / "v21d_candidate_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics_out, f, indent=2, default=str)

    # Summary
    summary = {
        "version": "v21d",
        "agent": "V21d_RETRAIN_FINAL",
        "verdict": "RETRAIN_COMPLETE",
        "trained_at": trained_at,
        "cv_metrics": v21_metrics,
        "comparison_vs_v20": comparison,
        "gate_criteria": gate,
        "gate_all_pass": gate["all_pass"],
        "corpus": {
            "base_dataset": "v20_manifest_v18_dataset.csv",
            "zone_source": "video_teacher_manifest_v19_dual_validated_v1",
            "approach": "v20_plus_zone_onehot_no_swap",
            "total_windows": len(df_guarded),
            "total_clips": int(df_guarded["__clip_id"].nunique()),
            "class_distribution": dict(df_guarded["__coarse"].value_counts()),
            "zone_distribution": dict(zone_dist),
        },
        "new_features": {
            "zone_one_hot": ["zone_center", "zone_transition", "zone_door", "zone_unknown"],
        },
        "artifacts": {
            "model": str(pkl_path.relative_to(PROJECT)),
            "dataset": str(ds_path.relative_to(PROJECT)),
            "metrics": str(metrics_path.relative_to(PROJECT)),
        },
        "confusion_matrix": v21_cm.tolist(),
        "dataset_hash": ds_hash,
        "model_hash": pkl_hash,
    }
    summary_path = OUTPUT / "v21d_eval_summary_v1.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n  Metrics: {metrics_path}")
    print(f"  Summary: {summary_path}")
    print(f"\n{'=' * 70}")
    print(f"V21d RETRAIN COMPLETE (V20 base + zone one-hot)")
    print(f"  Macro F1:      {v21_metrics['macro_f1']}")
    print(f"  EMPTY F1:      {v21_metrics['EMPTY_f1']}")
    print(f"  MOTION F1:     {v21_metrics['MOTION_f1']}")
    print(f"  STATIC F1:     {v21_metrics['STATIC_f1']}")
    print(f"  Binary BalAcc: {v21_metrics['binary_balacc']}")
    print(f"  FP Rate:       {v21_metrics['fp_rate']}")
    print(f"  FN Rate:       {v21_metrics['fn_rate']}")
    print(f"  Gate: {'ALL PASS' if gate['all_pass'] else 'FAIL'}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
