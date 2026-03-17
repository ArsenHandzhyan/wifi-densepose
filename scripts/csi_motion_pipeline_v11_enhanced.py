#!/usr/bin/env python3
"""
CSI-based Human Motion Recognition Pipeline v11 (Enhanced YOLO Labels)
======================================================================
Key improvement over v10: Uses ENHANCED YOLO annotations produced by running
YOLO on both original AND enhanced (gamma 0.3 + CLAHE + denoise) video frames.

Enhanced annotations live in:
  temp/video_teacher/{capture_label}.enhanced_yolo.csv
with columns:
  timestamp_sec, person_count_original, person_count_enhanced,
  person_count_best, motion_state, confidence_max, motion_score

person_count_best = max(original, enhanced) -- the honest label.
Enhancement yielded +132 frames (+9.9% improvement).

Architecture:
  Phase 1: Load ALL clips, match with enhanced YOLO then fallback to original YOLO
  Phase 2: Improved honest labeling using enhanced YOLO + clip.json metadata
  Phase 3: Rich feature extraction (~153 features: ~41 per-node averaged + 7 cross-node
            + 3 composites + epoch-normalized copies)
  Phase 4: Training (XGBoost, HistGBT, RandomForest, MLP) with StratifiedGroupKFold(5)
  Phase 5: Epoch-specific results
  Phase 6: Feature importance (permutation importance on best coarse model)
  Phase 7: Save results

Usage:
  python3 scripts/csi_motion_pipeline_v11_enhanced.py
"""

import os

# Limit threading BEFORE any numpy/scipy import
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"

import sys
import gc
import json
import glob
import gzip
import time
import base64
import warnings
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score,
    balanced_accuracy_score, f1_score,
)
from sklearn.inspection import permutation_importance
from sklearn.neural_network import MLPClassifier
from sklearn.base import clone as sklearn_clone
from scipy.stats import kurtosis as sp_kurtosis, skew as sp_skew

warnings.filterwarnings("ignore")

# Optional imports
try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("[INFO] xgboost not available, will skip XGBoost model")

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURES_DIR = BASE_DIR / "temp" / "captures"
YOLO_DIR = BASE_DIR / "temp" / "video_teacher"
OUTPUT_DIR = BASE_DIR / "output" / "csi_pipeline_v11_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CSI_HEADER_BYTES = 20
CSI_IQ_PAIRS = 128
CSI_PAYLOAD_BYTES = CSI_HEADER_BYTES + CSI_IQ_PAIRS * 2  # 276

ACTIVE_SC = np.array(list(range(6, 59)) + list(range(70, 123)), dtype=np.int32)
N_ACTIVE = len(ACTIVE_SC)  # 106

# Band splits: lo=0..35, mi=35..70, hi=70..106
BAND_LO = ACTIVE_SC[:35]
BAND_MI = ACTIVE_SC[35:70]
BAND_HI = ACTIVE_SC[70:]
BAND_INDICES = {"lo": np.arange(0, 35), "mi": np.arange(35, 70), "hi": np.arange(70, N_ACTIVE)}

SOURCE_ORDER = ["n01", "n02", "n03", "n04"]
IP_TO_NODE = {
    "192.168.1.101": "n01", "192.168.1.117": "n02",
    "192.168.1.125": "n03", "192.168.1.137": "n04",
}
CSI_RATE = 30.0

WINDOW_SEC = 1.5
STEP_SEC = 0.75


# ---------------------------------------------------------------------------
# Label definitions
# ---------------------------------------------------------------------------
EMPTY_LABELS = {
    "empty_room", "empty_room_pre", "empty_room_post",
    "empty_baseline", "door_no_entry",
    "empty_baseline_post", "empty_room_outside_pre", "empty_room_outside_post",
    "empty_pre", "empty_post", "empty_recalibrated",
    "empty_settled", "clean_empty", "empty_fp2_reference",
    "empty_room_confirm", "empty_room_settled_confirm",
    "empty_room_recalibrated_confirm", "empty_room_clean",
    "empty_pre_long", "empty_post_long",
}

STATIC_LABELS = {
    "quiet_static", "standing_still", "normal_breath", "deep_breath",
    "stand_center_edge", "stand_corridor", "stand_doorway",
    "squat_hold", "kneel_one_knee", "lie_down_floor",
    "reach_high", "hold_object_static", "lift_object_static",
    "three_person_static", "four_person_static", "three_people_static",
    "occupied_sit_down_hold", "occupied_stand_up_hold",
    "sit_down", "stand_up",
    "quiet_static_center", "quiet_static_center_confirm",
    "quiet_static_near_door_anchor", "quiet_static_far_left_anchor",
    "quiet_static_far_right_anchor", "quiet_static_center_anchor",
    "quiet_static_door_hold", "quiet_static_far_hold",
    "occupied_multiple_people",
    "hold_object_near_door_anchor",
    "lift_chair_near_door_anchor",
}


def _is_empty_label(label_name):
    ln = (label_name or "").lower().strip()
    if not ln:
        return False
    if ln in EMPTY_LABELS:
        return True
    for el in EMPTY_LABELS:
        if el in ln:
            return True
    return False


def _is_static_label(label_name):
    ln = (label_name or "").lower().strip()
    if not ln:
        return False
    if ln in STATIC_LABELS:
        return True
    for sl in STATIC_LABELS:
        if sl in ln:
            return True
    return False


# ---------------------------------------------------------------------------
# Enhanced YOLO annotation loading
# ---------------------------------------------------------------------------
_yolo_cache = {}


def _find_enhanced_yolo_csv(capture_label):
    """Find enhanced YOLO annotation CSV (priority) or fall back to original."""
    if capture_label in _yolo_cache:
        return _yolo_cache[capture_label]

    # Priority 1: Enhanced YOLO
    enhanced = YOLO_DIR / f"{capture_label}.enhanced_yolo.csv"
    if enhanced.exists():
        try:
            df = pd.read_csv(enhanced)
            if "timestamp_sec" in df.columns and "person_count_best" in df.columns:
                _yolo_cache[capture_label] = ("enhanced", df)
                return "enhanced", df
        except Exception:
            pass

    # Priority 2: Original YOLO
    original = YOLO_DIR / f"{capture_label}.yolo_annotations.csv"
    if original.exists():
        try:
            df = pd.read_csv(original)
            if "timestamp_sec" in df.columns and "person_count" in df.columns:
                # Normalize columns to match enhanced schema
                df["person_count_best"] = df["person_count"]
                if "motion_score" not in df.columns:
                    df["motion_score"] = 0.0
                _yolo_cache[capture_label] = ("original", df)
                return "original", df
        except Exception:
            pass

    _yolo_cache[capture_label] = (None, None)
    return None, None


# ---------------------------------------------------------------------------
# Honest labeling (v11 improved)
# ---------------------------------------------------------------------------
def get_honest_label(clip_meta, yolo_type, yolo_df, t_start, t_end):
    """
    Returns (binary_label, coarse_label) using the improved honest labeling strategy.

    Uses enhanced YOLO person_count_best (= max of original and enhanced detection)
    with 30% frame threshold for person presence.

    Returns (None, None) to skip unlabeled windows.
    """
    label_name = (clip_meta.get("label_name") or "").lower().strip()
    step_name = (clip_meta.get("step_name") or "").lower().strip()
    pc_expected = clip_meta.get("person_count_expected", -1)

    clip_says_empty = _is_empty_label(label_name) or _is_empty_label(step_name)
    if not clip_says_empty and pc_expected == 0 and "empty" in (label_name + step_name):
        clip_says_empty = True
    clip_says_static = _is_static_label(label_name) or _is_static_label(step_name)

    is_freeform = "long_capture_freeform" in label_name or "longcap" in label_name

    # --- Rule 1: We have YOLO for this window ---
    if yolo_df is not None and yolo_type is not None:
        window_rows = yolo_df[
            (yolo_df["timestamp_sec"] >= t_start) &
            (yolo_df["timestamp_sec"] < t_end)
        ]
        if len(window_rows) > 0:
            person_frames = (window_rows["person_count_best"] > 0).sum()
            total_frames = len(window_rows)
            yolo_sees_person = person_frames > total_frames * 0.3  # 30% threshold

            if yolo_sees_person:
                # YOLO confirms person present
                binary = "OCCUPIED"
                avg_motion = window_rows["motion_score"].mean()
                if avg_motion > 0.015:
                    coarse = "MOTION"
                else:
                    coarse = "STATIC"
                # Override with clip.json if more specific
                if clip_says_static:
                    coarse = "STATIC"
                elif not clip_says_empty and not clip_says_static and pc_expected is not None and pc_expected > 0:
                    coarse = "MOTION"  # trust clip label for motion
                return binary, coarse
            else:
                # YOLO doesn't see person
                if clip_says_empty or pc_expected == 0:
                    return "EMPTY", "EMPTY"
                elif (pc_expected is not None and pc_expected > 0) or clip_says_static:
                    # Clip says occupied but YOLO can't see (dark garage)
                    if clip_says_static:
                        return "OCCUPIED", "STATIC"
                    else:
                        return "OCCUPIED", "MOTION"
                elif is_freeform:
                    # Freeform + YOLO sees nothing -> probably empty
                    return "EMPTY", "EMPTY"
                else:
                    return None, None  # skip unlabeled

    # --- Rule 2: No YOLO -- use clip.json only ---
    if clip_says_empty:
        return "EMPTY", "EMPTY"

    if label_name == "long_capture_freeform" and pc_expected == -1:
        return None, None  # skip unlabeled freeform

    if clip_says_static:
        return "OCCUPIED", "STATIC"

    if (pc_expected is not None and pc_expected > 0) or (not clip_says_empty and label_name and not is_freeform):
        return "OCCUPIED", "MOTION"

    return None, None


# ---------------------------------------------------------------------------
# CSI parsing
# ---------------------------------------------------------------------------
def parse_csi_packet(payload_b64):
    """Parse one CSI packet -> (amplitude_128, phase_128) as float32."""
    try:
        raw = base64.b64decode(payload_b64)
    except Exception:
        return None, None
    if len(raw) < CSI_PAYLOAD_BYTES:
        return None, None
    iq = np.frombuffer(
        raw[CSI_HEADER_BYTES:CSI_PAYLOAD_BYTES], dtype=np.int8
    ).reshape(CSI_IQ_PAIRS, 2)
    i_v = iq[:, 0].astype(np.float32)
    q_v = iq[:, 1].astype(np.float32)
    amp = np.sqrt(i_v ** 2 + q_v ** 2)
    phase = np.arctan2(q_v, i_v)
    return amp, phase


def load_clip_csi(capture_file):
    """Load CSI data grouped by node. Returns dict: node -> list of (ts_ns, amp128, phase128)."""
    if not capture_file or not os.path.exists(capture_file):
        return {}
    data = defaultdict(list)
    try:
        with gzip.open(capture_file, "rt") as fh:
            for line in fh:
                try:
                    pkt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = pkt.get("ts_ns")
                src = pkt.get("src_ip")
                p64 = pkt.get("payload_b64")
                if not (ts and src and p64):
                    continue
                amp, phase = parse_csi_packet(p64)
                if amp is not None:
                    node = IP_TO_NODE.get(src, src)
                    if node in SOURCE_ORDER:
                        data[node].append((ts, amp, phase))
    except Exception as e:
        print(f"    [WARN] CSI load error: {e}")
    return data


# ---------------------------------------------------------------------------
# Empty-room baselines (per epoch)
# ---------------------------------------------------------------------------
_epoch_baselines = {}


def build_empty_baselines(clips_meta):
    """Compute per-epoch, per-node baselines from EMPTY clips."""
    print("\n--- Building epoch-specific empty-room baselines ---")
    epoch_node_amps = defaultdict(lambda: defaultdict(list))

    for _cf, meta in clips_meta:
        ln = (meta.get("label_name", "") or "").lower()
        if not _is_empty_label(ln):
            continue
        capf = meta.get("capture_file") or (meta.get("files") or {}).get("csi_ndjson", "")
        epoch = meta.get("dataset_epoch") or "early"
        if not capf or not os.path.exists(capf):
            continue
        csi = load_clip_csi(capf)
        for node, pkts in csi.items():
            for _, amp, _ in pkts[:300]:
                epoch_node_amps[epoch][node].append(amp)
        del csi
        gc.collect()

    for epoch, enodes in epoch_node_amps.items():
        _epoch_baselines[epoch] = {}
        for node, amps in enodes.items():
            if len(amps) >= 10:
                mat = np.array(amps, dtype=np.float32)
                _epoch_baselines[epoch][node] = {
                    "mean": mat.mean(axis=0),
                    "std": mat.std(axis=0) + np.float32(1e-6),
                }
                del mat
        nodes_info = ", ".join(f"{n}({len(enodes[n])})" for n in sorted(enodes))
        print(f"  Epoch '{epoch}': {nodes_info}")

    # Build combined fallback
    if epoch_node_amps:
        all_node_amps = defaultdict(list)
        for edata in epoch_node_amps.values():
            for node, amps in edata.items():
                all_node_amps[node].extend(amps)
        _epoch_baselines["_fallback"] = {}
        for node, amps in all_node_amps.items():
            if len(amps) >= 10:
                mat = np.array(amps, dtype=np.float32)
                _epoch_baselines["_fallback"][node] = {
                    "mean": mat.mean(axis=0),
                    "std": mat.std(axis=0) + np.float32(1e-6),
                }
                del mat
        print(f"  Fallback: {sorted(_epoch_baselines['_fallback'].keys())}")

    del epoch_node_amps
    gc.collect()


def get_baseline(node, epoch):
    if epoch in _epoch_baselines and node in _epoch_baselines[epoch]:
        return _epoch_baselines[epoch][node]
    if "_fallback" in _epoch_baselines and node in _epoch_baselines["_fallback"]:
        return _epoch_baselines["_fallback"][node]
    return None


# ---------------------------------------------------------------------------
# Per-node feature extraction (~41 features per node)
# ---------------------------------------------------------------------------
def extract_node_features(amp_mat, phase_mat, node, epoch):
    """
    Extract rich features from one node's time window.

    amp_mat:   (n_samples, 128) float32
    phase_mat: (n_samples, 128) float32

    Returns dict with ~41 features per node, or None if too few samples.
    Features are computed globally across active subcarriers AND per-band
    (lo, mi, hi) for key temporal stats.
    """
    n = amp_mat.shape[0]
    if n < 4:
        return None

    f = {}
    p = f"n_{node}_"
    amp_active = amp_mat[:, ACTIVE_SC]  # (n, 106)

    # ------ 1. AMPLITUDE STATS (7) ------
    amp_mean_per_sc = amp_active.mean(axis=0)
    global_mean = amp_mean_per_sc.mean()
    f[f"{p}amp_mean"] = np.float32(global_mean)
    f[f"{p}amp_std"] = np.float32(amp_mean_per_sc.std())
    f[f"{p}amp_range"] = np.float32(amp_mean_per_sc.max() - amp_mean_per_sc.min())
    iqr = np.percentile(amp_mean_per_sc, 75) - np.percentile(amp_mean_per_sc, 25)
    f[f"{p}amp_iqr"] = np.float32(iqr)
    f[f"{p}amp_cv"] = np.float32(amp_mean_per_sc.std() / (global_mean + 1e-10))
    f[f"{p}amp_kurtosis"] = np.float32(sp_kurtosis(amp_mean_per_sc))
    f[f"{p}amp_skew"] = np.float32(sp_skew(amp_mean_per_sc))

    # ------ 2. TEMPORAL VARIANCE per band (9) ------
    tv = amp_active.var(axis=0)  # per-subcarrier temporal variance
    for bname, bidx in BAND_INDICES.items():
        band_tv = tv[bidx]
        f[f"{p}tv_{bname}_mean"] = np.float32(band_tv.mean())
        f[f"{p}tv_{bname}_max"] = np.float32(band_tv.max())
        f[f"{p}tv_{bname}_p90"] = np.float32(np.percentile(band_tv, 90))

    # ------ 3. FIRST-DIFF ENERGY (3) ------
    diff1 = np.diff(amp_active, axis=0)
    abs_diff1 = np.abs(diff1)
    f[f"{p}diff1_mean"] = np.float32(abs_diff1.mean())
    f[f"{p}diff1_max"] = np.float32(abs_diff1.max())
    f[f"{p}diff1_std"] = np.float32(abs_diff1.std())

    # ------ 4. SECOND-DIFF ENERGY (2) ------
    if n >= 3:
        diff2 = np.diff(amp_active, n=2, axis=0)
        abs_diff2 = np.abs(diff2)
        f[f"{p}diff2_mean"] = np.float32(abs_diff2.mean())
        f[f"{p}diff2_max"] = np.float32(abs_diff2.max())
    else:
        f[f"{p}diff2_mean"] = np.float32(0.0)
        f[f"{p}diff2_max"] = np.float32(0.0)

    # ------ 5. BASELINE DEVIATION (3) ------
    bl = get_baseline(node, epoch)
    if bl is not None:
        bl_mean_sc = bl["mean"][ACTIVE_SC]
        bl_std_sc = bl["std"][ACTIVE_SC]
        win_mean = amp_active.mean(axis=0)
        deviation = np.abs(win_mean - bl_mean_sc) / bl_std_sc
        f[f"{p}bldev_mean"] = np.float32(deviation.mean())
        f[f"{p}bldev_max"] = np.float32(deviation.max())
        f[f"{p}bldev_p90"] = np.float32(np.percentile(deviation, 90))
    else:
        f[f"{p}bldev_mean"] = np.float32(0.0)
        f[f"{p}bldev_max"] = np.float32(0.0)
        f[f"{p}bldev_p90"] = np.float32(0.0)

    # ------ 6. BMI (1) ------
    var_diff = np.mean(np.var(diff1, axis=0))
    var_sig = np.mean(np.var(amp_active, axis=0)) + np.float32(1e-10)
    f[f"{p}bmi"] = np.float32(var_diff / var_sig)

    # ------ 7. DOPPLER / PHASE DERIVATIVE (3) ------
    if n >= 6:
        phase_active = phase_mat[:, ACTIVE_SC]
        phase_uw = np.unwrap(phase_active, axis=0).astype(np.float32)
        phase_rate = np.diff(phase_uw, axis=0) * np.float32(CSI_RATE)
        abs_pr = np.abs(phase_rate)
        f[f"{p}doppler_mean"] = np.float32(abs_pr.mean())
        f[f"{p}doppler_max"] = np.float32(abs_pr.max())
        f[f"{p}doppler_std"] = np.float32(phase_rate.std())
    else:
        f[f"{p}doppler_mean"] = np.float32(0.0)
        f[f"{p}doppler_max"] = np.float32(0.0)
        f[f"{p}doppler_std"] = np.float32(0.0)

    # ------ 8. AUTOCORRELATION (4) ------
    ts_mean = amp_active.mean(axis=1)
    ts_centered = ts_mean - ts_mean.mean()
    ts_var = np.var(ts_centered) + 1e-10
    for lag in [1, 2, 4, 6]:
        if n > lag:
            ac = np.mean(ts_centered[:-lag] * ts_centered[lag:]) / ts_var
            f[f"{p}ac_lag{lag}"] = np.float32(ac)
        else:
            f[f"{p}ac_lag{lag}"] = np.float32(0.0)

    # ------ 9. ZERO CROSSING RATE (1) ------
    diff1_mean = np.diff(ts_mean)
    if len(diff1_mean) > 1:
        zcr = np.mean(np.abs(np.diff(np.sign(diff1_mean))) > 0)
        f[f"{p}zcr"] = np.float32(zcr)
    else:
        f[f"{p}zcr"] = np.float32(0.0)

    # ------ 10. MOVING VARIANCE RATIO (2) ------
    if n >= 10:
        short_w = max(3, n // 6)
        long_w = max(6, n // 2)
        ts = ts_mean
        short_vars = [np.var(ts[max(0, i - short_w):i + 1]) for i in range(short_w, n)]
        long_vars = [np.var(ts[max(0, i - long_w):i + 1]) for i in range(long_w, n)]
        if short_vars and long_vars:
            sv = np.array(short_vars, dtype=np.float32)
            lv_mean = np.mean(long_vars) + 1e-10
            f[f"{p}mvr_mean"] = np.float32(np.mean(sv) / lv_mean)
            f[f"{p}mvr_max"] = np.float32(np.max(sv) / lv_mean)
        else:
            f[f"{p}mvr_mean"] = np.float32(1.0)
            f[f"{p}mvr_max"] = np.float32(1.0)
    else:
        f[f"{p}mvr_mean"] = np.float32(1.0)
        f[f"{p}mvr_max"] = np.float32(1.0)

    # ------ 11. FFT BAND ENERGIES (4) ------
    if n >= 10:
        ts_fft = ts_mean
        ts_fft_centered = ts_fft - ts_fft.mean()
        fft_mag = np.abs(np.fft.rfft(ts_fft_centered.astype(np.float64))).astype(np.float32)
        freqs = np.fft.rfftfreq(len(ts_fft_centered), d=1.0 / CSI_RATE).astype(np.float32)
        total_power = fft_mag.sum() + np.float32(1e-10)

        for bname, lo, hi in [("breath", 0.1, 0.5), ("slow", 0.5, 3.0), ("fast", 3.0, 12.0)]:
            mask = (freqs >= lo) & (freqs <= hi)
            f[f"{p}fft_{bname}"] = np.float32(
                fft_mag[mask].sum() / total_power) if mask.any() else np.float32(0.0)

        fast_e = f[f"{p}fft_fast"]
        slow_e = f[f"{p}fft_slow"]
        f[f"{p}fft_motion_ratio"] = np.float32(fast_e / (slow_e + 1e-10))
    else:
        for suffix in ["fft_breath", "fft_slow", "fft_fast", "fft_motion_ratio"]:
            f[f"{p}{suffix}"] = np.float32(0.0)

    # ------ 12. PCA EIGENVALUE RATIOS (2) ------
    if n >= 6:
        sub_amp = amp_active[:, ::4]  # every 4th for speed
        try:
            corr = np.corrcoef(sub_amp.T)
            corr = np.nan_to_num(corr, nan=0.0)
            evals = np.linalg.eigvalsh(corr)[::-1]
            evals = np.maximum(evals, np.float32(1e-10))
            total_ev = evals.sum()
            ev_norm = evals / total_ev
            f[f"{p}pca_ev1"] = np.float32(evals[0] / total_ev)
            f[f"{p}pca_effdim"] = np.float32(
                np.exp(-np.sum(ev_norm * np.log(ev_norm + 1e-10))))
        except Exception:
            f[f"{p}pca_ev1"] = np.float32(0.5)
            f[f"{p}pca_effdim"] = np.float32(10.0)
    else:
        f[f"{p}pca_ev1"] = np.float32(0.5)
        f[f"{p}pca_effdim"] = np.float32(10.0)

    return f


# ---------------------------------------------------------------------------
# Window-level feature extraction
# ---------------------------------------------------------------------------
def extract_window_features(csi_data, t_start_ns, t_end_ns, epoch):
    """
    Extract features for one time window, aggregating across nodes.
    Returns dict or None.
    """
    per_node = {}
    node_amp_ts = {}
    node_me_ts = {}
    node_phase_rate_ts = {}

    for node, pkts in csi_data.items():
        amps, phases = [], []
        for t, a, ph in pkts:
            if t_start_ns <= t < t_end_ns:
                amps.append(a)
                phases.append(ph)
        if len(amps) < 4:
            continue

        amp_mat = np.array(amps, dtype=np.float32)
        phase_mat = np.array(phases, dtype=np.float32)

        nf = extract_node_features(amp_mat, phase_mat, node, epoch)
        if nf:
            per_node[node] = nf
            active_amp = amp_mat[:, ACTIVE_SC].mean(axis=1)
            node_amp_ts[node] = active_amp
            node_me_ts[node] = np.abs(np.diff(active_amp))
            if len(amps) >= 6:
                uw = np.unwrap(phase_mat[:, ACTIVE_SC].mean(axis=1)).astype(np.float32)
                node_phase_rate_ts[node] = np.diff(uw)
        del amp_mat, phase_mat

    if not per_node:
        return None

    feat = {}

    # --- Aggregate per-node features: mean across available nodes ---
    feat_groups = defaultdict(list)
    for nf in per_node.values():
        for k, v in nf.items():
            # key format: "n_XX_feature_name" -> strip to "feature_name"
            parts = k.split("_", 2)
            feat_name = parts[2] if len(parts) >= 3 else k
            feat_groups[feat_name].append(v)

    for feat_name, vals in feat_groups.items():
        feat[f"avg_{feat_name}"] = np.float32(np.mean(vals))

    # --- Cross-node features (7) ---
    if len(node_amp_ts) >= 2:
        nodes = sorted(node_amp_ts.keys())
        amp_corrs, me_corrs, phase_corrs = [], [], []

        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a = node_amp_ts[nodes[i]]
                b = node_amp_ts[nodes[j]]
                mn = min(len(a), len(b))
                if mn < 4:
                    continue

                c = np.corrcoef(a[:mn], b[:mn])[0, 1]
                amp_corrs.append(0.0 if np.isnan(c) else float(c))

                da = node_me_ts.get(nodes[i])
                db = node_me_ts.get(nodes[j])
                if da is not None and db is not None:
                    mn2 = min(len(da), len(db))
                    if mn2 >= 3:
                        mc = np.corrcoef(da[:mn2], db[:mn2])[0, 1]
                        me_corrs.append(0.0 if np.isnan(mc) else float(mc))

                pa = node_phase_rate_ts.get(nodes[i])
                pb = node_phase_rate_ts.get(nodes[j])
                if pa is not None and pb is not None:
                    mn3 = min(len(pa), len(pb))
                    if mn3 >= 3:
                        pc_val = np.corrcoef(pa[:mn3], pb[:mn3])[0, 1]
                        phase_corrs.append(0.0 if np.isnan(pc_val) else float(pc_val))

        if amp_corrs:
            feat["xn_amp_corr_mean"] = np.float32(np.mean(amp_corrs))
            feat["xn_amp_corr_max"] = np.float32(np.max(amp_corrs))
            feat["xn_amp_corr_min"] = np.float32(np.min(amp_corrs))
            feat["xn_amp_corr_range"] = np.float32(np.max(amp_corrs) - np.min(amp_corrs))
        if me_corrs:
            feat["xn_me_corr_mean"] = np.float32(np.mean(me_corrs))
            feat["xn_me_corr_max"] = np.float32(np.max(me_corrs))
        if phase_corrs:
            feat["xn_phase_diff_std_mean"] = np.float32(np.std(phase_corrs))

    # --- Composite features (3) ---
    bmi = feat.get("avg_bmi", 0)
    doppler = feat.get("avg_doppler_mean", 0)
    me = feat.get("avg_diff1_mean", 0)

    feat["cmp_motion_score"] = np.float32(bmi * me * (1 + doppler))
    feat["cmp_bmi_x_doppler"] = np.float32(bmi * doppler)
    feat["cmp_n_active_sources"] = np.float32(len(per_node))

    return feat


# ---------------------------------------------------------------------------
# Epoch normalization
# ---------------------------------------------------------------------------
def add_epoch_normalized_features(df, feature_cols, epoch_col="epoch"):
    """Add z-scored features per epoch. Returns new DataFrame with added columns."""
    new_cols = {}
    for col in feature_cols:
        if col not in df.columns:
            continue
        zname = f"ez_{col}"
        vals = df[col].values.astype(np.float32)
        new_vals = np.zeros_like(vals)
        for epoch in df[epoch_col].unique():
            mask = df[epoch_col].values == epoch
            subset = vals[mask]
            if len(subset) > 1 and subset.std() > 1e-10:
                new_vals[mask] = (subset - subset.mean()) / (subset.std() + 1e-10)
            else:
                new_vals[mask] = 0.0
        new_cols[zname] = new_vals

    return pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)


# ---------------------------------------------------------------------------
# Dataset building
# ---------------------------------------------------------------------------
def build_dataset():
    t0 = time.time()
    print("=" * 70)
    print("PHASE 1: Load Clip Metadata & Enhanced YOLO Annotations")
    print(f"  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70)

    clip_files = sorted(glob.glob(str(CAPTURES_DIR / "*.clip.json")))
    print(f"Found {len(clip_files)} clip metadata files")

    clips_meta = []
    for cf in clip_files:
        try:
            with open(cf) as fh:
                meta = json.load(fh)
            clips_meta.append((cf, meta))
        except Exception:
            continue

    print(f"Loaded {len(clips_meta)} clip metadata entries")

    # Check YOLO coverage
    enhanced_files = sorted(glob.glob(str(YOLO_DIR / "*.enhanced_yolo.csv")))
    original_files = sorted(glob.glob(str(YOLO_DIR / "*.yolo_annotations.csv")))
    print(f"Found {len(enhanced_files)} enhanced YOLO + {len(original_files)} original YOLO files")

    # Build empty baselines
    build_empty_baselines(clips_meta)

    print(f"\n{'=' * 70}")
    print("PHASE 2: Feature Extraction with Enhanced YOLO Labels")
    print(f"  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70)

    rows = []
    label_stats = Counter()
    skipped_reasons = Counter()
    yolo_type_stats = Counter()
    clip_count = 0

    for clip_idx, (cf, meta) in enumerate(clips_meta):
        label_name = (meta.get("label_name") or "").lower().strip()
        capture_label = meta.get("capture_label", "")
        epoch = meta.get("dataset_epoch") or "early"

        # Get CSI capture file
        capf = meta.get("capture_file") or (meta.get("files") or {}).get("csi_ndjson", "")
        if not capf or not os.path.exists(capf):
            skipped_reasons["no_csi_file"] += 1
            continue

        # Try to find YOLO annotations (enhanced first, then original)
        yolo_type, yolo_df = _find_enhanced_yolo_csv(capture_label)

        # Pre-check: can we get any label at all?
        test_binary, test_coarse = get_honest_label(meta, yolo_type, yolo_df, 0, 10)
        if test_binary is None and yolo_df is None:
            skipped_reasons["no_label_no_yolo"] += 1
            continue

        # Load CSI
        csi_data = load_clip_csi(capf)
        if not csi_data:
            skipped_reasons["empty_csi"] += 1
            continue

        # Determine time range
        all_ts = []
        for node, pkts in csi_data.items():
            for t, _, _ in pkts:
                all_ts.append(t)
        if not all_ts:
            skipped_reasons["no_timestamps"] += 1
            del csi_data
            continue

        t_min = min(all_ts)
        t_max = max(all_ts)
        del all_ts

        # Get clip start time for YOLO alignment
        clip_start_ns = meta.get("started_at_ns")
        if clip_start_ns is None:
            ts_start_str = meta.get("timestamp_start", "")
            if ts_start_str:
                try:
                    dt = datetime.fromisoformat(ts_start_str.replace("Z", "+00:00"))
                    clip_start_ns = int(dt.timestamp() * 1e9)
                except Exception:
                    clip_start_ns = t_min
            else:
                clip_start_ns = t_min

        # Window iteration
        window_ns = int(WINDOW_SEC * 1e9)
        step_ns = int(STEP_SEC * 1e9)
        n_windows = 0

        t_cur = t_min
        while t_cur + window_ns <= t_max + step_ns:
            t_end = t_cur + window_ns

            # Convert window times to seconds-since-clip-start for YOLO
            win_start_sec = (t_cur - clip_start_ns) / 1e9
            win_end_sec = (t_end - clip_start_ns) / 1e9

            # Get honest labels for this window
            binary_label, coarse_label = get_honest_label(
                meta, yolo_type, yolo_df,
                max(0, win_start_sec), max(0, win_end_sec)
            )

            if binary_label is None:
                t_cur += step_ns
                continue

            # Extract features
            feat = extract_window_features(csi_data, t_cur, t_end, epoch)
            if feat is None:
                t_cur += step_ns
                continue

            feat["binary"] = binary_label
            feat["coarse"] = coarse_label
            feat["clip_id"] = capture_label
            feat["epoch"] = epoch
            feat["window_sec"] = np.float32(win_start_sec)
            feat["yolo_type"] = yolo_type or "none"

            rows.append(feat)
            label_stats[f"{binary_label}/{coarse_label}"] += 1
            if yolo_type:
                yolo_type_stats[yolo_type] += 1
            else:
                yolo_type_stats["none"] += 1
            n_windows += 1
            t_cur += step_ns

        clip_count += 1
        if clip_count % 20 == 0:
            elapsed = time.time() - t0
            print(f"  [{elapsed:.0f}s] Processed {clip_count}/{len(clips_meta)} clips, "
                  f"{len(rows)} windows so far...")

        del csi_data
        gc.collect()

    elapsed = time.time() - t0
    print(f"\nFeature extraction complete in {elapsed:.1f}s")
    print(f"  Clips processed: {clip_count}")
    print(f"  Windows extracted: {len(rows)}")
    print(f"  Skip reasons: {dict(skipped_reasons)}")
    print(f"  Label distribution: {dict(label_stats)}")
    print(f"  YOLO type distribution: {dict(yolo_type_stats)}")

    if not rows:
        print("[ERROR] No data extracted. Exiting.")
        sys.exit(1)

    df = pd.DataFrame(rows)

    # Identify feature columns (exclude metadata)
    meta_cols = {"binary", "coarse", "clip_id", "epoch", "window_sec", "yolo_type"}
    feature_cols = [c for c in df.columns if c not in meta_cols]

    # Fill NaN with 0
    df[feature_cols] = df[feature_cols].fillna(0).astype(np.float32)

    print(f"\n  Raw features: {len(feature_cols)}")

    # Add epoch-normalized features
    print("  Adding epoch-normalized features...")
    df = add_epoch_normalized_features(df, feature_cols, epoch_col="epoch")

    # Update feature columns
    feature_cols = [c for c in df.columns if c not in meta_cols]
    print(f"  Total features (raw + epoch-normalized): {len(feature_cols)}")

    return df, feature_cols


# ---------------------------------------------------------------------------
# Model training and evaluation
# ---------------------------------------------------------------------------
def train_and_evaluate(df, feature_cols):
    t0 = time.time()
    print(f"\n{'=' * 70}")
    print("PHASE 4: Model Training & Cross-Validation")
    print(f"  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70)

    X = df[feature_cols].values.astype(np.float32)
    groups = df["clip_id"].values

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X).astype(np.float32)

    results = {}

    # Define tasks
    tasks = {
        "binary": {
            "y": df["binary"].values,
            "desc": "Binary (EMPTY/OCCUPIED)",
        },
        "coarse": {
            "y": df["coarse"].values,
            "desc": "Coarse 3-class (EMPTY/STATIC/MOTION)",
        },
        "hier_sm": {
            "y": df.loc[df["binary"] == "OCCUPIED", "coarse"].values,
            "desc": "Hierarchical STATIC/MOTION (occupied only)",
            "mask": df["binary"].values == "OCCUPIED",
        },
    }

    for task_name, task_info in tasks.items():
        print(f"\n--- Task: {task_info['desc']} ---")

        mask = task_info.get("mask")
        if mask is not None:
            X_task = X_scaled[mask]
            y_task = task_info["y"]
            groups_task = groups[mask]
        else:
            X_task = X_scaled
            y_task = task_info["y"]
            groups_task = groups

        n_classes = len(set(y_task))
        print(f"  Samples: {len(y_task)}, Classes: {n_classes}, "
              f"Distribution: {dict(Counter(y_task))}")

        if n_classes < 2:
            print("  [SKIP] Only one class present")
            continue

        # Encode labels
        le = LabelEncoder()
        y_encoded = le.fit_transform(y_task)

        # Define models
        models = {}

        if HAS_XGB:
            models["XGBoost"] = XGBClassifier(
                n_estimators=500, max_depth=6, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                use_label_encoder=False, eval_metric="mlogloss",
                n_jobs=2, random_state=42, verbosity=0,
            )

        models["HistGBT"] = HistGradientBoostingClassifier(
            max_iter=500, max_depth=6, learning_rate=0.05,
            min_samples_leaf=20, l2_regularization=1.0,
            random_state=42,
        )

        models["RandomForest"] = RandomForestClassifier(
            n_estimators=300, max_depth=15, min_samples_leaf=5,
            class_weight="balanced",
            n_jobs=2, random_state=42,
        )

        models["MLP"] = MLPClassifier(
            hidden_layer_sizes=(128, 64, 32),
            early_stopping=True, max_iter=500, alpha=0.001,
            random_state=42, validation_fraction=0.15,
        )

        # Cross-validation
        n_unique_groups = len(set(groups_task))
        n_splits = min(5, n_unique_groups)
        if n_splits < 2:
            print("  [SKIP] Not enough groups for CV")
            continue

        cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)

        task_results = {}

        for model_name, model in models.items():
            print(f"  Training {model_name}...", end=" ", flush=True)

            fold_metrics = []
            all_y_true = []
            all_y_pred = []
            all_groups_true = []

            try:
                for fold_i, (train_idx, test_idx) in enumerate(
                    cv.split(X_task, y_encoded, groups_task)
                ):
                    X_tr, X_te = X_task[train_idx], X_task[test_idx]
                    y_tr, y_te = y_encoded[train_idx], y_encoded[test_idx]

                    model_clone = sklearn_clone(model)
                    model_clone.fit(X_tr, y_tr)
                    y_pred = model_clone.predict(X_te)

                    bal_acc = balanced_accuracy_score(y_te, y_pred)
                    fold_metrics.append(bal_acc)
                    all_y_true.extend(y_te)
                    all_y_pred.extend(y_pred)
                    all_groups_true.extend(groups_task[test_idx])

                mean_ba = np.mean(fold_metrics)
                std_ba = np.std(fold_metrics)
                overall_acc = accuracy_score(all_y_true, all_y_pred)
                overall_ba = balanced_accuracy_score(all_y_true, all_y_pred)
                overall_f1 = f1_score(all_y_true, all_y_pred, average="macro")

                print(f"BalAcc={mean_ba:.3f}+-{std_ba:.3f}, "
                      f"Acc={overall_acc:.3f}, F1={overall_f1:.3f}")

                # Compute clip-level BalAcc
                clip_ba = _compute_clip_level_balacc(
                    all_y_true, all_y_pred, all_groups_true
                )

                task_results[model_name] = {
                    "mean_bal_acc": mean_ba,
                    "std_bal_acc": std_ba,
                    "overall_acc": overall_acc,
                    "overall_bal_acc": overall_ba,
                    "overall_f1": overall_f1,
                    "clip_level_bal_acc": clip_ba,
                    "fold_metrics": fold_metrics,
                    "y_true": all_y_true,
                    "y_pred": all_y_pred,
                    "le": le,
                }
            except Exception as e:
                print(f"FAILED: {e}")
                continue

        if task_results:
            # Find best model
            best_model_name = max(task_results, key=lambda k: task_results[k]["mean_bal_acc"])
            best = task_results[best_model_name]
            print(f"\n  BEST: {best_model_name} -> BalAcc={best['mean_bal_acc']:.3f} "
                  f"+-{best['std_bal_acc']:.3f}, ClipBalAcc={best['clip_level_bal_acc']:.3f}")

            # Print confusion matrix for best
            y_t = np.array(best["y_true"])
            y_p = np.array(best["y_pred"])
            class_names = best["le"].classes_
            print(f"\n  Confusion matrix ({best_model_name}):")
            print(f"  Classes: {list(class_names)}")
            cm = confusion_matrix(y_t, y_p)
            print(f"  {cm}")
            print(f"\n  Per-class precision/recall:")
            print(classification_report(
                y_t, y_p, target_names=class_names, digits=3
            ))

        results[task_name] = task_results

    elapsed = time.time() - t0
    print(f"\nTraining complete in {elapsed:.1f}s")

    return results


def _compute_clip_level_balacc(y_true, y_pred, groups):
    """Compute balanced accuracy at clip level (majority vote per clip)."""
    clip_true = defaultdict(list)
    clip_pred = defaultdict(list)
    for yt, yp, g in zip(y_true, y_pred, groups):
        clip_true[g].append(yt)
        clip_pred[g].append(yp)

    clip_y_true = []
    clip_y_pred = []
    for g in clip_true:
        # Majority vote
        true_label = Counter(clip_true[g]).most_common(1)[0][0]
        pred_label = Counter(clip_pred[g]).most_common(1)[0][0]
        clip_y_true.append(true_label)
        clip_y_pred.append(pred_label)

    if len(set(clip_y_true)) < 2:
        return accuracy_score(clip_y_true, clip_y_pred)
    return balanced_accuracy_score(clip_y_true, clip_y_pred)


# ---------------------------------------------------------------------------
# Epoch-specific results
# ---------------------------------------------------------------------------
def epoch_specific_evaluation(df, feature_cols, results):
    print(f"\n{'=' * 70}")
    print("PHASE 5: Epoch-Specific Results")
    print(f"  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70)

    meta_cols = {"binary", "coarse", "clip_id", "epoch", "window_sec", "yolo_type"}
    scaler = StandardScaler()

    for epoch_name in ["early", "garage_ceiling_v2"]:
        epoch_mask = df["epoch"] == epoch_name
        df_epoch = df[epoch_mask]
        if len(df_epoch) < 20:
            print(f"\n  Epoch '{epoch_name}': too few samples ({len(df_epoch)}), skipping")
            continue

        print(f"\n  === Epoch: '{epoch_name}' ({len(df_epoch)} windows, "
              f"{df_epoch['clip_id'].nunique()} clips) ===")

        X_epoch = df_epoch[feature_cols].values.astype(np.float32)
        X_epoch_scaled = scaler.fit_transform(X_epoch).astype(np.float32)
        groups_epoch = df_epoch["clip_id"].values

        for task_name, label_col in [("binary", "binary"), ("coarse", "coarse")]:
            y_epoch = df_epoch[label_col].values
            n_classes = len(set(y_epoch))
            if n_classes < 2:
                print(f"    {task_name}: only {n_classes} class(es), skip")
                continue

            le = LabelEncoder()
            y_enc = le.fit_transform(y_epoch)

            n_unique_groups = len(set(groups_epoch))
            n_splits = min(5, n_unique_groups)
            if n_splits < 2:
                print(f"    {task_name}: not enough groups ({n_unique_groups}), skip")
                continue

            cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)

            # Use HistGBT for epoch evaluation
            model = HistGradientBoostingClassifier(
                max_iter=500, max_depth=6, learning_rate=0.05,
                min_samples_leaf=20, l2_regularization=1.0,
                random_state=42,
            )

            fold_ba = []
            all_yt, all_yp = [], []
            try:
                for train_idx, test_idx in cv.split(X_epoch_scaled, y_enc, groups_epoch):
                    m = sklearn_clone(model)
                    m.fit(X_epoch_scaled[train_idx], y_enc[train_idx])
                    yp = m.predict(X_epoch_scaled[test_idx])
                    fold_ba.append(balanced_accuracy_score(y_enc[test_idx], yp))
                    all_yt.extend(y_enc[test_idx])
                    all_yp.extend(yp)

                ba = np.mean(fold_ba)
                ba_std = np.std(fold_ba)
                f1 = f1_score(all_yt, all_yp, average="macro")
                print(f"    {task_name}: BalAcc={ba:.3f}+-{ba_std:.3f}, F1={f1:.3f}, "
                      f"dist={dict(Counter(y_epoch))}")
            except Exception as e:
                print(f"    {task_name}: failed ({e})")


# ---------------------------------------------------------------------------
# Feature importance analysis
# ---------------------------------------------------------------------------
def analyze_feature_importance(df, feature_cols, results):
    print(f"\n{'=' * 70}")
    print("PHASE 6: Feature Importance Analysis")
    print(f"  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70)

    X = df[feature_cols].values.astype(np.float32)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X).astype(np.float32)

    # Use coarse labels for importance analysis
    y_coarse = df["coarse"].values
    le = LabelEncoder()
    y_encoded = le.fit_transform(y_coarse)

    # Train best model on full data for importance
    best_model = HistGradientBoostingClassifier(
        max_iter=500, max_depth=6, learning_rate=0.05,
        min_samples_leaf=20, l2_regularization=1.0,
        random_state=42,
    )
    best_model.fit(X_scaled, y_encoded)

    # Permutation importance
    print("  Computing permutation importance (coarse task)...")
    perm_imp = permutation_importance(
        best_model, X_scaled, y_encoded,
        n_repeats=5, random_state=42, n_jobs=2,
        scoring="balanced_accuracy",
    )

    imp_mean = perm_imp.importances_mean
    imp_std = perm_imp.importances_std
    sorted_idx = np.argsort(imp_mean)[::-1]

    print("\n  Top 20 features (permutation importance, coarse task):")
    top_features = []
    for rank, idx in enumerate(sorted_idx[:20]):
        name = feature_cols[idx]
        print(f"    {rank + 1:2d}. {name:50s}  {imp_mean[idx]:.4f} +- {imp_std[idx]:.4f}")
        top_features.append((name, float(imp_mean[idx]), float(imp_std[idx])))

    return top_features


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------
def save_results(df, feature_cols, results, top_features):
    print(f"\n{'=' * 70}")
    print("PHASE 7: Saving Results")
    print(f"  {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 70)

    # Save dataset
    csv_path = OUTPUT_DIR / "v11_dataset.csv"
    df.to_csv(csv_path, index=False)
    print(f"  Dataset saved: {csv_path} ({len(df)} rows, {len(feature_cols)} features)")

    # Save summary
    summary = {
        "pipeline_version": "v11_enhanced_yolo",
        "timestamp": datetime.now().isoformat(),
        "n_windows": len(df),
        "n_features_raw_plus_normalized": len(feature_cols),
        "n_clips": int(df["clip_id"].nunique()),
        "yolo_coverage": dict(Counter(df["yolo_type"])),
        "label_distribution": {
            "binary": {k: int(v) for k, v in Counter(df["binary"]).items()},
            "coarse": {k: int(v) for k, v in Counter(df["coarse"]).items()},
        },
        "epoch_distribution": {k: int(v) for k, v in Counter(df["epoch"]).items()},
        "tasks": {},
        "top_20_features_coarse": [
            {"name": n, "importance": imp, "std": std}
            for n, imp, std in top_features
        ],
    }

    for task_name, task_results in results.items():
        task_summary = {}
        for model_name, mr in task_results.items():
            task_summary[model_name] = {
                "mean_bal_acc": float(mr["mean_bal_acc"]),
                "std_bal_acc": float(mr["std_bal_acc"]),
                "overall_acc": float(mr["overall_acc"]),
                "overall_bal_acc": float(mr["overall_bal_acc"]),
                "overall_f1": float(mr["overall_f1"]),
                "clip_level_bal_acc": float(mr["clip_level_bal_acc"]),
                "fold_metrics": [float(x) for x in mr["fold_metrics"]],
            }
        summary["tasks"][task_name] = task_summary

    summary_path = OUTPUT_DIR / "results_summary_v11.json"
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"  Summary saved: {summary_path}")

    # Best results
    print(f"\n{'=' * 70}")
    print("FINAL RESULTS SUMMARY (v11 Enhanced YOLO)")
    print("=" * 70)
    for task_name, task_results in results.items():
        if not task_results:
            continue
        best_name = max(task_results, key=lambda k: task_results[k]["mean_bal_acc"])
        best = task_results[best_name]
        print(f"  {task_name:12s}: {best_name:15s} BalAcc={best['mean_bal_acc']:.3f} "
              f"+-{best['std_bal_acc']:.3f}  Acc={best['overall_acc']:.3f}  "
              f"F1={best['overall_f1']:.3f}  ClipBA={best['clip_level_bal_acc']:.3f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    t_global = time.time()
    print("=" * 70)
    print("CSI Motion Pipeline v11 (Enhanced YOLO Labels)")
    print("  Enhanced YOLO: gamma 0.3 + CLAHE + denoise -> +9.9% detection")
    print("  person_count_best = max(original, enhanced)")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Phase 1-2: Build dataset
    df, feature_cols = build_dataset()

    # Phase 4: Train models
    results = train_and_evaluate(df, feature_cols)

    # Phase 5: Epoch-specific
    epoch_specific_evaluation(df, feature_cols, results)

    # Phase 6: Feature importance
    top_features = analyze_feature_importance(df, feature_cols, results)

    # Phase 7: Save
    save_results(df, feature_cols, results, top_features)

    elapsed = time.time() - t_global
    print(f"\nTotal runtime: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    print("Done.")


if __name__ == "__main__":
    main()
