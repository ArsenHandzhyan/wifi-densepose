#!/usr/bin/env python3
"""
V46 Drift-Robust 3-Class Model: empty / static / motion

Key fix over V45: uses DRIFT-RESISTANT features instead of absolute amplitudes.
V45 failed because max_amp drifts 40-70% between recordings (temperature/humidity).

Drift-resistant feature strategy:
  1. std/mean ratios (coefficient of variation) instead of absolute values
  2. Inter-node amplitude ratios (relative patterns are stable)
  3. Temporal variance within window (motion signature)
  4. RSSI-normalized amplitude features
"""

import base64
import gzip
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    GradientBoostingClassifier,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report

PROJECT = Path("/Users/arsen/Desktop/wifi-densepose")
CAPTURES = PROJECT / "temp" / "captures"
OUTPUT_DIR = PROJECT / "output" / "v46_drift_robust"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NODE_IPS = [
    "192.168.0.137", "192.168.0.117", "192.168.0.143", "192.168.0.125",
    "192.168.0.110", "192.168.0.132", "192.168.0.153",
]
WINDOW_SIZE = 7
MIN_NODES = 5

# ============================================================
# Recording patterns by class (same as V45)
# ============================================================

EMPTY_PATTERNS = [
    "empty_garage_10min_epoch4_20260331_chunk*.ndjson.gz",
    "empty_garage_30min_test_chunk*.ndjson.gz",
    "empty_garage_v41_5min_clean_chunk*.ndjson.gz",
    "empty_v41_5min_chunk*.ndjson.gz",
    "empty_garage_v41_baseline_chunk*.ndjson.gz",
    "empty_garage_epoch4_20260331_chunk*.ndjson.gz",
    "empty_garage_v41_5min_chunk0001_20260331_221037.ndjson.gz",
    "empty_garage_20min_v43_chunk*.ndjson.gz",
    "empty_garage_20min_v43b_chunk*.ndjson.gz",
    # V46: add live empty diagnostic (captures drift conditions)
    "empty_diag_v45_live_chunk*.ndjson.gz",
]

STATIC_PATTERNS = [
    "marker1_1min_20260331_chunk*.ndjson.gz",
    "marker2_1min_20260331_chunk*.ndjson.gz",
    "marker3_1min_20260331_chunk*.ndjson.gz",
    "marker4_1min_20260331_chunk*.ndjson.gz",
    "marker5_1min_20260331_chunk*.ndjson.gz",
    "marker6_1min_20260331_chunk*.ndjson.gz",
    "marker7_1min_20260331_chunk*.ndjson.gz",
    "marker8_1min_20260331_chunk*.ndjson.gz",
    "center_1min_20260331_chunk*.ndjson.gz",
    "door_1min_r2_20260331_chunk*.ndjson.gz",
    "door_standing_1min_20260331_chunk*.ndjson.gz",
    "occupied_center_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_door_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker1_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker5_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker7_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker8_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "marker4_static_1p_v44_chunk*.ndjson.gz",
    "center_static_1p_v44_chunk*.ndjson.gz",
    # V46 fresh static recordings (drift conditions, 2min each)
    "static_marker1_2min_v46_chunk*.ndjson.gz",
    "static_center_2min_v46_chunk*.ndjson.gz",
    "static_marker3_2min_v46_chunk*.ndjson.gz",
]

MOTION_PATTERNS = [
    "walking_v44_20260401_010017_walk_*_chunk*.ndjson.gz",
    "2person_freeform_v41_chunk*.ndjson.gz",
    "2person_v41_session3_chunk*.ndjson.gz",
    "2person_v41_session3b_chunk*.ndjson.gz",
    "2person_v41_video_chunk*.ndjson.gz",
    "center_walking_1p_v44_chunk*.ndjson.gz",
]

SKIP_CHUNKS = {
    "empty_garage_v41_chunk0001_20260331_215819.ndjson.gz",
    "empty_garage_v41_chunk0001_20260331_220010.ndjson.gz",
    "2person_v41_session2_chunk0001_20260331_225348.ndjson.gz",
}


def parse_csi_text_payload(b64_payload: str):
    try:
        decoded = base64.b64decode(b64_payload).decode("utf-8", errors="replace")
    except Exception:
        return 0.0, None
    if not decoded.startswith("CSI_DATA"):
        return 0.0, None
    bracket_start = decoded.find('"[')
    if bracket_start < 0:
        bracket_start = decoded.find("[")
    if bracket_start < 0:
        return 0.0, None
    header_part = decoded[:bracket_start].rstrip(",")
    csi_part = decoded[bracket_start:].strip().strip('"').strip("[]").strip()
    fields = header_part.split(",")
    rssi = float(fields[4]) if len(fields) > 4 else 0.0
    try:
        vals = [int(v) for v in csi_part.split() if v.lstrip("-").isdigit()]
    except ValueError:
        return rssi, None
    if len(vals) < 10 or len(vals) % 2 != 0:
        return rssi, None
    arr = np.array(vals, dtype=np.float64)
    return rssi, np.sqrt(arr[0::2]**2 + arr[1::2]**2)


def extract_features_v46(data: dict) -> np.ndarray | None:
    """
    Drift-robust features: 11 per node × 7 nodes = 77 features.

    Per-node features (drift-resistant):
      0. std_rssi                    — RSSI variability (drift-free)
      1. cv_amp = std_amp/mean_amp   — coefficient of variation (normalized)
      2. amp_range_ratio = (max-min)/(mean+1)  — normalized dynamic range
      3. temporal_var = mean(std across packets per subcarrier)  — motion signature
      4. low_ratio = mean(low_band) / (mean_amp + 1)  — spectral shape ratio
      5. mid_ratio = mean(mid_band) / (mean_amp + 1)
      6. high_ratio = mean(high_band) / (mean_amp + 1)
      7. packet_std_amp = std of per-packet mean amplitudes  — temporal energy variation
      8. subcarrier_entropy = entropy of mean subcarrier profile  — spectral complexity
      9. rssi_range = max_rssi - min_rssi  — RSSI spread (drift-free)
     10. amp_iqr_ratio = IQR / median  — robust dispersion measure
    """
    features = []
    active = 0
    N_FEATS = 11

    for ip in NODE_IPS:
        node_data = data.get(ip) or {}
        rssi_list = node_data.get("rssi", [])
        amp_list = node_data.get("amp", [])
        if not rssi_list or not amp_list:
            features.extend([0.0] * N_FEATS)
            continue

        active += 1
        rssi_arr = np.array(rssi_list, dtype=np.float64)

        amp_mat = []
        for a in amp_list:
            if isinstance(a, list) and len(a) > 0:
                amp_mat.append(np.array(a, dtype=np.float64))
        if not amp_mat:
            features.extend([0.0] * N_FEATS)
            continue

        max_sc = max(len(a) for a in amp_mat)
        padded = np.zeros((len(amp_mat), max_sc))
        for i, a in enumerate(amp_mat):
            padded[i, :len(a)] = a

        mean_amp = np.mean(padded)
        std_amp = np.std(padded)
        third = max_sc // 3

        # Per-packet mean amplitudes (temporal energy)
        per_pkt_means = padded.mean(axis=1)

        # Subcarrier profile (mean across packets)
        sc_profile = padded.mean(axis=0)
        sc_profile_norm = sc_profile / (sc_profile.sum() + 1e-10)
        # Entropy
        sc_entropy = -np.sum(sc_profile_norm * np.log(sc_profile_norm + 1e-10))

        # Temporal variance per subcarrier (how much each subcarrier changes across packets)
        temporal_var = padded.std(axis=0).mean() if padded.shape[0] > 1 else 0.0

        # IQR
        q75 = np.percentile(padded, 75)
        q25 = np.percentile(padded, 25)
        median_amp = np.median(padded)

        features.extend([
            np.std(rssi_arr),                                              # 0: std_rssi
            std_amp / (mean_amp + 1e-6),                                   # 1: cv_amp
            (np.max(padded) - np.min(padded)) / (mean_amp + 1.0),         # 2: amp_range_ratio
            temporal_var / (mean_amp + 1e-6),                              # 3: temporal_var (normalized)
            np.mean(padded[:, :third]) / (mean_amp + 1.0) if third > 0 else 0.0,  # 4: low_ratio
            np.mean(padded[:, third:2*third]) / (mean_amp + 1.0) if third > 0 else 0.0,  # 5: mid_ratio
            np.mean(padded[:, 2*third:]) / (mean_amp + 1.0) if third > 0 else 0.0,  # 6: high_ratio
            np.std(per_pkt_means) / (np.mean(per_pkt_means) + 1e-6),      # 7: packet_std_amp (CV of temporal)
            sc_entropy,                                                     # 8: subcarrier_entropy
            np.max(rssi_arr) - np.min(rssi_arr),                           # 9: rssi_range
            (q75 - q25) / (median_amp + 1.0),                             # 10: amp_iqr_ratio
        ])

    if active < MIN_NODES:
        return None
    return np.array(features)


def load_chunk_windows(fpath: Path, stride: int = 1) -> list[dict]:
    node_packets: dict[str, list[tuple[float, np.ndarray]]] = defaultdict(list)
    with gzip.open(fpath, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pkt = json.loads(line)
            except json.JSONDecodeError:
                continue
            src_ip = pkt.get("src_ip", "")
            if src_ip not in NODE_IPS:
                continue
            b64 = pkt.get("payload_b64", "")
            if not b64:
                continue
            rssi, amps = parse_csi_text_payload(b64)
            if amps is not None:
                node_packets[src_ip].append((rssi, amps))
    active_nodes = [ip for ip in NODE_IPS if len(node_packets.get(ip, [])) >= WINDOW_SIZE]
    if len(active_nodes) < MIN_NODES:
        return []
    windows = []
    min_pkts = min(len(node_packets[ip]) for ip in active_nodes)
    for start in range(0, min_pkts - WINDOW_SIZE + 1, stride):
        end = start + WINDOW_SIZE
        window_data = {}
        nodes_ok = 0
        for ip in NODE_IPS:
            pkts = node_packets.get(ip, [])
            if len(pkts) >= end:
                window_data[ip] = {
                    "rssi": [p[0] for p in pkts[start:end]],
                    "amp": [p[1].tolist() for p in pkts[start:end]],
                }
                nodes_ok += 1
            else:
                window_data[ip] = {"rssi": [], "amp": []}
        if nodes_ok >= MIN_NODES:
            windows.append({"data": window_data})
    return windows


def collect_files(patterns):
    files = []
    seen = set()
    for pat in patterns:
        for f in sorted(CAPTURES.glob(pat)):
            if f.name not in SKIP_CHUNKS and f.name not in seen:
                seen.add(f.name)
                files.append(f)
    return sorted(files)


def load_class_data(patterns, label, stride=1):
    files = collect_files(patterns)
    X, y = [], []
    for f in files:
        windows = load_chunk_windows(f, stride=stride)
        for w in windows:
            feat = extract_features_v46(w["data"])
            if feat is not None:
                X.append(feat)
                y.append(label)
    return files, X, y


def main():
    print("=" * 60)
    print("V46 Drift-Robust Three-Class: empty / static / motion")
    print("=" * 60)

    # 1. Load each class
    print("\n1. EMPTY recordings...")
    empty_files, X_empty, y_empty = load_class_data(EMPTY_PATTERNS, "empty")
    print(f"   Files: {len(empty_files)}, Windows: {len(X_empty)}")

    print("\n2. STATIC recordings (standing still)...")
    static_files, X_static, y_static = load_class_data(STATIC_PATTERNS, "static")
    print(f"   Files: {len(static_files)}, Windows: {len(X_static)}")

    print("\n3. MOTION recordings (walking)...")
    motion_files, X_motion, y_motion = load_class_data(MOTION_PATTERNS, "motion")
    print(f"   Files: {len(motion_files)}, Windows: {len(X_motion)}")

    # Combine
    X_all = X_empty + X_static + X_motion
    y_all = y_empty + y_static + y_motion
    X = np.array(X_all)
    y = np.array(y_all)
    counts = Counter(y)
    print(f"\n4. DATASET: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"   {dict(counts)}")

    if len(counts) < 3:
        print("   WARNING: fewer than 3 classes found!")

    # Balance if needed
    min_class_count = min(counts.values())
    max_class_count = max(counts.values())
    ratio = max_class_count / max(1, min_class_count)
    print(f"   Imbalance ratio: {ratio:.1f}x")

    if ratio > 3.0:
        print("   Balancing via undersampling...")
        target_per_class = int(min_class_count * 2.5)
        keep_indices = []
        np.random.seed(42)
        for cls in sorted(set(y)):
            cls_idx = np.where(y == cls)[0]
            if len(cls_idx) > target_per_class:
                sampled = np.random.choice(cls_idx, size=target_per_class, replace=False)
                keep_indices.extend(sampled)
            else:
                keep_indices.extend(cls_idx)
        keep_indices = np.sort(keep_indices)
        X, y = X[keep_indices], y[keep_indices]
        counts = Counter(y)
        print(f"   After balance: {dict(counts)}")

    # 5. Train
    print("\n5. Training classifiers...")
    n_splits = min(5, min(counts.values()))
    n_splits = max(2, n_splits)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    models = {
        "HGB-300": HistGradientBoostingClassifier(
            max_iter=300, random_state=42, class_weight="balanced"
        ),
        "RF-1000": RandomForestClassifier(
            n_estimators=1000, random_state=42, class_weight="balanced", n_jobs=-1
        ),
        "GBM-500": GradientBoostingClassifier(
            n_estimators=500, max_depth=3, learning_rate=0.05,
            subsample=0.8, random_state=42
        ),
    }

    best_name, best_score = None, -1
    for name, clf in models.items():
        scores = cross_val_score(clf, X, y, cv=skf, scoring="f1_macro")
        print(f"   {name}: F1_macro={scores.mean():.4f} ± {scores.std():.4f}  [{', '.join(f'{s:.3f}' for s in scores)}]")
        if scores.mean() > best_score:
            best_score = scores.mean()
            best_name = name

    print(f"\n   Best: {best_name} (F1_macro={best_score:.4f})")

    # Fit best model on all data
    clf = models[best_name]
    clf.fit(X, y)
    y_pred = clf.predict(X)
    print(f"   Train accuracy: {clf.score(X, y):.4f}")
    print("\n   Classification Report (train):")
    print(classification_report(y, y_pred, digits=4))

    # Feature importances
    node_names = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
    feat_suffixes = [
        "std_rssi", "cv_amp", "amp_range_ratio", "temporal_var",
        "low_ratio", "mid_ratio", "high_ratio",
        "pkt_std_amp", "sc_entropy", "rssi_range", "amp_iqr_ratio"
    ]
    feat_names = [f"{n}_{f}" for n in node_names for f in feat_suffixes]

    if hasattr(clf, "feature_importances_"):
        imp = clf.feature_importances_
        top = np.argsort(imp)[-15:][::-1]
        print("   Top 15 features:")
        for i in top:
            print(f"     {feat_names[i]}: {imp[i]:.4f}")

    # 6. Save
    from sklearn.preprocessing import LabelEncoder
    le = LabelEncoder()
    le.classes_ = np.array(sorted(set(y)))

    model_data = {
        "model": clf,
        "label_encoder": le,
        "feature_names": feat_names,
        "version": "v46",
        "feature_extractor": "extract_features_v46",
    }

    # Save to V46 own dir
    v46_path = OUTPUT_DIR / "v46_drift_robust.pkl"
    with open(v46_path, "wb") as f:
        pickle.dump(model_data, f)

    # Also save to v41 model path (production hot-swap)
    v41_path = PROJECT / "output" / "epoch4_v41_model" / "v41_position_classifier.pkl"
    with open(v41_path, "wb") as f:
        pickle.dump(model_data, f)

    meta = {
        "version": "v46_drift_robust",
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "classes": list(le.classes_),
        "cv_f1_macro": float(best_score),
        "best_model": best_name,
        "label_counts": {k: int(v) for k, v in counts.items()},
        "empty_files": len(empty_files),
        "static_files": len(static_files),
        "motion_files": len(motion_files),
        "window_size": WINDOW_SIZE,
        "min_nodes": MIN_NODES,
        "feature_type": "drift_robust_v46",
        "features_per_node": 11,
        "drift_resistant": True,
    }

    for path in [OUTPUT_DIR / "v46_meta.json", PROJECT / "output" / "epoch4_v41_model" / "v41_position_classifier_meta.json"]:
        with open(path, "w") as f:
            json.dump(meta, f, indent=2)

    print(f"\n6. Saved:")
    print(f"   {v46_path}")
    print(f"   {v41_path} (production)")
    print(f"   Meta: {OUTPUT_DIR / 'v46_meta.json'}")
    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
