#!/usr/bin/env python3
"""
V44 Binary — RECORDINGS ONLY, no snapshots.

Snapshots have different statistical properties than runtime windows.
Using only chunk recordings ensures train/inference feature distribution match.
"""

import base64
import gzip
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report

PROJECT = Path("/Users/arsen/Desktop/wifi-densepose")
CAPTURES = PROJECT / "temp" / "captures"
OUTPUT_DIR = PROJECT / "output" / "v44_binary_recordings_only"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NODE_IPS = [
    "192.168.0.137", "192.168.0.117", "192.168.0.143", "192.168.0.125",
    "192.168.0.110", "192.168.0.132", "192.168.0.153",
]
WINDOW_SIZE = 7
MIN_NODES = 5

# ============================================================
# ALL RECORDINGS — only chunk files, no snapshots
# ============================================================

EMPTY_PATTERNS = [
    "empty_garage_10min_epoch4_20260331_chunk*.ndjson.gz",
    "empty_garage_30min_test_chunk*.ndjson.gz",
    "empty_garage_v41_5min_clean_chunk*.ndjson.gz",
    "empty_v41_5min_chunk*.ndjson.gz",
    "empty_garage_v41_baseline_chunk*.ndjson.gz",
    "empty_garage_epoch4_20260331_chunk*.ndjson.gz",
    "empty_garage_v41_5min_chunk0001_20260331_221037.ndjson.gz",
    # NEW: 20min recording from tonight
    "empty_garage_20min_v43_chunk*.ndjson.gz",
    "empty_garage_20min_v43b_chunk*.ndjson.gz",
]

PRESENT_PATTERNS = [
    # 1-person markers
    "marker1_1min_20260331_chunk*.ndjson.gz",
    "marker2_1min_20260331_chunk*.ndjson.gz",
    "marker3_1min_20260331_chunk*.ndjson.gz",
    "marker4_1min_20260331_chunk*.ndjson.gz",
    "marker5_1min_20260331_chunk*.ndjson.gz",
    "marker6_1min_20260331_chunk*.ndjson.gz",
    "marker7_1min_20260331_chunk*.ndjson.gz",
    "marker8_1min_20260331_chunk*.ndjson.gz",
    # 1-person positions
    "center_1min_20260331_chunk*.ndjson.gz",
    "door_1min_r2_20260331_chunk*.ndjson.gz",
    "door_standing_1min_20260331_chunk*.ndjson.gz",
    "occupied_center_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_door_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker1_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker5_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker7_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_marker8_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    # 2-person
    "2person_freeform_v41_chunk*.ndjson.gz",
    "2person_v41_session3_chunk*.ndjson.gz",
    "2person_v41_session3b_chunk*.ndjson.gz",
    "2person_v41_video_chunk*.ndjson.gz",
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


def extract_features(data: dict) -> np.ndarray | None:
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


def load_chunk_windows(fpath: Path, stride: int = 1) -> list[dict]:
    """Sliding window with stride=1 for maximum data extraction."""
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


def main():
    print("=" * 60)
    print("V44 Binary — RECORDINGS ONLY (stride=1 for max windows)")
    print("=" * 60)

    X_all, y_all = [], []

    # Empty
    print("\n1. EMPTY recordings...")
    empty_files = collect_files(EMPTY_PATTERNS)
    print(f"   Files: {len(empty_files)}")
    for f in empty_files:
        windows = load_chunk_windows(f, stride=1)
        for w in windows:
            feat = extract_features(w["data"])
            if feat is not None:
                X_all.append(feat)
                y_all.append("empty")
    empty_total = sum(1 for y in y_all if y == "empty")
    print(f"   Windows: {empty_total}")

    # Present
    print("\n2. PRESENT recordings...")
    present_files = collect_files(PRESENT_PATTERNS)
    print(f"   Files: {len(present_files)}")
    for f in present_files:
        windows = load_chunk_windows(f, stride=1)
        for w in windows:
            feat = extract_features(w["data"])
            if feat is not None:
                X_all.append(feat)
                y_all.append("present")
    present_total = len(y_all) - empty_total
    print(f"   Windows: {present_total}")

    X = np.array(X_all)
    y = np.array(y_all)
    counts = Counter(y)
    print(f"\n3. TOTAL: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"   {dict(counts)}")
    ratio = max(counts.values()) / max(1, min(counts.values()))
    print(f"   Ratio: {ratio:.1f}x")

    # Balance via undersampling if needed
    if ratio > 2.5:
        minority = min(counts, key=counts.get)
        majority = max(counts, key=counts.get)
        target = int(counts[minority] * 2)
        min_idx = np.where(y == minority)[0]
        maj_idx = np.where(y == majority)[0]
        np.random.seed(42)
        sampled = np.random.choice(maj_idx, size=min(target, len(maj_idx)), replace=False)
        keep = np.sort(np.concatenate([min_idx, sampled]))
        X, y = X[keep], y[keep]
        counts = Counter(y)
        print(f"   After balance: {dict(counts)}")

    # Train
    print("\n4. Training...")
    n_splits = min(5, min(counts.values()))
    skf = StratifiedKFold(n_splits=max(2, n_splits), shuffle=True, random_state=42)

    models = {
        "HGB-300": HistGradientBoostingClassifier(max_iter=300, random_state=42, class_weight="balanced"),
        "RF-1000": RandomForestClassifier(n_estimators=1000, random_state=42, class_weight="balanced", n_jobs=-1),
        "GBM-500": GradientBoostingClassifier(n_estimators=500, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42),
    }

    best_name, best_score = None, -1
    for name, clf in models.items():
        scores = cross_val_score(clf, X, y, cv=skf, scoring="f1_macro")
        print(f"   {name}: F1={scores.mean():.4f} ± {scores.std():.4f}")
        if scores.mean() > best_score:
            best_score = scores.mean()
            best_name = name

    print(f"\n   Best: {best_name} (F1={best_score:.4f})")
    clf = models[best_name]
    clf.fit(X, y)
    print(f"   Train acc: {clf.score(X, y):.4f}")
    print(classification_report(y, clf.predict(X)))

    # Feature importances
    if hasattr(clf, 'feature_importances_'):
        node_names = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
        feat_names = [f"{n}_{f}" for n in node_names for f in ["mean_rssi", "std_rssi", "mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]]
        imp = clf.feature_importances_
        top = np.argsort(imp)[-10:][::-1]
        print("   Top features:")
        for i in top:
            print(f"     {feat_names[i]}: {imp[i]:.4f}")

    # Save in v41-compatible format
    from sklearn.preprocessing import LabelEncoder
    le = LabelEncoder()
    le.classes_ = np.array(sorted(set(y)))

    node_names = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
    feat_names = [f"{n}_{f}" for n in node_names for f in ["mean_rssi", "std_rssi", "mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]]

    # Save to v41 model path (hot-swappable)
    v41_path = PROJECT / "output" / "epoch4_v41_model" / "v41_position_classifier.pkl"
    with open(v41_path, "wb") as f:
        pickle.dump({"model": clf, "label_encoder": le, "feature_names": feat_names}, f)

    meta = {
        "version": "v44_binary_recordings_only",
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "classes": list(le.classes_),
        "cv_f1_macro": best_score,
        "best_model": best_name,
        "label_counts": dict(counts),
        "empty_files": len(empty_files),
        "present_files": len(present_files),
    }
    v41_meta = PROJECT / "output" / "epoch4_v41_model" / "v41_position_classifier_meta.json"
    with open(v41_meta, "w") as f:
        json.dump(meta, f, indent=2)

    # Also save to own dir
    with open(OUTPUT_DIR / "v44_model.pkl", "wb") as f2:
        pickle.dump({"model": clf, "label_encoder": le, "feature_names": feat_names}, f2)

    print(f"\n5. Saved to {v41_path}")
    print("Done!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
