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
from typing import Any

import numpy as np
from scipy.stats import entropy, kurtosis, skew

logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parents[3]
MODEL_PATH = PROJECT / "output" / "v5_runtime_model_latest.pkl"
UDP_PORT = 5005
NODE_IPS = sorted(["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137"])

# ── Track B v1 shadow-mode constants (2026-03-21) ────────────────
# Track B uses raw CSI subcarrier amplitudes instead of statistical features.
# It expects [50, 424] = 50 time steps × (4 nodes × 106 active subcarriers).
# CRITICAL: node order must match training: n01, n02, n03, n04 (by node ID,
#   NOT by IP sort). IP→node mapping below.
TRACK_B_MODEL_PATH = PROJECT / "output" / "tcn_v2_track_b_v1_torchscript.pt"
TRACK_B_CHECKPOINT_PATH = PROJECT / "output" / "tcn_v2_track_b_v1.pt"
TRACK_B_ENABLED = True  # shadow mode only — does NOT affect production output
TRACK_B_ACTIVE_LO = list(range(6, 59))    # subcarriers 6-58 (53 active)
TRACK_B_ACTIVE_HI = list(range(70, 123))  # subcarriers 70-122 (53 active)
TRACK_B_ACTIVE_SC = np.array(TRACK_B_ACTIVE_LO + TRACK_B_ACTIVE_HI, dtype=np.int32)  # 106
TRACK_B_MAX_PACKETS = 50
TRACK_B_N_NODES = 4
TRACK_B_CLASS_NAMES = ["EMPTY", "STATIC", "MOTION"]
# Node order for Track B tensor: n01, n02, n03, n04 (matches training corpus)
TRACK_B_IP_ORDER = [
    "192.168.1.137",  # n01
    "192.168.1.117",  # n02
    "192.168.1.101",  # n03
    "192.168.1.125",  # n04
]
WINDOW_SEC = 5.0
CSI_HEADER = 20
BUFFER_WINDOWS = 3  # keep recent history; binary smoothing is not applied here yet
MAX_BUFFER_SEC = 30  # max seconds of packets to keep in memory

# ── Topology-aware warmup damping (2026-03-21) ──────────────────
# When a node reconnects after being offline for longer than
# WARMUP_OFFLINE_THRESHOLD_SEC, its CSI features are zeroed out for
# WARMUP_DURATION_SEC to prevent cold-start noise from being
# misclassified as motion.  Evidence: overnight head-to-head showed
# motion FP jumped from 9% to 80% when node04 reconnected after
# ~7 hours offline (AGENTCLOUD_ANALYSIS2, 2026-03-21).
WARMUP_OFFLINE_THRESHOLD_SEC = 300.0   # 5 min gap → treat as cold reconnect
WARMUP_DURATION_SEC = 120.0            # dampen for 2 min (24 × 5-sec windows)

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
        self._coarse_empty_boost = 0.0

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
            "model_id": MODEL_PATH.name,
            "model_filename": MODEL_PATH.name,
            "model_path": str(MODEL_PATH.resolve()),
            "model_kind": "unknown",
            "model_default": True,
            "binary_threshold": 0.5,
            "garage": {"width": GARAGE_WIDTH, "height": GARAGE_HEIGHT,
                       "nodes": {ip: {"x": x, "y": y} for ip, (x, y) in NODE_POSITIONS.items()},
                       "door": {"x": DOOR_POSITION[0], "y": DOOR_POSITION[1]}},
            "history": [],
        }
        self._prev_target = (0.0, 0.0)  # for position smoothing only
        self._node_baselines = {}  # running mean per node for relative positioning
        self._active_model_path = str(MODEL_PATH)
        self._active_model_id = MODEL_PATH.name
        self._active_model_kind = None

        # ── Topology-aware warmup state ──────────────────────────────
        # Tracks per-node last-seen time and warmup expiry.
        # When a node is in warmup, its features are zeroed out so that
        # cold-start noise does not contaminate inference.
        self._node_last_seen: dict[str, float] = {}      # ip → monotonic time
        self._node_warmup_until: dict[str, float] = {}   # ip → monotonic time
        self._node_warmup_log: list[dict] = []            # observable history

        # ── Track B v1 shadow-mode state ─────────────────────────────
        # Shadow inference runs Track B alongside Track A without affecting
        # production output. All results go to logs/telemetry only.
        self._track_b_model = None       # TorchScript model (torch.jit)
        self._track_b_feat_mean = None   # np.ndarray [424]
        self._track_b_feat_std = None    # np.ndarray [424]
        self._track_b_loaded = False
        self._track_b_shadow = {}        # latest shadow prediction
        self._track_b_history: list[dict] = []  # recent shadow predictions

    @staticmethod
    def _classify_runtime_bundle(bundle: dict[str, Any]) -> str | None:
        if "feature_columns" in bundle and "model" in bundle:
            return "v25_like"
        if "feature_names" in bundle and "binary_model" in bundle:
            return "v21_like"
        return None

    def _inspect_runtime_bundle(self, path: Path) -> dict[str, Any] | None:
        try:
            with path.open("rb") as handle:
                bundle = pickle.load(handle)
        except Exception as error:
            logger.warning("Skipping unreadable runtime bundle %s: %s", path.name, error)
            return None

        if not isinstance(bundle, dict):
            return None

        kind = self._classify_runtime_bundle(bundle)
        if not kind:
            return None

        threshold = bundle.get("threshold", 0.5 if kind == "v25_like" else 0.5)
        version = bundle.get("version") or path.stem
        stat = path.stat()
        resolved_path = str(path.resolve())
        default_model = path.resolve() == MODEL_PATH.resolve()
        active_model = Path(self._active_model_path).resolve() == path.resolve()

        return {
            "model_id": path.name,
            "filename": path.name,
            "display_name": f"{version} · {path.stem}",
            "version": version,
            "kind": kind,
            "threshold": float(threshold),
            "path": resolved_path,
            "is_default": default_model,
            "is_active": active_model,
            "loaded": active_model and self.binary_model is not None,
            "updated_at": int(stat.st_mtime * 1000),
        }

    def list_runtime_ready_models(self) -> list[dict[str, Any]]:
        output_dir = MODEL_PATH.parent
        if not output_dir.exists():
            return []

        models = []
        for path in sorted(output_dir.glob("*.pkl")):
            metadata = self._inspect_runtime_bundle(path)
            if metadata:
                models.append(metadata)

        def sort_key(item: dict[str, Any]):
            return (
                0 if item["is_active"] else 1,
                0 if item["is_default"] else 1,
                -float(item["updated_at"]),
                item["filename"],
            )

        return sorted(models, key=sort_key)

    def select_runtime_model(self, model_id: str) -> dict[str, Any]:
        if not model_id:
            raise ValueError("model_id is required")

        candidates = {item["model_id"]: item for item in self.list_runtime_ready_models()}
        selected = candidates.get(model_id)
        if not selected:
            raise ValueError(f"Runtime-ready model not found: {model_id}")

        loaded = self.load_model(selected["path"])
        if not loaded:
            raise RuntimeError(f"Failed to load runtime model: {model_id}")

        refreshed = next((item for item in self.list_runtime_ready_models() if item["model_id"] == model_id), None)
        return refreshed or selected

    def load_model(self, path: str | Path | None = None):
        """Load trained model bundle (supports V21/V22 and V25 formats)."""
        p = Path(path) if path else MODEL_PATH
        if not p.exists():
            logger.error(f"Model not found: {p}")
            return False

        try:
            with p.open("rb") as handle:
                bundle = pickle.load(handle)
            self.model_bundle = bundle
            version = bundle.get("version", "unknown")
            kind = self._classify_runtime_bundle(bundle)
            if not kind:
                raise ValueError(f"Unsupported runtime bundle format: {p.name}")

            # V25 format: model, feature_columns, threshold
            if kind == "v25_like":
                self.feature_names = bundle["feature_columns"]
                self.binary_model = bundle["model"]
                self.coarse_model = bundle.get("coarse_model")
                self.coarse_labels = bundle.get("coarse_labels", {0: "static", 1: "motion"})
                self._binary_threshold = bundle.get("threshold", 0.5)
                self._coarse_empty_boost = float((bundle.get("calibration") or {}).get("empty_boost", 0.0) or 0.0)
                cv_score = bundle.get("binary_balaccc", 0)
            else:
                # V21/V22 format
                self.feature_names = bundle["feature_names"]
                self.binary_model = bundle["binary_model"]
                self.coarse_model = bundle.get("coarse_model")
                self.coarse_labels = bundle.get("coarse_labels", {0: "static", 1: "motion"})
                self._binary_threshold = 0.5
                self._coarse_empty_boost = float((bundle.get("calibration") or {}).get("empty_boost", 0.0) or 0.0)
                cv_score = bundle.get("binary_cv_score", 0)

            self._active_model_path = str(p.resolve())
            self._active_model_id = p.name
            self._active_model_kind = kind
            logger.info(
                f"Model loaded: v={version}, "
                f"features={len(self.feature_names)}, "
                f"cv_score={cv_score:.3f}, "
                f"threshold={self._binary_threshold}"
            )
            self.current["model_version"] = version
            self.current["model_id"] = p.name
            self.current["model_filename"] = p.name
            self.current["model_path"] = str(p.resolve())
            self.current["model_kind"] = kind
            self.current["model_default"] = p.resolve() == MODEL_PATH.resolve()
            self.current["binary_threshold"] = float(self._binary_threshold)
            return True
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    # ── Track B v1 shadow-mode methods ──────────────────────────────

    def _load_track_b(self) -> bool:
        """Load Track B v1 TorchScript model + normalization vectors.

        Safe to call repeatedly — skips if already loaded or if artifacts
        are missing.  Never affects Track A production inference.
        """
        if self._track_b_loaded:
            return True
        if not TRACK_B_ENABLED:
            return False

        try:
            import torch
        except ImportError:
            logger.warning("Track B shadow: torch not installed, skipping")
            return False

        if not TRACK_B_MODEL_PATH.exists():
            logger.warning("Track B shadow: TorchScript model not found: %s",
                           TRACK_B_MODEL_PATH)
            return False
        if not TRACK_B_CHECKPOINT_PATH.exists():
            logger.warning("Track B shadow: checkpoint not found: %s",
                           TRACK_B_CHECKPOINT_PATH)
            return False

        try:
            # Load TorchScript model
            self._track_b_model = torch.jit.load(
                str(TRACK_B_MODEL_PATH), map_location="cpu")
            self._track_b_model.eval()

            # Load normalization vectors from checkpoint
            ckpt = torch.load(str(TRACK_B_CHECKPOINT_PATH),
                              map_location="cpu", weights_only=False)
            norm = ckpt["normalization"]
            self._track_b_feat_mean = np.array(norm["feat_mean"], dtype=np.float32)
            self._track_b_feat_std = np.array(norm["feat_std"], dtype=np.float32)
            self._track_b_feat_std = np.where(
                self._track_b_feat_std < 1e-8, 1.0, self._track_b_feat_std)

            self._track_b_loaded = True
            logger.info(
                "Track B v1 shadow loaded: TorchScript + normalization "
                "(mean/std shape=%s)", self._track_b_feat_mean.shape)
            return True
        except Exception as e:
            logger.error("Track B shadow load failed: %s", e)
            self._track_b_model = None
            self._track_b_feat_mean = None
            self._track_b_feat_std = None
            return False

    def _build_raw_csi_window(self, t_start: float, t_end: float) -> np.ndarray | None:
        """Build raw CSI tensor [50, 424] from live packet buffer.

        Mirrors the exact training preprocessing:
        - For each node in TRACK_B_IP_ORDER (n01, n02, n03, n04):
          - Select packets in [t_start, t_end)
          - Extract amplitude for ACTIVE_SC (106 subcarriers)
          - Pad/truncate to MAX_PACKETS=50 rows
        - Concatenate along axis=1 → [50, 424]

        Returns None if fewer than 2 nodes have any data.
        """
        parts = []
        nodes_with_data = 0

        for ip in TRACK_B_IP_ORDER:
            pkts = [(t, a) for t, a, _p in self._packets.get(ip, [])
                    if t_start <= t < t_end]

            if len(pkts) >= 2:
                nodes_with_data += 1
                # Build amplitude matrix [n_packets, 128], then select active SC
                amp_mat = np.array([a for _, a in pkts], dtype=np.float32)
                # Select 106 active subcarriers (same as training)
                if amp_mat.shape[1] >= 128:
                    active_mat = amp_mat[:, TRACK_B_ACTIVE_SC]
                else:
                    # Pad columns if fewer than 128
                    padded = np.zeros((amp_mat.shape[0], 128), dtype=np.float32)
                    padded[:, :amp_mat.shape[1]] = amp_mat
                    active_mat = padded[:, TRACK_B_ACTIVE_SC]
                # Pad/truncate to 50 rows
                active_mat = self._pad_or_truncate(active_mat, TRACK_B_MAX_PACKETS)
            else:
                active_mat = np.zeros(
                    (TRACK_B_MAX_PACKETS, len(TRACK_B_ACTIVE_SC)), dtype=np.float32)

            parts.append(active_mat)

        if nodes_with_data < 2:
            return None

        # [50, 106*4] = [50, 424]
        return np.concatenate(parts, axis=1).astype(np.float32)

    @staticmethod
    def _pad_or_truncate(mat: np.ndarray, max_len: int) -> np.ndarray:
        """Pad or truncate a 2D matrix to exactly max_len rows."""
        if len(mat) == 0:
            return np.zeros((max_len, mat.shape[1] if mat.ndim > 1 else 106),
                            dtype=np.float32)
        if len(mat) >= max_len:
            return mat[:max_len]
        pad = np.zeros((max_len - len(mat), mat.shape[1]), dtype=np.float32)
        return np.vstack([mat, pad])

    def _shadow_predict_track_b(self, t_start: float, t_end: float,
                                 w_end: float) -> dict | None:
        """Run Track B inference in shadow mode. Never affects production.

        Returns shadow prediction dict or None if blocked.
        """
        if not self._track_b_loaded:
            if not self._load_track_b():
                return None

        raw_window = self._build_raw_csi_window(t_start, t_end)
        if raw_window is None:
            return None

        try:
            import torch
            import torch.nn.functional as F

            # z-score normalize
            x = (raw_window - self._track_b_feat_mean) / self._track_b_feat_std
            x_tensor = torch.from_numpy(x).float().unsqueeze(0)  # [1, 50, 424]

            t0 = time.perf_counter()
            with torch.no_grad():
                logits = self._track_b_model(x_tensor)
            inference_ms = (time.perf_counter() - t0) * 1000

            probs = F.softmax(logits, dim=1).squeeze(0).numpy()
            pred_idx = int(np.argmax(probs))
            pred_class = TRACK_B_CLASS_NAMES[pred_idx]

            shadow = {
                "t": w_end,
                "track": "B_v1",
                "predicted_class": pred_class,
                "predicted_idx": pred_idx,
                "probabilities": {
                    TRACK_B_CLASS_NAMES[i]: round(float(probs[i]), 4)
                    for i in range(3)
                },
                "inference_ms": round(inference_ms, 2),
                "nodes_with_data": sum(
                    1 for ip in TRACK_B_IP_ORDER
                    if any(t_start <= t < t_end
                           for t, _, _ in self._packets.get(ip, []))
                ),
            }
            self._track_b_shadow = shadow
            self._track_b_history.append(shadow)
            if len(self._track_b_history) > 60:
                self._track_b_history = self._track_b_history[-60:]

            logger.info(
                "Track B SHADOW: %s (E=%.3f S=%.3f M=%.3f) %.1fms",
                pred_class, probs[0], probs[1], probs[2], inference_ms)
            return shadow

        except Exception as e:
            logger.error("Track B shadow inference failed: %s", e)
            return None

    # ── CSI parsing ───────────────────────────────────────────────────

    @staticmethod
    def _normalize_to_64(amp, phase=None):
        """Normalize amplitude/phase to exactly 64 subcarriers.

        FIX_SUB64 (2026-03-22): eliminates amplitude confound caused by
        zero-padding 64-sub packets to 128 (halving mean amplitude) while
        128-sub packets kept full amplitude.  All packets now produce 64
        real-valued subcarriers with consistent amplitude scale.

        - n_sub == 64 → keep as-is
        - n_sub > 64  → average adjacent pairs (128→64, 96→48 then pad, etc.)
        - n_sub < 64  → pad with zeros
        """
        n = len(amp)
        if n == 64:
            a64, p64 = amp, phase
        elif n > 64:
            k = n // 64
            usable = 64 * k
            a64 = amp[:usable].reshape(64, k).mean(axis=1)
            if phase is not None:
                # take every k-th phase sample (circular mean is fragile)
                p64 = phase[:usable:k][:64]
            else:
                p64 = None
        else:
            a64 = np.pad(amp, (0, 64 - n), mode='constant')
            p64 = np.pad(phase, (0, 64 - n), mode='constant') if phase is not None else None
        return a64, p64

    @staticmethod
    def _parse_csi(b64: str):
        """Parse base64 CSI payload into amplitude and phase arrays (64-sub normalized)."""
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
        return CSIPredictionService._normalize_to_64(amp, phase)

    # ── Feature extraction (mirrors V21) ──────────────────────────────

    def _extract_window_features(self, t_start: float, t_end: float) -> dict | None:
        """Extract V21-compatible features for one window from live buffer."""
        feat = {"t_mid": (t_start + t_end) / 2}
        nm, ns, nv, nd1 = [], [], [], []
        n_sc_ent, n_sc_frac, n_dop, n_bldev = [], [], [], []
        active_nodes = 0

        now_mono = time.monotonic()

        for ni, ip in enumerate(NODE_IPS):
            pkts = [(t, a, p) for t, a, p in self._packets.get(ip, []) if t_start <= t < t_end]
            pre = f"n{ni}"

            # ── Topology warmup gate: suppress features for reconnected node ─
            warmup_end = self._node_warmup_until.get(ip, 0)
            node_in_warmup = now_mono < warmup_end
            if node_in_warmup and len(pkts) >= 5:
                remaining = warmup_end - now_mono
                logger.debug(
                    f"Node warmup ACTIVE: {ip} has {len(pkts)} pkts but damped "
                    f"({remaining:.0f}s remaining)"
                )
                pkts = []  # treat as offline — zero all features

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

            # V19 subcarrier features (64-sub normalized)
            sc_var = amp_mat.var(axis=0)
            feat[f"{pre}_sc_var_mean"] = float(sc_var.mean())
            feat[f"{pre}_sc_var_max"] = float(sc_var.max())
            feat[f"{pre}_sc_var_lo"] = float(sc_var[:16].mean())
            feat[f"{pre}_sc_var_hi"] = float(sc_var[16:32].mean()) if len(sc_var) > 16 else 0

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

            # V22: temporal variance split by subcarrier bands (64-sub normalized)
            sc_tvar = amp_mat.var(axis=0)
            lo_band = sc_tvar[3:30]   # lower active band (64-sub)
            hi_band = sc_tvar[35:62]  # upper active band (64-sub)
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

            # PCA (64-sub: take every 2nd for ~32 components)
            if amp_mat.shape[0] >= 5:
                try:
                    cov = np.cov(amp_mat[:, ::2].T)
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

    def _normalize_coarse_label(self, value: Any) -> str:
        if isinstance(value, str):
            return value.lower()
        return self.coarse_labels.get(value, str(value).lower())

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
            coarse_proba = self.coarse_model.predict_proba(X)[0]
            coarse_classes = list(getattr(self.coarse_model, "classes_", []))
            coarse_proba_adj = np.array(coarse_proba, copy=True)

            if self._coarse_empty_boost > 0 and coarse_classes:
                for idx, cls in enumerate(coarse_classes):
                    if self._normalize_coarse_label(cls) == "empty":
                        coarse_proba_adj[idx] += self._coarse_empty_boost
                        break

            if coarse_classes:
                coarse_idx = int(np.argmax(coarse_proba_adj))
                coarse_label = self._normalize_coarse_label(coarse_classes[coarse_idx])
                coarse_conf = float(coarse_proba_adj[coarse_idx])
            else:
                coarse_pred = self.coarse_model.predict(X)[0]
                coarse_label = self._normalize_coarse_label(coarse_pred)
                coarse_conf = float(max(coarse_proba_adj))
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
                now_m = time.monotonic()
                damped_ips = [ip for ip in NODE_IPS if now_m < self._node_warmup_until.get(ip, 0)]
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
                    "warmup_damped": damped_ips if damped_ips else None,
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

        # ── Track B shadow inference (does NOT affect production output) ──
        try:
            shadow = self._shadow_predict_track_b(w_start, w_end, w_end)
            if shadow is not None:
                # Append to telemetry for offline comparison
                try:
                    shadow_path = PROJECT / "temp" / "track_b_shadow_telemetry.ndjson"
                    with open(shadow_path, "a") as sf:
                        shadow_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "track_a_motion": motion_state,
                            "track_a_coarse": coarse_label,
                            "track_b_class": shadow["predicted_class"],
                            "track_b_probs": shadow["probabilities"],
                            "track_b_ms": shadow["inference_ms"],
                            "agree": (shadow["predicted_class"].lower() == coarse_label),
                        }
                        sf.write(json.dumps(shadow_entry) + "\n")
                except Exception:
                    pass  # shadow telemetry must never crash
        except Exception as e:
            logger.debug("Track B shadow skipped: %s", e)

        # Prune old packets
        cutoff = now - MAX_BUFFER_SEC
        for ip in list(self._packets.keys()):
            self._packets[ip] = [(t, a, p) for t, a, p in self._packets[ip] if t > cutoff]

    # ── UDP listener ──────────────────────────────────────────────────

    def _handle_raw_packet(self, data: bytes, addr: tuple):
        """Process one incoming raw UDP CSI packet from ESP32 node."""
        ip = addr[0]

        # Feed to recording service BEFORE filtering — shadow nodes (e.g. node05)
        # are recorded but not used for inference.
        try:
            from .csi_recording_service import csi_recording_service
            csi_recording_service.ingest_packet(data, addr)
        except Exception:
            pass

        # Only process packets from core inference nodes
        if ip not in NODE_IPS:
            return

        # Raw binary CSI — same format as capture scripts expect
        amp, phase = self._parse_csi_raw(data)
        if amp is None:
            return
        if self._start_time is None:
            self._start_time = time.time()
        t_sec = time.time() - self._start_time
        self._packets[ip].append((t_sec, amp, phase))

        # ── Topology warmup: detect reconnect after long offline ─────
        now_mono = time.monotonic()
        prev = self._node_last_seen.get(ip)
        self._node_last_seen[ip] = now_mono

        if prev is not None:
            gap = now_mono - prev
            if gap >= WARMUP_OFFLINE_THRESHOLD_SEC:
                warmup_end = now_mono + WARMUP_DURATION_SEC
                self._node_warmup_until[ip] = warmup_end
                event = {
                    "event": "warmup_started",
                    "ip": ip,
                    "gap_sec": round(gap, 1),
                    "warmup_until_mono": round(warmup_end, 1),
                    "ts": time.time(),
                }
                self._node_warmup_log.append(event)
                if len(self._node_warmup_log) > 100:
                    self._node_warmup_log = self._node_warmup_log[-50:]
                logger.warning(
                    f"Node warmup STARTED: {ip} reconnected after {gap:.0f}s offline, "
                    f"damping features for {WARMUP_DURATION_SEC:.0f}s"
                )

    @staticmethod
    def _parse_csi_raw(data: bytes):
        """Parse raw binary CSI payload (not base64, direct bytes). 64-sub normalized."""
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
        return CSIPredictionService._normalize_to_64(amp, phase)

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
        now_mono = time.monotonic()
        warmup_nodes = {}
        for ip in NODE_IPS:
            end = self._node_warmup_until.get(ip, 0)
            if now_mono < end:
                warmup_nodes[ip] = {
                    "remaining_sec": round(end - now_mono, 1),
                    "damped": True,
                }
        status = {
            "running": self._running,
            "model_loaded": self.binary_model is not None,
            "warmup_active": len(warmup_nodes) > 0,
            "warmup_nodes": warmup_nodes,
            **self.current,
        }
        # Track B shadow info (debug surface only)
        if self._track_b_loaded and self._track_b_shadow:
            status["track_b_shadow"] = self._track_b_shadow
        elif TRACK_B_ENABLED:
            status["track_b_shadow"] = {
                "loaded": self._track_b_loaded,
                "status": "awaiting_first_window" if self._track_b_loaded else "not_loaded",
            }
        return status


# Singleton
csi_prediction_service = CsiPredictionService()
