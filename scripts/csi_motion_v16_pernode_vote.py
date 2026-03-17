#!/usr/bin/env python3
"""
V16: Per-Node Binary Voting + Temporal Smoothing

Alternative hypothesis: instead of cross-node features,
train a separate binary model per node, then vote.

Why this might work:
  - Each node has independent CSI signal path
  - A person near node X causes strong perturbation on X, weak on Y
  - Simple per-node models are more robust to node failures
  - Temporal smoothing reduces noise

Also tests:
  - Overlapping windows (50% overlap)
  - Temporal smoothing with median filter
  - Consensus voting (2/4, 3/4, 4/4 nodes agree)
"""

import gzip, json, base64, time, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")

from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder
from scipy.ndimage import median_filter
from scipy.stats import kurtosis, skew

PROJECT = Path(__file__).resolve().parents[1]
CAPTURES = PROJECT / "temp" / "captures"
t0 = time.time()

print("=" * 70)
print("V16: Per-Node Binary Voting + Temporal Smoothing")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ── CSI parsing ───────────────────────────────────────────────────────────

CSI_HEADER = 20
NODE_IPS = {
    "192.168.1.101": "n01",
    "192.168.1.117": "n02",
    "192.168.1.125": "n03",
    "192.168.1.137": "n04",
}

def parse_amp(b64):
    raw = base64.b64decode(b64)
    if len(raw) < CSI_HEADER + 40:
        return None
    iq = raw[CSI_HEADER:CSI_HEADER + 256]
    n = len(iq) // 2
    if n < 20:
        return None
    arr = np.frombuffer(iq[:n*2], dtype=np.int8).reshape(-1, 2)
    return np.sqrt(arr[:, 0].astype(np.float32)**2 + arr[:, 1].astype(np.float32)**2)

# ── Load all clips with honest labels ─────────────────────────────────────

def load_clip_labels():
    """Load all clips with scripted/manual labels."""
    labels = {}

    for sf in sorted(CAPTURES.glob("*.summary.json")):
        try:
            d = json.load(open(sf))
            label = d.get("label", "")
            pc = d.get("person_count_expected", -1)
            dur = d.get("duration_sec", 0)
            sources = d.get("source_count", 0)
            step = d.get("step_name", "")

            if sources < 3 or dur < 5 or pc < 0:
                continue

            if "empty" in step.lower() or pc == 0:
                binary = "EMPTY"
            else:
                binary = "OCCUPIED"

            if "walk" in step.lower() or "entry" in step.lower() or "exit" in step.lower():
                coarse = "MOTION"
            elif "static" in step.lower() or "stand" in step.lower() or "sit" in step.lower():
                coarse = "STATIC"
            elif pc == 0:
                coarse = "EMPTY"
            else:
                coarse = "STATIC"

            labels[label] = {"binary": binary, "coarse": coarse, "pc": pc, "dur": dur}
        except:
            continue

    # Also from clip.json
    for cf in sorted(CAPTURES.glob("*.clip.json")):
        try:
            d = json.load(open(cf))
            label = d.get("capture_label", "")
            if label in labels:
                continue
            ln = d.get("label_name", "")
            sn = d.get("step_name", "")
            pc = d.get("person_count_expected", 0)

            if "empty" in ln.lower() or pc == 0:
                binary = "EMPTY"
            else:
                binary = "OCCUPIED"

            if any(x in sn.lower() for x in ["walk", "entry", "exit", "corridor", "fast", "step"]):
                coarse = "MOTION"
            elif any(x in sn.lower() for x in ["static", "quiet", "breath", "sit", "stand", "hold"]):
                coarse = "STATIC"
            elif pc == 0:
                coarse = "EMPTY"
            else:
                coarse = "STATIC"

            capf = d.get("capture_file", d.get("files", {}).get("csi_ndjson", ""))
            dur = d.get("duration_sec", d.get("duration_actual_sec", 0))

            labels[label] = {"binary": binary, "coarse": coarse, "pc": pc, "dur": dur}
        except:
            continue

    return labels

# ── Per-node feature extraction ───────────────────────────────────────────

def extract_pernode_features(csi_path, window_sec=5.0, overlap=0.5):
    """Extract features per node per window."""
    node_packets = defaultdict(list)

    with gzip.open(str(csi_path), "rt") as f:
        first_ts = None
        for line in f:
            try:
                rec = json.loads(line)
                ts = rec.get("ts_ns", 0)
                ip = rec.get("src_ip", "")
                if ip not in NODE_IPS:
                    continue
                amp = parse_amp(rec.get("payload_b64", ""))
                if amp is None:
                    continue
                if first_ts is None:
                    first_ts = ts
                t_sec = (ts - first_ts) / 1e9
                node_packets[NODE_IPS[ip]].append((t_sec, amp[:128] if len(amp) >= 128 else np.pad(amp, (0, max(0, 128-len(amp))))))
            except:
                continue

    if not node_packets:
        return {}

    all_t = [t for pkts in node_packets.values() for t, _ in pkts]
    max_t = max(all_t)
    step_sec = window_sec * (1 - overlap)

    # Per-node windows
    result = {}
    for node in ["n01", "n02", "n03", "n04"]:
        pkts = node_packets.get(node, [])
        if not pkts:
            continue

        windows = []
        t_start = 0
        while t_start + window_sec <= max_t + step_sec:
            t_end = t_start + window_sec
            w_pkts = [(t, a) for t, a in pkts if t_start <= t < t_end]

            if len(w_pkts) < 3:
                t_start += step_sec
                continue

            amps_mean = np.array([a.mean() for _, a in w_pkts])
            amp_mat = np.array([a for _, a in w_pkts], dtype=np.float32)

            feat = {
                "t_mid": (t_start + t_end) / 2,
                "mean": float(np.mean(amps_mean)),
                "std": float(np.std(amps_mean)),
                "max": float(np.max(amps_mean)),
                "range": float(np.ptp(amps_mean)),
                "pps": len(w_pkts) / window_sec,
                "tvar": float(np.var(np.diff(amps_mean))) if len(amps_mean) > 1 else 0,
            }

            # Diff energy
            diff1 = np.abs(np.diff(amps_mean))
            feat["diff1_mean"] = float(np.mean(diff1)) if len(diff1) > 0 else 0
            feat["diff1_max"] = float(np.max(diff1)) if len(diff1) > 0 else 0

            # Stats
            if len(amps_mean) > 3:
                feat["kurtosis"] = float(kurtosis(amps_mean))
                feat["skew"] = float(skew(amps_mean))
                # Zero crossing rate
                diff_sign = np.diff(np.sign(np.diff(amps_mean)))
                feat["zcr"] = float(np.mean(np.abs(diff_sign) > 0))
            else:
                feat["kurtosis"] = 0
                feat["skew"] = 0
                feat["zcr"] = 0

            # Subcarrier variance
            sc_var = amp_mat.var(axis=0)
            feat["sc_var_mean"] = float(sc_var.mean())
            feat["sc_var_max"] = float(sc_var.max())
            feat["sc_var_lo"] = float(sc_var[:30].mean())
            feat["sc_var_hi"] = float(sc_var[30:60].mean()) if len(sc_var) > 30 else 0

            # FFT
            if len(amps_mean) >= 8:
                fft_v = np.abs(np.fft.rfft(amps_mean - amps_mean.mean()))
                feat["fft_peak"] = float(np.max(fft_v[1:])) if len(fft_v) > 1 else 0
                feat["fft_energy"] = float(np.sum(fft_v[1:]**2)) if len(fft_v) > 1 else 0
            else:
                feat["fft_peak"] = 0
                feat["fft_energy"] = 0

            windows.append(feat)
            t_start += step_sec

        if windows:
            result[node] = windows

    return result

# ── Build dataset ─────────────────────────────────────────────────────────

print("\n[Phase 1] Loading clips and extracting per-node features...")
clip_labels = load_clip_labels()
print(f"  Clips with labels: {len(clip_labels)}")

all_node_data = {}  # {node: [{"features": ..., "binary": ..., "clip_id": ..., "t_mid": ...}]}
for node in ["n01", "n02", "n03", "n04"]:
    all_node_data[node] = []

clip_counter = 0
skipped = 0
processed = 0

for label, info in sorted(clip_labels.items()):
    csi_path = CAPTURES / f"{label}.ndjson.gz"
    if not csi_path.exists():
        skipped += 1
        continue

    node_windows = extract_pernode_features(csi_path)
    if not node_windows:
        skipped += 1
        continue

    for node, windows in node_windows.items():
        for w in windows:
            row = dict(w)
            row["binary"] = info["binary"]
            row["coarse"] = info["coarse"]
            row["clip_id"] = clip_counter
            row["clip_label"] = label
            all_node_data[node].append(row)

    clip_counter += 1
    processed += 1
    if processed % 50 == 0:
        print(f"  Processed {processed} clips...")

print(f"  Processed: {processed}, Skipped: {skipped}")
for node in ["n01", "n02", "n03", "n04"]:
    print(f"  {node}: {len(all_node_data[node])} windows")

# ── Train per-node models ─────────────────────────────────────────────────

print("\n[Phase 2] Training per-node binary models...")

feat_names = ["mean", "std", "max", "range", "pps", "tvar",
              "diff1_mean", "diff1_max", "kurtosis", "skew", "zcr",
              "sc_var_mean", "sc_var_max", "sc_var_lo", "sc_var_hi",
              "fft_peak", "fft_energy"]

node_models = {}
node_results = {}

for node in ["n01", "n02", "n03", "n04"]:
    data = all_node_data[node]
    if len(data) < 50:
        print(f"  {node}: too few windows ({len(data)}), skipping")
        continue

    df_node = pd.DataFrame(data)
    X = df_node[feat_names].replace([np.inf, -np.inf], np.nan).fillna(0).values
    y = LabelEncoder().fit_transform(df_node["binary"].values)
    groups = df_node["clip_id"].values

    n_splits = min(5, len(np.unique(groups)))
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)

    best_ba = 0
    for mname, model in [
        ("RF_bal", RandomForestClassifier(n_estimators=500, max_depth=12,
                                          class_weight="balanced", random_state=42, n_jobs=-1)),
        ("HGB_bal", HistGradientBoostingClassifier(max_iter=500, max_depth=6, learning_rate=0.03,
                                                    class_weight="balanced", random_state=42)),
    ]:
        fold_ba = []
        all_preds = np.zeros(len(y), dtype=int)
        for train_idx, test_idx in sgkf.split(X, y, groups):
            m = type(model)(**model.get_params())
            m.fit(X[train_idx], y[train_idx])
            preds = m.predict(X[test_idx])
            all_preds[test_idx] = preds
            fold_ba.append(balanced_accuracy_score(y[test_idx], preds))

        ba = np.mean(fold_ba)
        if ba > best_ba:
            best_ba = ba
            best_name = mname
            best_preds = all_preds
            best_std = np.std(fold_ba)

    node_results[node] = {
        "bal_acc": best_ba, "std": best_std, "model": best_name,
        "preds": best_preds, "y_true": y, "groups": groups,
        "t_mids": df_node["t_mid"].values, "clip_ids": df_node["clip_id"].values,
    }
    print(f"  {node}: {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f} ({len(data)} windows)")

# ── Voting ensemble ───────────────────────────────────────────────────────

print("\n[Phase 3] Voting ensemble across nodes...")

# Align windows by clip_id and t_mid (within 1s tolerance)
# For each (clip_id, t_mid), collect node predictions

from collections import defaultdict as dd

# Build aligned index
clip_t_preds = dd(lambda: {})  # (clip_id, t_bin) -> {node: pred}
clip_t_true = {}

for node, res in node_results.items():
    for i in range(len(res["preds"])):
        cid = int(res["clip_ids"][i])
        t = round(res["t_mids"][i], 0)  # round to 1s bins
        key = (cid, t)
        clip_t_preds[key][node] = res["preds"][i]
        clip_t_true[key] = res["y_true"][i]

# Vote with different thresholds
for min_agree in [1, 2, 3, 4]:
    correct = 0
    total = 0
    y_true_all = []
    y_pred_all = []

    for key, node_preds in clip_t_preds.items():
        if len(node_preds) < 2:
            continue

        votes = list(node_preds.values())
        occupied_votes = sum(votes)

        if occupied_votes >= min(min_agree, len(votes)):
            pred = 1  # OCCUPIED
        else:
            pred = 0  # EMPTY

        true = clip_t_true.get(key, 0)
        y_true_all.append(true)
        y_pred_all.append(pred)

    if y_true_all:
        ba = balanced_accuracy_score(y_true_all, y_pred_all)
        print(f"  Vote >= {min_agree}/4 agree: BalAcc={ba:.3f} ({len(y_true_all)} windows)")

# ── Temporal smoothing ────────────────────────────────────────────────────

print("\n[Phase 4] Temporal smoothing (median filter)...")

for node, res in node_results.items():
    preds = res["preds"].copy()
    y_true = res["y_true"]
    clips = res["clip_ids"]

    # Apply median filter per clip
    smoothed = preds.copy()
    for cid in np.unique(clips):
        mask = clips == cid
        if mask.sum() >= 3:
            smoothed[mask] = median_filter(preds[mask], size=3)

    ba_raw = balanced_accuracy_score(y_true, preds)
    ba_smooth = balanced_accuracy_score(y_true, smoothed)
    print(f"  {node}: raw={ba_raw:.3f} -> smoothed={ba_smooth:.3f} (delta={ba_smooth-ba_raw:+.3f})")

# ── Summary ───────────────────────────────────────────────────────────────

elapsed = time.time() - t0
print("\n" + "=" * 70)
print(f"V16 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min)")
print("=" * 70)
