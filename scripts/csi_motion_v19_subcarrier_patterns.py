#!/usr/bin/env python3
"""
V19: Subcarrier-level pattern analysis for STATIC detection

Core hypothesis: Walking person creates variance across ALL subcarriers,
while static person creates variance only on NEARBY subcarriers.

This exploits the physical fact that different subcarriers correspond to
different multipath components. A moving person disturbs all paths,
while a stationary person only blocks specific paths.

Features to try:
  1. Fraction of high-variance subcarriers (>threshold)
  2. Variance entropy across subcarriers
  3. Variance concentration ratio (top10% / total)
  4. Subcarrier correlation matrix eigenvalue ratio
  5. Band-specific variance ratios
  6. Doppler spread (phase rate of change)
"""

import gzip, json, base64, time, warnings, pickle
import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter, defaultdict
from scipy.stats import entropy, kurtosis

warnings.filterwarnings("ignore")

from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
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
print("V19: Subcarrier Pattern Analysis for STATIC Detection")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# ── CSI parsing ───────────────────────────────────────────────────────────

CSI_HEADER = 20
NODE_IPS = sorted(["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137"])
ACTIVE_LO = list(range(6, 59))   # 53 subcarriers
ACTIVE_HI = list(range(70, 123)) # 53 subcarriers
WINDOW_SEC = 5.0

def parse_full(b64):
    """Parse CSI into full amplitude + phase arrays."""
    raw = base64.b64decode(b64)
    if len(raw) < CSI_HEADER + 40: return None, None
    iq = raw[CSI_HEADER:CSI_HEADER + 256]
    n = len(iq) // 2
    if n < 64: return None, None
    arr = np.frombuffer(iq[:n*2], dtype=np.int8).reshape(-1, 2)
    i_v, q_v = arr[:, 0].astype(np.float32), arr[:, 1].astype(np.float32)
    amp = np.sqrt(i_v**2 + q_v**2)
    phase = np.arctan2(q_v, i_v)
    return amp[:128], phase[:128]

# ── Load labeled clips ────────────────────────────────────────────────────

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

            if pc == 0 or "empty" in step:
                labels[label] = ("EMPTY", "EMPTY")
            elif any(x in step for x in ["walk", "entry", "exit", "freeform", "corridor", "motion", "fast"]):
                labels[label] = ("OCCUPIED", "MOTION")
            elif any(x in step for x in ["static", "quiet", "sit", "stand", "breath", "hold"]):
                labels[label] = ("OCCUPIED", "STATIC")
            else:
                labels[label] = ("OCCUPIED", "STATIC")
        except: continue

    # Also from clip.json
    for cf in sorted(CAPTURES.glob("*.clip.json")):
        try:
            d = json.load(open(cf))
            label = d.get("capture_label", "")
            if label in labels: continue
            ln = d.get("label_name", "").lower()
            pc = d.get("person_count_expected", -1)
            if pc < 0: continue

            if pc == 0 or "empty" in ln:
                labels[label] = ("EMPTY", "EMPTY")
            elif any(x in ln for x in ["walk", "entry", "exit", "corridor", "step", "fast"]):
                labels[label] = ("OCCUPIED", "MOTION")
            else:
                labels[label] = ("OCCUPIED", "STATIC")
        except: continue

    return labels

# ── Subcarrier-level feature extraction ───────────────────────────────────

def extract_subcarrier_features(csi_path):
    """Extract subcarrier-level features per window."""
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
    for w in range(n_windows):
        t0w = w * WINDOW_SEC
        t1w = t0w + WINDOW_SEC
        feat = {}

        node_sc_vars = []  # per-node subcarrier variance profiles
        node_phase_rates = []
        node_means = []

        for ni, ip in enumerate(NODE_IPS):
            pkts = [(t, a, p) for t, a, p in node_packets.get(ip, []) if t0w <= t < t1w]
            prefix = f"n{ni}"

            if len(pkts) < 5:
                # Zero features
                for k in [f"{prefix}_sc_var_frac_hi", f"{prefix}_sc_var_entropy",
                          f"{prefix}_sc_var_concentration", f"{prefix}_sc_var_kurtosis",
                          f"{prefix}_sc_var_lo_ratio", f"{prefix}_sc_var_hi_ratio",
                          f"{prefix}_phase_rate_mean", f"{prefix}_phase_rate_std",
                          f"{prefix}_doppler_spread", f"{prefix}_amp_mean",
                          f"{prefix}_amp_std", f"{prefix}_diff1_mean",
                          f"{prefix}_corr_eigenratio"]:
                    feat[k] = 0
                continue

            # Pad all to 128
            amp_list = []
            phase_list = []
            for _, a, p in pkts:
                if len(a) >= 128:
                    amp_list.append(a[:128])
                    phase_list.append(p[:128])
                else:
                    amp_list.append(np.pad(a, (0, 128-len(a))))
                    phase_list.append(np.pad(p, (0, 128-len(p))))
            amp_mat = np.array(amp_list, dtype=np.float32)  # (T, 128)
            phase_mat = np.array(phase_list, dtype=np.float32)

            # === SUBCARRIER VARIANCE PROFILE ===
            sc_var = amp_mat.var(axis=0)  # variance per subcarrier

            # 1. Fraction of high-variance subcarriers
            threshold = np.median(sc_var) * 2
            frac_hi = (sc_var > threshold).mean()
            feat[f"{prefix}_sc_var_frac_hi"] = float(frac_hi)

            # 2. Variance entropy (uniform = motion, concentrated = static)
            sc_var_safe = sc_var + 1e-10
            sc_var_norm = sc_var_safe / sc_var_safe.sum()
            var_ent = float(entropy(sc_var_norm))
            feat[f"{prefix}_sc_var_entropy"] = var_ent

            # 3. Variance concentration (top 10% / total)
            sorted_var = np.sort(sc_var)[::-1]
            top10 = sorted_var[:max(1, len(sorted_var)//10)].sum()
            total_var = sorted_var.sum() + 1e-10
            feat[f"{prefix}_sc_var_concentration"] = float(top10 / total_var)

            # 4. Variance kurtosis (peaky = concentrated = static?)
            feat[f"{prefix}_sc_var_kurtosis"] = float(kurtosis(sc_var))

            # 5. Band-specific variance ratios
            if len(sc_var) >= 60:
                lo_var = sc_var[:30].mean()
                hi_var = sc_var[30:60].mean()
                total_mean = sc_var.mean() + 1e-10
                feat[f"{prefix}_sc_var_lo_ratio"] = float(lo_var / total_mean)
                feat[f"{prefix}_sc_var_hi_ratio"] = float(hi_var / total_mean)
            else:
                feat[f"{prefix}_sc_var_lo_ratio"] = 0
                feat[f"{prefix}_sc_var_hi_ratio"] = 0

            # === PHASE/DOPPLER FEATURES ===
            if phase_mat.shape[0] >= 5:
                # Unwrap and compute rate of change
                ph_unwrap = np.unwrap(phase_mat, axis=0)
                ph_diff = np.diff(ph_unwrap, axis=0)
                ph_rate = np.abs(ph_diff)

                feat[f"{prefix}_phase_rate_mean"] = float(ph_rate.mean())
                feat[f"{prefix}_phase_rate_std"] = float(ph_rate.std())

                # Doppler spread: std of phase rates across subcarriers
                mean_rate_per_sc = ph_rate.mean(axis=0)
                feat[f"{prefix}_doppler_spread"] = float(mean_rate_per_sc.std())

                node_phase_rates.append(ph_rate.mean())
            else:
                feat[f"{prefix}_phase_rate_mean"] = 0
                feat[f"{prefix}_phase_rate_std"] = 0
                feat[f"{prefix}_doppler_spread"] = 0

            # === AMPLITUDE FEATURES ===
            amps = amp_mat.mean(axis=1)
            feat[f"{prefix}_amp_mean"] = float(np.mean(amps))
            feat[f"{prefix}_amp_std"] = float(np.std(amps))

            diff1 = np.abs(np.diff(amps))
            feat[f"{prefix}_diff1_mean"] = float(np.mean(diff1)) if len(diff1) > 0 else 0

            # === CORRELATION EIGENVALUE RATIO ===
            if amp_mat.shape[0] >= 10 and amp_mat.shape[1] >= 30:
                # Sample subcarriers for speed
                sc_sample = amp_mat[:, ::4]  # every 4th subcarrier
                try:
                    cov = np.cov(sc_sample.T)
                    eigvals = np.sort(np.linalg.eigvalsh(cov))[::-1]
                    if len(eigvals) >= 2 and eigvals[1] > 0:
                        feat[f"{prefix}_corr_eigenratio"] = float(eigvals[0] / eigvals[1])
                    else:
                        feat[f"{prefix}_corr_eigenratio"] = 0
                except:
                    feat[f"{prefix}_corr_eigenratio"] = 0
            else:
                feat[f"{prefix}_corr_eigenratio"] = 0

            node_sc_vars.append(sc_var)
            node_means.append(np.mean(amps))

        # === CROSS-NODE FEATURES ===
        if len(node_sc_vars) >= 2:
            # Cross-node variance profile similarity
            corrs = []
            for i in range(len(node_sc_vars)):
                for j in range(i+1, len(node_sc_vars)):
                    n_sc = min(len(node_sc_vars[i]), len(node_sc_vars[j]))
                    if n_sc > 10:
                        c = np.corrcoef(node_sc_vars[i][:n_sc], node_sc_vars[j][:n_sc])[0, 1]
                        if np.isfinite(c):
                            corrs.append(c)
            feat["x_sc_var_corr_mean"] = float(np.mean(corrs)) if corrs else 0
            feat["x_sc_var_corr_std"] = float(np.std(corrs)) if len(corrs) > 1 else 0

            # Cross-node amplitude stats
            feat["x_amp_std"] = float(np.std(node_means))
            feat["x_amp_range"] = float(max(node_means) - min(node_means)) if node_means else 0
        else:
            feat["x_sc_var_corr_mean"] = 0
            feat["x_sc_var_corr_std"] = 0
            feat["x_amp_std"] = 0
            feat["x_amp_range"] = 0

        feat["t_mid"] = (t0w + t1w) / 2
        windows.append(feat)

    return windows

# ── Build dataset ─────────────────────────────────────────────────────────

print("\n[Phase 1] Loading labels and extracting subcarrier features...")
labels = get_labels()
print(f"  Labeled clips: {len(labels)}")

all_rows = []
clip_id = 0
processed = 0

for label, (binary, coarse) in sorted(labels.items()):
    csi_path = CAPTURES / f"{label}.ndjson.gz"
    if not csi_path.exists() or csi_path.stat().st_size < 100:
        continue

    windows = extract_subcarrier_features(csi_path)
    if not windows:
        continue

    for w in windows:
        w["binary"] = binary
        w["coarse"] = coarse
        w["clip_id"] = clip_id
    all_rows.extend(windows)
    clip_id += 1
    processed += 1
    if processed % 50 == 0:
        print(f"  {processed} clips, {len(all_rows)} windows...")

print(f"  Total: {processed} clips, {len(all_rows)} windows")

if len(all_rows) < 50:
    print("Too few windows!")
    exit(1)

df = pd.DataFrame(all_rows)
feat_cols = [c for c in df.columns if c not in ["binary", "coarse", "clip_id", "t_mid"]]

X = df[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0).values
y_binary = df["binary"].values
y_coarse = df["coarse"].values
groups = df["clip_id"].values

print(f"\n  Features: {len(feat_cols)}")
print(f"  Binary: {dict(Counter(y_binary))}")
print(f"  Coarse: {dict(Counter(y_coarse))}")

# ── Train ─────────────────────────────────────────────────────────────────

print("\n[Phase 2] Training models...")

CV = min(5, len(np.unique(groups)))
sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)

for task, y_task in [("binary", y_binary), ("coarse", y_coarse)]:
    le = LabelEncoder()
    y = le.fit_transform(y_task)
    classes = le.classes_

    if len(np.unique(y)) < 2:
        continue

    best_ba = 0
    best_name = ""
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
            best_ba = ba; best_name = mname
            best_std = np.std(fold_ba); best_preds = all_preds

    print(f"\n  {task}: {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f}")
    cm = confusion_matrix(y, best_preds)
    print(f"  Classes: {list(classes)}")
    for row in cm:
        print(f"  {row}")
    print(classification_report(y, best_preds, target_names=classes, digits=3))

# ── STATIC/MOTION only ────────────────────────────────────────────────────

print("\n[Phase 3] STATIC vs MOTION subproblem...")

mask_occ = y_binary == "OCCUPIED"
if mask_occ.sum() >= 50:
    X_occ = X[mask_occ]
    y_sm = y_coarse[mask_occ]
    g_occ = groups[mask_occ]

    if len(np.unique(y_sm)) >= 2:
        le_sm = LabelEncoder()
        y_sm_enc = le_sm.fit_transform(y_sm)

        sgkf2 = StratifiedGroupKFold(n_splits=min(CV, len(np.unique(g_occ))),
                                      shuffle=True, random_state=42)

        best_ba = 0
        for mname, model in [
            ("RF_bal", RandomForestClassifier(n_estimators=500, max_depth=15,
                                              class_weight="balanced", random_state=42, n_jobs=-1)),
            ("HGB_bal", HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                        class_weight="balanced", random_state=42)),
        ]:
            fold_ba = []
            all_preds = np.zeros(len(y_sm_enc), dtype=int)
            for train_idx, test_idx in sgkf2.split(X_occ, y_sm_enc, g_occ):
                m = type(model)(**model.get_params())
                m.fit(X_occ[train_idx], y_sm_enc[train_idx])
                preds = m.predict(X_occ[test_idx])
                all_preds[test_idx] = preds
                fold_ba.append(balanced_accuracy_score(y_sm_enc[test_idx], preds))
            ba = np.mean(fold_ba)
            if ba > best_ba:
                best_ba = ba; best_name = mname; best_std = np.std(fold_ba)
                best_preds_sm = all_preds

        print(f"  STATIC/MOTION: {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f}")
        cm = confusion_matrix(y_sm_enc, best_preds_sm)
        print(f"  Classes: {list(le_sm.classes_)}")
        for row in cm:
            print(f"  {row}")
        print(classification_report(y_sm_enc, best_preds_sm,
                                     target_names=le_sm.classes_, digits=3))

# ── Feature importance ────────────────────────────────────────────────────

print("\n[Phase 4] Feature importance for STATIC/MOTION...")
if mask_occ.sum() >= 50 and len(np.unique(y_sm)) >= 2:
    from sklearn.inspection import permutation_importance

    # Train on full data for importance
    m = RandomForestClassifier(n_estimators=500, max_depth=15,
                                class_weight="balanced", random_state=42, n_jobs=-1)
    m.fit(X_occ, y_sm_enc)

    pi = permutation_importance(m, X_occ, y_sm_enc, n_repeats=5, random_state=42, n_jobs=-1)
    imp = pd.Series(pi.importances_mean, index=feat_cols).sort_values(ascending=False)

    print("  Top 15 features for STATIC/MOTION:")
    for i, (fname, val) in enumerate(imp.head(15).items()):
        print(f"    {i+1:3d}. {fname:40s} importance={val:.4f}")

elapsed = time.time() - t0
print(f"\nV19 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min)")
