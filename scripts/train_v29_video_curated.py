#!/usr/bin/env python3
"""
V29: CSI model trained with video-curated labels from pipeline.

Uses output/video_curation/labels_compact.csv as label source,
extracts CSI features for matching clips, applies tier-based sample weighting.

Label tiers -> sample weights:
  human_verified: 1.0
  strong_teacher: 0.85
  weak_auto:      0.5
  reject:         0.0 (excluded)
"""
import gzip, json, base64, csv, sys, time
import numpy as np
from pathlib import Path
from collections import defaultdict, Counter

PROJECT = Path(__file__).resolve().parents[1]
CAPTURE_DIR = PROJECT / "temp" / "captures"
CURATION_CSV = PROJECT / "output" / "video_curation" / "labels_compact.csv"
OUTPUT_DIR = PROJECT / "output" / "csi_pipeline_v29_results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TIER_WEIGHTS = {
    "human_verified": 1.0,
    "strong_teacher": 0.85,
    "weak_auto": 0.5,
    "synthetic": 0.3,
    "reject": 0.0,
}

CSI_HEADER = 20
WINDOW_SEC = 5

def parse_csi_payload(b64):
    raw = base64.b64decode(b64)
    if len(raw) < CSI_HEADER + 40:
        return None, None
    iq_bytes = raw[CSI_HEADER:CSI_HEADER + 256]
    n_sub = len(iq_bytes) // 2
    if n_sub < 20:
        return None, None
    iq = np.frombuffer(iq_bytes[:n_sub*2], dtype=np.int8).reshape(-1, 2)
    i_v, q_v = iq[:, 0].astype(np.float32), iq[:, 1].astype(np.float32)
    return np.sqrt(i_v**2 + q_v**2), np.arctan2(q_v, i_v)

def extract_csi_features(csi_path, window_sec=5):
    packets_by_node = defaultdict(list)
    with gzip.open(str(csi_path), "rt") as f:
        first_ts = None
        for line in f:
            try: rec = json.loads(line)
            except: continue
            ts_ns = rec.get("ts_ns", 0)
            ip = rec.get("src_ip", "")
            amp, phase = parse_csi_payload(rec.get("payload_b64", ""))
            if amp is None: continue
            if first_ts is None: first_ts = ts_ns
            t_sec = (ts_ns - first_ts) / 1e9
            packets_by_node[ip].append((t_sec, amp, phase))
    if not packets_by_node: return []

    max_t = max(t for pkts in packets_by_node.values() for t, _, _ in pkts)
    n_windows = int(max_t / window_sec)
    node_ips = sorted(packets_by_node.keys())
    clip_bl = {}
    for ip in node_ips:
        early = [a.mean() for t, a, _ in packets_by_node[ip] if t < window_sec]
        clip_bl[ip] = np.mean(early) if early else 1.0

    windows = []
    prev_feats = None
    for w in range(n_windows):
        t0, t1 = w * window_sec, (w + 1) * window_sec
        feat = {"t_start": t0, "t_end": t1}
        nv = {"mean": [], "std": [], "tvar": [], "diff1": [], "sc_var": []}
        for ni, ip in enumerate(node_ips[:4]):
            pkts = [(t, a, p) for t, a, p in packets_by_node[ip] if t0 <= t < t1]
            pf = f"n{ni}"
            if len(pkts) < 3:
                for k in ["mean","std","max","range","pps","tvar","norm","diff1","diff1_max",
                           "sc_var_mean","sc_var_std","sc_var_max","tvar_lo","tvar_hi","zcr","kurtosis"]:
                    feat[f"{pf}_{k}"] = 0
                for v in nv.values(): v.append(0)
                continue
            amp_list = []
            for _, a, _ in pkts:
                if len(a) >= 128: amp_list.append(a[:128])
                else: amp_list.append(np.pad(a, (0, 128 - len(a))))
            amp_mat = np.array(amp_list, dtype=np.float32)
            amps = amp_mat.mean(axis=1)
            feat[f"{pf}_mean"] = float(np.mean(amps))
            feat[f"{pf}_std"] = float(np.std(amps))
            feat[f"{pf}_max"] = float(np.max(amps))
            feat[f"{pf}_range"] = float(np.ptp(amps))
            feat[f"{pf}_pps"] = len(pkts) / window_sec
            tvar = float(np.var(np.diff(amps))) if len(amps) > 1 else 0
            feat[f"{pf}_tvar"] = tvar
            bl = clip_bl.get(ip, 1.0)
            feat[f"{pf}_norm"] = float(np.mean(amps) / bl) if bl > 0 else 0
            diff1 = np.abs(np.diff(amps))
            feat[f"{pf}_diff1"] = float(np.mean(diff1)) if len(diff1) > 0 else 0
            feat[f"{pf}_diff1_max"] = float(np.max(diff1)) if len(diff1) > 0 else 0
            if amp_mat.shape[1] >= 60:
                sc_v = amp_mat.var(axis=0)
                feat[f"{pf}_sc_var_mean"] = float(sc_v.mean())
                feat[f"{pf}_sc_var_std"] = float(sc_v.std())
                feat[f"{pf}_sc_var_max"] = float(sc_v.max())
                feat[f"{pf}_tvar_lo"] = float(sc_v[:30].mean())
                feat[f"{pf}_tvar_hi"] = float(sc_v[30:60].mean())
            else:
                for k in ["sc_var_mean","sc_var_std","sc_var_max"]: feat[f"{pf}_{k}"] = 0
                feat[f"{pf}_tvar_lo"] = tvar; feat[f"{pf}_tvar_hi"] = tvar
            if len(amps) > 3:
                ds = np.diff(np.sign(np.diff(amps)))
                feat[f"{pf}_zcr"] = float(np.mean(np.abs(ds) > 0))
                from scipy.stats import kurtosis as spk
                feat[f"{pf}_kurtosis"] = float(spk(amps))
            else:
                feat[f"{pf}_zcr"] = 0; feat[f"{pf}_kurtosis"] = 0
            nv["mean"].append(np.mean(amps)); nv["std"].append(np.std(amps))
            nv["tvar"].append(tvar); nv["diff1"].append(feat[f"{pf}_diff1"])
            nv["sc_var"].append(feat[f"{pf}_sc_var_mean"])
        if len(nv["mean"]) >= 2:
            feat["x_mean_std"] = float(np.std(nv["mean"]))
            feat["x_mean_range"] = float(max(nv["mean"]) - min(nv["mean"]))
            feat["x_std_mean"] = float(np.mean(nv["std"]))
            feat["x_tvar_mean"] = float(np.mean(nv["tvar"]))
            feat["x_tvar_max"] = float(max(nv["tvar"]))
            feat["x_diff1_mean"] = float(np.mean(nv["diff1"]))
            feat["x_sc_var_mean"] = float(np.mean(nv["sc_var"]))
            feat["x_corr_mean_std"] = float(np.corrcoef(nv["mean"], nv["std"])[0,1]) if len(nv["mean"])>=3 else 0
        else:
            for k in ["x_mean_std","x_mean_range","x_std_mean","x_tvar_mean",
                      "x_tvar_max","x_diff1_mean","x_sc_var_mean","x_corr_mean_std"]:
                feat[k] = 0
        all_a = [a.mean() for ip in node_ips[:4] for t,a,_ in packets_by_node[ip] if t0<=t<t1]
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / window_sec if all_a else 0
        if prev_feats:
            for ni in range(min(4, len(nv["mean"]))):
                feat[f"n{ni}_delta"] = nv["mean"][ni] - prev_feats.get(f"n{ni}_mean", 0)
        else:
            for ni in range(4): feat[f"n{ni}_delta"] = 0
        prev_feats = feat.copy()
        windows.append(feat)
    return windows

# ── Main ──
print("=" * 70)
print("V29: CSI MODEL WITH VIDEO-CURATED LABELS")
print("=" * 70)

# Load curated labels
labels_by_clip = defaultdict(list)
with open(CURATION_CSV) as f:
    for row in csv.DictReader(f):
        tier = row.get("tier", "weak_auto")
        w = TIER_WEIGHTS.get(tier, 0.5)
        if w <= 0: continue
        label = row.get("label", "UNKNOWN")
        if label in ("UNKNOWN",): continue
        labels_by_clip[row["clip_id"]].append({
            "w_start": int(float(row["start"])),
            "label": label, "tier": tier, "weight": w,
        })
print(f"Curated labels: {sum(len(v) for v in labels_by_clip.values())} windows, {len(labels_by_clip)} clips")

# CSI-only empty clips
empty_extra = []
for sf in sorted(CAPTURE_DIR.glob("*.summary.json")):
    try:
        d = json.load(open(sf))
        label = d.get("label",""); step = d.get("step_name","")
        pc = d.get("person_count_expected", -1); sources = d.get("source_count", 0)
        dur = d.get("duration_sec", 0)
        if sources < 3 or dur < 10: continue
        if (pc == 0 or "empty" in step.lower()) and label not in labels_by_clip:
            empty_extra.append(label)
    except: continue
print(f"CSI-only empty clips: {len(empty_extra)}")

# Extract features
all_X, all_yb, all_yc, all_g, all_w = [], [], [], [], []
feat_names = None; t_start = time.time(); n_clips = 0

for clip_id, lwins in sorted(labels_by_clip.items()):
    csi = CAPTURE_DIR / f"{clip_id}.ndjson.gz"
    if not csi.exists(): continue
    wins = extract_csi_features(csi)
    if not wins: continue
    if feat_names is None:
        feat_names = [k for k in wins[0] if k not in ("t_start","t_end")]
    lmap = {lw["w_start"]: lw for lw in lwins}
    for win in wins:
        ws = int(win["t_start"])
        if ws not in lmap: continue
        lw = lmap[ws]; label = lw["label"]
        if label == "ENTRY_EXIT": label = "MOTION"
        all_X.append([win.get(f, 0) for f in feat_names])
        all_yb.append("EMPTY" if label == "EMPTY" else "OCCUPIED")
        all_yc.append(label); all_g.append(clip_id); all_w.append(lw["weight"])
    n_clips += 1
    if n_clips % 20 == 0: print(f"  [{time.time()-t_start:.0f}s] {n_clips} clips, {len(all_X)} windows")

for clip_id in empty_extra:
    csi = CAPTURE_DIR / f"{clip_id}.ndjson.gz"
    if not csi.exists(): continue
    wins = extract_csi_features(csi)
    if not wins: continue
    for win in wins:
        all_X.append([win.get(f, 0) for f in feat_names])
        all_yb.append("EMPTY"); all_yc.append("EMPTY")
        all_g.append(clip_id); all_w.append(1.0)
    n_clips += 1

print(f"\nDone in {time.time()-t_start:.1f}s: {n_clips} clips, {len(all_X)} windows, {len(feat_names)} features")
print(f"Binary: {Counter(all_yb)}")
print(f"Coarse: {Counter(all_yc)}")
if len(all_X) < 50: print("Too few!"); sys.exit(1)

# Train
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import balanced_accuracy_score, classification_report
import pickle

X = np.nan_to_num(np.array(all_X, dtype=np.float32))
yb, yc = np.array(all_yb), np.array(all_yc)
groups, weights = np.array(all_g), np.array(all_w, dtype=np.float32)

cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)

for task, y in [("binary", yb), ("coarse", yc)]:
    print(f"\n{'='*70}\n{task.upper()}: {Counter(y)}\n{'='*70}")
    best_ba, best_name, best_clf = 0, "", None
    for name, clf in [
        ("HGB_bal", HistGradientBoostingClassifier(max_iter=500, learning_rate=0.05, max_depth=6, class_weight="balanced", random_state=42)),
        ("RF_bal", RandomForestClassifier(n_estimators=300, max_depth=12, class_weight="balanced", random_state=42, n_jobs=-1)),
        ("HGB_wt", HistGradientBoostingClassifier(max_iter=500, learning_rate=0.05, max_depth=6, random_state=42)),
    ]:
        scores = []
        for train_i, test_i in cv.split(X, y, groups):
            if "wt" in name: clf.fit(X[train_i], y[train_i], sample_weight=weights[train_i])
            else: clf.fit(X[train_i], y[train_i])
            scores.append(balanced_accuracy_score(y[test_i], clf.predict(X[test_i])))
        ba = np.mean(scores)
        print(f"  {name:12s}: BalAcc={ba:.3f} +- {np.std(scores):.3f}")
        if ba > best_ba:
            best_ba, best_name = ba, name
            best_clf = clf
            if "wt" in name: best_clf.fit(X, y, sample_weight=weights)
            else: best_clf.fit(X, y)
    print(f"\n  BEST: {best_name} BalAcc={best_ba:.3f}")
    print(classification_report(y, best_clf.predict(X), zero_division=0))
    pickle.dump({"model": best_clf, "feature_names": feat_names, "task": task,
                 "bal_acc": best_ba, "name": best_name}, open(OUTPUT_DIR / f"v29_{task}.pkl", "wb"))

# Temporal smoothing
print("\n--- Temporal Smoothing (binary) ---")
bm = pickle.load(open(OUTPUT_DIR / "v29_binary.pkl", "rb"))["model"]
proba = bm.predict_proba(X)
oi = list(bm.classes_).index("OCCUPIED")
op = proba[:, oi]
for k in [3, 5, 7]:
    s = np.convolve(op, np.ones(k)/k, mode='same')
    for th in [0.3, 0.4, 0.5]:
        p = np.where(s > th, "OCCUPIED", "EMPTY")
        print(f"  k={k} th={th:.1f}: BalAcc={balanced_accuracy_score(yb, p):.3f}")

print(f"\nTotal: {time.time()-t_start:.1f}s. Done.")
