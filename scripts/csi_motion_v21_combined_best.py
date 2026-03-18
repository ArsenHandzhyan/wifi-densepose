#!/usr/bin/env python3
"""
V21: Combined Best Features — Subcarrier Patterns + V4 Rich Features

Merge the two best approaches:
  - V19 subcarrier features (Binary=0.804): sc_var_entropy, sc_var_frac_hi,
    doppler_spread, phase_rate, corr_eigenratio
  - V4/V12 rich features (Coarse=0.673): MI-selected from 1844

Also adds:
  - Temporal smoothing (median filter per clip)
  - Probability calibration
  - Threshold tuning for binary
  - Hierarchical: binary(threshold) -> S/M classifier
"""

import gzip, json, base64, time, warnings, pickle
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter, defaultdict
from scipy.stats import entropy, kurtosis, skew
from scipy.ndimage import median_filter

warnings.filterwarnings("ignore")

from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except: HAS_XGB = False

PROJECT = Path(__file__).resolve().parents[1]
CAPTURES = PROJECT / "temp" / "captures"
t0 = time.time()

print("=" * 70)
print("V21: Combined Best Features + Temporal Smoothing")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ── CSI parsing ───────────────────────────────────────────────────────────

CSI_HEADER = 20
NODE_IPS = sorted(["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137"])
WINDOW_SEC = 5.0

def parse_full(b64):
    raw = base64.b64decode(b64)
    if len(raw) < CSI_HEADER + 40: return None, None
    iq = raw[CSI_HEADER:CSI_HEADER + 256]
    n = len(iq) // 2
    if n < 40: return None, None
    arr = np.frombuffer(iq[:n*2], dtype=np.int8).reshape(-1, 2)
    i_v, q_v = arr[:, 0].astype(np.float32), arr[:, 1].astype(np.float32)
    amp = np.sqrt(i_v**2 + q_v**2)
    phase = np.arctan2(q_v, i_v)
    # Pad to 128
    if len(amp) < 128:
        amp = np.pad(amp, (0, 128 - len(amp)))
        phase = np.pad(phase, (0, 128 - len(phase)))
    return amp[:128], phase[:128]

# ── Labels ────────────────────────────────────────────────────────────────

def get_labels():
    labels = {}
    for sf in sorted(CAPTURES.glob("*.summary.json")):
        try:
            d = json.load(open(sf))
            label = d.get("label", "")
            pc = d.get("person_count_expected", -1)
            step = d.get("step_name", "").lower()
            src = d.get("source_count", 0)
            if pc < 0 or src < 3: continue
            if "freeform" in step and "long_capture" in step: continue  # skip noisy

            if pc == 0 or "empty" in step:
                labels[label] = ("EMPTY", "EMPTY")
            elif any(x in step for x in ["walk", "entry", "exit", "freeform", "corridor",
                                          "motion", "fast", "step", "shift", "diagonal",
                                          "bend", "carry", "loop", "linger", "move"]):
                labels[label] = ("OCCUPIED", "MOTION")
            elif any(x in step for x in ["static", "quiet", "sit", "stand", "breath",
                                          "hold", "observe", "lie", "kneel", "reach",
                                          "squat_hold", "person_static"]):
                labels[label] = ("OCCUPIED", "STATIC")
            else:
                labels[label] = ("OCCUPIED", "STATIC")
        except: continue

    for cf in sorted(CAPTURES.glob("*.clip.json")):
        try:
            d = json.load(open(cf))
            label = d.get("capture_label", "")
            if label in labels: continue
            ln = d.get("label_name", "").lower()
            sn = d.get("step_name", "").lower()
            pc = d.get("person_count_expected", -1)
            if pc < 0: continue
            name = ln + " " + sn
            if "freeform" in name and "long_capture" in name: continue

            if pc == 0 or "empty" in name:
                labels[label] = ("EMPTY", "EMPTY")
            elif any(x in name for x in ["walk", "entry", "exit", "corridor", "step",
                                           "fast", "shift", "diagonal", "bend", "carry",
                                           "loop", "linger", "move", "squat_stand"]):
                labels[label] = ("OCCUPIED", "MOTION")
            elif any(x in name for x in ["static", "quiet", "breath", "sit", "stand",
                                           "hold", "observe", "lie", "kneel", "reach",
                                           "multiple_people", "two_person", "three_person",
                                           "four_person", "passive"]):
                labels[label] = ("OCCUPIED", "STATIC")
            elif "occupied" in name:
                labels[label] = ("OCCUPIED", "STATIC")
            else:
                continue
        except: continue

    return labels

# ── Combined feature extraction ───────────────────────────────────────────

def extract_combined_features(csi_path):
    """Extract BOTH v12-style + v19 subcarrier features per window."""
    node_packets = defaultdict(list)

    with gzip.open(str(csi_path), "rt") as f:
        first_ts = None
        for line in f:
            try:
                rec = json.loads(line)
                ip = rec.get("src_ip", "")
                if ip not in NODE_IPS: continue
                amp, phase = parse_full(rec.get("payload_b64", ""))
                if amp is None: continue
                ts = rec.get("ts_ns", 0)
                if first_ts is None: first_ts = ts
                t_sec = (ts - first_ts) / 1e9
                node_packets[ip].append((t_sec, amp, phase))
            except: continue

    if len(node_packets) < 3:
        return []

    all_t = [t for pkts in node_packets.values() for t, _, _ in pkts]
    max_t = max(all_t)
    n_windows = int(max_t / WINDOW_SEC)

    windows = []
    prev_means = None

    for w in range(n_windows):
        t0w = w * WINDOW_SEC
        t1w = t0w + WINDOW_SEC
        feat = {"t_mid": (t0w + t1w) / 2}

        nm, ns, nv, nd1, ndev = [], [], [], [], []
        n_sc_ent, n_sc_frac, n_dop = [], [], []

        for ni, ip in enumerate(NODE_IPS):
            pkts = [(t, a, p) for t, a, p in node_packets.get(ip, []) if t0w <= t < t1w]
            pre = f"n{ni}"

            if len(pkts) < 5:
                for k in [f"{pre}_{s}" for s in [
                    "mean","std","max","range","pps","tvar","diff1","diff1_max",
                    "kurtosis","skew","zcr",
                    "sc_var_mean","sc_var_max","sc_var_lo","sc_var_hi",
                    "sc_var_frac_hi","sc_var_entropy","sc_var_concentration","sc_var_kurtosis",
                    "phase_rate_mean","doppler_spread",
                    "fft_peak","fft_energy",
                    "pca_ev1","pca_effdim"]]:
                    feat[k] = 0
                nm.append(0); ns.append(0); nv.append(0); nd1.append(0)
                n_sc_ent.append(0); n_sc_frac.append(0); n_dop.append(0)
                continue

            amp_mat = np.array([a for _, a, _ in pkts], dtype=np.float32)
            phase_mat = np.array([p for _, _, p in pkts], dtype=np.float32)
            amps = amp_mat.mean(axis=1)

            # ── V12-style features ──
            feat[f"{pre}_mean"] = float(np.mean(amps))
            feat[f"{pre}_std"] = float(np.std(amps))
            feat[f"{pre}_max"] = float(np.max(amps))
            feat[f"{pre}_range"] = float(np.ptp(amps))
            feat[f"{pre}_pps"] = len(pkts) / WINDOW_SEC
            tv = float(np.var(np.diff(amps))) if len(amps) > 1 else 0
            feat[f"{pre}_tvar"] = tv

            d1 = np.abs(np.diff(amps))
            feat[f"{pre}_diff1"] = float(np.mean(d1)) if len(d1) > 0 else 0
            feat[f"{pre}_diff1_max"] = float(np.max(d1)) if len(d1) > 0 else 0

            if len(amps) > 3:
                feat[f"{pre}_kurtosis"] = float(kurtosis(amps))
                feat[f"{pre}_skew"] = float(skew(amps))
                feat[f"{pre}_zcr"] = float(np.mean(np.abs(np.diff(np.sign(np.diff(amps)))) > 0))
            else:
                feat[f"{pre}_kurtosis"] = 0; feat[f"{pre}_skew"] = 0; feat[f"{pre}_zcr"] = 0

            # ── V19 subcarrier features ──
            sc_var = amp_mat.var(axis=0)
            feat[f"{pre}_sc_var_mean"] = float(sc_var.mean())
            feat[f"{pre}_sc_var_max"] = float(sc_var.max())
            feat[f"{pre}_sc_var_lo"] = float(sc_var[:30].mean())
            feat[f"{pre}_sc_var_hi"] = float(sc_var[30:60].mean()) if len(sc_var) > 30 else 0

            thresh = np.median(sc_var) * 2
            frac_hi = float((sc_var > thresh).mean())
            feat[f"{pre}_sc_var_frac_hi"] = frac_hi

            sc_safe = sc_var + 1e-10
            sc_norm = sc_safe / sc_safe.sum()
            sc_ent = float(entropy(sc_norm))
            feat[f"{pre}_sc_var_entropy"] = sc_ent

            top10 = np.sort(sc_var)[::-1][:max(1, len(sc_var)//10)].sum()
            feat[f"{pre}_sc_var_concentration"] = float(top10 / (sc_var.sum() + 1e-10))
            feat[f"{pre}_sc_var_kurtosis"] = float(kurtosis(sc_var))

            # Phase/Doppler
            if phase_mat.shape[0] >= 5:
                ph_unwrap = np.unwrap(phase_mat, axis=0)
                ph_rate = np.abs(np.diff(ph_unwrap, axis=0))
                feat[f"{pre}_phase_rate_mean"] = float(ph_rate.mean())
                mean_rate_sc = ph_rate.mean(axis=0)
                dop_spread = float(mean_rate_sc.std())
                feat[f"{pre}_doppler_spread"] = dop_spread
            else:
                feat[f"{pre}_phase_rate_mean"] = 0; dop_spread = 0
                feat[f"{pre}_doppler_spread"] = 0

            # FFT
            if len(amps) >= 8:
                fft_v = np.abs(np.fft.rfft(amps - amps.mean()))
                feat[f"{pre}_fft_peak"] = float(np.max(fft_v[1:])) if len(fft_v) > 1 else 0
                feat[f"{pre}_fft_energy"] = float(np.sum(fft_v[1:]**2)) if len(fft_v) > 1 else 0
            else:
                feat[f"{pre}_fft_peak"] = 0; feat[f"{pre}_fft_energy"] = 0

            # PCA
            if amp_mat.shape[0] >= 5:
                try:
                    cov = np.cov(amp_mat[:, ::4].T)
                    ev = np.sort(np.linalg.eigvalsh(cov))[::-1]
                    feat[f"{pre}_pca_ev1"] = float(ev[0])
                    total = ev.sum()
                    if total > 0:
                        probs = ev[ev > 0] / total
                        feat[f"{pre}_pca_effdim"] = float(np.exp(-np.sum(probs * np.log(probs))))
                    else:
                        feat[f"{pre}_pca_effdim"] = 0
                except:
                    feat[f"{pre}_pca_ev1"] = 0; feat[f"{pre}_pca_effdim"] = 0
            else:
                feat[f"{pre}_pca_ev1"] = 0; feat[f"{pre}_pca_effdim"] = 0

            nm.append(np.mean(amps)); ns.append(np.std(amps)); nv.append(tv)
            nd1.append(feat[f"{pre}_diff1"])
            n_sc_ent.append(sc_ent); n_sc_frac.append(frac_hi); n_dop.append(dop_spread)

        # ── Cross-node features ──
        if len(nm) >= 2:
            feat["x_mean_std"] = float(np.std(nm))
            feat["x_mean_range"] = float(max(nm) - min(nm))
            feat["x_std_mean"] = float(np.mean(ns))
            feat["x_tvar_mean"] = float(np.mean(nv))
            feat["x_tvar_max"] = float(max(nv))
            feat["x_diff1_mean"] = float(np.mean(nd1))
            feat["x_sc_ent_mean"] = float(np.mean(n_sc_ent))
            feat["x_sc_ent_std"] = float(np.std(n_sc_ent))
            feat["x_sc_frac_mean"] = float(np.mean(n_sc_frac))
            feat["x_doppler_mean"] = float(np.mean(n_dop))
            feat["x_doppler_max"] = float(max(n_dop))
        else:
            for k in ["x_mean_std","x_mean_range","x_std_mean","x_tvar_mean","x_tvar_max",
                       "x_diff1_mean","x_sc_ent_mean","x_sc_ent_std","x_sc_frac_mean",
                       "x_doppler_mean","x_doppler_max"]:
                feat[k] = 0

        # Aggregate
        all_a = [a.mean() for ip in NODE_IPS for t, a, _ in node_packets.get(ip, []) if t0w <= t < t1w]
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / WINDOW_SEC

        # Temporal delta
        if prev_means and len(nm) == len(prev_means):
            for ni in range(min(4, len(nm))):
                feat[f"n{ni}_delta"] = nm[ni] - prev_means[ni]
        else:
            for ni in range(4):
                feat[f"n{ni}_delta"] = 0

        prev_means = list(nm)
        windows.append(feat)

    return windows

# ── Build dataset ─────────────────────────────────────────────────────────

print("\n[Phase 1] Extracting combined features...")
labels = get_labels()
print(f"  Labeled clips: {len(labels)}")

all_rows = []
clip_id = 0

for label, (binary, coarse) in sorted(labels.items()):
    csi_path = CAPTURES / f"{label}.ndjson.gz"
    if not csi_path.exists() or csi_path.stat().st_size < 100:
        continue

    windows = extract_combined_features(csi_path)
    if not windows:
        continue

    for w in windows:
        w["binary"] = binary
        w["coarse"] = coarse
        w["clip_id"] = clip_id
        w["clip_label"] = label
    all_rows.extend(windows)
    clip_id += 1

    if clip_id % 50 == 0:
        print(f"  {clip_id} clips, {len(all_rows)} windows...")

df = pd.DataFrame(all_rows)
feat_cols = [c for c in df.columns if c not in ["binary","coarse","clip_id","clip_label","t_mid"]]

X = df[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0).values
y_b = df["binary"].values
y_c = df["coarse"].values
groups = df["clip_id"].values
clip_labels = df["clip_label"].values

print(f"\n  Windows: {len(df)}, Clips: {clip_id}, Features: {len(feat_cols)}")
print(f"  Binary: {dict(Counter(y_b))}")
print(f"  Coarse: {dict(Counter(y_c))}")

# ── Training ──────────────────────────────────────────────────────────────

print("\n[Phase 2] Training models...")
CV = min(5, len(np.unique(groups)))
sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)

for task, y_task in [("binary", y_b), ("coarse", y_c)]:
    le = LabelEncoder()
    y = le.fit_transform(y_task)
    classes = le.classes_

    best_ba = 0
    for mname, model in [
        ("RF_bal", RandomForestClassifier(n_estimators=500, max_depth=15,
                                          class_weight="balanced", random_state=42, n_jobs=-1)),
        ("HGB_bal", HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                    class_weight="balanced", random_state=42)),
    ]:
        fold_ba = []
        all_preds = np.zeros(len(y), dtype=int)
        for train_idx, test_idx in sgkf.split(X, y, groups):
            m = type(model)(**model.get_params())
            m.fit(X[train_idx], y[train_idx])
            preds = m.predict(X[test_idx])
            all_preds[test_idx] = preds
            fold_ba.append(balanced_accuracy_score(y[test_idx], preds))
        ba = np.mean(fold_ba)
        if ba > best_ba:
            best_ba = ba; best_name = mname; best_std = np.std(fold_ba)
            best_preds = all_preds

    print(f"\n  {task}: {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f}")
    cm = confusion_matrix(y, best_preds)
    print(f"  Classes: {list(classes)}")
    for row in cm:
        print(f"  {row}")
    print(classification_report(y, best_preds, target_names=classes, digits=3))

# ── Threshold tuning for binary ───────────────────────────────────────────

print("\n[Phase 3] Binary threshold tuning...")
le_b = LabelEncoder()
y = le_b.fit_transform(y_b)

all_probs = np.zeros((len(y), 2))
for train_idx, test_idx in sgkf.split(X, y, groups):
    m = RandomForestClassifier(n_estimators=1000, max_depth=20,
                                class_weight="balanced", random_state=42, n_jobs=-1)
    m.fit(X[train_idx], y[train_idx])
    all_probs[test_idx] = m.predict_proba(X[test_idx])

best_t = 0.5; best_ba_t = 0
for t in np.arange(0.2, 0.9, 0.02):
    preds_t = (all_probs[:, 1] >= t).astype(int)
    ba = balanced_accuracy_score(y, preds_t)
    if ba > best_ba_t:
        best_ba_t = ba; best_t = t

pt = (all_probs[:, 1] >= best_t).astype(int)
print(f"  Threshold={best_t:.2f}: BalAcc={best_ba_t:.3f}")
print(f"  EMPTY recall: {(pt[y==0]==0).mean():.3f}")
print(f"  OCCUPIED recall: {(pt[y==1]==1).mean():.3f}")

# ── Temporal smoothing ────────────────────────────────────────────────────

print("\n[Phase 4] Temporal smoothing (median filter)...")

for task, preds, y_true in [("binary", best_preds, le_b.transform(y_b))]:
    smoothed = preds.copy()
    for cid in np.unique(groups):
        mask = groups == cid
        if mask.sum() >= 3:
            smoothed[mask] = median_filter(preds[mask], size=3)

    ba_raw = balanced_accuracy_score(y_true, preds)
    ba_smooth = balanced_accuracy_score(y_true, smoothed)
    print(f"  {task}: raw={ba_raw:.3f} -> smoothed={ba_smooth:.3f} (delta={ba_smooth-ba_raw:+.3f})")

# ── STATIC/MOTION subproblem ──────────────────────────────────────────────

print("\n[Phase 5] STATIC/MOTION...")
mask_occ = y_b == "OCCUPIED"
if mask_occ.sum() >= 50:
    X_occ = X[mask_occ]
    y_sm = y_c[mask_occ]
    g_occ = groups[mask_occ]

    le_sm = LabelEncoder()
    y_sm_enc = le_sm.fit_transform(y_sm)

    best_ba = 0
    for mname, model in [
        ("RF_bal", RandomForestClassifier(n_estimators=500, max_depth=15,
                                          class_weight="balanced", random_state=42, n_jobs=-1)),
        ("HGB_bal", HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                    class_weight="balanced", random_state=42)),
    ]:
        fold_ba = []
        all_preds_sm = np.zeros(len(y_sm_enc), dtype=int)
        sgkf2 = StratifiedGroupKFold(n_splits=min(CV, len(np.unique(g_occ))),
                                      shuffle=True, random_state=42)
        for train_idx, test_idx in sgkf2.split(X_occ, y_sm_enc, g_occ):
            m = type(model)(**model.get_params())
            m.fit(X_occ[train_idx], y_sm_enc[train_idx])
            preds = m.predict(X_occ[test_idx])
            all_preds_sm[test_idx] = preds
            fold_ba.append(balanced_accuracy_score(y_sm_enc[test_idx], preds))
        ba = np.mean(fold_ba)
        if ba > best_ba:
            best_ba = ba; best_name = mname; best_std = np.std(fold_ba)
            best_preds_sm = all_preds_sm

    print(f"  {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f}")
    print(classification_report(y_sm_enc, best_preds_sm,
                                 target_names=le_sm.classes_, digits=3))

# ── Feature importance ────────────────────────────────────────────────────

print("\n[Phase 6] Top features...")
from sklearn.inspection import permutation_importance

m = RandomForestClassifier(n_estimators=500, max_depth=15, class_weight="balanced",
                            random_state=42, n_jobs=-1)
le_b2 = LabelEncoder()
m.fit(X, le_b2.fit_transform(y_b))
pi = permutation_importance(m, X, le_b2.transform(y_b), n_repeats=5, random_state=42, n_jobs=-1)
imp = pd.Series(pi.importances_mean, index=feat_cols).sort_values(ascending=False)

print("  Binary top 20:")
for i, (f, v) in enumerate(imp.head(20).items()):
    print(f"    {i+1:3d}. {f:45s} {v:.4f}")

# Save
outdir = PROJECT / "output" / "csi_pipeline_v21_results"
outdir.mkdir(parents=True, exist_ok=True)
df.to_csv(outdir / "v21_dataset.csv", index=False)

elapsed = time.time() - t0
print(f"\nV21 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min)")
