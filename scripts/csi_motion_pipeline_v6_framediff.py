#!/usr/bin/env python3
"""
CSI Motion Pipeline V6 - Video Frame Differencing Ground Truth
================================================================
Breaks the circular labeling problem of V1-V5 by deriving ground truth
labels directly from VIDEO frame differencing, not from CSI features
or filename heuristics.

Ground truth derivation:
  1. Extract frames at 1fps from each .teacher.mp4 video
  2. Compute inter-frame pixel difference (grayscale, downsampled)
  3. Auto-calibrate thresholds from clips with "empty" in the name
  4. Classify each second as: EMPTY / STATIC / MOTION
     - EMPTY:  frame diff ~ empty baseline noise, no localized change
     - MOTION: frame diff >> empty baseline (walking, gesturing, etc.)
     - STATIC: intermediate (person present but minimal movement)

CSI features (~45 per 1-second window):
  - Per-node (4 nodes x 9 feat = 36): amp_mean, amp_std, bmi,
    motion_energy, motion_energy_std, tv_mean, tv_max, tv_frac_3x,
    doppler_proxy
  - Cross-node (4): corr_mean, corr_min, corr_max, corr_std
  - Aggregate (5): agg_mean/max_motion_energy, agg_mean/max_tv,
    n_nodes_active

Model: HistGradientBoostingClassifier with StratifiedGroupKFold
  (groups = clip_id, so no data leakage between clips)

Usage:
  /Users/arsen/Desktop/wifi-densepose/venv/bin/python3 \\
      scripts/csi_motion_pipeline_v6_framediff.py
"""

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"

import sys
import gc
import json
import gzip
import time
import base64
import pickle
import warnings
from pathlib import Path
from collections import defaultdict
from datetime import datetime

import numpy as np

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python (cv2) required. pip install opencv-python")
    sys.exit(1)

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedGroupKFold, GroupKFold
from sklearn.metrics import (
    classification_report, confusion_matrix, balanced_accuracy_score,
)

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURES_DIR = BASE_DIR / "temp" / "captures"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_PATH = OUTPUT_DIR / "v6_framediff_results.json"
MODEL_PATH = OUTPUT_DIR / "v6_framediff_model.pkl"

# CSI constants
CSI_HEADER_BYTES = 20
CSI_IQ_PAIRS = 128
CSI_PAYLOAD_BYTES = CSI_HEADER_BYTES + CSI_IQ_PAIRS * 2  # 276

ACTIVE_SC = np.array(list(range(6, 59)) + list(range(70, 123)), dtype=np.int32)
N_ACTIVE = len(ACTIVE_SC)  # 106

SOURCE_ORDER = ["n01", "n02", "n03", "n04"]
IP_TO_NODE = {
    "192.168.1.101": "n01",
    "192.168.1.117": "n02",
    "192.168.1.125": "n03",
    "192.168.1.137": "n04",
}
CSI_RATE = 30.0

WINDOW_SEC = 1.0
STEP_SEC = 1.0

# Frame resolution for processing (downsampled for speed)
FRAME_W, FRAME_H = 160, 120

# Global empty-room reference frame (computed from "empty" clips)
_empty_ref_frame = None  # np.array (FRAME_H, FRAME_W) float32


# ===================================================================
# Step 1: Discover paired captures (both .ndjson.gz AND .teacher.mp4)
# ===================================================================
def discover_paired_captures():
    """Match .teacher.mp4 videos to .ndjson.gz CSI captures.

    Naming conventions:
      mp4:    <label>.teacher.mp4
      ndjson: <timestamp>_<label>.ndjson.gz   OR   <label>.ndjson.gz
    """
    mp4_files = sorted(CAPTURES_DIR.glob("*.teacher.mp4"))
    ndjson_files = sorted(CAPTURES_DIR.glob("*.ndjson.gz"))

    # Build label -> ndjson path index
    ndjson_by_label = {}
    for nf in ndjson_files:
        # stem of foo.ndjson.gz is "foo.ndjson"
        stem = nf.name
        if stem.endswith(".ndjson.gz"):
            stem = stem[:-len(".ndjson.gz")]

        # Extract label after optional timestamp prefix "YYYYMMDD-HHMMSS_"
        parts = stem.split("_", 1)
        if (len(parts) >= 2
                and len(parts[0]) >= 8
                and "-" in parts[0]
                and parts[0].replace("-", "").isdigit()):
            label = parts[1]
        else:
            label = stem
        ndjson_by_label[label] = nf

    pairs = []
    seen_ndjson = set()

    for mp4 in mp4_files:
        mp4_label = mp4.name.replace(".teacher.mp4", "")
        ndjson = ndjson_by_label.get(mp4_label)
        if ndjson and str(ndjson) not in seen_ndjson:
            pairs.append({
                "clip_id": mp4_label,
                "mp4_path": str(mp4),
                "ndjson_path": str(ndjson),
            })
            seen_ndjson.add(str(ndjson))

    return pairs


# ===================================================================
# Step 2: Video frame differencing -> per-second labels
# ===================================================================
def _read_video_frames(mp4_path):
    """Read one grayscale frame per second, downsampled to FRAME_W x FRAME_H.

    Returns list of float32 frames, or empty list on failure.
    """
    cap = cv2.VideoCapture(mp4_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or n_frames <= 0:
        cap.release()
        return []

    n_sec = int(n_frames / fps)
    frames = []
    for s in range(n_sec + 1):
        fidx = min(int(s * fps), n_frames - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (FRAME_W, FRAME_H),
                           interpolation=cv2.INTER_AREA)
        frames.append(small.astype(np.float32))
    cap.release()
    return frames


def extract_frame_metrics(mp4_path):
    """Extract per-second frame-diff metrics from video.

    Uses two complementary signals:
      1. Frame-to-frame differencing (motion detection)
      2. Frame-to-empty-reference differencing (presence detection)

    The empty reference is a global mean frame from "empty" clips;
    if not available, presence features are set to 0.
    """
    global _empty_ref_frame

    frames = _read_video_frames(mp4_path)
    if len(frames) < 2:
        return []

    metrics = []
    for i in range(1, len(frames)):
        # --- Motion signal: consecutive frame difference ---
        diff = np.abs(frames[i] - frames[i - 1])

        # Block-based analysis (4x4 grid)
        bh, bw = FRAME_H // 4, FRAME_W // 4
        block_means = []
        for bi in range(4):
            for bj in range(4):
                block = diff[bi * bh:(bi + 1) * bh, bj * bw:(bj + 1) * bw]
                block_means.append(float(block.mean()))

        # --- Presence signal: deviation from empty-room reference ---
        bg_dev_mean = 0.0
        bg_dev_max_block = 0.0
        bg_change_frac = 0.0
        if _empty_ref_frame is not None:
            bg_diff = np.abs(frames[i] - _empty_ref_frame)
            bg_dev_mean = float(bg_diff.mean())
            # Block-based background deviation
            bg_blocks = []
            for bi in range(4):
                for bj in range(4):
                    blk = bg_diff[bi * bh:(bi + 1) * bh, bj * bw:(bj + 1) * bw]
                    bg_blocks.append(float(blk.mean()))
            bg_dev_max_block = max(bg_blocks)
            bg_change_frac = float((bg_diff > 20.0).mean())

        metrics.append({
            "second": i - 1,
            "diff_mean": float(diff.mean()),
            "diff_std": float(diff.std()),
            "block_max": max(block_means),
            "block_p75": float(np.percentile(block_means, 75)),
            "change_frac": float((diff > 15.0).mean()),
            "frame_mean": float(frames[i].mean()),
            "frame_std": float(frames[i].std()),
            # Presence features (background subtraction)
            "bg_dev_mean": bg_dev_mean,
            "bg_dev_max_block": bg_dev_max_block,
            "bg_change_frac": bg_change_frac,
        })

    return metrics


def compute_empty_baseline(pairs):
    """Compute video frame-diff statistics from clips with 'empty' in name.

    Also builds a global empty-room reference frame (mean of all empty
    clip frames) for background subtraction based presence detection.
    """
    global _empty_ref_frame

    diffs = []
    all_empty_frames = []

    for pair in pairs:
        cid = pair["clip_id"].lower()
        if "empty" not in cid:
            continue
        frames = _read_video_frames(pair["mp4_path"])
        if not frames:
            continue
        # Collect frame diffs
        for i in range(1, len(frames)):
            d = float(np.abs(frames[i] - frames[i - 1]).mean())
            diffs.append(d)
        # Collect frames for reference
        all_empty_frames.extend(frames)

    # Build empty reference frame
    if all_empty_frames:
        _empty_ref_frame = np.mean(all_empty_frames, axis=0).astype(np.float32)
        print(f"  Built empty reference frame from {len(all_empty_frames)} frames")
    else:
        _empty_ref_frame = None
        print("  [WARN] No empty frames found for reference frame")

    if len(diffs) < 3:
        print("  [WARN] <3 empty video seconds found, using hardcoded defaults")
        return {"mean": 1.5, "std": 1.0, "p95": 3.0, "p99": 5.0}

    # Also compute background deviation stats for empty frames
    bg_devs = []
    if _empty_ref_frame is not None:
        for f in all_empty_frames:
            bg_devs.append(float(np.abs(f - _empty_ref_frame).mean()))

    result = {
        "mean": float(np.mean(diffs)),
        "std": float(np.std(diffs)),
        "p95": float(np.percentile(diffs, 95)),
        "p99": float(np.percentile(diffs, 99)),
        "n_samples": len(diffs),
    }
    if bg_devs:
        result["bg_dev_mean"] = float(np.mean(bg_devs))
        result["bg_dev_std"] = float(np.std(bg_devs))
        result["bg_dev_p95"] = float(np.percentile(bg_devs, 95))
        result["bg_dev_p99"] = float(np.percentile(bg_devs, 99))
        print(f"  BG deviation: mean={result['bg_dev_mean']:.2f}, "
              f"p95={result['bg_dev_p95']:.2f}")

    return result


def classify_second(m, ebl):
    """Classify one video second as EMPTY / STATIC / MOTION.

    Uses two orthogonal signals:
      1. Frame-to-frame diff -> motion detection (walking, gesturing)
      2. Frame-to-empty-reference diff -> presence detection (person standing still)

    Decision tree:
      - If high frame diff -> MOTION
      - Else if frame appearance deviates from empty reference -> STATIC
      - Else -> EMPTY
    """
    d = m["diff_mean"]
    cf = m["change_frac"]
    bmax = m["block_max"]
    bg_dev = m.get("bg_dev_mean", 0.0)
    bg_dev_block = m.get("bg_dev_max_block", 0.0)
    bg_cf = m.get("bg_change_frac", 0.0)

    empty_p95 = ebl["p95"]
    empty_p99 = ebl.get("p99", empty_p95 * 1.5)
    empty_std = ebl["std"]
    empty_mean = ebl["mean"]

    # Background deviation thresholds (empty room appearance)
    bg_empty_p95 = ebl.get("bg_dev_p95", 5.0)
    bg_empty_p99 = ebl.get("bg_dev_p99", 8.0)

    # --- Motion detection (frame-to-frame diff) ---
    motion_thr = max(empty_p99 * 2.0, empty_mean + 5 * empty_std, 5.0)

    if d > motion_thr or cf > 0.06:
        return "MOTION"
    if bmax > motion_thr * 1.5 and cf > 0.025:
        return "MOTION"

    # --- Presence detection (background subtraction) ---
    presence_thr = max(bg_empty_p99 * 1.5, bg_empty_p95 + 3.0)

    if bg_dev > presence_thr or bg_dev_block > presence_thr * 1.5:
        mild_motion_thr = max(empty_p95 * 1.5, empty_mean + 3 * empty_std)
        if d > mild_motion_thr:
            return "MOTION"
        return "STATIC"

    if bg_cf > 0.05:
        return "STATIC"

    return "EMPTY"


def classify_motion_binary(m, ebl):
    """Binary motion classification: STILL vs MOVING.

    Pure frame-differencing based -- no presence detection needed.
    STILL = low frame diff (empty or person standing still)
    MOVING = high frame diff (person walking, gesturing, etc.)
    """
    d = m["diff_mean"]
    cf = m["change_frac"]
    bmax = m["block_max"]

    empty_p95 = ebl["p95"]
    empty_p99 = ebl.get("p99", empty_p95 * 1.5)
    empty_std = ebl["std"]
    empty_mean = ebl["mean"]

    motion_thr = max(empty_p99 * 2.0, empty_mean + 5 * empty_std, 5.0)

    if d > motion_thr or cf > 0.06:
        return "MOVING"
    if bmax > motion_thr * 1.5 and cf > 0.025:
        return "MOVING"

    return "STILL"


# ===================================================================
# Step 3: CSI parsing
# ===================================================================
def parse_csi_amp(payload_b64):
    """Decode base64 CSI payload -> amplitude array (128,) float32, or None."""
    try:
        raw = base64.b64decode(payload_b64)
    except Exception:
        return None
    if len(raw) != CSI_PAYLOAD_BYTES:
        return None
    iq = np.frombuffer(raw[CSI_HEADER_BYTES:], dtype=np.int8).reshape(
        CSI_IQ_PAIRS, 2
    )
    i_v = iq[:, 0].astype(np.float32)
    q_v = iq[:, 1].astype(np.float32)
    return np.sqrt(i_v ** 2 + q_v ** 2)


def load_clip_csi(ndjson_path):
    """Load CSI from .ndjson.gz -> {node: [(ts_sec, amp128), ...]}."""
    data = defaultdict(list)
    try:
        with gzip.open(ndjson_path, "rt") as fh:
            for line in fh:
                try:
                    pkt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_ns = pkt.get("ts_ns")
                src = pkt.get("src_ip")
                p64 = pkt.get("payload_b64")
                if not (ts_ns and src and p64):
                    continue
                amp = parse_csi_amp(p64)
                if amp is not None:
                    node = IP_TO_NODE.get(src, src)
                    if node in SOURCE_ORDER:
                        data[node].append((ts_ns / 1e9, amp))
    except Exception as e:
        print(f"    [WARN] CSI load error: {e}")
    return data


# ===================================================================
# Step 4: CSI feature extraction
# ===================================================================
def node_features(amps, node):
    """9 features from one node's 1-sec window. amps: (N, 128) float32."""
    n = amps.shape[0]
    if n < 3:
        return None

    p = f"n_{node}_"
    aa = amps[:, ACTIVE_SC]  # (n, 106)
    f = {}

    # Amplitude level
    f[f"{p}amp_mean"] = np.float32(aa.mean())
    f[f"{p}amp_std"] = np.float32(aa.std())

    # Body motion index
    d1 = np.diff(aa, axis=0)
    vd = np.mean(np.var(d1, axis=0))
    vs = np.mean(np.var(aa, axis=0)) + 1e-10
    f[f"{p}bmi"] = np.float32(vd / vs)

    # Motion energy
    f[f"{p}motion_energy"] = np.float32(np.mean(np.abs(d1)))
    me_ps = np.mean(np.abs(d1), axis=1)
    f[f"{p}motion_energy_std"] = np.float32(np.std(me_ps))

    # Temporal variance
    tv = aa.var(axis=0)
    f[f"{p}tv_mean"] = np.float32(tv.mean())
    f[f"{p}tv_max"] = np.float32(tv.max())
    median_tv = np.median(tv) + 1e-10
    f[f"{p}tv_frac_3x"] = np.float32((tv > 3 * median_tv).mean())

    # Doppler proxy (1 - lag-1 autocorrelation of mean amplitude)
    if n >= 6:
        ts_mean = aa.mean(axis=1)
        ac = np.corrcoef(ts_mean[:-1], ts_mean[1:])[0, 1]
        f[f"{p}doppler_proxy"] = np.float32(1.0 - max(float(ac), 0.0)
                                            if np.isfinite(ac) else 0.5)
    else:
        f[f"{p}doppler_proxy"] = np.float32(0.0)

    return f


_ZERO_NODE_SUFFIXES = [
    "amp_mean", "amp_std", "bmi", "motion_energy", "motion_energy_std",
    "tv_mean", "tv_max", "tv_frac_3x", "doppler_proxy",
]


def window_features(csi_data, t0, t1):
    """Extract features for one 1-second window [t0, t1) in seconds.
    Returns dict or None.
    """
    per_node = {}
    node_ts = {}

    for node in SOURCE_ORDER:
        pkts = csi_data.get(node, [])
        amps = [a for ts, a in pkts if t0 <= ts < t1]
        if len(amps) < 3:
            continue
        mat = np.array(amps, dtype=np.float32)
        nf = node_features(mat, node)
        if nf:
            per_node[node] = nf
            node_ts[node] = mat[:, ACTIVE_SC].mean(axis=1)

    if not per_node:
        return None

    feat = {}

    # Per-node features (pad missing nodes with 0)
    for node in SOURCE_ORDER:
        if node in per_node:
            feat.update(per_node[node])
        else:
            p = f"n_{node}_"
            for s in _ZERO_NODE_SUFFIXES:
                feat[f"{p}{s}"] = np.float32(0.0)

    # Cross-node correlation
    if len(node_ts) >= 2:
        nlist = sorted(node_ts.keys())
        corrs = []
        for i in range(len(nlist)):
            for j in range(i + 1, len(nlist)):
                a, b = node_ts[nlist[i]], node_ts[nlist[j]]
                mn = min(len(a), len(b))
                if mn < 3:
                    continue
                c = np.corrcoef(a[:mn], b[:mn])[0, 1]
                if np.isfinite(c):
                    corrs.append(float(c))
        if corrs:
            feat["cross_corr_mean"] = np.float32(np.mean(corrs))
            feat["cross_corr_min"] = np.float32(np.min(corrs))
            feat["cross_corr_max"] = np.float32(np.max(corrs))
            feat["cross_corr_std"] = np.float32(np.std(corrs))
        else:
            for k in ("cross_corr_mean", "cross_corr_min",
                       "cross_corr_max", "cross_corr_std"):
                feat[k] = np.float32(0.0)
    else:
        for k in ("cross_corr_mean", "cross_corr_min",
                   "cross_corr_max", "cross_corr_std"):
            feat[k] = np.float32(0.0)

    # Aggregates across active nodes
    me = [per_node[n][f"n_{n}_motion_energy"] for n in per_node]
    tv = [per_node[n][f"n_{n}_tv_mean"] for n in per_node]
    feat["agg_mean_motion_energy"] = np.float32(np.mean(me))
    feat["agg_max_motion_energy"] = np.float32(np.max(me))
    feat["agg_mean_tv"] = np.float32(np.mean(tv))
    feat["agg_max_tv"] = np.float32(np.max(tv))
    feat["n_nodes_active"] = np.float32(len(per_node))

    return feat


# ===================================================================
# Step 5: Build aligned dataset
# ===================================================================
def build_dataset(pairs, empty_baseline):
    """Process all paired captures: align video labels with CSI features.

    Returns (X, y_3class, y_binary, groups, feature_names, clip_stats).
    y_3class: EMPTY/STATIC/MOTION
    y_binary: STILL/MOVING (pure frame-diff, no presence needed)
    """
    rows = []  # (feat_dict, label_3c, label_bin, clip_id)
    clip_stats = {}

    for idx, pair in enumerate(pairs):
        cid = pair["clip_id"]
        print(f"\n  [{idx + 1}/{len(pairs)}] {cid[:60]}")

        # Video labels
        mets = extract_frame_metrics(pair["mp4_path"])
        if not mets:
            print(f"    SKIP: no video frames extracted")
            continue

        for m in mets:
            m["label_3c"] = classify_second(m, empty_baseline)
            m["label_bin"] = classify_motion_binary(m, empty_baseline)

        lc3 = defaultdict(int)
        lcb = defaultdict(int)
        for m in mets:
            lc3[m["label_3c"]] += 1
            lcb[m["label_bin"]] += 1
        print(f"    Video: {len(mets)}s -> 3c:{dict(lc3)}  bin:{dict(lcb)}")

        # CSI data
        csi = load_clip_csi(pair["ndjson_path"])
        if not csi:
            print(f"    SKIP: no CSI data")
            continue

        npkts = sum(len(v) for v in csi.values())
        nodes = sorted(csi.keys())
        print(f"    CSI: {npkts} pkts, nodes={nodes}")

        all_ts = [ts for node_pkts in csi.values() for ts, _ in node_pkts]
        if not all_ts:
            continue
        csi_t0 = min(all_ts)
        csi_t1 = max(all_ts)
        csi_dur = csi_t1 - csi_t0
        print(f"    CSI span: {csi_dur:.1f}s")

        # Align: video second i -> CSI window [csi_t0 + i, csi_t0 + i + 1)
        n_aligned = 0
        for m in mets:
            sec = m["second"]
            ws = csi_t0 + sec
            we = ws + WINDOW_SEC
            if we > csi_t1 + 0.5:
                continue
            feat = window_features(csi, ws, we)
            if feat is not None:
                rows.append((feat, m["label_3c"], m["label_bin"], cid))
                n_aligned += 1

        print(f"    Aligned: {n_aligned} windows")
        clip_stats[cid] = {
            "video_seconds": len(mets),
            "aligned": n_aligned,
            "labels_3c": dict(lc3),
            "labels_bin": dict(lcb),
        }

        del csi
        gc.collect()

    if not rows:
        return None, None, None, None, None, {}

    # Assemble matrix
    fnames = sorted(rows[0][0].keys())
    X = np.zeros((len(rows), len(fnames)), dtype=np.float32)
    y3_list, yb_list, g_list = [], [], []
    for i, (fd, l3, lb, gid) in enumerate(rows):
        for j, fn in enumerate(fnames):
            X[i, j] = fd.get(fn, 0.0)
        y3_list.append(l3)
        yb_list.append(lb)
        g_list.append(gid)

    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    return (X, np.array(y3_list), np.array(yb_list),
            np.array(g_list), fnames, clip_stats)


# ===================================================================
# Step 6: Train & evaluate
# ===================================================================
def train_evaluate(X, y, groups, fnames):
    """HistGradientBoosting with StratifiedGroupKFold.

    Returns results dict + final trained model.
    """
    unique_clips = sorted(set(groups))
    n_splits = min(5, len(unique_clips))
    if n_splits < 2:
        n_splits = 2

    # Encode groups as ints
    g_map = {c: i for i, c in enumerate(unique_clips)}
    g_int = np.array([g_map[c] for c in groups])

    try:
        splitter = StratifiedGroupKFold(
            n_splits=n_splits, shuffle=True, random_state=42
        )
        splits = list(splitter.split(X, y, g_int))
    except ValueError:
        splitter = GroupKFold(n_splits=min(n_splits, len(unique_clips)))
        splits = list(splitter.split(X, y, g_int))

    all_preds = np.empty(len(y), dtype=object)
    all_preds[:] = ""
    fold_results = []

    for fi, (tri, tei) in enumerate(splits):
        Xtr, Xte = X[tri], X[tei]
        ytr, yte = y[tri], y[tei]

        # Class-balance via sample weights
        cc = {lbl: int((ytr == lbl).sum()) for lbl in np.unique(ytr)}
        mx = max(cc.values())
        sw = np.array([mx / cc[l] for l in ytr], dtype=np.float32)

        clf = HistGradientBoostingClassifier(
            max_iter=300, max_depth=5, learning_rate=0.05,
            min_samples_leaf=5, l2_regularization=1.0,
            max_bins=128, random_state=42,
        )
        clf.fit(Xtr, ytr, sample_weight=sw)
        preds = clf.predict(Xte)
        all_preds[tei] = preds

        ba = balanced_accuracy_score(yte, preds)
        test_clips = sorted(set(groups[tei]))
        tr_dist = {l: int((ytr == l).sum()) for l in np.unique(ytr)}
        te_dist = {l: int((yte == l).sum()) for l in np.unique(yte)}

        print(f"\n  Fold {fi + 1}/{len(splits)}: BalAcc={ba:.4f}")
        print(f"    Train: {len(tri)} {tr_dist}")
        print(f"    Test:  {len(tei)} {te_dist}")
        print(f"    Test clips: {test_clips[:3]}{'...' if len(test_clips) > 3 else ''}")

        fold_results.append({
            "fold": fi + 1,
            "train_n": len(tri),
            "test_n": len(tei),
            "balanced_accuracy": float(ba),
            "train_dist": tr_dist,
            "test_dist": te_dist,
        })

    valid = all_preds != ""
    overall_ba = balanced_accuracy_score(y[valid], all_preds[valid])
    present_labels = sorted(np.unique(y))

    print(f"\n  CV Balanced Accuracy: {overall_ba:.4f}")
    print("\n  Classification Report:")
    rpt_str = classification_report(
        y[valid], all_preds[valid], labels=present_labels, zero_division=0
    )
    print(rpt_str)
    rpt_dict = classification_report(
        y[valid], all_preds[valid], labels=present_labels,
        output_dict=True, zero_division=0
    )

    cm = confusion_matrix(y[valid], all_preds[valid], labels=present_labels)
    print("  Confusion Matrix (rows=true, cols=pred):")
    hdr = "".join(f"{l:>9}" for l in present_labels)
    print(f"    {'':>10}{hdr}")
    for i, lbl in enumerate(present_labels):
        vals = "".join(f"{cm[i, j]:>9}" for j in range(len(present_labels)))
        print(f"    {lbl:>10}{vals}")

    # Per-clip accuracy
    print("\n  Per-clip accuracy:")
    clip_accs = {}
    for cid in sorted(set(groups)):
        mask = (groups == cid) & valid
        if mask.sum() > 0:
            ca = balanced_accuracy_score(y[mask], all_preds[mask])
            clip_accs[cid] = round(float(ca), 4)
            short = cid[:55]
            print(f"    {short:55s} {ca:.3f} ({mask.sum()} win)")

    # Train final model on all data
    print("\n  Training final model on all data...")
    cc_all = {l: int((y == l).sum()) for l in np.unique(y)}
    mx_all = max(cc_all.values())
    sw_all = np.array([mx_all / cc_all[l] for l in y], dtype=np.float32)

    final_clf = HistGradientBoostingClassifier(
        max_iter=400, max_depth=5, learning_rate=0.05,
        min_samples_leaf=5, l2_regularization=1.0,
        max_bins=128, random_state=42,
    )
    final_clf.fit(X, y, sample_weight=sw_all)
    train_ba = balanced_accuracy_score(y, final_clf.predict(X))
    print(f"  Final model train BalAcc: {train_ba:.4f}")

    return {
        "cv_balanced_accuracy": round(float(overall_ba), 4),
        "train_balanced_accuracy": round(float(train_ba), 4),
        "cv_folds": fold_results,
        "classification_report": rpt_dict,
        "confusion_matrix": cm.tolist(),
        "per_clip_accuracy": clip_accs,
    }, final_clf


# ===================================================================
# Main
# ===================================================================
def main():
    t0 = time.time()
    print("=" * 72)
    print("CSI Motion Pipeline V6 - Video Frame Differencing Ground Truth")
    print("=" * 72)

    # 1. Discover paired captures
    print("\n--- Discovering paired captures ---")
    pairs = discover_paired_captures()
    print(f"  Found {len(pairs)} paired captures (CSI + video)")
    for p in pairs[:5]:
        print(f"    {p['clip_id'][:65]}")
    if len(pairs) > 5:
        print(f"    ... and {len(pairs) - 5} more")

    if not pairs:
        print("ERROR: No paired captures found. Exiting.")
        sys.exit(1)

    # 2. Empty video baseline
    print("\n--- Computing empty video baseline ---")
    ebl = compute_empty_baseline(pairs)
    print(f"  Empty baseline: mean={ebl['mean']:.2f}, std={ebl['std']:.2f}, "
          f"p95={ebl['p95']:.2f}, n={ebl.get('n_samples', '?')}")

    # 3. Build aligned dataset
    print("\n--- Building aligned dataset ---")
    result = build_dataset(pairs, ebl)
    X, y_3c, y_bin, groups, fnames, clip_stats = result

    if X is None or len(X) < 20:
        print(f"ERROR: Too few aligned windows ({0 if X is None else len(X)}). "
              f"Need >= 20.")
        sys.exit(1)

    ldist_3c = {l: int((y_3c == l).sum()) for l in ["EMPTY", "STATIC", "MOTION"]
                if (y_3c == l).sum() > 0}
    ldist_bin = {l: int((y_bin == l).sum()) for l in ["STILL", "MOVING"]
                 if (y_bin == l).sum() > 0}
    print(f"\n  Total windows: {len(X)}")
    print(f"  Features: {len(fnames)}")
    print(f"  3-class distribution: {ldist_3c}")
    print(f"  Binary distribution:  {ldist_bin}")
    print(f"  Clips: {len(set(groups))}")

    # 4a. Train binary model (STILL vs MOVING -- the cleanest task)
    print("\n" + "=" * 72)
    print("  Task A: Binary STILL vs MOVING (frame-diff ground truth)")
    print("=" * 72)
    results_bin, model_bin = train_evaluate(X, y_bin, groups, fnames)

    # 4b. Train 3-class model (EMPTY/STATIC/MOTION)
    results_3c = None
    model_3c = None
    if min(ldist_3c.values()) >= 10:
        print("\n" + "=" * 72)
        print("  Task B: 3-class EMPTY/STATIC/MOTION (bg-sub + frame-diff)")
        print("=" * 72)
        results_3c, model_3c = train_evaluate(X, y_3c, groups, fnames)
    else:
        print(f"\n  Skipping 3-class: too few samples in minority class "
              f"({ldist_3c})")

    # 5. Save outputs
    elapsed = time.time() - t0

    output_json = {
        "pipeline": "v6_framediff",
        "description": (
            "Video frame-differencing ground truth. Breaks circular labeling. "
            "Binary task uses pure frame-diff (STILL vs MOVING). "
            "3-class task adds background subtraction for presence (EMPTY/STATIC/MOTION)."
        ),
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "elapsed_sec": round(elapsed, 1),
        "n_paired_captures": len(pairs),
        "n_total_windows": len(X),
        "n_clips": len(set(groups)),
        "n_features": len(fnames),
        "feature_names": fnames,
        "label_distribution_3class": ldist_3c,
        "label_distribution_binary": ldist_bin,
        "empty_video_baseline": ebl,
        "clip_stats": clip_stats,
        "binary_still_vs_moving": results_bin,
    }
    if results_3c:
        output_json["triclass_empty_static_motion"] = results_3c

    with open(RESULTS_PATH, "w") as fh:
        json.dump(output_json, fh, indent=2, default=str)
    print(f"\n  Results: {RESULTS_PATH}")

    with open(MODEL_PATH, "wb") as fh:
        pickle.dump({
            "model_binary": model_bin,
            "model_3class": model_3c,
            "feature_names": fnames,
            "empty_baseline": ebl,
        }, fh)
    print(f"  Model:   {MODEL_PATH}")

    # Summary
    print(f"\n{'=' * 72}")
    print(f"  DONE in {elapsed:.1f}s")
    print(f"  Binary STILL/MOVING  CV BalAcc: "
          f"{results_bin['cv_balanced_accuracy']:.4f}")
    if results_3c:
        print(f"  3-class E/S/M        CV BalAcc: "
              f"{results_3c['cv_balanced_accuracy']:.4f}")
    print(f"  Windows: {len(X)}, Clips: {len(set(groups))}, "
          f"Features: {len(fnames)}")
    print(f"  Binary: {ldist_bin}")
    print(f"  3-class: {ldist_3c}")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
