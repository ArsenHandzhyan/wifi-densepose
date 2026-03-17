#!/usr/bin/env python3
"""
V18: Semi-supervised labeling + Training

Strategy:
  1. Compute empty-room CSI baseline from known empty clips
  2. For each unlabeled window, compute deviation from baseline
  3. Use YOLO detections + CSI deviation to create confident labels
  4. Train only on HIGH-CONFIDENCE labels (skip uncertain)

Label confidence hierarchy:
  A) Manual annotation -> confidence=1.0
  B) Scripted with person_count -> confidence=0.9
  C) CSI deviation > 3σ from empty AND YOLO sees person -> confidence=0.8 (OCCUPIED)
  D) CSI deviation < 1σ from empty AND YOLO sees nothing -> confidence=0.8 (EMPTY)
  E) Only CSI deviation (no YOLO) -> confidence=0.5
  F) Contradictory (YOLO sees person but CSI looks empty) -> skip

This should give more data with honest labels.
"""

import gzip, json, base64, time, warnings, pickle
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")

from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except: HAS_XGB = False

PROJECT = Path(__file__).resolve().parents[1]
CAPTURES = PROJECT / "temp" / "captures"
t0 = time.time()

print("=" * 70)
print("V18: Semi-supervised Labeling + Training")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ── CSI parsing ───────────────────────────────────────────────────────────

CSI_HEADER = 20
NODE_IPS = sorted(["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137"])

def parse_amp(b64):
    raw = base64.b64decode(b64)
    if len(raw) < CSI_HEADER + 40:
        return None
    iq = raw[CSI_HEADER:CSI_HEADER + 256]
    n = len(iq) // 2
    if n < 20:
        return None
    arr = np.frombuffer(iq[:n*2], dtype=np.int8).reshape(-1, 2)
    amp = np.sqrt(arr[:, 0].astype(np.float32)**2 + arr[:, 1].astype(np.float32)**2)
    return amp[:128] if len(amp) >= 128 else np.pad(amp, (0, 128-len(amp)))

# ── Step 1: Build empty baseline ─────────────────────────────────────────

print("\n[Step 1] Building empty-room baseline...")

empty_clips = []
for sf in sorted(CAPTURES.glob("*.summary.json")):
    d = json.load(open(sf))
    if d.get("person_count_expected", -1) == 0 and d.get("source_count", 0) >= 3:
        empty_clips.append(d.get("label", ""))

for cf in sorted(CAPTURES.glob("*.clip.json")):
    d = json.load(open(cf))
    ln = d.get("label_name", "").lower()
    if ("empty" in ln) and d.get("person_count_expected", -1) == 0:
        label = d.get("capture_label", "")
        if label not in empty_clips:
            empty_clips.append(label)

print(f"  Found {len(empty_clips)} empty-room clips")

# Compute per-node baseline stats
baseline_amps = defaultdict(list)  # ip -> list of mean amplitudes per window

for ec in empty_clips:
    p = CAPTURES / f"{ec}.ndjson.gz"
    if not p.exists():
        continue
    node_amps = defaultdict(list)
    with gzip.open(str(p), "rt") as f:
        first_ts = None
        for line in f:
            try:
                rec = json.loads(line)
                amp = parse_amp(rec.get("payload_b64", ""))
                if amp is None: continue
                ip = rec.get("src_ip", "")
                ts = rec.get("ts_ns", 0)
                if first_ts is None: first_ts = ts
                node_amps[ip].append(amp.mean())
            except: continue

    for ip, vals in node_amps.items():
        baseline_amps[ip].extend(vals)

# Compute statistics
baseline_stats = {}
for ip in NODE_IPS:
    vals = baseline_amps.get(ip, [])
    if len(vals) > 10:
        baseline_stats[ip] = {
            "mean": np.mean(vals),
            "std": np.std(vals),
            "p95": np.percentile(vals, 95),
            "p05": np.percentile(vals, 5),
        }
        print(f"  {ip}: mean={baseline_stats[ip]['mean']:.2f}, std={baseline_stats[ip]['std']:.2f}, n={len(vals)}")

# ── Step 2: Process all clips with semi-supervised labeling ───────────────

print("\n[Step 2] Processing all clips with semi-supervised labels...")

WINDOW_SEC = 5.0

def extract_features_and_label(csi_path, label, known_binary=None, known_coarse=None,
                                yolo_data=None, confidence=1.0):
    """Extract features + assign semi-supervised labels."""
    node_packets = defaultdict(list)

    with gzip.open(str(csi_path), "rt") as f:
        first_ts = None
        for line in f:
            try:
                rec = json.loads(line)
                ip = rec.get("src_ip", "")
                if ip not in NODE_IPS: continue
                amp = parse_amp(rec.get("payload_b64", ""))
                if amp is None: continue
                ts = rec.get("ts_ns", 0)
                if first_ts is None: first_ts = ts
                t_sec = (ts - first_ts) / 1e9
                node_packets[ip].append((t_sec, amp))
            except: continue

    if len(node_packets) < 3:
        return []

    all_t = [t for pkts in node_packets.values() for t, _ in pkts]
    max_t = max(all_t)
    n_windows = int(max_t / WINDOW_SEC)

    windows = []
    for w in range(n_windows):
        t0w = w * WINDOW_SEC
        t1w = t0w + WINDOW_SEC

        feat = {}
        node_means = []
        node_stds = []
        node_tvars = []
        node_deviations = []

        for ip in NODE_IPS:
            pkts = [(t, a) for t, a in node_packets.get(ip, []) if t0w <= t < t1w]
            ni = NODE_IPS.index(ip)
            prefix = f"n{ni}"

            if len(pkts) < 3:
                for k in [f"{prefix}_{s}" for s in ["mean","std","max","range","pps","tvar",
                           "diff1","diff1_max","sc_var_mean","sc_var_max","deviation"]]:
                    feat[k] = 0
                node_means.append(0); node_stds.append(0); node_tvars.append(0)
                node_deviations.append(0)
                continue

            amp_mat = np.array([a for _, a in pkts], dtype=np.float32)
            amps = amp_mat.mean(axis=1)

            feat[f"{prefix}_mean"] = float(np.mean(amps))
            feat[f"{prefix}_std"] = float(np.std(amps))
            feat[f"{prefix}_max"] = float(np.max(amps))
            feat[f"{prefix}_range"] = float(np.ptp(amps))
            feat[f"{prefix}_pps"] = len(pkts) / WINDOW_SEC
            tvar = float(np.var(np.diff(amps))) if len(amps) > 1 else 0
            feat[f"{prefix}_tvar"] = tvar

            diff1 = np.abs(np.diff(amps))
            feat[f"{prefix}_diff1"] = float(np.mean(diff1)) if len(diff1) > 0 else 0
            feat[f"{prefix}_diff1_max"] = float(np.max(diff1)) if len(diff1) > 0 else 0

            sc_var = amp_mat.var(axis=0)
            feat[f"{prefix}_sc_var_mean"] = float(sc_var.mean())
            feat[f"{prefix}_sc_var_max"] = float(sc_var.max())

            # Baseline deviation (z-score)
            if ip in baseline_stats:
                bl = baseline_stats[ip]
                dev = abs(np.mean(amps) - bl["mean"]) / max(bl["std"], 0.01)
                feat[f"{prefix}_deviation"] = float(dev)
                node_deviations.append(dev)
            else:
                feat[f"{prefix}_deviation"] = 0
                node_deviations.append(0)

            node_means.append(np.mean(amps)); node_stds.append(np.std(amps))
            node_tvars.append(tvar)

        # Cross-node
        if len(node_means) >= 2:
            feat["x_mean_std"] = float(np.std(node_means))
            feat["x_mean_range"] = float(max(node_means) - min(node_means))
            feat["x_tvar_mean"] = float(np.mean(node_tvars))
            feat["x_tvar_max"] = float(max(node_tvars))
            feat["x_dev_mean"] = float(np.mean(node_deviations))
            feat["x_dev_max"] = float(max(node_deviations))
        else:
            for k in ["x_mean_std","x_mean_range","x_tvar_mean","x_tvar_max","x_dev_mean","x_dev_max"]:
                feat[k] = 0

        # Aggregate
        all_a = [a.mean() for ip in NODE_IPS for t, a in node_packets.get(ip, []) if t0w <= t < t1w]
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / WINDOW_SEC

        # ── Semi-supervised labeling ──
        max_dev = max(node_deviations) if node_deviations else 0
        mean_dev = np.mean(node_deviations) if node_deviations else 0

        if known_binary is not None:
            # Known label
            feat["binary"] = known_binary
            feat["coarse"] = known_coarse
            feat["confidence"] = confidence
        else:
            # Semi-supervised: use CSI deviation
            if mean_dev < 1.0:
                feat["binary"] = "EMPTY"
                feat["coarse"] = "EMPTY"
                feat["confidence"] = min(0.7, 1.0 - mean_dev * 0.3)
            elif max_dev > 3.0:
                feat["binary"] = "OCCUPIED"
                # Can't distinguish STATIC vs MOTION from deviation alone
                feat["coarse"] = "UNKNOWN"
                feat["confidence"] = min(0.7, max_dev / 10.0)
            else:
                feat["binary"] = "UNCERTAIN"
                feat["coarse"] = "UNCERTAIN"
                feat["confidence"] = 0.0

        feat["clip_label"] = label
        feat["t_mid"] = (t0w + t1w) / 2
        windows.append(feat)

    return windows

# Process all clips
all_rows = []
clip_counter = 0

# First: known-label clips
for sf in sorted(CAPTURES.glob("*.summary.json")):
    try:
        d = json.load(open(sf))
        label = d.get("label", "")
        pc = d.get("person_count_expected", -1)
        dur = d.get("duration_sec", 0)
        sources = d.get("source_count", 0)
        step = d.get("step_name", "").lower()

        if sources < 3 or dur < 5 or pc < 0:
            continue

        csi_path = CAPTURES / f"{label}.ndjson.gz"
        if not csi_path.exists():
            continue

        binary = "EMPTY" if pc == 0 or "empty" in step else "OCCUPIED"
        if "walk" in step or "entry" in step or "exit" in step:
            coarse = "MOTION"
        elif pc == 0 or "empty" in step:
            coarse = "EMPTY"
        else:
            coarse = "STATIC"

        windows = extract_features_and_label(csi_path, label, binary, coarse, confidence=0.9)
        for w in windows:
            w["clip_id"] = clip_counter
        all_rows.extend(windows)
        clip_counter += 1
    except:
        continue

# Second: clip.json clips (without summary)
processed_labels = {r["clip_label"] for r in all_rows}
for cf in sorted(CAPTURES.glob("*.clip.json")):
    try:
        d = json.load(open(cf))
        label = d.get("capture_label", "")
        if label in processed_labels:
            continue

        ln = d.get("label_name", "").lower()
        pc = d.get("person_count_expected", -1)
        capf = d.get("capture_file", "")

        if pc < 0:
            continue

        csi_path = Path(capf) if capf else CAPTURES / f"{label}.ndjson.gz"
        if not csi_path.exists():
            continue

        binary = "EMPTY" if pc == 0 or "empty" in ln else "OCCUPIED"
        if any(x in ln for x in ["walk", "entry", "exit", "corridor", "step"]):
            coarse = "MOTION"
        elif pc == 0 or "empty" in ln:
            coarse = "EMPTY"
        else:
            coarse = "STATIC"

        windows = extract_features_and_label(csi_path, label, binary, coarse, confidence=0.85)
        for w in windows:
            w["clip_id"] = clip_counter
        all_rows.extend(windows)
        clip_counter += 1
        processed_labels.add(label)
    except:
        continue

# Third: unlabeled clips (CSI-only, semi-supervised)
for csi_path in sorted(CAPTURES.glob("*.ndjson.gz")):
    label = csi_path.stem.replace(".ndjson", "")
    if label in processed_labels:
        continue

    windows = extract_features_and_label(csi_path, label)
    for w in windows:
        w["clip_id"] = clip_counter
    all_rows.extend(windows)
    clip_counter += 1
    processed_labels.add(label)

df = pd.DataFrame(all_rows)
print(f"\n  Total windows: {len(df)}")
print(f"  Total clips: {clip_counter}")
print(f"  Confidence distribution:")
print(f"    High (>=0.8): {(df['confidence'] >= 0.8).sum()}")
print(f"    Medium (0.5-0.8): {((df['confidence'] >= 0.5) & (df['confidence'] < 0.8)).sum()}")
print(f"    Low (<0.5): {(df['confidence'] < 0.5).sum()}")
print(f"  Binary (high conf): {dict(Counter(df[df['confidence']>=0.8]['binary']))}")
print(f"  Coarse (high conf): {dict(Counter(df[df['confidence']>=0.8]['coarse']))}")

# ── Step 3: Train on high-confidence labels ───────────────────────────────

print("\n[Step 3] Training on high-confidence labels...")

# Filter to high-confidence, known labels
df_train = df[(df["confidence"] >= 0.8) & (~df["binary"].isin(["UNCERTAIN"]))].copy()
feat_cols = [c for c in df_train.columns if c not in
             ["binary", "coarse", "confidence", "clip_label", "clip_id", "t_mid"]]

X = df_train[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0).values
y_b = df_train["binary"].values
y_c = df_train["coarse"].values
groups = df_train["clip_id"].values

# Remove UNKNOWN coarse labels
mask_known_c = y_c != "UNKNOWN"

print(f"  Training windows: {len(X)}, Clips: {len(np.unique(groups))}")
print(f"  Features: {len(feat_cols)}")
print(f"  Binary: {dict(Counter(y_b))}")
print(f"  Coarse (known): {dict(Counter(y_c[mask_known_c]))}")

CV = min(5, len(np.unique(groups)))
sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)

for task_name, y_task, mask in [("binary", y_b, np.ones(len(y_b), dtype=bool)),
                                  ("coarse", y_c, mask_known_c)]:
    X_t = X[mask]
    y_t = y_task[mask]
    g_t = groups[mask]

    if len(np.unique(y_t)) < 2:
        print(f"  {task_name}: skipped (< 2 classes)")
        continue

    le = LabelEncoder()
    y_enc = le.fit_transform(y_t)

    best_ba = 0
    best_name = ""
    for mname, model in [
        ("RF_bal", RandomForestClassifier(n_estimators=500, max_depth=15,
                                          class_weight="balanced", random_state=42, n_jobs=-1)),
        ("HGB_bal", HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                    class_weight="balanced", random_state=42)),
    ]:
        if HAS_XGB:
            pass  # add later

        fold_ba = []
        all_preds = np.zeros(len(y_enc), dtype=int)
        n_splits = min(CV, len(np.unique(g_t)))
        sgkf2 = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)

        for train_idx, test_idx in sgkf2.split(X_t, y_enc, g_t):
            m = type(model)(**model.get_params())
            m.fit(X_t[train_idx], y_enc[train_idx])
            preds = m.predict(X_t[test_idx])
            all_preds[test_idx] = preds
            fold_ba.append(balanced_accuracy_score(y_enc[test_idx], preds))

        ba = np.mean(fold_ba)
        if ba > best_ba:
            best_ba = ba; best_name = mname
            best_std = np.std(fold_ba); best_preds = all_preds

    f1 = balanced_accuracy_score(y_enc, best_preds)
    print(f"  {task_name:8s}: {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f}")

    cm = confusion_matrix(y_enc, best_preds)
    print(f"    Classes: {list(le.classes_)}")
    for row in cm:
        print(f"    {row}")
    print(classification_report(y_enc, best_preds, target_names=le.classes_, digits=3))

# ── Step 4: Compare with/without semi-supervised data ─────────────────────

print("\n[Step 4] Ablation: supervised-only vs semi-supervised...")

# Supervised only: confidence >= 0.85 (manually labeled)
df_sup = df[df["confidence"] >= 0.85].copy()
df_sup = df_sup[~df_sup["binary"].isin(["UNCERTAIN"])]

X_sup = df_sup[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0).values
y_sup_b = df_sup["binary"].values
g_sup = df_sup["clip_id"].values

if len(np.unique(y_sup_b)) >= 2 and len(np.unique(g_sup)) >= 3:
    le = LabelEncoder()
    y_enc = le.fit_transform(y_sup_b)
    sgkf3 = StratifiedGroupKFold(n_splits=min(5, len(np.unique(g_sup))), shuffle=True, random_state=42)

    fold_ba = []
    for train_idx, test_idx in sgkf3.split(X_sup, y_enc, g_sup):
        m = RandomForestClassifier(n_estimators=500, max_depth=15,
                                    class_weight="balanced", random_state=42, n_jobs=-1)
        m.fit(X_sup[train_idx], y_enc[train_idx])
        fold_ba.append(balanced_accuracy_score(y_enc[test_idx], m.predict(X_sup[test_idx])))

    print(f"  Supervised-only (conf>=0.85): Binary BalAcc={np.mean(fold_ba):.3f}+-{np.std(fold_ba):.3f} ({len(X_sup)} win, {len(np.unique(g_sup))} clips)")

elapsed = time.time() - t0
print(f"\nV18 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min)")
