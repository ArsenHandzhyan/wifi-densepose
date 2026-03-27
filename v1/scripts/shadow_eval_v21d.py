#!/usr/bin/env python3
"""Shadow evaluation: V21d (zone-aware) vs V20 (production) on recent live captures.

Loads both models, extracts features from the 5 most recent capture sessions,
builds seq_len=7 sequences, and compares predictions side-by-side.
"""
from __future__ import annotations

import json
import os
import pickle
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

# ── Project root ───────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from runtime_aligned_training_extractor import (
    WINDOW_SEC,
    add_v8_f2_features,
    extract_window_features_from_packets,
    load_capture_packets,
)

# ── Paths ──────────────────────────────────────────────────────
V20_PATH = ROOT / "output/train_runs/v20_manifest_v18_candidate.pkl"
V21D_PATH = ROOT / "output/train_runs/v21_dual_validated/v21d_candidate.pkl"
CAPTURES_DIR = ROOT / "temp/captures"
OUTPUT_PATH = ROOT / "output/train_runs/v21_dual_validated/shadow_eval_v1.json"

EPS = 1e-10
SEQ_LEN = 7
N_SESSIONS = 5


# ── Guard features (V23) ──────────────────────────────────────
def add_v23_guard_features(feat: dict) -> dict:
    """Add guard features matching the training pipeline."""
    out = dict(feat)

    pps_vals = [float(out.get(f"n{i}_pps", 0) or 0) for i in range(4)]
    min_pps = min(pps_vals)
    max_pps = max(pps_vals)
    out["gh_min_pps"] = min_pps
    out["gh_max_pps"] = max_pps
    out["gh_pps_imbalance"] = max_pps / (min_pps + EPS)
    out["gh_degraded_node_count"] = float(sum(1 for p in pps_vals if p < 15))
    out["gh_node_health_score"] = min(1.0, 1.0 / (max_pps / (min_pps + EPS) + EPS))
    out["gh_pps_std"] = float(np.std(pps_vals))

    tvar_hi = [float(out.get(f"n{i}_tvar_hi", 0) or 0) for i in range(4)]
    max_tvar_n01 = max(tvar_hi[0], tvar_hi[1])
    x_tvar = float(out.get("x_tvar_mean", 0) or 0)
    out["gv_max_tvar_hi_n01"] = max_tvar_n01
    out["gv_sc_var_ratio"] = max_tvar_n01 / (x_tvar + EPS)
    out["gv_sc_var_noise_score"] = float(max_tvar_n01 > 3.8 and x_tvar < 1.5)
    out["gv_max_tvar_hi_all"] = max(tvar_hi)
    out["gv_tvar_hi_std"] = float(np.std(tvar_hi))

    node_trigger = float(min_pps < 15 and max_pps > 25)
    out["ge_composite"] = min(1.0, node_trigger + out["gv_sc_var_noise_score"])
    out["ge_low_motion_high_noise"] = float(x_tvar < 1.5 and max_tvar_n01 > 3.8 * 0.8)

    pj = [float(out.get(f"n{i}_sq_phase_jump_rate", 0) or 0) for i in range(4)]
    out["gp_phase_jump_mean"] = float(np.mean(pj))
    out["gp_phase_jump_max"] = max(pj)
    out["gp_phase_noise_score"] = float(np.mean(pj) > 0.30)

    drift = [float(out.get(f"n{i}_sq_amp_drift", 0) or 0) for i in range(4)]
    out["gd_amp_drift_max"] = max(drift)
    out["gd_drift_noise_score"] = float(max(drift) > 2.0 and x_tvar < 1.5)

    dead = [float(out.get(f"n{i}_sq_dead_sc_frac", 0) or 0) for i in range(4)]
    out["gs_dead_sc_max"] = max(dead)
    out["gs_dead_sc_score"] = float(max(dead) > 0.40)

    out["ge_v23_composite"] = min(
        1.0,
        out["ge_composite"]
        + out["gp_phase_noise_score"]
        + out["gd_drift_noise_score"]
        + out["gs_dead_sc_score"],
    )
    return out


# ── Session discovery ──────────────────────────────────────────
def discover_sessions(captures_dir: Path, n: int) -> list[tuple[str, list[Path]]]:
    """Find the N most recent capture sessions, grouped by session prefix."""
    files = list(captures_dir.glob("*.ndjson.gz"))
    sessions: dict[str, list[Path]] = {}
    for f in files:
        m = re.match(r"(.+?)_chunk\d+", f.name)
        if m:
            key = m.group(1)
            sessions.setdefault(key, []).append(f)

    # Sort by most recent file modification time
    ordered = sorted(
        sessions.items(),
        key=lambda kv: max(p.stat().st_mtime for p in kv[1]),
        reverse=True,
    )
    # Filter out tiny sessions (< 10KB total)
    result = []
    for name, chunks in ordered:
        total_size = sum(c.stat().st_size for c in chunks)
        if total_size > 10_000:
            result.append((name, sorted(chunks, key=lambda p: p.name)))
        if len(result) >= n:
            break
    return result


# ── Feature extraction ─────────────────────────────────────────
def extract_session_windows(
    chunks: list[Path], window_features: list[str]
) -> list[list[float]]:
    """Extract window feature vectors from a session's capture chunks."""
    all_windows: list[list[float]] = []
    for chunk_path in chunks:
        try:
            packets, max_t = load_capture_packets(chunk_path)
        except Exception as e:
            print(f"  [WARN] Failed to load {chunk_path.name}: {e}")
            continue

        if max_t < WINDOW_SEC:
            continue

        t = 0.0
        while t + WINDOW_SEC <= max_t + 1e-6:
            feat, active, pkt_count = extract_window_features_from_packets(
                packets, t, t + WINDOW_SEC
            )
            if active < 2 or pkt_count < 20:
                t += WINDOW_SEC
                continue

            # Add F2 + guard features
            feat = add_v8_f2_features(feat)
            feat = add_v23_guard_features(feat)

            # Extract in canonical order
            vec = [float(feat.get(f, 0) or 0) for f in window_features]
            all_windows.append(vec)
            t += WINDOW_SEC

    return all_windows


def build_sequences(
    windows: list[list[float]], seq_len: int
) -> np.ndarray:
    """Build flattened sequences: each row = [t0_f0, t0_f1, ..., t6_fN]."""
    if len(windows) < seq_len:
        return np.empty((0,))
    n_feat = len(windows[0])
    seqs = []
    for i in range(len(windows) - seq_len + 1):
        flat = []
        for j in range(seq_len):
            flat.extend(windows[i + j])
        seqs.append(flat)
    return np.array(seqs, dtype=np.float32)


# ── Main ───────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("Shadow Evaluation: V21d (zone-aware) vs V20 (production)")
    print("=" * 70)

    # Load V20
    print("\nLoading V20 model...")
    with open(V20_PATH, "rb") as fh:
        v20_bundle = pickle.load(fh)
    v20_coarse = v20_bundle["coarse_model"]
    v20_features = v20_bundle["feature_names"]  # seq-level features
    v20_window_features = v20_bundle["window_feature_names"]
    v20_seq_len = v20_bundle["seq_len"]
    v20_labels = [str(c) for c in v20_coarse.classes_]
    print(f"  V20: {len(v20_window_features)} window features, seq_len={v20_seq_len}")
    print(f"  V20 classes: {v20_labels}")
    print(f"  V20 total seq features: {v20_coarse.n_features_in_}")

    # Load V21d
    print("\nLoading V21d model...")
    with open(V21D_PATH, "rb") as fh:
        v21d_model = pickle.load(fh)
    v21d_labels = [str(c) for c in v21d_model.classes_]
    print(f"  V21d: n_features_in={v21d_model.n_features_in_}")
    print(f"  V21d classes: {v21d_labels}")

    assert v20_seq_len == SEQ_LEN, f"Expected seq_len={SEQ_LEN}, got {v20_seq_len}"
    assert v20_coarse.n_features_in_ == v21d_model.n_features_in_, (
        f"Feature count mismatch: V20={v20_coarse.n_features_in_}, "
        f"V21d={v21d_model.n_features_in_}"
    )

    # Discover sessions
    print(f"\nDiscovering {N_SESSIONS} most recent capture sessions...")
    sessions = discover_sessions(CAPTURES_DIR, N_SESSIONS)
    if not sessions:
        print("ERROR: No capture sessions found!")
        sys.exit(1)
    print(f"  Found {len(sessions)} sessions:")
    for name, chunks in sessions:
        total_kb = sum(c.stat().st_size for c in chunks) / 1024
        print(f"    {name}: {len(chunks)} chunks ({total_kb:.0f} KB)")

    # Process each session
    all_v20_preds: list[str] = []
    all_v21d_preds: list[str] = []
    all_v20_proba: list[list[float]] = []
    all_v21d_proba: list[list[float]] = []
    session_results = []

    for sess_name, chunks in sessions:
        print(f"\n{'─' * 60}")
        print(f"Session: {sess_name}")
        print(f"  Chunks: {len(chunks)}")

        # Extract windows
        windows = extract_session_windows(chunks, v20_window_features)
        print(f"  Windows extracted: {len(windows)}")
        if len(windows) < SEQ_LEN:
            print(f"  SKIP: not enough windows (need >= {SEQ_LEN})")
            session_results.append({
                "session": sess_name,
                "n_chunks": len(chunks),
                "n_windows": len(windows),
                "n_sequences": 0,
                "skipped": True,
                "reason": f"not enough windows ({len(windows)} < {SEQ_LEN})",
            })
            continue

        # Build sequences
        X = build_sequences(windows, SEQ_LEN)
        n_seq = X.shape[0]
        print(f"  Sequences built: {n_seq} (shape: {X.shape})")

        # Clean NaN/Inf
        X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

        # Predict with V20
        t0 = time.perf_counter()
        v20_pred = v20_coarse.predict(X)
        v20_proba = v20_coarse.predict_proba(X)
        v20_ms = (time.perf_counter() - t0) * 1000

        # Predict with V21d
        t0 = time.perf_counter()
        v21d_pred = v21d_model.predict(X)
        v21d_proba = v21d_model.predict_proba(X)
        v21d_ms = (time.perf_counter() - t0) * 1000

        v20_preds = [str(p) for p in v20_pred]
        v21d_preds = [str(p) for p in v21d_pred]

        # Agreement
        agree = sum(1 for a, b in zip(v20_preds, v21d_preds) if a == b)
        agree_rate = agree / n_seq if n_seq > 0 else 0

        # Distribution
        v20_dist = dict(Counter(v20_preds))
        v21d_dist = dict(Counter(v21d_preds))

        print(f"  V20  inference: {v20_ms:.1f}ms, dist: {v20_dist}")
        print(f"  V21d inference: {v21d_ms:.1f}ms, dist: {v21d_dist}")
        print(f"  Agreement: {agree}/{n_seq} ({agree_rate:.1%})")

        # Disagreement analysis
        disagree_pairs: Counter = Counter()
        disagree_details: list[dict] = []
        for i, (a, b) in enumerate(zip(v20_preds, v21d_preds)):
            if a != b:
                disagree_pairs[(a, b)] += 1
                if len(disagree_details) < 10:
                    disagree_details.append({
                        "seq_idx": i,
                        "v20": a,
                        "v21d": b,
                        "v20_proba": {
                            lbl: round(float(p), 4)
                            for lbl, p in zip(v20_labels, v20_proba[i])
                        },
                        "v21d_proba": {
                            lbl: round(float(p), 4)
                            for lbl, p in zip(v21d_labels, v21d_proba[i])
                        },
                    })

        if disagree_pairs:
            print(f"  Disagreements:")
            for (a, b), cnt in disagree_pairs.most_common():
                print(f"    V20={a} -> V21d={b}: {cnt} ({cnt/n_seq:.1%})")

        # Confidence stats
        v20_conf = np.max(v20_proba, axis=1)
        v21d_conf = np.max(v21d_proba, axis=1)

        sess_result = {
            "session": sess_name,
            "n_chunks": len(chunks),
            "n_windows": len(windows),
            "n_sequences": n_seq,
            "skipped": False,
            "v20_distribution": v20_dist,
            "v21d_distribution": v21d_dist,
            "agreement_rate": round(agree_rate, 4),
            "agreement_count": agree,
            "disagreement_count": n_seq - agree,
            "disagreement_pairs": {
                f"{a}->{b}": cnt for (a, b), cnt in disagree_pairs.most_common()
            },
            "v20_inference_ms": round(v20_ms, 2),
            "v21d_inference_ms": round(v21d_ms, 2),
            "v20_confidence": {
                "mean": round(float(v20_conf.mean()), 4),
                "min": round(float(v20_conf.min()), 4),
                "max": round(float(v20_conf.max()), 4),
            },
            "v21d_confidence": {
                "mean": round(float(v21d_conf.mean()), 4),
                "min": round(float(v21d_conf.min()), 4),
                "max": round(float(v21d_conf.max()), 4),
            },
            "disagree_examples": disagree_details[:5],
        }
        session_results.append(sess_result)

        all_v20_preds.extend(v20_preds)
        all_v21d_preds.extend(v21d_preds)
        all_v20_proba.extend(v20_proba.tolist())
        all_v21d_proba.extend(v21d_proba.tolist())

    # ── Global summary ─────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("GLOBAL SUMMARY")
    print(f"{'=' * 70}")

    total = len(all_v20_preds)
    if total == 0:
        print("No sequences processed!")
        sys.exit(1)

    global_agree = sum(1 for a, b in zip(all_v20_preds, all_v21d_preds) if a == b)
    global_agree_rate = global_agree / total

    global_v20_dist = dict(Counter(all_v20_preds))
    global_v21d_dist = dict(Counter(all_v21d_preds))

    global_disagree: Counter = Counter()
    for a, b in zip(all_v20_preds, all_v21d_preds):
        if a != b:
            global_disagree[(a, b)] += 1

    print(f"\nTotal sequences: {total}")
    print(f"Sessions processed: {sum(1 for s in session_results if not s.get('skipped'))}")
    print(f"\nV20  prediction distribution: {global_v20_dist}")
    print(f"V21d prediction distribution: {global_v21d_dist}")
    print(f"\nGlobal agreement: {global_agree}/{total} ({global_agree_rate:.1%})")

    if global_disagree:
        print(f"\nDisagreement breakdown:")
        for (a, b), cnt in global_disagree.most_common():
            print(f"  V20={a} -> V21d={b}: {cnt} ({cnt/total:.1%})")

    # Confidence comparison
    if all_v20_proba:
        v20_conf_all = np.max(np.array(all_v20_proba), axis=1)
        v21d_conf_all = np.max(np.array(all_v21d_proba), axis=1)
        print(f"\nV20  confidence: mean={v20_conf_all.mean():.4f}, "
              f"min={v20_conf_all.min():.4f}, std={v20_conf_all.std():.4f}")
        print(f"V21d confidence: mean={v21d_conf_all.mean():.4f}, "
              f"min={v21d_conf_all.min():.4f}, std={v21d_conf_all.std():.4f}")

        # Confidence on disagreements
        disagree_mask = np.array([a != b for a, b in zip(all_v20_preds, all_v21d_preds)])
        if disagree_mask.sum() > 0:
            print(f"\nOn disagreements ({disagree_mask.sum()} sequences):")
            print(f"  V20  confidence: mean={v20_conf_all[disagree_mask].mean():.4f}")
            print(f"  V21d confidence: mean={v21d_conf_all[disagree_mask].mean():.4f}")

    # ── Save results ───────────────────────────────────────────
    output = {
        "eval_type": "shadow_v21d_vs_v20",
        "timestamp": datetime.now().isoformat(),
        "v20_model": str(V20_PATH),
        "v21d_model": str(V21D_PATH),
        "seq_len": SEQ_LEN,
        "window_sec": WINDOW_SEC,
        "n_window_features": len(v20_window_features),
        "n_sessions": len(sessions),
        "n_sessions_processed": sum(1 for s in session_results if not s.get("skipped")),
        "total_sequences": total,
        "global_agreement_rate": round(global_agree_rate, 4),
        "global_agreement_count": global_agree,
        "global_disagreement_count": total - global_agree,
        "global_v20_distribution": global_v20_dist,
        "global_v21d_distribution": global_v21d_dist,
        "global_disagreement_pairs": {
            f"{a}->{b}": cnt for (a, b), cnt in global_disagree.most_common()
        },
        "global_v20_confidence": {
            "mean": round(float(v20_conf_all.mean()), 4),
            "min": round(float(v20_conf_all.min()), 4),
            "std": round(float(v20_conf_all.std()), 4),
        } if all_v20_proba else {},
        "global_v21d_confidence": {
            "mean": round(float(v21d_conf_all.mean()), 4),
            "min": round(float(v21d_conf_all.min()), 4),
            "std": round(float(v21d_conf_all.std()), 4),
        } if all_v21d_proba else {},
        "sessions": session_results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
