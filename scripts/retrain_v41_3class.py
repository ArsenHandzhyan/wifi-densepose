"""
Retrain v4.1 model with 3 classes: empty / occupied / single_person.

Simplifies the task for reliable presence detection first.
All marker snapshots where a person was standing → "single_person"
Empty snapshots + empty recordings → "empty"
2-person recordings → "occupied"
"""

import base64
import gzip
import json
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder

SNAPSHOTS_DIR = Path("output/epoch4_live_snapshots")
CAPTURES_DIR = Path("temp/captures")
OUTPUT_DIR = Path("output/epoch4_v41_model")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NODE_IPS = [
    "192.168.0.137", "192.168.0.117", "192.168.0.143", "192.168.0.125",
    "192.168.0.110", "192.168.0.132", "192.168.0.153",
]
WINDOW_SIZE = 7

# Map original labels to 3 classes
LABEL_MAP = {
    "empty": "empty",
    "live_empty_diag": "empty",
    "live_empty_test": "empty",
    "center": "single_person",
    "door": "single_person",
    "marker1": "single_person",
    "marker2": "single_person",
    "marker3": "single_person",
    "marker4": "single_person",
    "marker5": "single_person",
    "marker6": "single_person",
    "marker7": "single_person",
    "marker8": "single_person",
    "occupied": "occupied",
}


def extract_features(data: dict) -> np.ndarray | None:
    """8 features per node: mean_rssi, std_rssi, mean_amp, std_amp, max_amp, low/mid/high_amp."""
    features = []
    for ip in NODE_IPS:
        node_data = data.get(ip) or {}
        rssi_list = node_data.get("rssi", [])
        amp_list = node_data.get("amp", [])

        if not rssi_list or not amp_list:
            features.extend([0.0] * 8)
            continue

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

    return np.array(features)


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


def load_recording_windows(chunk_files: list[Path]) -> list[dict]:
    node_packets: dict[str, list[tuple[float, np.ndarray]]] = defaultdict(list)
    for fpath in chunk_files:
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
                b64 = pkt.get("payload_b64", "")
                if not b64 or src_ip not in dict(zip(NODE_IPS, NODE_IPS)):
                    continue
                rssi, amps = parse_csi_text_payload(b64)
                if amps is not None:
                    node_packets[src_ip].append((rssi, amps))

    windows = []
    stride = max(1, WINDOW_SIZE // 2)
    # Require at least 6 of 7 nodes to have enough packets
    active_nodes = [ip for ip in NODE_IPS if len(node_packets.get(ip, [])) >= WINDOW_SIZE]
    if len(active_nodes) < 6:
        return windows
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
        # Skip windows where too many nodes are missing
        if nodes_with_data >= 6:
            windows.append({"data": window_data})
    return windows


def main():
    print("=" * 60)
    print("RETRAIN: v4.1 3-class model (empty / single_person / occupied)")
    print("=" * 60)

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
    print(f"   From snapshots: {dict(snap_counts)}")

    # 2. All empty recordings
    print("\n2. Loading empty recordings...")
    empty_patterns = [
        "empty_garage_v41_baseline_chunk*.ndjson.gz",
        "empty_garage_v41_5min_clean_chunk*.ndjson.gz",
        "empty_v41_5min_chunk*.ndjson.gz",
        "empty_garage_v41_chunk*.ndjson.gz",
    ]
    SKIP_EMPTY = {
        "empty_garage_v41_chunk0001_20260331_215819.ndjson.gz",  # min=2
        "empty_garage_v41_chunk0001_20260331_220010.ndjson.gz",  # min=1
    }
    all_empty_chunks = []
    for pat in empty_patterns:
        for f in sorted(CAPTURES_DIR.glob(pat)):
            if f.name not in SKIP_EMPTY:
                all_empty_chunks.append(f)
    all_empty_chunks = sorted(set(all_empty_chunks))
    print(f"   Empty chunk files: {len(all_empty_chunks)}")
    empty_windows = load_recording_windows(all_empty_chunks)
    print(f"   Empty windows: {len(empty_windows)}")
    for w in empty_windows:
        feat = extract_features(w["data"])
        if feat is not None:
            X_all.append(feat)
            y_all.append("empty")

    # 3. ALL 2-person recordings (filter bad chunks with < 3 pkts/node)
    print("\n3. Loading 2-person recordings...")
    twop_patterns = [
        "2person_freeform_v41_chunk*.ndjson.gz",
        "2person_v41_session3_chunk*.ndjson.gz",
        "2person_v41_session3b_chunk*.ndjson.gz",
        "2person_v41_video_chunk*.ndjson.gz",
    ]
    # Explicit skip list: chunks with too few packets per node
    SKIP_CHUNKS = {
        "2person_v41_session2_chunk0001_20260331_225348.ndjson.gz",  # min=2
    }
    all_twop_chunks = []
    for pat in twop_patterns:
        for f in sorted(CAPTURES_DIR.glob(pat)):
            if f.name not in SKIP_CHUNKS:
                all_twop_chunks.append(f)
    all_twop_chunks = sorted(set(all_twop_chunks))
    print(f"   2-person chunk files: {len(all_twop_chunks)} (skipped {len(SKIP_CHUNKS)} bad)")
    twop_windows = load_recording_windows(all_twop_chunks)
    print(f"   2-person windows: {len(twop_windows)}")
    for w in twop_windows:
        feat = extract_features(w["data"])
        if feat is not None:
            X_all.append(feat)
            y_all.append("occupied")

    # 4. Dataset
    X = np.array(X_all)
    y = np.array(y_all)
    counts = Counter(y)
    print(f"\n4. Dataset: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"   Labels: {dict(counts)}")

    # 5. Train
    print("\n5. Training GradientBoosting...")
    le = LabelEncoder()
    y_enc = le.fit_transform(y)
    print(f"   Classes: {list(le.classes_)}")

    clf = GradientBoostingClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.1,
        min_samples_leaf=5,
        subsample=0.8,
        random_state=42,
    )

    n_splits = min(5, min(counts.values()))
    if n_splits >= 2:
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        scores = cross_val_score(clf, X, y_enc, cv=skf, scoring="f1_macro")
        print(f"   CV macro F1: {scores.mean():.4f} ± {scores.std():.4f}")
        print(f"   Per-fold: {[f'{s:.4f}' for s in scores]}")
    else:
        scores = np.array([0.0])

    clf.fit(X, y_enc)
    train_acc = clf.score(X, y_enc)
    print(f"   Train accuracy: {train_acc:.4f}")

    # Feature importances
    node_names = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
    feat_names = []
    for n in node_names:
        for f in ["mean_rssi", "std_rssi", "mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]:
            feat_names.append(f"{n}_{f}")

    importances = clf.feature_importances_
    top_idx = np.argsort(importances)[-10:][::-1]
    print("\n   Top 10 features:")
    for idx in top_idx:
        name = feat_names[idx] if idx < len(feat_names) else f"feat_{idx}"
        print(f"     {name}: {importances[idx]:.4f}")

    # 6. Save
    model_path = OUTPUT_DIR / "v41_position_classifier.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({"model": clf, "label_encoder": le, "feature_names": feat_names}, f)

    meta = {
        "version": "v41_3class",
        "format": "text_csi",
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "n_classes": len(le.classes_),
        "classes": list(le.classes_),
        "window_size": WINDOW_SIZE,
        "node_ips": NODE_IPS,
        "cv_f1_macro": float(scores.mean()) if n_splits >= 2 else None,
        "train_accuracy": float(train_acc),
        "label_counts": dict(counts),
    }
    meta_path = OUTPUT_DIR / "v41_position_classifier_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n6. Saved: {model_path}")
    print(f"   Meta: {meta_path}")
    print("\nDone!")


if __name__ == "__main__":
    main()
