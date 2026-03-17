#!/usr/bin/env python3
"""
V10 CSI Motion Pipeline — Corrected Ground Truth

Uses ALL known facts + YOLO per-frame analysis to build accurate annotations:

KNOWN FACTS:
- Session 1 (20:13-20:19): 3-4 people in garage for tests, then 2-3 for freeform
- Session 1 long capture (20:30-21:28): User alone in garage entire time.
  Manual annotation confirmed: chunk1=1p, chunk9=1p→exit at ~240s, chunk11=1p.
  YOLO confirms person detected in at least some frames of ALL chunks 1-12.
  Therefore ALL chunks 2-8, 10, 12 = 1 person present.
- Session 3 (22:11-22:13): 1 chunk, abort. User in garage.
- Session 3 (22:12-22:21): 9 chunks 1min each. User recording from phone = in garage.
  YOLO sees person in 52-60/60 frames per chunk (high detection rate).
- Empty garage (22:32): 3 min, nobody inside. CSI-only.

YOLO USAGE:
- Per-frame motion_score to classify walking vs static WITHIN each chunk
- motion_score > 0.015 = walking frame, else static
- NOT used for person count (unreliable in dark)
"""

import gzip, json, base64, os, sys, time
import numpy as np
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = PROJECT / "temp" / "captures"
OUTPUT_DIR = PROJECT / "output"

# ── Load YOLO per-frame motion scores ──────────────────────────────────────

def load_yolo_motion_timeline():
    """Load per-frame motion scores from YOLO results."""
    yolo_path = OUTPUT_DIR / "yolo_person_detection_results.json"
    if not yolo_path.exists():
        return {}
    d = json.load(open(yolo_path))
    timelines = {}
    for label, r in d.get("results", {}).items():
        frames = r.get("frames", [])
        if frames:
            timelines[label] = [(f["sec"], f.get("motion_score", 0)) for f in frames]
    return timelines

YOLO_MOTION = load_yolo_motion_timeline()

def get_motion_at(label, t_sec, window_sec=5):
    """Determine if motion or static at time t using YOLO frame data."""
    timeline = YOLO_MOTION.get(label, [])
    if not timeline:
        return "walking"  # default if no YOLO data

    # Find frames within the window
    scores = [ms for ts, ms in timeline if abs(ts - t_sec) <= window_sec]
    if not scores:
        # Nearest frame
        scores = [ms for ts, ms in timeline]
        if not scores:
            return "walking"

    avg_motion = np.mean(scores)
    return "walking" if avg_motion > 0.015 else "static"


# ── Build ground truth from known facts ────────────────────────────────────

def build_annotations():
    """Build comprehensive annotations using all known facts."""
    annotations = {}

    # ── Multi-person tests (20:13-20:19) ──
    annotations["three_person_static_test_20260317_201352"] = [
        (0, 22, 3, "static"),
    ]
    annotations["four_person_static_test_20260317_201452"] = [
        (0, 22, 4, "static"),
    ]
    annotations["multi_person_freeform_20260317_201710"] = [
        (0, 62, 3, "walking"),
    ]
    annotations["multi_person_freeform_long_20260317_201856"] = [
        (0, 122, 2, "walking"),
    ]

    # ── Session 1 long capture (20:30-21:28) — 1 person entire time ──
    # Manual annotation for chunk 1 (detailed segments)
    annotations["longcap_chunk0001_20260317_203020"] = [
        (0, 40, 1, "walking"),
        (40, 140, 1, "static"),
        (140, 190, 1, "walking"),
        (190, 300, 1, "static"),
    ]

    # Chunks 2-8: 1 person, use YOLO motion to determine walking/static per 5s window
    for i in range(2, 9):
        ts_map = {
            2: "203523", 3: "204025", 4: "204527",
            5: "205029", 6: "205531", 7: "210033", 8: "210535",
        }
        label = f"longcap_chunk{i:04d}_20260317_{ts_map[i]}"
        annotations[label] = []  # Will be filled per-window below

    # Chunk 9: manual annotation (exit event)
    annotations["longcap_chunk0009_20260317_211037"] = [
        (0, 190, 1, "walking"),
        (190, 240, 1, "static"),
        (240, 300, 0, "empty"),
    ]

    # Chunk 10: After chunk 9 exit. YOLO sees person in 10/30 frames.
    # User likely came back. Motion score suggests movement.
    annotations["longcap_chunk0010_20260317_211539"] = []  # Per-window

    # Chunk 11: manual annotation (1 person, mostly static)
    annotations["longcap_chunk0011_20260317_212041"] = [
        (0, 30, 1, "walking"),
        (30, 300, 1, "static"),
    ]

    # Chunk 12: Last chunk (2.5 min). YOLO sees person in 7/16 frames.
    annotations["longcap_chunk0012_20260317_212543"] = []  # Per-window

    # ── Session 3 abort (22:11) ──
    annotations["longcap_chunk0001_20260317_221138"] = [
        (0, 55, 1, "static"),  # YOLO high detection, low motion
    ]

    # ── Session 3 (22:12-22:21) — user with phone in garage ──
    session3_chunks = {
        "longcap_chunk0001_20260317_221250": 60,
        "longcap_chunk0002_20260317_221352": 60,
        "longcap_chunk0003_20260317_221454": 60,
        "longcap_chunk0004_20260317_221556": 60,
        "longcap_chunk0005_20260317_221658": 60,
        "longcap_chunk0006_20260317_221800": 60,
        "longcap_chunk0007_20260317_221902": 60,
        "longcap_chunk0008_20260317_222005": 60,
        "longcap_chunk0009_20260317_222107": 37,
    }
    for label, dur in session3_chunks.items():
        annotations[label] = []  # Per-window, 1 person

    # ── Empty garage (22:32) ──
    annotations["empty_garage_20260317_223236"] = [
        (0, 180, 0, "empty"),
    ]

    return annotations


# ── CSI Feature Extraction ─────────────────────────────────────────────────

def parse_csi(b64):
    raw = base64.b64decode(b64)
    n = min(128, len(raw) // 2)
    if n < 20:
        return None
    iq = np.frombuffer(raw[:n*2], dtype=np.int8).reshape(-1, 2)
    return np.sqrt(iq[:, 0].astype(float)**2 + iq[:, 1].astype(float)**2)


def extract_features(csi_path, window_sec=5):
    by_node = defaultdict(list)
    with gzip.open(str(csi_path), "rt") as f:
        t0 = None
        for line in f:
            try:
                rec = json.loads(line)
            except:
                continue
            ts = rec.get("ts_ns", 0)
            amp = parse_csi(rec.get("payload_b64", ""))
            if amp is None:
                continue
            if t0 is None:
                t0 = ts
            by_node[rec["src_ip"]].append(((ts - t0) / 1e9, amp))

    if not by_node:
        return []

    max_t = max(t for pkts in by_node.values() for t, _ in pkts)
    n_win = int(max_t / window_sec)
    ips = sorted(by_node.keys())[:4]

    baselines = {}
    for ip in ips:
        early = [a.mean() for t, a in by_node[ip] if t < window_sec]
        baselines[ip] = np.mean(early) if early else 1.0

    windows = []
    prev_means = None

    for w in range(n_win):
        ws, we = w * window_sec, (w + 1) * window_sec
        feat = {"t_mid": (ws + we) / 2}
        nmeans, nstds, ntvars = [], [], []

        for ni, ip in enumerate(ips):
            pkts = [(t, a) for t, a in by_node[ip] if ws <= t < we]
            if len(pkts) < 3:
                for k in [f"n{ni}_{s}" for s in ["mean","std","max","range","pps","tvar","norm"]]:
                    feat[k] = 0
                nmeans.append(0); nstds.append(0); ntvars.append(0)
                continue

            amps = np.array([a.mean() for _, a in pkts])
            feat[f"n{ni}_mean"] = float(np.mean(amps))
            feat[f"n{ni}_std"] = float(np.std(amps))
            feat[f"n{ni}_max"] = float(np.max(amps))
            feat[f"n{ni}_range"] = float(np.ptp(amps))
            feat[f"n{ni}_pps"] = len(pkts) / window_sec
            tv = float(np.var(np.diff(amps))) if len(amps) > 1 else 0
            feat[f"n{ni}_tvar"] = tv
            bl = baselines.get(ip, 1.0)
            feat[f"n{ni}_norm"] = float(np.mean(amps) / bl) if bl > 0 else 0

            nmeans.append(np.mean(amps))
            nstds.append(np.std(amps))
            ntvars.append(tv)

        if len(nmeans) >= 2:
            feat["x_mean_std"] = float(np.std(nmeans))
            feat["x_mean_range"] = float(max(nmeans) - min(nmeans))
            feat["x_std_mean"] = float(np.mean(nstds))
            feat["x_tvar_mean"] = float(np.mean(ntvars))
            feat["x_tvar_max"] = float(max(ntvars))
        else:
            for k in ["x_mean_std","x_mean_range","x_std_mean","x_tvar_mean","x_tvar_max"]:
                feat[k] = 0

        all_a = []
        for ip in ips:
            all_a.extend([a.mean() for t, a in by_node[ip] if ws <= t < we])
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / window_sec

        if prev_means and len(nmeans) == len(prev_means):
            for ni in range(len(nmeans)):
                feat[f"n{ni}_delta"] = nmeans[ni] - prev_means[ni]
        else:
            for ni in range(4):
                feat[f"n{ni}_delta"] = 0

        prev_means = list(nmeans)
        windows.append(feat)

    return windows


# ── Main ───────────────────────────────────────────────────────────────────

print("=" * 70)
print("V10 CSI MOTION PIPELINE — CORRECTED GROUND TRUTH")
print("=" * 70)

annotations = build_annotations()
label_map = {"empty": 0, "static": 1, "walking": 2}

all_X, all_y_bin, all_y_3c, all_y_cnt, all_groups = [], [], [], [], []
clip_info = {}

for label, segments in sorted(annotations.items()):
    csi_path = CAPTURE_DIR / f"{label}.ndjson.gz"
    if not csi_path.exists():
        continue

    windows = extract_features(csi_path, window_sec=5)
    if not windows:
        continue

    labeled = 0
    for w in windows:
        t_mid = w.pop("t_mid")

        if segments:
            # Use predefined segments
            matched = None
            for s0, s1, pc, motion in segments:
                if s0 <= t_mid < s1:
                    matched = (pc, motion)
                    break
            if matched is None:
                matched = (segments[-1][2], segments[-1][3])
            pc, motion = matched
        else:
            # Empty segments = 1 person, motion from YOLO
            pc = 1
            motion = get_motion_at(label, t_mid)

        all_X.append(w)
        all_y_bin.append(0 if pc == 0 else 1)
        all_y_3c.append(label_map.get(motion, 1))
        all_y_cnt.append(pc)
        all_groups.append(label)
        labeled += 1

    s0_pc = segments[0][2] if segments else 1
    s0_m = segments[0][3] if segments else "yolo-auto"
    clip_info[label] = (labeled, s0_pc, s0_m)
    print(f"  {label[:55]:55s} | {labeled:4d}w | p={s0_pc} | {s0_m}")

print(f"\nTotal: {len(all_X)} windows, {len(clip_info)} clips")

# Convert
feat_names = sorted(all_X[0].keys())
X = np.array([[f.get(k, 0) for k in feat_names] for f in all_X])
y_bin = np.array(all_y_bin)
y_3c = np.array(all_y_3c)
y_cnt = np.array(all_y_cnt)
groups = np.array(all_groups)
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

print(f"Features: {X.shape[1]}")
print(f"Binary: empty={np.sum(y_bin==0)}, present={np.sum(y_bin==1)}")
print(f"3-class: empty={np.sum(y_3c==0)}, static={np.sum(y_3c==1)}, motion={np.sum(y_3c==2)}")
uc = sorted(set(y_cnt))
print(f"Count: " + ", ".join(f"{c}p={np.sum(y_cnt==c)}" for c in uc))

# ── Train ──────────────────────────────────────────────────────────────────

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix
import pickle

n_splits = min(5, len(set(groups)))

for task, y, names in [
    ("BINARY (present/empty)", y_bin, ["empty", "present"]),
    ("3-CLASS (empty/static/motion)", y_3c, ["empty", "static", "motion"]),
    ("PERSON COUNT", y_cnt, [f"{c}p" for c in uc]),
]:
    print(f"\n══ {task} ══")
    if len(set(y)) < 2:
        print("  Skip")
        continue
    for nm, clf in [
        ("HGB", HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)),
        ("RF", RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=3, random_state=42)),
    ]:
        try:
            cv = StratifiedGroupKFold(n_splits=n_splits)
            scores = cross_val_score(clf, X, y, cv=cv, groups=groups, scoring="balanced_accuracy")
            print(f"  {nm}: BalAcc = {scores.mean():.4f} (+/- {scores.std():.4f})")
        except Exception as e:
            print(f"  {nm}: FAILED — {e}")

# Final
print("\n══ Final models ══")
models = {}
for task, y in [("binary", y_bin), ("class3", y_3c), ("count", y_cnt)]:
    clf = HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)
    clf.fit(X, y)
    models[task] = clf
    print(f"  {task}: train BalAcc = {balanced_accuracy_score(y, clf.predict(X)):.4f}")

print("\n── 3-class report ──")
print(classification_report(y_3c, models["class3"].predict(X), target_names=["empty","static","motion"]))

if hasattr(models["class3"], "feature_importances_"):
    imp = models["class3"].feature_importances_
    idx = np.argsort(imp)[::-1][:10]
    print("── Top 10 features ──")
    for i in idx:
        print(f"  {feat_names[i]:25s} {imp[i]:.4f}")

# Save
stamp = time.strftime("%Y%m%d_%H%M%S")
rp = OUTPUT_DIR / f"v10_corrected_gt_results_{stamp}.json"
mp = OUTPUT_DIR / f"v10_corrected_gt_model_{stamp}.pkl"

results = {
    "v": "10",
    "windows": len(all_X),
    "clips": len(clip_info),
    "features": len(feat_names),
    "binary_dist": {"empty": int(np.sum(y_bin==0)), "present": int(np.sum(y_bin==1))},
    "class3_dist": {"empty": int(np.sum(y_3c==0)), "static": int(np.sum(y_3c==1)), "motion": int(np.sum(y_3c==2))},
    "count_dist": {str(c): int(np.sum(y_cnt==c)) for c in uc},
}

with open(rp, "w") as f:
    json.dump(results, f, indent=2)
with open(mp, "wb") as f:
    pickle.dump({"models": models, "feature_names": feat_names}, f)

print(f"\nResults: {rp}")
print(f"Model: {mp}")
print("DONE")
