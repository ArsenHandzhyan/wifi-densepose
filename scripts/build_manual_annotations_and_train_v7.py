#!/usr/bin/env python3
"""
V7 CSI Motion Pipeline — Manual Annotation Ground Truth

Uses human-verified annotations from visual frame analysis as ground truth.
This breaks the circular labeling problem completely.

Ground truth sources:
- multi_person_freeform_long: 2 people, walking, 122s
- multi_person_freeform: 3 people, walking, 62s
- three_person_static_test: 3 people, static, 22s
- four_person_static_test: 4 people, static, 22s
- longcap_chunk0001: 1 person, mixed, 300s
- longcap_chunk0009: 1->0 person (exit event), 300s
- longcap_chunk0011: 1 person, static, 300s
- longcap empty chunks (no person visible): 0 people
"""

import gzip, json, base64, struct, glob, os, sys, time
import numpy as np
from pathlib import Path
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = PROJECT / "temp" / "captures"
OUTPUT_DIR = PROJECT / "output"

# ── Manual annotations (human-verified from keyframe analysis) ──────────────

MANUAL_ANNOTATIONS = {
    "multi_person_freeform_long_20260317_201856": {
        "person_count": 2,
        "motion_state": "walking",
        "duration": 122,
        "segments": [
            # (start_sec, end_sec, person_count, motion)
            (0, 122, 2, "walking"),
        ]
    },
    "multi_person_freeform_20260317_201710": {
        "person_count": 3,
        "motion_state": "walking",
        "duration": 62,
        "segments": [
            (0, 62, 3, "walking"),
        ]
    },
    "three_person_static_test_20260317_201352": {
        "person_count": 3,
        "motion_state": "static",
        "duration": 22,
        "segments": [
            (0, 22, 3, "static"),
        ]
    },
    "four_person_static_test_20260317_201452": {
        "person_count": 4,
        "motion_state": "static",
        "duration": 22,
        "segments": [
            (0, 22, 4, "static"),
        ]
    },
    "longcap_chunk0001_20260317_203020": {
        "person_count": 1,
        "motion_state": "mixed",
        "duration": 300,
        "segments": [
            (0, 40, 1, "walking"),
            (40, 90, 1, "static"),
            (90, 140, 1, "static"),
            (140, 190, 1, "walking"),
            (190, 240, 1, "static"),
            (240, 290, 1, "walking"),
            (290, 300, 1, "static"),
        ]
    },
    "longcap_chunk0009_20260317_211037": {
        "person_count": 1,
        "motion_state": "mixed",
        "duration": 300,
        "segments": [
            (0, 90, 1, "walking"),
            (90, 190, 1, "walking"),
            (190, 240, 1, "static"),
            (240, 300, 0, "empty"),  # Person exited
        ]
    },
    "longcap_chunk0011_20260317_212041": {
        "person_count": 1,
        "motion_state": "static",
        "duration": 300,
        "segments": [
            (0, 30, 1, "walking"),
            (30, 300, 1, "static"),
        ]
    },
}

# Add scripted captures with known labels
SCRIPTED_LABELS = {}
for sf in sorted(CAPTURE_DIR.glob("*.summary.json")):
    try:
        d = json.load(open(sf))
        label = d.get("label", "")
        step = d.get("step_name", "")
        pc = d.get("person_count_expected", -1)
        if pc < 0:
            continue
        dur = d.get("duration_sec", 0)
        if dur < 5:
            continue
        # Determine motion state from step name
        if "empty" in step:
            motion = "empty"
        elif "stand" in step or "static" in step or "still" in step:
            motion = "static"
        elif "walk" in step or "motion" in step or "fast" in step:
            motion = "walking"
        elif "entry" in step or "exit" in step:
            motion = "walking"
        else:
            continue
        SCRIPTED_LABELS[label] = {
            "person_count": pc,
            "motion_state": motion,
            "duration": dur,
            "segments": [(0, dur, pc, motion)],
        }
    except:
        continue

print(f"Manual annotations: {len(MANUAL_ANNOTATIONS)} clips")
print(f"Scripted annotations: {len(SCRIPTED_LABELS)} clips")

ALL_ANNOTATIONS = {}
ALL_ANNOTATIONS.update(SCRIPTED_LABELS)
ALL_ANNOTATIONS.update(MANUAL_ANNOTATIONS)  # Manual overrides scripted
print(f"Total annotated clips: {len(ALL_ANNOTATIONS)}")


# ── CSI Feature Extraction ─────────────────────────────────────────────────

def parse_csi_payload(b64):
    """Extract amplitude from CSI payload."""
    raw = base64.b64decode(b64)
    if len(raw) < 4:
        return None
    # Try to parse IQ pairs
    n_sub = min(128, len(raw) // 2)
    if n_sub < 20:
        return None
    iq = np.frombuffer(raw[:n_sub*2], dtype=np.int8).reshape(-1, 2)
    amp = np.sqrt(iq[:, 0].astype(float)**2 + iq[:, 1].astype(float)**2)
    return amp


def extract_features_from_capture(csi_path, window_sec=5):
    """Extract CSI features in fixed-size windows."""
    windows = []
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
            amp = parse_csi_payload(payload)
            if amp is None:
                continue
            if first_ts is None:
                first_ts = ts_ns
            t_sec = (ts_ns - first_ts) / 1e9
            packets_by_node[ip].append((t_sec, amp))

    if not packets_by_node:
        return []

    # Determine duration
    all_times = [t for pkts in packets_by_node.values() for t, _ in pkts]
    if not all_times:
        return []
    max_t = max(all_times)
    n_windows = int(max_t / window_sec)

    node_ips = sorted(packets_by_node.keys())

    for w in range(n_windows):
        t_start = w * window_sec
        t_end = t_start + window_sec
        t_mid = (t_start + t_end) / 2

        feat = {}
        feat["t_start"] = t_start
        feat["t_end"] = t_end
        feat["t_mid"] = t_mid

        node_means = []
        node_stds = []
        node_maxs = []
        all_amps = []

        for ni, ip in enumerate(node_ips):
            pkts = [(t, a) for t, a in packets_by_node[ip] if t_start <= t < t_end]
            if len(pkts) < 3:
                # Pad with zeros
                feat[f"n{ni}_mean"] = 0
                feat[f"n{ni}_std"] = 0
                feat[f"n{ni}_max"] = 0
                feat[f"n{ni}_pps"] = 0
                feat[f"n{ni}_amp_range"] = 0
                feat[f"n{ni}_temporal_var"] = 0
                node_means.append(0)
                node_stds.append(0)
                node_maxs.append(0)
                continue

            amps = np.array([a.mean() for _, a in pkts])
            all_amps.extend(amps)

            feat[f"n{ni}_mean"] = float(np.mean(amps))
            feat[f"n{ni}_std"] = float(np.std(amps))
            feat[f"n{ni}_max"] = float(np.max(amps))
            feat[f"n{ni}_pps"] = len(pkts) / window_sec
            feat[f"n{ni}_amp_range"] = float(np.max(amps) - np.min(amps))

            # Temporal variance: variance of consecutive differences
            if len(amps) > 1:
                diffs = np.diff(amps)
                feat[f"n{ni}_temporal_var"] = float(np.var(diffs))
            else:
                feat[f"n{ni}_temporal_var"] = 0

            node_means.append(np.mean(amps))
            node_stds.append(np.std(amps))
            node_maxs.append(np.max(amps))

        # Cross-node features
        if len(node_means) >= 2:
            feat["cross_mean_std"] = float(np.std(node_means))
            feat["cross_max_spread"] = float(max(node_maxs) - min(node_maxs)) if node_maxs else 0
            feat["cross_std_mean"] = float(np.mean(node_stds))
        else:
            feat["cross_mean_std"] = 0
            feat["cross_max_spread"] = 0
            feat["cross_std_mean"] = 0

        # Aggregate
        if all_amps:
            feat["agg_mean"] = float(np.mean(all_amps))
            feat["agg_std"] = float(np.std(all_amps))
            feat["agg_pps_total"] = sum(feat.get(f"n{i}_pps", 0) for i in range(len(node_ips)))
        else:
            feat["agg_mean"] = 0
            feat["agg_std"] = 0
            feat["agg_pps_total"] = 0

        windows.append(feat)

    return windows


# ── Build dataset ──────────────────────────────────────────────────────────

print("\n── Building dataset ──")

all_features = []
all_labels_binary = []  # 0=empty, 1=present
all_labels_3class = []  # 0=empty, 1=static, 2=motion
all_labels_count = []   # person count
all_groups = []         # clip label for CV groups

label_map_3class = {"empty": 0, "static": 1, "walking": 2}

for label, ann in sorted(ALL_ANNOTATIONS.items()):
    csi_path = CAPTURE_DIR / f"{label}.ndjson.gz"
    if not csi_path.exists():
        continue

    windows = extract_features_from_capture(csi_path, window_sec=5)
    if not windows:
        continue

    # Assign labels from segments
    labeled = 0
    for w in windows:
        t_mid = w["t_mid"]
        # Find matching segment
        matched = False
        for seg_start, seg_end, pc, motion in ann["segments"]:
            if seg_start <= t_mid < seg_end:
                # Remove time keys before adding to features
                feat = {k: v for k, v in w.items() if k not in ("t_start", "t_end", "t_mid")}
                all_features.append(feat)
                all_labels_binary.append(0 if pc == 0 else 1)
                all_labels_3class.append(label_map_3class.get(motion, 1))
                all_labels_count.append(pc)
                all_groups.append(label)
                labeled += 1
                matched = True
                break
        if not matched:
            # Use clip-level annotation
            pc = ann["person_count"]
            motion = ann["motion_state"]
            feat = {k: v for k, v in w.items() if k not in ("t_start", "t_end", "t_mid")}
            all_features.append(feat)
            all_labels_binary.append(0 if pc == 0 else 1)
            all_labels_3class.append(label_map_3class.get(motion, 1))
            all_labels_count.append(pc)
            all_groups.append(label)
            labeled += 1

    print(f"  {label[:50]:50s} | {labeled:3d} windows | p={ann['person_count']} | {ann['motion_state']}")

print(f"\nTotal dataset: {len(all_features)} windows, {len(set(all_groups))} clips")

if len(all_features) < 20:
    print("ERROR: Not enough data for training")
    sys.exit(1)

# ── Convert to arrays ──────────────────────────────────────────────────────

feature_names = sorted(all_features[0].keys())
X = np.array([[f.get(k, 0) for k in feature_names] for f in all_features])
y_binary = np.array(all_labels_binary)
y_3class = np.array(all_labels_3class)
y_count = np.array(all_labels_count)
groups = np.array(all_groups)

print(f"Feature matrix: {X.shape}")
print(f"Binary distribution: empty={np.sum(y_binary==0)}, present={np.sum(y_binary==1)}")
print(f"3-class: empty={np.sum(y_3class==0)}, static={np.sum(y_3class==1)}, motion={np.sum(y_3class==2)}")
print(f"Person count: " + ", ".join(f"{c}p={np.sum(y_count==c)}" for c in sorted(set(y_count))))

# ── Train models ──────────────────────────────────────────────────────────

from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import StandardScaler
import pickle

# Replace NaN/inf
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

results = {}

# ── Binary classification ──────────────────────────────────────────────────
print("\n══ BINARY: present vs empty ══")

for name, clf in [
    ("HGB", HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)),
    ("RF", RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)),
]:
    try:
        cv = StratifiedGroupKFold(n_splits=min(5, len(set(groups))))
        scores = cross_val_score(clf, X, y_binary, cv=cv, groups=groups, scoring="balanced_accuracy")
        print(f"  {name}: BalAcc = {scores.mean():.4f} (+/- {scores.std():.4f})")
        results[f"binary_{name}_mean"] = float(scores.mean())
        results[f"binary_{name}_std"] = float(scores.std())
    except Exception as e:
        print(f"  {name}: FAILED — {e}")

# ── 3-class classification ──────────────────────────────────────────────────
print("\n══ 3-CLASS: empty / static / motion ══")

for name, clf in [
    ("HGB", HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)),
    ("RF", RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)),
]:
    try:
        cv = StratifiedGroupKFold(n_splits=min(5, len(set(groups))))
        scores = cross_val_score(clf, X, y_3class, cv=cv, groups=groups, scoring="balanced_accuracy")
        print(f"  {name}: BalAcc = {scores.mean():.4f} (+/- {scores.std():.4f})")
        results[f"3class_{name}_mean"] = float(scores.mean())
        results[f"3class_{name}_std"] = float(scores.std())
    except Exception as e:
        print(f"  {name}: FAILED — {e}")

# ── Person count regression/classification ──────────────────────────────────
print("\n══ PERSON COUNT (0-4) ══")

unique_counts = sorted(set(y_count))
if len(unique_counts) >= 2:
    for name, clf in [
        ("HGB", HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)),
        ("RF", RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)),
    ]:
        try:
            cv = StratifiedGroupKFold(n_splits=min(5, len(set(groups))))
            scores = cross_val_score(clf, X, y_count, cv=cv, groups=groups, scoring="balanced_accuracy")
            print(f"  {name}: BalAcc = {scores.mean():.4f} (+/- {scores.std():.4f})")
            results[f"count_{name}_mean"] = float(scores.mean())
            results[f"count_{name}_std"] = float(scores.std())
        except Exception as e:
            print(f"  {name}: FAILED — {e}")

# ── Train final model on all data and save ──────────────────────────────────
print("\n══ Final model (full data) ══")

best_binary = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)
best_binary.fit(X, y_binary)
y_pred_bin = best_binary.predict(X)
print(f"  Binary train BalAcc: {balanced_accuracy_score(y_binary, y_pred_bin):.4f}")

best_3class = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)
best_3class.fit(X, y_3class)
y_pred_3c = best_3class.predict(X)
print(f"  3-class train BalAcc: {balanced_accuracy_score(y_3class, y_pred_3c):.4f}")

best_count = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, random_state=42)
best_count.fit(X, y_count)
y_pred_cnt = best_count.predict(X)
print(f"  Count train BalAcc: {balanced_accuracy_score(y_count, y_pred_cnt):.4f}")

print("\n  3-class report:")
print(classification_report(y_3class, y_pred_3c, target_names=["empty", "static", "motion"]))

print("\n  Count report:")
print(classification_report(y_count, y_pred_cnt, target_names=[f"{c}p" for c in unique_counts]))

# Feature importance
importances = best_3class.feature_importances_ if hasattr(best_3class, 'feature_importances_') else None
if importances is not None:
    print("\n  Top 10 features (3-class):")
    idx = np.argsort(importances)[::-1][:10]
    for i in idx:
        print(f"    {feature_names[i]:30s} {importances[i]:.4f}")

# ── Save ──────────────────────────────────────────────────────────────────
stamp = time.strftime("%Y%m%d_%H%M%S")
results_path = OUTPUT_DIR / f"v7_manual_gt_results_{stamp}.json"
model_path = OUTPUT_DIR / f"v7_manual_gt_model_{stamp}.pkl"

results.update({
    "total_windows": len(all_features),
    "total_clips": len(set(all_groups)),
    "feature_count": len(feature_names),
    "feature_names": feature_names,
    "binary_distribution": {"empty": int(np.sum(y_binary==0)), "present": int(np.sum(y_binary==1))},
    "class3_distribution": {"empty": int(np.sum(y_3class==0)), "static": int(np.sum(y_3class==1)), "motion": int(np.sum(y_3class==2))},
    "count_distribution": {str(c): int(np.sum(y_count==c)) for c in unique_counts},
    "clips": list(set(all_groups)),
})

with open(results_path, "w") as f:
    json.dump(results, f, indent=2)

with open(model_path, "wb") as f:
    pickle.dump({
        "binary_model": best_binary,
        "class3_model": best_3class,
        "count_model": best_count,
        "feature_names": feature_names,
        "label_map_3class": label_map_3class,
    }, f)

print(f"\nResults: {results_path}")
print(f"Model: {model_path}")
print("Done.")
