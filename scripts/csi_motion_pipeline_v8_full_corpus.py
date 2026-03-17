#!/usr/bin/env python3
"""
V8 CSI Motion Pipeline — Full Corpus with Combined Ground Truth

Combines all annotation sources:
1. Manual human annotations (highest priority, most accurate)
2. Scripted captures with known person_count (from run_session scripts)
3. YOLO detections (noisy but available for all video clips)
4. Older garage_ceiling_v2 scripted clips with known labels

Also adds all CSI-only captures (no video) that have scripted labels.
"""

import gzip, json, base64, glob, os, sys, time
import numpy as np
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = PROJECT / "temp" / "captures"
OUTPUT_DIR = PROJECT / "output"

# ── 1. Manual annotations (human-verified, highest quality) ────────────────

MANUAL_ANNOTATIONS = {
    "multi_person_freeform_long_20260317_201856": [
        (0, 122, 2, "walking"),
    ],
    "multi_person_freeform_20260317_201710": [
        (0, 62, 3, "walking"),
    ],
    "three_person_static_test_20260317_201352": [
        (0, 22, 3, "static"),
    ],
    "four_person_static_test_20260317_201452": [
        (0, 22, 4, "static"),
    ],
    "longcap_chunk0001_20260317_203020": [
        (0, 40, 1, "walking"),
        (40, 140, 1, "static"),
        (140, 190, 1, "walking"),
        (190, 300, 1, "static"),
    ],
    "longcap_chunk0009_20260317_211037": [
        (0, 190, 1, "walking"),
        (190, 240, 1, "static"),
        (240, 300, 0, "empty"),
    ],
    "longcap_chunk0011_20260317_212041": [
        (0, 30, 1, "walking"),
        (30, 300, 1, "static"),
    ],
    # ── Session 1 (20:30-21:28): chunks 2-8, 10, 12 handled by YOLO ──
    # Chunk 1 has detailed manual annotation above.
    # Chunks 2-8: user present but exact motion unknown → let YOLO decide
    # (with fixed trust: max_count > 0 → present)
    # Chunk 9 has detailed manual annotation above (exit at ~240s).
    # Chunk 10: user LEFT during chunk 9, known empty
    "longcap_chunk0010_20260317_211539": [(0, 300, 0, "empty")],
    # Chunk 11 has detailed manual annotation above (user came back).
    # Chunk 12: user in garage, sitting/standing.
    "longcap_chunk0012_20260317_212543": [(0, 155, 1, "static")],
    # ── Session 2 (22:12-22:21): handled by YOLO where available ──
    "longcap_chunk0001_20260317_221250": [(0, 60, 1, "walking")],
    # Empty garage recording (3 minutes, nobody inside)
    "empty_garage_20260317_223236": [
        (0, 180, 0, "empty"),
    ],
    # Session 4 — balanced pack, phone in middle zone, 1 person, no video
    "rec_20260317_232705_clip01_empty_baseline": [(0, 20, 0, "empty")],
    "rec_20260317_232705_clip02_empty_door_open": [(0, 20, 0, "empty")],
    "rec_20260317_232705_clip03_empty_settled": [(0, 20, 0, "empty")],
    "rec_20260317_232705_clip04_stand_center": [(0, 20, 1, "static")],
    "rec_20260317_232705_clip05_stand_near_exit": [(0, 20, 1, "static")],
    "rec_20260317_232705_clip06_stand_deep": [(0, 20, 1, "static")],
    "rec_20260317_232705_clip07_walk_slow": [(0, 25, 1, "walking")],
    "rec_20260317_232705_clip08_walk_normal": [(0, 25, 1, "walking")],
    "rec_20260317_232705_clip09_walk_around": [(0, 25, 1, "walking")],
    "rec_20260317_232705_clip10_enter_walk_stand": [
        (0, 8, 0, "empty"), (8, 18, 1, "walking"), (18, 25, 1, "static"),
    ],
    "rec_20260317_232705_clip11_enter_exit_fast": [
        (0, 3, 0, "empty"), (3, 10, 1, "walking"), (10, 15, 0, "empty"),
    ],
    "rec_20260317_232705_clip12_enter_stay": [
        (0, 5, 0, "empty"), (5, 15, 1, "walking"), (15, 25, 1, "static"),
    ],
}

# ── 2. Scripted capture labels ─────────────────────────────────────────────

def load_scripted_labels():
    """Load person_count and motion from summary.json step_name."""
    labels = {}
    for sf in sorted(CAPTURE_DIR.glob("*.summary.json")):
        try:
            d = json.load(open(sf))
            label = d.get("label", "")
            step = d.get("step_name", "")
            pc = d.get("person_count_expected", -1)
            dur = d.get("duration_sec", 0)
            sources = d.get("source_count", 0)

            if sources < 3 or dur < 5:
                continue

            # Skip if already in manual annotations
            if label in MANUAL_ANNOTATIONS:
                continue

            if pc >= 0:
                # Has explicit person count
                if "empty" in step:
                    motion = "empty"
                elif "stand" in step or "static" in step or "still" in step:
                    motion = "static"
                elif "walk" in step or "motion" in step or "fast" in step:
                    motion = "walking"
                elif "entry" in step or "exit" in step:
                    motion = "walking"
                elif "breathing" in step or "breath" in step:
                    motion = "static"
                elif "sit" in step:
                    motion = "static"
                else:
                    motion = "static" if pc > 0 else "empty"

                labels[label] = [(0, dur, pc, motion)]
        except:
            continue
    return labels


# ── 3. YOLO-based labels for remaining unlabeled clips ─────────────────────

def load_yolo_labels():
    """Load YOLO detections and create approximate labels."""
    yolo_path = OUTPUT_DIR / "yolo_person_detection_results.json"
    if not yolo_path.exists():
        return {}

    d = json.load(open(yolo_path))
    results = d.get("results", {})
    labels = {}

    for label, r in results.items():
        if label in MANUAL_ANNOTATIONS:
            continue

        frames = r.get("frames", [])
        if not frames:
            continue

        # RULE: In dark garage, YOLO misses static people. Only trust empty
        # when max_count==0 (no person detected in ANY frame).
        counts = [f.get("person_count", 0) for f in frames]
        max_count = max(counts) if counts else 0
        median_count = int(np.median(counts))

        # If YOLO ever saw a person, room is NOT empty
        if max_count > 0:
            effective_count = max(median_count, 1)  # at least 1 person
        else:
            effective_count = 0  # truly empty — YOLO never saw anyone

        # Motion: only trust if sufficient data
        motion_scores = [f.get("motion_score", 0) for f in frames if "motion_score" in f]
        avg_motion = np.mean(motion_scores) if motion_scores else 0

        if effective_count == 0:
            motion = "empty"
        elif avg_motion > 0.04:
            motion = "walking"
        else:
            motion = "static"

        median_count = effective_count

        # Get duration from summary
        summary_path = CAPTURE_DIR / f"{label}.summary.json"
        dur = 300  # default
        if summary_path.exists():
            try:
                dur = json.load(open(summary_path)).get("duration_sec", 300)
            except:
                pass

        labels[label] = [(0, dur, median_count, motion)]

    return labels


# ── CSI Feature Extraction ─────────────────────────────────────────────────

CSI_HEADER = 20  # skip first 20 bytes of payload
ACTIVE_SC = np.array(list(range(6, 59)) + list(range(70, 123)))  # 106 active subcarriers


def parse_csi_payload(b64):
    """Extract amplitude AND phase from CSI payload (full subcarrier spectrum)."""
    raw = base64.b64decode(b64)
    n_bytes = len(raw)
    if n_bytes < CSI_HEADER + 40:  # need at least 20 IQ pairs
        return None, None
    iq_bytes = raw[CSI_HEADER:CSI_HEADER + 256]  # 128 IQ pairs max
    n_sub = len(iq_bytes) // 2
    if n_sub < 20:
        return None, None
    iq = np.frombuffer(iq_bytes[:n_sub*2], dtype=np.int8).reshape(-1, 2)
    i_v = iq[:, 0].astype(np.float32)
    q_v = iq[:, 1].astype(np.float32)
    amp = np.sqrt(i_v**2 + q_v**2)
    phase = np.arctan2(q_v, i_v)
    return amp, phase


# Global empty-room baseline (computed from empty clips)
_empty_baselines = {}


def compute_empty_baseline(csi_path):
    """Compute per-node amplitude baseline from an empty-room clip."""
    baselines = {}
    with gzip.open(str(csi_path), "rt") as f:
        node_amps = defaultdict(list)
        for line in f:
            try:
                rec = json.loads(line)
            except:
                continue
            amp, _ = parse_csi_payload(rec.get("payload_b64", ""))
            if amp is None:
                continue
            ip = rec.get("src_ip", "")
            if len(amp) >= len(ACTIVE_SC):
                node_amps[ip].append(amp[ACTIVE_SC[:min(len(amp), len(ACTIVE_SC))]])
    for ip, amps in node_amps.items():
        if len(amps) >= 10:
            mat = np.array(amps[:300], dtype=np.float32)
            baselines[ip] = {
                "mean": mat.mean(axis=0),
                "std": mat.std(axis=0) + 1e-6,
            }
    return baselines


def extract_features(csi_path, window_sec=5):
    """Extract RICH CSI features per window (v12 enhanced: ~80 features)."""
    packets_by_node = defaultdict(list)

    with gzip.open(str(csi_path), "rt") as f:
        first_ts = None
        for line in f:
            try:
                rec = json.loads(line)
            except:
                continue
            ts_ns = rec.get("ts_ns", 0)
            ip = rec.get("src_ip", "")
            payload = rec.get("payload_b64", "")
            amp, phase = parse_csi_payload(payload)
            if amp is None:
                continue
            if first_ts is None:
                first_ts = ts_ns
            t_sec = (ts_ns - first_ts) / 1e9
            packets_by_node[ip].append((t_sec, amp, phase))

    if not packets_by_node:
        return []

    all_times = [t for pkts in packets_by_node.values() for t, _, _ in pkts]
    max_t = max(all_times)
    n_windows = int(max_t / window_sec)
    node_ips = sorted(packets_by_node.keys())

    # Per-clip baseline (first window)
    clip_baselines = {}
    for ip in node_ips:
        early = [a.mean() for t, a, _ in packets_by_node[ip] if t < window_sec]
        clip_baselines[ip] = np.mean(early) if early else 1.0

    windows = []
    prev_node_means = None

    for w in range(n_windows):
        t_start = w * window_sec
        t_end = t_start + window_sec

        feat = {"t_mid": (t_start + t_end) / 2}
        node_means = []
        node_stds = []
        node_vars = []
        node_diff1_energies = []
        node_doppler_means = []
        node_bldev_means = []

        for ni, ip in enumerate(node_ips[:4]):
            pkts = [(t, a, p) for t, a, p in packets_by_node[ip] if t_start <= t < t_end]

            if len(pkts) < 3:
                for key in [f"n{ni}_mean", f"n{ni}_std", f"n{ni}_max", f"n{ni}_range",
                           f"n{ni}_pps", f"n{ni}_tvar", f"n{ni}_norm",
                           f"n{ni}_diff1", f"n{ni}_diff1_max",
                           f"n{ni}_doppler", f"n{ni}_bldev",
                           f"n{ni}_tvar_lo", f"n{ni}_tvar_hi",
                           f"n{ni}_zcr", f"n{ni}_kurtosis"]:
                    feat[key] = 0
                node_means.append(0)
                node_stds.append(0)
                node_vars.append(0)
                node_diff1_energies.append(0)
                node_doppler_means.append(0)
                node_bldev_means.append(0)
                continue

            # Full amplitude matrix (n_pkts x n_sub) — pad/trim to 128
            target_len = 128
            amp_list = []
            phase_list = []
            for _, a, p in pkts:
                if len(a) >= target_len:
                    amp_list.append(a[:target_len])
                    phase_list.append(p[:target_len])
                else:
                    amp_list.append(np.pad(a, (0, target_len - len(a))))
                    phase_list.append(np.pad(p, (0, target_len - len(p))))
            amp_mat = np.array(amp_list, dtype=np.float32)
            phase_mat = np.array(phase_list, dtype=np.float32)

            # Mean amplitude per packet
            amps = amp_mat.mean(axis=1)

            # === ORIGINAL FEATURES (7) ===
            feat[f"n{ni}_mean"] = float(np.mean(amps))
            feat[f"n{ni}_std"] = float(np.std(amps))
            feat[f"n{ni}_max"] = float(np.max(amps))
            feat[f"n{ni}_range"] = float(np.ptp(amps))
            feat[f"n{ni}_pps"] = len(pkts) / window_sec
            tvar = float(np.var(np.diff(amps))) if len(amps) > 1 else 0
            feat[f"n{ni}_tvar"] = tvar
            bl = clip_baselines.get(ip, 1.0)
            feat[f"n{ni}_norm"] = float(np.mean(amps) / bl) if bl > 0 else 0

            # === NEW: First-diff energy (2) ===
            diff1 = np.abs(np.diff(amps))
            feat[f"n{ni}_diff1"] = float(np.mean(diff1)) if len(diff1) > 0 else 0
            feat[f"n{ni}_diff1_max"] = float(np.max(diff1)) if len(diff1) > 0 else 0

            # === NEW: Phase/Doppler (1) ===
            doppler_val = 0
            if len(pkts) >= 6 and phase_mat.shape[1] >= 20:
                n_sc = min(phase_mat.shape[1], len(ACTIVE_SC))
                ph_active = phase_mat[:, :n_sc]
                ph_unwrap = np.unwrap(ph_active, axis=0)
                ph_rate = np.abs(np.diff(ph_unwrap, axis=0))
                doppler_val = float(ph_rate.mean())
            feat[f"n{ni}_doppler"] = doppler_val

            # === NEW: Baseline deviation from empty room (1) ===
            bldev = 0
            if ip in _empty_baselines:
                bl_data = _empty_baselines[ip]
                n_sc = min(amp_mat.shape[1], len(bl_data["mean"]))
                win_mean = amp_mat[:, :n_sc].mean(axis=0)
                deviation = np.abs(win_mean - bl_data["mean"][:n_sc]) / bl_data["std"][:n_sc]
                bldev = float(deviation.mean())
            feat[f"n{ni}_bldev"] = bldev

            # === NEW: Band-split temporal variance (2) ===
            if amp_mat.shape[1] >= 60:
                tv_full = amp_mat.var(axis=0)
                feat[f"n{ni}_tvar_lo"] = float(tv_full[:30].mean())
                feat[f"n{ni}_tvar_hi"] = float(tv_full[30:60].mean())
            else:
                feat[f"n{ni}_tvar_lo"] = tvar
                feat[f"n{ni}_tvar_hi"] = tvar

            # === NEW: Zero crossing rate & kurtosis (2) ===
            if len(amps) > 3:
                diff_sign = np.diff(np.sign(np.diff(amps)))
                feat[f"n{ni}_zcr"] = float(np.mean(np.abs(diff_sign) > 0))
                from scipy.stats import kurtosis as sp_kurtosis
                feat[f"n{ni}_kurtosis"] = float(sp_kurtosis(amps))
            else:
                feat[f"n{ni}_zcr"] = 0
                feat[f"n{ni}_kurtosis"] = 0

            node_means.append(np.mean(amps))
            node_stds.append(np.std(amps))
            node_vars.append(tvar)
            node_diff1_energies.append(feat[f"n{ni}_diff1"])
            node_doppler_means.append(doppler_val)
            node_bldev_means.append(bldev)

        # === Cross-node features (original 5 + new 4) ===
        if len(node_means) >= 2:
            feat["x_mean_std"] = float(np.std(node_means))
            feat["x_mean_range"] = float(max(node_means) - min(node_means))
            feat["x_std_mean"] = float(np.mean(node_stds))
            feat["x_tvar_mean"] = float(np.mean(node_vars))
            feat["x_tvar_max"] = float(max(node_vars))
            # NEW cross-node
            feat["x_diff1_mean"] = float(np.mean(node_diff1_energies))
            feat["x_doppler_mean"] = float(np.mean(node_doppler_means))
            feat["x_bldev_mean"] = float(np.mean(node_bldev_means))
            feat["x_bldev_max"] = float(max(node_bldev_means))
        else:
            for k in ["x_mean_std", "x_mean_range", "x_std_mean", "x_tvar_mean",
                      "x_tvar_max", "x_diff1_mean", "x_doppler_mean",
                      "x_bldev_mean", "x_bldev_max"]:
                feat[k] = 0

        # === Aggregate (3) ===
        all_amps_in_window = []
        for ip in node_ips[:4]:
            all_amps_in_window.extend([a.mean() for t, a, _ in packets_by_node[ip]
                                       if t_start <= t < t_end])

        if all_amps_in_window:
            feat["agg_mean"] = float(np.mean(all_amps_in_window))
            feat["agg_std"] = float(np.std(all_amps_in_window))
            feat["agg_pps"] = len(all_amps_in_window) / window_sec
        else:
            feat["agg_mean"] = 0
            feat["agg_std"] = 0
            feat["agg_pps"] = 0

        # === Temporal context (4) ===
        if prev_node_means is not None and len(node_means) == len(prev_node_means):
            for ni in range(min(4, len(node_means))):
                feat[f"n{ni}_delta"] = node_means[ni] - prev_node_means[ni]
        else:
            for ni in range(4):
                feat[f"n{ni}_delta"] = 0

        prev_node_means = list(node_means)
        windows.append(feat)

    return windows


# ── Main ───────────────────────────────────────────────────────────────────

print("=" * 60)
print("V8 CSI MOTION PIPELINE — FULL CORPUS")
print("=" * 60)

# Load all annotation sources
scripted = load_scripted_labels()

# YOLO RE-ENABLED with fixed trust logic:
# max_count > 0 → present (not empty). median=0 alone doesn't mean empty.
yolo = load_yolo_labels()

# Merge with priority: manual > scripted > yolo
all_annotations = {}
all_annotations.update(yolo)       # lowest priority
all_annotations.update(scripted)   # medium priority
all_annotations.update(MANUAL_ANNOTATIONS)  # highest priority

# Pick up any NEW scripted captures (e.g. from record.sh) that have
# person_count_expected set and aren't in manual annotations yet.
for sf in sorted(CAPTURE_DIR.glob("*.summary.json")):
    try:
        d = json.load(open(sf))
        label = d.get("label", "")
        if label in all_annotations:
            continue
        sources = d.get("source_count", 0)
        dur = d.get("duration_sec", 0)
        pc = d.get("person_count_expected", -1)
        step = d.get("step_name", "")
        if sources < 3 or dur < 10 or pc < 0:
            continue
        # Only use clips with known person_count from record.sh
        if "empty" in step:
            motion = "empty"
        elif "stand" in step or "static" in step:
            motion = "static"
        elif "walk" in step or "motion" in step or "fast" in step:
            motion = "walking"
        elif "entry" in step or "exit" in step:
            motion = "walking"
        else:
            motion = "static" if pc > 0 else "empty"
        all_annotations[label] = [(0, dur, pc, motion)]
    except:
        continue

n_auto = len(all_annotations) - len(MANUAL_ANNOTATIONS) - len(scripted) - len(yolo)
print(f"\nAnnotation sources:")
print(f"  Manual: {len(MANUAL_ANNOTATIONS)} clips")
print(f"  Scripted: {len(scripted)} clips")
print(f"  YOLO (fixed trust): {len(yolo)} clips")
print(f"  Auto (record.sh): {max(0, n_auto)} clips")
print(f"  Total unique: {len(all_annotations)} clips")

# Build empty-room baseline from known empty clips
print("\n── Computing empty-room baselines ──")
empty_clips = [l for l, segs in all_annotations.items()
               if all(s[3] == "empty" for s in segs)]
for ec in empty_clips:
    ec_path = CAPTURE_DIR / f"{ec}.ndjson.gz"
    if ec_path.exists():
        bl = compute_empty_baseline(ec_path)
        for ip, data in bl.items():
            if ip not in _empty_baselines:
                _empty_baselines[ip] = data
                print(f"  Baseline from {ec}: {ip} ({len(data['mean'])} subcarriers)")
print(f"  Baselines: {len(_empty_baselines)} nodes")

# Build dataset
print("\n── Building dataset ──")

all_X = []
all_y_binary = []  # 0=empty, 1=present
all_y_3class = []  # 0=empty, 1=static, 2=motion
all_y_count = []
all_groups = []
label_source = {}  # track annotation source per clip

label_map = {"empty": 0, "static": 1, "walking": 2}

processed = 0
for label, segments in sorted(all_annotations.items()):
    csi_path = CAPTURE_DIR / f"{label}.ndjson.gz"
    if not csi_path.exists():
        continue

    windows = extract_features(csi_path, window_sec=5)
    if not windows:
        continue

    # Determine source
    if label in MANUAL_ANNOTATIONS:
        source = "manual"
    elif label in scripted:
        source = "scripted"
    else:
        source = "auto"

    labeled = 0
    for w in windows:
        t_mid = w.pop("t_mid")

        # Find matching segment
        matched_seg = None
        for seg_start, seg_end, pc, motion in segments:
            if seg_start <= t_mid < seg_end:
                matched_seg = (pc, motion)
                break

        if matched_seg is None:
            # Use first segment as fallback
            matched_seg = (segments[0][2], segments[0][3])

        pc, motion = matched_seg
        all_X.append(w)
        all_y_binary.append(0 if pc == 0 else 1)
        all_y_3class.append(label_map.get(motion, 1))
        all_y_count.append(pc)
        all_groups.append(label)
        labeled += 1

    label_source[label] = source
    processed += 1
    print(f"  [{source:8s}] {label[:50]:50s} | {labeled:4d} win | p={segments[0][2]} | {segments[0][3]}")

print(f"\nProcessed: {processed} clips, {len(all_X)} windows")

if len(all_X) < 30:
    print("ERROR: Not enough data")
    sys.exit(1)

# Convert to arrays
feature_names = sorted(all_X[0].keys())
X = np.array([[f.get(k, 0) for k in feature_names] for f in all_X])
y_binary = np.array(all_y_binary)
y_3class = np.array(all_y_3class)
y_count = np.array(all_y_count)
groups = np.array(all_groups)

X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

print(f"\nFeature matrix: {X.shape}")
print(f"Features: {len(feature_names)}")
print(f"Binary: empty={np.sum(y_binary==0)}, present={np.sum(y_binary==1)}")
print(f"3-class: empty={np.sum(y_3class==0)}, static={np.sum(y_3class==1)}, motion={np.sum(y_3class==2)}")
counts_unique = sorted(set(y_count))
print(f"Person count: " + ", ".join(f"{c}p={np.sum(y_count==c)}" for c in counts_unique))
print(f"Clips: {len(set(groups))} (manual={sum(1 for v in label_source.values() if v=='manual')}, scripted={sum(1 for v in label_source.values() if v=='scripted')}, yolo={sum(1 for v in label_source.values() if v not in ('manual','scripted'))})")

# ── Train ──────────────────────────────────────────────────────────────────

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix
import pickle

n_splits = min(5, len(set(groups)))
results = {"v": "8", "timestamp": time.strftime("%Y%m%d_%H%M%S")}

# Binary
print("\n══ BINARY: present vs empty ══")
for name, clf in [
    ("HGB", HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)),
    ("RF", RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=3, random_state=42)),
]:
    try:
        cv = StratifiedGroupKFold(n_splits=n_splits)
        scores = cross_val_score(clf, X, y_binary, cv=cv, groups=groups, scoring="balanced_accuracy")
        print(f"  {name}: BalAcc = {scores.mean():.4f} (+/- {scores.std():.4f})")
        results[f"binary_{name}"] = {"mean": float(scores.mean()), "std": float(scores.std())}
    except Exception as e:
        print(f"  {name}: FAILED — {e}")

# 3-class
print("\n══ 3-CLASS: empty / static / motion ══")
for name, clf in [
    ("HGB", HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)),
    ("RF", RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=3, random_state=42)),
]:
    try:
        cv = StratifiedGroupKFold(n_splits=n_splits)
        scores = cross_val_score(clf, X, y_3class, cv=cv, groups=groups, scoring="balanced_accuracy")
        print(f"  {name}: BalAcc = {scores.mean():.4f} (+/- {scores.std():.4f})")
        results[f"3class_{name}"] = {"mean": float(scores.mean()), "std": float(scores.std())}
    except Exception as e:
        print(f"  {name}: FAILED — {e}")

# Person count
if len(counts_unique) >= 2:
    print("\n══ PERSON COUNT ══")
    for name, clf in [
        ("HGB", HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)),
        ("RF", RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=3, random_state=42)),
    ]:
        try:
            cv = StratifiedGroupKFold(n_splits=n_splits)
            scores = cross_val_score(clf, X, y_count, cv=cv, groups=groups, scoring="balanced_accuracy")
            print(f"  {name}: BalAcc = {scores.mean():.4f} (+/- {scores.std():.4f})")
            results[f"count_{name}"] = {"mean": float(scores.mean()), "std": float(scores.std())}
        except Exception as e:
            print(f"  {name}: FAILED — {e}")

# Final model on all data
print("\n══ Final model (full data) ══")

final_binary = HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)
final_binary.fit(X, y_binary)

final_3class = HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)
final_3class.fit(X, y_3class)

final_count = HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)
final_count.fit(X, y_count)

print(f"  Binary train: {balanced_accuracy_score(y_binary, final_binary.predict(X)):.4f}")
print(f"  3-class train: {balanced_accuracy_score(y_3class, final_3class.predict(X)):.4f}")
print(f"  Count train: {balanced_accuracy_score(y_count, final_count.predict(X)):.4f}")

print("\n── Classification Report (3-class, train) ──")
print(classification_report(y_3class, final_3class.predict(X), target_names=["empty", "static", "motion"]))

print("\n── Confusion Matrix (3-class, train) ──")
cm = confusion_matrix(y_3class, final_3class.predict(X))
print(f"           empty  static  motion")
for i, name in enumerate(["empty", "static", "motion"]):
    print(f"  {name:6s}  {cm[i]}")

# Feature importance
if hasattr(final_3class, 'feature_importances_'):
    imp = final_3class.feature_importances_
    idx = np.argsort(imp)[::-1][:15]
    print("\n── Top 15 Features (3-class) ──")
    for i in idx:
        print(f"  {feature_names[i]:25s} {imp[i]:.4f}")

# Save
stamp = time.strftime("%Y%m%d_%H%M%S")
results.update({
    "total_windows": int(len(all_X)),
    "total_clips": len(set(groups)),
    "features": len(feature_names),
    "feature_names": feature_names,
    "binary_dist": {"empty": int(np.sum(y_binary==0)), "present": int(np.sum(y_binary==1))},
    "class3_dist": {"empty": int(np.sum(y_3class==0)), "static": int(np.sum(y_3class==1)), "motion": int(np.sum(y_3class==2))},
    "count_dist": {str(c): int(np.sum(y_count==c)) for c in counts_unique},
    "annotation_sources": {k: v for k, v in label_source.items()},
})

results_path = OUTPUT_DIR / f"v8_full_corpus_results_{stamp}.json"
model_path = OUTPUT_DIR / f"v8_full_corpus_model_{stamp}.pkl"

with open(results_path, "w") as f:
    json.dump(results, f, indent=2)

with open(model_path, "wb") as f:
    pickle.dump({
        "binary": final_binary,
        "class3": final_3class,
        "count": final_count,
        "feature_names": feature_names,
    }, f)

print(f"\nResults: {results_path}")
print(f"Model: {model_path}")
print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
