#!/usr/bin/env python3
"""
V9 CSI Motion Pipeline — All Sources Combined

Uses ALL available ground truth:
1. Manual human annotations (segment-level, highest quality)
2. clip.json person_count_expected (scripted captures)
3. summary.json person_count_expected (as fallback)
4. YOLO median for remaining unlabeled clips
5. Dedicated empty garage recording

Key improvement over V8: includes 24 pixel8pro clips from clip.json
"""

import gzip, json, base64, glob, os, sys, time
import numpy as np
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = PROJECT / "temp" / "captures"
OUTPUT_DIR = PROJECT / "output"

# ── 1. Manual segment-level annotations ────────────────────────────────────

MANUAL_SEGMENTS = {
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
    "longcap_chunk0001_20260317_221250": [
        (0, 60, 1, "walking"),
    ],
    "empty_garage_20260317_223236": [
        (0, 180, 0, "empty"),
    ],
}

# ── 2. Load ALL clip.json for scripted labels ──────────────────────────────

def load_clip_json_labels():
    """Extract person_count and motion from clip.json files."""
    labels = {}
    for cf in sorted(CAPTURE_DIR.glob("*.clip.json")):
        try:
            d = json.load(open(cf))
            label = d.get("capture_label", "")
            if not label or label in MANUAL_SEGMENTS:
                continue
            pc = d.get("person_count_expected", -1)
            if pc < 0:
                continue
            step = d.get("step_name", "")
            dur = d.get("duration_actual_sec") or d.get("duration_requested_sec", 0)
            if dur < 5:
                # Try to get from summary
                sp = CAPTURE_DIR / f"{label}.summary.json"
                if sp.exists():
                    sd = json.load(open(sp))
                    dur = sd.get("duration_sec", 0)
                    if sd.get("source_count", 0) < 2:
                        continue

            # Infer motion from step name
            if pc == 0:
                motion = "empty"
            elif any(k in step for k in ["empty", "baseline"]):
                motion = "empty" if pc == 0 else "static"
            elif any(k in step for k in ["walk", "motion", "fast", "entry", "exit", "laps", "corridor"]):
                motion = "walking"
            elif any(k in step for k in ["stand", "static", "still", "hold", "squat", "kneel", "lie", "sit", "breath"]):
                motion = "static"
            elif any(k in step for k in ["bend", "reach", "pick", "cycle"]):
                motion = "walking"  # active movement
            elif any(k in step for k in ["door_no_entry"]):
                motion = "empty"  # person near door but not inside
            else:
                motion = "static" if pc > 0 else "empty"

            labels[label] = [(0, max(dur, 10), pc, motion)]
        except:
            continue
    return labels


# ── 3. Load summary.json fallback ─────────────────────────────────────────

def load_summary_labels():
    """Fallback: use summary.json person_count_expected."""
    labels = {}
    for sf in sorted(CAPTURE_DIR.glob("*.summary.json")):
        try:
            d = json.load(open(sf))
            label = d.get("label", "")
            if not label or label in MANUAL_SEGMENTS:
                continue
            pc = d.get("person_count_expected", -1)
            if pc < 0:
                continue
            step = d.get("step_name", "")
            dur = d.get("duration_sec", 0)
            sources = d.get("source_count", 0)
            if sources < 2 or dur < 5:
                continue

            if pc == 0:
                motion = "empty"
            elif "walk" in step or "motion" in step or "fast" in step or "entry" in step:
                motion = "walking"
            else:
                motion = "static"

            labels[label] = [(0, dur, pc, motion)]
        except:
            continue
    return labels


# ── 4. YOLO fallback for remaining ─────────────────────────────────────────

def load_yolo_labels(existing_labels):
    """Use YOLO median for remaining unlabeled clips."""
    yolo_path = OUTPUT_DIR / "yolo_person_detection_results.json"
    if not yolo_path.exists():
        return {}

    d = json.load(open(yolo_path))
    results = d.get("results", {})
    labels = {}

    for label, r in results.items():
        if label in existing_labels or label in MANUAL_SEGMENTS:
            continue

        frames = r.get("frames", [])
        if not frames:
            continue

        counts = [f.get("person_count", 0) for f in frames]
        median_count = int(np.median(counts))
        max_count = max(counts) if counts else 0
        motions = [f.get("motion_score", 0) for f in frames]
        avg_motion = np.mean(motions) if motions else 0

        # Get duration
        sp = CAPTURE_DIR / f"{label}.summary.json"
        dur = 300
        sources = 4
        if sp.exists():
            sd = json.load(open(sp))
            dur = sd.get("duration_sec", 300)
            sources = sd.get("source_count", 0)

        if sources < 2:
            continue

        # IMPORTANT: YOLO is unreliable in dark garage — it often misses
        # static people. Only trust YOLO's "empty" label if max_count is
        # also 0 (never detected anyone in any frame). If YOLO sometimes
        # sees people, assume someone was present throughout.
        if median_count == 0 and max_count == 0:
            motion = "empty"
        elif median_count == 0 and max_count > 0:
            # YOLO sometimes sees people → person was likely there
            median_count = 1
            motion = "static"
        elif avg_motion > 0.04:
            motion = "walking"
        else:
            motion = "static"

        labels[label] = [(0, dur, median_count, motion)]

    return labels


# ── CSI Feature Extraction ─────────────────────────────────────────────────

def parse_csi_payload(b64):
    raw = base64.b64decode(b64)
    if len(raw) < 4:
        return None
    n_sub = min(128, len(raw) // 2)
    if n_sub < 20:
        return None
    iq = np.frombuffer(raw[:n_sub*2], dtype=np.int8).reshape(-1, 2)
    return np.sqrt(iq[:, 0].astype(float)**2 + iq[:, 1].astype(float)**2)


def extract_features(csi_path, window_sec=5):
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
            amp = parse_csi_payload(rec.get("payload_b64", ""))
            if amp is None:
                continue
            if first_ts is None:
                first_ts = ts_ns
            packets_by_node[ip].append(((ts_ns - first_ts) / 1e9, amp))

    if not packets_by_node:
        return []

    all_times = [t for pkts in packets_by_node.values() for t, _ in pkts]
    max_t = max(all_times)
    n_windows = int(max_t / window_sec)
    node_ips = sorted(packets_by_node.keys())[:4]

    # Baseline from first window
    baselines = {}
    for ip in node_ips:
        early = [a.mean() for t, a in packets_by_node[ip] if t < window_sec]
        baselines[ip] = np.mean(early) if early else 1.0

    windows = []
    prev_means = None

    for w in range(n_windows):
        t0, t1 = w * window_sec, (w + 1) * window_sec
        feat = {"t_mid": (t0 + t1) / 2}
        node_means, node_stds, node_tvars = [], [], []

        for ni, ip in enumerate(node_ips):
            pkts = [(t, a) for t, a in packets_by_node[ip] if t0 <= t < t1]

            if len(pkts) < 3:
                for k in [f"n{ni}_{s}" for s in ["mean","std","max","range","pps","tvar","norm"]]:
                    feat[k] = 0
                node_means.append(0); node_stds.append(0); node_tvars.append(0)
                continue

            amps = np.array([a.mean() for _, a in pkts])
            feat[f"n{ni}_mean"] = float(np.mean(amps))
            feat[f"n{ni}_std"] = float(np.std(amps))
            feat[f"n{ni}_max"] = float(np.max(amps))
            feat[f"n{ni}_range"] = float(np.ptp(amps))
            feat[f"n{ni}_pps"] = len(pkts) / window_sec
            feat[f"n{ni}_tvar"] = float(np.var(np.diff(amps))) if len(amps) > 1 else 0
            bl = baselines.get(ip, 1.0)
            feat[f"n{ni}_norm"] = float(np.mean(amps) / bl) if bl > 0 else 0

            node_means.append(np.mean(amps))
            node_stds.append(np.std(amps))
            node_tvars.append(feat[f"n{ni}_tvar"])

        # Cross-node
        if len(node_means) >= 2:
            feat["x_mean_std"] = float(np.std(node_means))
            feat["x_mean_range"] = float(max(node_means) - min(node_means))
            feat["x_std_mean"] = float(np.mean(node_stds))
            feat["x_tvar_mean"] = float(np.mean(node_tvars))
            feat["x_tvar_max"] = float(max(node_tvars))
        else:
            for k in ["x_mean_std","x_mean_range","x_std_mean","x_tvar_mean","x_tvar_max"]:
                feat[k] = 0

        # Aggregate
        all_a = []
        for ip in node_ips:
            all_a.extend([a.mean() for t, a in packets_by_node[ip] if t0 <= t < t1])
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / window_sec

        # Delta from previous
        if prev_means and len(node_means) == len(prev_means):
            for ni in range(len(node_means)):
                feat[f"n{ni}_delta"] = node_means[ni] - prev_means[ni]
        else:
            for ni in range(4):
                feat[f"n{ni}_delta"] = 0

        prev_means = list(node_means)
        windows.append(feat)

    return windows


# ── Main ───────────────────────────────────────────────────────────────────

print("=" * 70)
print("V9 CSI MOTION PIPELINE — ALL SOURCES COMBINED")
print("=" * 70)

# Load all annotation sources with priority
clip_labels = load_clip_json_labels()
summary_labels = load_summary_labels()

# Merge: manual > clip.json > summary.json > yolo
all_annotations = {}
yolo_labels = load_yolo_labels({**clip_labels, **summary_labels})
all_annotations.update(yolo_labels)
all_annotations.update(summary_labels)
all_annotations.update(clip_labels)
all_annotations.update(MANUAL_SEGMENTS)

# Add remaining long capture chunks (user was present)
for sf in sorted(CAPTURE_DIR.glob("longcap_chunk*.summary.json")):
    d = json.load(open(sf))
    label = d.get("label", "")
    if label in all_annotations:
        continue
    dur = d.get("duration_sec", 0)
    sources = d.get("source_count", 0)
    if sources >= 3 and dur >= 10:
        all_annotations[label] = [(0, dur, 1, "walking")]

print(f"\nAnnotation sources:")
print(f"  Manual segments: {len(MANUAL_SEGMENTS)}")
print(f"  clip.json: {len(clip_labels)}")
print(f"  summary.json: {len(summary_labels)}")
print(f"  YOLO fallback: {len(yolo_labels)}")
print(f"  Long capture default: {len(all_annotations) - len(MANUAL_SEGMENTS) - len(clip_labels) - len(summary_labels) - len(yolo_labels)}")
print(f"  Total unique: {len(all_annotations)}")

# Build dataset
print("\n── Building dataset ──")

label_map = {"empty": 0, "static": 1, "walking": 2}
all_X, all_y_bin, all_y_3c, all_y_cnt, all_groups = [], [], [], [], []
source_map = {}

processed = 0
for label, segments in sorted(all_annotations.items()):
    csi_path = CAPTURE_DIR / f"{label}.ndjson.gz"
    if not csi_path.exists():
        continue

    windows = extract_features(csi_path, window_sec=5)
    if not windows:
        continue

    # Determine source
    if label in MANUAL_SEGMENTS:
        src = "manual"
    elif label in clip_labels:
        src = "clip.json"
    elif label in summary_labels:
        src = "summary"
    elif label in yolo_labels:
        src = "yolo"
    else:
        src = "default"

    labeled = 0
    for w in windows:
        t_mid = w.pop("t_mid")
        # Find segment
        matched = None
        for s0, s1, pc, motion in segments:
            if s0 <= t_mid < s1:
                matched = (pc, motion)
                break
        if matched is None:
            matched = (segments[0][2], segments[0][3])

        pc, motion = matched
        all_X.append(w)
        all_y_bin.append(0 if pc == 0 else 1)
        all_y_3c.append(label_map.get(motion, 1))
        all_y_cnt.append(pc)
        all_groups.append(label)
        labeled += 1

    source_map[label] = src
    processed += 1
    pc0 = segments[0][2]
    m0 = segments[0][3]
    print(f"  [{src:8s}] {label[:50]:50s} | {labeled:4d}w | p={pc0} | {m0}")

print(f"\nProcessed: {processed} clips, {len(all_X)} windows")

if len(all_X) < 30:
    print("ERROR: Not enough data")
    sys.exit(1)

# Convert
feature_names = sorted(all_X[0].keys())
X = np.array([[f.get(k, 0) for k in feature_names] for f in all_X])
y_bin = np.array(all_y_bin)
y_3c = np.array(all_y_3c)
y_cnt = np.array(all_y_cnt)
groups = np.array(all_groups)
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

print(f"\nFeature matrix: {X.shape}")
print(f"Binary: empty={np.sum(y_bin==0)}, present={np.sum(y_bin==1)}")
print(f"3-class: empty={np.sum(y_3c==0)}, static={np.sum(y_3c==1)}, motion={np.sum(y_3c==2)}")
uc = sorted(set(y_cnt))
print(f"Person count: " + ", ".join(f"{c}p={np.sum(y_cnt==c)}" for c in uc))

src_counts = defaultdict(int)
for v in source_map.values():
    src_counts[v] += 1
print(f"Sources: " + ", ".join(f"{k}={v}" for k, v in sorted(src_counts.items())))

# ── Train ──────────────────────────────────────────────────────────────────

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix
import pickle

n_splits = min(5, len(set(groups)))
results = {"v": "9", "timestamp": time.strftime("%Y%m%d_%H%M%S")}

for task_name, y, class_names in [
    ("BINARY", y_bin, ["empty", "present"]),
    ("3-CLASS", y_3c, ["empty", "static", "motion"]),
    ("PERSON COUNT", y_cnt, [f"{c}p" for c in uc]),
]:
    print(f"\n══ {task_name} ══")
    if len(set(y)) < 2:
        print("  Skipped (single class)")
        continue

    for name, clf in [
        ("HGB", HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)),
        ("RF", RandomForestClassifier(n_estimators=300, max_depth=8, min_samples_leaf=3, random_state=42)),
    ]:
        try:
            cv = StratifiedGroupKFold(n_splits=n_splits)
            scores = cross_val_score(clf, X, y, cv=cv, groups=groups, scoring="balanced_accuracy")
            mean_s = float(scores.mean())
            std_s = float(scores.std())
            print(f"  {name}: BalAcc = {mean_s:.4f} (+/- {std_s:.4f})")
            results[f"{task_name}_{name}"] = {"mean": mean_s, "std": std_s}
        except Exception as e:
            print(f"  {name}: FAILED — {e}")

# Final models
print("\n══ Final models (full data) ══")
models = {}
for task_name, y, class_names in [
    ("binary", y_bin, ["empty", "present"]),
    ("class3", y_3c, ["empty", "static", "motion"]),
    ("count", y_cnt, [f"{c}p" for c in uc]),
]:
    clf = HistGradientBoostingClassifier(max_depth=5, max_iter=300, learning_rate=0.05, min_samples_leaf=5, random_state=42)
    clf.fit(X, y)
    models[task_name] = clf
    train_ba = balanced_accuracy_score(y, clf.predict(X))
    print(f"  {task_name} train BalAcc: {train_ba:.4f}")

# Reports
print("\n── 3-class Classification Report ──")
print(classification_report(y_3c, models["class3"].predict(X), target_names=["empty", "static", "motion"]))

print("── Confusion Matrix (3-class) ──")
cm = confusion_matrix(y_3c, models["class3"].predict(X))
print(f"            {'empty':>6s} {'static':>6s} {'motion':>6s}")
for i, n in enumerate(["empty", "static", "motion"]):
    print(f"  {n:6s}  {cm[i]}")

# Feature importance
if hasattr(models["class3"], "feature_importances_"):
    imp = models["class3"].feature_importances_
    idx = np.argsort(imp)[::-1][:15]
    print("\n── Top 15 Features ──")
    for i in idx:
        print(f"  {feature_names[i]:25s} {imp[i]:.4f}")

# Save
stamp = time.strftime("%Y%m%d_%H%M%S")
results.update({
    "total_windows": len(all_X),
    "total_clips": len(set(groups)),
    "features": len(feature_names),
    "feature_names": feature_names,
    "binary_dist": {"empty": int(np.sum(y_bin==0)), "present": int(np.sum(y_bin==1))},
    "class3_dist": {"empty": int(np.sum(y_3c==0)), "static": int(np.sum(y_3c==1)), "motion": int(np.sum(y_3c==2))},
    "count_dist": {str(c): int(np.sum(y_cnt==c)) for c in uc},
    "sources": dict(src_counts),
    "clips": list(set(groups)),
})

rp = OUTPUT_DIR / f"v9_all_sources_results_{stamp}.json"
mp = OUTPUT_DIR / f"v9_all_sources_model_{stamp}.pkl"

with open(rp, "w") as f:
    json.dump(results, f, indent=2)
with open(mp, "wb") as f:
    pickle.dump({"models": models, "feature_names": feature_names}, f)

print(f"\nResults: {rp}")
print(f"Model: {mp}")
print("=" * 70)
print("DONE")
