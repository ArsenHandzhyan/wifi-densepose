"""
Retrain position classifier using v4.1 TEXT-format data only.

Data sources:
1. Calibration snapshots (output/epoch4_live_snapshots/snap_*.json) — labeled positions
2. Empty baseline recording (temp/captures/empty_garage_v41_baseline_chunk*.ndjson.gz)
3. 2-person recording (temp/captures/2person_freeform_v41_chunk*.ndjson.gz) — labeled "occupied"

Output: output/epoch4_v41_model/
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

# ── Paths ──────────────────────────────────────────────────────────────────
SNAPSHOTS_DIR = Path("output/epoch4_live_snapshots")
CAPTURES_DIR = Path("temp/captures")
OUTPUT_DIR = Path("output/epoch4_v41_model")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NODE_IPS = [
    "192.168.0.137",  # n01
    "192.168.0.117",  # n02
    "192.168.0.143",  # n03
    "192.168.0.125",  # n04
    "192.168.0.110",  # n05
    "192.168.0.132",  # n06
    "192.168.0.153",  # n07
]

NODE_IP_TO_NAME = {
    "192.168.0.137": "n01", "192.168.0.117": "n02",
    "192.168.0.143": "n03", "192.168.0.125": "n04",
    "192.168.0.110": "n05", "192.168.0.132": "n06",
    "192.168.0.153": "n07",
}

WINDOW_SIZE = 10  # packets per node per window (matches snapshots)


def extract_features_from_snapshot(snap: dict) -> np.ndarray | None:
    """Extract feature vector from a calibration snapshot.

    Each snapshot has data[ip] = {rssi: [...], amp: [[subcarriers], ...]}
    We compute per-node: mean_rssi, std_rssi, mean_amp_per_sc (aggregated), std_amp, etc.
    """
    data = snap.get("data", {})
    features = []

    for ip in NODE_IPS:
        node_data = data.get(ip) or {}
        rssi_list = node_data.get("rssi", [])
        amp_list = node_data.get("amp", [])

        if not rssi_list or not amp_list:
            # Node missing — fill with zeros
            features.extend([0.0] * 8)  # 8 features per node
            continue

        rssi_arr = np.array(rssi_list, dtype=np.float64)
        # amp_list is list of lists (each packet has subcarrier amplitudes)
        amp_mat = []
        for a in amp_list:
            if isinstance(a, list) and len(a) > 0:
                amp_mat.append(np.array(a, dtype=np.float64))

        if not amp_mat:
            features.extend([0.0] * 8)
            continue

        # Pad/truncate to same length
        max_sc = max(len(a) for a in amp_mat)
        padded = np.zeros((len(amp_mat), max_sc))
        for i, a in enumerate(amp_mat):
            padded[i, :len(a)] = a

        # Features per node
        mean_rssi = np.mean(rssi_arr)
        std_rssi = np.std(rssi_arr)
        mean_amp = np.mean(padded)
        std_amp = np.std(padded)
        max_amp = np.max(padded)
        # Spectral features: mean of low/mid/high subcarriers
        n_sc = padded.shape[1]
        third = n_sc // 3
        low_amp = np.mean(padded[:, :third]) if third > 0 else 0.0
        mid_amp = np.mean(padded[:, third:2*third]) if third > 0 else 0.0
        high_amp = np.mean(padded[:, 2*third:]) if third > 0 else 0.0

        features.extend([mean_rssi, std_rssi, mean_amp, std_amp, max_amp, low_amp, mid_amp, high_amp])

    return np.array(features) if features else None


def parse_csi_text_payload(b64_payload: str) -> tuple[str, float, np.ndarray | None]:
    """Decode base64 CSI_DATA payload.

    Returns (mac, rssi, amplitude_array_or_None).
    """
    try:
        decoded = base64.b64decode(b64_payload).decode("utf-8", errors="replace")
    except Exception:
        return "", 0.0, None

    if not decoded.startswith("CSI_DATA"):
        return "", 0.0, None

    bracket_start = decoded.find('"[')
    if bracket_start < 0:
        bracket_start = decoded.find("[")
    if bracket_start < 0:
        return "", 0.0, None

    header_part = decoded[:bracket_start].rstrip(",")
    csi_part = decoded[bracket_start:].strip().strip('"').strip("[]").strip()

    fields = header_part.split(",")
    mac = fields[2] if len(fields) > 2 else ""
    rssi = float(fields[4]) if len(fields) > 4 else 0.0

    try:
        vals = [int(v) for v in csi_part.split() if v.lstrip("-").isdigit()]
    except ValueError:
        return mac, rssi, None

    if len(vals) < 10 or len(vals) % 2 != 0:
        return mac, rssi, None

    arr = np.array(vals, dtype=np.float64)
    amps = np.sqrt(arr[0::2]**2 + arr[1::2]**2)
    return mac, rssi, amps


def load_recording_windows(chunk_files: list[Path], window_size: int = WINDOW_SIZE) -> list[dict]:
    """Load CSI recording chunks and create sliding windows.

    Returns list of {ip: {rssi: [...], amp: [[...], ...]}} dicts,
    matching the snapshot format.
    """
    # Collect all packets per node
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
                if not b64 or src_ip not in NODE_IP_TO_NAME:
                    continue

                mac, rssi, amps = parse_csi_text_payload(b64)
                if amps is not None:
                    node_packets[src_ip].append((rssi, amps))

    # Create sliding windows with 50% overlap for data augmentation
    windows = []
    stride = max(1, window_size // 2)

    active_nodes = [ip for ip in NODE_IPS if len(node_packets.get(ip, [])) >= window_size]
    if not active_nodes:
        return windows

    min_pkts = min(len(node_packets[ip]) for ip in active_nodes)

    for start in range(0, min_pkts - window_size + 1, stride):
        end = start + window_size
        window_data = {}

        for ip in NODE_IPS:
            pkts = node_packets.get(ip, [])
            if len(pkts) >= end:
                rssi_list = [p[0] for p in pkts[start:end]]
                amp_list = [p[1].tolist() for p in pkts[start:end]]
                window_data[ip] = {"rssi": rssi_list, "amp": amp_list}
            else:
                window_data[ip] = {"rssi": [], "amp": []}

        windows.append({"data": window_data})

    return windows


def main():
    print("=" * 60)
    print("RETRAIN: v4.1 TEXT-format position model")
    print("=" * 60)

    X_all = []
    y_all = []

    # ── 1. Load calibration snapshots ──────────────────────────────────────
    print("\n1. Loading calibration snapshots...")
    snap_files = sorted(SNAPSHOTS_DIR.glob("snap_*.json"))
    snap_labels = Counter()

    # Merge rare/diagnostic labels into canonical ones
    LABEL_MAP = {
        "live_empty_diag": "empty",
        "live_empty_test": "empty",
    }

    for sf in snap_files:
        snap = json.load(open(sf))
        label = snap.get("label", "")
        if not label:
            continue
        label = LABEL_MAP.get(label, label)

        feat = extract_features_from_snapshot(snap)
        if feat is not None and len(feat) > 0:
            X_all.append(feat)
            y_all.append(label)
            snap_labels[label] += 1

    print(f"   Snapshots loaded: {len(snap_files)}, usable: {sum(snap_labels.values())}")
    for label, count in sorted(snap_labels.items()):
        print(f"     {label}: {count}")

    # ── 2. Load empty baseline recording ───────────────────────────────────
    print("\n2. Loading empty baseline recording...")
    empty_chunks = sorted(CAPTURES_DIR.glob("empty_garage_v41_baseline_chunk*.ndjson.gz"))
    empty_windows = load_recording_windows(empty_chunks)
    print(f"   Empty windows: {len(empty_windows)}")

    for w in empty_windows:
        feat = extract_features_from_snapshot(w)
        if feat is not None:
            X_all.append(feat)
            y_all.append("empty")

    # ── 3. Load 2-person recording ─────────────────────────────────────────
    print("\n3. Loading 2-person recording...")
    twop_chunks = sorted(CAPTURES_DIR.glob("2person_freeform_v41_chunk*.ndjson.gz"))
    twop_windows = load_recording_windows(twop_chunks)
    print(f"   2-person windows: {len(twop_windows)}")

    for w in twop_windows:
        feat = extract_features_from_snapshot(w)
        if feat is not None:
            X_all.append(feat)
            y_all.append("occupied")

    # ── 4. Build dataset ───────────────────────────────────────────────────
    X = np.array(X_all)
    y = np.array(y_all)
    print(f"\n4. Dataset: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"   Labels: {dict(Counter(y))}")

    if X.shape[0] < 10:
        print("ERROR: Too few samples!")
        sys.exit(1)

    # ── 5. Train classifier ────────────────────────────────────────────────
    print("\n5. Training GradientBoosting classifier...")
    le = LabelEncoder()
    y_enc = le.fit_transform(y)
    n_classes = len(le.classes_)
    print(f"   Classes ({n_classes}): {list(le.classes_)}")

    clf = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        min_samples_leaf=3,
        subsample=0.8,
        random_state=42,
    )

    # Cross-validation
    n_splits = min(5, min(Counter(y_enc).values()))
    if n_splits >= 2:
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        scores = cross_val_score(clf, X, y_enc, cv=skf, scoring="f1_macro")
        print(f"   CV macro F1: {scores.mean():.4f} ± {scores.std():.4f}")
        print(f"   Per-fold: {[f'{s:.4f}' for s in scores]}")
    else:
        print("   Too few samples per class for CV, training on all data")

    # Train on full dataset
    clf.fit(X, y_enc)
    train_acc = clf.score(X, y_enc)
    print(f"   Train accuracy: {train_acc:.4f}")

    # Feature importances (top 10)
    importances = clf.feature_importances_
    node_names = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
    feat_names = []
    for n in node_names:
        for f in ["mean_rssi", "std_rssi", "mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]:
            feat_names.append(f"{n}_{f}")

    top_idx = np.argsort(importances)[-10:][::-1]
    print("\n   Top 10 features:")
    for idx in top_idx:
        name = feat_names[idx] if idx < len(feat_names) else f"feat_{idx}"
        print(f"     {name}: {importances[idx]:.4f}")

    # ── 6. Save model ─────────────────────────────────────────────────────
    model_path = OUTPUT_DIR / "v41_position_classifier.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({"model": clf, "label_encoder": le, "feature_names": feat_names}, f)
    print(f"\n6. Model saved: {model_path}")

    meta = {
        "version": "v41_epoch4",
        "format": "text_csi",
        "n_samples": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "n_classes": n_classes,
        "classes": list(le.classes_),
        "window_size": WINDOW_SIZE,
        "node_ips": NODE_IPS,
        "cv_f1_macro": float(scores.mean()) if n_splits >= 2 else None,
        "train_accuracy": float(train_acc),
        "feature_names": feat_names,
        "data_sources": {
            "snapshots": len(snap_files),
            "empty_windows": len(empty_windows),
            "twoperson_windows": len(twop_windows),
        },
        "label_counts": dict(Counter(y)),
    }
    meta_path = OUTPUT_DIR / "v41_position_classifier_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"   Meta saved: {meta_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
