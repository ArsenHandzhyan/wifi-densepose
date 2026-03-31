#!/usr/bin/env python3
"""
V43 Binary Classifier — SUPER BALANCED empty vs present.

Uses ALL available recordings from 2026-03-31:
- empty: 10min + 30min + 5min recordings = massive empty corpus
- present: all marker, center, door, 2person recordings
- Filters out chunks with < 4 active nodes (network dropout)
- class_weight='balanced' + undersampling majority class
"""

import base64
import gzip
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report

PROJECT = Path("/Users/arsen/Desktop/wifi-densepose")
CAPTURES = PROJECT / "temp" / "captures"
OUTPUT_DIR = PROJECT / "output" / "v43_binary_superbalanced"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NODE_IPS = [
    "192.168.0.137", "192.168.0.117", "192.168.0.143", "192.168.0.125",
    "192.168.0.110", "192.168.0.132", "192.168.0.153",
]
WINDOW_SIZE = 7
MIN_NODES = 5  # At least 5 of 7 nodes must have data

# ============================================================
# RECORDINGS — ALL available data from 2026-03-31
# ============================================================

# EMPTY recordings (ground truth: nobody in garage)
EMPTY_PATTERNS = [
    # 10min empty recording (11 chunks)
    "empty_garage_10min_epoch4_20260331_chunk*.ndjson.gz",
    # 30min empty test (18 chunks!)
    "empty_garage_30min_test_chunk*.ndjson.gz",
    # 5min clean empty
    "empty_garage_v41_5min_clean_chunk*.ndjson.gz",
    # 5min empty
    "empty_v41_5min_chunk*.ndjson.gz",
    # Baseline empty
    "empty_garage_v41_baseline_chunk*.ndjson.gz",
    # Short empty
    "empty_garage_epoch4_20260331_chunk*.ndjson.gz",
    # 5min empty (another)
    "empty_garage_v41_5min_chunk0001_20260331_221037.ndjson.gz",
]

# PRESENT recordings (ground truth: 1 or 2 people in garage)
PRESENT_PATTERNS = [
    # 1-person marker recordings
    "marker1_1min_20260331_chunk*.ndjson.gz",
    "marker2_1min_20260331_chunk*.ndjson.gz",
    "marker3_1min_20260331_chunk*.ndjson.gz",
    "marker4_1min_20260331_chunk*.ndjson.gz",
    "marker5_1min_20260331_chunk*.ndjson.gz",
    "marker6_1min_20260331_chunk*.ndjson.gz",
    "marker7_1min_20260331_chunk*.ndjson.gz",
    "marker8_1min_20260331_chunk*.ndjson.gz",
    # 1-person center
    "center_1min_20260331_chunk*.ndjson.gz",
    # 1-person door
    "door_1min_r2_20260331_chunk*.ndjson.gz",
    "door_standing_1min_20260331_chunk*.ndjson.gz",
    # 1-person occupied static positions
    "occupied_center_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_door_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker1_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker5_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker7_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker8_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    # 2-person freeform (6 chunks)
    "2person_freeform_v41_chunk*.ndjson.gz",
    # 2-person session3 + session3b
    "2person_v41_session3_chunk*.ndjson.gz",
    "2person_v41_session3b_chunk*.ndjson.gz",
    # 2-person with video
    "2person_v41_video_chunk*.ndjson.gz",
]

# Known bad chunks (network dropouts, wrong network, etc.)
SKIP_CHUNKS = {
    "empty_garage_v41_chunk0001_20260331_215819.ndjson.gz",  # too few pkts
    "empty_garage_v41_chunk0001_20260331_220010.ndjson.gz",  # too few pkts
    "2person_v41_session2_chunk0001_20260331_225348.ndjson.gz",  # wrong network
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


def extract_features(data: dict) -> np.ndarray | None:
    """8 features per node: mean_rssi, std_rssi, mean_amp, std_amp, max_amp, low/mid/high_amp."""
    features = []
    active = 0
    for ip in NODE_IPS:
        node_data = data.get(ip) or {}
        rssi_list = node_data.get("rssi", [])
        amp_list = node_data.get("amp", [])

        if not rssi_list or not amp_list:
            features.extend([0.0] * 8)
            continue

        active += 1
        rssi_arr = np.array(rssi_list, dtype=np.float64)
        amp_mat = []
        for a in amp_list:
            if isinstance(a, list) and len(a) > 0:
                amp_mat.append(np.array(a, dtype=np.float64))

        if not amp_mat:
            features.extend([0.0] * 8)
            continue

        max_sc = max(len(a) for a in amp_mat)
        padded = np.zeros((len(amp_mat), max_sc))
        for i, a in enumerate(amp_mat):
            padded[i, :len(a)] = a

        third = max_sc // 3
        features.extend([
            np.mean(rssi_arr),
            np.std(rssi_arr),
            np.mean(padded),
            np.std(padded),
            np.max(padded),
            np.mean(padded[:, :third]) if third > 0 else 0.0,
            np.mean(padded[:, third:2*third]) if third > 0 else 0.0,
            np.mean(padded[:, 2*third:]) if third > 0 else 0.0,
        ])

    if active < MIN_NODES:
        return None
    return np.array(features)


def load_chunk_windows(fpath: Path) -> list[dict]:
    """Load a single chunk file and extract sliding windows."""
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

    # Check node coverage
    active_nodes = [ip for ip in NODE_IPS if len(node_packets.get(ip, [])) >= WINDOW_SIZE]
    if len(active_nodes) < MIN_NODES:
        return []

    windows = []
    stride = max(1, WINDOW_SIZE // 2)
    min_pkts = min(len(node_packets[ip]) for ip in active_nodes)
    for start in range(0, min_pkts - WINDOW_SIZE + 1, stride):
        end = start + WINDOW_SIZE
        window_data = {}
        nodes_with_data = 0
        for ip in NODE_IPS:
            pkts = node_packets.get(ip, [])
            if len(pkts) >= end:
                window_data[ip] = {
                    "rssi": [p[0] for p in pkts[start:end]],
                    "amp": [p[1].tolist() for p in pkts[start:end]],
                }
                nodes_with_data += 1
            else:
                window_data[ip] = {"rssi": [], "amp": []}
        if nodes_with_data >= MIN_NODES:
            windows.append({"data": window_data})
    return windows


def collect_files(patterns):
    """Collect unique files matching patterns, excluding bad chunks."""
    files = []
    seen = set()
    for pat in patterns:
        for f in sorted(CAPTURES.glob(pat)):
            if f.name not in SKIP_CHUNKS and f.name not in seen:
                seen.add(f.name)
                files.append(f)
    return sorted(files)


def main():
    print("=" * 60)
    print("V43 Binary SUPER-BALANCED: empty vs present")
    print("=" * 60)

    # Also load snapshots
    SNAPSHOTS_DIR = PROJECT / "output" / "epoch4_live_snapshots"
    LABEL_MAP = {
        "empty": "empty",
        "live_empty_diag": "empty",
        "live_empty_test": "empty",
        "center": "present",
        "door": "present",
        "marker1": "present", "marker2": "present", "marker3": "present",
        "marker4": "present", "marker5": "present", "marker6": "present",
        "marker7": "present", "marker8": "present",
        "occupied": "present",
    }

    X_all, y_all = [], []

    # 1. Snapshots
    print("\n1. Loading calibration snapshots...")
    snap_files = sorted(SNAPSHOTS_DIR.glob("snap_*.json"))
    snap_counts = Counter()
    for sf in snap_files:
        snap = json.load(open(sf))
        orig_label = snap.get("label", "")
        label = LABEL_MAP.get(orig_label)
        if label is None:
            continue
        feat = extract_features(snap.get("data", {}))
        if feat is not None:
            X_all.append(feat)
            y_all.append(label)
            snap_counts[label] += 1
    print(f"   Snapshots: {dict(snap_counts)}")

    # 2. Empty recordings
    print("\n2. Loading EMPTY recordings...")
    empty_files = collect_files(EMPTY_PATTERNS)
    print(f"   Found {len(empty_files)} empty chunk files")
    empty_win_count = 0
    for f in empty_files:
        windows = load_chunk_windows(f)
        for w in windows:
            feat = extract_features(w["data"])
            if feat is not None:
                X_all.append(feat)
                y_all.append("empty")
                empty_win_count += 1
    print(f"   Empty windows: {empty_win_count}")

    # 3. Present recordings
    print("\n3. Loading PRESENT recordings...")
    present_files = collect_files(PRESENT_PATTERNS)
    print(f"   Found {len(present_files)} present chunk files")
    present_win_count = 0
    for f in present_files:
        windows = load_chunk_windows(f)
        for w in windows:
            feat = extract_features(w["data"])
            if feat is not None:
                X_all.append(feat)
                y_all.append("present")
                present_win_count += 1
    print(f"   Present windows: {present_win_count}")

    # 4. Dataset summary
    X = np.array(X_all)
    y = np.array(y_all)
    counts = Counter(y)
    print(f"\n4. TOTAL: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"   Labels: {dict(counts)}")
    ratio = max(counts.values()) / min(counts.values())
    print(f"   Imbalance ratio: {ratio:.1f}x")

    # 5. Undersample majority if very imbalanced
    if ratio > 2.0:
        print(f"\n   Undersampling majority class to 2x minority...")
        minority_label = min(counts, key=counts.get)
        majority_label = max(counts, key=counts.get)
        minority_count = counts[minority_label]
        target = minority_count * 2

        minority_idx = np.where(y == minority_label)[0]
        majority_idx = np.where(y == majority_label)[0]
        np.random.seed(42)
        sampled_majority = np.random.choice(majority_idx, size=min(target, len(majority_idx)), replace=False)
        keep_idx = np.sort(np.concatenate([minority_idx, sampled_majority]))
        X = X[keep_idx]
        y = y[keep_idx]
        counts = Counter(y)
        print(f"   After undersampling: {dict(counts)}")

    # 6. Train multiple models
    print("\n5. Training classifiers...")
    node_names = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
    feat_names = []
    for n in node_names:
        for f in ["mean_rssi", "std_rssi", "mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]:
            feat_names.append(f"{n}_{f}")

    n_splits = min(5, min(counts.values()))
    skf = StratifiedKFold(n_splits=max(2, n_splits), shuffle=True, random_state=42)

    models = {
        "GBM-300": GradientBoostingClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.1,
            min_samples_leaf=5, subsample=0.8, random_state=42,
        ),
        "RF-500-balanced": RandomForestClassifier(
            n_estimators=500, random_state=42, class_weight="balanced", n_jobs=-1,
        ),
        "HGB-200": HistGradientBoostingClassifier(
            max_iter=200, random_state=42, class_weight="balanced",
        ),
    }

    best_name, best_score = None, -1
    cv_results = {}
    for name, clf in models.items():
        scores = cross_val_score(clf, X, y, cv=skf, scoring="f1_macro")
        mean_f1 = float(scores.mean())
        cv_results[name] = {"mean_f1": mean_f1, "std": float(scores.std()), "folds": [float(s) for s in scores]}
        print(f"   {name}: F1={mean_f1:.4f} ± {scores.std():.4f}")
        if mean_f1 > best_score:
            best_score = mean_f1
            best_name = name

    print(f"\n   Best: {best_name} (F1={best_score:.4f})")

    # 7. Train final
    clf = models[best_name]
    clf.fit(X, y)
    train_acc = clf.score(X, y)
    y_pred = clf.predict(X)
    print(f"\n6. Final model train accuracy: {train_acc:.4f}")
    print(classification_report(y, y_pred, target_names=sorted(set(y))))

    # Feature importances
    if hasattr(clf, 'feature_importances_'):
        importances = clf.feature_importances_
        top_idx = np.argsort(importances)[-10:][::-1]
        print("   Top 10 features:")
        for idx in top_idx:
            name = feat_names[idx] if idx < len(feat_names) else f"feat_{idx}"
            print(f"     {name}: {importances[idx]:.4f}")

    # 8. Save
    model_path = OUTPUT_DIR / "v43_binary_superbalanced.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": clf,
            "label_encoder": None,  # binary, classes are in model.classes_
            "feature_names": feat_names,
            "classes": list(clf.classes_),
        }, f)

    meta = {
        "version": "v43_binary_superbalanced",
        "format": "text_csi",
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "n_classes": 2,
        "classes": list(clf.classes_),
        "window_size": WINDOW_SIZE,
        "node_ips": NODE_IPS,
        "cv_f1_macro": best_score,
        "best_model": best_name,
        "cv_results": cv_results,
        "train_accuracy": float(train_acc),
        "label_counts": dict(counts),
        "empty_files": len(empty_files),
        "present_files": len(present_files),
        "empty_windows": empty_win_count,
        "present_windows": present_win_count,
    }
    meta_path = OUTPUT_DIR / "v43_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n7. Saved: {model_path}")
    print(f"   Meta:  {meta_path}")
    print("\nDone!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
