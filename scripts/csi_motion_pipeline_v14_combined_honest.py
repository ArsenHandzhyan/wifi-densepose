#!/usr/bin/env python3
"""
V14 CSI Motion Pipeline — Combined Honest Labels + Rich Features

STRATEGY: Merge ALL honestly-labeled data with 1844 rich features:
  1. V4 cache (219 clips, scripted labels from step_name) — 1844 features precomputed
  2. Track B manual annotations (23 clips, hand-labeled) — extract 1844 features
  3. Session 20260318 (6 new chunks, annotated) — extract 1844 features

This tests whether combining both pools beats either alone.

Track B v8 best: Binary=0.80 (27 clips, 40 features)
V12 best: Binary=0.708, Coarse=0.673 (219 clips, MI-selected from 1844)
"""

import pickle, gzip, json, base64, time, warnings, sys
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parents[1]
CAPTURES = PROJECT / "temp" / "captures"
t0 = time.time()

print("=" * 70)
print("CSI Motion Pipeline v14 — Combined Honest Labels + Rich Features")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ══════════════════════════════════════════════════════════════════════════
# PART A: Load v4 cache (pre-extracted 1844 features)
# ══════════════════════════════════════════════════════════════════════════

print("\n[A] Loading v4 cache...")
df_v4 = pickle.load(open(PROJECT / "output/csi_pipeline_v4_results/dataset_v4_cache.pkl", "rb"))
meta_cols = [c for c in df_v4.columns if c.startswith("__")]
feature_cols = [c for c in df_v4.columns if not c.startswith("__")]
print(f"  V4 cache: {df_v4.shape[0]} windows, {len(feature_cols)} features, {df_v4['__clip_id'].nunique()} clips")

# Label v4 cache windows
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
                              "carry_object_entry", "carry_object_walk",
                              "carry_object_stop", "carry_object_cross",
                              "move_obstacle", "loop_around", "linger",
                              "doorway_linger", "reposition_object_cross",
                              "occupied_entry", "occupied_exit",
                              "small_step", "transition", "side_step",
                              "squat_stand"]):
        return "OCCUPIED", "MOTION"
    if "occupied" in ln:
        return "OCCUPIED", "STATIC"
    return None, None

df_v4["binary"] = None
df_v4["coarse"] = None
df_v4["source"] = "v4_scripted"
for idx, row in df_v4.iterrows():
    b, c = ln_to_labels(row["__ln"])
    df_v4.at[idx, "binary"] = b
    df_v4.at[idx, "coarse"] = c

df_v4 = df_v4.dropna(subset=["binary"])
print(f"  Labeled: {len(df_v4)} windows")

# ══════════════════════════════════════════════════════════════════════════
# PART B: Extract features for Track B + new session clips
# ══════════════════════════════════════════════════════════════════════════

print("\n[B] Extracting features for Track B + new session clips...")

# We need to extract the SAME features as v4 cache. Since v4 used a complex
# pipeline, we'll extract a compatible subset and zero-pad missing features.
# But the real approach: use v4's feature extraction code.

# Actually, let's check what v4 features look like
print(f"  V4 feature names sample: {feature_cols[:10]}")
print(f"  V4 feature names last: {feature_cols[-10:]}")

# The v4 features are very complex (sw_w05_avg_*, en_*, lw_w20_*, etc.)
# Re-extracting them requires the v4 pipeline code. Instead, let's use
# Track B's simpler but effective approach: extract 80 features per clip
# and see if JUST the Track B clips with better features beat 0.80.

# Track B manual annotations
MANUAL_ANNOTATIONS = {
    "multi_person_freeform_long_20260317_201856": [(0, 122, 2, "walking")],
    "multi_person_freeform_20260317_201710": [(0, 62, 3, "walking")],
    "three_person_static_test_20260317_201352": [(0, 22, 3, "static")],
    "four_person_static_test_20260317_201452": [(0, 22, 4, "static")],
    "longcap_chunk0001_20260317_203020": [
        (0, 40, 1, "walking"), (40, 140, 1, "static"),
        (140, 190, 1, "walking"), (190, 300, 1, "static"),
    ],
    "longcap_chunk0009_20260317_211037": [
        (0, 190, 1, "walking"), (190, 240, 1, "static"), (240, 300, 0, "empty"),
    ],
    "longcap_chunk0011_20260317_212041": [
        (0, 30, 1, "walking"), (30, 300, 1, "static"),
    ],
    "longcap_chunk0010_20260317_211539": [(0, 300, 0, "empty")],
    "longcap_chunk0012_20260317_212543": [(0, 155, 1, "static")],
    "longcap_chunk0001_20260317_221250": [(0, 60, 1, "walking")],
    "empty_garage_20260317_223236": [(0, 180, 0, "empty")],
    "rec_20260317_232705_clip01_empty_baseline": [(0, 20, 0, "empty")],
    "rec_20260317_232705_clip02_empty_door_open": [(0, 20, 0, "empty")],
    "rec_20260317_232705_clip03_empty_settled": [(0, 20, 0, "empty")],
    "rec_20260317_232705_clip04_stand_center": [(0, 20, 1, "static")],
    "rec_20260317_232705_clip05_stand_near_exit": [(0, 20, 1, "static")],
    "rec_20260317_232705_clip06_stand_deep": [(0, 20, 1, "static")],
    "rec_20260317_232705_clip07_walk_slow": [(0, 25, 1, "walking")],
    "rec_20260317_232705_clip08_walk_normal": [(0, 25, 1, "walking")],
    "rec_20260317_232705_clip09_walk_around": [(0, 25, 1, "walking")],
    "rec_20260317_232705_clip10_enter_walk_stand": [
        (0, 8, 0, "empty"), (8, 18, 1, "walking"), (18, 25, 1, "static"),
    ],
    "rec_20260317_232705_clip11_enter_exit_fast": [
        (0, 3, 0, "empty"), (3, 10, 1, "walking"), (10, 15, 0, "empty"),
    ],
    "rec_20260317_232705_clip12_enter_stay": [
        (0, 5, 0, "empty"), (5, 15, 1, "walking"), (15, 25, 1, "static"),
    ],
    # New session 20260318
    "longcap_chunk0001_20260318_010147": [(0, 30, 1, "static")],
    "longcap_chunk0002_20260318_010219": [(0, 30, 1, "walking")],
    "longcap_chunk0003_20260318_010251": [(0, 30, 1, "walking")],
    "longcap_chunk0004_20260318_010323": [(0, 30, 1, "walking")],
    "longcap_chunk0005_20260318_010355": [(0, 30, 1, "static")],
    "longcap_chunk0006_20260318_010427": [(0, 19, 1, "static")],
}

# Also load scripted captures from summary.json
scripted_labels = {}
for sf in sorted(CAPTURES.glob("*.summary.json")):
    try:
        d = json.load(open(sf))
        label = d.get("label", "")
        if label in MANUAL_ANNOTATIONS:
            continue
        pc = d.get("person_count_expected", -1)
        dur = d.get("duration_sec", 0)
        sources = d.get("source_count", 0)
        step = d.get("step_name", "")
        if sources < 3 or dur < 5 or pc < 0:
            continue
        if "empty" in step:
            motion = "empty"
        elif any(x in step for x in ["stand", "static", "still", "breath", "sit"]):
            motion = "static"
        elif any(x in step for x in ["walk", "motion", "fast", "entry", "exit"]):
            motion = "walking"
        else:
            motion = "static" if pc > 0 else "empty"
        scripted_labels[label] = [(0, dur, pc, motion)]
    except:
        continue

all_new_labels = {}
all_new_labels.update(scripted_labels)
all_new_labels.update(MANUAL_ANNOTATIONS)  # manual overrides scripted

print(f"  Manual annotations: {len(MANUAL_ANNOTATIONS)} clips")
print(f"  Scripted (additional): {len(scripted_labels)} clips")
print(f"  Total new labels: {len(all_new_labels)} clips")

# ── Feature extraction (Track B style: 80 features per window) ────────────

CSI_HEADER = 20
ACTIVE_SC = np.array(list(range(6, 59)) + list(range(70, 123)))
WINDOW_SEC = 5

def parse_csi(b64):
    raw = base64.b64decode(b64)
    if len(raw) < CSI_HEADER + 40:
        return None, None
    iq = raw[CSI_HEADER:CSI_HEADER + 256]
    n_sub = len(iq) // 2
    if n_sub < 20:
        return None, None
    arr = np.frombuffer(iq[:n_sub*2], dtype=np.int8).reshape(-1, 2)
    i_v, q_v = arr[:, 0].astype(np.float32), arr[:, 1].astype(np.float32)
    return np.sqrt(i_v**2 + q_v**2), np.arctan2(q_v, i_v)

# Empty baselines
_baselines = {}
empty_clips = [l for l, segs in all_new_labels.items() if all(s[3] == "empty" for s in segs)]
for ec in empty_clips:
    p = CAPTURES / f"{ec}.ndjson.gz"
    if not p.exists():
        continue
    node_amps = defaultdict(list)
    with gzip.open(str(p), "rt") as f:
        for line in f:
            try:
                rec = json.loads(line)
                amp, _ = parse_csi(rec.get("payload_b64", ""))
                if amp is None: continue
                ip = rec.get("src_ip", "")
                node_amps[ip].append(amp[:128] if len(amp) >= 128 else np.pad(amp, (0, 128-len(amp))))
            except: continue
    for ip, amps in node_amps.items():
        if len(amps) >= 10 and ip not in _baselines:
            mat = np.array(amps[:300], dtype=np.float32)
            _baselines[ip] = {"mean": mat.mean(axis=0), "std": mat.std(axis=0) + 1e-6}

print(f"  Empty baselines: {len(_baselines)} nodes")

from scipy.stats import kurtosis as sp_kurtosis, skew as sp_skew

def extract_rich_features(csi_path):
    """Extract rich features per window (compatible with Track B but enhanced)."""
    packets_by_node = defaultdict(list)
    with gzip.open(str(csi_path), "rt") as f:
        first_ts = None
        for line in f:
            try:
                rec = json.loads(line)
                ts_ns = rec.get("ts_ns", 0)
                ip = rec.get("src_ip", "")
                amp, phase = parse_csi(rec.get("payload_b64", ""))
                if amp is None: continue
                if first_ts is None: first_ts = ts_ns
                t_sec = (ts_ns - first_ts) / 1e9
                # Pad to 128
                if len(amp) < 128:
                    amp = np.pad(amp, (0, 128 - len(amp)))
                    phase = np.pad(phase, (0, 128 - len(phase)))
                packets_by_node[ip].append((t_sec, amp[:128], phase[:128]))
            except: continue

    if not packets_by_node:
        return []

    all_times = [t for pkts in packets_by_node.values() for t, _, _ in pkts]
    max_t = max(all_times)
    n_windows = int(max_t / WINDOW_SEC)
    node_ips = sorted(packets_by_node.keys())[:4]

    # Clip baseline
    clip_bl = {}
    for ip in node_ips:
        early = [a.mean() for t, a, _ in packets_by_node[ip] if t < WINDOW_SEC]
        clip_bl[ip] = np.mean(early) if early else 1.0

    windows = []
    prev_means = None

    for w in range(n_windows):
        t0w = w * WINDOW_SEC
        t1w = t0w + WINDOW_SEC
        feat = {"t_mid": (t0w + t1w) / 2}

        nm, ns, nv, nd1, ndop, nbl = [], [], [], [], [], []

        for ni, ip in enumerate(node_ips):
            pkts = [(t, a, p) for t, a, p in packets_by_node[ip] if t0w <= t < t1w]

            prefix = f"n{ni}"
            if len(pkts) < 3:
                for k in [f"{prefix}_{s}" for s in ["mean","std","max","range","pps","tvar","norm",
                           "diff1","diff1_max","doppler","bldev","tvar_lo","tvar_hi","zcr","kurtosis",
                           "skew","pca_ev1","pca_effdim","fft_peak","fft_energy"]]:
                    feat[k] = 0
                nm.append(0); ns.append(0); nv.append(0); nd1.append(0); ndop.append(0); nbl.append(0)
                continue

            amp_mat = np.array([a for _, a, _ in pkts], dtype=np.float32)
            phase_mat = np.array([p for _, _, p in pkts], dtype=np.float32)
            amps = amp_mat.mean(axis=1)

            # Original 7
            feat[f"{prefix}_mean"] = float(np.mean(amps))
            feat[f"{prefix}_std"] = float(np.std(amps))
            feat[f"{prefix}_max"] = float(np.max(amps))
            feat[f"{prefix}_range"] = float(np.ptp(amps))
            feat[f"{prefix}_pps"] = len(pkts) / WINDOW_SEC
            tvar = float(np.var(np.diff(amps))) if len(amps) > 1 else 0
            feat[f"{prefix}_tvar"] = tvar
            bl = clip_bl.get(ip, 1.0)
            feat[f"{prefix}_norm"] = float(np.mean(amps) / bl) if bl > 0 else 0

            # Diff energy
            diff1 = np.abs(np.diff(amps))
            feat[f"{prefix}_diff1"] = float(np.mean(diff1)) if len(diff1) > 0 else 0
            feat[f"{prefix}_diff1_max"] = float(np.max(diff1)) if len(diff1) > 0 else 0

            # Doppler
            doppler = 0
            if len(pkts) >= 6 and phase_mat.shape[1] >= 20:
                ph = np.unwrap(phase_mat[:, :min(phase_mat.shape[1], len(ACTIVE_SC))], axis=0)
                doppler = float(np.abs(np.diff(ph, axis=0)).mean())
            feat[f"{prefix}_doppler"] = doppler

            # Baseline deviation
            bldev = 0
            if ip in _baselines:
                bl_d = _baselines[ip]
                n_sc = min(amp_mat.shape[1], len(bl_d["mean"]))
                deviation = np.abs(amp_mat[:, :n_sc].mean(axis=0) - bl_d["mean"][:n_sc]) / bl_d["std"][:n_sc]
                bldev = float(deviation.mean())
            feat[f"{prefix}_bldev"] = bldev

            # Band-split temporal variance
            tv_full = amp_mat.var(axis=0) if amp_mat.shape[0] > 1 else np.zeros(128)
            feat[f"{prefix}_tvar_lo"] = float(tv_full[:30].mean())
            feat[f"{prefix}_tvar_hi"] = float(tv_full[30:60].mean()) if len(tv_full) > 30 else tvar

            # Stats
            feat[f"{prefix}_zcr"] = float(np.mean(np.abs(np.diff(np.sign(np.diff(amps)))) > 0)) if len(amps) > 3 else 0
            feat[f"{prefix}_kurtosis"] = float(sp_kurtosis(amps)) if len(amps) > 3 else 0
            feat[f"{prefix}_skew"] = float(sp_skew(amps)) if len(amps) > 3 else 0

            # PCA on subcarrier amplitudes
            if amp_mat.shape[0] >= 5:
                cov = np.cov(amp_mat.T)
                eigvals = np.linalg.eigvalsh(cov)[::-1]
                feat[f"{prefix}_pca_ev1"] = float(eigvals[0]) if len(eigvals) > 0 else 0
                total = eigvals.sum()
                if total > 0:
                    probs = eigvals / total
                    probs = probs[probs > 0]
                    feat[f"{prefix}_pca_effdim"] = float(np.exp(-np.sum(probs * np.log(probs))))
                else:
                    feat[f"{prefix}_pca_effdim"] = 0
            else:
                feat[f"{prefix}_pca_ev1"] = 0
                feat[f"{prefix}_pca_effdim"] = 0

            # FFT on mean amplitude time series
            if len(amps) >= 8:
                fft_vals = np.abs(np.fft.rfft(amps - amps.mean()))
                feat[f"{prefix}_fft_peak"] = float(np.max(fft_vals[1:])) if len(fft_vals) > 1 else 0
                feat[f"{prefix}_fft_energy"] = float(np.sum(fft_vals[1:]**2)) if len(fft_vals) > 1 else 0
            else:
                feat[f"{prefix}_fft_peak"] = 0
                feat[f"{prefix}_fft_energy"] = 0

            nm.append(np.mean(amps)); ns.append(np.std(amps)); nv.append(tvar)
            nd1.append(feat[f"{prefix}_diff1"]); ndop.append(doppler); nbl.append(bldev)

        # Cross-node features
        if len(nm) >= 2:
            feat["x_mean_std"] = float(np.std(nm))
            feat["x_mean_range"] = float(max(nm) - min(nm))
            feat["x_std_mean"] = float(np.mean(ns))
            feat["x_tvar_mean"] = float(np.mean(nv))
            feat["x_tvar_max"] = float(max(nv))
            feat["x_diff1_mean"] = float(np.mean(nd1))
            feat["x_doppler_mean"] = float(np.mean(ndop))
            feat["x_bldev_mean"] = float(np.mean(nbl))
            feat["x_bldev_max"] = float(max(nbl))
            # Cross-node correlation
            if len(nm) >= 3:
                feat["x_corr_mean"] = float(np.corrcoef(nm[:3], ns[:3])[0, 1]) if np.std(nm[:3]) > 0 and np.std(ns[:3]) > 0 else 0
            else:
                feat["x_corr_mean"] = 0
        else:
            for k in ["x_mean_std","x_mean_range","x_std_mean","x_tvar_mean","x_tvar_max",
                       "x_diff1_mean","x_doppler_mean","x_bldev_mean","x_bldev_max","x_corr_mean"]:
                feat[k] = 0

        # Aggregate
        all_a = [a.mean() for ip in node_ips for t, a, _ in packets_by_node[ip] if t0w <= t < t1w]
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / WINDOW_SEC

        # Temporal delta
        if prev_means and len(nm) == len(prev_means):
            for ni in range(min(4, len(nm))):
                feat[f"n{ni}_delta"] = nm[ni] - prev_means[ni]
        else:
            for ni in range(4):
                feat[f"n{ni}_delta"] = 0

        prev_means = list(nm)
        windows.append(feat)

    return windows

# Extract features for all new clips
print("\n  Extracting features for new clips...")
new_rows = []
clip_counter = 1000  # offset to avoid collision with v4 clip IDs

for label, segments in sorted(all_new_labels.items()):
    csi_path = CAPTURES / f"{label}.ndjson.gz"
    if not csi_path.exists():
        continue

    # Skip if already in v4 cache (by matching label prefix)
    if any(label in c for c in df_v4["__clabel"].unique()):
        continue

    windows = extract_rich_features(csi_path)
    if not windows:
        continue

    for w in windows:
        t_mid = w["t_mid"]
        # Find matching segment
        binary = None
        coarse = None
        for seg_start, seg_end, pc, motion in segments:
            if seg_start <= t_mid < seg_end:
                if motion == "empty" or pc == 0:
                    binary, coarse = "EMPTY", "EMPTY"
                elif motion == "static":
                    binary, coarse = "OCCUPIED", "STATIC"
                elif motion == "walking":
                    binary, coarse = "OCCUPIED", "MOTION"
                break

        if binary is None:
            continue

        w["binary"] = binary
        w["coarse"] = coarse
        w["__clip_id"] = clip_counter
        w["__clabel"] = label
        w["source"] = "manual" if label in MANUAL_ANNOTATIONS else "scripted"
        new_rows.append(w)

    clip_counter += 1

df_new = pd.DataFrame(new_rows)
if len(df_new) > 0:
    print(f"  New clips processed: {df_new['__clabel'].nunique()}")
    print(f"  New windows: {len(df_new)}")
    print(f"  New label dist: {dict(Counter(df_new['coarse']))}")
else:
    print("  No new windows extracted!")

# ══════════════════════════════════════════════════════════════════════════
# PART C: Find common features between v4 cache and new extractions
# ══════════════════════════════════════════════════════════════════════════

print("\n[C] Finding common features...")

# New features are different from v4's 1844. We'll train on each separately
# AND try training only on new clips with their rich features.

# ══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 1: Track B + new session ONLY (enhanced features)
# ══════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("EXPERIMENT 1: Track B + new session only (enhanced 90 features)")
print("=" * 70)

if len(df_new) > 0:
    new_feat_cols = [c for c in df_new.columns if c not in
                     ["binary", "coarse", "__clip_id", "__clabel", "source", "t_mid"]]
    X_new = df_new[new_feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0).values
    y_new_b = df_new["binary"].values
    y_new_c = df_new["coarse"].values
    g_new = df_new["__clip_id"].values

    print(f"  Features: {len(new_feat_cols)}")
    print(f"  Windows: {len(X_new)}, Clips: {len(np.unique(g_new))}")
    print(f"  Binary: {dict(Counter(y_new_b))}")
    print(f"  Coarse: {dict(Counter(y_new_c))}")

    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.metrics import balanced_accuracy_score, f1_score, classification_report, confusion_matrix
    from sklearn.preprocessing import LabelEncoder

    try:
        from xgboost import XGBClassifier
        HAS_XGB = True
    except: HAS_XGB = False

    CV = min(5, len(np.unique(g_new)))

    for task, y_task in [("binary", y_new_b), ("coarse", y_new_c)]:
        le = LabelEncoder()
        y_enc = le.fit_transform(y_task)
        classes = le.classes_

        if len(np.unique(y_enc)) < 2:
            print(f"\n  {task}: skipped (< 2 classes)")
            continue

        sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)

        models = {
            "HGB": HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03, random_state=42),
            "HGB_bal": HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                       class_weight="balanced", random_state=42),
            "RF": RandomForestClassifier(n_estimators=500, max_depth=15, random_state=42, n_jobs=-1),
            "RF_bal": RandomForestClassifier(n_estimators=500, max_depth=15,
                                             class_weight="balanced", random_state=42, n_jobs=-1),
        }
        if HAS_XGB:
            models["XGB"] = XGBClassifier(n_estimators=500, max_depth=8, learning_rate=0.03,
                                           use_label_encoder=False, eval_metric="mlogloss",
                                           random_state=42, verbosity=0)

        best_ba = 0
        best_name = ""
        for mname, model in models.items():
            fold_ba = []
            all_preds = np.zeros(len(y_enc), dtype=int)
            for train_idx, test_idx in sgkf.split(X_new, y_enc, g_new):
                m = type(model)(**model.get_params())
                m.fit(X_new[train_idx], y_enc[train_idx])
                preds = m.predict(X_new[test_idx])
                all_preds[test_idx] = preds
                fold_ba.append(balanced_accuracy_score(y_enc[test_idx], preds))
            mean_ba = np.mean(fold_ba)
            std_ba = np.std(fold_ba)
            f1 = f1_score(y_enc, all_preds, average="macro")
            print(f"    {task:8s} {mname:10s}: BalAcc={mean_ba:.3f}+-{std_ba:.3f} F1={f1:.3f}")
            if mean_ba > best_ba:
                best_ba = mean_ba
                best_name = mname
                best_preds = all_preds
                best_std = std_ba

        print(f"\n  BEST {task}: {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f}")
        cm = confusion_matrix(y_enc, best_preds)
        print(f"  Classes: {list(classes)}")
        for row in cm:
            print(f"  {row}")
        print(classification_report(y_enc, best_preds, target_names=classes, digits=3))

# ══════════════════════════════════════════════════════════════════════════
# EXPERIMENT 2: V4 cache + new clips (common features only)
# ══════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("EXPERIMENT 2: V4 cache + new clips (common features)")
print("=" * 70)

if len(df_new) > 0:
    # Find common features between v4 and new
    v4_feats = set(feature_cols)
    new_feats = set(new_feat_cols)
    common = sorted(v4_feats & new_feats)
    print(f"  V4 features: {len(v4_feats)}")
    print(f"  New features: {len(new_feats)}")
    print(f"  Common features: {len(common)}")

    if len(common) >= 10:
        # Build combined dataset
        df_v4_sel = df_v4[common + ["binary", "coarse", "__clip_id", "source"]].copy()
        df_new_sel = df_new[common + ["binary", "coarse", "__clip_id", "source"]].copy()

        df_combined = pd.concat([df_v4_sel, df_new_sel], ignore_index=True)
        X_comb = df_combined[common].replace([np.inf, -np.inf], np.nan).fillna(0).values
        y_comb_b = df_combined["binary"].values
        y_comb_c = df_combined["coarse"].values
        g_comb = df_combined["__clip_id"].values

        print(f"\n  Combined: {len(X_comb)} windows, {len(np.unique(g_comb))} clips")
        print(f"  Binary: {dict(Counter(y_comb_b))}")
        print(f"  Coarse: {dict(Counter(y_comb_c))}")

        CV_comb = min(5, len(np.unique(g_comb)))

        for task, y_task in [("binary", y_comb_b), ("coarse", y_comb_c)]:
            le = LabelEncoder()
            y_enc = le.fit_transform(y_task)
            classes = le.classes_

            sgkf = StratifiedGroupKFold(n_splits=CV_comb, shuffle=True, random_state=42)

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
                all_preds = np.zeros(len(y_enc), dtype=int)
                for train_idx, test_idx in sgkf.split(X_comb, y_enc, g_comb):
                    m = type(model)(**model.get_params())
                    m.fit(X_comb[train_idx], y_enc[train_idx])
                    preds = m.predict(X_comb[test_idx])
                    all_preds[test_idx] = preds
                    fold_ba.append(balanced_accuracy_score(y_enc[test_idx], preds))
                mean_ba = np.mean(fold_ba)
                std_ba = np.std(fold_ba)
                if mean_ba > best_ba:
                    best_ba = mean_ba; best_name = mname; best_std = std_ba
                    best_preds = all_preds

            f1 = f1_score(y_enc, best_preds, average="macro")
            print(f"  {task:8s}: {best_name:10s} BalAcc={best_ba:.3f}+-{best_std:.3f} F1={f1:.3f}")
            cm = confusion_matrix(y_enc, best_preds)
            print(f"    Classes: {list(classes)}")
            for row in cm:
                print(f"    {row}")
    else:
        print("  Too few common features, skipping combined experiment")

# ══════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════

elapsed = time.time() - t0
print("\n" + "=" * 70)
print(f"v14 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min)")
print("=" * 70)

# Save results
outdir = PROJECT / "output" / "csi_pipeline_v14_results"
outdir.mkdir(parents=True, exist_ok=True)
if len(df_new) > 0:
    df_new.to_csv(outdir / "v14_new_clips_dataset.csv", index=False)
    print(f"  Saved: {outdir / 'v14_new_clips_dataset.csv'}")
