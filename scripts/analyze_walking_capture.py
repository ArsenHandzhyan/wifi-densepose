#!/usr/bin/env python3
"""
Full analysis of walking motion capture vs empty vs static presence.
Produces feature comparison diagrams.
"""

import base64
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

PROJECT = Path("/Users/arsen/Desktop/wifi-densepose")
CAPTURES = PROJECT / "temp" / "captures"
OUTPUT = PROJECT / "output" / "walking_analysis"
OUTPUT.mkdir(parents=True, exist_ok=True)

NODE_IPS = [
    "192.168.0.137", "192.168.0.117", "192.168.0.143", "192.168.0.125",
    "192.168.0.110", "192.168.0.132", "192.168.0.153",
]
NODE_NAMES = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
WINDOW_SIZE = 7
MIN_NODES = 5

# Walking files
WALKING_PREFIX = "walking_v44_20260401_010017_"
WALKING_CHUNKS = sorted(CAPTURES.glob(f"{WALKING_PREFIX}*_chunk*.ndjson.gz"))

# Empty recordings (from V44 training)
EMPTY_PATTERNS = [
    "empty_garage_10min_epoch4_20260331_chunk*.ndjson.gz",
    "empty_garage_30min_test_chunk*.ndjson.gz",
    "empty_garage_v41_5min_clean_chunk*.ndjson.gz",
    "empty_v41_5min_chunk*.ndjson.gz",
    "empty_garage_v41_baseline_chunk*.ndjson.gz",
    "empty_garage_20min_v43_chunk*.ndjson.gz",
    "empty_garage_20min_v43b_chunk*.ndjson.gz",
]

# Static presence (standing still)
STATIC_PATTERNS = [
    "marker1_1min_20260331_chunk*.ndjson.gz",
    "marker2_1min_20260331_chunk*.ndjson.gz",
    "marker3_1min_20260331_chunk*.ndjson.gz",
    "marker4_1min_20260331_chunk*.ndjson.gz",
    "marker5_1min_20260331_chunk*.ndjson.gz",
    "center_1min_20260331_chunk*.ndjson.gz",
    "door_1min_r2_20260331_chunk*.ndjson.gz",
    "door_standing_1min_20260331_chunk*.ndjson.gz",
    "occupied_center_static_1p_epoch4_20260331_chunk*.ndjson.gz",
    "occupied_door_static_1p_epoch4_20260331_chunk*.ndjson.gz",
]

SKIP_CHUNKS = {
    "empty_garage_v41_chunk0001_20260331_215819.ndjson.gz",
    "empty_garage_v41_chunk0001_20260331_220010.ndjson.gz",
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
    node_packets = defaultdict(list)
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


def load_raw_packets(fpath: Path) -> dict:
    """Load per-node raw RSSI and amplitude timeseries."""
    node_packets = defaultdict(lambda: {"rssi": [], "amp_mean": [], "amp_std": [], "amp_max": []})
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
                node_packets[src_ip]["rssi"].append(rssi)
                node_packets[src_ip]["amp_mean"].append(np.mean(amps))
                node_packets[src_ip]["amp_std"].append(np.std(amps))
                node_packets[src_ip]["amp_max"].append(np.max(amps))
    return dict(node_packets)


def collect_files(patterns):
    files = []
    seen = set()
    for pat in patterns:
        for f in sorted(CAPTURES.glob(pat)):
            if f.name not in SKIP_CHUNKS and f.name not in seen:
                seen.add(f.name)
                files.append(f)
    return sorted(files)


def extract_all_features(files, label, stride=1):
    X, y = [], []
    for f in files:
        for w in load_chunk_windows(f, stride=stride):
            feat = extract_features(w["data"])
            if feat is not None:
                X.append(feat)
                y.append(label)
    return X, y


def main():
    print("=" * 60)
    print("WALKING MOTION CAPTURE — FULL ANALYSIS")
    print("=" * 60)

    # 1. Load all data
    print("\n1. Loading data...")

    # Walking
    walk_files = list(WALKING_CHUNKS)
    X_walk, y_walk = extract_all_features(walk_files, "walking", stride=1)
    print(f"   Walking: {len(walk_files)} files → {len(X_walk)} windows")

    # Walking by zone
    walk_zones = {"center": [], "passage": [], "door": [], "transition": []}
    for f in walk_files:
        name = f.name
        if "center" in name:
            zone = "center"
        elif "passage" in name:
            zone = "passage"
        elif "door" in name:
            zone = "door"
        else:
            zone = "transition"
        for w in load_chunk_windows(f, stride=1):
            feat = extract_features(w["data"])
            if feat is not None:
                walk_zones[zone].append(feat)

    for z, feats in walk_zones.items():
        print(f"   Walking-{z}: {len(feats)} windows")

    # Empty
    empty_files = collect_files(EMPTY_PATTERNS)
    X_empty, y_empty = extract_all_features(empty_files, "empty", stride=1)
    print(f"   Empty: {len(empty_files)} files → {len(X_empty)} windows")

    # Static presence
    static_files = collect_files(STATIC_PATTERNS)
    X_static, y_static = extract_all_features(static_files, "static", stride=1)
    print(f"   Static: {len(static_files)} files → {len(X_static)} windows")

    X_all = np.array(X_walk + X_empty + X_static)
    y_all = np.array(y_walk + y_empty + y_static)
    print(f"\n   TOTAL: {len(X_all)} windows, {X_all.shape[1]} features")

    # Feature names
    feat_names = [f"{n}_{f}" for n in NODE_NAMES for f in ["mean_rssi", "std_rssi", "mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]]

    # 2. Feature statistics per class
    print("\n2. Feature statistics...")
    classes = ["empty", "static", "walking"]
    class_data = {c: X_all[y_all == c] for c in classes}
    for c in classes:
        d = class_data[c]
        print(f"   {c}: {len(d)} samples, mean_amp={d[:, 2::8].mean():.2f}, std_amp={d[:, 3::8].mean():.4f}")

    # ============================================================
    # DIAGRAM 1: Feature distributions (boxplot) — 3 classes
    # ============================================================
    print("\n3. Generating diagrams...")

    fig, axes = plt.subplots(2, 4, figsize=(20, 10))
    fig.suptitle("Распределение признаков CSI: Empty vs Static vs Walking", fontsize=16, fontweight="bold")
    feature_types = ["mean_rssi", "std_rssi", "mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]
    colors = {"empty": "#2196F3", "static": "#4CAF50", "walking": "#FF5722"}

    for idx, ft in enumerate(feature_types):
        ax = axes[idx // 4][idx % 4]
        # Average across all nodes for this feature type
        col_indices = [i * 8 + idx for i in range(7)]
        data_by_class = []
        labels = []
        for c in classes:
            vals = class_data[c][:, col_indices].mean(axis=1)
            data_by_class.append(vals)
            labels.append(c)
        bp = ax.boxplot(data_by_class, labels=labels, patch_artist=True, widths=0.6)
        for patch, c in zip(bp["boxes"], classes):
            patch.set_facecolor(colors[c])
            patch.set_alpha(0.7)
        ax.set_title(ft, fontsize=12, fontweight="bold")
        ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    p1 = OUTPUT / "01_feature_distributions_3class.png"
    plt.savefig(p1, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p1}")

    # ============================================================
    # DIAGRAM 2: Per-node amplitude comparison
    # ============================================================
    fig, axes = plt.subplots(1, 7, figsize=(24, 5))
    fig.suptitle("Средняя амплитуда CSI по нодам: Empty vs Static vs Walking", fontsize=16, fontweight="bold")

    for ni, (node_name, ax) in enumerate(zip(NODE_NAMES, axes)):
        mean_amp_idx = ni * 8 + 2  # mean_amp
        std_amp_idx = ni * 8 + 3   # std_amp
        for c in classes:
            vals = class_data[c][:, mean_amp_idx]
            ax.hist(vals, bins=30, alpha=0.5, label=c, color=colors[c], density=True)
        ax.set_title(node_name, fontsize=12, fontweight="bold")
        ax.set_xlabel("mean_amp")
        if ni == 0:
            ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    plt.tight_layout()
    p2 = OUTPUT / "02_per_node_amplitude_histogram.png"
    plt.savefig(p2, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p2}")

    # ============================================================
    # DIAGRAM 3: Walking zones comparison
    # ============================================================
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Ходьба по зонам: центр vs проход vs дверь vs переходы", fontsize=16, fontweight="bold")
    zone_colors = {"center": "#FF5722", "passage": "#9C27B0", "door": "#FF9800", "transition": "#607D8B"}
    zone_names = ["center", "passage", "door", "transition"]

    # mean_amp across all nodes
    ax = axes[0][0]
    for zn in zone_names:
        if walk_zones[zn]:
            vals = np.array(walk_zones[zn])[:, 2::8].mean(axis=1)
            ax.hist(vals, bins=25, alpha=0.5, label=zn, color=zone_colors[zn], density=True)
    ax.set_title("mean_amp (все ноды)", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(alpha=0.3)

    # std_amp
    ax = axes[0][1]
    for zn in zone_names:
        if walk_zones[zn]:
            vals = np.array(walk_zones[zn])[:, 3::8].mean(axis=1)
            ax.hist(vals, bins=25, alpha=0.5, label=zn, color=zone_colors[zn], density=True)
    ax.set_title("std_amp (все ноды)", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(alpha=0.3)

    # max_amp
    ax = axes[1][0]
    for zn in zone_names:
        if walk_zones[zn]:
            vals = np.array(walk_zones[zn])[:, 4::8].mean(axis=1)
            ax.hist(vals, bins=25, alpha=0.5, label=zn, color=zone_colors[zn], density=True)
    ax.set_title("max_amp (все ноды)", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(alpha=0.3)

    # mean_rssi
    ax = axes[1][1]
    for zn in zone_names:
        if walk_zones[zn]:
            vals = np.array(walk_zones[zn])[:, 0::8].mean(axis=1)
            ax.hist(vals, bins=25, alpha=0.5, label=zn, color=zone_colors[zn], density=True)
    ax.set_title("mean_rssi (все ноды)", fontsize=12, fontweight="bold")
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    p3 = OUTPUT / "03_walking_zones_comparison.png"
    plt.savefig(p3, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p3}")

    # ============================================================
    # DIAGRAM 4: Temporal signal — one walking clip raw timeseries
    # ============================================================
    sample_walk = walk_files[0]  # center_slow_1
    raw = load_raw_packets(sample_walk)
    fig, axes = plt.subplots(3, 1, figsize=(18, 12), sharex=True)
    fig.suptitle(f"Временной ряд CSI при ходьбе: {sample_walk.name}", fontsize=14, fontweight="bold")

    node_colors = plt.cm.tab10(np.linspace(0, 1, 7))
    for ni, ip in enumerate(NODE_IPS):
        if ip in raw:
            axes[0].plot(raw[ip]["rssi"], label=NODE_NAMES[ni], color=node_colors[ni], alpha=0.7, linewidth=0.8)
            axes[1].plot(raw[ip]["amp_mean"], label=NODE_NAMES[ni], color=node_colors[ni], alpha=0.7, linewidth=0.8)
            axes[2].plot(raw[ip]["amp_std"], label=NODE_NAMES[ni], color=node_colors[ni], alpha=0.7, linewidth=0.8)
    axes[0].set_ylabel("RSSI (dBm)")
    axes[0].set_title("RSSI по нодам")
    axes[0].legend(ncol=7, fontsize=8)
    axes[0].grid(alpha=0.3)
    axes[1].set_ylabel("Mean Amplitude")
    axes[1].set_title("Средняя амплитуда поднесущих")
    axes[1].grid(alpha=0.3)
    axes[2].set_ylabel("Std Amplitude")
    axes[2].set_title("Вариабельность амплитуды (std)")
    axes[2].set_xlabel("Packet #")
    axes[2].grid(alpha=0.3)
    plt.tight_layout()
    p4 = OUTPUT / "04_temporal_walking_signal.png"
    plt.savefig(p4, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p4}")

    # Same for empty
    empty_sample = empty_files[0]
    raw_empty = load_raw_packets(empty_sample)
    fig, axes = plt.subplots(3, 1, figsize=(18, 12), sharex=True)
    fig.suptitle(f"Временной ряд CSI ПУСТОЙ гараж: {empty_sample.name}", fontsize=14, fontweight="bold")
    for ni, ip in enumerate(NODE_IPS):
        if ip in raw_empty:
            axes[0].plot(raw_empty[ip]["rssi"], label=NODE_NAMES[ni], color=node_colors[ni], alpha=0.7, linewidth=0.8)
            axes[1].plot(raw_empty[ip]["amp_mean"], label=NODE_NAMES[ni], color=node_colors[ni], alpha=0.7, linewidth=0.8)
            axes[2].plot(raw_empty[ip]["amp_std"], label=NODE_NAMES[ni], color=node_colors[ni], alpha=0.7, linewidth=0.8)
    axes[0].set_ylabel("RSSI (dBm)")
    axes[0].set_title("RSSI по нодам")
    axes[0].legend(ncol=7, fontsize=8)
    axes[0].grid(alpha=0.3)
    axes[1].set_ylabel("Mean Amplitude")
    axes[1].set_title("Средняя амплитуда поднесущих")
    axes[1].grid(alpha=0.3)
    axes[2].set_ylabel("Std Amplitude")
    axes[2].set_title("Вариабельность амплитуды (std)")
    axes[2].set_xlabel("Packet #")
    axes[2].grid(alpha=0.3)
    plt.tight_layout()
    p5 = OUTPUT / "05_temporal_empty_signal.png"
    plt.savefig(p5, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p5}")

    # ============================================================
    # DIAGRAM 5: Feature importance heatmap (per-node, per-feature)
    # ============================================================
    fig, axes = plt.subplots(1, 3, figsize=(20, 6))
    fig.suptitle("Средние значения признаков по нодам (тепловая карта)", fontsize=16, fontweight="bold")

    for ci, c in enumerate(classes):
        d = class_data[c]
        mat = np.zeros((7, 8))
        for ni in range(7):
            for fi in range(8):
                mat[ni, fi] = d[:, ni * 8 + fi].mean()
        im = axes[ci].imshow(mat, aspect="auto", cmap="YlOrRd")
        axes[ci].set_title(c.upper(), fontsize=14, fontweight="bold")
        axes[ci].set_yticks(range(7))
        axes[ci].set_yticklabels(NODE_NAMES)
        axes[ci].set_xticks(range(8))
        axes[ci].set_xticklabels(["μRSSI", "σRSSI", "μAmp", "σAmp", "maxA", "lowA", "midA", "hiA"], rotation=45, fontsize=9)
        plt.colorbar(im, ax=axes[ci], fraction=0.046, pad=0.04)
    plt.tight_layout()
    p6 = OUTPUT / "06_feature_heatmap_by_class.png"
    plt.savefig(p6, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p6}")

    # ============================================================
    # DIAGRAM 6: Separation power — key discriminative features
    # ============================================================
    fig = plt.figure(figsize=(16, 12))
    gs = GridSpec(2, 2, figure=fig)
    fig.suptitle("Разделяющая способность признаков: Empty vs Static vs Walking", fontsize=16, fontweight="bold")

    # Scatter: mean_amp_all vs std_amp_all
    ax = fig.add_subplot(gs[0, 0])
    for c in classes:
        d = class_data[c]
        x = d[:, 2::8].mean(axis=1)  # mean_amp avg
        y = d[:, 3::8].mean(axis=1)  # std_amp avg
        ax.scatter(x, y, alpha=0.3, s=15, c=colors[c], label=c)
    ax.set_xlabel("mean_amp (avg all nodes)")
    ax.set_ylabel("std_amp (avg all nodes)")
    ax.set_title("mean_amp vs std_amp")
    ax.legend()
    ax.grid(alpha=0.3)

    # Scatter: max_amp vs std_rssi
    ax = fig.add_subplot(gs[0, 1])
    for c in classes:
        d = class_data[c]
        x = d[:, 4::8].mean(axis=1)  # max_amp avg
        y = d[:, 1::8].mean(axis=1)  # std_rssi avg
        ax.scatter(x, y, alpha=0.3, s=15, c=colors[c], label=c)
    ax.set_xlabel("max_amp (avg all nodes)")
    ax.set_ylabel("std_rssi (avg all nodes)")
    ax.set_title("max_amp vs std_rssi")
    ax.legend()
    ax.grid(alpha=0.3)

    # Bar: mean feature values per class
    ax = fig.add_subplot(gs[1, :])
    key_features = [2, 3, 4, 5, 6, 7]  # amp features for node 0
    key_names = ["mean_amp", "std_amp", "max_amp", "low_amp", "mid_amp", "high_amp"]
    x = np.arange(len(key_names))
    width = 0.25
    for ci, c in enumerate(classes):
        # Average across all nodes
        means = []
        for fi in key_features:
            col_indices = [i * 8 + fi for i in range(7)]
            means.append(class_data[c][:, col_indices].mean())
        ax.bar(x + ci * width, means, width, label=c, color=colors[c], alpha=0.8)
    ax.set_xticks(x + width)
    ax.set_xticklabels(key_names)
    ax.set_title("Средние значения амплитудных признаков по классам (all nodes avg)")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    p7 = OUTPUT / "07_separation_power.png"
    plt.savefig(p7, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p7}")

    # ============================================================
    # DIAGRAM 7: Walking vs Static — key difference
    # ============================================================
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle("Ключевое различие: Static (стоит) vs Walking (ходит)", fontsize=16, fontweight="bold")

    # std_amp — should be higher for walking
    ax = axes[0]
    for c, label in [("static", "Static"), ("walking", "Walking")]:
        vals = class_data[c][:, 3::8].mean(axis=1)
        ax.hist(vals, bins=30, alpha=0.6, label=label, color=colors[c], density=True)
    ax.set_title("std_amp — вариабельность амплитуды")
    ax.set_xlabel("std_amp (avg all nodes)")
    ax.legend()
    ax.grid(alpha=0.3)

    # std_rssi — should differ for walking
    ax = axes[1]
    for c, label in [("static", "Static"), ("walking", "Walking")]:
        vals = class_data[c][:, 1::8].mean(axis=1)
        ax.hist(vals, bins=30, alpha=0.6, label=label, color=colors[c], density=True)
    ax.set_title("std_rssi — вариабельность RSSI")
    ax.set_xlabel("std_rssi (avg all nodes)")
    ax.legend()
    ax.grid(alpha=0.3)

    # max_amp
    ax = axes[2]
    for c, label in [("static", "Static"), ("walking", "Walking")]:
        vals = class_data[c][:, 4::8].mean(axis=1)
        ax.hist(vals, bins=30, alpha=0.6, label=label, color=colors[c], density=True)
    ax.set_title("max_amp — максимальная амплитуда")
    ax.set_xlabel("max_amp (avg all nodes)")
    ax.legend()
    ax.grid(alpha=0.3)

    plt.tight_layout()
    p8 = OUTPUT / "08_static_vs_walking.png"
    plt.savefig(p8, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"   Saved: {p8}")

    # ============================================================
    # Print numeric summary
    # ============================================================
    print("\n" + "=" * 60)
    print("NUMERIC SUMMARY")
    print("=" * 60)
    for c in classes:
        d = class_data[c]
        print(f"\n  {c.upper()} ({len(d)} windows):")
        print(f"    mean_rssi:  {d[:, 0::8].mean():.2f} ± {d[:, 0::8].std():.2f}")
        print(f"    std_rssi:   {d[:, 1::8].mean():.4f} ± {d[:, 1::8].std():.4f}")
        print(f"    mean_amp:   {d[:, 2::8].mean():.2f} ± {d[:, 2::8].std():.2f}")
        print(f"    std_amp:    {d[:, 3::8].mean():.2f} ± {d[:, 3::8].std():.2f}")
        print(f"    max_amp:    {d[:, 4::8].mean():.2f} ± {d[:, 4::8].std():.2f}")

    # Walking zones
    print(f"\n  WALKING ZONES:")
    for zn in zone_names:
        if walk_zones[zn]:
            d = np.array(walk_zones[zn])
            print(f"    {zn} ({len(d)}): mean_amp={d[:, 2::8].mean():.2f}, std_amp={d[:, 3::8].mean():.2f}, max_amp={d[:, 4::8].mean():.2f}")

    print(f"\nAll diagrams saved to: {OUTPUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
