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
import os
import pickle
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import entropy, kurtosis, skew

from .csi_node_inventory import CORE_NODE_IPS

logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parents[3]
MODEL_PATH = PROJECT / "output" / "train_runs" / "v42_binary_balanced.pkl"
UDP_PORT = 5005
UDP_PORT_CSV = 5006  # ESP32-S3 nodes with CSI_DATA CSV format
NODE_IPS = sorted(["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137", "192.168.1.33", "192.168.1.77", "192.168.1.41"])

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
WINDOW_SEC = 2.0
WINDOW_SLIDE_SEC = 0.5  # sliding window step (predictions every 0.5s using 2s of data)
CSI_HEADER = 20
BUFFER_WINDOWS = 3  # keep recent history; binary smoothing is not applied here yet
MAX_BUFFER_SEC = 30  # max seconds of packets to keep in memory

# ── Transition boundary candidate detection (2026-03-23) ─────────
# When Track B MOTION probability exceeds this threshold after a
# stable non-MOTION period (≥ 1 window), flag as a potential
# count-transition boundary.  Forensic/eval marker only — does NOT
# affect production routing.  See CT1_RUNTIME_SHADOW_TEST1 report.
TRANSITION_BOUNDARY_MOTION_THRESHOLD = 0.95
TRANSITION_BOUNDARY_STABLE_WINDOWS = 1  # min non-MOTION windows before spike qualifies

# ── V8 F2-spectral canonical shadow-mode constants (2026-03-22) ─────
# V8 uses the same warehouse-bound seq7 surface as V7, but adds the
# winning F2 spectral/distribution feature family (+30 features).
V7_MODEL_PATH = PROJECT / "output" / "v7_whbound_canonical_baseline.pkl"
V7_METADATA_PATH = PROJECT / "output" / "v7_whbound_canonical_baseline_metadata.json"
V7_SHADOW_ENABLED = True  # shadow mode only — does NOT affect production output
V7_SEQ_LEN = 7

# ── V8 F2-spectral shadow-mode constants (2026-03-22) ──
# V8 = V7 base (85 features) + 30 F2 spectral/distribution features = 115 per window.
# HGB on seq_len=7 flattened: 115 × 7 = 805.
# Macro F1=0.9822 (beats V7 0.9806 on all metrics). Regression gate PASS.
# Shadow mode only — does NOT affect production output.
V8_MODEL_PATH = PROJECT / "output" / "v8_f2spectral_canonical_candidate.pkl"
V8_METADATA_PATH = PROJECT / "output" / "v8_f2spectral_canonical_candidate_metadata.json"
V8_SHADOW_ENABLED = True   # shadow mode only
V8_SEQ_LEN = 7
# F2 spectral feature names (per-node: 7 × 4 = 28, cross-node: 2 = 30 total)
V8_F2_PER_NODE = ["snr", "norm_range", "rel_diff1", "ctv", "rel_bldev", "shape_score", "pca_norm"]
V8_F2_CROSS = ["x_snr_cv", "x_snr_min"]

# ── Garage ratio V3 shadow candidate (2026-03-25) ──────────────────
# Non-production garage zoning candidate:
#   ratio RF-500 + threshold tuning + V5 door rescue.
# Shadow mode only; production routing remains on Track A / V5.
GARAGE_RATIO_V2_MODEL_PATH = PROJECT / "output" / "garage_ratio_layer_v3_candidate.pkl"
GARAGE_RATIO_V2_METADATA_PATH = PROJECT / "output" / "garage_ratio_layer_v3_candidate_metadata.json"
GARAGE_RATIO_V2_SHADOW_ENABLED = True
GARAGE_RATIO_NODE_ORDER = [
    ("192.168.1.137", "node01"),
    ("192.168.1.117", "node02"),
    ("192.168.1.101", "node03"),
    ("192.168.1.125", "node04"),
    ("192.168.1.33", "node05"),
    ("192.168.1.77", "node06"),
    ("192.168.1.41", "node07"),
]
GARAGE_RATIO_NODE_NAME_BY_IP = {ip: node_name for ip, node_name in GARAGE_RATIO_NODE_ORDER}
GARAGE_RATIO_ZONE_NAMES = ["door", "center", "deep"]
GARAGE_RATIO_MIN_ACTIVE_NODES = 3
GARAGE_RATIO_MIN_PACKETS = 20
GARAGE_RATIO_CAUSAL_SMOOTH_WINDOW = 7
GARAGE_RATIO_CAUSAL_SMOOTH_ENABLED = True
RSSI_OFFSET = 16

# ── Old-router domain-adapt shadow-mode constants (2026-03-27) ─────
# Non-production shadow now points to the gate2-passed EMPTY/STATIC
# regularized candidate. This does not change production routing.
OLD_ROUTER_DOMAIN_ADAPT_CANDIDATE_NAME = "old_router_empty_static_regularization1_candidate.pkl"
OLD_ROUTER_DOMAIN_ADAPT_MODEL_PATH = (
    PROJECT
    / "output"
    / "old_router_empty_static_regularization1"
    / OLD_ROUTER_DOMAIN_ADAPT_CANDIDATE_NAME
)
OLD_ROUTER_DOMAIN_ADAPT_SHADOW_ENABLED = False  # disabled: trained on old router, diverges from production model
OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN = 7

# Guard-feature thresholds shared with V16/V18/domain-adapt training.
NODE_HEALTH_MIN_PPS = 15.0
NODE_HEALTH_MAX_PPS = 25.0
SC_VAR_HI_THRESHOLD = 3.8
SC_VAR_MOTION_TVAR_CEILING = 1.5

# ── V29 CNN zone prediction (2026-03-26) ──────────────────────────
# ImprovedCNN1D on raw subcarrier amplitudes [40, 208] → 3 zones.
# LODO BA=0.442, door recall=0.789. Shadow mode only initially.
V29_CNN_MODEL_PATH = PROJECT / "output" / "train_runs" / "v29_cnn_zone_model.pt"
V29_CNN_SHADOW_ENABLED = True

# ── V42 few-shot zone calibration (2026-03-27) ────────────────────
# V42: RF on 1424 windows (5 sessions, 33 features incl. amp_norm + ratios).
# CV BA=0.9902. Balanced: 711 center / 713 door_passage. FREEZE.
# Offline eval: accuracy=1.0, BA=1.0, macro_f1=1.0 on S1-S5 archive.
V30_FEWSHOT_MODEL_PATH = PROJECT / "output" / "train_runs" / "v42_fewshot_zone_calibration.pkl"
V30_FEWSHOT_ZONE_ENABLED = True
V30_FEWSHOT_ZONE_NAMES = ["center", "door_passage"]

# ── V42 binary balanced production (2026-03-27) ─────────────────────
# Promoted from shadow to primary. V42 balanced HGB on 1876 windows
# (484 empty + 1392 occupied), BA=0.9858. Uses the legacy v26 pipeline.
V26_BINARY_7NODE_MODEL_PATH = PROJECT / "output" / "train_runs" / "v42_binary_balanced.pkl"
V26_BINARY_SHADOW_ENABLED = True
V26_BINARY_SHADOW_TELEMETRY_PATH = PROJECT / "temp" / "binary_7node_shadow_telemetry.ndjson"

# ── V43 binary shadow test (2026-03-28) ───────────────────────────
# V43: HGB coarse model on merged manifest_v20 (18828 windows, seq_len=7).
# CV macro_f1=0.8365, binary_balacc=0.8642. Gate criteria NOT all pass.
# Shadow mode only — runs alongside V42 production for live comparison.
# Enable via SHADOW_V43=1 env var.
V43_SHADOW_MODEL_PATH = PROJECT / "output" / "train_runs" / "v43_retrain" / "v43_binary_candidate.pkl"
V43_SHADOW_ENABLED = os.environ.get("SHADOW_V43", "0") == "1"
V43_SHADOW_SEQ_LEN = 7
V43_SHADOW_LOG_PATH = PROJECT / "output" / "shadow_v43" / "shadow_log.jsonl"
V29_CNN_MAX_PACKETS = 40
V29_CNN_N_SC = 52  # subcarriers 2-53 per node
V29_CNN_SC_START = 2
V29_CNN_SC_END = 54
V29_CNN_ZONE_NAMES = ["door", "center", "deep"]
V29_CNN_IP_ORDER = [
    "192.168.1.137",  # node01
    "192.168.1.117",  # node02
    "192.168.1.101",  # node03
    "192.168.1.125",  # node04
]

# ── Topology-aware warmup damping (2026-03-21) ──────────────────
# When a node reconnects after being offline for longer than
# WARMUP_OFFLINE_THRESHOLD_SEC, its CSI features are zeroed out for
# WARMUP_DURATION_SEC to prevent cold-start noise from being
# misclassified as motion.  Evidence: overnight head-to-head showed
# motion FP jumped from 9% to 80% when node04 reconnected after
# ~7 hours offline (AGENTCLOUD_ANALYSIS2, 2026-03-21).
WARMUP_OFFLINE_THRESHOLD_SEC = 120.0   # 2 min gap → treat as cold reconnect
WARMUP_DURATION_SEC = 30.0             # dampen for 30s (enough for CSI to stabilize)

# Garage geometry (meters). Origin = center of room, one door at bottom center.
# Garage Planner v3 layout for the 3m×7m garage (updated 2026-03-26):
# - node01 (y=0.55) / node02 (y=0.55) near door, left/right walls
# - node03 (y=3.15) left wall mid-garage, node04 (y=2.50) right wall
# - node05 (y=3.50) center ceiling, door/center boundary
# - Sorted by IP: 33=node05, 101=node03, 117=node02, 125=node04, 137=node01
NODE_POSITIONS = {
    # Garage Planner v3 (2026-03-26): 3×7m, ceiling-mounted, top-down projection.
    # Coordinate system: x=0..3 (left..right facing into garage), y=0=door, y=7=deep end.
    # Converted to center-based: x → x - 1.5 so x ∈ [-1.5, +1.5].
    "192.168.1.137": (-1.50, 0.55),  # node01 — left wall, near door
    "192.168.1.117": (1.50, 0.55),   # node02 — right wall, near door
    "192.168.1.101": (-1.50, 3.15),  # node03 — left wall, mid-garage
    "192.168.1.125": (1.50, 2.50),   # node04 — right wall, mid-garage
    "192.168.1.33":  (0.00, 3.50),   # node05 — center ceiling, door/center boundary
    "192.168.1.77":  (-1.50, 4.35),  # node06 — left wall, center zone
    "192.168.1.41":  (1.50, 3.70),   # node07 — right wall, center zone
}
GARAGE_WIDTH = 3.00   # meters
GARAGE_HEIGHT = 7.00  # meters (was 5.0 — corrected from Garage Planner v3)
DOOR_POSITION = (0.0, 0.0)  # bottom center, single door


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
        self._prediction_task: asyncio.Task | None = None

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

        # ── V23: Empty baseline profiles (topology-aware calibration) ─
        # Per-node statistics captured during a known-empty room period.
        # Used to compute deviation features at inference time.
        # Format: {ip: {amp_mean, amp_std, phase_rate_mean, phase_rate_std,
        #               sc_var_mean, sc_var_std, captured_at, window_count}}
        self._empty_baselines: dict[str, dict] = {}
        self._baseline_capture_active = False
        self._baseline_capture_windows: dict[str, list[dict]] = defaultdict(list)
        self._load_empty_baselines()  # auto-load on startup if file exists
        self._fewshot_adaptation_shadow: dict[str, Any] = {}

        # ── Track B v1 shadow-mode state ─────────────────────────────
        # Shadow inference runs Track B alongside Track A without affecting
        # production output. All results go to logs/telemetry only.
        self._track_b_model = None       # TorchScript model (torch.jit)
        self._track_b_feat_mean = None   # np.ndarray [424]
        self._track_b_feat_std = None    # np.ndarray [424]
        self._track_b_loaded = False
        self._track_b_shadow = {}        # latest shadow prediction
        self._track_b_history: list[dict] = []  # recent shadow predictions
        self._track_b_stable_non_motion: int = 0   # consecutive non-MOTION windows
        self._track_b_transition_markers: list[dict] = []  # transition boundary candidates

        # ── V8 F2-spectral canonical shadow-mode state ───────────────
        # V8 shadow: seq_len=7 HGB model on warehouse-bound canonical data
        # with added F2 spectral/distribution features.
        self._v15_model_bundle = None    # loaded pkl dict
        self._v15_binary_model = None    # derived binary only for compat
        self._v15_coarse_model = None    # HGB coarse
        self._v15_window_features: list[str] = []  # 115 window feature names
        self._v15_class_names: list[str] = []  # coarse class names from metadata
        self._v15_loaded = False
        self._v15_window_buffer: list[dict] = []   # ring buffer of last 7 window feat dicts
        self._v15_shadow = {}            # latest shadow prediction
        self._v15_history: list[dict] = []  # recent shadow predictions
        self._v15_warmup_windows = 0     # how many windows seen before first predict

        # ── V8 F2-spectral shadow-mode state ─────────────────────────
        # V8 = V7 + 30 F2 spectral features. Same seq_len, same HGB.
        # Runs alongside V5 production + V7 shadow — all results to telemetry only.
        self._v8_model = None
        self._v8_window_features: list[str] = []
        self._v8_class_names: list[str] = []
        self._v8_loaded = False
        self._v8_window_buffer: list[list[float]] = []
        self._v8_shadow = {}
        self._v8_history: list[dict] = []
        self._v8_warmup_windows = 0
        self._v8_prev_target = (0.0, 0.0)
        self._v8_node_baselines = {}

        # ── V19/V23 shadow-mode state ─────────────────────────────────
        # V21d promoted to production (2026-03-27). Same format as V20.
        # V21d = V20 base + zone one-hot features (zone_center, zone_transition,
        #   zone_door, zone_unknown). All gate criteria PASS, parity with V20.
        # Previously: v20_manifest_v18_candidate.pkl
        V19_MODEL_PATH = PROJECT / "output" / "train_runs" / "v21_dual_validated" / "v21d_candidate.pkl"
        self._v19_model_path = V19_MODEL_PATH
        self._v19_coarse_model = None
        self._v19_binary_model = None
        self._v19_window_features: list[str] = []
        self._v19_class_names: list[str] = []
        self._v19_seq_len = 7
        self._v19_loaded = False
        self._v19_window_buffer: list[dict] = []
        self._v19_shadow: dict = {}
        self._v19_gate_consecutive_below = 0   # hysteresis: consecutive windows below threshold
        self._v19_gate_consecutive_above = 0   # hysteresis: consecutive windows above threshold
        self._v19_gate_state = False            # current gate state (sticky)
        self._v19_history: list[dict] = []
        self._v19_warmup_windows = 0

        # ── V26 binary 7-node shadow state ────────────────────────────
        self._v26_model = None
        self._v26_scaler = None
        self._v26_features: list[str] = []
        self._v26_threshold = 0.50
        self._v26_loaded = False
        self._v26_shadow: dict = {}
        self._v26_history: list[dict] = []
        self._v26_candidate_name = V26_BINARY_7NODE_MODEL_PATH.name
        self._v26_track = "V42_binary_balanced"

        # ── Garage ratio V2 shadow candidate ─────────────────────────
        self._garage_ratio_v2_bundle = None
        self._garage_ratio_v2_model = None
        self._garage_ratio_v2_scaler = None
        self._garage_ratio_v2_feature_names: list[str] = []
        self._garage_ratio_v2_zone_names: list[str] = list(GARAGE_RATIO_ZONE_NAMES)
        self._garage_ratio_v2_thresholds: dict[str, float] = {}
        self._garage_ratio_v2_door_rescue: dict[str, Any] = {}
        self._garage_ratio_v2_runtime_smoothing: dict[str, Any] = {
            "enabled": GARAGE_RATIO_CAUSAL_SMOOTH_ENABLED,
            "mode": "causal_majority",
            "window": GARAGE_RATIO_CAUSAL_SMOOTH_WINDOW,
        }
        self._garage_ratio_v2_loaded = False
        self._garage_ratio_v2_shadow: dict = {}
        self._garage_ratio_v2_history: list[dict] = []

        # ── Old-router domain-adapt shadow-mode state ────────────────
        self._old_router_domain_adapt_model = None
        self._old_router_domain_adapt_window_features: list[str] = []
        self._old_router_domain_adapt_class_names: list[str] = []
        self._old_router_domain_adapt_loaded = False
        self._old_router_domain_adapt_window_buffer: list[list[float]] = []
        self._old_router_domain_adapt_shadow = {}
        self._old_router_domain_adapt_history: list[dict] = []
        self._old_router_domain_adapt_warmup_windows = 0

        # ── V29 CNN zone prediction shadow state ──────────────────────
        self._v29_cnn_model = None
        self._v29_cnn_feat_mean = None
        self._v29_cnn_feat_std = None
        self._v29_cnn_loaded = False
        self._v29_cnn_shadow: dict = {}
        self._v29_cnn_history: list[dict] = []

        # ── V30 fewshot zone production state ──────────────────────────
        self._v30_fewshot_model = None
        self._v30_fewshot_scaler = None
        self._v30_fewshot_feature_keys: list[str] = []
        self._v30_fewshot_loaded = False
        self._v30_fewshot_shadow: dict = {}
        self._v30_fewshot_history: list[dict] = []
        self._v30_fewshot_confirmed_zone: str = ""  # hysteresis: last confirmed zone
        self._v30_fewshot_pending_zone: str = ""     # candidate zone waiting for confirmation
        self._v30_fewshot_pending_count: int = 0     # consecutive windows candidate has led

        # ── V43 shadow test state (2026-03-28) ─────────────────────────
        # V43 coarse HGB (seq_len=7) shadow: runs alongside production,
        # logs predictions for offline comparison. Does NOT affect production.
        self._v43_coarse_model = None
        self._v43_binary_model = None
        self._v43_window_features: list[str] = []
        self._v43_class_names: list[str] = []
        self._v43_seq_len = V43_SHADOW_SEQ_LEN
        self._v43_loaded = False
        self._v43_window_buffer: list[list[float]] = []
        self._v43_shadow: dict = {}
        self._v43_history: list[dict] = []
        self._v43_warmup_windows = 0
        self._v43_window_count = 0
        self._v43_agree_count = 0
        self._v43_shadow_enabled = V43_SHADOW_ENABLED  # runtime-controllable flag

        # ── Zone calibration shadow state (per-session centroid) ────────
        # Shadow-only zone predictions from per-session NearestCentroid.
        # Does NOT affect V5 production output in any way.
        self._zone_calibration_shadow: dict = {}

        # ── Multi-person diagnostic estimator (non-production) ────────
        # Pragmatic heuristic that uses existing signals to estimate
        # whether more than one person is present.  This is a DIAGNOSTIC
        # layer — it must NEVER override the production single-target path.
        self._mp_estimate: dict = {
            "person_count_estimate": 1,
            "multi_person_state": "single",      # single | multi | unresolved
            "multi_person_confidence": 0.0,
            "diagnostic_tracks": [],              # list of candidate dicts
            "diagnostic_cluster_center": None,
            "diagnostic_cluster_radius": 0.0,
            "estimator_source": "runtime_heuristic",
        }

    # ── V23: Empty baseline calibration methods ─────────────────────

    _BASELINE_PATH = PROJECT / "output" / "empty_baseline_profiles.json"

    def _load_empty_baselines(self):
        """Load stored empty-room baseline profiles from disk."""
        if self._BASELINE_PATH.exists():
            try:
                with self._BASELINE_PATH.open() as f:
                    data = json.load(f)
                self._empty_baselines = data.get("profiles", {})
                logger.info(
                    "Empty baselines loaded: %d nodes, captured %s",
                    len(self._empty_baselines),
                    data.get("captured_at", "unknown"),
                )
            except Exception as e:
                logger.warning("Failed to load empty baselines: %s", e)

    def _save_empty_baselines(self):
        """Persist empty-room baseline profiles to disk."""
        data = {
            "profiles": self._empty_baselines,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "geometry": {
                "width": GARAGE_WIDTH,
                "height": GARAGE_HEIGHT,
                "nodes": {ip: list(pos) for ip, pos in NODE_POSITIONS.items()},
            },
        }
        self._BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._BASELINE_PATH.open("w") as f:
            json.dump(data, f, indent=2)
        logger.info("Empty baselines saved: %d nodes → %s", len(self._empty_baselines), self._BASELINE_PATH)

    def start_baseline_capture(self):
        """Begin accumulating empty-room statistics. Call when room is known empty."""
        self._baseline_capture_active = True
        self._baseline_capture_windows = defaultdict(list)
        logger.info("BASELINE CAPTURE STARTED — room must be empty")
        return {"status": "capturing", "message": "Collecting empty-room statistics..."}

    def stop_baseline_capture(self) -> dict:
        """Finalize baseline from captured windows. Returns summary."""
        self._baseline_capture_active = False
        if not self._baseline_capture_windows:
            return {"status": "error", "message": "No windows captured"}

        profiles = {}
        for ip, windows in self._baseline_capture_windows.items():
            if len(windows) < 3:
                continue
            amp_means = [w["amp_mean"] for w in windows]
            phase_rates = [w["phase_rate_mean"] for w in windows]
            sc_vars = [w["sc_var_mean"] for w in windows]
            profiles[ip] = {
                "amp_mean": float(np.mean(amp_means)),
                "amp_std": float(np.std(amp_means)),
                "phase_rate_mean": float(np.mean(phase_rates)),
                "phase_rate_std": float(np.std(phase_rates)),
                "sc_var_mean": float(np.mean(sc_vars)),
                "sc_var_std": float(np.std(sc_vars)),
                "window_count": len(windows),
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }

        self._empty_baselines = profiles
        self._save_empty_baselines()
        self._baseline_capture_windows = defaultdict(list)
        # Reset V19 gate hysteresis on baseline recapture — new baseline
        # invalidates old gate state since deviation thresholds are relative
        self._v19_gate_consecutive_below = 0
        self._v19_gate_consecutive_above = 0
        self._v19_gate_state = False
        logger.info("V19 gate hysteresis reset on baseline recapture")
        return {
            "status": "ok",
            "nodes_calibrated": len(profiles),
            "profiles": {ip: {k: round(v, 4) if isinstance(v, float) else v
                              for k, v in p.items()}
                         for ip, p in profiles.items()},
        }

    def _record_baseline_window(self, ip: str, feat: dict, pre: str):
        """Record one window's stats during baseline capture."""
        if not self._baseline_capture_active:
            return
        self._baseline_capture_windows[ip].append({
            "amp_mean": feat.get(f"{pre}_mean", 0),
            "phase_rate_mean": feat.get(f"{pre}_phase_rate_mean", 0),
            "sc_var_mean": feat.get(f"{pre}_sc_var_mean", 0),
        })

    def get_baseline_status(self) -> dict:
        """Return current empty baseline state for API."""
        return {
            "calibrated": bool(self._empty_baselines),
            "capturing": self._baseline_capture_active,
            "capture_windows": {ip: len(ws) for ip, ws in self._baseline_capture_windows.items()},
            "profiles": {ip: {
                "amp_mean": round(p.get("amp_mean", 0), 3),
                "sc_var_mean": round(p.get("sc_var_mean", 0), 3),
                "window_count": p.get("window_count", 0),
                "captured_at": p.get("captured_at", ""),
            } for ip, p in self._empty_baselines.items()},
        }

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

    async def ensure_started(self, interval: float = 2.0) -> dict[str, Any]:
        """Ensure the CSI listener and prediction loop are running.

        This is the canonical idempotent hook for backend startup and manual
        CSI control paths. It loads a model on demand, starts the UDP listener,
        and creates exactly one prediction loop task.
        """
        if not self.binary_model:
            if not self.load_model():
                return {
                    "ok": False,
                    "status": "model_not_loaded",
                    "listener_running": self._running,
                    "prediction_task_running": bool(self._prediction_task and not self._prediction_task.done()),
                }

        started_listener = False
        if not self._running:
            await self.start_udp_listener()
            started_listener = True

        loop_started = False
        if self._prediction_task is None or self._prediction_task.done():
            self._prediction_task = asyncio.create_task(self.prediction_loop(interval=interval))
            loop_started = True

        return {
            "ok": True,
            "status": "started" if (started_listener or loop_started) else "already_running",
            "model_version": self.current.get("model_version"),
            "listener_running": self._running,
            "prediction_task_running": bool(self._prediction_task and not self._prediction_task.done()),
        }

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
            pkts = [(t, a) for t, _r, a, _p in self._packets.get(ip, [])
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
                           for t, _, _, _ in self._packets.get(ip, []))
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

    # ── V29 CNN zone prediction methods ─────────────────────────────

    def _load_v29_cnn(self) -> bool:
        """Load V29 ImprovedCNN1D zone model. Safe to call repeatedly."""
        if self._v29_cnn_loaded:
            return True
        if not V29_CNN_SHADOW_ENABLED or not V29_CNN_MODEL_PATH.exists():
            return False
        try:
            import torch
            checkpoint = torch.load(V29_CNN_MODEL_PATH, map_location="cpu", weights_only=False)
            self._v29_cnn_feat_mean = checkpoint["feat_mean"]
            self._v29_cnn_feat_std = checkpoint["feat_std"]

            # Reconstruct model
            import torch.nn as nn
            import torch.nn.functional as F

            class ImprovedCNN1D(nn.Module):
                def __init__(self, in_channels=208, n_classes=3, hidden=96, dropout=0.3):
                    super().__init__()
                    self.conv1 = nn.Conv1d(in_channels, hidden, kernel_size=7, padding=3)
                    self.bn1 = nn.BatchNorm1d(hidden)
                    self.conv2 = nn.Conv1d(hidden, hidden, kernel_size=5, padding=2)
                    self.bn2 = nn.BatchNorm1d(hidden)
                    self.conv3 = nn.Conv1d(hidden, hidden, kernel_size=3, padding=1)
                    self.bn3 = nn.BatchNorm1d(hidden)
                    self.conv4 = nn.Conv1d(hidden, hidden // 2, kernel_size=3, padding=1)
                    self.bn4 = nn.BatchNorm1d(hidden // 2)
                    self.drop = nn.Dropout(dropout)
                    self.fc = nn.Linear(hidden // 2, n_classes)
                    self.res_proj = nn.Conv1d(hidden, hidden, kernel_size=1)

                def forward(self, x):
                    x = x.transpose(1, 2)
                    x = self.drop(F.relu(self.bn1(self.conv1(x))))
                    res = x
                    x = self.drop(F.relu(self.bn2(self.conv2(x))))
                    x = x + self.res_proj(res)
                    x = self.drop(F.relu(self.bn3(self.conv3(x))))
                    x = self.drop(F.relu(self.bn4(self.conv4(x))))
                    x = x.mean(dim=2)
                    return self.fc(x)

            in_ch = checkpoint.get("in_channels", 208)
            n_cl = checkpoint.get("n_classes", 3)
            model = ImprovedCNN1D(in_channels=in_ch, n_classes=n_cl)
            model.load_state_dict(checkpoint["model_state_dict"])
            model.eval()
            self._v29_cnn_model = model
            self._v29_cnn_loaded = True
            logger.info("V29 CNN zone model loaded: %s (%d ch, %d classes)",
                        V29_CNN_MODEL_PATH.name, in_ch, n_cl)
            return True
        except Exception as e:
            logger.warning("V29 CNN zone model load failed: %s", e)
            self._v29_cnn_model = None
            self._v29_cnn_loaded = False
            return False

    def _build_v29_raw_window(self, t_start: float, t_end: float) -> np.ndarray | None:
        """Build raw CSI tensor [40, 208] for V29 CNN zone prediction.

        Uses 52 subcarriers (indices 2-53) per node × 4 nodes = 208 channels.
        Pad/truncate to 40 time steps per node.
        """
        parts = []
        nodes_with_data = 0

        for ip in V29_CNN_IP_ORDER:
            pkts = [(t, a) for t, _r, a, _p in self._packets.get(ip, [])
                    if t_start <= t < t_end]

            if len(pkts) >= 3:
                nodes_with_data += 1
                # Build amplitude matrix [n_packets, 128+], select SC 2-53
                amp_mat = np.array([a for _, a in pkts], dtype=np.float32)
                if amp_mat.shape[1] >= V29_CNN_SC_END:
                    sc_mat = amp_mat[:, V29_CNN_SC_START:V29_CNN_SC_END]
                else:
                    padded = np.zeros((amp_mat.shape[0], V29_CNN_SC_END), dtype=np.float32)
                    padded[:, :amp_mat.shape[1]] = amp_mat
                    sc_mat = padded[:, V29_CNN_SC_START:V29_CNN_SC_END]
                sc_mat = self._pad_or_truncate(sc_mat, V29_CNN_MAX_PACKETS)
            else:
                sc_mat = np.zeros((V29_CNN_MAX_PACKETS, V29_CNN_N_SC), dtype=np.float32)

            parts.append(sc_mat)

        if nodes_with_data < 2:
            return None

        return np.concatenate(parts, axis=1).astype(np.float32)  # [40, 208]

    def _shadow_predict_v29_zone(self, t_start: float, t_end: float,
                                   w_end: float) -> dict | None:
        """Run V29 CNN zone inference in shadow mode. Never affects production."""
        if not self._v29_cnn_loaded:
            if not self._load_v29_cnn():
                return None

        raw_window = self._build_v29_raw_window(t_start, t_end)
        if raw_window is None:
            return None

        try:
            import torch
            import torch.nn.functional as F

            # z-score normalize with training stats
            x = (raw_window - self._v29_cnn_feat_mean) / self._v29_cnn_feat_std
            x_tensor = torch.from_numpy(x).float().unsqueeze(0)  # [1, 40, 208]

            t0 = time.perf_counter()
            with torch.no_grad():
                logits = self._v29_cnn_model(x_tensor)
            inference_ms = (time.perf_counter() - t0) * 1000

            probs = F.softmax(logits, dim=1).squeeze(0).numpy()
            pred_idx = int(np.argmax(probs))
            pred_zone = V29_CNN_ZONE_NAMES[pred_idx]

            shadow = {
                "t": w_end,
                "model": "v29_cnn",
                "zone": pred_zone,
                "zone_idx": pred_idx,
                "probabilities": {
                    V29_CNN_ZONE_NAMES[i]: round(float(probs[i]), 4)
                    for i in range(len(V29_CNN_ZONE_NAMES))
                },
                "inference_ms": round(inference_ms, 2),
            }
            self._v29_cnn_shadow = shadow
            self._v29_cnn_history.append(shadow)
            if len(self._v29_cnn_history) > 60:
                self._v29_cnn_history = self._v29_cnn_history[-60:]

            logger.info(
                "V29 CNN ZONE: %s (door=%.3f center=%.3f deep=%.3f) %.1fms",
                pred_zone, probs[0], probs[1], probs[2], inference_ms)
            return shadow

        except Exception as e:
            logger.error("V29 CNN zone inference failed: %s", e)
            return None

    # ── V30 fewshot zone prediction (production) ────────────────────

    def _load_v30_fewshot(self) -> bool:
        """Load V30 fewshot zone calibration model (HGB + scaler)."""
        if self._v30_fewshot_loaded:
            return True
        if not V30_FEWSHOT_ZONE_ENABLED:
            return False
        if not V30_FEWSHOT_MODEL_PATH.exists():
            logger.warning("V30 fewshot: model not found at %s", V30_FEWSHOT_MODEL_PATH)
            return False
        try:
            import pickle
            with V30_FEWSHOT_MODEL_PATH.open("rb") as fh:
                bundle = pickle.load(fh)
            self._v30_fewshot_model = bundle["model"]
            self._v30_fewshot_scaler = bundle["scaler"]
            self._v30_fewshot_feature_keys = bundle["feature_keys"]
            self._v30_fewshot_loaded = True
            logger.info(
                "V30 fewshot zone loaded: %d features, classes=%s",
                len(self._v30_fewshot_feature_keys),
                list(self._v30_fewshot_model.classes_),
            )
            return True
        except Exception as e:
            logger.error("V30 fewshot zone load failed: %s", e)
            return False

    def _predict_v30_fewshot_zone(self, feat_dict: dict, w_end: float) -> dict | None:
        """Run V34 fewshot zone prediction. Uses per-node AMP/motion features."""
        if not self._v30_fewshot_loaded:
            if not self._load_v30_fewshot():
                return None
        try:
            t0 = time.perf_counter()
            row = []
            for k in self._v30_fewshot_feature_keys:
                v = feat_dict.get(k, 0.0)
                try:
                    row.append(float(v) if v is not None else 0.0)
                except (TypeError, ValueError):
                    row.append(0.0)

            x = np.array([row])
            xs = self._v30_fewshot_scaler.transform(x)
            pred = self._v30_fewshot_model.predict(xs)[0]

            # Get probabilities
            probs_dict = {}
            if hasattr(self._v30_fewshot_model, "predict_proba"):
                proba = self._v30_fewshot_model.predict_proba(xs)[0]
                classes = list(self._v30_fewshot_model.classes_)
                probs_dict = {
                    str(classes[i]): round(float(proba[i]), 4)
                    for i in range(len(classes))
                }
            inference_ms = (time.perf_counter() - t0) * 1000

            # ── Hysteresis: smooth + require N consecutive wins to switch zone ──
            SMOOTH_N = 5          # averaging window
            HYSTERESIS_N = 3      # consecutive windows new zone must lead
            HYSTERESIS_MARGIN = 0.0  # no margin — any lead counts

            raw_shadow = {
                "t": w_end,
                "model": "v30_fewshot",
                "zone": str(pred),
                "probabilities": probs_dict,
                "inference_ms": round(inference_ms, 2),
            }
            self._v30_fewshot_history.append(raw_shadow)
            if len(self._v30_fewshot_history) > 60:
                self._v30_fewshot_history = self._v30_fewshot_history[-60:]

            # Average probabilities over recent windows
            recent = self._v30_fewshot_history[-SMOOTH_N:]
            if len(recent) >= 3 and all(h.get("probabilities") for h in recent):
                all_classes = list(recent[-1]["probabilities"].keys())
                avg_probs = {}
                for cls in all_classes:
                    avg_probs[cls] = round(
                        sum(h["probabilities"].get(cls, 0.0) for h in recent) / len(recent), 4
                    )
            else:
                avg_probs = probs_dict

            smoothed_winner = max(avg_probs, key=avg_probs.get)

            # Initialize confirmed zone on first prediction
            if not self._v30_fewshot_confirmed_zone:
                self._v30_fewshot_confirmed_zone = smoothed_winner

            # Hysteresis logic
            if smoothed_winner == self._v30_fewshot_confirmed_zone:
                # Same as confirmed — reset pending
                self._v30_fewshot_pending_zone = ""
                self._v30_fewshot_pending_count = 0
            else:
                # Different zone is leading — check margin
                confirmed_prob = avg_probs.get(self._v30_fewshot_confirmed_zone, 0)
                winner_prob = avg_probs.get(smoothed_winner, 0)
                if winner_prob - confirmed_prob > HYSTERESIS_MARGIN:
                    if smoothed_winner == self._v30_fewshot_pending_zone:
                        self._v30_fewshot_pending_count += 1
                    else:
                        self._v30_fewshot_pending_zone = smoothed_winner
                        self._v30_fewshot_pending_count = 1

                    if self._v30_fewshot_pending_count >= HYSTERESIS_N:
                        self._v30_fewshot_confirmed_zone = smoothed_winner
                        self._v30_fewshot_pending_zone = ""
                        self._v30_fewshot_pending_count = 0
                else:
                    self._v30_fewshot_pending_count = 0

            output_zone = self._v30_fewshot_confirmed_zone

            shadow = {
                "t": w_end,
                "model": "v30_fewshot",
                "zone": output_zone,
                "probabilities": avg_probs,
                "inference_ms": round(inference_ms, 2),
            }
            self._v30_fewshot_shadow = shadow

            logger.info(
                "V30 FEWSHOT ZONE: %s (raw=%s pending=%s/%d) probs=%s %.1fms",
                output_zone, smoothed_winner,
                self._v30_fewshot_pending_zone, self._v30_fewshot_pending_count,
                avg_probs, inference_ms,
            )
            return shadow
        except Exception as e:
            logger.error("V30 fewshot zone inference failed: %s", e)
            return None

    # ── V7 warehouse-bound canonical shadow-mode methods ────────────

    def _load_v15_shadow(self) -> bool:
        """Load V8 canonical sequence model for shadow inference.

        Safe to call repeatedly — skips if already loaded or artifacts missing.
        Never affects V5 production inference.
        """
        if self._v15_loaded:
            return True
        if not V7_SHADOW_ENABLED:
            return False
        if not V7_MODEL_PATH.exists() or not V7_METADATA_PATH.exists():
            logger.warning(
                "V7 shadow: missing artifact(s): model=%s metadata=%s",
                V7_MODEL_PATH.exists(),
                V7_METADATA_PATH.exists(),
            )
            return False

        try:
            with V7_MODEL_PATH.open("rb") as fh:
                model = pickle.load(fh)
            metadata = json.loads(V7_METADATA_PATH.read_text(encoding="utf-8"))
            base_metadata = {}
            if V7_METADATA_PATH.exists():
                base_metadata = json.loads(V7_METADATA_PATH.read_text(encoding="utf-8"))
            base_feature_columns = list(base_metadata.get("dataset", {}).get("feature_columns", []))
            f2_features = list(metadata.get("feature_surface", {}).get("f2_features", []))

            self._v15_model_bundle = {"metadata": metadata}
            self._v15_binary_model = None
            self._v15_coarse_model = model
            self._v15_window_features = base_feature_columns + f2_features
            self._v15_class_names = metadata.get("class_names", ["EMPTY", "MOTION", "STATIC"])
            seq_len = int(metadata.get("feature_surface", {}).get("seq_len", V8_SEQ_LEN) or V8_SEQ_LEN)

            self._v15_loaded = True
            logger.info(
                "V8 shadow loaded: name=%s, window_features=%d, seq_len=%d, "
                "n_sequences=%s, cv_macro_f1=%s",
                metadata.get("name", "?"),
                len(self._v15_window_features),
                seq_len,
                metadata.get("dataset", {}).get("total_sequences", "?"),
                metadata.get("metrics", {}).get("macro_f1", metadata.get("comparison_to_v7", {}).get("macro_f1", "?")),
            )
            return True
        except Exception as e:
            logger.error("V8 shadow load failed: %s", e)
            self._v15_model_bundle = None
            self._v15_binary_model = None
            self._v15_coarse_model = None
            self._v15_class_names = []
            return False

    @staticmethod
    def _add_v8_f2_features(feat_dict: dict) -> dict:
        """Exact F2 spectral/distribution runtime feature augmentation."""
        out = dict(feat_dict)
        snrs = []
        for ni in range(4):
            pre = f"n{ni}"
            mean = float(out.get(f"{pre}_mean", 0.0) or 0.0)
            std = float(out.get(f"{pre}_std", 0.0) or 0.0)
            rng = float(out.get(f"{pre}_range", 0.0) or 0.0)
            diff1 = float(out.get(f"{pre}_diff1", 0.0) or 0.0)
            tvar = float(out.get(f"{pre}_tvar", 0.0) or 0.0)
            bldev = float(out.get(f"{pre}_bldev", 0.0) or 0.0)
            amp_skew = float(out.get(f"{pre}_amp_skew", 0.0) or 0.0)
            kurt = float(out.get(f"{pre}_kurtosis", 0.0) or 0.0)
            pca_effdim = float(out.get(f"{pre}_pca_effdim", 0.0) or 0.0)
            denom_mean = mean + 1e-10
            snr = mean / (std + 1e-10)
            out[f"{pre}_snr"] = float(snr)
            out[f"{pre}_norm_range"] = float(rng / denom_mean)
            out[f"{pre}_rel_diff1"] = float(diff1 / denom_mean)
            out[f"{pre}_ctv"] = float(tvar / (mean ** 2 + 1e-10))
            out[f"{pre}_rel_bldev"] = float(bldev / denom_mean)
            out[f"{pre}_shape_score"] = float(abs(kurt) * abs(amp_skew))
            out[f"{pre}_pca_norm"] = float(pca_effdim / 85.0)
            snrs.append(snr)
        if snrs:
            snrs_np = np.array(snrs, dtype=np.float32)
            out["x_snr_cv"] = float(snrs_np.std() / (snrs_np.mean() + 1e-10))
            out["x_snr_min"] = float(snrs_np.min())
        else:
            out["x_snr_cv"] = 0.0
            out["x_snr_min"] = 0.0
        return out

    @staticmethod
    def _add_old_router_domain_adapt_guard_features(feat_dict: dict) -> dict:
        """Compute the 13 guard features used by V16/V18/domain-adapt."""
        out = dict(feat_dict)

        per_node_pps = [float(out.get(f"n{i}_pps", 0) or 0) for i in range(4)]
        min_pps = min(per_node_pps) if per_node_pps else 0.0
        max_pps = max(per_node_pps) if per_node_pps else 0.0
        pps_arr = np.array(per_node_pps, dtype=np.float32) if per_node_pps else np.zeros(4, dtype=np.float32)
        out["gh_min_pps"] = float(min_pps)
        out["gh_max_pps"] = float(max_pps)
        out["gh_pps_imbalance"] = float(max_pps / (min_pps + 1e-10))
        out["gh_degraded_node_count"] = float(sum(1 for p in per_node_pps if p < NODE_HEALTH_MIN_PPS))
        out["gh_node_health_score"] = float(np.clip(1.0 / ((max_pps / (min_pps + 1e-10)) + 1e-10), 0, 1))
        out["gh_pps_std"] = float(pps_arr.std())

        tvar_hi_vals = [float(out.get(f"n{i}_tvar_hi", 0) or 0) for i in range(4)]
        tvar_hi_arr = np.array(tvar_hi_vals, dtype=np.float32) if tvar_hi_vals else np.zeros(4, dtype=np.float32)
        max_tvar_n01 = max(tvar_hi_vals[0], tvar_hi_vals[1]) if len(tvar_hi_vals) >= 2 else 0.0
        x_tvar_mean = float(out.get("x_tvar_mean", 0) or 0)
        if x_tvar_mean == 0:
            tvar_vals = [float(out.get(f"n{i}_tvar", 0) or 0) for i in range(4)]
            x_tvar_mean = float(sum(tvar_vals) / max(len(tvar_vals), 1))
        out["gv_max_tvar_hi_n01"] = float(max_tvar_n01)
        out["gv_sc_var_ratio"] = float(max_tvar_n01 / (x_tvar_mean + 1e-10))
        out["gv_sc_var_noise_score"] = float(
            (max_tvar_n01 > SC_VAR_HI_THRESHOLD) and (x_tvar_mean < SC_VAR_MOTION_TVAR_CEILING)
        )
        out["gv_max_tvar_hi_all"] = float(tvar_hi_arr.max()) if len(tvar_hi_arr) else 0.0
        out["gv_tvar_hi_std"] = float(tvar_hi_arr.std())

        node_trigger = float((min_pps < NODE_HEALTH_MIN_PPS) and (max_pps > NODE_HEALTH_MAX_PPS))
        out["ge_composite"] = float(np.clip(node_trigger + out["gv_sc_var_noise_score"], 0, 1))
        out["ge_low_motion_high_noise"] = float(
            (x_tvar_mean < SC_VAR_MOTION_TVAR_CEILING) and (max_tvar_n01 > SC_VAR_HI_THRESHOLD * 0.8)
        )
        return out

    # ── V19/V23 shadow methods ──────────────────────────────────────

    def _load_v19_shadow(self) -> bool:
        """Load V21d model (V23 + zone features) for production inference."""
        if self._v19_loaded:
            return True
        if not self._v19_model_path.exists():
            return False
        try:
            with self._v19_model_path.open("rb") as fh:
                bundle = pickle.load(fh)
            self._v19_coarse_model = bundle.get("coarse_model")
            self._v19_binary_model = bundle.get("binary_model")
            self._v19_window_features = bundle.get("window_feature_names", [])
            self._v19_class_names = bundle.get("coarse_labels", ["EMPTY", "MOTION", "STATIC"])
            self._v19_seq_len = bundle.get("seq_len", 7)
            self._v19_loaded = True
            logger.info(
                "V19 shadow loaded: window_features=%d, seq_len=%d, version=%s",
                len(self._v19_window_features), self._v19_seq_len,
                bundle.get("version", "?"),
            )
            return True
        except Exception as e:
            logger.error("V19 shadow load failed: %s", e)
            return False

    def _add_v23_guard_features(self, feat_dict: dict) -> dict:
        """Add V23 guard features to a window feature dict for V19 shadow."""
        out = dict(feat_dict)
        EPS = 1e-10

        # Node health guards (same as V18)
        pps_vals = [float(out.get(f"n{i}_pps", 0) or 0) for i in range(4)]
        min_pps = min(pps_vals)
        max_pps = max(pps_vals)
        out["gh_min_pps"] = min_pps
        out["gh_max_pps"] = max_pps
        out["gh_pps_imbalance"] = max_pps / (min_pps + EPS)
        out["gh_degraded_node_count"] = float(sum(1 for p in pps_vals if p < 15))
        out["gh_node_health_score"] = min(1.0, 1.0 / (max_pps / (min_pps + EPS) + EPS))
        out["gh_pps_std"] = float(np.std(pps_vals))

        # SC var guards
        tvar_hi = [float(out.get(f"n{i}_tvar_hi", 0) or 0) for i in range(4)]
        max_tvar_n01 = max(tvar_hi[0], tvar_hi[1])
        x_tvar = float(out.get("x_tvar_mean", 0) or 0)
        out["gv_max_tvar_hi_n01"] = max_tvar_n01
        out["gv_sc_var_ratio"] = max_tvar_n01 / (x_tvar + EPS)
        out["gv_sc_var_noise_score"] = float(max_tvar_n01 > 3.8 and x_tvar < 1.5)
        out["gv_max_tvar_hi_all"] = max(tvar_hi)
        out["gv_tvar_hi_std"] = float(np.std(tvar_hi))

        # Composite
        node_trigger = float(min_pps < 15 and max_pps > 25)
        out["ge_composite"] = min(1.0, node_trigger + out["gv_sc_var_noise_score"])
        out["ge_low_motion_high_noise"] = float(x_tvar < 1.5 and max_tvar_n01 > 3.8 * 0.8)

        # V23 guards
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

        out["ge_v23_composite"] = min(1.0,
            out["ge_composite"] + out["gp_phase_noise_score"] +
            out["gd_drift_noise_score"] + out["gs_dead_sc_score"])

        return out

    # ── V26 binary 7-node shadow methods ────────────────────────────

    def _load_v26_shadow(self) -> bool:
        """Load current 7-node binary shadow candidate without touching primary runtime."""
        if self._v26_loaded:
            return True
        if not V26_BINARY_7NODE_MODEL_PATH.exists():
            return False
        try:
            with V26_BINARY_7NODE_MODEL_PATH.open("rb") as fh:
                bundle = pickle.load(fh)
            self._v26_model = bundle["model"]
            self._v26_scaler = bundle.get("scaler")  # V40+ includes StandardScaler
            self._v26_features = bundle["feature_columns"]
            self._v26_threshold = float(bundle.get("threshold", 0.50))
            self._v26_candidate_name = V26_BINARY_7NODE_MODEL_PATH.name
            self._v26_track = str(bundle.get("version", "V26_binary_7node"))
            self._v26_loaded = True
            logger.info(
                "Binary shadow loaded: candidate=%s features=%d, threshold=%.3f, version=%s",
                self._v26_candidate_name,
                len(self._v26_features), self._v26_threshold,
                self._v26_track,
            )
            return True
        except Exception as e:
            logger.error("V26 shadow load failed: %s", e)
            return False

    def _shadow_predict_v26(self, feat_dict: dict, w_end: float,
                            track_a_binary: str) -> dict | None:
        """Run V26 binary shadow inference. Single-window, no sequence buffer."""
        if not V26_BINARY_SHADOW_ENABLED:
            return None
        if not self._v26_loaded:
            if not self._load_v26_shadow():
                return None
        try:
            X = np.array(
                [[float(feat_dict.get(f, 0) or 0) for f in self._v26_features]],
                dtype=np.float32,
            )
            X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)
            if self._v26_scaler is not None:
                X = self._v26_scaler.transform(X)

            t0 = time.perf_counter()
            proba = self._v26_model.predict_proba(X)[0]
            inference_ms = (time.perf_counter() - t0) * 1000

            # proba[1] = P(occupied)
            p_occ = float(proba[1]) if len(proba) > 1 else float(proba[0])
            binary_label = "occupied" if p_occ >= self._v26_threshold else "empty"

            shadow = {
                "track": self._v26_track,
                "candidate_name": self._v26_candidate_name,
                "loaded": True,
                "status": "shadow_live",
                "binary": binary_label,
                "binary_proba": round(p_occ, 4),
                "threshold": self._v26_threshold,
                "agree_binary": binary_label == track_a_binary,
                "inference_ms": round(inference_ms, 2),
                "window_t": round(w_end, 2),
            }
            self._v26_shadow = shadow
            self._v26_history.append(shadow)
            if len(self._v26_history) > 50:
                self._v26_history = self._v26_history[-30:]

            logger.debug(
                "V26 SHADOW: %s P(occ)=%.4f agree=%s %.1fms",
                binary_label, p_occ, shadow["agree_binary"], inference_ms,
            )
            return shadow
        except Exception as e:
            logger.warning("V26 shadow predict error: %s", e)
            return None

    # ── V43 shadow test methods (2026-03-28) ────────────────────────

    def enable_v43_shadow(self) -> dict:
        """Enable V43 shadow at runtime (no restart needed)."""
        loaded = self._load_v43_shadow()
        if not loaded:
            return {
                "status": "error",
                "detail": f"V43 model not found at {V43_SHADOW_MODEL_PATH}",
            }
        self._v43_shadow_enabled = True
        logger.info("V43 shadow ENABLED via API (runtime hot-reload)")
        return {
            "status": "enabled",
            "model": "v43_binary_candidate",
            "model_path": str(V43_SHADOW_MODEL_PATH),
            "seq_len": self._v43_seq_len,
            "classes": self._v43_class_names,
        }

    def disable_v43_shadow(self) -> dict:
        """Disable V43 shadow at runtime."""
        self._v43_shadow_enabled = False
        logger.info("V43 shadow DISABLED via API")
        return {"status": "disabled"}

    def get_v43_shadow_status(self) -> dict:
        """Return current V43 shadow state for the status endpoint."""
        agreement_rate = (
            self._v43_agree_count / self._v43_window_count
            if self._v43_window_count > 0
            else None
        )
        return {
            "enabled": self._v43_shadow_enabled,
            "model_loaded": self._v43_loaded,
            "model_path": str(V43_SHADOW_MODEL_PATH),
            "window_count": self._v43_window_count,
            "agree_count": self._v43_agree_count,
            "agreement_rate": round(agreement_rate, 4) if agreement_rate is not None else None,
            "seq_len": self._v43_seq_len,
            "classes": self._v43_class_names if self._v43_loaded else [],
            "last_shadow": self._v43_shadow or None,
        }

    def _load_v43_shadow(self) -> bool:
        """Load V43 coarse HGB model for shadow inference."""
        if self._v43_loaded:
            return True
        if not V43_SHADOW_MODEL_PATH.exists():
            logger.warning("V43 shadow model not found: %s", V43_SHADOW_MODEL_PATH)
            return False
        try:
            with V43_SHADOW_MODEL_PATH.open("rb") as fh:
                bundle = pickle.load(fh)
            self._v43_coarse_model = bundle.get("coarse_model")
            self._v43_binary_model = bundle.get("binary_model")
            self._v43_window_features = bundle.get("window_feature_names", [])
            self._v43_class_names = bundle.get("coarse_labels", ["EMPTY", "MOTION", "STATIC"])
            self._v43_seq_len = bundle.get("seq_len", V43_SHADOW_SEQ_LEN)
            self._v43_loaded = True
            logger.info(
                "V43 shadow loaded: window_features=%d, seq_len=%d, classes=%s, version=%s",
                len(self._v43_window_features), self._v43_seq_len,
                self._v43_class_names, bundle.get("version", "v43"),
            )
            # Ensure log directory exists
            V43_SHADOW_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error("V43 shadow load failed: %s", e)
            return False

    def _shadow_predict_v43(self, feat_dict: dict, w_end: float,
                            prod_coarse: str, prod_binary: str,
                            prod_binary_conf: float) -> dict | None:
        """Run V43 shadow inference. seq_len=7 coarse HGB model.

        Logs every prediction to shadow_log.jsonl for offline analysis.
        Does NOT affect production output.
        """
        if not self._v43_shadow_enabled:
            return None
        if not self._v43_loaded:
            if not self._load_v43_shadow():
                return None

        # Use the same feature augmentation as V19 (F2 + V23 guard + zone)
        augmented = self._add_v8_f2_features(feat_dict)
        augmented = self._add_v23_guard_features(augmented)
        augmented = self._add_v21d_zone_features(augmented)

        # Extract window features in correct order
        window_feats = [augmented.get(f, 0) for f in self._v43_window_features]
        self._v43_window_buffer.append(window_feats)
        self._v43_warmup_windows += 1

        if len(self._v43_window_buffer) > self._v43_seq_len:
            self._v43_window_buffer = self._v43_window_buffer[-self._v43_seq_len:]

        if len(self._v43_window_buffer) < self._v43_seq_len:
            return None

        try:
            X = np.array(
                [f for window in self._v43_window_buffer for f in window],
                dtype=np.float32,
            ).reshape(1, -1)
            X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

            t0 = time.perf_counter()
            coarse_proba = self._v43_coarse_model.predict_proba(X)[0]
            coarse_classes = list(self._v43_class_names)
            coarse_idx = int(np.argmax(coarse_proba))
            coarse_pred = str(coarse_classes[coarse_idx])

            empty_idx = coarse_classes.index("EMPTY") if "EMPTY" in coarse_classes else 0
            empty_proba = float(coarse_proba[empty_idx])
            v43_binary = "empty" if coarse_pred == "EMPTY" else "occupied"
            v43_binary_conf = empty_proba if v43_binary == "empty" else 1.0 - empty_proba

            inference_ms = (time.perf_counter() - t0) * 1000

            self._v43_window_count += 1
            agree_binary = v43_binary == prod_binary
            if agree_binary:
                self._v43_agree_count += 1
            agreement_rate = (
                self._v43_agree_count / self._v43_window_count
                if self._v43_window_count > 0 else 0.0
            )

            shadow = {
                "t": round(w_end, 2),
                "track": "V43_shadow",
                "predicted_class": coarse_pred,
                "binary": v43_binary,
                "binary_conf": round(v43_binary_conf, 4),
                "probabilities": {
                    str(cls): round(float(coarse_proba[i]), 4)
                    for i, cls in enumerate(coarse_classes)
                },
                "inference_ms": round(inference_ms, 2),
                "buffer_depth": len(self._v43_window_buffer),
                "agree_binary": agree_binary,
                "agree_coarse": coarse_pred.lower() == prod_coarse.lower(),
                "prod_binary": prod_binary,
                "prod_coarse": prod_coarse,
                "prod_binary_conf": round(prod_binary_conf, 4),
                "confidence_diff": round(v43_binary_conf - prod_binary_conf, 4),
                "window_id": self._v43_window_count,
                "agreement_rate": round(agreement_rate, 4),
            }
            self._v43_shadow = shadow
            self._v43_history.append(shadow)
            if len(self._v43_history) > 60:
                self._v43_history = self._v43_history[-60:]

            # Log to shadow file
            try:
                log_entry = {
                    "ts": time.time(),
                    **shadow,
                }
                with open(V43_SHADOW_LOG_PATH, "a") as sf:
                    sf.write(json.dumps(log_entry) + "\n")
            except Exception:
                pass  # logging must never crash runtime

            # Periodic summary every 100 windows
            if self._v43_window_count % 100 == 0:
                logger.info(
                    "V43 SHADOW SUMMARY [%d windows]: agreement=%.1f%% "
                    "v43_last=%s prod_last=%s",
                    self._v43_window_count,
                    agreement_rate * 100,
                    v43_binary, prod_binary,
                )

            logger.debug(
                "V43 SHADOW: %s (E=%.3f M=%.3f S=%.3f) bin=%s agree=%s %.1fms",
                coarse_pred,
                coarse_proba[coarse_classes.index("EMPTY")] if "EMPTY" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("MOTION")] if "MOTION" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("STATIC")] if "STATIC" in coarse_classes else 0,
                v43_binary, agree_binary, inference_ms,
            )
            return shadow
        except Exception as e:
            logger.warning("V43 shadow predict error: %s", e)
            return None

    def _add_v21d_zone_features(self, feat_dict: dict) -> dict:
        """Add V21d zone one-hot features based on fewshot/coordinate zone.

        V21d expects 4 zone columns: zone_center, zone_transition, zone_door,
        zone_unknown.  When a zone is known (from V30 fewshot calibration or
        the coordinate system), exactly one is set to 1.  Otherwise default
        to zone_unknown=1.
        """
        out = dict(feat_dict)
        zone = self._v30_fewshot_confirmed_zone  # e.g. "center", "door", ""
        zone_map = {
            "center": "zone_center",
            "transition": "zone_transition",
            "door": "zone_door",
        }
        # Reset all zone columns
        for col in ("zone_center", "zone_transition", "zone_door", "zone_unknown"):
            out[col] = 0.0
        matched = zone_map.get(zone)
        if matched:
            out[matched] = 1.0
        else:
            out["zone_unknown"] = 1.0
        return out

    def _shadow_predict_v19(self, feat_dict: dict, w_end: float,
                            track_a_coarse: str, track_a_binary: str) -> dict | None:
        """Run V21d production inference with V23 + zone features."""
        if not self._v19_loaded:
            if not self._load_v19_shadow():
                return None

        # Add F2 spectral features + V23 guard features + V21d zone one-hot
        augmented = self._add_v8_f2_features(feat_dict)
        augmented = self._add_v23_guard_features(augmented)
        augmented = self._add_v21d_zone_features(augmented)

        # Extract window features in correct order
        window_feats = [augmented.get(f, 0) for f in self._v19_window_features]
        self._v19_window_buffer.append(window_feats)
        self._v19_warmup_windows += 1

        if len(self._v19_window_buffer) > self._v19_seq_len:
            self._v19_window_buffer = self._v19_window_buffer[-self._v19_seq_len:]

        if len(self._v19_window_buffer) < self._v19_seq_len:
            return None

        try:
            X = np.array(
                [f for window in self._v19_window_buffer for f in window],
                dtype=np.float32,
            ).reshape(1, -1)
            X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

            t0 = time.perf_counter()
            coarse_proba = self._v19_coarse_model.predict_proba(X)[0]
            coarse_classes = list(self._v19_class_names)
            coarse_idx = int(np.argmax(coarse_proba))
            coarse_pred = str(coarse_classes[coarse_idx])

            empty_idx = coarse_classes.index("EMPTY") if "EMPTY" in coarse_classes else 0
            empty_proba = float(coarse_proba[empty_idx])
            binary_label = "empty" if coarse_pred == "EMPTY" else "occupied"
            binary_conf = empty_proba if binary_label == "empty" else 1.0 - empty_proba

            inference_ms = (time.perf_counter() - t0) * 1000

            # ── V19 empty gate: baseline-calibrated override ───────────
            # If baseline is calibrated and signal is close to empty-room
            # profile, override model's prediction to EMPTY.  Fixes the
            # motion-bias blind spot discovered in minipack1 eval.
            bl_amp_dev_max = float(augmented.get("x_baseline_amp_dev_max", 999))
            bl_sc_var_dev_max = float(augmented.get("x_baseline_sc_var_dev_max", 999))
            V19_EMPTY_GATE_AMP = 0.5   # stddevs from baseline (lowered: 1.2→0.5 to catch static person)
            V19_EMPTY_GATE_SC = 0.6    # stddevs (lowered: 1.3→0.6 — static person gives ~0.6σ deviation)
            V19_GATE_HYSTERESIS = 4    # consecutive windows required to switch state
            empty_gate_fired = False
            raw_coarse_pred = coarse_pred  # preserve original for telemetry

            if self._empty_baselines and coarse_pred != "EMPTY":
                below = (bl_amp_dev_max < V19_EMPTY_GATE_AMP
                         and bl_sc_var_dev_max < V19_EMPTY_GATE_SC)
                if below:
                    self._v19_gate_consecutive_below += 1
                    self._v19_gate_consecutive_above = 0
                else:
                    self._v19_gate_consecutive_above += 1
                    self._v19_gate_consecutive_below = 0

                # Hysteresis: only switch state after N consecutive windows
                if (self._v19_gate_consecutive_below >= V19_GATE_HYSTERESIS
                        and not self._v19_gate_state):
                    self._v19_gate_state = True
                    logger.info("V19 EMPTY GATE → ON (hysteresis: %d consecutive below)",
                                self._v19_gate_consecutive_below)
                elif (self._v19_gate_consecutive_above >= V19_GATE_HYSTERESIS
                      and self._v19_gate_state):
                    self._v19_gate_state = False
                    logger.info("V19 EMPTY GATE → OFF (hysteresis: %d consecutive above)",
                                self._v19_gate_consecutive_above)

                if self._v19_gate_state:
                    empty_gate_fired = True
                    coarse_pred = "EMPTY"
                    binary_label = "empty"
                    binary_conf = 1.0 - empty_proba
                    if bl_amp_dev_max < 1.0 and bl_sc_var_dev_max < 0.8:
                        binary_conf = max(binary_conf, 0.85)
                    logger.info(
                        "V19 EMPTY GATE fired: amp_dev=%.2f sc_dev=%.2f "
                        "raw_pred=%s → EMPTY (consec_below=%d)",
                        bl_amp_dev_max, bl_sc_var_dev_max, raw_coarse_pred,
                        self._v19_gate_consecutive_below,
                    )

            shadow = {
                "t": w_end,
                "track": "V19_shadow",
                "predicted_class": coarse_pred,
                "binary": binary_label,
                "probabilities": {
                    str(cls): round(float(coarse_proba[i]), 4)
                    for i, cls in enumerate(coarse_classes)
                },
                "binary_proba": round(binary_conf, 4),
                "inference_ms": round(inference_ms, 2),
                "buffer_depth": len(self._v19_window_buffer),
                "warmup_windows_seen": self._v19_warmup_windows,
                "agree_coarse": (coarse_pred.lower() == track_a_coarse.lower()),
                "agree_binary": (binary_label == track_a_binary),
                "empty_gate_fired": empty_gate_fired,
                "empty_gate_state": self._v19_gate_state,
                "raw_predicted_class": raw_coarse_pred if empty_gate_fired else None,
                "bl_amp_dev_max": round(bl_amp_dev_max, 3),
                "bl_sc_var_dev_max": round(bl_sc_var_dev_max, 3),
                "gate_consec_below": self._v19_gate_consecutive_below,
                "gate_consec_above": self._v19_gate_consecutive_above,
                "gate_config": {"amp": V19_EMPTY_GATE_AMP, "sc": V19_EMPTY_GATE_SC, "n": V19_GATE_HYSTERESIS},
            }
            self._v19_shadow = shadow
            self._v19_history.append(shadow)
            if len(self._v19_history) > 60:
                self._v19_history = self._v19_history[-60:]

            logger.info(
                "V19 SHADOW: %s (E=%.3f M=%.3f S=%.3f) bin=%s %.1fms "
                "agree_coarse=%s agree_bin=%s gate=%s bl_amp=%.2f bl_sc=%.2f",
                coarse_pred,
                coarse_proba[coarse_classes.index("EMPTY")] if "EMPTY" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("MOTION")] if "MOTION" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("STATIC")] if "STATIC" in coarse_classes else 0,
                binary_label, inference_ms,
                shadow["agree_coarse"], shadow["agree_binary"],
                empty_gate_fired, bl_amp_dev_max, bl_sc_var_dev_max,
            )
            return shadow
        except Exception as e:
            logger.warning("V19 shadow predict error: %s", e)
            return None

    def _shadow_predict_v15(self, feat_dict: dict, w_end: float,
                            track_a_coarse: str, track_a_binary: str) -> dict | None:
        """Run V7 shadow inference. Never affects production.

        Maintains a ring buffer of 7 window feature dicts (85 base only).
        Only predicts when buffer has seq_len windows.

        Returns shadow prediction dict or None if not ready.
        """
        if not self._v15_loaded:
            if not self._load_v15_shadow():
                return None

        # V7 uses only base 85 features — no F2 augmentation
        window_feats = [feat_dict.get(f, 0) for f in self._v15_window_features]

        # Push to ring buffer
        self._v15_window_buffer.append(window_feats)
        self._v15_warmup_windows += 1

        # Trim buffer to seq_len
        if len(self._v15_window_buffer) > V8_SEQ_LEN:
            self._v15_window_buffer = self._v15_window_buffer[-V8_SEQ_LEN:]

        # Not enough windows yet — report warmup status
        if len(self._v15_window_buffer) < V8_SEQ_LEN:
            remaining = V8_SEQ_LEN - len(self._v15_window_buffer)
            logger.debug(
                "V8 shadow: warming up, %d/%d windows buffered (%d more needed)",
                len(self._v15_window_buffer), V8_SEQ_LEN, remaining)
            return None

        try:
            # Flatten: [7 windows × 115 features] → [805]
            X = np.array(
                [f for window in self._v15_window_buffer for f in window],
                dtype=np.float32
            ).reshape(1, -1)
            X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

            t0 = time.perf_counter()

            # Coarse prediction (3-class)
            coarse_proba = self._v15_coarse_model.predict_proba(X)[0]
            coarse_classes = list(self._v15_class_names or ["EMPTY", "MOTION", "STATIC"])
            coarse_idx = int(np.argmax(coarse_proba))
            coarse_pred = str(coarse_classes[coarse_idx])

            # Derived binary prediction from coarse-only V7 artifact
            empty_idx = coarse_classes.index("EMPTY") if "EMPTY" in coarse_classes else 0
            empty_proba = float(coarse_proba[empty_idx]) if empty_idx < len(coarse_proba) else 0.0
            occupied_proba = float(max(0.0, 1.0 - empty_proba))
            binary_label = "empty" if coarse_pred == "EMPTY" else "occupied"
            binary_conf = empty_proba if binary_label == "empty" else occupied_proba

            inference_ms = (time.perf_counter() - t0) * 1000

            shadow = {
                "t": w_end,
                "track": "V8_shadow",
                "predicted_class": coarse_pred,
                "binary": binary_label,
                "probabilities": {
                    str(cls): round(float(coarse_proba[i]), 4)
                    for i, cls in enumerate(coarse_classes)
                },
                "binary_proba": round(binary_conf, 4),
                "inference_ms": round(inference_ms, 2),
                "buffer_depth": len(self._v15_window_buffer),
                "warmup_windows_seen": self._v15_warmup_windows,
                "agree_coarse": (coarse_pred.lower() == track_a_coarse.lower()),
                "agree_binary": (binary_label == track_a_binary),
            }
            self._v15_shadow = shadow
            self._v15_history.append(shadow)
            if len(self._v15_history) > 60:
                self._v15_history = self._v15_history[-60:]

            logger.info(
                "V8 SHADOW: %s (E=%.3f M=%.3f S=%.3f) bin=%s %.1fms "
                "agree_coarse=%s agree_bin=%s",
                coarse_pred,
                coarse_proba[coarse_classes.index("EMPTY")] if "EMPTY" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("MOTION")] if "MOTION" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("STATIC")] if "STATIC" in coarse_classes else 0,
                binary_label,
                inference_ms,
                shadow["agree_coarse"],
                shadow["agree_binary"],
            )
            return shadow

        except Exception as e:
            logger.error("V7 shadow inference failed: %s", e)
            return None

    # ── V8 F2-spectral shadow load + predict ─────────────────────────

    def _load_v8_shadow(self) -> bool:
        """Load V8 F2-spectral model for shadow inference."""
        if self._v8_loaded:
            return True
        if not V8_SHADOW_ENABLED:
            return False
        if not V8_MODEL_PATH.exists() or not V8_METADATA_PATH.exists():
            logger.warning("V8 shadow: missing artifact(s)")
            return False
        try:
            with V8_MODEL_PATH.open("rb") as fh:
                self._v8_model = pickle.load(fh)
            metadata = json.loads(V8_METADATA_PATH.read_text(encoding="utf-8"))
            self._v8_window_features = metadata.get("feature_surface", {}).get("f2_features", [])
            self._v8_class_names = metadata.get("class_names", ["EMPTY", "MOTION", "STATIC"])
            self._v8_loaded = True
            logger.info("V8 F2-spectral shadow loaded: features=115, f2=%d",
                        len(self._v8_window_features))
            return True
        except Exception as e:
            logger.error("V8 shadow load failed: %s", e)
            return False

    def _load_old_router_domain_adapt_shadow(self) -> bool:
        """Load old-router domain-adapt candidate for shadow inference."""
        if self._old_router_domain_adapt_loaded:
            return True
        if not OLD_ROUTER_DOMAIN_ADAPT_SHADOW_ENABLED:
            return False
        if not OLD_ROUTER_DOMAIN_ADAPT_MODEL_PATH.exists():
            logger.warning(
                "Old-router domain-adapt shadow: model not found: %s",
                OLD_ROUTER_DOMAIN_ADAPT_MODEL_PATH,
            )
            return False
        try:
            with OLD_ROUTER_DOMAIN_ADAPT_MODEL_PATH.open("rb") as fh:
                bundle = pickle.load(fh)
            self._old_router_domain_adapt_model = bundle["coarse_model"]
            self._old_router_domain_adapt_window_features = list(
                bundle.get("window_feature_names") or []
            )
            self._old_router_domain_adapt_class_names = list(
                bundle.get("coarse_labels") or ["EMPTY", "MOTION", "STATIC"]
            )
            self._old_router_domain_adapt_loaded = True
            logger.info(
                "Old-router domain-adapt shadow loaded: candidate=%s features=%d, seq_len=%s, version=%s",
                OLD_ROUTER_DOMAIN_ADAPT_CANDIDATE_NAME,
                len(self._old_router_domain_adapt_window_features),
                bundle.get("seq_len", OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN),
                bundle.get("version", "?"),
            )
            return True
        except Exception as e:
            logger.error("Old-router domain-adapt shadow load failed: %s", e)
            self._old_router_domain_adapt_model = None
            self._old_router_domain_adapt_window_features = []
            self._old_router_domain_adapt_class_names = []
            self._old_router_domain_adapt_loaded = False
            return False

    def _shadow_predict_v8(self, feat_dict: dict, w_end: float,
                           track_a_coarse: str, track_a_binary: str) -> dict | None:
        """Run V8 F2-spectral shadow inference. Never affects production.

        Uses V7 base features + F2 spectral augmentation = 115 per window.
        """
        if not self._v8_loaded:
            if not self._load_v8_shadow():
                return None
        # V7 base must be loaded for feature names
        if not self._v15_loaded:
            if not self._load_v15_shadow():
                return None

        # Compute F2 features on top of base
        feat_v8 = self._add_v8_f2_features(feat_dict)

        # Build 115-feature window vector: V7 base (85) + F2 (30)
        v7_names = self._v15_window_features
        f2_names = [f"n{ni}_{fn}" for ni in range(4) for fn in V8_F2_PER_NODE] + list(V8_F2_CROSS)
        all_names = list(v7_names) + f2_names
        window_vec = [feat_v8.get(f, 0) for f in all_names]

        self._v8_window_buffer.append(window_vec)
        self._v8_warmup_windows += 1
        if len(self._v8_window_buffer) > V8_SEQ_LEN:
            self._v8_window_buffer = self._v8_window_buffer[-V8_SEQ_LEN:]
        if len(self._v8_window_buffer) < V8_SEQ_LEN:
            return None

        try:
            X = np.array(
                [f for window in self._v8_window_buffer for f in window],
                dtype=np.float32
            ).reshape(1, -1)
            X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

            t0 = time.perf_counter()
            coarse_proba = self._v8_model.predict_proba(X)[0]
            coarse_classes = list(self._v8_class_names or ["EMPTY", "MOTION", "STATIC"])
            coarse_idx = int(np.argmax(coarse_proba))
            coarse_pred = str(coarse_classes[coarse_idx])

            empty_idx = coarse_classes.index("EMPTY") if "EMPTY" in coarse_classes else 0
            empty_proba = float(coarse_proba[empty_idx])
            binary_label = "empty" if coarse_pred == "EMPTY" else "occupied"
            binary_conf = empty_proba if binary_label == "empty" else 1.0 - empty_proba

            inference_ms = (time.perf_counter() - t0) * 1000
            target_x, target_y = 0.0, 0.0
            target_zone = "empty"
            if binary_label == "occupied":
                target_x, target_y = self._estimate_v8_shadow_target(feat_dict)
                if target_y < 1.5:
                    target_zone = "door"
                elif target_y > 5.0:
                    target_zone = "deep"
                else:
                    target_zone = "center"

            shadow = {
                "t": w_end,
                "track": "V8_F2_shadow",
                "predicted_class": coarse_pred,
                "binary": binary_label,
                "probabilities": {
                    str(cls): round(float(coarse_proba[i]), 4)
                    for i, cls in enumerate(coarse_classes)
                },
                "binary_proba": round(binary_conf, 4),
                "inference_ms": round(inference_ms, 2),
                "buffer_depth": len(self._v8_window_buffer),
                "warmup_windows_seen": self._v8_warmup_windows,
                "agree_coarse": (coarse_pred.lower() == track_a_coarse.lower()),
                "agree_binary": (binary_label == track_a_binary),
                "target_x": round(target_x, 2),
                "target_y": round(target_y, 2),
                "target_zone": target_zone,
                "coordinate_source": "v8_shadow_diagnostic",
            }
            self._v8_shadow = shadow
            self._v8_history.append(shadow)
            if len(self._v8_history) > 60:
                self._v8_history = self._v8_history[-60:]

            logger.info(
                "V8 F2 SHADOW: %s (E=%.3f M=%.3f S=%.3f) bin=%s %.1fms agree=%s",
                coarse_pred,
                coarse_proba[coarse_classes.index("EMPTY")] if "EMPTY" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("MOTION")] if "MOTION" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("STATIC")] if "STATIC" in coarse_classes else 0,
                binary_label, inference_ms, shadow["agree_coarse"],
            )
            return shadow
        except Exception as e:
            logger.error("V8 F2 shadow inference failed: %s", e)
            return None

    def _shadow_predict_old_router_domain_adapt(
        self, feat_dict: dict, w_end: float, track_a_coarse: str, track_a_binary: str
    ) -> dict | None:
        """Run old-router domain-adapt candidate in shadow mode."""
        if not self._old_router_domain_adapt_loaded:
            if not self._load_old_router_domain_adapt_shadow():
                return None

        feat_shadow = self._add_old_router_domain_adapt_guard_features(feat_dict)
        window_vec = [
            feat_shadow.get(f, 0) for f in self._old_router_domain_adapt_window_features
        ]
        self._old_router_domain_adapt_window_buffer.append(window_vec)
        self._old_router_domain_adapt_warmup_windows += 1
        if len(self._old_router_domain_adapt_window_buffer) > OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN:
            self._old_router_domain_adapt_window_buffer = (
                self._old_router_domain_adapt_window_buffer[-OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN:]
            )
        if len(self._old_router_domain_adapt_window_buffer) < OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN:
            return None

        try:
            X = np.array(
                [f for window in self._old_router_domain_adapt_window_buffer for f in window],
                dtype=np.float32,
            ).reshape(1, -1)
            X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

            t0 = time.perf_counter()
            coarse_proba = self._old_router_domain_adapt_model.predict_proba(X)[0]
            coarse_classes = list(self._old_router_domain_adapt_class_names or ["EMPTY", "MOTION", "STATIC"])
            coarse_idx = int(np.argmax(coarse_proba))
            coarse_pred = str(coarse_classes[coarse_idx])

            empty_idx = coarse_classes.index("EMPTY") if "EMPTY" in coarse_classes else 0
            empty_proba = float(coarse_proba[empty_idx])
            binary_label = "empty" if coarse_pred == "EMPTY" else "occupied"
            binary_conf = empty_proba if binary_label == "empty" else 1.0 - empty_proba
            inference_ms = (time.perf_counter() - t0) * 1000

            shadow = {
                "t": w_end,
                "track": "old_router_domain_adapt_shadow",
                "candidate_name": OLD_ROUTER_DOMAIN_ADAPT_CANDIDATE_NAME,
                "predicted_class": coarse_pred,
                "binary": binary_label,
                "probabilities": {
                    str(cls): round(float(coarse_proba[i]), 4)
                    for i, cls in enumerate(coarse_classes)
                },
                "binary_proba": round(binary_conf, 4),
                "inference_ms": round(inference_ms, 2),
                "buffer_depth": len(self._old_router_domain_adapt_window_buffer),
                "warmup_windows_seen": self._old_router_domain_adapt_warmup_windows,
                "agree_coarse": (coarse_pred.lower() == track_a_coarse.lower()),
                "agree_binary": (binary_label == track_a_binary),
                "guard_features_snapshot": {
                    key: round(float(feat_shadow.get(key, 0) or 0), 4)
                    for key in (
                        "gh_min_pps",
                        "gh_max_pps",
                        "gh_pps_imbalance",
                        "gh_degraded_node_count",
                        "gh_node_health_score",
                        "gh_pps_std",
                        "gv_max_tvar_hi_n01",
                        "gv_sc_var_ratio",
                        "gv_sc_var_noise_score",
                        "gv_max_tvar_hi_all",
                        "gv_tvar_hi_std",
                        "ge_composite",
                        "ge_low_motion_high_noise",
                    )
                },
            }
            self._old_router_domain_adapt_shadow = shadow
            self._old_router_domain_adapt_history.append(shadow)
            if len(self._old_router_domain_adapt_history) > 60:
                self._old_router_domain_adapt_history = self._old_router_domain_adapt_history[-60:]

            logger.info(
                "OLD ROUTER DOMAIN-ADAPT SHADOW: %s (E=%.3f M=%.3f S=%.3f) bin=%s %.1fms agree=%s",
                coarse_pred,
                coarse_proba[coarse_classes.index("EMPTY")] if "EMPTY" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("MOTION")] if "MOTION" in coarse_classes else 0,
                coarse_proba[coarse_classes.index("STATIC")] if "STATIC" in coarse_classes else 0,
                binary_label,
                inference_ms,
                shadow["agree_coarse"],
            )
            return shadow
        except Exception as e:
            logger.error("Old-router domain-adapt shadow inference failed: %s", e)
            return None

    def _estimate_v8_shadow_target(self, feat_dict: dict) -> tuple[float, float]:
        """Compute a diagnostic coordinate for V8 shadow presence without touching production state."""
        import math
        node_signals = []

        for ni, ip in enumerate(NODE_IPS):
            tvar = float(feat_dict.get(f"n{ni}_tvar", 0) or 0)
            std_val = float(feat_dict.get(f"n{ni}_std", 0) or 0)
            sc_var = float(feat_dict.get(f"n{ni}_sc_var_mean", 0) or 0)
            diff1 = float(feat_dict.get(f"n{ni}_diff1", 0) or 0)
            doppler = float(feat_dict.get(f"n{ni}_doppler_spread", 0) or 0)
            signal = tvar + std_val * 5.0 + sc_var * 0.5 + diff1 * 10.0 + doppler * 20.0

            if ip not in NODE_POSITIONS:
                continue

            key = f"n{ni}"
            baseline = self._v8_node_baselines.get(key)
            if baseline is None:
                self._v8_node_baselines[key] = signal
                deviation = 0.0
            else:
                self._v8_node_baselines[key] = 0.95 * baseline + 0.05 * signal
                next_baseline = self._v8_node_baselines[key]
                deviation = abs(signal - next_baseline) / next_baseline if next_baseline > 0 else 0.0

            node_signals.append((ip, deviation, NODE_POSITIONS[ip]))

        target_x, target_y = self._v8_prev_target
        if node_signals:
            weights = [max(d ** 2, 1e-9) for _, d, _ in node_signals]
            total_w = sum(weights)
            cx = sum(w * p[0] for w, (_, _, p) in zip(weights, node_signals)) / total_w
            cy = sum(w * p[1] for w, (_, _, p) in zip(weights, node_signals)) / total_w

            all_x = [p[0] for _, _, p in node_signals]
            all_y = [p[1] for _, _, p in node_signals]
            node_center_x = sum(all_x) / len(all_x)
            node_center_y = sum(all_y) / len(all_y)

            pull_x = cx - node_center_x
            pull_y = cy - node_center_y

            max_w = max(weights)
            concentration = max_w / total_w if total_w > 0 else 0.25
            extrap_scale = 1.0 + concentration * 3.0

            target_x = node_center_x + pull_x * extrap_scale
            target_y = node_center_y + pull_y * extrap_scale

        if self._v8_prev_target != (0.0, 0.0):
            dx = target_x - self._v8_prev_target[0]
            dy = target_y - self._v8_prev_target[1]
            dist = math.hypot(dx, dy)
            if dist < 0.05:
                target_x, target_y = self._v8_prev_target
            else:
                alpha = 0.45 if dist > 1.5 else 0.25 if dist > 0.5 else 0.15
                target_x = self._v8_prev_target[0] + dx * alpha
                target_y = self._v8_prev_target[1] + dy * alpha

        target_x = max(-GARAGE_WIDTH / 2, min(GARAGE_WIDTH / 2, target_x))
        target_y = max(0, min(GARAGE_HEIGHT, target_y))
        self._v8_prev_target = (target_x, target_y)
        return target_x, target_y

    def _load_garage_ratio_v2_shadow(self) -> bool:
        """Load the latest garage ratio candidate bundle for shadow inference."""
        if self._garage_ratio_v2_loaded:
            return True

        if not GARAGE_RATIO_V2_MODEL_PATH.exists():
            logger.info("Garage ratio shadow candidate not found: %s", GARAGE_RATIO_V2_MODEL_PATH)
            return False

        try:
            with GARAGE_RATIO_V2_MODEL_PATH.open("rb") as fh:
                bundle = pickle.load(fh)

            self._garage_ratio_v2_bundle = bundle
            self._garage_ratio_v2_model = bundle.get("model")
            self._garage_ratio_v2_scaler = bundle.get("scaler")
            self._garage_ratio_v2_feature_names = list(bundle.get("feature_names") or [])
            self._garage_ratio_v2_zone_names = list(bundle.get("zone_names") or GARAGE_RATIO_ZONE_NAMES)
            self._garage_ratio_v2_thresholds = dict(bundle.get("thresholds") or {})
            self._garage_ratio_v2_door_rescue = dict(bundle.get("v5_door_rescue") or {})
            self._garage_ratio_v2_runtime_smoothing = dict(
                bundle.get("runtime_smoothing")
                or {
                    "enabled": GARAGE_RATIO_CAUSAL_SMOOTH_ENABLED,
                    "mode": "causal_majority",
                    "window": GARAGE_RATIO_CAUSAL_SMOOTH_WINDOW,
                }
            )

            if self._garage_ratio_v2_model is None:
                raise RuntimeError("garage ratio shadow bundle missing model")
            if not self._garage_ratio_v2_feature_names:
                raise RuntimeError("garage ratio shadow bundle missing feature_names")

            self._garage_ratio_v2_loaded = True
            logger.info(
                "Garage ratio shadow loaded: %s (%d features)",
                bundle.get("candidate_name", "unknown"),
                len(self._garage_ratio_v2_feature_names),
            )
            return True
        except Exception as e:
            logger.error("Failed to load garage ratio shadow: %s", e)
            self._garage_ratio_v2_bundle = None
            self._garage_ratio_v2_model = None
            self._garage_ratio_v2_scaler = None
            self._garage_ratio_v2_feature_names = []
            self._garage_ratio_v2_zone_names = list(GARAGE_RATIO_ZONE_NAMES)
            self._garage_ratio_v2_thresholds = {}
            self._garage_ratio_v2_door_rescue = {}
            self._garage_ratio_v2_runtime_smoothing = {
                "enabled": GARAGE_RATIO_CAUSAL_SMOOTH_ENABLED,
                "mode": "causal_majority",
                "window": GARAGE_RATIO_CAUSAL_SMOOTH_WINDOW,
            }
            self._garage_ratio_v2_loaded = False
            return False

    @staticmethod
    def _build_garage_ratio_v2_feature_map(feat_dict: dict) -> dict:
        """Build the exact 40-feature ratio surface used by the garage candidate."""
        features: dict[str, float] = {}
        node_pairs = [(1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4)]
        nodes = [1, 2, 3, 4]

        for a, b in node_pairs:
            pa = f"csi_node{a:02d}"
            pb = f"csi_node{b:02d}"
            rssi_a = float(feat_dict.get(f"{pa}_rssi_mean", 0.0) or 0.0)
            rssi_b = float(feat_dict.get(f"{pb}_rssi_mean", 0.0) or 0.0)
            amp_a = max(float(feat_dict.get(f"{pa}_amp_mean", 0.0) or 0.0), 0.1)
            amp_b = max(float(feat_dict.get(f"{pb}_amp_mean", 0.0) or 0.0), 0.1)
            std_a = max(float(feat_dict.get(f"{pa}_rssi_std", 0.0) or 0.0), 0.01)
            std_b = max(float(feat_dict.get(f"{pb}_rssi_std", 0.0) or 0.0), 0.01)
            motion_a = float(feat_dict.get(f"{pa}_motion_mean", 0.0) or 0.0)
            motion_b = float(feat_dict.get(f"{pb}_motion_mean", 0.0) or 0.0)

            features[f"rssi_diff_{a}_{b}"] = rssi_a - rssi_b
            features[f"amp_ratio_{a}_{b}"] = amp_a / amp_b
            features[f"amp_log_ratio_{a}_{b}"] = float(np.log(amp_a / amp_b))
            features[f"rssi_std_ratio_{a}_{b}"] = std_a / std_b
            features[f"motion_diff_{a}_{b}"] = motion_a - motion_b

        rssi_vals = np.array(
            [float(feat_dict.get(f"csi_node{n:02d}_rssi_mean", 0.0) or 0.0) for n in nodes],
            dtype=np.float32,
        )
        amp_vals = np.array(
            [float(feat_dict.get(f"csi_node{n:02d}_amp_mean", 0.0) or 0.0) for n in nodes],
            dtype=np.float32,
        )

        features["rssi_range"] = float(rssi_vals.max() - rssi_vals.min()) if len(rssi_vals) else 0.0
        features["amp_range"] = float(amp_vals.max() - amp_vals.min()) if len(amp_vals) else 0.0
        features["rssi_argmax"] = float(rssi_vals.argmax()) if len(rssi_vals) else 0.0
        features["rssi_argmin"] = float(rssi_vals.argmin()) if len(rssi_vals) else 0.0
        features["amp_argmax"] = float(amp_vals.argmax()) if len(amp_vals) else 0.0
        features["amp_argmin"] = float(amp_vals.argmin()) if len(amp_vals) else 0.0

        features["deep_c_rssi_04_0103"] = float(
            feat_dict.get("csi_node04_rssi_mean", 0.0)
            - (feat_dict.get("csi_node01_rssi_mean", 0.0) + feat_dict.get("csi_node03_rssi_mean", 0.0)) / 2.0
        )
        features["deep_c_amp_04_0103"] = float(
            feat_dict.get("csi_node04_amp_mean", 0.0)
            - (feat_dict.get("csi_node01_amp_mean", 0.0) + feat_dict.get("csi_node03_amp_mean", 0.0)) / 2.0
        )
        features["deep_c_rssi_02_0103"] = float(
            feat_dict.get("csi_node02_rssi_mean", 0.0)
            - (feat_dict.get("csi_node01_rssi_mean", 0.0) + feat_dict.get("csi_node03_rssi_mean", 0.0)) / 2.0
        )
        features["deep_c_amp_02_0103"] = float(
            feat_dict.get("csi_node02_amp_mean", 0.0)
            - (feat_dict.get("csi_node01_amp_mean", 0.0) + feat_dict.get("csi_node03_amp_mean", 0.0)) / 2.0
        )
        return features

    def _apply_garage_ratio_v2_policy(self, probs: np.ndarray, production_zone: str) -> tuple[str, int, dict, bool]:
        """Apply class thresholds and V5 door rescue for the garage candidate."""
        thresholds = {
            "door": float(self._garage_ratio_v2_thresholds.get("t_door", 1.0) or 1.0),
            "center": float(self._garage_ratio_v2_thresholds.get("t_center", 1.0) or 1.0),
            "deep": float(self._garage_ratio_v2_thresholds.get("t_deep", 1.0) or 1.0),
        }
        adjusted = np.asarray(probs, dtype=np.float32).copy()
        adjusted[0] = adjusted[0] / max(thresholds["door"], 1e-6)
        adjusted[1] = adjusted[1] / max(thresholds["center"], 1e-6)
        adjusted[2] = adjusted[2] / max(thresholds["deep"], 1e-6)

        pred_idx = int(np.argmax(adjusted))
        pred_zone = self._garage_ratio_v2_zone_names[pred_idx]
        door_rescue_applied = False

        rescue_enabled = bool(self._garage_ratio_v2_door_rescue.get("enabled"))
        rescue_threshold = float(self._garage_ratio_v2_door_rescue.get("threshold", 0.05) or 0.05)
        if (
            rescue_enabled
            and production_zone == "door"
            and float(probs[0]) >= rescue_threshold
            and pred_zone != "door"
        ):
            pred_zone = "door"
            pred_idx = 0
            door_rescue_applied = True

        adjusted_scores = {
            self._garage_ratio_v2_zone_names[i]: round(float(adjusted[i]), 4)
            for i in range(min(len(adjusted), len(self._garage_ratio_v2_zone_names)))
        }
        return pred_zone, pred_idx, adjusted_scores, door_rescue_applied

    def _apply_garage_ratio_v2_causal_smoothing(self, raw_zone: str, raw_idx: int) -> tuple[str, int, dict]:
        """Apply trailing majority smoothing over the last garage shadow windows."""
        window = int(self._garage_ratio_v2_runtime_smoothing.get("window", GARAGE_RATIO_CAUSAL_SMOOTH_WINDOW) or GARAGE_RATIO_CAUSAL_SMOOTH_WINDOW)
        enabled = bool(self._garage_ratio_v2_runtime_smoothing.get("enabled", GARAGE_RATIO_CAUSAL_SMOOTH_ENABLED))
        self._garage_ratio_v2_history.append({"predicted_zone": raw_zone, "predicted_idx": int(raw_idx)})
        if len(self._garage_ratio_v2_history) > 60:
            self._garage_ratio_v2_history = self._garage_ratio_v2_history[-60:]

        if not enabled:
            return raw_zone, int(raw_idx), {
                "enabled": False,
                "mode": "disabled",
                "window": window,
                "count": 1,
                "ready": True,
                "applied": False,
                "raw_zone": raw_zone,
                "smoothed_zone": raw_zone,
                "counts": {raw_zone: 1},
            }

        recent = self._garage_ratio_v2_history[-window:]
        vote_idxs = [int(item["predicted_idx"]) for item in recent if item.get("predicted_idx") is not None]
        counts = np.bincount(vote_idxs, minlength=len(self._garage_ratio_v2_zone_names)) if vote_idxs else np.zeros(len(self._garage_ratio_v2_zone_names), dtype=int)
        max_count = int(counts.max()) if counts.size else 0
        winners = [idx for idx, count in enumerate(counts) if count == max_count and max_count > 0]
        if not winners:
            smooth_idx = int(raw_idx)
        elif len(winners) == 1:
            smooth_idx = int(winners[0])
        else:
            smooth_idx = int(raw_idx)
            for item in reversed(recent):
                idx = item.get("predicted_idx")
                if idx in winners:
                    smooth_idx = int(idx)
                    break

        smooth_zone = self._garage_ratio_v2_zone_names[smooth_idx]
        smoothing_meta = {
            "enabled": True,
            "mode": "causal_majority",
            "window": window,
            "count": len(vote_idxs),
            "ready": len(vote_idxs) >= window,
            "applied": smooth_idx != int(raw_idx),
            "raw_zone": raw_zone,
            "smoothed_zone": smooth_zone,
            "counts": {
                self._garage_ratio_v2_zone_names[idx]: int(counts[idx])
                for idx in range(min(len(counts), len(self._garage_ratio_v2_zone_names)))
            },
        }
        return smooth_zone, smooth_idx, smoothing_meta

    def _shadow_predict_garage_ratio_v2(
        self,
        feat_dict: dict,
        w_end: float,
        production_zone: str,
        binary_label: str,
        active_nodes: int,
        pkt_count: int,
    ) -> dict | None:
        """Run the latest garage ratio candidate in shadow mode."""
        if not self._garage_ratio_v2_loaded:
            if not self._load_garage_ratio_v2_shadow():
                return None

        base_shadow = {
            "t": w_end,
            "track": self._garage_ratio_v2_bundle.get("candidate_name", "GARAGE_RATIO_LAYER_V3_CANDIDATE"),
            "candidate_name": self._garage_ratio_v2_bundle.get("candidate_name", "GARAGE_RATIO_LAYER_V3_CANDIDATE"),
            "loaded": self._garage_ratio_v2_loaded,
            "production_zone": production_zone,
            "binary": binary_label,
            "active_nodes": int(active_nodes),
            "packets_in_window": int(pkt_count),
            "thresholds": dict(self._garage_ratio_v2_thresholds),
            "v5_door_rescue": dict(self._garage_ratio_v2_door_rescue),
            "runtime_smoothing": dict(self._garage_ratio_v2_runtime_smoothing),
        }

        if binary_label != "occupied":
            self._garage_ratio_v2_history = []
            shadow = {
                **base_shadow,
                "status": "empty_gate",
                "predicted_zone": "empty",
                "target_zone": "empty",
                "door_rescue_applied": False,
            }
            self._garage_ratio_v2_shadow = shadow
            return shadow

        node_packet_counts = {
            node_name: int(feat_dict.get(f"csi_{node_name}_packets", 0) or 0)
            for _, node_name in GARAGE_RATIO_NODE_ORDER
        }
        nodes_with_ratio = sum(1 for count in node_packet_counts.values() if count >= 5)
        if nodes_with_ratio < GARAGE_RATIO_MIN_ACTIVE_NODES:
            self._garage_ratio_v2_history = []
            shadow = {
                **base_shadow,
                "status": "insufficient_nodes",
                "predicted_zone": "unknown",
                "target_zone": "unknown",
                "nodes_with_ratio": nodes_with_ratio,
                "node_packets": node_packet_counts,
                "door_rescue_applied": False,
            }
            self._garage_ratio_v2_shadow = shadow
            return shadow

        ratio_features = self._build_garage_ratio_v2_feature_map(feat_dict)
        X = np.array(
            [[float(ratio_features.get(name, 0.0) or 0.0) for name in self._garage_ratio_v2_feature_names]],
            dtype=np.float32,
        )
        X = np.nan_to_num(X, nan=0.0, posinf=10.0, neginf=-10.0)
        if self._garage_ratio_v2_scaler is not None:
            X = self._garage_ratio_v2_scaler.transform(X)
            X = np.nan_to_num(X, nan=0.0, posinf=10.0, neginf=-10.0)

        t0 = time.perf_counter()
        probs = self._garage_ratio_v2_model.predict_proba(X)[0]
        inference_ms = (time.perf_counter() - t0) * 1000

        raw_zone, raw_idx, adjusted_scores, door_rescue_applied = self._apply_garage_ratio_v2_policy(
            probs,
            production_zone,
        )
        pred_zone, pred_idx, smoothing_meta = self._apply_garage_ratio_v2_causal_smoothing(raw_zone, raw_idx)
        probabilities = {
            self._garage_ratio_v2_zone_names[i]: round(float(probs[i]), 4)
            for i in range(min(len(probs), len(self._garage_ratio_v2_zone_names)))
        }
        shadow = {
            **base_shadow,
            "status": "shadow_live",
            "predicted_zone": pred_zone,
            "predicted_idx": pred_idx,
            "target_zone": pred_zone,
            "raw_predicted_zone": raw_zone,
            "raw_predicted_idx": raw_idx,
            "probabilities": probabilities,
            "adjusted_scores": adjusted_scores,
            "inference_ms": round(inference_ms, 2),
            "nodes_with_ratio": nodes_with_ratio,
            "node_packets": node_packet_counts,
            "door_rescue_applied": door_rescue_applied,
            "smoothing": smoothing_meta,
            "top_features": {
                key: round(float(ratio_features.get(key, 0.0) or 0.0), 4)
                for key in (
                    "rssi_std_ratio_1_4",
                    "rssi_std_ratio_3_4",
                    "deep_c_rssi_04_0103",
                    "deep_c_amp_04_0103",
                )
            },
        }
        self._garage_ratio_v2_shadow = shadow

        logger.info(
            "GARAGE_RATIO SHADOW: raw=%s final=%s (door=%.3f center=%.3f deep=%.3f rescue=%s smooth=%s) %.1fms",
            raw_zone,
            pred_zone,
            probs[0],
            probs[1],
            probs[2],
            door_rescue_applied,
            smoothing_meta.get("applied", False),
            inference_ms,
        )
        return shadow

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
        return CsiPredictionService._normalize_to_64(amp, phase)

    # ── Feature extraction (mirrors V21) ──────────────────────────────

    def _extract_window_features(self, t_start: float, t_end: float) -> dict | None:
        """Extract V21-compatible features for one window from live buffer."""
        feat = {"t_mid": (t_start + t_end) / 2}
        nm, ns, nv, nd1 = [], [], [], []
        n_sc_ent, n_sc_frac, n_dop, n_bldev = [], [], [], []
        active_nodes = 0

        now_mono = time.monotonic()

        for ni, ip in enumerate(NODE_IPS):
            pkts = [(t, r, a, p) for t, r, a, p in self._packets.get(ip, []) if t_start <= t < t_end]
            pre = f"n{ni}"
            canonical_node = GARAGE_RATIO_NODE_NAME_BY_IP.get(ip, f"node{ni + 1:02d}")
            csi_pre = f"csi_{canonical_node}"

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

            if len(pkts) < 3:
                for s in [
                    "mean", "std", "max", "range", "pps", "tvar", "diff1", "diff1_max",
                    "kurtosis", "skew", "zcr",
                    "sc_var_mean", "sc_var_max", "sc_var_lo", "sc_var_hi",
                    "sc_var_frac_hi", "sc_var_entropy", "sc_var_concentration", "sc_var_kurtosis",
                    "phase_rate_mean", "doppler_spread", "doppler",
                    "phase_accel_mean", "phase_rate_lo", "phase_rate_hi",
                    "phase_spatial_std", "phase_coherence",
                    "fft_peak", "fft_energy", "pca_ev1", "pca_effdim",
                    "norm", "bldev", "amp_skew", "tvar_lo", "tvar_hi",
                    "baseline_amp_dev", "baseline_phase_dev", "baseline_sc_var_dev",
                    "sq_dead_sc_frac", "sq_phase_jump_rate", "sq_amp_drift",
                ]:
                    feat[f"{pre}_{s}"] = 0
                feat[f"{csi_pre}_rssi_mean"] = 0
                feat[f"{csi_pre}_rssi_std"] = 0
                feat[f"{csi_pre}_amp_mean"] = 0
                feat[f"{csi_pre}_motion_mean"] = 0
                feat[f"{csi_pre}_packets"] = 0
                nm.append(0); ns.append(0); nv.append(0); nd1.append(0)
                n_sc_ent.append(0); n_sc_frac.append(0); n_dop.append(0); n_bldev.append(0)
                continue

            active_nodes += 1
            rssi_vals = np.array([r for _, r, _, _ in pkts], dtype=np.float32)
            amp_mat = np.array([a for _, _, a, _ in pkts], dtype=np.float32)
            phase_mat = np.array([p for _, _, _, p in pkts], dtype=np.float32)
            amps = amp_mat.mean(axis=1)
            motion_mean = float(np.std(np.diff(amps))) if len(amps) > 1 else 0.0

            feat[f"{csi_pre}_rssi_mean"] = float(np.mean(rssi_vals))
            feat[f"{csi_pre}_rssi_std"] = float(np.std(rssi_vals))
            feat[f"{csi_pre}_amp_mean"] = float(np.mean(amps))
            feat[f"{csi_pre}_motion_mean"] = motion_mean
            feat[f"{csi_pre}_packets"] = int(len(pkts))
            feat[f"{csi_pre}_amp_std"] = float(np.std(amps))
            feat[f"{csi_pre}_amp_range"] = float(np.ptp(amps))
            feat[f"{csi_pre}_amp_tvar"] = float(np.var(np.diff(amps))) if len(amps) > 1 else 0.0
            _d1 = np.abs(np.diff(amps))
            feat[f"{csi_pre}_amp_diff1"] = float(np.mean(_d1)) if len(_d1) > 0 else 0.0
            feat[f"{csi_pre}_pps"] = len(pkts) / WINDOW_SEC

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

                # V23: Enhanced phase features
                # Phase velocity (second derivative of unwrapped phase)
                ph_accel = np.abs(np.diff(ph_unwrap, n=2, axis=0))
                feat[f"{pre}_phase_accel_mean"] = float(ph_accel.mean()) if ph_accel.size > 0 else 0

                # Band-wise phase rate (lo/hi bands, mirrors amplitude band split)
                ph_rate_lo = ph_rate[:, 3:30]   # lower active subcarriers
                ph_rate_hi = ph_rate[:, 35:62]  # upper active subcarriers
                feat[f"{pre}_phase_rate_lo"] = float(ph_rate_lo.mean()) if ph_rate_lo.size > 0 else 0
                feat[f"{pre}_phase_rate_hi"] = float(ph_rate_hi.mean()) if ph_rate_hi.size > 0 else 0

                # Phase std across subcarriers (spatial phase spread per time step)
                ph_spatial_std = ph_unwrap.std(axis=1)
                feat[f"{pre}_phase_spatial_std"] = float(ph_spatial_std.mean())

                # Phase temporal coherence: mean correlation between adjacent
                # subcarrier phase time-series (high = coherent signal, low = noise)
                if ph_unwrap.shape[1] >= 4:
                    ph_corrs = []
                    for sc_i in range(0, min(ph_unwrap.shape[1] - 1, 63), 2):
                        s1 = ph_unwrap[:, sc_i]
                        s2 = ph_unwrap[:, sc_i + 1]
                        s1d = s1 - s1.mean()
                        s2d = s2 - s2.mean()
                        denom = (np.sqrt((s1d ** 2).sum() * (s2d ** 2).sum()))
                        if denom > 1e-10:
                            ph_corrs.append(float((s1d * s2d).sum() / denom))
                    feat[f"{pre}_phase_coherence"] = float(np.mean(ph_corrs)) if ph_corrs else 0
                else:
                    feat[f"{pre}_phase_coherence"] = 0

                # Store phase_mat for inter-node features later
                feat[f"_raw_phase_{ni}"] = ph_unwrap
            else:
                feat[f"{pre}_phase_rate_mean"] = 0
                dop_spread = 0
                feat[f"{pre}_doppler_spread"] = 0
                feat[f"{pre}_doppler"] = 0
                feat[f"{pre}_phase_accel_mean"] = 0
                feat[f"{pre}_phase_rate_lo"] = 0
                feat[f"{pre}_phase_rate_hi"] = 0
                feat[f"{pre}_phase_spatial_std"] = 0
                feat[f"{pre}_phase_coherence"] = 0

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

            # ── V23: Empty baseline deviation features ──────────────────
            # Compare current window stats against stored empty-room profile.
            # If no baseline exists yet, output 0 (neutral — no signal).
            bl = self._empty_baselines.get(ip)
            if bl is not None:
                bl_amp_dev = abs(float(np.mean(amps)) - bl["amp_mean"]) / (bl["amp_std"] + 1e-10)
                bl_phase_dev = abs(feat[f"{pre}_phase_rate_mean"] - bl.get("phase_rate_mean", 0)) / (bl.get("phase_rate_std", 1e-10) + 1e-10)
                bl_sc_var_dev = abs(feat[f"{pre}_sc_var_mean"] - bl.get("sc_var_mean", 0)) / (bl.get("sc_var_std", 1e-10) + 1e-10)
            else:
                bl_amp_dev = 0
                bl_phase_dev = 0
                bl_sc_var_dev = 0
            feat[f"{pre}_baseline_amp_dev"] = float(bl_amp_dev)
            feat[f"{pre}_baseline_phase_dev"] = float(bl_phase_dev)
            feat[f"{pre}_baseline_sc_var_dev"] = float(bl_sc_var_dev)

            # Accumulate baseline data if calibration capture is active
            self._record_baseline_window(ip, feat, pre)

            # ── V23: Signal quality indicators (per-node) ────────────────
            # Dead subcarrier fraction: subcarriers with near-zero variance
            dead_thresh = 0.01
            dead_sc_frac = float((sc_var < dead_thresh).mean())
            feat[f"{pre}_sq_dead_sc_frac"] = dead_sc_frac

            # Phase jump rate: fraction of time steps with large phase discontinuity
            if phase_mat.shape[0] >= 5:
                raw_ph_diff = np.abs(np.diff(phase_mat, axis=0))
                # jumps > pi indicate unwrap failure or severe noise
                jump_frac = float((raw_ph_diff > np.pi).mean())
                feat[f"{pre}_sq_phase_jump_rate"] = jump_frac
            else:
                feat[f"{pre}_sq_phase_jump_rate"] = 0

            # Amplitude drift: slope of per-packet mean amplitude over time
            if len(amps) >= 5:
                t_local = np.arange(len(amps), dtype=np.float32)
                t_local -= t_local.mean()
                slope = float(np.dot(t_local, amps - amps.mean()) / (np.dot(t_local, t_local) + 1e-10))
                feat[f"{pre}_sq_amp_drift"] = abs(slope)
            else:
                feat[f"{pre}_sq_amp_drift"] = 0

            nm.append(np.mean(amps)); ns.append(np.std(amps)); nv.append(tv)
            nd1.append(feat[f"{pre}_diff1"])
            n_sc_ent.append(sc_ent); n_sc_frac.append(frac_hi); n_dop.append(dop_spread)
            n_bldev.append(feat[f"{pre}_bldev"])

        # ── V23: Inter-node relative phase features ──────────────────
        # Pairwise mean phase difference between node pairs. This captures
        # how a person's body changes the relative propagation path between
        # links — a stronger signal than absolute phase from any single node.
        _NODE_PAIRS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
        n_phase_coherence = []
        for na, nb in _NODE_PAIRS:
            ph_a = feat.get(f"_raw_phase_{na}")
            ph_b = feat.get(f"_raw_phase_{nb}")
            pair_key = f"x_phase_diff_{na}{nb}"
            if ph_a is not None and ph_b is not None:
                # Align to minimum length (nodes may have different packet counts)
                min_t = min(ph_a.shape[0], ph_b.shape[0])
                min_sc = min(ph_a.shape[1], ph_b.shape[1])
                rel_phase = ph_a[:min_t, :min_sc] - ph_b[:min_t, :min_sc]
                feat[pair_key + "_mean"] = float(np.abs(rel_phase).mean())
                feat[pair_key + "_std"] = float(rel_phase.std())
                # Temporal variance of relative phase → motion indicator
                if min_t >= 3:
                    rel_tvar = np.var(np.diff(rel_phase, axis=0))
                    feat[pair_key + "_tvar"] = float(rel_tvar)
                else:
                    feat[pair_key + "_tvar"] = 0
                n_phase_coherence.append(feat[pair_key + "_std"])
            else:
                feat[pair_key + "_mean"] = 0
                feat[pair_key + "_std"] = 0
                feat[pair_key + "_tvar"] = 0

        # Clean up raw phase arrays from feat dict (internal only)
        for ni in range(4):
            feat.pop(f"_raw_phase_{ni}", None)

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

            # V23: Cross-node phase coherence (from inter-node relative phase)
            if n_phase_coherence:
                feat["x_rel_phase_std_mean"] = float(np.mean(n_phase_coherence))
                feat["x_rel_phase_std_max"] = float(max(n_phase_coherence))
            else:
                feat["x_rel_phase_std_mean"] = 0
                feat["x_rel_phase_std_max"] = 0

            # V23: Cross-node baseline deviation summary
            bl_amp_devs = [feat.get(f"n{i}_baseline_amp_dev", 0) for i in range(4)]
            bl_sc_var_devs = [feat.get(f"n{i}_baseline_sc_var_dev", 0) for i in range(4)]
            feat["x_baseline_amp_dev_max"] = float(max(bl_amp_devs))
            feat["x_baseline_amp_dev_mean"] = float(np.mean(bl_amp_devs))
            feat["x_baseline_sc_var_dev_max"] = float(max(bl_sc_var_devs))

            # V23: Cross-node signal quality summary
            sq_dead = [feat.get(f"n{i}_sq_dead_sc_frac", 0) for i in range(4)]
            sq_drift = [feat.get(f"n{i}_sq_amp_drift", 0) for i in range(4)]
            sq_phjump = [feat.get(f"n{i}_sq_phase_jump_rate", 0) for i in range(4)]
            feat["x_sq_dead_sc_max"] = float(max(sq_dead))
            feat["x_sq_amp_drift_max"] = float(max(sq_drift))
            feat["x_sq_phase_jump_max"] = float(max(sq_phjump))
        else:
            for k in ["x_mean_std", "x_mean_range", "x_std_mean", "x_tvar_mean",
                       "x_tvar_max", "x_diff1_mean", "x_sc_ent_mean", "x_sc_ent_std",
                       "x_sc_frac_mean", "x_doppler_mean", "x_doppler_max",
                       "x_bldev_mean", "x_bldev_std", "x_bldev_max",
                       "x_rel_phase_std_mean", "x_rel_phase_std_max",
                       "x_baseline_amp_dev_max", "x_baseline_amp_dev_mean",
                       "x_baseline_sc_var_dev_max",
                       "x_sq_dead_sc_max", "x_sq_amp_drift_max", "x_sq_phase_jump_max"]:
                feat[k] = 0

        # Aggregate
        all_a = []
        for ip in NODE_IPS:
            all_a.extend([a.mean() for t, _, a, _ in self._packets.get(ip, []) if t_start <= t < t_end])
        feat["agg_mean"] = float(np.mean(all_a)) if all_a else 0
        feat["agg_std"] = float(np.std(all_a)) if all_a else 0
        feat["agg_pps"] = len(all_a) / WINDOW_SEC

        # Temporal delta (use previous prediction if available)
        for ni in range(4):
            feat[f"n{ni}_delta"] = 0  # simplified for live

        # ── V38: Drift-invariant features ──────────────────────────────
        # Normalized amp share: amp_i / sum(all amps) — cancels multiplicative drift
        _ALL_NODES = ["node01", "node02", "node03", "node04", "node05", "node06", "node07"]
        total_amp = sum(feat.get(f"csi_{n}_amp_mean", 0.0) for n in _ALL_NODES)
        if total_amp > 0:
            for nn in _ALL_NODES:
                feat[f"csi_{nn}_amp_norm"] = feat.get(f"csi_{nn}_amp_mean", 0.0) / total_amp
        else:
            for nn in _ALL_NODES:
                feat[f"csi_{nn}_amp_norm"] = 0.0

        # Inter-node ratios for key pairs
        _eps = 0.01
        for ni_name, nj_name in [("node01", "node05"), ("node01", "node03"),
                                   ("node06", "node05"), ("node01", "node07"),
                                   ("node03", "node05")]:
            ai = feat.get(f"csi_{ni_name}_amp_mean", 0.0)
            aj = feat.get(f"csi_{nj_name}_amp_mean", 0.0)
            feat[f"ratio_{ni_name}_{nj_name}"] = ai / (aj + _eps)

        # ── V40: Additional drift-invariant features ──
        # RSSI normalized share
        total_rssi_abs = sum(abs(feat.get(f"csi_{n}_rssi_mean", 0.0)) for n in _ALL_NODES)
        if total_rssi_abs > 0:
            for nn in _ALL_NODES:
                feat[f"csi_{nn}_rssi_norm"] = abs(feat.get(f"csi_{nn}_rssi_mean", 0.0)) / total_rssi_abs
        else:
            for nn in _ALL_NODES:
                feat[f"csi_{nn}_rssi_norm"] = 0.0

        # Motion normalized share (position-dependent, not drift-affected)
        total_motion = sum(feat.get(f"csi_{n}_motion_mean", 0.0) for n in _ALL_NODES)
        if total_motion > 0:
            for nn in _ALL_NODES:
                feat[f"csi_{nn}_motion_norm"] = feat.get(f"csi_{nn}_motion_mean", 0.0) / total_motion
        else:
            for nn in _ALL_NODES:
                feat[f"csi_{nn}_motion_norm"] = 0.0

        return feat, active_nodes, sum(len(p) for p in self._packets.values() if any(t_start <= t < t_end for t, _, _, _ in p))

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
        # Sliding window: step by WINDOW_SLIDE_SEC, use WINDOW_SEC of data
        w_end = int(now / WINDOW_SLIDE_SEC) * WINDOW_SLIDE_SEC
        w_start = w_end - WINDOW_SEC

        if w_end <= self._last_window_time or w_start < 0:
            return

        self._last_window_time = w_end
        result = self._extract_window_features(w_start, w_end)
        if result is None:
            return

        feat, active_nodes, pkt_count = result
        self._last_window_feat = feat  # for signal quality status API

        # Build feature vector in correct order
        X = np.array([[feat.get(f, 0) for f in self.feature_names]], dtype=np.float32)
        X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

        # ── Run Track B shadow BEFORE binary decision (needed for ensemble) ──
        try:
            self._shadow_predict_track_b(w_start, w_end, w_end)
        except Exception as e:
            logger.debug("Track B pre-inference skipped: %s", e)

        # ── V29 CNN zone shadow prediction ──
        try:
            self._shadow_predict_v29_zone(w_start, w_end, w_end)
        except Exception as e:
            logger.debug("V29 CNN zone shadow skipped: %s", e)

        # Binary prediction with custom threshold
        bin_proba = self.binary_model.predict_proba(X)[0]
        threshold = getattr(self, '_binary_threshold', 0.5)
        # proba[1] = P(occupied)
        p_occupied = float(bin_proba[1]) if len(bin_proba) > 1 else float(bin_proba[0])
        bin_pred = 1 if p_occupied >= threshold else 0
        binary_label = "occupied" if bin_pred == 1 else "empty"
        binary_conf = p_occupied if bin_pred == 1 else (1 - p_occupied)

        # ── Track B ensemble override (conservative) ─────────────────────
        # Override V5=empty ONLY when:
        #  1. Track B is very confident (>0.85 occupied)
        #  2. V5 is not strongly confident about empty (p_occupied > 0.15)
        #  3. Track B has been consistent for 3+ consecutive windows
        # This prevents false positives from Track B warmup / empty-garage noise.
        track_b_override = False
        if not hasattr(self, '_track_b_consecutive_occupied'):
            self._track_b_consecutive_occupied = 0

        if bin_pred == 0 and self._track_b_loaded:
            tb = self._track_b_shadow
            if isinstance(tb, dict) and tb.get("predicted_class") in ("MOTION", "STATIC"):
                tb_probs = tb.get("probabilities", {})
                tb_motion_p = float(tb_probs.get("MOTION", 0))
                tb_static_p = float(tb_probs.get("STATIC", 0))
                tb_occupied_p = tb_motion_p + tb_static_p

                # Carry-over should only accumulate on windows that are already
                # eligible for a future override; otherwise strongly-empty V5
                # windows can preload stale Track-B state into the next window.
                eligible_for_carry = tb_occupied_p > 0.85 and p_occupied > 0.15
                if eligible_for_carry:
                    self._track_b_consecutive_occupied += 1
                else:
                    self._track_b_consecutive_occupied = 0

                # Override only after 3 consecutive occupied windows AND
                # V5 is not strongly certain about empty
                if (self._track_b_consecutive_occupied >= 3
                        and eligible_for_carry):
                    bin_pred = 1
                    binary_label = "occupied"
                    binary_conf = tb_occupied_p * 0.8  # discount slightly
                    track_b_override = True
                    logger.info(
                        "Track B ensemble override: V5=empty(%.2f) → occupied "
                        "(Track B %s %.2f, %d consecutive)",
                        p_occupied, tb.get("predicted_class"),
                        tb_occupied_p, self._track_b_consecutive_occupied)
            else:
                self._track_b_consecutive_occupied = 0
        elif bin_pred == 1:
            # V5 already says occupied — reset Track B counter
            self._track_b_consecutive_occupied = 0

        # ── Node-health guard: partial node dropout → force empty ────────
        # When one CSI node is partially degraded (PPS < 15 while others
        # are healthy at > 25), V5 misinterprets the resulting cross-node
        # asymmetry as occupied signal.  This is a known false-positive
        # mechanism isolated in HIGHPPS_EMPTY_FEATURE_PROBE1.
        # Guard: detect partial dropout via per-node PPS imbalance and
        # suppress the false occupied prediction.
        # DIAGNOSTIC ONLY — does NOT affect canonical storyline or training.
        node_health_override = False
        node_health_diag = {}
        per_node_pps = [feat.get(f"n{i}_pps", 0) for i in range(4)]
        min_node_pps = min(per_node_pps)
        max_node_pps = max(per_node_pps)
        pps_imbalance = (max_node_pps - min_node_pps) / (max_node_pps + 1e-10) if max_node_pps > 0 else 0

        if bin_pred == 1 and min_node_pps < NODE_HEALTH_MIN_PPS and max_node_pps > NODE_HEALTH_MAX_PPS:
            # Partial node dropout detected — suppress false occupied
            degraded_nodes = [i for i in range(4) if per_node_pps[i] < 15]
            node_health_override = True
            bin_pred = 0
            binary_label = "empty"
            binary_conf = 1.0 - p_occupied  # flip confidence
            track_b_override = False  # cancel any Track B override too
            self._track_b_consecutive_occupied = 0
            logger.info(
                "NODE HEALTH GUARD: partial dropout detected — "
                "node(s) %s PPS=[%s], min=%.1f max=%.1f → force empty "
                "(was occupied p=%.3f)",
                degraded_nodes,
                ", ".join(f"{p:.1f}" for p in per_node_pps),
                min_node_pps, max_node_pps, p_occupied,
            )
            node_health_diag = {
                "guard_fired": True,
                "degraded_nodes": degraded_nodes,
                "per_node_pps": [round(p, 1) for p in per_node_pps],
                "min_node_pps": round(min_node_pps, 1),
                "max_node_pps": round(max_node_pps, 1),
                "pps_imbalance": round(pps_imbalance, 3),
                "original_p_occupied": round(p_occupied, 4),
            }
        else:
            node_health_diag = {
                "guard_fired": False,
                "per_node_pps": [round(p, 1) for p in per_node_pps],
                "min_node_pps": round(min_node_pps, 1),
                "max_node_pps": round(max_node_pps, 1),
                "pps_imbalance": round(pps_imbalance, 3),
            }

        # ── Subcarrier-variance noise gate: session-late sc_var elevation ──
        # After the node-health guard, the remaining high-PPS empty FPs
        # are dominated by elevated subcarrier variance (quasi-motion noise)
        # on n0/n1, concentrated in late-session windows of long captures.
        # Guard: when V5 says occupied but all nodes are healthy (PPS≥25),
        # temporal motion proxy is low, and max sc_var_hi on n0/n1 exceeds
        # the forensic separation threshold, suppress the false occupied.
        # Threshold 3.8 chosen from FP/TN boundary analysis:
        #   FP median sc_var_hi ≈ 4.5–5.0, TN p90 ≈ 3.6.
        # DIAGNOSTIC ONLY — does NOT affect canonical storyline or training.
        SC_VAR_MIN_NODE_PPS = 25

        sc_var_noise_override = False
        sc_var_noise_diag = {}
        if bin_pred == 1 and not node_health_override:
            sc_var_hi_vals = [
                float(feat.get(f"n{i}_sc_var_hi", 0) or 0) for i in range(4)
            ]
            max_sc_var_hi_01 = max(sc_var_hi_vals[0], sc_var_hi_vals[1])
            x_tvar_mean = float(feat.get("x_tvar_mean", 0) or 0)
            if x_tvar_mean == 0:
                # compute from per-node tvar if aggregate not available
                tvar_vals = [float(feat.get(f"n{i}_tvar", 0) or 0) for i in range(4)]
                x_tvar_mean = sum(tvar_vals) / max(len(tvar_vals), 1)

            if (min_node_pps >= SC_VAR_MIN_NODE_PPS
                    and max_sc_var_hi_01 > SC_VAR_HI_THRESHOLD
                    and x_tvar_mean < SC_VAR_MOTION_TVAR_CEILING):
                sc_var_noise_override = True
                bin_pred = 0
                binary_label = "empty"
                binary_conf = 1.0 - p_occupied
                track_b_override = False
                self._track_b_consecutive_occupied = 0
                logger.info(
                    "SC_VAR NOISE GATE: elevated subcarrier variance on n0/n1 "
                    "— max_sc_var_hi(n0,n1)=%.2f > %.1f, tvar=%.3f < %.1f, "
                    "min_pps=%.1f → force empty (was occupied p=%.3f)",
                    max_sc_var_hi_01, SC_VAR_HI_THRESHOLD,
                    x_tvar_mean, SC_VAR_MOTION_TVAR_CEILING,
                    min_node_pps, p_occupied,
                )
                sc_var_noise_diag = {
                    "guard_fired": True,
                    "max_sc_var_hi_n01": round(max_sc_var_hi_01, 3),
                    "sc_var_hi_all": [round(v, 3) for v in sc_var_hi_vals],
                    "x_tvar_mean": round(x_tvar_mean, 4),
                    "min_node_pps": round(min_node_pps, 1),
                    "threshold": SC_VAR_HI_THRESHOLD,
                    "original_p_occupied": round(p_occupied, 4),
                }
            else:
                sc_var_noise_diag = {
                    "guard_fired": False,
                    "max_sc_var_hi_n01": round(max_sc_var_hi_01, 3),
                    "x_tvar_mean": round(x_tvar_mean, 4),
                    "min_node_pps": round(min_node_pps, 1),
                }

        # ── V23: Phase noise gate ─────────────────────────────────────
        # When phase jump rate across all nodes is elevated (>30% of
        # time-steps have >π jumps), the signal is corrupted — suppress
        # occupied to prevent phase-noise false positives.
        PHASE_JUMP_THRESHOLD = 0.30
        phase_noise_override = False
        phase_noise_diag = {}
        if bin_pred == 1 and not node_health_override and not sc_var_noise_override:
            pj_vals = [float(feat.get(f"n{i}_sq_phase_jump_rate", 0) or 0) for i in range(4)]
            mean_pj = float(np.mean(pj_vals))
            if mean_pj > PHASE_JUMP_THRESHOLD:
                phase_noise_override = True
                bin_pred = 0
                binary_label = "empty"
                binary_conf = 1.0 - p_occupied
                track_b_override = False
                self._track_b_consecutive_occupied = 0
                logger.info(
                    "PHASE NOISE GATE: elevated phase jump rate — mean=%.3f > %.2f "
                    "per-node=[%s] → force empty (was occupied p=%.3f)",
                    mean_pj, PHASE_JUMP_THRESHOLD,
                    ", ".join(f"{v:.3f}" for v in pj_vals), p_occupied,
                )
                phase_noise_diag = {
                    "guard_fired": True,
                    "mean_phase_jump_rate": round(mean_pj, 4),
                    "per_node": [round(v, 4) for v in pj_vals],
                    "threshold": PHASE_JUMP_THRESHOLD,
                    "original_p_occupied": round(p_occupied, 4),
                }
            else:
                phase_noise_diag = {
                    "guard_fired": False,
                    "mean_phase_jump_rate": round(mean_pj, 4),
                }

        # ── V23: Amplitude drift gate ────────────────────────────────
        # Slow amplitude drift (temperature, AGC) can mimic occupation.
        # When drift is high but temporal variance (motion proxy) is low,
        # the signal is environmental drift, not a person.
        AMP_DRIFT_THRESHOLD = 2.0      # slope units/window
        AMP_DRIFT_TVAR_CEILING = 1.0   # must be low-motion to fire
        amp_drift_override = False
        amp_drift_diag = {}
        if bin_pred == 1 and not node_health_override and not sc_var_noise_override and not phase_noise_override:
            drift_vals = [float(feat.get(f"n{i}_sq_amp_drift", 0) or 0) for i in range(4)]
            max_drift = max(drift_vals)
            x_tvar = float(feat.get("x_tvar_mean", 0) or 0)
            if max_drift > AMP_DRIFT_THRESHOLD and x_tvar < AMP_DRIFT_TVAR_CEILING:
                amp_drift_override = True
                bin_pred = 0
                binary_label = "empty"
                binary_conf = 1.0 - p_occupied
                track_b_override = False
                self._track_b_consecutive_occupied = 0
                logger.info(
                    "AMP DRIFT GATE: slow drift detected — max_drift=%.2f > %.1f, "
                    "tvar=%.3f < %.1f → force empty (was occupied p=%.3f)",
                    max_drift, AMP_DRIFT_THRESHOLD, x_tvar, AMP_DRIFT_TVAR_CEILING, p_occupied,
                )
                amp_drift_diag = {
                    "guard_fired": True,
                    "max_drift": round(max_drift, 3),
                    "per_node": [round(v, 3) for v in drift_vals],
                    "x_tvar_mean": round(x_tvar, 4),
                    "threshold": AMP_DRIFT_THRESHOLD,
                    "original_p_occupied": round(p_occupied, 4),
                }
            else:
                amp_drift_diag = {
                    "guard_fired": False,
                    "max_drift": round(max_drift, 3),
                    "x_tvar_mean": round(x_tvar, 4),
                }

        # ── V23: Dead subcarrier gate ────────────────────────────────
        # When too many subcarriers have near-zero variance across nodes,
        # the CSI stream is degraded (firmware issue, interference).
        # Suppress occupied to prevent garbage-in predictions.
        DEAD_SC_THRESHOLD = 0.40  # >40% dead subcarriers on any node
        dead_sc_override = False
        dead_sc_diag = {}
        if bin_pred == 1 and not node_health_override:
            dead_vals = [float(feat.get(f"n{i}_sq_dead_sc_frac", 0) or 0) for i in range(4)]
            max_dead = max(dead_vals)
            if max_dead > DEAD_SC_THRESHOLD:
                dead_sc_override = True
                bin_pred = 0
                binary_label = "empty"
                binary_conf = 1.0 - p_occupied
                track_b_override = False
                self._track_b_consecutive_occupied = 0
                logger.info(
                    "DEAD SC GATE: excessive dead subcarriers — max_dead=%.2f > %.2f "
                    "per-node=[%s] → force empty (was occupied p=%.3f)",
                    max_dead, DEAD_SC_THRESHOLD,
                    ", ".join(f"{v:.2f}" for v in dead_vals), p_occupied,
                )
                dead_sc_diag = {
                    "guard_fired": True,
                    "max_dead_sc_frac": round(max_dead, 3),
                    "per_node": [round(v, 3) for v in dead_vals],
                    "threshold": DEAD_SC_THRESHOLD,
                    "original_p_occupied": round(p_occupied, 4),
                }
            else:
                dead_sc_diag = {
                    "guard_fired": False,
                    "max_dead_sc_frac": round(max_dead, 3),
                }

        # Coarse prediction (only if occupied and coarse model exists)
        coarse_label = "empty"
        coarse_conf = 0.0
        if bin_pred == 1 and track_b_override:
            # Use Track B class directly when it overrode V5
            tb_class = self._track_b_shadow.get("predicted_class", "STATIC")
            coarse_label = "motion" if tb_class == "MOTION" else "static"
            coarse_conf = binary_conf
        elif bin_pred == 1 and self.coarse_model is not None:
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
            len([1 for t, _, _, _ in self._packets.get(ip, []) if w_start <= t < w_end])
            for ip in NODE_IPS
        ) / WINDOW_SEC

        # ── Position estimation (gradient-extrapolated from node signals) ──
        target_x, target_y = 0.0, 0.0
        if bin_pred == 1:
            node_signals = []
            for ni, ip in enumerate(NODE_IPS):
                tvar = feat.get(f"n{ni}_tvar", 0)
                std_val = feat.get(f"n{ni}_std", 0)
                sc_var = feat.get(f"n{ni}_sc_var_mean", 0)
                diff1 = feat.get(f"n{ni}_diff1", 0)
                doppler = feat.get(f"n{ni}_doppler_spread", 0)

                signal = tvar + std_val * 5.0 + sc_var * 0.5 + diff1 * 10.0 + doppler * 20.0

                key = f"n{ni}"
                if key not in self._node_baselines:
                    self._node_baselines[key] = signal
                else:
                    self._node_baselines[key] = 0.95 * self._node_baselines[key] + 0.05 * signal

                baseline = self._node_baselines[key]
                deviation = abs(signal - baseline) / baseline if baseline > 0 else 0.0

                if ip in NODE_POSITIONS:
                    node_signals.append((ip, deviation, NODE_POSITIONS[ip]))

            if node_signals:
                # Step 1: weighted centroid as base anchor
                weights = [max(d ** 2, 1e-9) for _, d, _ in node_signals]
                total_w = sum(weights)
                cx = sum(w * p[0] for w, (_, _, p) in zip(weights, node_signals)) / total_w
                cy = sum(w * p[1] for w, (_, _, p) in zip(weights, node_signals)) / total_w

                # Step 2: extrapolate BEYOND node hull toward strongest signal
                # Compute the geometric center of all nodes
                all_x = [p[0] for _, _, p in node_signals]
                all_y = [p[1] for _, _, p in node_signals]
                node_center_x = sum(all_x) / len(all_x)
                node_center_y = sum(all_y) / len(all_y)

                # Vector from node center to weighted centroid — this is the
                # direction the target is pulling. Scale by 2.0 to extrapolate
                # beyond the node rectangle into the full garage space.
                pull_x = cx - node_center_x
                pull_y = cy - node_center_y

                # Scale factor: how concentrated is the signal on one node?
                # More concentrated = target is further toward that node (and beyond)
                max_w = max(weights)
                concentration = max_w / total_w if total_w > 0 else 0.25
                # concentration ~0.25 = evenly spread, ~1.0 = one node dominates
                extrap_scale = 1.0 + concentration * 3.0  # 1.75x to 4x extrapolation

                target_x = node_center_x + pull_x * extrap_scale
                target_y = node_center_y + pull_y * extrap_scale
            else:
                target_x, target_y = self._prev_target

            # Smooth with adaptive alpha
            import math
            if self._prev_target != (0.0, 0.0):
                dx = target_x - self._prev_target[0]
                dy = target_y - self._prev_target[1]
                dist = math.hypot(dx, dy)
                # Adaptive alpha: higher = more responsive, less teleportation
                alpha = 0.65 if dist > 1.5 else 0.45 if dist > 0.5 else 0.30
                target_x = self._prev_target[0] + dx * alpha
                target_y = self._prev_target[1] + dy * alpha

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
            "v29_cnn_zone": self._v29_cnn_shadow.get("zone") if self._v29_cnn_shadow.get("t") == w_end else None,
            "v29_cnn_probs": self._v29_cnn_shadow.get("probabilities") if self._v29_cnn_shadow.get("t") == w_end else None,
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
                    "node_health_guard": node_health_diag if node_health_override else None,
                    "sc_var_noise_gate": sc_var_noise_diag if sc_var_noise_override else None,
                    "phase_noise_gate": phase_noise_diag if phase_noise_override else None,
                    "amp_drift_gate": amp_drift_diag if amp_drift_override else None,
                    "dead_sc_gate": dead_sc_diag if dead_sc_override else None,
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

        # ── Garage ratio V2 shadow candidate (does NOT affect production) ──
        try:
            garage_ratio_v2_shadow = self._shadow_predict_garage_ratio_v2(
                feat,
                w_end,
                zone,
                binary_label,
                active_nodes,
                pkt_count,
            )
            if garage_ratio_v2_shadow is not None and garage_ratio_v2_shadow.get("t") == w_end:
                try:
                    shadow_path = PROJECT / "temp" / "garage_ratio_v2_shadow_telemetry.ndjson"
                    with open(shadow_path, "a") as sf:
                        shadow_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v5_zone": zone,
                            "v5_binary": binary_label,
                            "v5_motion": motion_state,
                            "garage_ratio_v2_status": garage_ratio_v2_shadow.get("status"),
                            "garage_ratio_v2_zone": garage_ratio_v2_shadow.get("target_zone"),
                            "garage_ratio_v2_raw_zone": garage_ratio_v2_shadow.get("raw_predicted_zone"),
                            "garage_ratio_v2_probs": garage_ratio_v2_shadow.get("probabilities", {}),
                            "garage_ratio_v2_adjusted_scores": garage_ratio_v2_shadow.get("adjusted_scores", {}),
                            "garage_ratio_v2_ms": garage_ratio_v2_shadow.get("inference_ms"),
                            "garage_ratio_v2_door_rescue": garage_ratio_v2_shadow.get("door_rescue_applied", False),
                            "garage_ratio_v2_nodes": garage_ratio_v2_shadow.get("nodes_with_ratio"),
                            "garage_ratio_v2_smoothing": garage_ratio_v2_shadow.get("smoothing", {}),
                        }
                        sf.write(json.dumps(shadow_entry) + "\n")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Garage ratio V2 shadow skipped: %s", e)

        # ── Zone calibration shadow (per-session NearestCentroid, NEVER affects V5) ──
        try:
            from .zone_calibration_service import zone_calibration_service as _zone_cal
            # If calibrating, feed windows to calibration service
            _zone_cal.add_calibration_window(feat, active_nodes, pkt_count)
            # If calibrated, get shadow zone prediction
            zone_cal_result = _zone_cal.predict(feat, active_nodes)
            self._zone_calibration_shadow = zone_cal_result
            if zone_cal_result.get("calibration_status") not in ("not_calibrated",):
                try:
                    shadow_path = PROJECT / "temp" / "zone_calibration_shadow_telemetry.ndjson"
                    shadow_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(shadow_path, "a") as sf:
                        sf.write(json.dumps({
                            "ts": time.time(),
                            "window_t": w_end,
                            "v5_zone": zone,
                            "v5_binary": binary_label,
                            "zone_cal_zone": zone_cal_result.get("zone"),
                            "zone_cal_raw": zone_cal_result.get("zone_raw"),
                            "zone_cal_confidence": zone_cal_result.get("confidence"),
                            "zone_cal_status": zone_cal_result.get("calibration_status"),
                            "zone_cal_smoothed": zone_cal_result.get("smoothed"),
                        }) + "\n")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Zone calibration shadow skipped: %s", e)

        # ── Few-shot packet adaptation shadow (saved packet consumer only) ──
        try:
            from .fewshot_adaptation_consumer_service import (
                fewshot_adaptation_consumer_service as _fewshot_consumer,
            )
            fewshot_result = _fewshot_consumer.predict(
                feat,
                active_nodes,
                pkt_count=pkt_count,
                window_t=w_end,
            )
            self._fewshot_adaptation_shadow = fewshot_result
            if fewshot_result.get("status") == "shadow_live":
                try:
                    shadow_path = PROJECT / "temp" / "fewshot_adaptation_shadow_telemetry.ndjson"
                    shadow_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(shadow_path, "a") as sf:
                        sf.write(json.dumps({
                            "ts": time.time(),
                            "window_t": w_end,
                            "v20_binary": binary_label,
                            "v20_zone": zone,
                            "fewshot_zone": fewshot_result.get("zone"),
                            "fewshot_zone_raw": fewshot_result.get("zone_raw"),
                            "fewshot_confidence": fewshot_result.get("confidence"),
                            "fewshot_status": fewshot_result.get("status"),
                            "fewshot_session_id": fewshot_result.get("active_session_id"),
                            "fewshot_probabilities": fewshot_result.get("probabilities", {}),
                            "fewshot_smoothing": fewshot_result.get("smoothing", {}),
                        }) + "\n")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Few-shot adaptation shadow skipped: %s", e)

        # ── Coordinate stabilization (shadow-only) ───────────────────
        try:
            from .coord_stabilization_service import coord_stabilization_service
            stabilized = coord_stabilization_service.process(
                raw_x=target_x,
                raw_y=target_y,
                motion_state=motion_state,
                zone=zone,
                binary=binary_label,
                window_t=w_end,
            )
            self.current["coord_stabilization"] = stabilized
        except Exception as e:
            logger.debug("Coord stabilization skipped: %s", e)

        logger.info(
            f"CSI predict: {motion_state} ({motion_conf:.2f}) "
            f"| binary={binary_label} ({binary_conf:.2f}) "
            f"| coarse={coarse_label} ({coarse_conf:.2f}) "
            f"| {active_nodes} nodes | {total_pps:.0f} pps"
        )

        # ── Track B shadow telemetry (inference already ran above for ensemble) ──
        try:
            shadow = self._track_b_shadow if self._track_b_shadow else None
            if shadow is not None and shadow.get("t") == w_end:
                tb_class = shadow["predicted_class"]
                tb_motion_p = shadow["probabilities"].get("MOTION", 0.0)

                # ── Transition boundary candidate detection ──
                # Track consecutive non-MOTION windows, then detect MOTION spike.
                # Forensic marker only — does NOT affect production routing.
                is_transition_boundary = False
                if tb_class == "MOTION" and tb_motion_p >= TRANSITION_BOUNDARY_MOTION_THRESHOLD:
                    if self._track_b_stable_non_motion >= TRANSITION_BOUNDARY_STABLE_WINDOWS:
                        is_transition_boundary = True
                        marker = {
                            "window_t": w_end,
                            "ts": time.time(),
                            "motion_prob": tb_motion_p,
                            "stable_windows_before": self._track_b_stable_non_motion,
                        }
                        self._track_b_transition_markers.append(marker)
                        if len(self._track_b_transition_markers) > 30:
                            self._track_b_transition_markers = self._track_b_transition_markers[-30:]
                        logger.info(
                            "TRANSITION BOUNDARY CANDIDATE at wt=%.0f "
                            "(Track B MOTION P=%.3f after %d stable windows)",
                            w_end, tb_motion_p, self._track_b_stable_non_motion)
                    self._track_b_stable_non_motion = 0
                else:
                    self._track_b_stable_non_motion += 1

                # Append to telemetry for offline comparison
                try:
                    shadow_path = PROJECT / "temp" / "track_b_shadow_telemetry.ndjson"
                    with open(shadow_path, "a") as sf:
                        shadow_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "track_a_motion": motion_state,
                            "track_a_coarse": coarse_label,
                            "track_b_class": tb_class,
                            "track_b_probs": shadow["probabilities"],
                            "track_b_ms": shadow["inference_ms"],
                            "agree": (tb_class.lower() == coarse_label),
                            "transition_boundary_candidate": is_transition_boundary,
                        }
                        sf.write(json.dumps(shadow_entry) + "\n")
                except Exception:
                    pass  # shadow telemetry must never crash
        except Exception as e:
            logger.debug("Track B shadow skipped: %s", e)

        # ── V7 warehouse-bound canonical shadow (does NOT affect production) ──
        try:
            v15_shadow = self._shadow_predict_v15(feat, w_end, coarse_label, binary_label)
            if v15_shadow is not None:
                try:
                    v15_path = PROJECT / "temp" / "v7_shadow_telemetry.ndjson"
                    with open(v15_path, "a") as vf:
                        v15_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v5_coarse": coarse_label,
                            "v5_binary": binary_label,
                            "v5_motion": motion_state,
                            "v7_coarse": v15_shadow["predicted_class"],
                            "v7_binary": v15_shadow["binary"],
                            "v7_probs": v15_shadow["probabilities"],
                            "v7_binary_proba": v15_shadow["binary_proba"],
                            "v7_ms": v15_shadow["inference_ms"],
                            "agree_coarse": v15_shadow["agree_coarse"],
                            "agree_binary": v15_shadow["agree_binary"],
                            "buffer_depth": v15_shadow["buffer_depth"],
                        }
                        vf.write(json.dumps(v15_entry) + "\n")
                except Exception:
                    pass  # shadow telemetry must never crash
            elif self._v15_loaded and len(self._v15_window_buffer) < V7_SEQ_LEN:
                try:
                    v15_path = PROJECT / "temp" / "v7_shadow_telemetry.ndjson"
                    with open(v15_path, "a") as vf:
                        warmup_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v7_status": "warmup",
                            "buffer_depth": len(self._v15_window_buffer),
                            "warmup_remaining": V7_SEQ_LEN - len(self._v15_window_buffer),
                        }
                        vf.write(json.dumps(warmup_entry) + "\n")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("V7 shadow skipped: %s", e)

        # ── V8 F2-spectral shadow (does NOT affect production) ──
        try:
            v8_shadow = self._shadow_predict_v8(feat, w_end, coarse_label, binary_label)
            if v8_shadow is not None:
                try:
                    v8_path = PROJECT / "temp" / "v8_shadow_telemetry.ndjson"
                    with open(v8_path, "a") as vf:
                        v8_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v5_coarse": coarse_label,
                            "v5_binary": binary_label,
                            "v5_motion": motion_state,
                            "v8_coarse": v8_shadow["predicted_class"],
                            "v8_binary": v8_shadow["binary"],
                            "v8_probs": v8_shadow["probabilities"],
                            "v8_binary_proba": v8_shadow["binary_proba"],
                            "v8_ms": v8_shadow["inference_ms"],
                            "v8_agree_coarse": v8_shadow["agree_coarse"],
                            "v8_agree_binary": v8_shadow["agree_binary"],
                            "v8_buffer_depth": v8_shadow["buffer_depth"],
                        }
                        vf.write(json.dumps(v8_entry) + "\n")
                except Exception:
                    pass  # shadow telemetry must never crash
            elif self._v8_loaded and len(self._v8_window_buffer) < V8_SEQ_LEN:
                try:
                    v8_path = PROJECT / "temp" / "v8_shadow_telemetry.ndjson"
                    with open(v8_path, "a") as vf:
                        warmup_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v8_status": "warmup",
                            "buffer_depth": len(self._v8_window_buffer),
                            "warmup_remaining": V8_SEQ_LEN - len(self._v8_window_buffer),
                        }
                        vf.write(json.dumps(warmup_entry) + "\n")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("V8 shadow skipped: %s", e)

        # ── Old-router domain-adapt shadow (does NOT affect production) ──
        try:
            old_router_shadow = self._shadow_predict_old_router_domain_adapt(
                feat, w_end, coarse_label, binary_label
            )
            if old_router_shadow is not None:
                try:
                    shadow_path = PROJECT / "temp" / "old_router_domain_adapt_shadow_telemetry.ndjson"
                    with open(shadow_path, "a") as of:
                        shadow_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v5_coarse": coarse_label,
                            "v5_binary": binary_label,
                            "v5_motion": motion_state,
                            "old_router_domain_adapt_coarse": old_router_shadow["predicted_class"],
                            "old_router_domain_adapt_binary": old_router_shadow["binary"],
                            "old_router_domain_adapt_probs": old_router_shadow["probabilities"],
                            "old_router_domain_adapt_binary_proba": old_router_shadow["binary_proba"],
                            "old_router_domain_adapt_ms": old_router_shadow["inference_ms"],
                            "old_router_domain_adapt_agree_coarse": old_router_shadow["agree_coarse"],
                            "old_router_domain_adapt_agree_binary": old_router_shadow["agree_binary"],
                            "old_router_domain_adapt_buffer_depth": old_router_shadow["buffer_depth"],
                            "old_router_domain_adapt_guard_features": old_router_shadow["guard_features_snapshot"],
                        }
                        of.write(json.dumps(shadow_entry) + "\n")
                except Exception:
                    pass
            elif self._old_router_domain_adapt_loaded and len(self._old_router_domain_adapt_window_buffer) < OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN:
                try:
                    shadow_path = PROJECT / "temp" / "old_router_domain_adapt_shadow_telemetry.ndjson"
                    with open(shadow_path, "a") as of:
                        warmup_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "old_router_domain_adapt_status": "warmup",
                            "old_router_domain_adapt_buffer_depth": len(self._old_router_domain_adapt_window_buffer),
                            "old_router_domain_adapt_warmup_remaining": OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN - len(self._old_router_domain_adapt_window_buffer),
                        }
                        of.write(json.dumps(warmup_entry) + "\n")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Old-router domain-adapt shadow skipped: %s", e)

        # ── V21d production override (promoted 2026-03-27) ──
        # V21d runs through the V19 pipeline (same format: seq_len=7, V23 + zone features).
        # When V21d produces a prediction, it OVERRIDES V25 production output.
        try:
            v19_shadow = self._shadow_predict_v19(feat, w_end, coarse_label, binary_label)
            if v19_shadow is not None:
                # V21d production override: update production output
                v20_coarse = v19_shadow["predicted_class"].lower()
                v20_binary = v19_shadow["binary"]
                v20_binary_conf = float(v19_shadow.get("binary_proba", binary_conf))
                # V30 fewshot zone — PRODUCTION zone override (BA=0.966)
                v30_result = self._predict_v30_fewshot_zone(feat, w_end)
                v30_zone = v30_result["zone"] if v30_result else None
                v30_probs = v30_result["probabilities"] if v30_result else None

                # Fallback to V29 CNN if V30 unavailable
                if v30_zone is None:
                    v29_zone = self._v29_cnn_shadow.get("zone") if self._v29_cnn_shadow.get("t") == w_end else None
                    v29_probs = self._v29_cnn_shadow.get("probabilities") if v29_zone else None
                    prod_zone = v29_zone
                    prod_zone_probs = v29_probs
                    prod_zone_model = "v29_cnn" if v29_zone else None
                else:
                    prod_zone = v30_zone
                    prod_zone_probs = v30_probs
                    prod_zone_model = "v30_fewshot"

                self.current.update({
                    "binary": v20_binary,
                    "binary_confidence": round(v20_binary_conf, 3),
                    "coarse": v20_coarse,
                    "model_version": "v21d",
                    "model_id": "v21d_candidate.pkl",
                    "zone": prod_zone,
                    "zone_probabilities": prod_zone_probs,
                    "zone_model": prod_zone_model,
                })
                # Override target_zone with fewshot zone when available
                if prod_zone:
                    self.current["target_zone"] = prod_zone
                # Update telemetry variables for downstream logging
                binary_label = v20_binary
                coarse_label = v20_coarse
                binary_conf = v20_binary_conf
                logger.debug("V21d production override: binary=%s coarse=%s", v20_binary, v20_coarse)

                try:
                    v19_path = PROJECT / "temp" / "v20_production_telemetry.ndjson"
                    with open(v19_path, "a") as vf:
                        v19_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v25_coarse": coarse_label,
                            "v25_binary": binary_label,
                            "v20_coarse": v19_shadow["predicted_class"],
                            "v20_binary": v19_shadow["binary"],
                            "v20_probs": v19_shadow["probabilities"],
                            "v20_binary_proba": v19_shadow["binary_proba"],
                            "v20_ms": v19_shadow["inference_ms"],
                            "v20_agree_coarse": v19_shadow["agree_coarse"],
                            "v20_agree_binary": v19_shadow["agree_binary"],
                            "v20_buffer_depth": v19_shadow["buffer_depth"],
                            "v20_empty_gate_fired": v19_shadow.get("empty_gate_fired", False),
                            "v20_gate_state": v19_shadow.get("empty_gate_state", False),
                            "v20_raw_pred": v19_shadow.get("raw_predicted_class"),
                            "v20_bl_amp_dev": v19_shadow.get("bl_amp_dev_max"),
                            "v20_bl_sc_dev": v19_shadow.get("bl_sc_var_dev_max"),
                            "v20_gate_consec_below": v19_shadow.get("gate_consec_below", 0),
                            "v20_gate_consec_above": v19_shadow.get("gate_consec_above", 0),
                            "v30_zone": v30_zone,
                            "v30_zone_probs": v30_probs,
                            "v30_zone_model": prod_zone_model,
                        }
                        vf.write(json.dumps(v19_entry) + "\n")
                except Exception:
                    pass  # telemetry must never crash
            elif self._v19_loaded and len(self._v19_window_buffer) < self._v19_seq_len:
                try:
                    v19_path = PROJECT / "temp" / "v19_shadow_telemetry.ndjson"
                    with open(v19_path, "a") as vf:
                        warmup_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "v19_status": "warmup",
                            "v19_buffer_depth": len(self._v19_window_buffer),
                            "v19_warmup_remaining": self._v19_seq_len - len(self._v19_window_buffer),
                        }
                        vf.write(json.dumps(warmup_entry) + "\n")
                except Exception:
                    pass
        except Exception as e:
            logger.debug("V19 shadow skipped: %s", e)

        # ── V30 fewshot zone — independent of V19 (moved out 2026-03-27) ──
        try:
            v30_result = self._predict_v30_fewshot_zone(feat, w_end)
            if v30_result:
                v30_zone = v30_result["zone"]
                v30_probs = v30_result["probabilities"]
                self.current.update({
                    "zone": v30_zone,
                    "zone_probabilities": v30_probs,
                    "zone_model": "v30_fewshot",
                })
                if v30_zone:
                    self.current["target_zone"] = v30_zone
        except Exception as e:
            logger.debug("V30 fewshot zone skipped: %s", e)

        # ── V42 balanced binary production override ──
        # V42 trained on 7-node balanced data (BA=0.9858), replaces V25/V40.
        try:
            v26_shadow = self._shadow_predict_v26(feat, w_end, binary_label)
            if v26_shadow is not None:
                primary_binary = binary_label
                primary_conf = binary_conf
                v40_binary = v26_shadow["binary"]
                v40_conf = v26_shadow["binary_proba"]
                # V40 production override
                self.current.update({
                    "binary": v40_binary,
                    "binary_confidence": round(v40_conf if v40_binary == "occupied" else 1.0 - v40_conf, 3),
                    "model_version": v26_shadow["track"],
                    "model_id": v26_shadow["candidate_name"],
                })
                binary_label = v40_binary
                binary_conf = v40_conf
                logger.debug(
                    "V40 binary override: %s→%s P(occ)=%.4f",
                    primary_binary,
                    v40_binary,
                    v40_conf,
                )

                try:
                    with open(V26_BINARY_SHADOW_TELEMETRY_PATH, "a") as vf:
                        v26_entry = {
                            "ts": time.time(),
                            "window_t": w_end,
                            "candidate_name": v26_shadow["candidate_name"],
                            "track": v26_shadow["track"],
                            "shadow_binary": v26_shadow["binary"],
                            "shadow_binary_proba": v26_shadow["binary_proba"],
                            "shadow_agree_primary": v26_shadow["agree_binary"],
                            "shadow_ms": v26_shadow["inference_ms"],
                            "primary_binary": primary_binary,
                            "primary_binary_confidence": primary_conf,
                            "primary_coarse": coarse_label,
                        }
                        vf.write(json.dumps(v26_entry) + "\n")
                except Exception:
                    pass  # telemetry must never crash
        except Exception as e:
            logger.debug("7-node binary shadow skipped: %s", e)

        # ── V43 shadow test (2026-03-28) ──
        # Runs V43 coarse HGB shadow alongside production for comparison.
        # Controlled by SHADOW_V43=1 env var. Does NOT affect production.
        try:
            v43_shadow = self._shadow_predict_v43(
                feat, w_end, coarse_label, binary_label, binary_conf,
            )
        except Exception as e:
            logger.debug("V43 shadow skipped: %s", e)

        # Prune old packets
        cutoff = now - MAX_BUFFER_SEC
        for ip in list(self._packets.keys()):
            self._packets[ip] = [(t, r, a, p) for t, r, a, p in self._packets[ip] if t > cutoff]

    # ── UDP listener ──────────────────────────────────────────────────

    def _handle_keepalive(self, data: bytes, addr: tuple) -> bool:
        """Detect and handle keepalive packets from ESP32 nodes.

        Keepalive format: {"keepalive":1,"node":"nodeXX","t":12345}
        Returns True if packet was a keepalive (caller should skip CSI parsing).
        """
        # Quick check: keepalive packets are short JSON starting with '{'
        if len(data) < 5 or len(data) > 256 or data[0:1] != b"{":
            return False
        try:
            msg = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
        if "keepalive" not in msg:
            return False

        ip = addr[0]
        now_mono = time.monotonic()
        self._node_last_seen[ip] = now_mono
        node_name = msg.get("node", ip)
        logger.debug("Keepalive from %s (%s)", node_name, ip)
        return True

    def _handle_raw_packet(self, data: bytes, addr: tuple):
        """Process one incoming raw UDP CSI packet from ESP32 node."""
        ip = addr[0]

        # Detect keepalive packets before any CSI processing
        if self._handle_keepalive(data, addr):
            return

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
        rssi, amp, phase = self._parse_csi_raw(data)
        if amp is None:
            if not getattr(self, '_raw_parse_fail_logged', False):
                import struct
                magic = struct.unpack('<I', data[:4])[0] if len(data) >= 4 else 0
                logger.warning("CSI raw parse failed: ip=%s len=%d magic=0x%08x first20=%s",
                               ip, len(data), magic, data[:20].hex() if len(data) >= 20 else data.hex())
                self._raw_parse_fail_logged = True
            return
        if self._start_time is None:
            self._start_time = time.time()
        t_sec = time.time() - self._start_time
        self._packets[ip].append((t_sec, rssi, amp, phase))

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
            return None, None, None
        iq = data[CSI_HEADER : CSI_HEADER + 256]
        n = len(iq) // 2
        if n < 40:
            return None, None, None
        arr = np.frombuffer(iq[: n * 2], dtype=np.int8).reshape(-1, 2)
        i_v = arr[:, 0].astype(np.float32)
        q_v = arr[:, 1].astype(np.float32)
        amp = np.sqrt(i_v**2 + q_v**2)
        phase = np.arctan2(q_v, i_v)
        rssi = int(np.frombuffer(data[RSSI_OFFSET : RSSI_OFFSET + 1], dtype=np.int8)[0]) if len(data) > RSSI_OFFSET else 0
        amp64, phase64 = CsiPredictionService._normalize_to_64(amp, phase)
        return rssi, amp64, phase64

    # ── CSV-format handler for ESP32-S3 nodes (port 5006) ──────────

    def _handle_csv_packet(self, data: bytes, addr: tuple):
        """Process CSV CSI_DATA packet from ESP32-S3 nodes (firmware v2.0)."""
        ip = addr[0]

        # Detect keepalive packets before CSV parsing
        if self._handle_keepalive(data, addr):
            return

        try:
            line = data.decode("utf-8", errors="replace").strip()
        except Exception:
            return
        if "CSI_DATA" not in line:
            return

        # Feed to recording service (raw bytes for storage)
        try:
            from .csi_recording_service import csi_recording_service
            csi_recording_service.ingest_packet(data, addr)
        except Exception:
            pass

        # Parse CSV: CSI_DATA,role,node_mac,src_mac,rssi,...,csi_len,"[I Q ...]"
        try:
            parts = line.split(",")
            rssi = int(parts[4])
            si = line.find('"[')
            ei = line.find(']"', si)
            if si < 0 or ei < 0:
                return
            csi_str = line[si + 2 : ei]
            vals = [int(x) for x in csi_str.split()]
            n = len(vals) // 2
            if n < 40:
                return
            arr = np.array(vals[: n * 2], dtype=np.float32).reshape(-1, 2)
            amp = np.sqrt(arr[:, 0] ** 2 + arr[:, 1] ** 2)
            phase = np.arctan2(arr[:, 1], arr[:, 0])
            amp64, phase64 = CsiPredictionService._normalize_to_64(amp, phase)
        except Exception:
            return

        if self._start_time is None:
            self._start_time = time.time()
        t_sec = time.time() - self._start_time
        self._packets[ip].append((t_sec, rssi, amp64, phase64))

        now_mono = time.monotonic()
        prev = self._node_last_seen.get(ip)
        self._node_last_seen[ip] = now_mono
        if prev is not None:
            gap = now_mono - prev
            if gap >= WARMUP_OFFLINE_THRESHOLD_SEC:
                warmup_end = now_mono + WARMUP_DURATION_SEC
                self._node_warmup_until[ip] = warmup_end

    class _UdpProtocol(asyncio.DatagramProtocol):
        def __init__(self, service):
            self.service = service

        def datagram_received(self, data, addr):
            self.service._handle_raw_packet(data, addr)

    class _CsvUdpProtocol(asyncio.DatagramProtocol):
        """Protocol for ESP32-S3 CSV CSI_DATA packets on port 5006."""
        def __init__(self, service):
            self.service = service

        def datagram_received(self, data, addr):
            self.service._handle_csv_packet(data, addr)

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

        # Also start CSV listener for ESP32-S3 nodes
        try:
            csv_transport, _ = await loop.create_datagram_endpoint(
                lambda: self._CsvUdpProtocol(self),
                local_addr=("0.0.0.0", UDP_PORT_CSV),
            )
            self._csv_transport = csv_transport
            logger.info(f"CSI CSV UDP listener started on port {UDP_PORT_CSV}")
        except Exception as exc:
            logger.warning(f"Could not start CSV UDP listener on {UDP_PORT_CSV}: {exc}")

    async def stop(self):
        """Stop the UDP listener."""
        if self._prediction_task is not None:
            self._prediction_task.cancel()
            try:
                await self._prediction_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("Prediction loop stopped with error during shutdown: %s", exc)
            finally:
                self._prediction_task = None

        if self._transport:
            close = getattr(self._transport, "close", None)
            if callable(close):
                close()
            self._transport = None
        self._running = False
        logger.info("CSI UDP listener stopped")

    # ── Tenda AP auto-recovery ────────────────────────────────────
    _tenda_last_reboot_t: float = 0.0
    _tenda_reboot_cooldown: float = 300.0  # min 5 min between reboots
    _tenda_dropout_threshold: int = 5      # if ≥5 nodes offline for 90s → reboot AP

    def _check_tenda_ap_health(self):
        """Auto-reboot Tenda AC7 when mass node dropout detected."""
        now = time.monotonic()
        if now - self._tenda_last_reboot_t < self._tenda_reboot_cooldown:
            return
        offline_count = 0
        for ip in NODE_IPS:
            last = self._node_last_seen.get(ip)
            if last is None or (now - last) > 90:
                offline_count += 1
        if offline_count >= self._tenda_dropout_threshold:
            logger.warning(
                "TENDA AUTO-REBOOT: %d/%d nodes offline >90s — rebooting AP",
                offline_count, len(NODE_IPS))
            self._tenda_last_reboot_t = now
            try:
                import hashlib, urllib.request
                pwd_hash = hashlib.md5(b"bookread595").hexdigest()
                # Login
                login_req = urllib.request.Request(
                    "http://192.168.1.2/login/Auth",
                    data=f"username=admin&password={pwd_hash}".encode())
                resp = urllib.request.urlopen(login_req, timeout=5)
                cookie = None
                for hdr in resp.headers.get_all("Set-Cookie") or []:
                    if "password=" in hdr:
                        cookie = hdr.split(";")[0]
                        break
                if cookie:
                    reboot_req = urllib.request.Request(
                        "http://192.168.1.2/goform/SysToolReboot")
                    reboot_req.add_header("Cookie", cookie)
                    urllib.request.urlopen(reboot_req, timeout=5)
                    logger.warning("TENDA REBOOT command sent successfully")
            except Exception as e:
                logger.error("TENDA REBOOT failed: %s", e)

    async def prediction_loop(self, interval: float = 0.3):
        """Run predictions at regular intervals."""
        loop_count = 0
        while self._running:
            try:
                self.predict_window()
                self._estimate_multi_person()
                self._voice_announce()
                loop_count += 1
                if loop_count % 100 == 0:  # every ~30s at 0.3s interval
                    self._check_tenda_ap_health()
            except Exception as e:
                logger.error(f"Prediction error: {e}")
            await asyncio.sleep(interval)

    # ── Voice announcements (ElevenLabs TTS) ─────────────────────────

    _voice_enabled: bool = False
    _voice_last_binary: str = ""
    _voice_last_zone: str = ""
    _voice_last_announce_t: float = 0.0
    _voice_cooldown_sec: float = 8.0  # minimum seconds between announcements

    def voice_start(self) -> dict:
        """Enable real-time voice announcements."""
        self._voice_enabled = True
        self._voice_last_binary = ""
        self._voice_last_zone = ""
        self._voice_last_announce_t = 0.0
        # Pre-cache common phrases
        try:
            from .tts_service import get_tts_service
            tts = get_tts_service()
            if tts.available:
                tts.precache([
                    "Гараж пуст.",
                    "Обнаружен человек в зоне двери.",
                    "Обнаружен человек в центре.",
                    "Человек перешёл в зону двери.",
                    "Человек перешёл в центр.",
                    "Человек ушёл. Гараж пуст.",
                ])
                return {"status": "started", "tts_available": True, "voice": tts._resolved_voice_name}
            return {"status": "started", "tts_available": False, "fallback": "macOS say"}
        except Exception as e:
            logger.warning("Voice start: TTS init failed: %s", e)
            return {"status": "started", "tts_available": False, "error": str(e)}

    def voice_stop(self) -> dict:
        """Disable voice announcements."""
        self._voice_enabled = False
        try:
            from .tts_service import get_tts_service
            get_tts_service().stop()
        except Exception:
            pass
        return {"status": "stopped"}

    def _voice_announce(self) -> None:
        """Announce state changes via TTS. Non-blocking."""
        if not self._voice_enabled:
            return

        now = time.time()
        if now - self._voice_last_announce_t < self._voice_cooldown_sec:
            return

        binary = self.current.get("binary", "unknown")
        zone = self.current.get("zone") or ""

        # Map zone names to Russian
        zone_ru = {"door_passage": "двери", "center": "центре", "deep": "глубокой зоне", "door": "двери"}.get(zone, zone)

        text = None

        if binary == "occupied" and self._voice_last_binary != "occupied":
            # Transition to occupied
            if zone_ru:
                text = f"Обнаружен человек в зоне {zone_ru}."
            else:
                text = "Обнаружен человек в гараже."
        elif binary == "empty" and self._voice_last_binary == "occupied":
            # Transition to empty
            text = "Человек ушёл. Гараж пуст."
        elif binary == "occupied" and zone != self._voice_last_zone and self._voice_last_zone and zone:
            # Zone changed while occupied
            text = f"Человек перешёл в зону {zone_ru}."

        if text:
            self._voice_last_announce_t = now
            try:
                from .tts_service import get_tts_service
                tts = get_tts_service()
                tts.speak(text, block=False)
                logger.info("VOICE: %s", text)
            except Exception as e:
                logger.warning("Voice announce failed: %s", e)

        self._voice_last_binary = binary
        self._voice_last_zone = zone

    # ── Multi-person diagnostic estimator ────────────────────────────
    def _estimate_multi_person(self) -> None:
        """Heuristic multi-person estimator using existing runtime signals.

        Uses:
          1. Production vs V8-shadow coordinate spread
          2. Production vs shadow class disagreement
          3. Motion energy / confidence thresholds
          4. Recording person_count hint (auxiliary only)

        Result written to self._mp_estimate (diagnostic, non-production).
        """
        prod = self.current
        v8 = self._v8_shadow or {}
        tb = self._track_b_shadow or {}

        # ── 1. Coordinate spread between production and V8 shadow ────
        prod_x = prod.get("target_x", 0.0)
        prod_y = prod.get("target_y", 0.0)
        v8_x = v8.get("target_x")
        v8_y = v8.get("target_y")
        coord_spread = 0.0
        if v8_x is not None and v8_y is not None:
            coord_spread = ((prod_x - v8_x) ** 2 + (prod_y - v8_y) ** 2) ** 0.5

        # ── 2. Class disagreement signals ────────────────────────────
        prod_coarse = str(prod.get("coarse", "")).upper()
        v8_class = str(v8.get("predicted_class", "")).upper()
        tb_class = str(tb.get("predicted_class", "")).upper()
        v8_disagree = bool(v8_class and prod_coarse and v8_class != prod_coarse)
        tb_disagree = bool(tb_class and prod_coarse and tb_class != prod_coarse)
        disagree_count = int(v8_disagree) + int(tb_disagree)

        # ── 3. Motion energy ─────────────────────────────────────────
        motion_conf = float(prod.get("motion_confidence", 0))
        binary_conf = float(prod.get("binary_confidence", 0))
        coarse_conf = float(prod.get("coarse_confidence", 0))
        low_confidence = (coarse_conf < 0.55) if coarse_conf else False

        # ── 4. Recording hint (auxiliary) ─────────────────────────────
        rec_hint = 0
        try:
            from .csi_recording_service import csi_recording_service
            rec = csi_recording_service.get_status()
            if rec.get("recording"):
                rec_hint = int(rec.get("person_count", 0) or 0)
        except Exception:
            pass

        # ── Combine heuristic scores ──────────────────────────────────
        score = 0.0
        reasons = []

        # Large coordinate spread → likely multi-person
        if coord_spread > 1.2:
            score += 0.35
            reasons.append(f"coord_spread={coord_spread:.2f}")
        elif coord_spread > 0.6:
            score += 0.15
            reasons.append(f"coord_spread={coord_spread:.2f}")

        # Class disagreement
        if disagree_count >= 2:
            score += 0.30
            reasons.append("both_shadows_disagree")
        elif disagree_count == 1:
            score += 0.15
            reasons.append("one_shadow_disagrees")

        # Low coarse confidence → ambiguous situation
        if low_confidence:
            score += 0.15
            reasons.append(f"low_coarse_conf={coarse_conf:.2f}")

        # Recording hint as soft boost (never sole evidence)
        if rec_hint > 1 and score > 0.05:
            score += 0.10
            reasons.append(f"recording_hint={rec_hint}")

        # ── Determine state ───────────────────────────────────────────
        score = min(score, 1.0)

        if score >= 0.50:
            state = "multi"
            est_count = max(2, rec_hint) if rec_hint > 1 else 2
        elif score >= 0.25:
            state = "unresolved"
            est_count = 1  # not confident enough to claim > 1
        else:
            state = "single"
            est_count = 1

        # ── Build diagnostic tracks ───────────────────────────────────
        tracks = []
        # Track 0: always the production coordinate
        tracks.append({
            "id": "prod_0",
            "source": "production",
            "x": round(prod_x, 3),
            "y": round(prod_y, 3),
            "zone": prod.get("target_zone", "unknown"),
            "class": prod_coarse.lower() if prod_coarse else "unknown",
            "confidence": round(coarse_conf, 3),
        })

        # Track 1: V8 shadow coordinate (if available and different enough)
        if v8_x is not None and v8_y is not None and coord_spread > 0.3:
            v8_conf = float(v8.get("binary_proba", 0) or 0)
            tracks.append({
                "id": "v8_shadow_1",
                "source": "v8_shadow",
                "x": round(v8_x, 3),
                "y": round(v8_y, 3),
                "zone": v8.get("target_zone", "unknown"),
                "class": v8_class.lower() if v8_class else "unknown",
                "confidence": round(v8_conf, 3),
            })

        # Cluster center/radius
        if len(tracks) >= 2:
            xs = [t["x"] for t in tracks]
            ys = [t["y"] for t in tracks]
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            radius = max(((t["x"] - cx) ** 2 + (t["y"] - cy) ** 2) ** 0.5 for t in tracks)
            cluster_center = {"x": round(cx, 3), "y": round(cy, 3)}
            cluster_radius = round(radius, 3)
        else:
            cluster_center = {"x": round(prod_x, 3), "y": round(prod_y, 3)}
            cluster_radius = 0.0

        self._mp_estimate = {
            "person_count_estimate": est_count,
            "multi_person_state": state,
            "multi_person_confidence": round(score, 3),
            "diagnostic_tracks": tracks,
            "diagnostic_cluster_center": cluster_center,
            "diagnostic_cluster_radius": cluster_radius,
            "estimator_source": "runtime_heuristic",
            "estimator_reasons": reasons,
            "recording_hint": rec_hint,
        }

    def get_node_health(self) -> dict:
        """Get per-node health status based on last-seen timestamps.

        Returns a dict keyed by canonical node name (e.g. "node01") with
        ip, last_seen_sec, and status ("online" / "degraded" / "offline").

        Nodes may have multiple IPs in GARAGE_RATIO_NODE_ORDER (e.g. node05
        has both .33 and .105).  Pick the IP with the freshest last_seen so
        the health report reflects the actually-active address.
        """
        now_mono = time.monotonic()
        # Collect best (freshest) IP per node name
        best: dict[str, tuple[str, float | None]] = {}  # node_name → (ip, age)
        for ip, node_name in GARAGE_RATIO_NODE_ORDER:
            last = self._node_last_seen.get(ip)
            age = None if last is None else (now_mono - last)
            prev = best.get(node_name)
            if prev is None:
                best[node_name] = (ip, age)
            else:
                prev_age = prev[1]
                # Prefer the IP that was seen (age is not None) and fresher
                if age is not None and (prev_age is None or age < prev_age):
                    best[node_name] = (ip, age)

        result = {}
        for node_name, (ip, age) in best.items():
            if age is None:
                status = "offline"
            elif age < 30:
                status = "online"
            elif age < 60:
                status = "degraded"
            else:
                status = "offline"
            result[node_name] = {
                "ip": ip,
                "last_seen_sec": None if age is None else round(age, 1),
                "status": status,
            }
        return result

    @staticmethod
    def _build_dropout_summary(nodes: dict) -> dict:
        if not nodes:
            return {
                "total_nodes": 0,
                "online_nodes": [],
                "degraded_nodes": [],
                "offline_nodes": [],
                "core_nodes": [],
                "shadow_nodes": [],
                "core_online_count": 0,
                "core_degraded_count": 0,
                "core_offline_count": 0,
                "healthy_core_count": 0,
                "healthy_total_count": 0,
                "has_dropout": False,
                "latest_last_seen_sec": None,
                "oldest_last_seen_sec": None,
            }

        node_values = list(nodes.values())
        online_nodes = [name for name, node in nodes.items() if node.get("status") == "online"]
        degraded_nodes = [name for name, node in nodes.items() if node.get("status") == "degraded"]
        offline_nodes = [name for name, node in nodes.items() if node.get("status") == "offline"]
        core_nodes = [name for name, node in nodes.items() if node.get("ip") in CORE_NODE_IPS]
        shadow_nodes = [name for name, node in nodes.items() if node.get("ip") not in CORE_NODE_IPS]
        core_online = [name for name, node in nodes.items() if node.get("status") == "online" and node.get("ip") in CORE_NODE_IPS]
        core_degraded = [name for name, node in nodes.items() if node.get("status") == "degraded" and node.get("ip") in CORE_NODE_IPS]
        core_offline = [name for name, node in nodes.items() if node.get("status") == "offline" and node.get("ip") in CORE_NODE_IPS]
        seen_ages = [float(node["last_seen_sec"]) for node in node_values if node.get("last_seen_sec") is not None]
        return {
            "total_nodes": len(nodes),
            "online_nodes": online_nodes,
            "degraded_nodes": degraded_nodes,
            "offline_nodes": offline_nodes,
            "core_nodes": core_nodes,
            "shadow_nodes": shadow_nodes,
            "core_online_count": len(core_online),
            "core_degraded_count": len(core_degraded),
            "core_offline_count": len(core_offline),
            "healthy_core_count": len(core_online),
            "healthy_total_count": len(online_nodes),
            "has_dropout": len(degraded_nodes) > 0 or len(offline_nodes) > 0,
            "latest_last_seen_sec": max(seen_ages) if seen_ages else None,
            "oldest_last_seen_sec": min(seen_ages) if seen_ages else None,
        }

    def get_status(self) -> dict:
        """Get current prediction status for API."""
        # Preload V8 shadow metadata for UI/debug surfaces even before the
        # first live window arrives. This keeps the operator UI honest:
        # "model loaded, waiting for CSI / warmup" instead of a misleading
        # "not_loaded" when the candidate artifact is already available.
        if V8_SHADOW_ENABLED and not self._v15_loaded:
            try:
                self._load_v15_shadow()
            except Exception:
                pass
        if GARAGE_RATIO_V2_SHADOW_ENABLED and not self._garage_ratio_v2_loaded:
            try:
                self._load_garage_ratio_v2_shadow()
            except Exception:
                pass

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
        # Transition boundary candidates (forensic/eval marker only)
        if self._track_b_transition_markers:
            status["transition_boundary_candidates"] = self._track_b_transition_markers[-5:]
        # V7 shadow info (debug surface only — NOT production)
        if self._v15_loaded and self._v15_shadow:
            status["v7_shadow"] = self._v15_shadow
            status["v15_shadow"] = self._v15_shadow  # compat alias
        elif V7_SHADOW_ENABLED:
            status["v7_shadow"] = {
                "loaded": self._v15_loaded,
                "status": "warmup" if self._v15_loaded else "not_loaded",
                "buffer_depth": len(self._v15_window_buffer),
                "warmup_remaining": max(0, V7_SEQ_LEN - len(self._v15_window_buffer)),
            }
            status["v15_shadow"] = status["v7_shadow"]
        # V8 F2-spectral shadow info (debug surface only — NOT production)
        if self._v8_loaded and self._v8_shadow:
            status["v8_shadow"] = self._v8_shadow
        elif V8_SHADOW_ENABLED:
            status["v8_shadow"] = {
                "loaded": self._v8_loaded,
                "status": "warmup" if self._v8_loaded else "not_loaded",
                "buffer_depth": len(self._v8_window_buffer),
                "warmup_remaining": max(0, V8_SEQ_LEN - len(self._v8_window_buffer)),
            }
        if self._old_router_domain_adapt_loaded and self._old_router_domain_adapt_shadow:
            status["old_router_domain_adapt_shadow"] = self._old_router_domain_adapt_shadow
        elif OLD_ROUTER_DOMAIN_ADAPT_SHADOW_ENABLED:
            status["old_router_domain_adapt_shadow"] = {
                "candidate_name": OLD_ROUTER_DOMAIN_ADAPT_CANDIDATE_NAME,
                "loaded": self._old_router_domain_adapt_loaded,
                "status": "warmup" if self._old_router_domain_adapt_loaded else "not_loaded",
                "buffer_depth": len(self._old_router_domain_adapt_window_buffer),
                "warmup_remaining": max(
                    0,
                    OLD_ROUTER_DOMAIN_ADAPT_SEQ_LEN - len(self._old_router_domain_adapt_window_buffer),
                ),
            }
        # ── V26 binary 7-node shadow info ──────────────────────────────
        if self._v26_loaded and self._v26_shadow:
            status["v26_shadow"] = self._v26_shadow
        elif V26_BINARY_SHADOW_ENABLED:
            status["v26_shadow"] = {
                "candidate_name": self._v26_candidate_name,
                "track": self._v26_track,
                "loaded": self._v26_loaded,
                "status": "not_loaded",
            }

        # ── Multi-person diagnostic estimate (non-production) ─────────
        status["multi_person_estimate"] = self._mp_estimate

        # ── V19 V23-features shadow info ───────────────────────────────
        if self._v19_loaded and self._v19_shadow:
            status["v19_shadow"] = self._v19_shadow
        else:
            status["v19_shadow"] = {
                "loaded": self._v19_loaded,
                "status": "warmup" if self._v19_loaded else "not_loaded",
                "buffer_depth": len(self._v19_window_buffer),
                "warmup_remaining": max(0, self._v19_seq_len - len(self._v19_window_buffer)),
            }

        # ── Garage ratio shadow info ──────────────────────────────────
        if self._garage_ratio_v2_loaded and self._garage_ratio_v2_shadow:
            status["garage_ratio_v3_shadow"] = self._garage_ratio_v2_shadow
            status["garage_ratio_v2_shadow"] = self._garage_ratio_v2_shadow
        elif GARAGE_RATIO_V2_SHADOW_ENABLED:
            shadow_stub = {
                "loaded": self._garage_ratio_v2_loaded,
                "status": "awaiting_first_window" if self._garage_ratio_v2_loaded else "not_loaded",
                "track": self._garage_ratio_v2_bundle.get("candidate_name", "GARAGE_RATIO_LAYER_V3_CANDIDATE")
                if self._garage_ratio_v2_bundle else "GARAGE_RATIO_LAYER_V3_CANDIDATE",
                "candidate_name": self._garage_ratio_v2_bundle.get("candidate_name", "GARAGE_RATIO_LAYER_V3_CANDIDATE")
                if self._garage_ratio_v2_bundle else "GARAGE_RATIO_LAYER_V3_CANDIDATE",
                "thresholds": dict(self._garage_ratio_v2_thresholds),
                "v5_door_rescue": dict(self._garage_ratio_v2_door_rescue),
                "runtime_smoothing": dict(self._garage_ratio_v2_runtime_smoothing),
            }
            status["garage_ratio_v3_shadow"] = shadow_stub
            status["garage_ratio_v2_shadow"] = {
                **shadow_stub,
            }

        # ── V43 shadow test status ─────────────────────────────────────
        if self._v43_loaded and self._v43_shadow:
            status["v43_shadow"] = {
                **self._v43_shadow,
                "total_windows": self._v43_window_count,
                "total_agreements": self._v43_agree_count,
            }
        elif V43_SHADOW_ENABLED:
            status["v43_shadow"] = {
                "loaded": self._v43_loaded,
                "status": "warmup" if self._v43_loaded else "not_loaded",
                "buffer_depth": len(self._v43_window_buffer),
                "warmup_remaining": max(0, self._v43_seq_len - len(self._v43_window_buffer)),
                "env_enabled": V43_SHADOW_ENABLED,
                "model_path": str(V43_SHADOW_MODEL_PATH),
            }
        else:
            status["v43_shadow"] = {
                "enabled": False,
                "status": "disabled (set SHADOW_V43=1 to enable)",
            }

        # ── V29 CNN zone shadow status ──────────────────────────────────
        if self._v29_cnn_loaded and self._v29_cnn_shadow:
            status["v29_cnn_zone_shadow"] = self._v29_cnn_shadow
        elif V29_CNN_SHADOW_ENABLED:
            status["v29_cnn_zone_shadow"] = {
                "loaded": self._v29_cnn_loaded,
                "status": "awaiting_first_window" if self._v29_cnn_loaded else "not_loaded",
                "model_path": str(V29_CNN_MODEL_PATH),
            }

        # ── V30 fewshot zone production status ─────────────────────────
        if self._v30_fewshot_loaded and self._v30_fewshot_shadow:
            status["v30_fewshot_zone"] = self._v30_fewshot_shadow
        elif V30_FEWSHOT_ZONE_ENABLED:
            status["v30_fewshot_zone"] = {
                "loaded": self._v30_fewshot_loaded,
                "status": "awaiting_first_window" if self._v30_fewshot_loaded else "not_loaded",
                "model_path": str(V30_FEWSHOT_MODEL_PATH),
            }

        # ── Zone calibration shadow status (per-session centroid) ─────
        try:
            from .zone_calibration_service import zone_calibration_service as _zone_cal
            status["zone_calibration_shadow"] = {
                **_zone_cal.get_status(),
                "last_prediction": self._zone_calibration_shadow if self._zone_calibration_shadow else None,
            }
        except Exception:
            status["zone_calibration_shadow"] = {"calibrated": False, "status": "not_loaded"}

        # ── Few-shot adaptation shadow status (saved packet consumer) ──
        try:
            from .fewshot_adaptation_consumer_service import (
                fewshot_adaptation_consumer_service as _fewshot_consumer,
            )
            status["fewshot_adaptation_shadow"] = {
                **_fewshot_consumer.get_status(),
                "last_prediction": self._fewshot_adaptation_shadow if self._fewshot_adaptation_shadow else None,
            }
        except Exception:
            status["fewshot_adaptation_shadow"] = {"enabled": True, "active": False, "status": "not_loaded"}

        # ── Coord stabilization shadow status ──────────────────────────
        try:
            from .coord_stabilization_service import coord_stabilization_service as _coord_stab
            status["coord_stabilization"] = self.current.get("coord_stabilization", {})
        except Exception:
            pass

        # ── Node health (keepalive + CSI packet tracking) ─────────────
        nodes = self.get_node_health()
        status["nodes"] = nodes
        status["dropout_summary"] = self._build_dropout_summary(nodes)

        # ── V23: Empty baseline calibration status ────────────────────
        status["empty_baseline"] = self.get_baseline_status()

        # ── V23: Signal quality summary (last window) ─────────────────
        if self._recent_predictions:
            last_feat = getattr(self, "_last_window_feat", None)
            if last_feat:
                status["signal_quality"] = {
                    "phase_jump_max": float(max(
                        last_feat.get(f"n{i}_sq_phase_jump_rate", 0) or 0 for i in range(4)
                    )),
                    "dead_sc_max": float(max(
                        last_feat.get(f"n{i}_sq_dead_sc_frac", 0) or 0 for i in range(4)
                    )),
                    "amp_drift_max": float(max(
                        last_feat.get(f"n{i}_sq_amp_drift", 0) or 0 for i in range(4)
                    )),
                    "phase_coherence_mean": float(np.mean([
                        last_feat.get(f"n{i}_phase_coherence", 0) or 0 for i in range(4)
                    ])),
                }

        return status


# Singleton
csi_prediction_service = CsiPredictionService()
