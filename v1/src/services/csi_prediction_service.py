"""
CSI Real-Time Prediction Service

Listens to UDP CSI packets from ESP32 nodes, extracts features in 5-second
windows, and runs motion detection via HGB classifier.

PRIMARY RUNTIME CONTRACT (2026-03-19):
  motion_state: MOTION_DETECTED | NO_MOTION
  This is the only reliable cross-session output (0.70 BalAcc, drift-resistant).

SECONDARY/EXPERIMENTAL (not primary product output):
  binary: empty | occupied  — unreliable cross-session (SNR < 0.3)
  coarse: empty | static | motion — internal telemetry only
"""

import asyncio
import base64
import json
import logging
import pickle
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import entropy, kurtosis, skew

logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parents[3]
MODEL_PATH = PROJECT / "output" / "frozen_twostage_runtime_v1.pkl"
UDP_PORT = 5005
NODE_IPS = sorted(["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137"])
WINDOW_SEC = 5.0
CSI_HEADER = 20
BUFFER_WINDOWS = 3  # keep recent history; binary smoothing is not applied here yet
MAX_BUFFER_SEC = 30  # max seconds of packets to keep in memory

# Garage geometry (meters). Origin = center of room.
# node01(192.168.1.137)=bottom-right near door, node02(117)=bottom-left near door
# node03(101)=top-right deep, node04(125)=top-left deep
# Sorted by IP: 101=node03, 117=node02, 125=node04, 137=node01
NODE_POSITIONS = {
    "192.168.1.101": (1.10, 3.25),   # node03 — right, deep
    "192.168.1.117": (-1.00, 0.15),  # node02 — left, near door
    "192.168.1.125": (-1.05, 3.25),  # node04 — left, deep
    "192.168.1.137": (1.05, 0.15),   # node01 — right, near door
}
GARAGE_WIDTH = 4.30   # meters
GARAGE_HEIGHT = 7.50  # meters
DOOR_POSITION = (1.5, 0.0)  # right side, bottom


class CsiPredictionService:
    def __init__(self):
        self.model_bundle = None
        self.feature_names = None
        self.binary_model = None
        self.coarse_model = None
        self.coarse_labels = None

        # Live packet buffer: {ip: [(t_sec, amp, phase), ...]}
        self._packets = defaultdict(list)
        self._start_time = None
        self._last_window_time = 0
        self._recent_predictions = []
        self._transport = None
        self._running = False

        # Current prediction state
        # PRIMARY: motion_state is the only reliable cross-session output
        # SECONDARY: binary/coarse kept as internal telemetry only
        self.current = {
            "motion_state": "NO_MOTION",
            "motion_confidence": 0.0,
            "binary": "unknown",
            "binary_confidence": 0.0,
            "coarse": "unknown",
            "coarse_confidence": 0.0,
            "target_x": 0.0,
            "target_y": 0.0,
            "target_zone": "unknown",
            "nodes_active": 0,
            "packets_in_window": 0,
            "pps": 0.0,
            "window_age_sec": 0.0,
            "model_version": "none",
            "garage": {"width": GARAGE_WIDTH, "height": GARAGE_HEIGHT,
                       "nodes": {ip: {"x": x, "y": y} for ip, (x, y) in NODE_POSITIONS.items()},
                       "door": {"x": DOOR_POSITION[0], "y": DOOR_POSITION[1]}},
            "history": [],
        }
        self._prev_target = (0.0, 0.0)  # for position smoothing only
        self._node_baselines = {}  # running mean per node for relative positioning

    def load_model(self, path: str | Path | None = None):
        """Load trained model bundle (supports V21/V22 and V25 formats)."""
        p = Path(path) if path else MODEL_PATH
        if not p.exists():
            logger.error(f"Model not found: {p}")
            return False

        try:
            bundle = pickle.load(open(p, "rb"))
            self.model_bundle = bundle
            version = bundle.get("version", "unknown")

            # V25 format: model, feature_columns, threshold
            if "feature_columns" in bundle:
                self.feature_names = bundle["feature_columns"]
                self.binary_model = bundle["model"]
                self.coarse_model = bundle.get("coarse_model")
                self.coarse_labels = bundle.get("coarse_labels", {0: "static", 1: "motion"})
                self._binary_threshold = bundle.get("threshold", 0.5)
                cv_score = bundle.get("binary_balaccc", 0)
            else:
                # V21/V22 format
                self.feature_names = bundle["feature_names"]
                self.binary_model = bundle["binary_model"]
                self.coarse_model = bundle.get("coarse_model")
                self.coarse_labels = bundle.get("coarse_labels", {0: "static", 1: "motion"})
                self._binary_threshold = 0.5
                cv_score = bundle.get("binary_cv_score", 0)

            logger.info(
                f"Model loaded: v={version}, "
                f"features={len(self.feature_names)}, "
                f"cv_score={cv_score:.3f}, "
                f"threshold={self._binary_threshold}"
            )
            self.current["model_version"] = version
            return True
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    # ── CSI parsing ───────────────────────────────────────────────────

    @staticmethod
    def _parse_csi(b64: str):
        """Parse base64 CSI payload into amplitude and phase arrays."""
        raw = base64.b64decode(b64)
        if len(raw) < CSI_HEADER + 40:
            return None, None
        iq = raw[CSI_HEADER : CSI_HEADER + 256]
        n = len(iq) // 2
        if n < 40:
            return None, None
        arr = np.frombuffer(iq[: n * 2], dtype=np.int8).reshape(-1, 2)
        i_v = arr[:, 0].astype(np.float32)
        q_v = arr[:, 1].astype(np.float32)
        amp = np.sqrt(i_v**2 + q_v**2)
        phase = np.arctan2(q_v, i_v)
        if len(amp) < 128:
            amp = np.pad(amp, (0, 128 - len(amp)))
            phase = np.pad(phase, (0, 128 - len(phase)))
        return amp[:128], phase[:128]

    # ── Feature extraction (mirrors V21) ──────────────────────────────

    def _extract_window_features(self, t_start: float, t_end: float) -> dict | None:
        """Extract V21-compatible features for one window from live buffer."""
        feat = {"t_mid": (t_start + t_end) / 2}
        nm, ns, nv, nd1 = [], [], [], []
        n_sc_ent, n_sc_frac, n_dop, n_bldev = [], [], [], []
        active_nodes = 0

        for ni, ip in enumerate(NODE_IPS):
            pkts = [(t, a, p) for t, a, p in self._packets.get(ip, []) if t_start <= t < t_end]
            pre = f"n{ni}"

            if len(pkts) < 5:
                for s in [
                    "mean", "std", "max", "range", "pps", "tvar", "diff1", "diff1_max",
                    "kurtosis", "skew", "zcr",
                    "sc_var_mean", "sc_var_max", "sc_var_lo", "sc_var_hi",
                    "sc_var_frac_hi", "sc_var_entropy", "sc_var_concentration", "sc_var_kurtosis",
                    "phase_rate_mean", "doppler_spread", "doppler",
                    "fft_peak", "fft_energy", "pca_ev1", "pca_effdim",
                    "norm", "bldev", "amp_skew", "tvar_lo", "tvar_hi",
                ]:
                    feat[f"{pre}_{s}"] = 0
                nm.append(0); ns.append(0); nv.append(0); nd1.append(0)
                n_sc_ent.append(0); n_sc_frac.append(0); n_dop.append(0); n_bldev.append(0)
                continue

            active_nodes += 1
            amp_mat = np.array([a for _, a, _ in pkts], dtype=np.float32)
            phase_mat = np.array([p for _, _, p in pkts], dtype=np.float32)
            amps = amp_mat.mean(axis=1)

            # V12-style features
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

            # V19 subcarrier features
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

            top10 = np.sort(sc_var)[::-1][:max(1, len(sc_var) // 10)].sum()
            feat[f"{pre}_sc_var_concentration"] = float(top10 / (sc_var.sum() + 1e-10))
            feat[f"{pre}_sc_var_kurtosis"] = float(kurtosis(sc_var))

            # V22: normalized mean amplitude
            feat[f"{pre}_norm"] = float(np.mean(amps) / (np.std(amps) + 1e-10))

            # V22: baseline deviation (mean abs diff from window mean)
            feat[f"{pre}_bldev"] = float(np.mean(np.abs(amps - np.mean(amps))))

            # V22: amplitude skewness
            feat[f"{pre}_amp_skew"] = float(skew(amps)) if len(amps) > 3 else 0

            # V22: temporal variance split by subcarrier bands
            sc_tvar = amp_mat.var(axis=0)
            lo_band = sc_tvar[6:59]   # subcarriers 6-58
            hi_band = sc_tvar[70:123] # subcarriers 70-122
            feat[f"{pre}_tvar_lo"] = float(lo_band.mean()) if len(lo_band) > 0 else 0
            feat[f"{pre}_tvar_hi"] = float(hi_band.mean()) if len(hi_band) > 0 else 0

            # Phase / Doppler
            if phase_mat.shape[0] >= 5:
                ph_unwrap = np.unwrap(phase_mat, axis=0)
                ph_rate = np.abs(np.diff(ph_unwrap, axis=0))
                feat[f"{pre}_phase_rate_mean"] = float(ph_rate.mean())
                dop_spread = float(ph_rate.mean(axis=0).std())
                feat[f"{pre}_doppler_spread"] = dop_spread
                feat[f"{pre}_doppler"] = dop_spread  # V22 alias
            else:
                feat[f"{pre}_phase_rate_mean"] = 0
                dop_spread = 0
                feat[f"{pre}_doppler_spread"] = 0
                feat[f"{pre}_doppler"] = 0

            # FFT
            if len(amps) >= 8:
                fft_v = np.abs(np.fft.rfft(amps - amps.mean()))
                feat[f"{pre}_fft_peak"] = float(np.max(fft_v[1:])) if len(fft_v) > 1 else 0
                feat[f"{pre}_fft_energy"] = float(np.sum(fft_v[1:] ** 2)) if len(fft_v) > 1 else 0
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
                except Exception:
                    feat[f"{pre}_pca_ev1"] = 0; feat[f"{pre}_pca_effdim"] = 0
            else:
                feat[f"{pre}_pca_ev1"] = 0; feat[f"{pre}_pca_effdim"] = 0

            nm.append(np.mean(amps)); ns.append(np.std(amps)); nv.append(tv)
            nd1.append(feat[f"{pre}_diff1"])
            n_sc_ent.append(sc_ent); n_sc_frac.append(frac_hi); n_dop.append(dop_spread)
            n_bldev.append(feat[f"{pre}_bldev"])

        # Cross-node features
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
            feat["x_bldev_mean"] = float(np.mean(n_bldev))
            feat["x_bldev_std"] = float(np.std(n_bldev))
            feat["x_bldev_max"] = float(max(n_bldev))
        else:
            for k in ["x_mean_std", "x_mean_range", "x_std_mean", "x_tvar_mean",
                       "x_tvar_max", "x_diff1_mean", "x_sc_ent_mean", "x_sc_ent_std",
                       "x_sc_frac_mean", "x_doppler_mean", "x_doppler_max",
                       "x_bldev_mean", "x_bldev_std", "x_bldev_max"]:
                feat[k] = 0

        # Aggregate
        all_a = []
        for ip in NODE_IPS:
            all_a.extend([a.mean() for t, a, _ in self._packets.get(ip, []) if t_start <= t < t_end])
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / WINDOW_SEC

        # Temporal delta (use previous prediction if available)
        for ni in range(4):
            feat[f"n{ni}_delta"] = 0  # simplified for live

        return feat, active_nodes, sum(len(p) for p in self._packets.values() if any(t_start <= t < t_end for t, _, _ in p))

    # ── Prediction ────────────────────────────────────────────────────

    def predict_window(self):
        """Run prediction on the most recent complete window."""
        if not self.binary_model or not self._start_time:
            return

        now = time.time() - self._start_time
        w_end = int(now / WINDOW_SEC) * WINDOW_SEC
        w_start = w_end - WINDOW_SEC

        if w_end <= self._last_window_time or w_end < WINDOW_SEC:
            return

        self._last_window_time = w_end
        result = self._extract_window_features(w_start, w_end)
        if result is None:
            return

        feat, active_nodes, pkt_count = result

        # Build feature vector in correct order
        X = np.array([[feat.get(f, 0) for f in self.feature_names]], dtype=np.float32)
        X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

        # Binary prediction with custom threshold
        bin_proba = self.binary_model.predict_proba(X)[0]
        threshold = getattr(self, '_binary_threshold', 0.5)
        # proba[1] = P(occupied)
        p_occupied = float(bin_proba[1]) if len(bin_proba) > 1 else float(bin_proba[0])
        bin_pred = 1 if p_occupied >= threshold else 0
        binary_label = "occupied" if bin_pred == 1 else "empty"
        binary_conf = p_occupied if bin_pred == 1 else (1 - p_occupied)

        # Coarse prediction (only if occupied and coarse model exists)
        coarse_label = "empty"
        coarse_conf = 0.0
        if bin_pred == 1 and self.coarse_model is not None:
            coarse_pred = self.coarse_model.predict(X)[0]
            coarse_proba = self.coarse_model.predict_proba(X)[0]
            # coarse_pred may be int (old models) or string (frozen_twostage_v1)
            if isinstance(coarse_pred, str):
                coarse_label = coarse_pred.lower()
            else:
                coarse_label = self.coarse_labels.get(coarse_pred, "unknown")
            coarse_conf = float(max(coarse_proba))
        elif bin_pred == 1:
            # No coarse model — estimate motion from temporal variance (fallback)
            tvar_sum = sum(feat.get(f"n{i}_tvar", 0) for i in range(4))
            coarse_label = "motion" if tvar_sum > 600 else "static"
            coarse_conf = 0.5

        total_pps = sum(
            len([1 for t, _, _ in self._packets.get(ip, []) if w_start <= t < w_end])
            for ip in NODE_IPS
        ) / WINDOW_SEC

        # ── Position estimation (relative deviation from per-node baseline) ──
        target_x, target_y = 0.0, 0.0
        if bin_pred == 1:
            # Update running baselines and compute relative deviation
            weights = []
            positions = []
            for ni, ip in enumerate(NODE_IPS):
                tvar = feat.get(f"n{ni}_tvar", 0)
                std_val = feat.get(f"n{ni}_std", 0)
                sc_var = feat.get(f"n{ni}_sc_var_mean", 0)
                diff1 = feat.get(f"n{ni}_diff1", 0)
                doppler = feat.get(f"n{ni}_doppler_spread", 0)

                # Combined signal strength for this node
                signal = tvar + std_val * 5.0 + sc_var * 0.5 + diff1 * 10.0 + doppler * 20.0

                # Update exponential moving baseline (slow — captures "normal" level)
                key = f"n{ni}"
                if key not in self._node_baselines:
                    self._node_baselines[key] = signal
                else:
                    self._node_baselines[key] = 0.95 * self._node_baselines[key] + 0.05 * signal

                # Relative deviation: how much this node differs from its own baseline
                baseline = self._node_baselines[key]
                if baseline > 0:
                    deviation = abs(signal - baseline) / baseline
                else:
                    deviation = 0

                # Use deviation^3 to strongly amplify the node seeing the most change
                w = deviation ** 3
                if ip in NODE_POSITIONS:
                    weights.append(w)
                    positions.append(NODE_POSITIONS[ip])

            if weights and sum(weights) > 0:
                total_w = sum(weights)
                target_x = sum(w * p[0] for w, p in zip(weights, positions)) / total_w
                target_y = sum(w * p[1] for w, p in zip(weights, positions)) / total_w
            else:
                # Fallback: keep previous position
                target_x, target_y = self._prev_target

            # Light smoothing (alpha=0.6)
            alpha = 0.6
            if self._prev_target != (0.0, 0.0):
                target_x = alpha * target_x + (1 - alpha) * self._prev_target[0]
                target_y = alpha * target_y + (1 - alpha) * self._prev_target[1]

            # Clamp to garage bounds
            target_x = max(-GARAGE_WIDTH / 2, min(GARAGE_WIDTH / 2, target_x))
            target_y = max(0, min(GARAGE_HEIGHT, target_y))

            self._prev_target = (target_x, target_y)

        # Determine zone
        if bin_pred == 0:
            zone = "empty"
        elif target_y < 1.5:
            zone = "door"
        elif target_y > 5.0:
            zone = "deep"
        else:
            zone = "center"

        # PRIMARY: motion state (reliable cross-session, 0.70 BalAcc)
        motion_state = "MOTION_DETECTED" if coarse_label == "motion" else "NO_MOTION"
        motion_conf = coarse_conf if coarse_label == "motion" else max(0.5, 1.0 - coarse_conf) if coarse_conf > 0 else 0.5

        entry = {
            "t": w_end,
            "motion_state": motion_state,
            "motion_confidence": round(motion_conf, 3),
            "binary": binary_label,
            "binary_confidence": round(binary_conf, 3),
            "coarse": coarse_label,
            "coarse_confidence": round(coarse_conf, 3),
            "target_x": round(target_x, 2),
            "target_y": round(target_y, 2),
            "zone": zone,
            "nodes_active": active_nodes,
            "pps": round(total_pps, 1),
        }

        self._recent_predictions.append(entry)
        if len(self._recent_predictions) > 60:  # keep 5 min
            self._recent_predictions = self._recent_predictions[-60:]

        # Telemetry: append prediction to NDJSON log for offline failure analysis
        try:
            telemetry_path = PROJECT / "temp" / "runtime_telemetry.ndjson"
            with open(telemetry_path, "a") as tf:
                telemetry_entry = {
                    "ts": time.time(),
                    "window_t": w_end,
                    "motion_state": motion_state,
                    "motion_conf": round(motion_conf, 3),
                    "binary": binary_label,
                    "binary_conf": round(binary_conf, 3),
                    "coarse": coarse_label,
                    "coarse_conf": round(coarse_conf, 3),
                    "nodes": active_nodes,
                    "pps": round(total_pps, 1),
                    "zone": zone,
                }
                tf.write(json.dumps(telemetry_entry) + "\n")
        except Exception:
            pass  # telemetry must never crash prediction

        self.current.update({
            "motion_state": motion_state,
            "motion_confidence": round(motion_conf, 3),
            "binary": binary_label,
            "binary_confidence": round(binary_conf, 3),
            "coarse": coarse_label,
            "coarse_confidence": round(coarse_conf, 3),
            "target_x": round(target_x, 2),
            "target_y": round(target_y, 2),
            "target_zone": zone,
            "nodes_active": active_nodes,
            "packets_in_window": pkt_count,
            "pps": round(total_pps, 1),
            "window_age_sec": round(time.time() - self._start_time - w_end, 1),
            "history": self._recent_predictions[-30:],
        })

        logger.info(
            f"CSI predict: {motion_state} ({motion_conf:.2f}) "
            f"| binary={binary_label} ({binary_conf:.2f}) "
            f"| coarse={coarse_label} ({coarse_conf:.2f}) "
            f"| {active_nodes} nodes | {total_pps:.0f} pps"
        )

        # Prune old packets
        cutoff = now - MAX_BUFFER_SEC
        for ip in list(self._packets.keys()):
            self._packets[ip] = [(t, a, p) for t, a, p in self._packets[ip] if t > cutoff]

    # ── UDP listener ──────────────────────────────────────────────────

    def _handle_raw_packet(self, data: bytes, addr: tuple):
        """Process one incoming raw UDP CSI packet from ESP32 node."""
        ip = addr[0]
        if ip not in NODE_IPS:
            return

        # Feed to recording service (parallel capture — runs first to avoid data loss)
        try:
            from .csi_recording_service import csi_recording_service
            csi_recording_service.ingest_packet(data, addr)
        except Exception:
            pass

        # Raw binary CSI — same format as capture scripts expect
        amp, phase = self._parse_csi_raw(data)
        if amp is None:
            return
        if self._start_time is None:
            self._start_time = time.time()
        t_sec = time.time() - self._start_time
        self._packets[ip].append((t_sec, amp, phase))

    @staticmethod
    def _parse_csi_raw(data: bytes):
        """Parse raw binary CSI payload (not base64, direct bytes)."""
        if len(data) < CSI_HEADER + 40:
            return None, None
        iq = data[CSI_HEADER : CSI_HEADER + 256]
        n = len(iq) // 2
        if n < 40:
            return None, None
        arr = np.frombuffer(iq[: n * 2], dtype=np.int8).reshape(-1, 2)
        i_v = arr[:, 0].astype(np.float32)
        q_v = arr[:, 1].astype(np.float32)
        amp = np.sqrt(i_v**2 + q_v**2)
        phase = np.arctan2(q_v, i_v)
        if len(amp) < 128:
            amp = np.pad(amp, (0, 128 - len(amp)))
            phase = np.pad(phase, (0, 128 - len(phase)))
        return amp[:128], phase[:128]

    class _UdpProtocol(asyncio.DatagramProtocol):
        def __init__(self, service):
            self.service = service

        def datagram_received(self, data, addr):
            self.service._handle_raw_packet(data, addr)

    async def start_udp_listener(self, port: int = UDP_PORT):
        """Start listening for CSI packets on UDP port."""
        loop = asyncio.get_event_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self._UdpProtocol(self),
            local_addr=("0.0.0.0", port),
        )
        self._transport = transport
        self._running = True
        logger.info(f"CSI UDP listener started on port {port}")

    async def stop(self):
        """Stop the UDP listener."""
        if self._transport:
            self._transport.close()
            self._transport = None
        self._running = False
        logger.info("CSI UDP listener stopped")

    async def prediction_loop(self, interval: float = 2.0):
        """Run predictions at regular intervals."""
        while self._running:
            try:
                self.predict_window()
            except Exception as e:
                logger.error(f"Prediction error: {e}")
            await asyncio.sleep(interval)

    def get_status(self) -> dict:
        """Get current prediction status for API."""
        return {
            "running": self._running,
            "model_loaded": self.binary_model is not None,
            **self.current,
        }


# Singleton
csi_prediction_service = CsiPredictionService()
