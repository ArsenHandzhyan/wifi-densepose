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
import math
import os
import pickle
import sys
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import entropy, kurtosis, skew

from .csi_node_inventory import CORE_NODE_IPS, resolve_ip, MAC_TO_NODE_ID
from .csi_mesh_link import MeshLinkManager, parse_mesh_csv_fields

logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parents[3]
# V56 twoperson_boost3 (2026-03-30): Tenda+FW4, binary_rf_f1=0.9945, coord_mae=0.198m
# Trained on 11 canonical sessions + 7 empty boosts + two_person_center_marker7_marker8_2min + two_person_center_marker7_marker8_v55_20260330 (2473 windows)
MODEL_PATH = PROJECT / "output" / "train_runs" / "v48_production" / "v48_production.pkl"
_V44_FALLBACK_MODEL_PATH = PROJECT / "output" / "train_runs" / "v55_twoperson_boost2" / "v48_production_candidate.pkl"
UDP_PORT = 5005
UDP_PORT_CSV = 5006  # ESP32-S3 nodes with CSI_DATA CSV format
NODE_IPS = sorted(["192.168.0.144", "192.168.0.117", "192.168.0.125", "192.168.0.137", "192.168.0.110", "192.168.0.132", "192.168.0.153"])

# Dead subcarriers: DC (0) + guard bands (27-37) — always zero on ESP32
_DEAD_SUBCARRIERS = {0} | set(range(27, 38))  # {0, 27, 28, ..., 37}
_LIVE_SC_MASK_64 = np.array([i not in _DEAD_SUBCARRIERS for i in range(64)], dtype=bool)

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
    "192.168.0.137",  # n01
    "192.168.0.117",  # n02
    "192.168.0.144",  # n03
    "192.168.0.125",  # n04
]
WINDOW_SEC = 2.0
WINDOW_SLIDE_SEC = 0.5  # sliding window step (predictions every 0.5s using 2s of data)
# V1/V2 firmware packet format constants
CSI_MAGIC_V1 = 0xC5110001
CSI_MAGIC_V2 = 0xC5110002
CSI_HEADER_SIZE_V1 = 20  # V1: 20-byte header, no phase data
CSI_HEADER_SIZE_V2 = 24  # V2: 24-byte header (byte[20]=flags, [21-22]=phase_offset, [23]=reserved)
CSI_HEADER = CSI_HEADER_SIZE_V1  # backward-compat alias (V1 default)
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
    ("192.168.0.137", "node01"),
    ("192.168.0.117", "node02"),
    ("192.168.0.144", "node03"),
    ("192.168.0.125", "node04"),
    ("192.168.0.110",  "node05"),
    ("192.168.0.132",  "node06"),
    ("192.168.0.153",  "node07"),
]
GARAGE_RATIO_NODE_NAME_BY_IP = {ip: node_name for ip, node_name in GARAGE_RATIO_NODE_ORDER}
GARAGE_RATIO_NODE_NAME_BY_IP["192.168.0.143"] = "node03"
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

# ── Door/center live shadow candidate (2026-04-03) ─────────────────
# Prototype shadow path + temporal overlay are execution-safe overlays for
# operator validation. They never override production runtime directly.
FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH = (
    PROJECT
    / "output"
    / "garage_fewshot_adaptation_consumer1"
    / "center_door_prototype1"
    / "best_prototype_candidate_v1.json"
)
FEWSHOT_PROTOTYPE_SHADOW_ENABLED = os.environ.get("FEWSHOT_PROTOTYPE_SHADOW", "1") == "1"
FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH = (
    PROJECT
    / "output"
    / "garage_fewshot_adaptation_consumer1"
    / "center_door_temporal1"
    / "center_door_temporal_summary_v1.json"
)
FEWSHOT_TEMPORAL_OVERLAY_ENABLED = os.environ.get("FEWSHOT_TEMPORAL_OVERLAY", "1") == "1"
LIVE_DOOR_SHADOW_ENABLED = os.environ.get("LIVE_DOOR_SHADOW", "1") == "1"

# ── V57 multi-person classifier (2026-03-30) ────────────────────────
# Person count classification (1 vs 2) using coordinate spread
# CV F1: 1.0000, trained on 558 two-person windows + contrast
# V58 v2 ROLLED BACK — false multi on empty garage (conf=1.0)
V57_PERSON_COUNT_MODEL_PATH = PROJECT / "output" / "production_models" / "v57_twoperson_coordinate_v1" / "v57_person_count_classifier.pkl"
V57_ENABLED = True  # Production mode for multi-person detection

# ── V60 mesh binary (2026-04-02) ─────────────────────────────────
# V60: GBM-500 trained on mesh v5.0 peer-to-peer CSI features.
# 453 features (338 peer-link + 105 router + 10 aggregate).
# CV F1=0.9665, peer RSSI is #1 discriminator. Replaces V48 binary
# when mesh peer data is available. Falls back to V48 otherwise.
V60_MESH_BINARY_MODEL_PATH = PROJECT / "output" / "train_runs" / "v60_mesh_binary" / "v60_mesh_binary.pkl"
V60_MESH_BINARY_ENABLED = os.environ.get("V60_MESH_BINARY", "0") == "1"  # disabled: not trained on Tenda data
V60_MESH_MIN_PEER_LINKS = 3  # minimum active peer links to trust V60

# ── V44 binary production (2026-03-28) ────────────────────────────
# V44: V43 + live empty-door-open augmentation. Fixes empty detection
# with 7 nodes active + door open. macro_f1=0.835, fp_rate=0.55%.
V26_BINARY_7NODE_MODEL_PATH = PROJECT / "output" / "train_runs" / "v44_retrain" / "v44_binary_candidate.pkl"
V26_BINARY_SHADOW_ENABLED = True
V26_BINARY_SHADOW_TELEMETRY_PATH = PROJECT / "temp" / "binary_7node_shadow_telemetry.ndjson"

# ── V53 binary shadow (2026-04-02) ────────────────────────────────
# V53: Runtime-matching feature extraction, 145 features.
# 625 empty + 524 occupied (Tenda-era recordings only).
# CV macro_f1=0.993.
V43_SHADOW_MODEL_PATH = PROJECT / "output" / "train_runs" / "v45_retrain" / "v53_shadow.pkl"
V43_SHADOW_ENABLED = os.environ.get("SHADOW_V43", "1") == "1"  # V45 enabled by default
V43_SHADOW_SEQ_LEN = 1  # V45 uses single-window (seq_len=1)
V43_SHADOW_LOG_PATH = PROJECT / "output" / "shadow_v43" / "shadow_log.jsonl"
OFFLINE_REGIME_CANDIDATE_NAME = "offline_regime_classifier1"
OFFLINE_REGIME_BUNDLE_PATH = (
    PROJECT
    / "output"
    / "train_runs"
    / "offline_regime_classifier1"
    / "offline_regime_classifier1_bundle.pkl"
)
OFFLINE_REGIME_SHADOW_ENABLED = os.environ.get("OFFLINE_REGIME_SHADOW", "1") == "1"
OFFLINE_REGIME_SHADOW_TELEMETRY_PATH = PROJECT / "temp" / "offline_regime_shadow_telemetry.ndjson"
EMPTY_SUBREGIME_CANDIDATE_NAME = "empty_subregime_shadow1"
EMPTY_SUBREGIME_BUNDLE_PATH = (
    PROJECT
    / "output"
    / "train_runs"
    / "empty_subregime_shadow1"
    / "empty_subregime_shadow1_bundle.pkl"
)
EMPTY_SUBREGIME_SHADOW_ENABLED = os.environ.get("EMPTY_SUBREGIME_SHADOW", "1") == "1"
EMPTY_SUBREGIME_SHADOW_TELEMETRY_PATH = PROJECT / "temp" / "empty_subregime_shadow_telemetry.ndjson"
EMPTY_SUBREGIME_RESCUE_ENABLED = os.environ.get("EMPTY_SUBREGIME_RESCUE", "1") == "1"  # default ON: corrects empty-like FP
EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS = 3
EMPTY_SUBREGIME_RESCUE_MIN_EMPTY_LIKE_RATIO = 0.8
EMPTY_SUBREGIME_RESCUE_MIN_DIAG_RATIO = 0.4
EMPTY_SUBREGIME_RESCUE_MAX_OCCUPIED_RATIO = 0.2
EMPTY_SUBREGIME_RESCUE_MIN_ACTIVE_NODES = 7
EMPTY_SUBREGIME_RESCUE_REQUIRED_ZONE = "center"
EMPTY_SUBREGIME_RESCUE_MIN_TARGET_Y = 3.0
EMPTY_SUBREGIME_RESCUE_MAX_TARGET_X = 1.4
EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_TARGET_X = 1.5
EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_TARGET_Y = 2.0  # extended: covers y=1.3..2.0 zone (was 1.3)
EMPTY_SUBREGIME_RESCUE_SHALLOW_MIN_EMPTY_LIKE_RATIO = 0.85
EMPTY_SUBREGIME_RESCUE_SHALLOW_MIN_DIAG_RATIO = 0.85
EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_OCCUPIED_RATIO = 0.15
EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_BINARY_CONF = 0.97
EMPTY_SUBREGIME_RESCUE_SHALLOW_MIN_V29_DOOR_PROB = 0.55
EMPTY_SUBREGIME_RESCUE_SHALLOW_HOLD_MAX_TARGET_X = 1.7
EMPTY_SUBREGIME_RESCUE_SHALLOW_HOLD_MAX_TARGET_Y = 1.3
EMPTY_SUBREGIME_RESCUE_HOLD_MIN_ACTIVE_NODES = 6
EMPTY_SUBREGIME_RESCUE_HOLD_MAX_PPS = 3.0
DEEP_RIGHT_SHADOW_CANDIDATE_NAME = "deep_right_shadow2"
DEEP_RIGHT_SHADOW_BUNDLE_PATH = (
    PROJECT
    / "output"
    / "train_runs"
    / "deep_right_shadow2"
    / "deep_right_shadow2_bundle.pkl"
)
DEEP_RIGHT_SHADOW_ENABLED = os.environ.get("DEEP_RIGHT_SHADOW", "1") == "1"
DEEP_RIGHT_SHADOW_TELEMETRY_PATH = PROJECT / "temp" / "deep_right_shadow_telemetry.ndjson"
DEEP_RIGHT_GUIDANCE_ENABLED = os.environ.get("DEEP_RIGHT_GUIDANCE", "1") == "1"
DEEP_RIGHT_GUIDANCE_CONSECUTIVE_WINDOWS = 2
DEEP_RIGHT_GUIDANCE_MIN_ACTIVE_NODES = 7
DEEP_RIGHT_GUIDANCE_MIN_PPS = 2.0
DEEP_RIGHT_GUIDANCE_HOLD_MIN_ACTIVE_NODES = 6
DEEP_RIGHT_GUIDANCE_HOLD_MIN_PPS = 1.5
DEEP_RIGHT_GUIDANCE_HOLD_MIN_PROB = 0.2
DEEP_RIGHT_GUIDANCE_RELEASE_NEGATIVE_WINDOWS = 3
DEEP_RIGHT_GUIDANCE_ALLOWED_ZONES = {"center", "door", "door_passage"}
DEEP_RIGHT_GUIDANCE_ANCHOR_X = 0.5
DEEP_RIGHT_GUIDANCE_ANCHOR_Y = 5.0
EMPTY_BASELINE_RESCUE_FRESH_SEC = 30 * 60
EMPTY_BASELINE_OPERATOR_ARM_SEC = 5 * 60
EMPTY_BASELINE_RESCUE_MIN_V8_CONF = 0.99
# Tuned against the current 192.168.0.* garage topology after a quiet empty
# recapture: the live empty stream reaches a stable 4-window run at these
# limits, while a confirmed 3-person center session stays below the
# 4-consecutive threshold.
EMPTY_BASELINE_RESCUE_CONSECUTIVE_WINDOWS = 4
EMPTY_BASELINE_OPERATOR_CONSECUTIVE_WINDOWS = 2
EMPTY_BASELINE_OPERATOR_MAX_PRIMARY_CONF = 0.80
EMPTY_BASELINE_RESCUE_AMP_DEV_MAX = 1.5
EMPTY_BASELINE_RESCUE_SC_VAR_DEV_MAX = 2.1
EMPTY_BASELINE_OPERATOR_STICKY_HOLD_SEC = 60
OUTSIDE_DOOR_LEAKAGE_GUARD_ENABLED = os.environ.get("OUTSIDE_DOOR_LEAKAGE_GUARD", "1") == "1"
OUTSIDE_DOOR_LEAKAGE_GUARD_PROMOTE = os.environ.get("OUTSIDE_DOOR_LEAKAGE_GUARD_PROMOTE", "0") == "1"
OUTSIDE_DOOR_LEAKAGE_CONSECUTIVE_WINDOWS = 4
OUTSIDE_DOOR_LEAKAGE_MIN_V29_DOOR_PROBA = 0.55
OUTSIDE_DOOR_LEAKAGE_MIN_TARGET_X = 1.45
OUTSIDE_DOOR_LEAKAGE_MAX_TARGET_Y = 3.35
OUTSIDE_DOOR_LEAKAGE_MIN_V8_CONF = 0.99
V8_EMPTY_PRIORITY_GUARD_ENABLED = os.environ.get("V8_EMPTY_PRIORITY_GUARD", "1") == "1"
V8_EMPTY_PRIORITY_CONSECUTIVE_WINDOWS = 3
V8_EMPTY_PRIORITY_MIN_V8_CONF = 0.99
V8_EMPTY_PRIORITY_MAX_PRIMARY_CONF = 0.86
V8_EMPTY_PRIORITY_RELEASE_CONSECUTIVE_WINDOWS = 3
V8_EMPTY_PRIORITY_RELEASE_MIN_PRIMARY_CONF = 0.79
SAFE_BINARY_ONLY_ZONE_MODE = os.environ.get("CSI_SAFE_BINARY_ONLY_ZONE_MODE", "1") == "1"
V48_PRODUCTION_DIR = PROJECT / "output" / "train_runs" / "v48_production"
V29_CNN_MAX_PACKETS = 40
V29_CNN_N_SC = 52  # subcarriers 2-53 per node
V29_CNN_SC_START = 2
V29_CNN_SC_END = 54
V29_CNN_ZONE_NAMES = ["door", "center", "deep"]
V29_CNN_IP_ORDER = [
    "192.168.0.137",  # node01
    "192.168.0.117",  # node02
    "192.168.0.144",  # node03
    "192.168.0.125",  # node04
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
    "192.168.0.137": (-1.50, 0.55),  # node01 — left wall, near door
    "192.168.0.117": (1.50, 0.55),   # node02 — right wall, near door
    "192.168.0.144": (-1.50, 3.15),  # node03 — left wall, mid-garage
    "192.168.0.143": (-1.50, 3.15),  # legacy node03 IP for old recordings
    "192.168.0.125": (1.50, 2.50),   # node04 — right wall, mid-garage
    "192.168.0.110":  (0.00, 3.50),   # node05 — center ceiling, door/center boundary
    "192.168.0.132":  (-1.50, 4.35),  # node06 — left wall, center zone
    "192.168.0.153":  (1.50, 3.70),   # node07 — right wall, center zone
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
        self._zone3_classifier = None
        self._zone3_labels = None
        self._zone3_feature_names = None
        self._zone3_scaler = None
        self._zone3_last = None
        self._zone3_err_count = 0

        # V57 multi-person classifier
        self.v57_model = None
        if V57_ENABLED:
            self.load_v57_model()

        # ── V48 binary hysteresis (3 consecutive windows to switch) ──
        self._v48_hysteresis_state = "empty"  # current stable state
        self._v48_hysteresis_count = 0        # consecutive windows disagreeing with state
        self._V48_HYSTERESIS_N = 3            # windows needed to flip
        self._MULTI_PERSON_COORD_GUARD_THRESHOLD = 0.50

        # Live packet buffer: {ip: [(t_sec, amp, phase), ...]}
        self._packets = defaultdict(list)
        self._start_time = None

        # ── Mesh link manager (peer-to-peer ESP-NOW links) ──────────────
        # Tracks per-link CSI buffers for 12+ inter-node links.
        # Backward-compatible: if no mesh data arrives, features are zeroed.
        self._mesh = MeshLinkManager()
        self._mesh_enabled = False  # set True when first mesh packet arrives
        self._last_window_time = 0
        self._recent_predictions = []
        self._transport = None
        self._csv_transport = None
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
            "coordinate_valid": False,
            "coordinate_reliability": "unavailable",
            "coordinate_guard": {
                "applied": False,
                "reason": "boot",
                "raw_target_x": None,
                "raw_target_y": None,
                "raw_target_zone": "unknown",
                "raw_coordinate_source": None,
                "multi_person_state": "single",
                "multi_person_confidence": 0.0,
            },
            "zone_confidence": 0.0,
            "zone_source": "none",
            "empty_subregime_rescue": {
                "enabled": EMPTY_SUBREGIME_RESCUE_ENABLED,
                "eligible": False,
                "applied": False,
                "consecutive": 0,
                "required_consecutive": EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS,
                "predicted_class": None,
                "recommended_action": None,
                "empty_like_ratio": 0.0,
                "diag_empty_ratio": 0.0,
                "occupied_anchor_ratio": 0.0,
            },
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
            "decision_model_version": "none",
            "decision_model_id": MODEL_PATH.name,
            "decision_model_backend": "unknown",
            "binary_threshold": 0.5,
            "feature_window_sec": float(WINDOW_SEC),
            "last_prediction_at": None,
            "last_error": None,
            "last_error_traceback": None,
            "feature_status": "boot",
            "garage": {"width": GARAGE_WIDTH, "height": GARAGE_HEIGHT,
                       "nodes": {ip: {"x": x, "y": y} for ip, (x, y) in NODE_POSITIONS.items()},
                       "door": {"x": DOOR_POSITION[0], "y": DOOR_POSITION[1]}},
            "history": [],
        }
        self._prev_target = (0.0, 0.0)  # for position smoothing only
        self._node_baselines = {}  # running mean per node for relative positioning
        self._active_model_path = str(MODEL_PATH)
        self._active_model_id = MODEL_PATH.name
        self._active_model_version = "none"
        self._active_model_kind = None
        self._base_binary_backend = "unknown"
        self._active_binary_backend = "unknown"
        self._feature_window_sec = float(WINDOW_SEC)

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
        self._fewshot_prototype_shadow: dict[str, Any] = {}
        self._fewshot_temporal_overlay_shadow: dict[str, Any] = {}
        self._live_door_shadow: dict[str, Any] = {}
        self._door_center_candidate_shadow: dict[str, Any] = {}
        self._fewshot_temporal_overlay_service = None
        self._live_door_shadow_service = None
        self._fewshot_temporal_overlay_state: str | None = None
        self._fewshot_temporal_overlay_pending: int = 0
        self._fewshot_temporal_overlay_bootstrap_scores: list[float] = []
        self._door_center_candidate_state: str | None = None
        self._door_center_candidate_pending_zone: str | None = None
        self._door_center_candidate_pending_count: int = 0
        self._door_signature_consecutive: int = 0

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
        self._v8_empty_priority_release_consecutive: int = 0
        self._v8_prev_target = (0.0, 0.0)
        self._v8_node_baselines = {}
        self._zone_coord_prev = (0.0, 0.0)  # EMA state for zone-based coordinates
        self._last_feat_dict: dict = {}     # last window feature dict for zone inject

        # ── Marker-GBR coordinate model (V1) ──────────────────────────
        # Trained on marker recordings with 5-fold CV: 0.57m mean, 0.37m median.
        # Predicts (x, y) from 437 CSI features → top 50 via scaler + GBR.
        self._coord_model: dict | None = None
        self._coord_model_loaded = False
        self._coord_gbr_prev = (0.0, 0.0)  # EMA state for GBR coordinates
        self._load_coord_gbr_model()
        self._shallow_coord_shadow_loaded = False
        self._shallow_coord_shadow_path: str | None = None
        self._shallow_coord_shadow: dict[str, Any] = {}
        self._shallow_coord_x = None
        self._shallow_coord_y = None
        self._shallow_coord_scaler = None
        self._shallow_coord_feature_names = None
        self._load_shallow_coord_shadow_bundle()

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

        # ── V60 mesh binary state ─────────────────────────────────────
        self._v60_model = None
        self._v60_feature_cols: list[str] = []
        self._v60_loaded = False
        self._v60_shadow: dict = {}
        self._v60_history: list[dict] = []
        self._v60_consecutive_empty = 0
        self._v60_consecutive_occupied = 0
        self._load_v60_mesh_binary()

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
        self._v43_scaler = None
        self._v43_pps_invariant = False
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

        # ── Offline regime classifier shadow state (2026-03-30) ───────
        # Bridge-surface regime bundle:
        #   - empty vs occupied: train-ready offline candidate
        #   - single vs multi: diagnostic only for now
        #   - three-class head: diagnostic only for now
        # Never overrides V48 production routing directly.
        self._offline_regime_bundle = None
        self._offline_regime_feature_cols: list[str] = []
        self._offline_regime_three_class_model = None
        self._offline_regime_empty_vs_occupied_model = None
        self._offline_regime_single_vs_multi_model = None
        self._offline_regime_analysis_path: Path | None = None
        self._offline_regime_verdict: dict[str, Any] = {}
        self._offline_regime_loaded = False
        self._offline_regime_shadow: dict = {}
        self._offline_regime_history: list[dict] = []
        self._empty_subregime_bundle = None
        self._empty_subregime_feature_names: list[str] = []
        self._empty_subregime_mu = None
        self._empty_subregime_sigma = None
        self._empty_subregime_centroids: dict[str, np.ndarray] = {}
        self._empty_subregime_ref_matrix = None
        self._empty_subregime_ref_labels: list[str] = []
        self._empty_subregime_ref_recordings: list[str] = []
        self._empty_subregime_top_k = 15
        self._empty_subregime_analysis_path: Path | None = None
        self._empty_subregime_verdict: dict[str, Any] = {}
        self._empty_subregime_loaded = False
        self._empty_subregime_shadow: dict = {}
        self._empty_subregime_history: list[dict] = []
        self._deep_right_shadow_bundle = None
        self._deep_right_shadow_feature_names: list[str] = []
        self._deep_right_shadow_model = None
        self._deep_right_shadow_scaler = None
        self._deep_right_shadow_analysis_path: Path | None = None
        self._deep_right_shadow_verdict: dict[str, Any] = {}
        self._deep_right_shadow_trigger_threshold = 0.6
        self._deep_right_shadow_positive_label = "marker7"
        self._deep_right_shadow_positive_alias = "deep_right"
        self._deep_right_shadow_negative_alias = "not_deep_right"
        self._deep_right_shadow_loaded = False
        self._deep_right_shadow: dict = {}
        self._deep_right_shadow_history: list[dict] = []
        self._deep_right_guidance_consecutive = 0
        self._deep_right_guidance_active = False
        self._deep_right_guidance_negative_consecutive = 0
        self._empty_subregime_rescue_consecutive = 0
        self._empty_baseline_rescue_consecutive = 0
        self._empty_baseline_rescue_hold_until = 0.0
        self._outside_door_leakage_consecutive = 0
        self._v8_empty_priority_consecutive = 0
        self._legacy_bridge_cache_window: tuple[float, float] | None = None
        self._legacy_bridge_cache_result: tuple[dict, int, int] | None = None

        # ── Zone calibration shadow state (per-session centroid) ────────
        # Shadow-only zone predictions from per-session NearestCentroid.
        # Does NOT affect V5 production output in any way.
        self._zone_calibration_shadow: dict = {}

        # ── Multi-person diagnostic estimator ─────────────────────────
        # Pragmatic heuristic that uses existing signals to estimate
        # whether more than one person is present.  The estimate is
        # diagnostic, but it also feeds a runtime guard so the UI does
        # not present a misleading single-person coordinate in a clearly
        # multi-person scene.
        self._mp_estimate: dict = {
            "person_count_estimate": 1,
            "multi_person_state": "single",      # single | multi | unresolved
            "multi_person_confidence": 0.0,
            "diagnostic_tracks": [],              # list of candidate dicts
            "diagnostic_cluster_center": None,
            "diagnostic_cluster_radius": 0.0,
            "estimator_source": "runtime_heuristic",
        }

    # ── V48 Epoch3 feature extraction ────────────────────────────────

    _V48_NODE_NAMES = {
        "192.168.0.137": "node01", "192.168.0.117": "node02",
        "192.168.0.144": "node03", "192.168.0.143": "node03", "192.168.0.125": "node04",
        "192.168.0.110":  "node05", "192.168.0.132":  "node06",
        "192.168.0.153":  "node07",
    }
    _V48_N_SUB = 192
    _V48_N_BANDS = 8
    _V48_BAND_SIZE = 24  # 192 / 8

    def _extract_v48_features(self, t_start: float, t_end: float) -> dict | None:
        """Extract V48-style features (133+ dims) from live CSI buffer.

        Returns feature dict with keys matching V48 training feature names:
        - Per-node (7 nodes × 14 features): amp_mean/std/max, rssi, tvar, pkt_count, 8 band means
        - Per-node phase features: phase_std, phase_mean, phase_coherence
        - Cross-node (21 ratios + 21 correlations)
        - Global stats (14 + 4 phase globals)
        """
        feat = {}
        node_amp_means = {}
        node_amp_vectors = {}
        node_phase_stds = {}
        node_phase_coherences = {}

        for ip in NODE_IPS:
            name = self._V48_NODE_NAMES.get(ip, ip)
            pkts = [(t, r, a, p) for t, r, a, p in self._packets.get(ip, [])
                    if t_start <= t < t_end]

            pkt_count = len(pkts)
            if pkt_count == 0:
                feat[f"{name}_amp_mean"] = 0.0
                feat[f"{name}_amp_std"] = 0.0
                feat[f"{name}_amp_max"] = 0.0
                feat[f"{name}_rssi_mean"] = -100.0
                feat[f"{name}_tvar"] = 0.0
                feat[f"{name}_pkt_count"] = 0
                for b in range(self._V48_N_BANDS):
                    feat[f"{name}_band{b}_mean"] = 0.0
                node_amp_means[name] = 0.0
                node_amp_vectors[name] = np.zeros(self._V48_N_SUB)
                node_phase_stds[name] = 0.0
                node_phase_coherences[name] = 0.0
                feat[f"{name}_phase_std"] = 0.0
                feat[f"{name}_phase_mean"] = 0.0
                feat[f"{name}_phase_coherence"] = 0.0
                feat[f"{name}_median_nsub"] = 0.0
                feat[f"{name}_pkt_size_std"] = 0.0
                feat[f"{name}_frac_short"] = 0.0
                continue

            # Normalize each amplitude vector to V48_N_SUB (192) subcarriers
            # before stacking. ESP32 nodes send mixed sizes (64/128/192) per packet.
            _TVAR_SUB = 64  # fallback minimum subcarrier count for tvar if mixed sizes
            _amp_rows = []
            for _, _, a, _ in pkts:
                row = np.zeros(self._V48_N_SUB, dtype=np.float32)
                n_copy = min(len(a), self._V48_N_SUB)
                row[:n_copy] = a[:n_copy]
                _amp_rows.append(row)
            amp_mat = np.array(_amp_rows, dtype=np.float32)
            rssis = np.array([r for _, r, _, _ in pkts], dtype=np.float32)

            # Per-packet mean: only over real subcarriers (not zero-padded)
            _pkt_lens_arr = np.array([min(len(a), self._V48_N_SUB) for _, _, a, _ in pkts], dtype=np.float32)
            amp_means_per_pkt = np.array([float(amp_mat[i, :int(_pkt_lens_arr[i])].mean())
                                          if _pkt_lens_arr[i] > 0 else 0.0
                                          for i in range(pkt_count)], dtype=np.float32)
            mean_amp_vec = amp_mat.mean(axis=0)

            feat[f"{name}_amp_mean"] = float(amp_means_per_pkt.mean())
            feat[f"{name}_amp_std"] = float(amp_means_per_pkt.std())
            baseline_sc_var_mean = float(amp_mat.var(axis=0).mean()) if pkt_count >= 2 else 0.0
            # Keep parity with offline V48 training extractor: amp_max is the
            # maximum individual subcarrier amplitude observed in the packet
            # matrix, not the maximum of per-packet mean amplitudes.
            feat[f"{name}_amp_max"] = float(np.max(amp_mat))
            feat[f"{name}_rssi_mean"] = float(rssis.mean())
            # tvar: use first 64 subcarriers ONLY, excluding dead ones (DC + guard)
            # Matches V55 training with LIVE_SUBCARRIER_MASK_64.
            if pkt_count >= 2:
                feat[f"{name}_tvar"] = float(np.mean(np.var(amp_mat[:, :_TVAR_SUB][:, _LIVE_SC_MASK_64], axis=0)))
            else:
                feat[f"{name}_tvar"] = 0.0
            feat[f"{name}_pkt_count"] = pkt_count

            # Packet size normalization features
            feat[f"{name}_median_nsub"] = float(np.median(_pkt_lens_arr))
            feat[f"{name}_pkt_size_std"] = float(np.std(_pkt_lens_arr))
            feat[f"{name}_frac_short"] = float(np.mean(_pkt_lens_arr <= 64))

            # 8-band spectral features — only average across packets that
            # actually have subcarriers in that band (avoids dilution from
            # zero-padded short packets: 63-sub packets have no data for bands 3-7)
            _pkt_lens = np.array([min(len(a), self._V48_N_SUB) for _, _, a, _ in pkts])
            for b in range(self._V48_N_BANDS):
                b_start = b * self._V48_BAND_SIZE
                b_end = b_start + self._V48_BAND_SIZE
                # Only include packets that have at least b_end subcarriers
                _band_mask = _pkt_lens >= b_end
                if _band_mask.any():
                    feat[f"{name}_band{b}_mean"] = float(amp_mat[_band_mask, b_start:b_end].mean())
                else:
                    feat[f"{name}_band{b}_mean"] = 0.0

            node_amp_means[name] = feat[f"{name}_amp_mean"]
            node_amp_vectors[name] = mean_amp_vec

            # Phase features (from same packet window)
            # ── CMU Phase Sanitization: полный multi-packet pipeline на окне ──
            # unwrap (axis=0) + linear trend removal + median filter + mean removal
            phase_pkts = [p for _, _, _, p in pkts if p is not None and len(p) > 0]
            if len(phase_pkts) >= 5:
                # Normalize phase vectors: truncate to minimum common length
                # to avoid artificial phase jumps from zero-padded positions
                _ph_min_sub = min(len(ph) for ph in phase_pkts)
                _ph_min_sub = min(_ph_min_sub, self._V48_N_SUB)
                _ph_rows = []
                for ph in phase_pkts:
                    row = np.zeros(self._V48_N_SUB, dtype=np.float32)
                    n_copy = min(len(ph), self._V48_N_SUB)
                    row[:n_copy] = ph[:n_copy]
                    _ph_rows.append(row)
                phase_mat = np.array(_ph_rows, dtype=np.float32)
                # Полный CMU pipeline на окне пакетов (unwrap + trend + median + mean)
                try:
                    from .csi_phase_sanitization import sanitize_phase
                    ph_unwrap = sanitize_phase(phase_mat)  # (n_pkts, n_sub), float32
                except Exception:
                    ph_unwrap = np.unwrap(phase_mat, axis=0)  # fallback
                ph_rate = np.diff(ph_unwrap, axis=0)
                feat[f"{name}_phase_rate_mean"] = float(np.abs(ph_rate).mean())
                feat[f"{name}_phase_rate_std"] = float(ph_rate.std())
                feat[f"{name}_phase_spatial_std"] = float(phase_mat.std(axis=1).mean())
                corrs = []
                for sc in range(0, min(phase_mat.shape[1] - 1, 32), 4):
                    c = np.corrcoef(phase_mat[:, sc], phase_mat[:, sc + 1])[0, 1]
                    if not np.isnan(c):
                        corrs.append(abs(c))
                feat[f"{name}_phase_coherence"] = float(np.mean(corrs)) if corrs else 0.0
            else:
                feat[f"{name}_phase_rate_mean"] = 0.0
                feat[f"{name}_phase_rate_std"] = 0.0
                feat[f"{name}_phase_spatial_std"] = 0.0
                feat[f"{name}_phase_coherence"] = 0.0

            # Empty baseline recapture must work under the active V48 path.
            # Record the same per-node statistics the rescue layer expects,
            # keyed by live node IP, instead of relying on the legacy sidecar.
            if self._baseline_capture_active and pkt_count >= 3:
                self._record_baseline_observation(
                    ip,
                    amp_mean=feat[f"{name}_amp_mean"],
                    phase_rate_mean=feat[f"{name}_phase_rate_mean"],
                    sc_var_mean=baseline_sc_var_mean,
                )

            # ── IQ-derived phase features (drift-robust, matches training) ──
            # Build raw phase matrix from packet phase arrays (atan2-derived at ingest).
            # Use first _TVAR_SUB=64 subcarriers only, matching tvar convention.
            _raw_phase_rows = []
            for _, _, _, p in pkts:
                if p is not None and len(p) > 0:
                    row = np.zeros(_TVAR_SUB, dtype=np.float32)
                    n_copy = min(len(p), _TVAR_SUB)
                    row[:n_copy] = p[:n_copy]
                    _raw_phase_rows.append(row)

            if len(_raw_phase_rows) >= 1:
                _raw_phase_mat = np.array(_raw_phase_rows, dtype=np.float32)  # (n_pkts, 64)
                n_ph_pkts = _raw_phase_mat.shape[0]

                # phase_mean: circular mean across all packets and first 64 subcarriers
                _circ_mean = np.angle(np.mean(np.exp(1j * _raw_phase_mat)))
                feat[f"{name}_phase_mean"] = float(_circ_mean)

                # phase_std: std of per-packet circular mean phase across the window
                # Per-packet circular mean: angle(mean(exp(1j * phase_per_packet)))
                _per_pkt_circ_mean = np.angle(
                    np.mean(np.exp(1j * _raw_phase_mat), axis=1)
                )  # (n_pkts,)
                feat[f"{name}_phase_std"] = float(np.std(_per_pkt_circ_mean))

                # phase_coherence: mean abs correlation of phase between consecutive packets
                if n_ph_pkts >= 2:
                    _ph_corrs = []
                    for pidx in range(n_ph_pkts - 1):
                        _s1 = _raw_phase_mat[pidx]
                        _s2 = _raw_phase_mat[pidx + 1]
                        if np.std(_s1) > 0 and np.std(_s2) > 0:
                            _c = np.corrcoef(_s1, _s2)[0, 1]
                            if not np.isnan(_c):
                                _ph_corrs.append(abs(_c))
                    feat[f"{name}_phase_coherence"] = float(np.mean(_ph_corrs)) if _ph_corrs else 0.0
                else:
                    feat[f"{name}_phase_coherence"] = 0.0

                node_phase_stds[name] = feat[f"{name}_phase_std"]
                node_phase_coherences[name] = feat[f"{name}_phase_coherence"]
            else:
                feat[f"{name}_phase_std"] = 0.0
                feat[f"{name}_phase_mean"] = 0.0
                feat[f"{name}_phase_coherence"] = 0.0
                node_phase_stds[name] = 0.0
                node_phase_coherences[name] = 0.0

        # Cross-node amplitude ratios (21 pairs)
        node_list = sorted(node_amp_means.keys())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                n1, n2 = node_list[i], node_list[j]
                a1, a2 = node_amp_means[n1], node_amp_means[n2]
                # Match V55 training: guard low amps
                if a1 < 0.1 or a2 < 0.1:
                    feat[f"ratio_{n1}_{n2}"] = 1.0
                else:
                    feat[f"ratio_{n1}_{n2}"] = a1 / a2

        # Cross-node correlations (21 pairs)
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                n1, n2 = node_list[i], node_list[j]
                v1, v2 = node_amp_vectors[n1], node_amp_vectors[n2]
                if np.std(v1) > 0 and np.std(v2) > 0:
                    feat[f"corr_{n1}_{n2}"] = float(np.corrcoef(v1, v2)[0, 1])
                else:
                    feat[f"corr_{n1}_{n2}"] = 0.0

        # Global stats
        tvars = [feat.get(f"{n}_tvar", 0) for n in node_list]
        amp_means_list = [node_amp_means.get(n, 0) for n in node_list]
        rssi_means = [feat.get(f"{n}_rssi_mean", -100) for n in node_list]

        feat["tvar_mean"] = float(np.mean(tvars))
        feat["tvar_max"] = float(np.max(tvars))
        feat["tvar_std"] = float(np.std(tvars))
        feat["tvar_min"] = float(np.min(tvars))
        # Match V55 training: count nodes with tvar > 1.0
        feat["tvar_active_nodes"] = int(sum(1 for t in tvars if t > 1.0))
        feat["amp_mean_global"] = float(np.mean(amp_means_list))
        feat["amp_std_global"] = float(np.std(amp_means_list))
        feat["amp_spread"] = float(max(amp_means_list) - min(amp_means_list))
        feat["rssi_mean_global"] = float(np.mean(rssi_means))
        feat["rssi_std_global"] = float(np.std(rssi_means))
        feat["rssi_spread"] = float(max(rssi_means) - min(rssi_means))
        # Amplitude entropy
        pos_amps = [a for a in amp_means_list if a > 0]
        if pos_amps:
            s = sum(pos_amps)
            feat["amp_entropy"] = float(-sum((a / s) * math.log(a / s + 1e-10) for a in pos_amps))
        else:
            feat["amp_entropy"] = 0.0
        feat["total_pkt_count"] = sum(feat.get(f"{n}_pkt_count", 0) for n in node_list)
        feat["active_nodes"] = sum(1 for n in node_list if feat.get(f"{n}_pkt_count", 0) > 0)

        # Additional global features from band data
        all_band_means = []
        for n in node_list:
            for b in range(self._V48_N_BANDS):
                all_band_means.append(feat.get(f"{n}_band{b}_mean", 0))
        feat["band_mean_global"] = float(np.mean(all_band_means))
        feat["band_std_global"] = float(np.std(all_band_means))
        feat["band_max_global"] = float(np.max(all_band_means))
        feat["band_min_global"] = float(np.min(all_band_means))
        feat["band_spread_global"] = feat["band_max_global"] - feat["band_min_global"]

        # Global packet size features
        all_median_nsubs = [feat.get(f"{n}_median_nsub", 0) for n in node_list]
        all_frac_shorts = [feat.get(f"{n}_frac_short", 0) for n in node_list]
        feat["nsub_mean_global"] = float(np.mean(all_median_nsubs))
        feat["nsub_std_global"] = float(np.std(all_median_nsubs))
        feat["frac_short_global"] = float(np.mean(all_frac_shorts))

        # Global phase features (drift-robust, matches training)
        _ph_stds = [node_phase_stds.get(n, 0.0) for n in node_list]
        _ph_cohs = [node_phase_coherences.get(n, 0.0) for n in node_list]
        feat["phase_std_mean"] = float(np.mean(_ph_stds))
        feat["phase_std_max"] = float(np.max(_ph_stds)) if _ph_stds else 0.0
        feat["phase_coherence_mean"] = float(np.mean(_ph_cohs))
        feat["phase_active_nodes"] = int(sum(1 for ps in _ph_stds if ps > 0.5))

        if feat["active_nodes"] < 2:
            return None

        # Few-shot calibration packets persist a compact `csi_nodeXX_*` surface.
        # Mirror those aliases in the live V48 extractor so prototype shadow
        # sees the same online keys as the calibration storage snapshots.
        _window_sec = max(float(t_end - t_start), 1e-3)
        feat["chunk_packets"] = float(feat.get("total_pkt_count", 0.0))
        feat["chunk_pps"] = float(feat["chunk_packets"] / _window_sec)
        for n in node_list:
            _idx = n.replace("node", "")
            feat[f"csi_node{_idx}_rssi_mean"] = float(feat.get(f"{n}_rssi_mean", -100.0))
            feat[f"csi_node{_idx}_amp_mean"] = float(feat.get(f"{n}_amp_mean", 0.0))
            feat[f"csi_node{_idx}_motion_mean"] = float(feat.get(f"{n}_tvar", 0.0))
            feat[f"csi_node{_idx}_packets"] = float(feat.get(f"{n}_pkt_count", 0.0))

        # ── Mesh link features (ESP-NOW peer-to-peer) ──────────────────
        # If mesh data is available, extract per-link and cross-link features.
        # These are additive and backward-compatible: when no mesh data
        # exists, all mesh features are 0.0 and the model can ignore them.
        if self._mesh_enabled and self._mesh.peer_link_count > 0:
            mesh_feats = self._mesh.extract_all_link_features(
                t_start, t_end, peer_only=False, max_links=16,
            )
            feat.update(mesh_feats)
        else:
            # Zero-fill mesh aggregate features for backward compat
            feat["mesh_spatial_variance"] = 0.0
            feat["mesh_link_agreement"] = 1.0
            feat["mesh_max_link_delta"] = 0.0
            feat["mesh_active_peer_links"] = 0.0

        return feat

    # ── V60 mesh binary model ───────────────────────────────────────

    # All 42 peer link IDs used by V60 training (rx<-tx format mapped to feature prefix)
    _V60_ALL_NODES = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]
    _V60_TOP_PEER_LINKS = [
        "n03<-n07", "n03<-n01", "n05<-n02", "n06<-n04", "n05<-n06",
        "n03<-n04", "n07<-n03", "n04<-n06", "n07<-n05", "n06<-n03",
    ]

    def _load_v60_mesh_binary(self) -> None:
        """Load V60 mesh binary model (GBM-500 trained on peer-to-peer CSI)."""
        if not V60_MESH_BINARY_ENABLED:
            logger.debug("V60 mesh binary disabled")
            return
        if not V60_MESH_BINARY_MODEL_PATH.exists():
            logger.info("V60 mesh binary model not found: %s", V60_MESH_BINARY_MODEL_PATH)
            return
        try:
            import joblib
            bundle = joblib.load(V60_MESH_BINARY_MODEL_PATH)
            self._v60_model = bundle["model"]
            self._v60_feature_cols = bundle["feature_cols"]
            self._v60_loaded = True
            logger.info(
                "V60 mesh binary loaded: %s, %d features, CV F1=%.4f",
                bundle.get("model_name", "?"),
                len(self._v60_feature_cols),
                bundle.get("cv_f1_mean", 0),
            )
        except Exception as e:
            logger.error("Failed to load V60 mesh binary: %s", e)
            self._v60_loaded = False

    def _extract_v60_mesh_features(self, t_start: float, t_end: float) -> dict | None:
        """Extract V60-style mesh features from live MeshLinkManager buffers.

        Returns feature dict with 453 keys matching V60 training schema:
        - Per-node router features (7 nodes × 16 features)
        - Per-peer-link features (42 links × 8 features)
        - Top-10 peer aggregate features (5)
        - Cross-link spatial features (3)
        - Global counts (4)
        """
        if not self._mesh_enabled or self._mesh.peer_link_count < V60_MESH_MIN_PEER_LINKS:
            return None

        feat: dict[str, float] = {}
        N_SUB = self._V48_N_SUB  # 192

        # ── Per-node router features ──────────────────────────────────
        for node in self._V60_ALL_NODES:
            link_id = self._mesh.make_link_id(node, "router")
            pkts = self._mesh.get_link_packets(link_id, t_start, t_end)
            prefix = f"{node}_router"

            if len(pkts) >= 2:
                amps = np.array([np.pad(p.amplitude, (0, max(0, N_SUB - len(p.amplitude))))[:N_SUB]
                                 for p in pkts], dtype=np.float32)
                rssis = np.array([p.rssi for p in pkts], dtype=np.float32)

                feat[f"{prefix}_pkt_count"] = float(len(pkts))
                feat[f"{prefix}_amp_mean"] = float(np.mean(amps))
                feat[f"{prefix}_amp_std"] = float(np.std(amps))
                feat[f"{prefix}_amp_max"] = float(np.max(amps))
                feat[f"{prefix}_amp_min"] = float(np.min(np.mean(amps, axis=1)))
                feat[f"{prefix}_rssi_mean"] = float(np.mean(rssis))
                feat[f"{prefix}_tvar"] = float(np.mean(np.var(amps, axis=0)))
                band_size = N_SUB // 8
                for b in range(8):
                    s, e = b * band_size, min((b + 1) * band_size, N_SUB)
                    feat[f"{prefix}_band{b}_mean"] = float(np.mean(amps[:, s:e]))
            else:
                feat[f"{prefix}_pkt_count"] = float(len(pkts))
                for k in ["amp_mean", "amp_std", "amp_max", "amp_min", "rssi_mean", "tvar"]:
                    feat[f"{prefix}_{k}"] = 0.0
                for b in range(8):
                    feat[f"{prefix}_band{b}_mean"] = 0.0

        # ── Per-peer-link features ────────────────────────────────────
        peer_amp_vars: dict[str, float] = {}
        peer_pccs: dict[str, float] = {}
        total_peer_pkts = 0
        total_router_pkts = 0

        for rx in self._V60_ALL_NODES:
            for tx in self._V60_ALL_NODES:
                if rx == tx:
                    continue
                train_link = f"{rx}<-{tx}"  # training format
                mesh_link = self._mesh.make_link_id(rx, tx)  # runtime format (rx_tx)
                pkts = self._mesh.get_link_packets(mesh_link, t_start, t_end)
                prefix = f"peer_{rx}_from_{tx}"
                total_peer_pkts += len(pkts)

                if len(pkts) >= 2:
                    amps = np.array([np.pad(p.amplitude, (0, max(0, N_SUB - len(p.amplitude))))[:N_SUB]
                                     for p in pkts], dtype=np.float32)
                    phases = np.array([np.pad(p.phase, (0, max(0, N_SUB - len(p.phase))))[:N_SUB]
                                       for p in pkts], dtype=np.float32)
                    rssis = np.array([p.rssi for p in pkts], dtype=np.float32)

                    amp_var = float(np.mean(np.var(amps, axis=0)))
                    peer_amp_vars[train_link] = amp_var

                    pcc_vals = []
                    for i in range(1, len(amps)):
                        c = np.corrcoef(amps[i - 1], amps[i])[0, 1]
                        if not np.isnan(c):
                            pcc_vals.append(c)
                    mean_pcc = float(np.mean(pcc_vals)) if pcc_vals else 0.0
                    peer_pccs[train_link] = mean_pcc

                    phase_stab = float(np.mean(np.abs(np.diff(phases, axis=0)))) if len(phases) > 1 else 0.0

                    feat[f"{prefix}_pkt_count"] = float(len(pkts))
                    feat[f"{prefix}_amp_var"] = amp_var
                    feat[f"{prefix}_amp_mean"] = float(np.mean(amps))
                    feat[f"{prefix}_amp_std"] = float(np.std(amps))
                    feat[f"{prefix}_pcc"] = mean_pcc
                    feat[f"{prefix}_phase_stab"] = phase_stab
                    feat[f"{prefix}_rssi_mean"] = float(np.mean(rssis))
                    feat[f"{prefix}_rssi_std"] = float(np.std(rssis))
                else:
                    feat[f"{prefix}_pkt_count"] = float(len(pkts))
                    for k in ["amp_var", "amp_mean", "amp_std", "pcc", "phase_stab", "rssi_mean", "rssi_std"]:
                        feat[f"{prefix}_{k}"] = 0.0

        # Count router packets
        for node in self._V60_ALL_NODES:
            link_id = self._mesh.make_link_id(node, "router")
            total_router_pkts += len(self._mesh.get_link_packets(link_id, t_start, t_end))

        # ── Top-10 peer aggregate ─────────────────────────────────────
        top_vars = [peer_amp_vars.get(l, 0.0) for l in self._V60_TOP_PEER_LINKS]
        top_pccs = [peer_pccs.get(l, 0.0) for l in self._V60_TOP_PEER_LINKS]
        feat["top10_amp_var_mean"] = float(np.mean(top_vars))
        feat["top10_amp_var_max"] = float(np.max(top_vars))
        feat["top10_amp_var_std"] = float(np.std(top_vars))
        feat["top10_pcc_mean"] = float(np.mean(top_pccs))
        feat["top10_pcc_std"] = float(np.std(top_pccs))

        # ── Cross-link spatial features ───────────────────────────────
        all_vars = list(peer_amp_vars.values())
        if len(all_vars) >= 3:
            feat["mesh_spatial_var"] = float(np.var(all_vars))
            feat["mesh_var_spread"] = float(np.max(all_vars) - np.min(all_vars))
            feat["mesh_active_peer_links"] = float(len(all_vars))
        else:
            feat["mesh_spatial_var"] = 0.0
            feat["mesh_var_spread"] = 0.0
            feat["mesh_active_peer_links"] = 0.0

        # ── Global counts ─────────────────────────────────────────────
        total = total_peer_pkts + total_router_pkts
        feat["total_pkt_count"] = float(total)
        feat["peer_pkt_count"] = float(total_peer_pkts)
        feat["router_pkt_count"] = float(total_router_pkts)
        feat["peer_ratio"] = float(total_peer_pkts) / max(total, 1)

        if total < 5:
            return None

        return feat

    # ── Marker-GBR coordinate model loader ──────────────────────────

    _COORD_MODEL_PATH = PROJECT / "output" / "marker_recordings" / "coord_model_v3_extended.pkl"

    def _load_coord_gbr_model(self):
        """Load trained GBR coordinate model (V2 PPS-invariant or V1 legacy)."""
        if not self._COORD_MODEL_PATH.exists():
            logger.info("Coord GBR model not found: %s", self._COORD_MODEL_PATH)
            return
        try:
            with self._COORD_MODEL_PATH.open("rb") as f:
                bundle = pickle.load(f)
            # V2 uses "feature_names", V1 uses "feature_keys"
            feat_key = "feature_names" if "feature_names" in bundle else "feature_keys"
            for key in (feat_key, "scaler", "model_x", "model_y"):
                if key not in bundle:
                    logger.warning("Coord model missing key '%s', skipping", key)
                    return
            self._coord_model = bundle
            self._coord_model_loaded = True
            version = bundle.get("version", "v1")
            n_feat = len(bundle[feat_key])
            cv_val = bundle.get("cv_5fold_mean", bundle.get("cv_5fold_combined_mae", -1))
            logger.info(
                "Coord model loaded: version=%s, %d features, CV=%.3fm",
                version, n_feat, cv_val,
            )
        except Exception as e:
            logger.warning("Failed to load coord model: %s", e)

    def _find_latest_shallow_coord_shadow_bundle(self) -> Path | None:
        try:
            candidates = sorted(
                V48_PRODUCTION_DIR.glob("v48_production.pkl.bad_shallow_candidate_*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return None
        return candidates[0] if candidates else None

    def _load_shallow_coord_shadow_bundle(self):
        self._shallow_coord_shadow_loaded = False
        self._shallow_coord_shadow_path = None
        self._shallow_coord_shadow = {}
        self._shallow_coord_x = None
        self._shallow_coord_y = None
        self._shallow_coord_scaler = None
        self._shallow_coord_feature_names = None

        bundle_path = self._find_latest_shallow_coord_shadow_bundle()
        if bundle_path is None or not bundle_path.exists():
            return
        try:
            with bundle_path.open("rb") as handle:
                bundle = pickle.load(handle)
            self._shallow_coord_x = bundle.get("coordinate_model_x")
            self._shallow_coord_y = bundle.get("coordinate_model_y")
            self._shallow_coord_scaler = bundle.get("coordinate_scaler")
            self._shallow_coord_feature_names = bundle.get("coordinate_feature_names")
            if self._shallow_coord_x is None or self._shallow_coord_y is None or self._shallow_coord_feature_names is None:
                return
            self._shallow_coord_shadow_loaded = True
            self._shallow_coord_shadow_path = str(bundle_path.resolve())
            logger.info("Shallow coord shadow loaded: %s", bundle_path.name)
        except Exception as e:
            logger.warning("Failed to load shallow coord shadow bundle: %s", e)

    def _predict_shallow_coord_shadow(self, feat_dict: dict[str, Any]) -> tuple[float, float] | None:
        if not self._shallow_coord_shadow_loaded:
            return None
        try:
            coord_feats = self._shallow_coord_feature_names or self.feature_names
            Xc = np.array([[feat_dict.get(f, 0) for f in coord_feats]], dtype=np.float32)
            Xc = np.nan_to_num(Xc, nan=0, posinf=0, neginf=0)
            if self._shallow_coord_scaler is not None:
                Xc = self._shallow_coord_scaler.transform(Xc)
            pred_x = float(self._shallow_coord_x.predict(Xc)[0])
            pred_y = float(self._shallow_coord_y.predict(Xc)[0])
            return pred_x, pred_y
        except Exception as e:
            logger.debug("Shallow coord shadow predict failed: %s", e)
            return None

    def _predict_coord_gbr(self, feat_dict: dict) -> tuple[float, float] | None:
        """Predict (x, y) from feature dict using GBR coordinate model.

        Supports V2 (PPS-invariant 26 features) and V1 (437 features + top idx).
        Returns (x, y) clipped to garage bounds, or None on failure.
        """
        if not self._coord_model_loaded or self._coord_model is None:
            return None
        try:
            import numpy as np
            bundle = self._coord_model

            # V2/V3: PPS-invariant features with extra ratios computed at runtime
            if "feature_names" in bundle:
                feature_names = bundle["feature_names"]
                scaler = bundle["scaler"]
                model_x = bundle["model_x"]
                model_y = bundle["model_y"]

                # Compute extra ratios (pairwise amp ratios)
                extra_ratios = bundle.get("extra_ratios", {})
                augmented = dict(feat_dict)
                for rname, (num, den) in extra_ratios.items():
                    n = float(augmented.get(num, 0) or 0)
                    d = float(augmented.get(den, 0) or 0)
                    augmented[rname] = n / d if d != 0 else 0.0

                # V3 extended: compute derived features at runtime
                _NODES = ["node01","node02","node03","node04","node05","node06","node07"]
                # Subcarrier entropy stats
                sc_ents = [float(augmented.get(f"csi_{n}_sc_entropy", 0) or 0) for n in _NODES]
                augmented["sc_ent_mean"] = float(np.mean(sc_ents)) if sc_ents else 0.0
                augmented["sc_ent_std"] = float(np.std(sc_ents)) if sc_ents else 0.0
                augmented["sc_ent_max"] = float(np.max(sc_ents)) if sc_ents else 0.0
                augmented["sc_ent_min"] = float(np.min(sc_ents)) if sc_ents else 0.0
                # Amplitude variance concentration
                amp_vars = [float(augmented.get(f"csi_{n}_sc_var", 0) or 0) for n in _NODES]
                total_var = sum(amp_vars) + 1e-10
                for i, n in enumerate(_NODES):
                    augmented[f"{n}_var_conc"] = amp_vars[i] / total_var
                # Cross-node amp_norm stats
                amp_norms = [float(augmented.get(f"csi_{n}_amp_norm", 0) or 0) for n in _NODES]
                augmented["amp_norm_mean"] = float(np.mean(amp_norms))
                augmented["amp_norm_std"] = float(np.std(amp_norms))
                augmented["amp_norm_range"] = float(max(amp_norms) - min(amp_norms))
                _mn = float(np.mean(amp_norms)); _sd = float(np.std(amp_norms)) + 1e-10
                augmented["amp_norm_skew"] = float(np.mean([(x - _mn)**3 for x in amp_norms]) / (_sd**3))
                # RSSI cross-node stats
                rssi_norms = [float(augmented.get(f"csi_{n}_rssi_norm", 0) or 0) for n in _NODES]
                augmented["rssi_norm_mean"] = float(np.mean(rssi_norms))
                augmented["rssi_norm_std"] = float(np.std(rssi_norms))
                augmented["rssi_norm_range"] = float(max(rssi_norms) - min(rssi_norms))
                # Left-right asymmetry
                left_amp = float(np.mean([augmented.get("node01_amp_norm", augmented.get("csi_node01_amp_norm", 0)), augmented.get("node03_amp_norm", augmented.get("csi_node03_amp_norm", 0))]))
                right_amp = float(np.mean([augmented.get("node02_amp_norm", augmented.get("csi_node02_amp_norm", 0)), augmented.get("node04_amp_norm", augmented.get("csi_node04_amp_norm", 0))]))
                augmented["lr_asymmetry"] = left_amp - right_amp
                augmented["lr_ratio"] = left_amp / (right_amp + 1e-10)
                # Near-far asymmetry
                near_amp = float(np.mean([augmented.get("node01_amp_norm", augmented.get("csi_node01_amp_norm", 0)), augmented.get("node02_amp_norm", augmented.get("csi_node02_amp_norm", 0))]))
                far_amp = float(np.mean([augmented.get("node03_amp_norm", augmented.get("csi_node03_amp_norm", 0)), augmented.get("node04_amp_norm", augmented.get("csi_node04_amp_norm", 0))]))
                augmented["nf_asymmetry"] = near_amp - far_amp
                augmented["nf_ratio"] = near_amp / (far_amp + 1e-10)
                # Rename csi_nodeXX_ -> nodeXX_ for V3 feature names
                for n in _NODES:
                    for suffix in ("amp_norm", "rssi_norm"):
                        csi_key = f"csi_{n}_{suffix}"
                        plain_key = f"{n}_{suffix}"
                        if plain_key not in augmented and csi_key in augmented:
                            augmented[plain_key] = augmented[csi_key]

                raw = np.array(
                    [float(augmented.get(k, 0.0) or 0.0) for k in feature_names],
                    dtype=np.float64,
                ).reshape(1, -1)
                raw = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
                scaled = scaler.transform(raw)

            else:
                # V1 legacy: 437 features + top_feature_idx
                feature_keys = bundle["feature_keys"]
                scaler = bundle["scaler"]
                top_idx = bundle["top_feature_idx"]
                model_x = bundle["model_x"]
                model_y = bundle["model_y"]

                raw = np.array(
                    [float(feat_dict.get(k, 0.0) or 0.0) for k in feature_keys],
                    dtype=np.float64,
                ).reshape(1, -1)
                raw = np.nan_to_num(raw, nan=0.0, posinf=0.0, neginf=0.0)
                scaled = scaler.transform(raw)[:, top_idx]

            x = float(model_x.predict(scaled)[0])
            y = float(model_y.predict(scaled)[0])

            # Clip to garage bounds
            x = max(0.0, min(3.0, x))
            y = max(0.0, min(7.0, y))
            return (x, y)
        except Exception as e:
            logger.debug("Coord GBR predict failed: %s", e)
            return None

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
        self._empty_baseline_rescue_hold_until = 0.0
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
        self._empty_baseline_rescue_hold_until = 0.0
        logger.info("V19 gate hysteresis reset on baseline recapture")
        return {
            "status": "ok",
            "nodes_calibrated": len(profiles),
            "profiles": {ip: {k: round(v, 4) if isinstance(v, float) else v
                              for k, v in p.items()}
                         for ip, p in profiles.items()},
        }

    def _record_baseline_observation(
        self,
        ip: str,
        *,
        amp_mean: float,
        phase_rate_mean: float,
        sc_var_mean: float,
    ) -> None:
        """Append one per-node empty-baseline observation for the current window."""
        if not self._baseline_capture_active:
            return
        self._baseline_capture_windows[ip].append({
            "amp_mean": float(amp_mean),
            "phase_rate_mean": float(phase_rate_mean),
            "sc_var_mean": float(sc_var_mean),
        })

    def _record_baseline_window(self, ip: str, feat: dict, pre: str):
        """Record one window's stats during baseline capture."""
        self._record_baseline_observation(
            ip,
            amp_mean=feat.get(f"{pre}_mean", 0),
            phase_rate_mean=feat.get(f"{pre}_phase_rate_mean", 0),
            sc_var_mean=feat.get(f"{pre}_sc_var_mean", 0),
        )

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

    def _empty_baseline_is_fresh(self) -> bool:
        """Treat the latest empty baseline as fresh for a short rescue window."""
        if not self._BASELINE_PATH.exists():
            return False
        try:
            age_sec = time.time() - self._BASELINE_PATH.stat().st_mtime
        except OSError:
            return False
        return age_sec <= EMPTY_BASELINE_RESCUE_FRESH_SEC

    def _empty_baseline_is_operator_recent(self) -> bool:
        """Treat a just-captured empty baseline as an explicit operator-empty signal."""
        if not self._BASELINE_PATH.exists():
            return False
        try:
            age_sec = time.time() - self._BASELINE_PATH.stat().st_mtime
        except OSError:
            return False
        return age_sec <= EMPTY_BASELINE_OPERATOR_ARM_SEC

    def _get_legacy_bridge_window_result(
        self,
        t_start: float,
        t_end: float,
    ) -> tuple[dict, int, int] | None:
        """Return cached legacy bridge features for the current window."""
        cache_key = (float(t_start), float(t_end))
        if self._legacy_bridge_cache_window == cache_key and self._legacy_bridge_cache_result is not None:
            return self._legacy_bridge_cache_result

        legacy_result = self._extract_window_features(t_start, t_end, record_baseline=False)
        self._legacy_bridge_cache_window = cache_key
        self._legacy_bridge_cache_result = legacy_result
        return legacy_result

    def _apply_fresh_empty_baseline_rescue(
        self,
        *,
        t_start: float,
        t_end: float,
        active_nodes: int,
        motion_state: str,
    ) -> None:
        """Force empty when a freshly captured baseline and V8 agree on empty.

        This is intentionally narrow:
        - only shortly after an operator recaptures a known-empty baseline
        - only on stable no-motion windows
        - only when full 7-node topology is active
        - only after V8 shadow says empty for several consecutive windows
        """
        current_binary = str(self.current.get("binary", "unknown") or "unknown").lower()
        current_binary_conf = float(self.current.get("binary_confidence", 0.0) or 0.0)
        v8 = self._get_latest_v8_shadow()
        v8_binary = str(v8.get("binary", "unknown") or "unknown").lower()
        v8_conf = float(v8.get("binary_proba", 0.0) or 0.0)
        baseline_fresh = self._empty_baseline_is_fresh()
        operator_recent = self._empty_baseline_is_operator_recent()
        now_sec = time.time()
        legacy_result = self._get_legacy_bridge_window_result(t_start, t_end)
        if legacy_result is not None:
            legacy_feat, _, _ = legacy_result
            bl_amp_dev_max = float(legacy_feat.get("x_baseline_amp_dev_max", 999.0) or 999.0)
            bl_sc_var_dev_max = float(legacy_feat.get("x_baseline_sc_var_dev_max", 999.0) or 999.0)
        else:
            bl_amp_dev_max = 999.0
            bl_sc_var_dev_max = 999.0
        hold_active = self._empty_baseline_rescue_hold_until > now_sec
        if hold_active and not (
            motion_state == "NO_MOTION"
            and active_nodes >= 7
            and v8_binary == "empty"
            and v8_conf >= EMPTY_BASELINE_RESCUE_MIN_V8_CONF
        ):
            self._empty_baseline_rescue_hold_until = 0.0
            hold_active = False

        if hold_active:
            self.current["empty_rescue_guard"] = {
                "eligible": True,
                "applied": True,
                "consecutive": EMPTY_BASELINE_OPERATOR_CONSECUTIVE_WINDOWS,
                "required_consecutive": EMPTY_BASELINE_OPERATOR_CONSECUTIVE_WINDOWS,
                "v8_binary": v8_binary,
                "v8_confidence": round(v8_conf, 4),
                "primary_confidence": round(current_binary_conf, 4),
                "baseline_fresh": baseline_fresh,
                "operator_recent": operator_recent,
                "operator_sticky_hold": True,
                "baseline_amp_dev_max": round(bl_amp_dev_max, 4),
                "baseline_sc_var_dev_max": round(bl_sc_var_dev_max, 4),
            }
            self.current.update(
                {
                    "binary": "empty",
                    "binary_confidence": round(max(v8_conf, 0.99), 3),
                    "coarse": "empty",
                    "coarse_confidence": round(max(v8_conf, 0.99), 3),
                    "target_x": 0.0,
                    "target_y": 0.0,
                    "target_zone": "empty",
                    "coordinate_source": "fresh_empty_baseline_rescue",
                    "decision_model_backend": "v48_v8_fresh_empty_rescue",
                }
            )
            return

        strict_can_rescue = (
            current_binary == "occupied"
            and motion_state == "NO_MOTION"
            and active_nodes >= 7
            and baseline_fresh
            and v8_binary == "empty"
            and v8_conf >= EMPTY_BASELINE_RESCUE_MIN_V8_CONF
            and bl_amp_dev_max <= EMPTY_BASELINE_RESCUE_AMP_DEV_MAX
            and bl_sc_var_dev_max <= EMPTY_BASELINE_RESCUE_SC_VAR_DEV_MAX
        )
        operator_can_rescue = (
            operator_recent
            and current_binary == "occupied"
            and motion_state == "NO_MOTION"
            and active_nodes >= 7
            and baseline_fresh
            and v8_binary == "empty"
            and v8_conf >= EMPTY_BASELINE_RESCUE_MIN_V8_CONF
            and current_binary_conf <= EMPTY_BASELINE_OPERATOR_MAX_PRIMARY_CONF
        )
        can_rescue = strict_can_rescue or operator_can_rescue
        required_consecutive = (
            EMPTY_BASELINE_OPERATOR_CONSECUTIVE_WINDOWS
            if operator_can_rescue
            else EMPTY_BASELINE_RESCUE_CONSECUTIVE_WINDOWS
        )

        if not can_rescue:
            self._empty_baseline_rescue_consecutive = 0
            self.current["empty_rescue_guard"] = {
                "eligible": False,
                "applied": False,
                "consecutive": 0,
                "required_consecutive": required_consecutive,
                "v8_binary": v8_binary,
                "v8_confidence": round(v8_conf, 4),
                "primary_confidence": round(current_binary_conf, 4),
                "baseline_fresh": baseline_fresh,
                "operator_recent": operator_recent,
                "operator_sticky_hold": False,
                "baseline_amp_dev_max": round(bl_amp_dev_max, 4),
                "baseline_sc_var_dev_max": round(bl_sc_var_dev_max, 4),
            }
            return

        self._empty_baseline_rescue_consecutive += 1
        applied = self._empty_baseline_rescue_consecutive >= required_consecutive
        self.current["empty_rescue_guard"] = {
            "eligible": True,
            "applied": applied,
            "consecutive": self._empty_baseline_rescue_consecutive,
            "required_consecutive": required_consecutive,
            "v8_binary": v8_binary,
            "v8_confidence": round(v8_conf, 4),
            "primary_confidence": round(current_binary_conf, 4),
            "baseline_fresh": baseline_fresh,
            "operator_recent": operator_recent,
            "operator_sticky_hold": False,
            "baseline_amp_dev_max": round(bl_amp_dev_max, 4),
            "baseline_sc_var_dev_max": round(bl_sc_var_dev_max, 4),
        }
        if not applied:
            return

        if operator_recent:
            hold_until = now_sec + EMPTY_BASELINE_OPERATOR_STICKY_HOLD_SEC
            try:
                hold_until = max(
                    hold_until,
                    self._BASELINE_PATH.stat().st_mtime + EMPTY_BASELINE_OPERATOR_ARM_SEC,
                )
            except OSError:
                pass
            self._empty_baseline_rescue_hold_until = hold_until

        self.current.update(
            {
                "binary": "empty",
                "binary_confidence": round(max(v8_conf, 0.99), 3),
                "coarse": "empty",
                "coarse_confidence": round(max(v8_conf, 0.99), 3),
                "target_x": 0.0,
                "target_y": 0.0,
                "target_zone": "empty",
                "coordinate_source": "fresh_empty_baseline_rescue",
                "decision_model_backend": "v48_v8_fresh_empty_rescue",
            }
        )

    def _apply_outside_door_leakage_guard(
        self,
        *,
        active_nodes: int,
        motion_state: str,
    ) -> None:
        """Force empty on a very narrow, repeatedly observed outside-door leakage signature."""
        v29 = self._v29_cnn_shadow or {}
        v29_probs = v29.get("probabilities") or {}
        v29_zone = str(v29.get("zone", "") or "").lower()
        v29_door_proba = float(v29_probs.get("door", 0.0) or 0.0)

        v8 = self._get_latest_v8_shadow()
        v8_binary = str(v8.get("binary", "") or "").lower()
        v8_conf = float(v8.get("binary_proba", 0.0) or 0.0)

        current_binary = str(self.current.get("binary", "unknown") or "unknown").lower()
        current_coarse = str(self.current.get("coarse", "unknown") or "unknown").lower()
        current_zone = str(self.current.get("target_zone", "unknown") or "unknown").lower()
        target_x = self.current.get("target_x")
        target_y = self.current.get("target_y")

        try:
            target_x_f = float(target_x)
            target_y_f = float(target_y)
        except (TypeError, ValueError):
            target_x_f = None
            target_y_f = None

        eligible = bool(
            OUTSIDE_DOOR_LEAKAGE_GUARD_ENABLED
            and current_binary == "occupied"
            and current_coarse == "static"
            and motion_state == "NO_MOTION"
            and active_nodes >= 7
            and current_zone == "center"
            and target_x_f is not None
            and target_y_f is not None
            and target_x_f >= OUTSIDE_DOOR_LEAKAGE_MIN_TARGET_X
            and target_y_f <= OUTSIDE_DOOR_LEAKAGE_MAX_TARGET_Y
            and v29_zone == "door"
            and v29_door_proba >= OUTSIDE_DOOR_LEAKAGE_MIN_V29_DOOR_PROBA
            and v8_binary == "empty"
            and v8_conf >= OUTSIDE_DOOR_LEAKAGE_MIN_V8_CONF
        )

        if not eligible:
            self._outside_door_leakage_consecutive = 0
            self.current["outside_door_guard"] = {
                "enabled": OUTSIDE_DOOR_LEAKAGE_GUARD_ENABLED,
                "eligible": False,
                "applied": False,
                "consecutive": 0,
                "required_consecutive": OUTSIDE_DOOR_LEAKAGE_CONSECUTIVE_WINDOWS,
                "target_x": None if target_x_f is None else round(target_x_f, 3),
                "target_y": None if target_y_f is None else round(target_y_f, 3),
                "target_zone": current_zone,
                "v29_zone": v29_zone,
                "v29_door_proba": round(v29_door_proba, 4),
                "v8_binary": v8_binary,
                "v8_confidence": round(v8_conf, 4),
            }
            return

        self._outside_door_leakage_consecutive += 1
        would_apply = self._outside_door_leakage_consecutive >= OUTSIDE_DOOR_LEAKAGE_CONSECUTIVE_WINDOWS
        applied = would_apply and OUTSIDE_DOOR_LEAKAGE_GUARD_PROMOTE
        self.current["outside_door_guard"] = {
            "enabled": True,
            "eligible": True,
            "applied": applied,
            "would_apply": would_apply,
            "promote_enabled": OUTSIDE_DOOR_LEAKAGE_GUARD_PROMOTE,
            "consecutive": self._outside_door_leakage_consecutive,
            "required_consecutive": OUTSIDE_DOOR_LEAKAGE_CONSECUTIVE_WINDOWS,
            "target_x": round(target_x_f, 3),
            "target_y": round(target_y_f, 3),
            "target_zone": current_zone,
            "v29_zone": v29_zone,
            "v29_door_proba": round(v29_door_proba, 4),
            "v8_binary": v8_binary,
            "v8_confidence": round(v8_conf, 4),
        }
        if not would_apply:
            return

        if applied:
            self.current.update(
                {
                    "binary": "empty",
                    "binary_confidence": round(max(v8_conf, 0.99), 3),
                    "coarse": "empty",
                    "coarse_confidence": round(max(v8_conf, 0.99), 3),
                    "target_x": 0.0,
                    "target_y": 0.0,
                    "target_zone": "empty",
                    "coordinate_source": "outside_door_leakage_guard",
                    "decision_model_backend": "v48_outside_door_empty_guard",
                }
            )

    def _apply_v8_empty_priority_guard(
        self,
        *,
        active_nodes: int,
        motion_state: str,
    ) -> None:
        """Prefer empty over temporary door/center few-shot routing on static empty scenes."""
        v8 = self._get_latest_v8_shadow()
        current_binary = str(self.current.get("binary", "unknown") or "unknown").lower()
        current_zone = str(self.current.get("target_zone", "unknown") or "unknown").lower()
        current_binary_conf = float(self.current.get("binary_confidence", 0.0) or 0.0)
        v8_binary = str(v8.get("binary", "unknown") or "unknown").lower()
        v8_conf = float(v8.get("binary_proba", 0.0) or 0.0)
        candidate = self._door_center_candidate_shadow or {}
        fewshot = self._fewshot_adaptation_shadow or {}
        candidate_zone = str(candidate.get("stable_zone") or candidate.get("candidate_zone") or candidate.get("zone") or "")
        raw_candidate_zone = str(candidate.get("raw_candidate_zone") or "")
        proto_zone = str(candidate.get("prototype_zone") or "")
        temporal_zone = str(candidate.get("temporal_zone") or "")
        threshold_zone = str(candidate.get("threshold_zone") or "")
        fewshot_confidence = float(candidate.get("fewshot_confidence", 0.0) or 0.0)
        candidate_agreement = str(candidate.get("agreement", "") or "")
        fewshot_zone = str((fewshot.get("last_prediction") or {}).get("zone") or fewshot.get("zone") or "")
        _last_feat = getattr(self, "_last_feat_dict", None)
        truth_tvar_median = None
        if _last_feat is not None:
            _tn = ["node01", "node02", "node03", "node04", "node05", "node06", "node07"]
            _tvs = sorted(
                [
                    _last_feat.get(f"{n}_tvar", 0.0)
                    for n in _tn
                    if _last_feat.get(f"{n}_tvar", 0.0) > 0
                ]
            )
            if len(_tvs) >= 3:
                truth_tvar_median = float(_tvs[len(_tvs) // 2])
        truth_tvar_runtime = (
            self.current.get("truth_tvar")
            if isinstance(self.current.get("truth_tvar"), dict)
            else {}
        )
        truth_tvar_runtime_verdict = str(
            truth_tvar_runtime.get("truth_verdict", "") or ""
        ).lower()
        candidate_consensus_ready = (
            candidate_zone in {"center", "door_passage"}
            and (
                raw_candidate_zone == candidate_zone
                or fewshot_zone == candidate_zone
            )
        )
        center_consensus_ready = (
            candidate_zone == "center"
            and candidate_agreement
            in {
                "full",
                "prototype_override",
                "temporal_override",
                "fewshot_center_override",
            }
            and raw_candidate_zone == "center"
            and proto_zone == "center"
            and temporal_zone == "center"
            and threshold_zone == "center"
        )
        empty_rescue_diag = (
            self.current.get("empty_subregime_rescue")
            if isinstance(self.current.get("empty_subregime_rescue"), dict)
            else {}
        )
        rescue_predicted_class = str(
            empty_rescue_diag.get("predicted_class", "") or ""
        )
        rescue_empty_like_ratio = float(
            empty_rescue_diag.get("empty_like_ratio", 0.0) or 0.0
        )
        rescue_occupied_anchor_ratio = float(
            empty_rescue_diag.get("occupied_anchor_ratio", 0.0) or 0.0
        )
        rescue_center_like = bool(
            empty_rescue_diag.get("deep_center_like")
            or empty_rescue_diag.get("shallow_center_like")
        )
        occupied_anchor_empty_rescue_ready = bool(
            motion_state == "NO_MOTION"
            and center_consensus_ready
            and current_binary == "occupied"
            and current_zone in {"occupied", "center"}
            and v8_binary == "empty"
            and v8_conf >= 0.999
            and current_binary_conf <= 0.82
            and active_nodes >= 7
            and rescue_predicted_class == "occupied_anchor"
            and rescue_empty_like_ratio >= 0.25
            and rescue_occupied_anchor_ratio <= 0.75
            and rescue_center_like
        )
        static_empty_anchor_ready = bool(
            motion_state == "NO_MOTION"
            and center_consensus_ready
            and current_binary == "occupied"
            and current_zone in {"occupied", "center"}
            and v8_binary == "empty"
            and v8_conf >= 0.999
            and current_binary_conf <= 0.82
            and active_nodes >= 7
            and truth_tvar_median is not None
            and truth_tvar_median >= 4.0
            and fewshot_zone not in {"door", "door_passage"}
        )
        recent_motion_anchor = False
        recent_motion_windows = 0
        if self._recent_predictions:
            for item in self._recent_predictions[-24:]:
                if str(item.get("motion_state", "") or "").upper() == "MOTION_DETECTED":
                    recent_motion_windows += 1
            recent_motion_anchor = recent_motion_windows > 0
        v8_no_motion_empty_context = bool(
            motion_state == "NO_MOTION"
            and v8_binary == "empty"
            and v8_conf >= V8_EMPTY_PRIORITY_MIN_V8_CONF
            and active_nodes >= 7
        )
        hard_door_release_evidence = bool(
            candidate.get("door_gate_support")
            or candidate.get("raw_door_assist")
            or candidate.get("raw_door_hold")
            or candidate.get("current_fw3_door_assist")
            or candidate.get("current_fw3_low_tvar_door")
            or candidate.get("current_fw3_tvar_shape_door")
            or candidate.get("current_fw3_door_hold")
            or candidate.get("current_live_fw3_door")
            or candidate.get("current_live_fw3_door_hold")
        )
        soft_presence_anchor = bool(
            int(candidate.get("raw_door_votes") or 0) >= 4
            and int(candidate.get("current_fw3_door_votes") or 0) >= 5
            and float(candidate.get("door_tvar_mean", 0.0) or 0.0)
            >= float(candidate.get("center_tvar_mean", 0.0) or 0.0) + 0.4
            and truth_tvar_median is not None
            and truth_tvar_median >= 3.4
            and active_nodes >= 7
        )
        hard_door_release_evidence = bool(
            hard_door_release_evidence or soft_presence_anchor
        )
        no_motion_empty_fast_path = bool(
            v8_no_motion_empty_context
            and not recent_motion_anchor
            and not hard_door_release_evidence
        )
        strong_center_release_ready = bool(
            center_consensus_ready
            and v8_binary != "empty"
            and (
                not v8_no_motion_empty_context
                or recent_motion_anchor
            )
            and (
                (fewshot_zone == "center" and fewshot_confidence >= 0.9)
                or (
                    fewshot_zone == "door_passage"
                    and fewshot_confidence < 0.88
                )
            )
        )
        center_anchor_release_ready = bool(
            center_consensus_ready
            and current_binary == "occupied"
            and current_binary_conf >= 0.60
            and active_nodes >= 7
            and truth_tvar_median is not None
            and truth_tvar_median >= 3.0
            and truth_tvar_runtime_verdict != "empty"
            and (
                not v8_no_motion_empty_context
                or recent_motion_anchor
            )
            and not static_empty_anchor_ready
            and not occupied_anchor_empty_rescue_ready
        )
        low_tvar_empty_scene = bool(
            motion_state == "NO_MOTION"
            and truth_tvar_median is not None
            and truth_tvar_median < 4.0
        )
        live_door_release_blocked = bool(
            low_tvar_empty_scene
            and candidate_agreement in {
                "live_door_shadow",
                "current_live_fw3_door",
                "current_live_fw3_door_hold",
            }
        )
        truth_empty_rescue_ready = bool(
            motion_state == "NO_MOTION"
            and current_binary == "occupied"
            and current_binary_conf <= 0.80
            and active_nodes >= 7
            and low_tvar_empty_scene
            and not soft_presence_anchor
            and (
                (
                    candidate_zone == "center"
                    and center_consensus_ready
                )
                or (
                    candidate_zone == "door_passage"
                    and candidate_agreement in {
                        "live_door_shadow",
                        "current_live_fw3_door",
                        "current_live_fw3_door_hold",
                        "current_fw3_rssi_door",
                        "current_fw3_low_tvar_door",
                    }
                )
            )
        )
        strong_door_release_ready = (
            candidate_zone == "door_passage"
            and candidate_agreement
            in {
                "full",
                "prototype_override",
                "temporal_override",
                "fewshot_door_gate",
                "fewshot_runtime_override",
                "live_door_shadow",
                "door_raw_assist",
                "door_raw_hold",
                "current_fw3_rssi_door",
                "current_fw3_temporal_door",
                "current_fw3_door_assist",
                "current_fw3_low_tvar_door",
                "current_fw3_tvar_shape_door",
                "current_fw3_door_hold",
                "current_live_fw3_door",
                "current_live_fw3_door_hold",
            }
            and (
                (
                    fewshot_zone == "door_passage"
                    and fewshot_confidence >= 0.82
                )
                or candidate_agreement in {
                    "door_raw_assist",
                    "door_raw_hold",
                    "live_door_shadow",
                    "current_fw3_rssi_door",
                    "current_fw3_temporal_door",
                    "current_fw3_door_assist",
                    "current_fw3_low_tvar_door",
                    "current_fw3_tvar_shape_door",
                    "current_fw3_door_hold",
                    "current_live_fw3_door",
                    "current_live_fw3_door_hold",
                }
            )
            and (
                raw_candidate_zone == "door_passage"
                or current_zone in {"door", "door_passage"}
                or candidate_agreement in {
                    "live_door_shadow",
                    "current_fw3_rssi_door",
                    "current_fw3_temporal_door",
                    "current_fw3_door_assist",
                    "current_fw3_low_tvar_door",
                    "current_fw3_tvar_shape_door",
                    "current_fw3_door_hold",
                    "current_live_fw3_door",
                    "current_live_fw3_door_hold",
                }
            )
            and (
                v8_binary != "empty"
                or bool(candidate.get("raw_door_assist"))
                or bool(candidate.get("raw_door_hold"))
                or candidate_agreement in {
                    "live_door_shadow",
                    "door_raw_assist",
                    "door_raw_hold",
                    "current_fw3_rssi_door",
                    "current_fw3_temporal_door",
                    "current_fw3_door_assist",
                    "current_fw3_low_tvar_door",
                    "current_fw3_tvar_shape_door",
                    "current_fw3_door_hold",
                    "current_live_fw3_door",
                    "current_live_fw3_door_hold",
                }
            )
            and (
                not v8_no_motion_empty_context
                or recent_motion_anchor
                or hard_door_release_evidence
            )
            and not (
                v8_no_motion_empty_context
                and candidate_agreement == "live_door_shadow"
                and not hard_door_release_evidence
                and not recent_motion_anchor
            )
            and not live_door_release_blocked
        )
        required_release_consecutive = (
            1
            if (
                strong_center_release_ready
                or center_anchor_release_ready
                or strong_door_release_ready
            )
            else V8_EMPTY_PRIORITY_RELEASE_CONSECUTIVE_WINDOWS
        )
        generic_release_ready = bool(
            current_binary == "occupied"
            and current_binary_conf >= V8_EMPTY_PRIORITY_RELEASE_MIN_PRIMARY_CONF
            and candidate_consensus_ready
            and candidate_agreement
            in {
                "full",
                "prototype_override",
                "temporal_override",
                "fewshot_door_gate",
                "fewshot_runtime_override",
                "fewshot_center_override",
            }
            and v8_binary != "empty"
            and (
                not v8_no_motion_empty_context
                or recent_motion_anchor
                or hard_door_release_evidence
            )
        )
        release_ready = bool(
            active_nodes >= 7
            and (
                generic_release_ready
                or strong_center_release_ready
                or center_anchor_release_ready
                or strong_door_release_ready
            )
        )
        if release_ready:
            self._v8_empty_priority_release_consecutive += 1
        else:
            self._v8_empty_priority_release_consecutive = 0
        if (
            self._v8_empty_priority_release_consecutive
            >= required_release_consecutive
        ):
            self._v8_empty_priority_consecutive = 0
            self.current["v8_empty_priority_guard"] = {
                "enabled": V8_EMPTY_PRIORITY_GUARD_ENABLED,
                "eligible": False,
                "applied": False,
                "released": True,
                "release_reason": "occupied_spatial_evidence",
                "release_consecutive": self._v8_empty_priority_release_consecutive,
                "required_release_consecutive": required_release_consecutive,
                "v8_binary": v8_binary,
                "v8_confidence": round(v8_conf, 4),
                "primary_confidence": round(current_binary_conf, 4),
                "truth_tvar_median": (
                    round(truth_tvar_median, 3)
                    if truth_tvar_median is not None
                    else None
                ),
                "current_zone": current_zone,
                "candidate_zone": candidate_zone or None,
                "candidate_agreement": candidate_agreement or None,
                "fewshot_zone": fewshot_zone or None,
                "center_anchor_release_ready": center_anchor_release_ready,
                "static_empty_anchor_ready": static_empty_anchor_ready,
                "occupied_anchor_empty_rescue_ready": occupied_anchor_empty_rescue_ready,
                "truth_empty_rescue_ready": truth_empty_rescue_ready,
                "live_door_release_blocked": live_door_release_blocked,
                "low_tvar_empty_scene": low_tvar_empty_scene,
                "recent_motion_anchor": recent_motion_anchor,
                "recent_motion_windows": recent_motion_windows,
                "v8_no_motion_empty_context": v8_no_motion_empty_context,
                "hard_door_release_evidence": hard_door_release_evidence,
                "soft_presence_anchor": soft_presence_anchor,
                "no_motion_empty_fast_path": no_motion_empty_fast_path,
            }
            return
        eligible = bool(
            V8_EMPTY_PRIORITY_GUARD_ENABLED
            and current_binary == "occupied"
            and motion_state == "NO_MOTION"
            and active_nodes >= 7
            and not soft_presence_anchor
            and current_zone in {"center", "door", "door_passage"}
            and (
                (
                    v8_binary == "empty"
                    and v8_conf >= V8_EMPTY_PRIORITY_MIN_V8_CONF
                    and current_binary_conf <= V8_EMPTY_PRIORITY_MAX_PRIMARY_CONF
                    and (
                        candidate_zone in {"center", "door_passage"}
                        or current_zone in {"center", "door", "door_passage"}
                    )
                )
                or truth_empty_rescue_ready
            )
        )
        required_apply_consecutive = (
            1
            if (
                static_empty_anchor_ready
                or occupied_anchor_empty_rescue_ready
                or truth_empty_rescue_ready
                or no_motion_empty_fast_path
            )
            else V8_EMPTY_PRIORITY_CONSECUTIVE_WINDOWS
        )

        if not eligible:
            self._v8_empty_priority_consecutive = 0
            self.current["v8_empty_priority_guard"] = {
                "enabled": V8_EMPTY_PRIORITY_GUARD_ENABLED,
                "eligible": False,
                "applied": False,
                "released": False,
                "consecutive": 0,
                "required_consecutive": required_apply_consecutive,
                "release_consecutive": self._v8_empty_priority_release_consecutive,
                "required_release_consecutive": required_release_consecutive,
                "v8_binary": v8_binary,
                "v8_confidence": round(v8_conf, 4),
                "primary_confidence": round(current_binary_conf, 4),
                "truth_tvar_median": (
                    round(truth_tvar_median, 3)
                    if truth_tvar_median is not None
                    else None
                ),
                "current_zone": current_zone,
                "candidate_zone": candidate_zone or None,
                "candidate_agreement": candidate_agreement or None,
                "fewshot_zone": fewshot_zone or None,
                "center_anchor_release_ready": center_anchor_release_ready,
                "static_empty_anchor_ready": static_empty_anchor_ready,
                "occupied_anchor_empty_rescue_ready": occupied_anchor_empty_rescue_ready,
                "truth_empty_rescue_ready": truth_empty_rescue_ready,
                "live_door_release_blocked": live_door_release_blocked,
                "low_tvar_empty_scene": low_tvar_empty_scene,
                "recent_motion_anchor": recent_motion_anchor,
                "recent_motion_windows": recent_motion_windows,
                "v8_no_motion_empty_context": v8_no_motion_empty_context,
                "hard_door_release_evidence": hard_door_release_evidence,
                "soft_presence_anchor": soft_presence_anchor,
                "no_motion_empty_fast_path": no_motion_empty_fast_path,
            }
            return

        self._v8_empty_priority_consecutive += 1
        applied = self._v8_empty_priority_consecutive >= required_apply_consecutive
        self.current["v8_empty_priority_guard"] = {
            "enabled": V8_EMPTY_PRIORITY_GUARD_ENABLED,
            "eligible": True,
            "applied": applied,
            "released": False,
            "consecutive": self._v8_empty_priority_consecutive,
            "required_consecutive": required_apply_consecutive,
            "release_consecutive": self._v8_empty_priority_release_consecutive,
            "required_release_consecutive": required_release_consecutive,
            "v8_binary": v8_binary,
            "v8_confidence": round(v8_conf, 4),
            "primary_confidence": round(current_binary_conf, 4),
            "truth_tvar_median": (
                round(truth_tvar_median, 3)
                if truth_tvar_median is not None
                else None
            ),
            "current_zone": current_zone,
            "candidate_zone": candidate_zone or None,
            "candidate_agreement": candidate_agreement or None,
            "fewshot_zone": fewshot_zone or None,
            "center_anchor_release_ready": center_anchor_release_ready,
            "static_empty_anchor_ready": static_empty_anchor_ready,
            "occupied_anchor_empty_rescue_ready": occupied_anchor_empty_rescue_ready,
            "truth_empty_rescue_ready": truth_empty_rescue_ready,
            "recent_motion_anchor": recent_motion_anchor,
            "recent_motion_windows": recent_motion_windows,
            "v8_no_motion_empty_context": v8_no_motion_empty_context,
            "hard_door_release_evidence": hard_door_release_evidence,
            "soft_presence_anchor": soft_presence_anchor,
            "no_motion_empty_fast_path": no_motion_empty_fast_path,
        }
        if not applied:
            return

        # ── Truth-backed TVAR veto: do NOT override to empty if TVAR clearly
        # indicates occupied.  TVAR has zero overlap between empty/occupied in
        # truth-backed analysis (F1=1.0).  This prevents the V8 shadow from
        # forcing empty when people are actually present.
        if _last_feat is not None:
            if truth_tvar_median is not None:
                _tmed = truth_tvar_median
                if _tmed >= 4.0:
                    if (
                        not static_empty_anchor_ready
                        and not occupied_anchor_empty_rescue_ready
                        and not truth_empty_rescue_ready
                        and not no_motion_empty_fast_path
                    ):
                        logger.warning(
                            "V8 empty guard VETOED by truth-tvar: tvar_median=%.2f >= 4.0, "
                            "v8_binary=%s v8_conf=%.3f",
                            _tmed, v8_binary, v8_conf,
                        )
                        self.current["v8_empty_priority_guard"]["applied"] = False
                        self.current["v8_empty_priority_guard"]["truth_tvar_veto"] = True
                        self.current["v8_empty_priority_guard"]["truth_tvar_median"] = round(_tmed, 3)
                        return
                    self.current["v8_empty_priority_guard"]["truth_tvar_veto"] = False
                    self.current["v8_empty_priority_guard"]["truth_tvar_empty_anchor_override"] = True
                    self.current["v8_empty_priority_guard"]["truth_tvar_median"] = round(_tmed, 3)

        self.current.update(
            {
                "binary": "empty",
                "binary_confidence": round(max(v8_conf, 0.95 if truth_empty_rescue_ready else 0.99), 3),
                "coarse": "empty",
                "coarse_confidence": round(max(v8_conf, 0.95 if truth_empty_rescue_ready else 0.99), 3),
                "target_x": 0.0,
                "target_y": 0.0,
                "target_zone": "empty",
                "coordinate_source": "v8_empty_priority_guard",
                "decision_model_backend": "v48_v8_empty_priority_guard",
            }
        )

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
        _bundle_version = bundle.get("version") or path.stem
        _parent_dir = path.parent.name  # e.g. v54_twoperson_boost1
        # Prefer parent directory name as version when it carries meaningful info
        version = _parent_dir if (_parent_dir and _parent_dir != path.stem and not _parent_dir.startswith("train_runs")) else _bundle_version
        stat = path.stat()
        resolved_path = str(path.resolve())
        default_model = path.resolve() == MODEL_PATH.resolve()
        active_model = Path(self._active_model_path).resolve() == path.resolve()

        # Load analysis.json if it exists next to the model file
        _metrics = None
        _analysis_path = path.parent / "analysis.json"
        if _analysis_path.exists():
            try:
                with _analysis_path.open("r") as _fh:
                    _analysis = json.load(_fh)
                _bm = _analysis.get("binary_model") or {}
                _cm = _analysis.get("coordinate_model") or {}
                _metrics = {
                    "f1_macro": _bm.get("cv_macro_f1_rf"),
                    "empty_accuracy": _bm.get("empty_detection_accuracy"),
                    "n_windows": _analysis.get("total_windows"),
                    "n_recordings": (lambda r: len(r) if isinstance(r, list) else r)(_analysis.get("recordings_used")),
                    "mae_combined": _cm.get("cv_mae_combined"),
                    "mae_x": _cm.get("cv_mae_x"),
                    "mae_y": _cm.get("cv_mae_y"),
                    "generated_at": _analysis.get("generated_at"),
                }
            except Exception:
                pass

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
            "metrics": _metrics,
        }

    @staticmethod
    def _bundle_v48_window_sec(bundle: dict[str, Any]) -> float:
        config = bundle.get("v48_feature_config") or {}
        raw = config.get("window_sec", WINDOW_SEC)
        try:
            window_sec = float(raw)
        except (TypeError, ValueError):
            return float(WINDOW_SEC)
        return window_sec if window_sec > 0 else float(WINDOW_SEC)

    def _active_feature_window_sec(self) -> float:
        try:
            window_sec = float(self._feature_window_sec)
        except (TypeError, ValueError):
            window_sec = float(WINDOW_SEC)
        # Widen window to 10s at low PPS (<5) to accumulate enough packets
        # At 2 PPS, 3s window = ~6 pkts (too few); 10s window = ~20 pkts (workable)
        if window_sec < 10.0:
            window_sec = 10.0
        return window_sec if window_sec > 0 else float(WINDOW_SEC)

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

    def _sync_active_model_contract(self) -> None:
        active_path = Path(self._active_model_path) if self._active_model_path else MODEL_PATH
        try:
            resolved_path = active_path.resolve()
        except Exception:
            resolved_path = MODEL_PATH.resolve()
        active_model_id = self._active_model_id or resolved_path.name
        active_model_version = self._active_model_version or self.current.get("model_version") or resolved_path.stem
        active_model_kind = self._active_model_kind or self.current.get("model_kind") or "unknown"
        self.current["model_version"] = active_model_version
        self.current["model_id"] = active_model_id
        self.current["model_filename"] = active_model_id
        self.current["model_path"] = str(resolved_path)
        self.current["model_kind"] = active_model_kind
        self.current["model_default"] = resolved_path == MODEL_PATH.resolve()
        self.current["feature_window_sec"] = float(self._active_feature_window_sec())

    def _legacy_production_overrides_enabled(self) -> bool:
        active_model_id = self._active_model_id or MODEL_PATH.name
        return active_model_id != "v48_production.pkl"

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
                self._feature_window_sec = float(WINDOW_SEC)
                self._coarse_empty_boost = float((bundle.get("calibration") or {}).get("empty_boost", 0.0) or 0.0)
                cv_score = bundle.get("binary_balaccc", 0)
                self._base_binary_backend = "v25_primary"
                self._active_binary_backend = "v25_primary"
            else:
                # V21/V22 format
                self.feature_names = bundle["feature_names"]
                if version == "v48":
                    # FW4.0 retrain: RF (macro-F1=0.979) >> GB (0.946)
                    self.binary_model = bundle["binary_model"]
                    self._base_binary_backend = "v48_random_forest"
                    self._active_binary_backend = "v48_random_forest"
                else:
                    self.binary_model = bundle["binary_model"]
                    self._base_binary_backend = "v21_binary_model"
                    self._active_binary_backend = "v21_binary_model"
                self.coarse_model = bundle.get("coarse_model")
                self.coarse_labels = bundle.get("coarse_labels", {0: "static", 1: "motion"})
                # V54: lowered threshold from 0.5 to 0.25 — 2-person standing
                # produces proba(occ)~0.28-0.34, empty~0.10-0.20.
                # 3-window hysteresis guards against false positives.
                self._binary_threshold = bundle.get("threshold", 0.25)
                self._feature_window_sec = (
                    self._bundle_v48_window_sec(bundle)
                    if version == "v48"
                    else float(WINDOW_SEC)
                )
                self._coarse_empty_boost = float((bundle.get("calibration") or {}).get("empty_boost", 0.0) or 0.0)
                cv_score = bundle.get("binary_cv_score", 0)

            # ── V48 coordinate model extraction ─────────────────────
            self._v48_coord_x = bundle.get("coordinate_model_x")
            self._v48_coord_y = bundle.get("coordinate_model_y")
            self._v48_coord_scaler = bundle.get("coordinate_scaler")
            self._v48_coord_feature_names = bundle.get("coordinate_feature_names")
            self._v48_last_coord = None
            self._v48_err_count = 0
            if self._v48_coord_x is not None:
                _cmeta = bundle.get("coordinate_metadata") or {}
                logger.info("V48 coordinate model loaded: variant=%s, cv_euclid=%.3f",
                            _cmeta.get("variant", "?"), _cmeta.get("cv_euclidean", 0))

            # ── V49 zone3 classifier extraction ──────────────────────
            self._zone3_classifier = bundle.get("zone_classifier")
            self._zone3_labels = bundle.get("zone_labels")  # ['door','center','deep']
            self._zone3_feature_names = bundle.get("zone_feature_names")
            self._zone3_scaler = bundle.get("zone_scaler")
            self._zone3_last = None  # (zone, confidence) tuple
            self._zone3_err_count = 0
            if self._zone3_classifier is not None and self._zone3_feature_names is not None:
                logger.info("Zone3 classifier loaded: labels=%s, features=%d",
                            self._zone3_labels, len(self._zone3_feature_names))

            self._active_model_path = str(p.resolve())
            self._active_model_id = p.name
            self._active_model_version = version
            self._active_model_kind = kind
            logger.info(
                f"Model loaded: v={version}, "
                f"features={len(self.feature_names)}, "
                f"cv_score={cv_score:.3f}, "
                f"threshold={self._binary_threshold}, "
                f"window_sec={self._active_feature_window_sec()}"
            )
            self.current["model_version"] = version
            self.current["model_id"] = p.name
            self.current["model_filename"] = p.name
            self.current["model_path"] = str(p.resolve())
            self.current["model_kind"] = kind
            self.current["model_default"] = p.resolve() == MODEL_PATH.resolve()
            self.current["decision_model_version"] = version
            self.current["decision_model_id"] = p.name
            self.current["decision_model_backend"] = self._active_binary_backend
            self.current["binary_threshold"] = float(self._binary_threshold)
            self.current["feature_window_sec"] = float(self._active_feature_window_sec())
            self._load_shallow_coord_shadow_bundle()
            return True
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    def load_v57_model(self) -> bool:
        """Загружает v57 person count classifier для multi-person detection."""
        if not V57_ENABLED:
            logger.debug("V57 disabled, skipping model load")
            return False
        
        try:
            if not V57_PERSON_COUNT_MODEL_PATH.exists():
                logger.warning(f"V57 model not found: {V57_PERSON_COUNT_MODEL_PATH}")
                return False
            
            with open(V57_PERSON_COUNT_MODEL_PATH, 'rb') as f:
                _v57_bundle = pickle.load(f)
            # V58 stores model inside dict with key 'model'
            if isinstance(_v57_bundle, dict) and 'model' in _v57_bundle:
                self.v57_model = _v57_bundle['model']
                self._v57_classes = _v57_bundle.get('classes', {})
            else:
                self.v57_model = _v57_bundle
                self._v57_classes = {}

            logger.info(f"✓ V57/V58 person count classifier loaded (path: {V57_PERSON_COUNT_MODEL_PATH})")
            return True
        except Exception as e:
            logger.error(f"Failed to load V57 model: {e}")
            self.v57_model = None
            return False

    def predict_person_count(self, features: np.ndarray) -> dict[str, Any]:
        """
        Предсказывает количество людей (1 или 2) используя v57 classifier.
        
        Args:
            features: CSI feature vector - supports both 1D (903,) and 2D (1, 903)
        
        Returns:
            {
                'person_count': 1 or 2,
                'confidence': float (0-1),
                'source': 'v57_person_count_classifier',
                'class_probabilities': {'person_1': float, 'person_2': float}
            }
        """
        if self.v57_model is None:
            return {
                'person_count': None,
                'confidence': 0.0,
                'source': 'v57_not_loaded',
                'error': 'V57 model not loaded'
            }
        
        try:
            # Ensure 2D array (1, n_features)
            if features.ndim == 1:
                features = features.reshape(1, -1)
            elif features.ndim == 2 and features.shape[0] != 1:
                # Take first row if batch
                features = features[0:1]
            
            # Predict
            prediction = self.v57_model.predict(features)[0]
            proba = self.v57_model.predict_proba(features)[0]
            
            return {
                'person_count': int(prediction),
                'confidence': float(max(proba)),
                'source': 'v57_person_count_classifier',
                'class_probabilities': {
                    'empty': float(proba[0]) if len(proba) > 0 else 0.0,
                    'single': float(proba[1]) if len(proba) > 1 else 0.0,
                    'multi': float(proba[2]) if len(proba) > 2 else 0.0,
                }
            }
        except Exception as e:
            logger.error(f"V57 prediction failed: {e}")
            return {
                'person_count': None,
                'confidence': 0.0,
                'source': 'v57_prediction_error',
                'error': str(e)
            }

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
                    "csv_listener_running": self._csv_transport is not None,
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
            "csv_listener_running": self._csv_transport is not None,
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
            # Track B is a shadow-only forensic surface. On Python 3.14+
            # PyTorch emits a deprecation warning for torch.jit.load; suppress
            # that warning locally until the artifact format is migrated.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"`torch\.jit\.load` is not supported in Python 3\.14\+ and may break\.",
                    category=DeprecationWarning,
                )
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
        """Load V43/V45/V46 binary model for shadow inference."""
        if self._v43_loaded:
            return True
        if not V43_SHADOW_MODEL_PATH.exists():
            logger.warning("V43 shadow model not found: %s", V43_SHADOW_MODEL_PATH)
            return False
        try:
            with V43_SHADOW_MODEL_PATH.open("rb") as fh:
                bundle = pickle.load(fh)

            version = bundle.get("version", "v43")

            # V46+: PPS-invariant model with scaler + feature_names
            if bundle.get("pps_invariant"):
                self._v43_binary_model = bundle["binary_model"]
                self._v43_scaler = bundle.get("scaler")
                self._v43_window_features = bundle.get("feature_names", [])
                self._v43_pps_invariant = True
                self._v43_class_names = ["empty", "occupied"]
            else:
                # Legacy V45/V44/V43 path
                self._v43_coarse_model = bundle.get("coarse_model")
                self._v43_binary_model = bundle.get("binary_model")
                self._v43_window_features = bundle.get("window_feature_names", [])
                self._v43_class_names = bundle.get("coarse_labels", ["EMPTY", "MOTION", "STATIC"])
                self._v43_pps_invariant = False
                self._v43_scaler = None

            self._v43_seq_len = bundle.get("seq_len", V43_SHADOW_SEQ_LEN)
            self._v43_loaded = True
            logger.info(
                "V43 shadow loaded: version=%s, pps_inv=%s, features=%d, seq_len=%d, classes=%s",
                version, self._v43_pps_invariant,
                len(self._v43_window_features), self._v43_seq_len,
                self._v43_class_names,
            )
            # Ensure log directory exists
            V43_SHADOW_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error("V43 shadow load failed: %s", e)
            return False

    @staticmethod
    def _compute_v46_features(feat_dict: dict) -> dict:
        """Compute V46 PPS-invariant features from raw feat_dict at runtime."""
        _NODES = ["node01","node02","node03","node04","node05","node06","node07"]
        out = {}
        # Normalized amp, rssi, motion
        for n in _NODES:
            out[f"{n}_amp_norm"] = float(feat_dict.get(f"csi_{n}_amp_norm", 0) or 0)
            out[f"{n}_rssi_norm"] = float(feat_dict.get(f"csi_{n}_rssi_norm", 0) or 0)
            out[f"{n}_motion_norm"] = float(feat_dict.get(f"csi_{n}_motion_norm", 0) or 0)
        # Pairwise amplitude ratios
        amp_means = {}
        for n in _NODES:
            amp_means[n] = float(feat_dict.get(f"csi_{n}_amp_mean", 0) or 0)
        for i, n1 in enumerate(_NODES):
            for n2 in _NODES[i+1:]:
                d = amp_means[n2] + 1e-10
                out[f"ratio_{n1}_{n2}"] = amp_means[n1] / d
        # Cross-node stats
        amp_norms = [out[f"{n}_amp_norm"] for n in _NODES]
        out["amp_norm_mean"] = float(np.mean(amp_norms))
        out["amp_norm_std"] = float(np.std(amp_norms))
        out["amp_norm_range"] = float(max(amp_norms) - min(amp_norms))
        rssi_norms = [out[f"{n}_rssi_norm"] for n in _NODES]
        out["rssi_norm_mean"] = float(np.mean(rssi_norms))
        out["rssi_norm_std"] = float(np.std(rssi_norms))
        out["rssi_norm_range"] = float(max(rssi_norms) - min(rssi_norms))
        # Asymmetry
        left_amp = float(np.mean([out.get("node01_amp_norm",0), out.get("node03_amp_norm",0)]))
        right_amp = float(np.mean([out.get("node02_amp_norm",0), out.get("node04_amp_norm",0)]))
        out["lr_asymmetry"] = left_amp - right_amp
        near_amp = float(np.mean([out.get("node01_amp_norm",0), out.get("node02_amp_norm",0)]))
        far_amp = float(np.mean([out.get("node03_amp_norm",0), out.get("node04_amp_norm",0)]))
        out["nf_asymmetry"] = near_amp - far_amp
        # Variance concentration
        try:
            sc_vars = [float(feat_dict.get(f"csi_{n}_sc_var", 0) or 0) for n in _NODES]
        except (ValueError, TypeError):
            sc_vars = [0.0] * 7
        total_var = sum(sc_vars) + 1e-10
        for i, n in enumerate(_NODES):
            out[f"{n}_var_conc"] = sc_vars[i] / total_var
        # Delta norm
        for n in _NODES:
            out[f"{n}_delta_norm"] = float(feat_dict.get(f"csi_{n}_delta_norm",
                                    feat_dict.get(f"csi_{n}_delta", 0)) or 0)
        return out

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

        # V46: PPS-invariant features computed at runtime
        # V45: raw feat_dict
        # Legacy V44: augmented features
        if getattr(self, "_v43_pps_invariant", False):
            # V46: compute PPS-invariant features
            source = self._compute_v46_features(feat_dict)
        elif self._v43_binary_model is not None:
            source = feat_dict
        else:
            source = self._add_v8_f2_features(feat_dict)
            source = self._add_v23_guard_features(source)
            source = self._add_v21d_zone_features(source)

        # Extract window features in correct order
        window_feats = [source.get(f, 0) for f in self._v43_window_features]
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

            # V46: apply scaler
            if getattr(self, "_v43_scaler", None) is not None:
                X = self._v43_scaler.transform(X)

            t0 = time.perf_counter()

            # V45+/V46: binary_model direct (no coarse_model needed)
            if self._v43_binary_model is not None:
                bin_proba = self._v43_binary_model.predict_proba(X)[0]
                bin_classes = list(self._v43_binary_model.classes_)
                bin_idx = int(np.argmax(bin_proba))
                bin_pred_raw = bin_classes[bin_idx]
                # Classes can be [0,1] or ["EMPTY","OCCUPIED"]
                # 0/"EMPTY" = empty, 1/"OCCUPIED" = occupied
                is_empty = (bin_pred_raw in (0, "EMPTY", "0"))
                # Find empty class index for probability
                empty_candidates = [i for i, c in enumerate(bin_classes) if c in (0, "EMPTY", "0")]
                empty_idx_b = empty_candidates[0] if empty_candidates else 0
                empty_proba = float(bin_proba[empty_idx_b])
                v43_binary = "empty" if is_empty else "occupied"
                v43_binary_conf = empty_proba if v43_binary == "empty" else 1.0 - empty_proba
                coarse_pred = "EMPTY" if v43_binary == "empty" else "STATIC"
                coarse_proba = bin_proba
                coarse_classes = bin_classes
            elif self._v43_coarse_model is not None:
                # Legacy V44 path: coarse model → binary
                coarse_proba = self._v43_coarse_model.predict_proba(X)[0]
                coarse_classes = list(self._v43_class_names)
                coarse_idx = int(np.argmax(coarse_proba))
                coarse_pred = str(coarse_classes[coarse_idx])
                empty_idx = coarse_classes.index("EMPTY") if "EMPTY" in coarse_classes else 0
                empty_proba = float(coarse_proba[empty_idx])
                v43_binary = "empty" if coarse_pred == "EMPTY" else "occupied"
                v43_binary_conf = empty_proba if v43_binary == "empty" else 1.0 - empty_proba
            else:
                return None

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

    def _load_offline_regime_shadow(self) -> bool:
        """Load the offline regime bundle for runtime shadow inference."""
        if self._offline_regime_loaded:
            return True
        if not OFFLINE_REGIME_SHADOW_ENABLED:
            return False
        if not OFFLINE_REGIME_BUNDLE_PATH.exists():
            logger.info("Offline regime shadow bundle not found: %s", OFFLINE_REGIME_BUNDLE_PATH)
            return False

        try:
            with OFFLINE_REGIME_BUNDLE_PATH.open("rb") as fh:
                bundle = pickle.load(fh)

            feature_cols = list(bundle.get("feature_cols") or [])
            three_class_model = bundle.get("three_class_model")
            empty_vs_occupied_model = bundle.get("empty_vs_occupied_model")
            single_vs_multi_model = bundle.get("single_vs_multi_model")
            if not feature_cols:
                raise RuntimeError("offline regime bundle missing feature_cols")
            if three_class_model is None or empty_vs_occupied_model is None or single_vs_multi_model is None:
                raise RuntimeError("offline regime bundle missing one or more models")

            self._offline_regime_bundle = bundle
            self._offline_regime_feature_cols = feature_cols
            self._offline_regime_three_class_model = three_class_model
            self._offline_regime_empty_vs_occupied_model = empty_vs_occupied_model
            self._offline_regime_single_vs_multi_model = single_vs_multi_model
            self._offline_regime_analysis_path = None
            self._offline_regime_verdict = {}

            analysis_path_value = bundle.get("analysis_path")
            if analysis_path_value:
                analysis_path = Path(str(analysis_path_value))
                self._offline_regime_analysis_path = analysis_path
                if analysis_path.exists():
                    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
                    self._offline_regime_verdict = dict(analysis.get("verdict") or {})

            self._offline_regime_loaded = True
            logger.info(
                "Offline regime shadow loaded: %s (%d features)",
                OFFLINE_REGIME_CANDIDATE_NAME,
                len(self._offline_regime_feature_cols),
            )
            return True
        except Exception as e:
            logger.error("Failed to load offline regime shadow: %s", e)
            self._offline_regime_bundle = None
            self._offline_regime_feature_cols = []
            self._offline_regime_three_class_model = None
            self._offline_regime_empty_vs_occupied_model = None
            self._offline_regime_single_vs_multi_model = None
            self._offline_regime_analysis_path = None
            self._offline_regime_verdict = {}
            self._offline_regime_loaded = False
            return False

    @staticmethod
    def _predict_shadow_classifier(model: Any, X: np.ndarray) -> tuple[str, float, dict[str, float]]:
        """Predict class/confidence/probability map for a sklearn-like classifier."""
        proba = model.predict_proba(X)[0]
        classes = list(getattr(model, "classes_", []))
        if not classes and hasattr(model, "named_steps"):
            try:
                last_step = list(model.named_steps.values())[-1]
                classes = list(getattr(last_step, "classes_", []))
            except Exception:
                classes = []

        pred_idx = int(np.argmax(proba))
        pred_raw = classes[pred_idx] if classes and pred_idx < len(classes) else model.predict(X)[0]
        probabilities = {
            str(classes[i]) if classes and i < len(classes) else str(i): round(float(proba[i]), 4)
            for i in range(len(proba))
        }
        return str(pred_raw), float(proba[pred_idx]), probabilities

    def _shadow_predict_offline_regime(
        self,
        t_start: float,
        t_end: float,
        window_sec: float,
        prod_binary: str,
        prod_coarse: str,
    ) -> dict | None:
        """Run the offline regime bundle on the legacy bridge feature surface."""
        if not self._offline_regime_loaded:
            if not self._load_offline_regime_shadow():
                return None

        legacy_result = self._get_legacy_bridge_window_result(t_start, t_end)
        if legacy_result is None:
            return None

        feat_shadow, active_nodes, packet_count = legacy_result
        source = dict(feat_shadow)
        source.update(
            {
                "t_start": float(t_start),
                "t_end": float(t_end),
                "window_sec": float(window_sec),
                "nodes_active": int(active_nodes),
                "packet_count": int(packet_count),
            }
        )
        X = np.array(
            [[float(source.get(feature_name, 0.0) or 0.0) for feature_name in self._offline_regime_feature_cols]],
            dtype=np.float32,
        )
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        try:
            eo_label, eo_conf, eo_probs = self._predict_shadow_classifier(
                self._offline_regime_empty_vs_occupied_model,
                X,
            )
            three_label, three_conf, three_probs = self._predict_shadow_classifier(
                self._offline_regime_three_class_model,
                X,
            )

            sm_block: dict[str, Any] = {
                "status": "skipped_empty_scene",
                "train_ready": bool(self._offline_regime_verdict.get("single_vs_multi_train_ready", False)),
                "reason": "empty_vs_occupied predicted empty",
                "recommended_use": "diagnostic_only",
            }
            if eo_label == "occupied":
                sm_label, sm_conf, sm_probs = self._predict_shadow_classifier(
                    self._offline_regime_single_vs_multi_model,
                    X,
                )
                sm_block = {
                    "status": "shadow_live",
                    "predicted_class": sm_label,
                    "confidence": round(sm_conf, 4),
                    "probabilities": sm_probs,
                    "train_ready": bool(self._offline_regime_verdict.get("single_vs_multi_train_ready", False)),
                    "reason": self._offline_regime_verdict.get("single_vs_multi_reason", ""),
                    "recommended_use": "diagnostic_only",
                }

            shadow = {
                "t": round(float(t_end), 2),
                "track": OFFLINE_REGIME_CANDIDATE_NAME,
                "status": "shadow_live",
                "feature_surface": "legacy_bridge_window_features",
                "window_sec": round(float(window_sec), 3),
                "nodes_active": int(active_nodes),
                "packet_count": int(packet_count),
                "runtime_binary": prod_binary,
                "runtime_coarse": prod_coarse,
                "verdict": dict(self._offline_regime_verdict),
                "empty_vs_occupied": {
                    "predicted_class": eo_label,
                    "confidence": round(eo_conf, 4),
                    "probabilities": eo_probs,
                    "agree_binary": eo_label == prod_binary,
                    "train_ready": bool(self._offline_regime_verdict.get("empty_vs_occupied_train_ready", False)),
                    "recommended_use": "production_candidate",
                },
                "three_class": {
                    "predicted_class": three_label,
                    "confidence": round(three_conf, 4),
                    "probabilities": three_probs,
                    "agree_binary": ("empty" if three_label == "empty" else "occupied") == prod_binary,
                    "train_ready": bool(self._offline_regime_verdict.get("three_class_train_ready", False)),
                    "reason": self._offline_regime_verdict.get("three_class_reason", ""),
                    "recommended_use": "diagnostic_only",
                },
                "single_vs_multi": sm_block,
            }
            self._offline_regime_shadow = shadow
            self._offline_regime_history.append(shadow)
            if len(self._offline_regime_history) > 60:
                self._offline_regime_history = self._offline_regime_history[-60:]

            try:
                OFFLINE_REGIME_SHADOW_TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
                with OFFLINE_REGIME_SHADOW_TELEMETRY_PATH.open("a", encoding="utf-8") as tf:
                    tf.write(json.dumps({"ts": time.time(), **shadow}) + "\n")
            except Exception:
                pass

            logger.debug(
                "OFFLINE REGIME SHADOW: eo=%s(%.3f) three=%s(%.3f) sm=%s agree_bin=%s",
                eo_label,
                eo_conf,
                three_label,
                three_conf,
                sm_block.get("predicted_class", sm_block.get("status")),
                eo_label == prod_binary,
            )
            return shadow
        except Exception as e:
            logger.error("Offline regime shadow inference failed: %s", e)
            return None

    def _load_empty_subregime_shadow(self) -> bool:
        """Load the shadow-only empty-subregime discriminator."""
        if self._empty_subregime_loaded:
            return True
        if not EMPTY_SUBREGIME_SHADOW_ENABLED:
            return False
        if not EMPTY_SUBREGIME_BUNDLE_PATH.exists():
            logger.info("Empty subregime shadow bundle not found: %s", EMPTY_SUBREGIME_BUNDLE_PATH)
            return False

        try:
            with EMPTY_SUBREGIME_BUNDLE_PATH.open("rb") as fh:
                bundle = pickle.load(fh)

            feature_names = list(bundle.get("feature_names") or [])
            z_mu = bundle.get("z_mu")
            z_sigma = bundle.get("z_sigma")
            class_centroids = bundle.get("class_centroids") or {}
            ref_matrix = bundle.get("reference_matrix_z")
            ref_labels = list(bundle.get("reference_labels") or [])
            ref_recordings = list(bundle.get("reference_recordings") or [])
            if not feature_names:
                raise RuntimeError("empty subregime bundle missing feature_names")
            if z_mu is None or z_sigma is None:
                raise RuntimeError("empty subregime bundle missing z-scaler")
            if not class_centroids:
                raise RuntimeError("empty subregime bundle missing class_centroids")
            if ref_matrix is None or not ref_labels:
                raise RuntimeError("empty subregime bundle missing reference_matrix_z or reference_labels")

            self._empty_subregime_bundle = bundle
            self._empty_subregime_feature_names = feature_names
            self._empty_subregime_mu = np.asarray(z_mu, dtype=np.float32)
            self._empty_subregime_sigma = np.asarray(z_sigma, dtype=np.float32)
            self._empty_subregime_centroids = {
                str(label): np.asarray(vec, dtype=np.float32)
                for label, vec in class_centroids.items()
            }
            self._empty_subregime_ref_matrix = np.asarray(ref_matrix, dtype=np.float32)
            self._empty_subregime_ref_labels = ref_labels
            self._empty_subregime_ref_recordings = ref_recordings
            self._empty_subregime_top_k = int(bundle.get("top_k", 15) or 15)
            self._empty_subregime_analysis_path = None
            self._empty_subregime_verdict = {
                "recommended_use": str(bundle.get("recommended_use") or "shadow_only"),
                "production_override_ready": bool(bundle.get("production_override_ready", False)),
                "class_counts": dict(bundle.get("class_counts") or {}),
            }
            analysis_path_value = bundle.get("analysis_path")
            if analysis_path_value:
                analysis_path = Path(str(analysis_path_value))
                self._empty_subregime_analysis_path = analysis_path
                if analysis_path.exists():
                    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
                    self._empty_subregime_verdict.update(dict(analysis.get("verdict") or {}))

            self._empty_subregime_loaded = True
            logger.info(
                "Empty subregime shadow loaded: %s (%d features, k=%d)",
                EMPTY_SUBREGIME_CANDIDATE_NAME,
                len(self._empty_subregime_feature_names),
                self._empty_subregime_top_k,
            )
            return True
        except Exception as e:
            logger.error("Failed to load empty subregime shadow: %s", e)
            self._empty_subregime_bundle = None
            self._empty_subregime_feature_names = []
            self._empty_subregime_mu = None
            self._empty_subregime_sigma = None
            self._empty_subregime_centroids = {}
            self._empty_subregime_ref_matrix = None
            self._empty_subregime_ref_labels = []
            self._empty_subregime_ref_recordings = []
            self._empty_subregime_top_k = 15
            self._empty_subregime_analysis_path = None
            self._empty_subregime_verdict = {}
            self._empty_subregime_loaded = False
            return False

    def _shadow_predict_empty_subregime(
        self,
        feat_dict: dict[str, Any],
        w_end: float,
        prod_binary: str,
        prod_binary_conf: float,
    ) -> dict | None:
        """Run shadow-only empty-subregime discriminator on V48 features."""
        if not self._empty_subregime_loaded:
            if not self._load_empty_subregime_shadow():
                return None

        try:
            X = np.array(
                [[float(feat_dict.get(name, 0.0) or 0.0) for name in self._empty_subregime_feature_names]],
                dtype=np.float32,
            )
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            z = (X[0] - self._empty_subregime_mu) / self._empty_subregime_sigma

            centroid_distances = {
                label: float(np.linalg.norm(z - centroid))
                for label, centroid in self._empty_subregime_centroids.items()
            }
            ordered_centroids = sorted(centroid_distances.items(), key=lambda item: item[1])
            centroid_pred = ordered_centroids[0][0]
            if len(ordered_centroids) >= 2:
                d1 = ordered_centroids[0][1]
                d2 = ordered_centroids[1][1]
                centroid_margin = float(max(0.0, min(0.999, (d2 - d1) / (d2 + 1e-6))))
            else:
                centroid_margin = 0.0

            ref_distances = np.linalg.norm(self._empty_subregime_ref_matrix - z, axis=1)
            top_k = min(self._empty_subregime_top_k, len(ref_distances))
            nn_idx = np.argsort(ref_distances)[:top_k]
            nn_labels = [self._empty_subregime_ref_labels[i] for i in nn_idx]
            nn_recordings = [self._empty_subregime_ref_recordings[i] for i in nn_idx]
            label_counts = Counter(nn_labels)
            recording_counts = Counter(nn_recordings)
            knn_pred, knn_votes = label_counts.most_common(1)[0]
            knn_conf = float(knn_votes / max(top_k, 1))

            canonical_empty_ratio = label_counts.get("canonical_empty", 0) / max(top_k, 1)
            diag_empty_ratio = label_counts.get("diag_empty", 0) / max(top_k, 1)
            empty_like_ratio = (label_counts.get("canonical_empty", 0) + label_counts.get("diag_empty", 0)) / max(top_k, 1)
            occupied_anchor_ratio = label_counts.get("occupied_anchor", 0) / max(top_k, 1)
            predicted_class = knn_pred if knn_pred == centroid_pred else centroid_pred

            recommended_action = "observe"
            if prod_binary == "occupied" and predicted_class in {"canonical_empty", "diag_empty"} and empty_like_ratio >= 0.6:
                recommended_action = "consider_empty_rescue"
            elif prod_binary == "empty" and predicted_class == "occupied_anchor" and occupied_anchor_ratio >= 0.6:
                recommended_action = "possible_false_empty"

            shadow = {
                "t": round(float(w_end), 2),
                "track": EMPTY_SUBREGIME_CANDIDATE_NAME,
                "status": "shadow_live",
                "feature_surface": "v48_primary_features",
                "runtime_binary": prod_binary,
                "runtime_binary_conf": round(float(prod_binary_conf), 4),
                "predicted_class": predicted_class,
                "knn_predicted_class": knn_pred,
                "knn_confidence": round(knn_conf, 4),
                "centroid_predicted_class": centroid_pred,
                "centroid_margin": round(centroid_margin, 4),
                "centroid_distances": {key: round(val, 4) for key, val in ordered_centroids},
                "top_k": int(top_k),
                "neighbor_label_counts": dict(label_counts),
                "neighbor_recording_counts": dict(recording_counts),
                "empty_like_ratio": round(float(empty_like_ratio), 4),
                "canonical_empty_ratio": round(float(canonical_empty_ratio), 4),
                "diag_empty_ratio": round(float(diag_empty_ratio), 4),
                "occupied_anchor_ratio": round(float(occupied_anchor_ratio), 4),
                "recommended_action": recommended_action,
                "analysis_path": str(self._empty_subregime_analysis_path) if self._empty_subregime_analysis_path else None,
                "verdict": dict(self._empty_subregime_verdict),
            }
            self._empty_subregime_shadow = shadow
            self._empty_subregime_history.append(shadow)
            if len(self._empty_subregime_history) > 60:
                self._empty_subregime_history = self._empty_subregime_history[-60:]

            try:
                EMPTY_SUBREGIME_SHADOW_TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
                with EMPTY_SUBREGIME_SHADOW_TELEMETRY_PATH.open("a", encoding="utf-8") as tf:
                    tf.write(json.dumps({"ts": time.time(), **shadow}) + "\n")
            except Exception:
                pass

            logger.debug(
                "EMPTY SUBREGIME SHADOW: pred=%s empty_like=%.3f diag=%.3f runtime=%s",
                predicted_class,
                empty_like_ratio,
                diag_empty_ratio,
                prod_binary,
            )
            return shadow
        except Exception as e:
            logger.warning("Empty subregime shadow predict error: %s", e)
            return None

    def _load_deep_right_shadow(self) -> bool:
        """Load the deep-right / marker7 shadow classifier bundle."""
        if self._deep_right_shadow_loaded:
            return True
        if not DEEP_RIGHT_SHADOW_ENABLED:
            return False
        if not DEEP_RIGHT_SHADOW_BUNDLE_PATH.exists():
            logger.info("Deep-right shadow bundle not found: %s", DEEP_RIGHT_SHADOW_BUNDLE_PATH)
            return False

        try:
            with DEEP_RIGHT_SHADOW_BUNDLE_PATH.open("rb") as fh:
                bundle = pickle.load(fh)

            feature_names = list(bundle.get("feature_names") or [])
            classifier = bundle.get("classifier") or bundle.get("model")
            scaler = bundle.get("scaler")
            if not feature_names or classifier is None:
                raise RuntimeError("deep-right shadow bundle missing feature_names/classifier")

            self._deep_right_shadow_bundle = bundle
            self._deep_right_shadow_feature_names = feature_names
            self._deep_right_shadow_scaler = scaler
            self._deep_right_shadow_model = classifier
            self._deep_right_shadow_analysis_path = None
            self._deep_right_shadow_verdict = {
                "recommended_use": str(bundle.get("recommended_use") or "shadow_only"),
                "production_override_ready": bool(bundle.get("production_override_ready", False)),
            }
            self._deep_right_shadow_trigger_threshold = float(
                bundle.get("decision_threshold", bundle.get("threshold", bundle.get("trigger_threshold", 0.6))) or 0.6
            )
            self._deep_right_shadow_positive_label = str(bundle.get("positive_label") or self._deep_right_shadow_positive_label)
            self._deep_right_shadow_positive_alias = str(bundle.get("positive_alias") or self._deep_right_shadow_positive_alias)
            self._deep_right_shadow_negative_alias = str(bundle.get("negative_alias") or self._deep_right_shadow_negative_alias)

            analysis_path_value = bundle.get("analysis_path")
            if analysis_path_value:
                analysis_path = Path(str(analysis_path_value))
                self._deep_right_shadow_analysis_path = analysis_path
                if analysis_path.exists():
                    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
                    self._deep_right_shadow_verdict.update(dict(analysis.get("verdict") or {}))

            self._deep_right_shadow_loaded = True
            logger.info(
                "Deep-right shadow loaded: %s (%d features, trigger=%.2f)",
                DEEP_RIGHT_SHADOW_CANDIDATE_NAME,
                len(self._deep_right_shadow_feature_names),
                self._deep_right_shadow_trigger_threshold,
            )
            return True
        except Exception as e:
            logger.error("Failed to load deep-right shadow: %s", e)
            self._deep_right_shadow_bundle = None
            self._deep_right_shadow_feature_names = []
            self._deep_right_shadow_scaler = None
            self._deep_right_shadow_model = None
            self._deep_right_shadow_analysis_path = None
            self._deep_right_shadow_verdict = {}
            self._deep_right_shadow_trigger_threshold = 0.6
            self._deep_right_shadow_positive_label = "marker7"
            self._deep_right_shadow_positive_alias = "deep_right"
            self._deep_right_shadow_negative_alias = "not_deep_right"
            self._deep_right_shadow_loaded = False
            return False

    def _shadow_predict_deep_right(
        self,
        feat_dict: dict[str, Any],
        w_end: float,
        prod_binary: str,
        prod_binary_conf: float,
        prod_zone: str,
        prod_x: float,
        prod_y: float,
    ) -> dict | None:
        """Run shadow-only deep-right / marker7 discriminator on V48 features."""
        if not self._deep_right_shadow_loaded:
            if not self._load_deep_right_shadow():
                return None

        try:
            X = np.array(
                [[float(feat_dict.get(name, 0.0) or 0.0) for name in self._deep_right_shadow_feature_names]],
                dtype=np.float32,
            )
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
            X_eval = self._deep_right_shadow_scaler.transform(X) if self._deep_right_shadow_scaler is not None else X
            pred_label, pred_conf, probs = self._predict_shadow_classifier(self._deep_right_shadow_model, X_eval)
            positive_prob_keys = [
                self._deep_right_shadow_positive_label,
                self._deep_right_shadow_positive_alias,
                "deep_right_marker7",
                "deep_right",
                "marker7",
                "1",
                "true",
                "True",
            ]
            deep_right_prob = 0.0
            for key in positive_prob_keys:
                if key in probs:
                    deep_right_prob = float(probs[key] or 0.0)
                    break
            if not deep_right_prob and "0" in probs and "1" in probs:
                deep_right_prob = float(probs.get("1", 0.0) or 0.0)

            predicted_is_positive = str(pred_label) in {k for k in positive_prob_keys} or deep_right_prob >= 0.5
            predicted_class = self._deep_right_shadow_positive_alias if predicted_is_positive else self._deep_right_shadow_negative_alias

            recommended_action = "observe"
            if (
                prod_binary == "occupied"
                and predicted_is_positive
                and deep_right_prob >= self._deep_right_shadow_trigger_threshold
                and prod_zone in {"center", "door", "door_passage"}
            ):
                recommended_action = "consider_deep_right_guidance"

            shadow = {
                "t": round(float(w_end), 2),
                "track": DEEP_RIGHT_SHADOW_CANDIDATE_NAME,
                "status": "shadow_live",
                "feature_surface": "v48_primary_features",
                "runtime_binary": prod_binary,
                "runtime_binary_conf": round(float(prod_binary_conf), 4),
                "runtime_target_zone": prod_zone,
                "runtime_target_x": round(float(prod_x), 3),
                "runtime_target_y": round(float(prod_y), 3),
                "raw_predicted_class": str(pred_label),
                "predicted_class": predicted_class,
                "confidence": round(float(pred_conf), 4),
                "probabilities": probs,
                "deep_right_probability": round(deep_right_prob, 4),
                "trigger_threshold": round(float(self._deep_right_shadow_trigger_threshold), 4),
                "trigger_ready": bool(deep_right_prob >= self._deep_right_shadow_trigger_threshold),
                "recommended_action": recommended_action,
                "analysis_path": str(self._deep_right_shadow_analysis_path) if self._deep_right_shadow_analysis_path else None,
                "verdict": dict(self._deep_right_shadow_verdict),
            }
            self._deep_right_shadow = shadow
            self._deep_right_shadow_history.append(shadow)
            if len(self._deep_right_shadow_history) > 60:
                self._deep_right_shadow_history = self._deep_right_shadow_history[-60:]

            try:
                DEEP_RIGHT_SHADOW_TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
                with DEEP_RIGHT_SHADOW_TELEMETRY_PATH.open("a", encoding="utf-8") as tf:
                    tf.write(json.dumps({"ts": time.time(), **shadow}) + "\n")
            except Exception:
                pass

            logger.debug(
                "DEEP RIGHT SHADOW: pred=%s p=%.3f runtime_zone=%s action=%s",
                predicted_class,
                deep_right_prob,
                prod_zone,
                recommended_action,
            )
            return shadow
        except Exception as e:
            logger.warning("Deep-right shadow predict error: %s", e)
            return None

    def _apply_deep_right_guidance(
        self,
        *,
        active_nodes: int,
        packets_per_second: float,
    ) -> None:
        shadow = self._deep_right_shadow or {}
        deep_right_prob = float(shadow.get("deep_right_probability") or 0.0)
        predicted_deep_right = shadow.get("predicted_class") == self._deep_right_shadow_positive_alias
        base_eligible = (
            DEEP_RIGHT_GUIDANCE_ENABLED
            and self.current.get("binary") == "occupied"
            and predicted_deep_right
            and bool(shadow.get("trigger_ready"))
            and active_nodes >= DEEP_RIGHT_GUIDANCE_MIN_ACTIVE_NODES
            and float(packets_per_second or 0.0) >= DEEP_RIGHT_GUIDANCE_MIN_PPS
            and str(self.current.get("target_zone") or "") in DEEP_RIGHT_GUIDANCE_ALLOWED_ZONES
        )
        raw_target_x = float(self.current.get("target_x", 0.0) or 0.0)
        raw_target_y = float(self.current.get("target_y", 0.0) or 0.0)
        current_zone = str(self.current.get("target_zone") or "")

        if base_eligible:
            self._deep_right_guidance_consecutive += 1
            if self._deep_right_guidance_consecutive >= DEEP_RIGHT_GUIDANCE_CONSECUTIVE_WINDOWS:
                self._deep_right_guidance_active = True
            self._deep_right_guidance_negative_consecutive = 0
        else:
            self._deep_right_guidance_consecutive = 0
            if self._deep_right_guidance_active:
                hold_ok = (
                    DEEP_RIGHT_GUIDANCE_ENABLED
                    and self.current.get("binary") == "occupied"
                    and active_nodes >= DEEP_RIGHT_GUIDANCE_HOLD_MIN_ACTIVE_NODES
                    and float(packets_per_second or 0.0) >= DEEP_RIGHT_GUIDANCE_HOLD_MIN_PPS
                )
                still_supportive = (
                    predicted_deep_right
                    or deep_right_prob >= DEEP_RIGHT_GUIDANCE_HOLD_MIN_PROB
                    or current_zone == "deep_right"
                )
                if hold_ok and still_supportive:
                    self._deep_right_guidance_negative_consecutive = 0
                elif hold_ok:
                    self._deep_right_guidance_negative_consecutive += 1
                else:
                    self._deep_right_guidance_negative_consecutive = DEEP_RIGHT_GUIDANCE_RELEASE_NEGATIVE_WINDOWS

                if self._deep_right_guidance_negative_consecutive >= DEEP_RIGHT_GUIDANCE_RELEASE_NEGATIVE_WINDOWS:
                    self._deep_right_guidance_active = False
                    self._deep_right_guidance_negative_consecutive = 0
            else:
                self._deep_right_guidance_negative_consecutive = 0

        applied = bool(self._deep_right_guidance_active)
        eligible = bool(base_eligible)

        self.current["deep_right_guidance"] = {
            "enabled": DEEP_RIGHT_GUIDANCE_ENABLED,
            "eligible": eligible,
            "applied": applied,
            "consecutive": self._deep_right_guidance_consecutive,
            "required_consecutive": DEEP_RIGHT_GUIDANCE_CONSECUTIVE_WINDOWS,
            "active": bool(self._deep_right_guidance_active),
            "negative_consecutive": self._deep_right_guidance_negative_consecutive,
            "release_negative_windows": DEEP_RIGHT_GUIDANCE_RELEASE_NEGATIVE_WINDOWS,
            "anchor_x": DEEP_RIGHT_GUIDANCE_ANCHOR_X,
            "anchor_y": DEEP_RIGHT_GUIDANCE_ANCHOR_Y,
            "raw_target_x": round(raw_target_x, 3),
            "raw_target_y": round(raw_target_y, 3),
            "deep_right_probability": shadow.get("deep_right_probability"),
        }

        if not applied:
            return

        self.current.update({
            "target_zone": "deep_right",
            "target_x": round(DEEP_RIGHT_GUIDANCE_ANCHOR_X, 2),
            "target_y": round(DEEP_RIGHT_GUIDANCE_ANCHOR_Y, 2),
            "coordinate_source": "deep_right_shadow_guidance",
        })

    def _apply_empty_subregime_rescue(
        self,
        *,
        active_nodes: int,
        motion_state: str,
    ) -> None:
        """Conservatively rescue empty on the diagnosed false-occupied empty subregime."""
        shadow = self._empty_subregime_shadow or {}
        current_binary = str(self.current.get("binary", "unknown") or "unknown").lower()
        predicted_class = str(shadow.get("predicted_class", "") or "")
        recommended_action = str(shadow.get("recommended_action", "") or "")
        empty_like_ratio = float(shadow.get("empty_like_ratio", 0.0) or 0.0)
        diag_empty_ratio = float(shadow.get("diag_empty_ratio", 0.0) or 0.0)
        occupied_anchor_ratio = float(shadow.get("occupied_anchor_ratio", 0.0) or 0.0)
        runtime_target_zone = str(self.current.get("target_zone", "unknown") or "unknown").lower()
        raw_target_x = self.current.get("target_x")
        raw_target_y = self.current.get("target_y")
        raw_pps = self.current.get("pps", 0.0)
        target_x = float(raw_target_x) if isinstance(raw_target_x, (int, float)) else None
        target_y = float(raw_target_y) if isinstance(raw_target_y, (int, float)) else None
        current_pps = float(raw_pps) if isinstance(raw_pps, (int, float)) else 0.0
        current_binary_conf = float(self.current.get("binary_confidence", 0.0) or 0.0)
        status_active_nodes = int(self.current.get("nodes_active", 0) or 0)
        runtime_active_nodes = max(int(active_nodes or 0), status_active_nodes)
        v29_shadow = self._v29_cnn_shadow or {}
        v29_zone = str(v29_shadow.get("zone", "") or "").lower()
        v29_probs = v29_shadow.get("probabilities") or {}
        raw_v29_door_prob = v29_probs.get("door", 0.0)
        v29_door_prob = (
            float(raw_v29_door_prob)
            if isinstance(raw_v29_door_prob, (int, float))
            else 0.0
        )
        predicted_is_empty_like = predicted_class in {"diag_empty", "canonical_empty"}
        deep_center_like = (
            runtime_target_zone == EMPTY_SUBREGIME_RESCUE_REQUIRED_ZONE
            and target_y is not None
            and target_y >= EMPTY_SUBREGIME_RESCUE_MIN_TARGET_Y
            and target_x is not None
            and target_x <= EMPTY_SUBREGIME_RESCUE_MAX_TARGET_X
        )
        shallow_center_like = (
            runtime_target_zone == EMPTY_SUBREGIME_RESCUE_REQUIRED_ZONE
            and target_x is not None
            and target_x <= EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_TARGET_X
            and target_y is not None
            and target_y <= EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_TARGET_Y
        )
        shallow_hold_like = (
            runtime_target_zone == EMPTY_SUBREGIME_RESCUE_REQUIRED_ZONE
            and target_x is not None
            and target_x <= EMPTY_SUBREGIME_RESCUE_SHALLOW_HOLD_MAX_TARGET_X
            and target_y is not None
            and target_y <= EMPTY_SUBREGIME_RESCUE_SHALLOW_HOLD_MAX_TARGET_Y
        )
        rescue_shape_like = deep_center_like or shallow_center_like
        v29_door_like = (
            v29_zone == "door"
            and v29_door_prob >= EMPTY_SUBREGIME_RESCUE_SHALLOW_MIN_V29_DOOR_PROB
        )

        base_can_rescue = (
            EMPTY_SUBREGIME_RESCUE_ENABLED
            and current_binary == "occupied"
            and motion_state == "NO_MOTION"
            and runtime_active_nodes >= EMPTY_SUBREGIME_RESCUE_MIN_ACTIVE_NODES
            and predicted_is_empty_like
            and recommended_action == "consider_empty_rescue"
            and empty_like_ratio >= EMPTY_SUBREGIME_RESCUE_MIN_EMPTY_LIKE_RATIO
            and diag_empty_ratio >= EMPTY_SUBREGIME_RESCUE_MIN_DIAG_RATIO
            and occupied_anchor_ratio <= EMPTY_SUBREGIME_RESCUE_MAX_OCCUPIED_RATIO
            and deep_center_like
        )
        shallow_can_rescue = (
            EMPTY_SUBREGIME_RESCUE_ENABLED
            and current_binary == "occupied"
            and motion_state == "NO_MOTION"
            and runtime_active_nodes >= EMPTY_SUBREGIME_RESCUE_MIN_ACTIVE_NODES
            and predicted_class == "diag_empty"
            and recommended_action == "consider_empty_rescue"
            and empty_like_ratio >= EMPTY_SUBREGIME_RESCUE_SHALLOW_MIN_EMPTY_LIKE_RATIO
            and diag_empty_ratio >= EMPTY_SUBREGIME_RESCUE_SHALLOW_MIN_DIAG_RATIO
            and occupied_anchor_ratio <= EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_OCCUPIED_RATIO
            and current_binary_conf <= EMPTY_SUBREGIME_RESCUE_SHALLOW_MAX_BINARY_CONF
            and shallow_center_like
            and v29_door_like
        )
        sticky_hold = (
            EMPTY_SUBREGIME_RESCUE_ENABLED
            and self._empty_subregime_rescue_consecutive >= EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS
            and current_binary == "occupied"
            and motion_state == "NO_MOTION"
            and runtime_active_nodes >= EMPTY_SUBREGIME_RESCUE_MIN_ACTIVE_NODES
            and predicted_is_empty_like
            and recommended_action == "consider_empty_rescue"
            and empty_like_ratio >= EMPTY_SUBREGIME_RESCUE_MIN_EMPTY_LIKE_RATIO
            and occupied_anchor_ratio <= EMPTY_SUBREGIME_RESCUE_MAX_OCCUPIED_RATIO
            and (rescue_shape_like or shallow_hold_like)
        )
        weak_window_hold = (
            EMPTY_SUBREGIME_RESCUE_ENABLED
            and self._empty_subregime_rescue_consecutive >= EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS
            and current_binary == "occupied"
            and motion_state == "NO_MOTION"
            and runtime_active_nodes >= EMPTY_SUBREGIME_RESCUE_HOLD_MIN_ACTIVE_NODES
            and current_pps <= EMPTY_SUBREGIME_RESCUE_HOLD_MAX_PPS
            and predicted_class == "diag_empty"
            and (rescue_shape_like or shallow_hold_like)
        )
        empty_state_hold = (
            EMPTY_SUBREGIME_RESCUE_ENABLED
            and current_binary == "empty"
            and motion_state == "NO_MOTION"
            and runtime_active_nodes >= EMPTY_SUBREGIME_RESCUE_HOLD_MIN_ACTIVE_NODES
            and predicted_is_empty_like
            and recommended_action == "consider_empty_rescue"
            and empty_like_ratio >= EMPTY_SUBREGIME_RESCUE_SHALLOW_MIN_EMPTY_LIKE_RATIO
            and (
                self._empty_subregime_rescue_consecutive >= EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS
                or v29_door_like
            )
        )
        can_rescue = (
            base_can_rescue
            or shallow_can_rescue
            or sticky_hold
            or weak_window_hold
            or empty_state_hold
        )

        if not can_rescue:
            self._empty_subregime_rescue_consecutive = 0
            self.current["empty_subregime_rescue"] = {
                "enabled": EMPTY_SUBREGIME_RESCUE_ENABLED,
                "eligible": False,
                "applied": False,
                "consecutive": 0,
                "required_consecutive": EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS,
                "predicted_class": predicted_class or None,
                "recommended_action": recommended_action or None,
                "empty_like_ratio": round(empty_like_ratio, 4),
                "diag_empty_ratio": round(diag_empty_ratio, 4),
                "occupied_anchor_ratio": round(occupied_anchor_ratio, 4),
                "runtime_target_zone": runtime_target_zone,
                "runtime_target_x": round(target_x, 3) if target_x is not None else None,
                "runtime_target_y": round(target_y, 3) if target_y is not None else None,
                "deep_center_like": bool(deep_center_like),
                "shallow_center_like": bool(shallow_center_like),
                "shallow_hold_like": bool(shallow_hold_like),
                "shallow_profile": bool(shallow_can_rescue),
                "sticky_hold": bool(sticky_hold),
                "weak_window_hold": bool(weak_window_hold),
                "empty_state_hold": bool(empty_state_hold),
                "runtime_pps": round(current_pps, 3),
                "runtime_binary_confidence": round(current_binary_conf, 4),
                "runtime_active_nodes": runtime_active_nodes,
                "v29_zone": v29_zone or None,
                "v29_door_probability": round(v29_door_prob, 4),
                "v29_door_like": bool(v29_door_like),
            }
            return

        if empty_state_hold:
            self._empty_subregime_rescue_consecutive = max(
                self._empty_subregime_rescue_consecutive,
                EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS,
            )
            self.current["empty_subregime_rescue"] = {
                "enabled": EMPTY_SUBREGIME_RESCUE_ENABLED,
                "eligible": True,
                "applied": True,
                "consecutive": self._empty_subregime_rescue_consecutive,
                "required_consecutive": EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS,
                "predicted_class": predicted_class,
                "recommended_action": recommended_action,
                "empty_like_ratio": round(empty_like_ratio, 4),
                "diag_empty_ratio": round(diag_empty_ratio, 4),
                "occupied_anchor_ratio": round(occupied_anchor_ratio, 4),
                "runtime_target_zone": runtime_target_zone,
                "runtime_target_x": round(target_x, 3) if target_x is not None else None,
                "runtime_target_y": round(target_y, 3) if target_y is not None else None,
                "deep_center_like": bool(deep_center_like),
                "shallow_center_like": bool(shallow_center_like),
                "shallow_hold_like": bool(shallow_hold_like),
                "shallow_profile": bool(shallow_can_rescue),
                "sticky_hold": bool(sticky_hold),
                "weak_window_hold": bool(weak_window_hold),
                "empty_state_hold": True,
                "runtime_pps": round(current_pps, 3),
                "runtime_binary_confidence": round(current_binary_conf, 4),
                "runtime_active_nodes": runtime_active_nodes,
                "v29_zone": v29_zone or None,
                "v29_door_probability": round(v29_door_prob, 4),
                "v29_door_like": bool(v29_door_like),
            }
            return

        self._empty_subregime_rescue_consecutive += 1
        applied = self._empty_subregime_rescue_consecutive >= EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS
        self.current["empty_subregime_rescue"] = {
            "enabled": EMPTY_SUBREGIME_RESCUE_ENABLED,
            "eligible": True,
            "applied": applied,
            "consecutive": self._empty_subregime_rescue_consecutive,
            "required_consecutive": EMPTY_SUBREGIME_RESCUE_CONSECUTIVE_WINDOWS,
            "predicted_class": predicted_class,
            "recommended_action": recommended_action,
            "empty_like_ratio": round(empty_like_ratio, 4),
            "diag_empty_ratio": round(diag_empty_ratio, 4),
            "occupied_anchor_ratio": round(occupied_anchor_ratio, 4),
            "runtime_target_zone": runtime_target_zone,
            "runtime_target_x": round(target_x, 3) if target_x is not None else None,
            "runtime_target_y": round(target_y, 3) if target_y is not None else None,
            "deep_center_like": bool(deep_center_like),
            "shallow_center_like": bool(shallow_center_like),
            "shallow_hold_like": bool(shallow_hold_like),
            "shallow_profile": bool(shallow_can_rescue),
            "sticky_hold": bool(sticky_hold),
            "weak_window_hold": bool(weak_window_hold),
            "empty_state_hold": False,
            "runtime_pps": round(current_pps, 3),
            "runtime_binary_confidence": round(current_binary_conf, 4),
            "runtime_active_nodes": runtime_active_nodes,
            "v29_zone": v29_zone or None,
            "v29_door_probability": round(v29_door_prob, 4),
            "v29_door_like": bool(v29_door_like),
        }
        if not applied:
            return

        rescue_conf = min(
            0.99,
            max(
                0.9,
                0.5 + 0.3 * empty_like_ratio + 0.2 * diag_empty_ratio,
            ),
        )
        self.current.update(
            {
                "binary": "empty",
                "binary_confidence": round(rescue_conf, 3),
                "coarse": "empty",
                "coarse_confidence": round(rescue_conf, 3),
                "target_x": 0.0,
                "target_y": 0.0,
                "target_zone": "empty",
                "coordinate_source": "empty_subregime_rescue",
                "decision_model_backend": "v48_empty_subregime_rescue",
            }
        )

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
                "ts": time.time(),
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

    def _get_latest_v8_shadow(self, *, max_age_sec: float = 30.0) -> dict:
        """Return the freshest usable V8 shadow, falling back to recent history.

        The live status surface and empty guards should not lose a valid EMPTY verdict
        just because one runtime window skipped V8 inference or is still warming up.
        """
        current = self._v8_shadow or {}
        current_binary = str(current.get("binary", "") or "").lower()
        if current_binary in {"empty", "occupied"}:
            return current

        now = time.time()
        for entry in reversed(self._v8_history):
            entry_binary = str(entry.get("binary", "") or "").lower()
            if entry_binary not in {"empty", "occupied"}:
                continue
            entry_ts = float(entry.get("ts", 0.0) or 0.0)
            if entry_ts > 0.0 and (now - entry_ts) > max_age_sec:
                continue
            fallback = dict(entry)
            fallback["status"] = "history_fallback"
            if entry_ts > 0.0:
                fallback["stale_sec"] = round(max(0.0, now - entry_ts), 3)
            return fallback

        return current

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
                # Max human speed ~1.5 m/s, window ~2s → max 3m per window
                # Clamp large jumps (likely noise, not real movement)
                MAX_STEP_M = 0.5  # max 0.5m per window for smooth tracking
                alpha = min(MAX_STEP_M / dist, 0.3) if dist > 0.3 else 0.1
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
        """Parse base64 CSI payload into amplitude and phase arrays (64-sub normalized).

        Supports V1 (magic=0xC5110001, 20-byte header) and V2 (magic=0xC5110002,
        24-byte header with flags/phase_offset fields) firmware packet formats.
        """
        import struct as _struct
        raw = base64.b64decode(b64)
        if len(raw) < 4:
            return None, None

        magic = _struct.unpack_from('<I', raw, 0)[0]
        if magic == CSI_MAGIC_V2:
            header_size = CSI_HEADER_SIZE_V2
            if len(raw) < header_size + 40:
                return None, None
            flags = raw[20]
            has_hw_phase = bool(flags & 0x01)
            phase_offset_field = _struct.unpack_from('<H', raw, 21)[0]
            iq_end = header_size + phase_offset_field if has_hw_phase else len(raw)
            iq = raw[header_size:iq_end][:256]
        elif magic == CSI_MAGIC_V1:
            header_size = CSI_HEADER_SIZE_V1
            if len(raw) < header_size + 40:
                return None, None
            iq = raw[header_size : header_size + 256]
        else:
            # Unknown magic — fall back to legacy V1 behaviour
            header_size = CSI_HEADER_SIZE_V1
            if len(raw) < header_size + 40:
                return None, None
            iq = raw[header_size : header_size + 256]

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

    def _extract_window_features(
        self,
        t_start: float,
        t_end: float,
        *,
        record_baseline: bool = True,
    ) -> dict | None:
        """Extract V21-compatible features for one window from live buffer."""
        feat = {"t_mid": (t_start + t_end) / 2}
        nm, ns, nv, nd1 = [], [], [], []
        n_sc_ent, n_sc_frac, n_dop, n_bldev = [], [], [], []
        n_pcc, n_sti = [], []
        active_nodes = 0
        packet_count = 0

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

            node_pkt_count = len(pkts)
            packet_count += node_pkt_count
            if node_pkt_count >= 1:
                active_nodes += 1

            if node_pkt_count < 3:
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
                    "pcc_mean", "pcc_std", "pcc_min", "sti_mean", "sti_max",
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
                n_pcc.append(0); n_sti.append(0)
                continue
            rssi_vals = np.array([r for _, r, _, _ in pkts], dtype=np.float32)
            _legacy_sub = self._V48_N_SUB
            _pkt_lens_arr = np.array(
                [min(len(a), _legacy_sub) for _, _, a, _ in pkts],
                dtype=np.float32,
            )
            _amp_rows = []
            _phase_rows = []
            for _, _, a, p in pkts:
                amp_row = np.zeros(_legacy_sub, dtype=np.float32)
                phase_row = np.zeros(_legacy_sub, dtype=np.float32)
                amp_copy = min(len(a), _legacy_sub)
                phase_copy = min(len(p), _legacy_sub) if p is not None else 0
                if amp_copy > 0:
                    amp_row[:amp_copy] = a[:amp_copy]
                if phase_copy > 0:
                    phase_row[:phase_copy] = p[:phase_copy]
                _amp_rows.append(amp_row)
                _phase_rows.append(phase_row)
            amp_mat = np.array(_amp_rows, dtype=np.float32)
            phase_mat = np.array(_phase_rows, dtype=np.float32)
            amps = np.array(
                [
                    float(amp_mat[i, : int(_pkt_lens_arr[i])].mean()) if _pkt_lens_arr[i] > 0 else 0.0
                    for i in range(node_pkt_count)
                ],
                dtype=np.float32,
            )
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

            # ── V57: PCC & STI features (CSIKit-inspired) ──────────────
            # PCC: mean Pearson correlation between consecutive CSI frames
            # STI: spatial-temporal index (normalized L2 distance between frames)
            # These directly measure temporal stationarity — key for empty vs static.
            if amp_mat.shape[0] >= 3:
                _pcc_vals = []
                _sti_vals = []
                for _fi in range(amp_mat.shape[0] - 1):
                    _f1 = amp_mat[_fi]
                    _f2 = amp_mat[_fi + 1]
                    # PCC
                    _f1d = _f1 - _f1.mean()
                    _f2d = _f2 - _f2.mean()
                    _denom = np.sqrt((_f1d ** 2).sum() * (_f2d ** 2).sum())
                    if _denom > 1e-10:
                        _pcc_vals.append(float((_f1d * _f2d).sum() / _denom))
                    # STI
                    _s1 = _f1d / (np.std(_f1) + 1e-10)
                    _s2 = _f2d / (np.std(_f2) + 1e-10)
                    _sti_vals.append(float(np.linalg.norm(_s1 - _s2)))
                feat[f"{pre}_pcc_mean"] = float(np.mean(_pcc_vals)) if _pcc_vals else 0
                feat[f"{pre}_pcc_std"] = float(np.std(_pcc_vals)) if len(_pcc_vals) > 1 else 0
                feat[f"{pre}_pcc_min"] = float(np.min(_pcc_vals)) if _pcc_vals else 0
                feat[f"{pre}_sti_mean"] = float(np.mean(_sti_vals)) if _sti_vals else 0
                feat[f"{pre}_sti_max"] = float(np.max(_sti_vals)) if _sti_vals else 0
            else:
                feat[f"{pre}_pcc_mean"] = 0
                feat[f"{pre}_pcc_std"] = 0
                feat[f"{pre}_pcc_min"] = 0
                feat[f"{pre}_sti_mean"] = 0
                feat[f"{pre}_sti_max"] = 0

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
            if record_baseline:
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
            n_pcc.append(feat[f"{pre}_pcc_mean"])
            n_sti.append(feat[f"{pre}_sti_mean"])

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

            # V57: Cross-node PCC/STI aggregates
            feat["x_pcc_mean"] = float(np.mean(n_pcc))
            feat["x_pcc_min"] = float(min(n_pcc))
            feat["x_pcc_std"] = float(np.std(n_pcc))
            feat["x_sti_mean"] = float(np.mean(n_sti))
            feat["x_sti_max"] = float(max(n_sti))

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
                       "x_pcc_mean", "x_pcc_min", "x_pcc_std", "x_sti_mean", "x_sti_max",
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

        # ── Mesh link features (ESP-NOW peer-to-peer) ──────────────────
        if self._mesh_enabled and self._mesh.peer_link_count > 0:
            mesh_feats = self._mesh.extract_all_link_features(
                t_start, t_end, peer_only=False, max_links=16,
            )
            feat.update(mesh_feats)
        else:
            feat["mesh_spatial_variance"] = 0.0
            feat["mesh_link_agreement"] = 1.0
            feat["mesh_max_link_delta"] = 0.0
            feat["mesh_active_peer_links"] = 0.0

        return feat, active_nodes, packet_count

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
        window_sec = self._active_feature_window_sec()
        # Sliding window: step by WINDOW_SLIDE_SEC, use the active model's
        # feature-window contract for the data span.
        w_end = int(now / WINDOW_SLIDE_SEC) * WINDOW_SLIDE_SEC

        w_start = w_end - window_sec

        if w_end <= self._last_window_time or w_start < 0:
            return

        self._last_window_time = w_end

        # ── V48 path: use epoch3 feature extraction ──────────────────
        _is_v48 = getattr(self, '_active_model_kind', None) == "v21_like" and \
                  any("node01_amp_mean" in f for f in (self.feature_names or []))

        if _is_v48:
            feat = self._extract_v48_features(w_start, w_end)
            if feat is None:
                return
            active_nodes = int(feat.get("active_nodes", 0))
            pkt_count = int(feat.get("total_pkt_count", 0))
            self._last_window_feat = feat

            # Empty baseline capture is recorded directly inside the active
            # V48 feature path, keyed by the live node IPs. Do not duplicate
            # legacy sidecar windows here.

            X = np.array([[feat.get(f, 0) for f in self.feature_names]], dtype=np.float32)
            X = np.nan_to_num(X, nan=0, posinf=0, neginf=0)

            # ── TEMP DIAG: dump key features to /tmp ──
            try:
                _diag_proba = self.binary_model.predict_proba(X)[0].tolist() if hasattr(self.binary_model, 'predict_proba') else None
                _diag_pred = int(self.binary_model.predict(X)[0]) if self.binary_model else None
                _diag_top = {k: round(float(feat.get(k, 0)), 4) for k in [
                    'node06_band6_mean','node06_band5_mean','corr_node01_node03',
                    'corr_node04_node06','ratio_node01_node06','tvar_mean','tvar_max']}
                with open("/tmp/csi_v50_diag.log", "a") as _df:
                    import json as _dj
                    _df.write(_dj.dumps({"t": round(w_end, 1), "top": _diag_top, "proba": _diag_proba, "pred": _diag_pred, "pkts": pkt_count, "nodes": active_nodes}) + "\n")
            except Exception:
                pass

            # V48 coordinate prediction (embedded in bundle)
            # Guard: skip coord prediction when too few nodes have data
            _active_coord_nodes = sum(1 for n in ["node01","node02","node03","node04","node05","node06","node07"]
                                      if feat.get(f"{n}_amp_mean", 0) > 0)
            _coord_skip = _active_coord_nodes < 6
            if _coord_skip:
                self._coord_diag = {"skipped": True, "active_nodes": _active_coord_nodes, "reason": "too_few_nodes"}
            if hasattr(self, '_v48_coord_x') and self._v48_coord_x is not None and not _coord_skip:
                try:
                    # Compute weighted centroid features (wc_*)
                    _NODE_POS = {
                        'node01': (0.0, 0.55), 'node02': (3.0, 0.55), 'node03': (0.0, 3.15),
                        'node04': (3.0, 2.5), 'node05': (1.5, 3.5), 'node06': (0.0, 4.35),
                        'node07': (3.0, 3.7),
                    }
                    _wc_amps = {}
                    for nid, pos in _NODE_POS.items():
                        a = feat.get(f'{nid}_amp_mean', 0)
                        if a > 0:
                            _wc_amps[nid] = a
                    if _wc_amps:
                        _tw = sum(a for a in _wc_amps.values())
                        feat['wc_x'] = sum(_NODE_POS[n][0] * a for n, a in _wc_amps.items()) / _tw
                        feat['wc_y'] = sum(_NODE_POS[n][1] * a for n, a in _wc_amps.items()) / _tw
                        # Weighted std
                        _wc_x = feat['wc_x']
                        _wc_y = feat['wc_y']
                        feat['wc_x_std'] = (sum(a * (_NODE_POS[n][0] - _wc_x)**2 for n, a in _wc_amps.items()) / _tw) ** 0.5
                        feat['wc_y_std'] = (sum(a * (_NODE_POS[n][1] - _wc_y)**2 for n, a in _wc_amps.items()) / _tw) ** 0.5
                        # Max/min amplitude node position
                        _max_n = max(_wc_amps, key=_wc_amps.get)
                        _min_n = min(_wc_amps, key=_wc_amps.get)
                        feat['wc_max_node_x'] = _NODE_POS[_max_n][0]
                        feat['wc_max_node_y'] = _NODE_POS[_max_n][1]
                        feat['wc_min_node_x'] = _NODE_POS[_min_n][0]
                        feat['wc_min_node_y'] = _NODE_POS[_min_n][1]
                        # Spread: max distance weighted by amp difference
                        _spread = 0.0
                        _nlist = list(_wc_amps.keys())
                        for _i in range(len(_nlist)):
                            for _j in range(_i+1, len(_nlist)):
                                _dx = _NODE_POS[_nlist[_i]][0] - _NODE_POS[_nlist[_j]][0]
                                _dy = _NODE_POS[_nlist[_i]][1] - _NODE_POS[_nlist[_j]][1]
                                _dist = (_dx**2 + _dy**2) ** 0.5
                                _adiff = abs(_wc_amps[_nlist[_i]] - _wc_amps[_nlist[_j]])
                                _spread = max(_spread, _dist * _adiff)
                        feat['wc_spread'] = _spread
                    else:
                        for _wk in ['wc_x','wc_y','wc_x_std','wc_y_std','wc_max_node_x','wc_max_node_y',
                                     'wc_min_node_x','wc_min_node_y','wc_spread']:
                            feat[_wk] = 0.0

                    coord_feats = getattr(self, '_v48_coord_feature_names', None) or self.feature_names
                    Xc = np.array([[feat.get(f, 0) for f in coord_feats]], dtype=np.float32)
                    Xc = np.nan_to_num(Xc, nan=0, posinf=0, neginf=0)
                    # ── DIAG: save coord feature snapshot for API ──
                    _zero_feats = [f for f, v in zip(coord_feats, Xc[0]) if v == 0.0]
                    self._coord_diag = {
                        "n_zero": len(_zero_feats),
                        "n_total": len(coord_feats),
                        "zero_feats": _zero_feats[:10],
                        "key_feats": {f: round(float(feat.get(f, 0)), 4)
                                      for f in coord_feats
                                      if any(k in f for k in ('node01_amp', 'node02_amp', 'node05_amp',
                                                               'corr_node02_node05', 'corr_node01',
                                                               'node06_band', 'node02_rssi',
                                                               'ratio_node01'))},
                    }
                    # Apply coordinate scaler if available
                    _cscaler = getattr(self, '_v48_coord_scaler', None)
                    if _cscaler is not None:
                        Xc = _cscaler.transform(Xc)
                    pred_x = float(self._v48_coord_x.predict(Xc)[0])
                    pred_y = float(self._v48_coord_y.predict(Xc)[0])
                    self._coord_diag["pred_x"] = round(pred_x, 3)
                    self._coord_diag["pred_y"] = round(pred_y, 3)
                    self._v48_last_coord = (pred_x, pred_y)
                    shallow_shadow = self._predict_shallow_coord_shadow(feat)
                    if shallow_shadow is not None:
                        shadow_x, shadow_y = shallow_shadow
                        self._shallow_coord_shadow = {
                            "loaded": True,
                            "status": "ok",
                            "target_x": round(shadow_x, 2),
                            "target_y": round(shadow_y, 2),
                            "model_path": self._shallow_coord_shadow_path,
                        }
                    elif self._shallow_coord_shadow_loaded:
                        self._shallow_coord_shadow = {
                            "loaded": True,
                            "status": "predict_failed",
                            "model_path": self._shallow_coord_shadow_path,
                        }
                except Exception as e:
                    import sys as _s, traceback as _tb
                    _cc2 = getattr(self, '_v48_err_count', 0) + 1; self._v48_err_count = _cc2
                    if _cc2 <= 3:
                        print(f"[V48-ERR] coord failed: {e}", file=_s.stderr, flush=True)
                        _tb.print_exc(file=_s.stderr)

            # ── V49 zone3 classifier prediction ──────────────────────
            if getattr(self, '_zone3_classifier', None) is not None and getattr(self, '_zone3_feature_names', None) is not None:
                try:
                    import sys as _zsys
                    # Compute extra features needed by zone3 classifier
                    # (WC features already computed above by coord block)

                    # tvar_diff pairs: nodeA_tvar - nodeB_tvar
                    _z3_nodes = sorted([f'node{i:02d}' for i in range(1, 8)])
                    for _zi in range(len(_z3_nodes)):
                        for _zj in range(_zi + 1, len(_z3_nodes)):
                            _zn1, _zn2 = _z3_nodes[_zi], _z3_nodes[_zj]
                            feat[f'tvar_diff_{_zn1}_{_zn2}'] = feat.get(f'{_zn1}_tvar', 0) - feat.get(f'{_zn2}_tvar', 0)

                    # phase_ratio pairs: phase_rate_mean ratio between nodes
                    for _zi in range(len(_z3_nodes)):
                        for _zj in range(_zi + 1, len(_z3_nodes)):
                            _zn1, _zn2 = _z3_nodes[_zi], _z3_nodes[_zj]
                            _pr_denom = feat.get(f'{_zn2}_phase_rate_mean', 0)
                            _pr_denom = _pr_denom if abs(_pr_denom) > 1e-6 else 1e-6
                            feat[f'phase_ratio_{_zn1}_{_zn2}'] = feat.get(f'{_zn1}_phase_rate_mean', 0) / _pr_denom

                    # door/deep aggregate features
                    # door nodes: node01, node02 (y~0.55); deep nodes: node06, node07 (y>3.7)
                    _door_amp = (feat.get('node01_amp_mean', 0) + feat.get('node02_amp_mean', 0)) / 2.0
                    _deep_amp = (feat.get('node06_amp_mean', 0) + feat.get('node07_amp_mean', 0)) / 2.0
                    _door_tvar = (feat.get('node01_tvar', 0) + feat.get('node02_tvar', 0)) / 2.0
                    _deep_tvar = (feat.get('node06_tvar', 0) + feat.get('node07_tvar', 0)) / 2.0
                    feat['diff_door_deep_amp'] = _door_amp - _deep_amp
                    feat['diff_door_deep_tvar'] = _door_tvar - _deep_tvar
                    _dd_amp_denom = _deep_amp if _deep_amp > 1e-6 else 1e-6
                    _dd_tvar_denom = _deep_tvar if _deep_tvar > 1e-6 else 1e-6
                    feat['ratio_door_deep_amp'] = _door_amp / _dd_amp_denom
                    feat['ratio_door_deep_tvar'] = _door_tvar / _dd_tvar_denom

                    # phase_rate_hi / phase_rate_lo / phase_accel_mean per node
                    # These require raw phase data; compute from packets if available
                    for _zip in NODE_IPS:
                        _zname = self._V48_NODE_NAMES.get(_zip, _zip)
                        _zpkts = [(t, r, a, p) for t, r, a, p in self._packets.get(_zip, [])
                                  if w_start <= t < w_end]
                        _zphase_pkts = [p for _, _, _, p in _zpkts if p is not None and len(p) > 0]
                        if len(_zphase_pkts) >= 5:
                            _zph_mat = np.array(_zphase_pkts, dtype=np.float32)
                            if _zph_mat.shape[1] < self._V48_N_SUB:
                                _zpad = np.zeros((_zph_mat.shape[0], self._V48_N_SUB), dtype=np.float32)
                                _zpad[:, :_zph_mat.shape[1]] = _zph_mat
                                _zph_mat = _zpad
                            else:
                                _zph_mat = _zph_mat[:, :self._V48_N_SUB]
                            _zph_unwrap = np.unwrap(_zph_mat, axis=0)
                            _zph_rate = np.diff(_zph_unwrap, axis=0)
                            _zph_abs = np.abs(_zph_rate).mean(axis=1)  # per-timestep mean rate
                            _z_median = float(np.median(_zph_abs))
                            feat[f'{_zname}_phase_rate_hi'] = float(np.mean(_zph_abs[_zph_abs > _z_median])) if np.any(_zph_abs > _z_median) else 0.0
                            feat[f'{_zname}_phase_rate_lo'] = float(np.mean(_zph_abs[_zph_abs <= _z_median])) if np.any(_zph_abs <= _z_median) else 0.0
                            # phase acceleration = diff of rate
                            if len(_zph_rate) >= 2:
                                _zph_accel = np.diff(_zph_rate, axis=0)
                                feat[f'{_zname}_phase_accel_mean'] = float(np.abs(_zph_accel).mean())
                            else:
                                feat[f'{_zname}_phase_accel_mean'] = 0.0
                        else:
                            feat[f'{_zname}_phase_rate_hi'] = 0.0
                            feat[f'{_zname}_phase_rate_lo'] = 0.0
                            feat[f'{_zname}_phase_accel_mean'] = 0.0

                    # Build zone3 feature vector
                    Xz = np.array([[feat.get(f, 0) for f in self._zone3_feature_names]], dtype=np.float32)
                    Xz = np.nan_to_num(Xz, nan=0, posinf=0, neginf=0)
                    if self._zone3_scaler is not None:
                        Xz = self._zone3_scaler.transform(Xz)
                    z3_pred = self._zone3_classifier.predict(Xz)[0]
                    z3_proba = self._zone3_classifier.predict_proba(Xz)[0]
                    z3_zone = self._zone3_labels[z3_pred] if isinstance(z3_pred, (int, np.integer)) else str(z3_pred)
                    z3_conf = float(z3_proba.max())
                    # Map probabilities using classifier's own classes_ order
                    _z3_classes = list(self._zone3_classifier.classes_)
                    z3_prob_dict = {str(_z3_classes[i]): round(float(z3_proba[i]), 4) for i in range(len(_z3_classes))}
                    self._zone3_last = (z3_zone, z3_conf, z3_prob_dict)
                    print(f"[ZONE3] pred={z3_zone} conf={z3_conf:.3f} probs={self._zone3_last[2]}", file=_zsys.stderr, flush=True)
                except Exception as _ze:
                    import traceback as _ztb
                    _zec = getattr(self, '_zone3_err_count', 0) + 1; self._zone3_err_count = _zec
                    if _zec <= 3:
                        print(f"[ZONE3-ERR] zone3 failed: {_ze}", file=_zsys.stderr, flush=True)
                        _ztb.print_exc(file=_zsys.stderr)

        else:
            result = self._extract_window_features(w_start, w_end)
            if result is None:
                return

            feat, active_nodes, pkt_count = result
            self._last_window_feat = feat

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

        # Binary prediction with the bundle/runtime threshold.
        # Do not hardcode a separate V48 RF threshold here: that created a
        # silent mismatch where offline eval used 0.5 but live runtime used
        # 0.92, suppressing occupied recall on real windows.
        self._active_binary_backend = self._base_binary_backend or self._active_binary_backend or "unknown"
        bin_proba = self.binary_model.predict_proba(X)[0]
        threshold = getattr(self, '_binary_threshold', 0.5)
        # proba[1] = P(occupied)
        p_occupied = float(bin_proba[1]) if len(bin_proba) > 1 else float(bin_proba[0])
        bin_pred = 1 if p_occupied >= threshold else 0
        binary_label = "occupied" if bin_pred == 1 else "empty"
        binary_conf = p_occupied if bin_pred == 1 else (1 - p_occupied)
        logger.debug("V48 binary: p_occ=%.3f threshold=%.2f -> %s (backend=%s)",
                     p_occupied, threshold, binary_label, self._active_binary_backend)

        # ── V60 mesh binary override (when peer links available) ─────────
        # V60 uses peer-to-peer CSI features (GBM-500, CV F1=0.9665).
        # When enough mesh peer links are active, V60 replaces V48 binary.
        v60_override = False
        v60_diag: dict[str, Any] = {}
        if self._v60_loaded and V60_MESH_BINARY_ENABLED:
            v60_feat = self._extract_v60_mesh_features(w_start, w_end)
            if v60_feat is not None:
                try:
                    X_v60 = np.array(
                        [[v60_feat.get(c, 0.0) for c in self._v60_feature_cols]],
                        dtype=np.float32,
                    )
                    X_v60 = np.nan_to_num(X_v60, nan=0.0, posinf=0.0, neginf=0.0)
                    v60_proba = self._v60_model.predict_proba(X_v60)[0]
                    v60_p_occ = float(v60_proba[1]) if len(v60_proba) > 1 else float(v60_proba[0])
                    v60_pred = 1 if v60_p_occ >= 0.5 else 0
                    v60_label = "occupied" if v60_pred == 1 else "empty"
                    v60_conf = v60_p_occ if v60_pred == 1 else (1.0 - v60_p_occ)

                    # Override V48 with V60
                    bin_pred = v60_pred
                    binary_label = v60_label
                    binary_conf = v60_conf
                    p_occupied = v60_p_occ
                    v60_override = True
                    self._active_binary_backend = "v60_mesh_binary"

                    v60_diag = {
                        "active": True,
                        "p_occupied": round(v60_p_occ, 4),
                        "prediction": v60_label,
                        "confidence": round(v60_conf, 4),
                        "peer_links": int(v60_feat.get("mesh_active_peer_links", 0)),
                        "peer_pkt_count": int(v60_feat.get("peer_pkt_count", 0)),
                    }
                    logger.info(
                        "V60 mesh binary: p_occ=%.3f -> %s (conf=%.3f, %d peer links, %d peer pkts)",
                        v60_p_occ, v60_label, v60_conf,
                        int(v60_feat.get("mesh_active_peer_links", 0)),
                        int(v60_feat.get("peer_pkt_count", 0)),
                    )
                except Exception as e:
                    logger.debug("V60 mesh binary prediction failed: %s", e)
                    v60_diag = {"active": False, "error": str(e)}
            else:
                v60_diag = {"active": False, "reason": "insufficient_peer_links"}

        # ── Track B ensemble override (conservative) ─────────────────────
        # Override V5=empty ONLY when:
        #  1. Track B is very confident (>0.85 occupied)
        #  2. V5 is not strongly confident about empty (p_occupied > 0.15)
        #  3. Track B has been consistent for 3+ consecutive windows
        # This prevents false positives from Track B warmup / empty-garage noise.
        track_b_override = False
        if not hasattr(self, '_track_b_consecutive_occupied'):
            self._track_b_consecutive_occupied = 0

        if bin_pred == 0 and self._track_b_loaded and self._active_binary_backend != "v48_random_forest":
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
                    "\u2014 max_sc_var_hi(n0,n1)=%.2f > %.1f, tvar=%.3f < %.1f, "
                    "min_pps=%.1f \u2192 force empty (was occupied p=%.3f)",
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
        
            # ── NODE04 BASELINE DETREND GATE (2026-03-30) ──────────────────
            # node04 (n3, IP 192.168.0.110) exhibits chronic high sc_tvar in empty
            # garage (~3.6), causing FP. If empty baseline is loaded and node04
            # sc_var deviation is within 1.5 sigma of its empty baseline, force empty.
            NODE04_IP = "192.168.0.125"
            NODE04_DETREND_SIGMA = 1.5   # max allowed z-score vs empty baseline
            NODE04_DETREND_MIN_PPS = 5.0  # minimum pps to trust the gate
            if (not sc_var_noise_override
                    and bin_pred == 1
                    and self._empty_baselines
                    and NODE04_IP in self._empty_baselines
                    and min_node_pps >= NODE04_DETREND_MIN_PPS):
                bl04 = self._empty_baselines[NODE04_IP]
                n3_sc_var = float(feat.get("n3_sc_var_mean", 0) or 0)
                bl04_mean = float(bl04.get("sc_var_mean", 0) or 0)
                bl04_std  = float(bl04.get("sc_var_std", 1e-4) or 1e-4)
                n3_dev_z = abs(n3_sc_var - bl04_mean) / (bl04_std + 1e-6)
                if n3_dev_z <= NODE04_DETREND_SIGMA and x_tvar_mean < SC_VAR_MOTION_TVAR_CEILING:
                    sc_var_noise_override = True
                    bin_pred = 0
                    binary_label = "empty"
                    binary_conf = 1.0 - p_occupied
                    track_b_override = False
                    self._track_b_consecutive_occupied = 0
                    logger.info(
                        "NODE04 DETREND GATE: n3 sc_var=%.3f within %.1f\u03c3 of empty "
                        "baseline (bl_mean=%.3f bl_std=%.3f dev_z=%.2f) "
                        "tvar=%.3f \u2192 force empty (was occupied p=%.3f)",
                        n3_sc_var, NODE04_DETREND_SIGMA,
                        bl04_mean, bl04_std, n3_dev_z,
                        x_tvar_mean, p_occupied,
                    )
                    sc_var_noise_diag = {
                        "guard_fired": True,
                        "gate": "node04_detrend",
                        "node04_sc_var": round(n3_sc_var, 3),
                        "baseline_mean": round(bl04_mean, 3),
                        "baseline_std": round(bl04_std, 4),
                        "dev_z": round(n3_dev_z, 3),
                        "sigma_threshold": NODE04_DETREND_SIGMA,
                        "x_tvar_mean": round(x_tvar_mean, 4),
                        "min_node_pps": round(min_node_pps, 1),
                        "original_p_occupied": round(p_occupied, 4),
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
        ) / window_sec

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

        # Determine zone — RSSI-based when PPS low, V48 coords when PPS sufficient
        _zone3_result = getattr(self, '_zone3_last', None)
        _v48_coord_available = getattr(self, '_coord_gbr_prev', (0.0, 0.0)) != (0.0, 0.0)

        # RSSI-based 2-zone detection (door vs center) — works at any PPS
        # n02_rssi has high variance at low PPS (±6 dBm per window).
        # Strategy: median of last N raw RSSI values + majority vote over windows.
        # Deep zone only available at high PPS via V48 coord model.
        _n02_rssi = feat.get("node02_rssi_mean", -100.0)
        if not hasattr(self, '_rssi_history'):
            self._rssi_history = []
            self._rssi_vote_history = []
        if _n02_rssi > -90.0:
            self._rssi_history.append(_n02_rssi)
            if len(self._rssi_history) > 12:
                self._rssi_history = self._rssi_history[-12:]
        # Median of last 8 values for smoothing
        _rssi_vals = self._rssi_history[-8:] if len(self._rssi_history) >= 3 else self._rssi_history
        _rssi_smooth = sorted(_rssi_vals)[len(_rssi_vals) // 2] if _rssi_vals else _n02_rssi
        self._n02_rssi_ema = _rssi_smooth  # export for UI

        _rssi_zone = None
        _rssi_zone_conf = 0.0
        if _rssi_smooth > -90.0:
            # Fixed threshold: door raw ≈ -47...-49, center raw = -44 (stable)
            _thresh = -45.0
            _vote = "center" if _rssi_smooth > _thresh else "door"
            self._rssi_vote_history.append(_vote)
            if len(self._rssi_vote_history) > 7:
                self._rssi_vote_history = self._rssi_vote_history[-7:]
            # Majority vote: zone flips only if 5 of last 7 votes agree
            _votes = self._rssi_vote_history
            _n_center = sum(1 for v in _votes if v == "center")
            _n_door = len(_votes) - _n_center
            _prev_rz = getattr(self, '_last_rssi_zone', None)
            if _n_center >= 5:
                _rssi_zone = "center"
                _rssi_zone_conf = min(0.9, 0.5 + _n_center / len(_votes) * 0.4)
            elif _n_door >= 5:
                _rssi_zone = "door"
                _rssi_zone_conf = min(0.9, 0.5 + _n_door / len(_votes) * 0.4)
            elif _prev_rz in ("door", "center"):
                _rssi_zone = _prev_rz  # hold — not enough consensus to flip
                _rssi_zone_conf = 0.4
            else:
                _rssi_zone = _vote  # initial
                _rssi_zone_conf = 0.5
        self._last_rssi_zone = _rssi_zone

        if bin_pred == 0:
            zone = "empty"
            _zone_source = "binary_empty"
            _zone_conf = round(1.0 - p_occupied, 3)
        elif total_pps >= 10.0 and _v48_coord_available:
            # High PPS: V48 coords are reliable (trained at 20 PPS)
            _cy = self._coord_gbr_prev[1]
            if _cy < 2.0:
                zone = "door"
            elif _cy > 5.0:
                zone = "deep"
            else:
                zone = "center"
            _zone_source = "v48_coord_zone"
            _zone_conf = round(_zone3_result[1], 3) if _zone3_result else 0.6
        elif _rssi_zone is not None:
            # Low PPS: use RSSI-based zone (works at any PPS)
            zone = _rssi_zone
            _zone_source = "rssi_zone"
            _zone_conf = round(_rssi_zone_conf, 3)
        elif _zone3_result is not None:
            zone = _zone3_result[0]  # 'door', 'center', or 'deep'
            _zone_source = "zone3_classifier"
            _zone_conf = round(_zone3_result[1], 3)
        elif target_y < 1.5:
            zone = "door"
            _zone_source = "coordinate_fallback"
            _zone_conf = 0.5
        elif target_y > 5.0:
            zone = "deep"
            _zone_source = "coordinate_fallback"
            _zone_conf = 0.5
        else:
            zone = "center"
            _zone_source = "coordinate_fallback"
            _zone_conf = 0.5

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

        # ── V48 binary hysteresis: require N consecutive windows to switch ──
        if binary_label != self._v48_hysteresis_state:
            self._v48_hysteresis_count += 1
            if self._v48_hysteresis_count >= self._V48_HYSTERESIS_N:
                # Flip state
                self._v48_hysteresis_state = binary_label
                self._v48_hysteresis_count = 0
                logger.info("V48 hysteresis FLIP → %s (after %d consecutive)",
                            binary_label, self._V48_HYSTERESIS_N)
            else:
                # Hold previous state
                binary_label = self._v48_hysteresis_state
                binary_conf = max(binary_conf, 0.5)  # don't show low conf for held state
                # Also hold coords/zone from previous if reverting to empty
                if binary_label == "empty":
                    target_x, target_y = 0.0, 0.0
                    zone = self.current.get("target_zone", "center")
                    _zone_source = "hysteresis_hold"
                    _zone_conf = self.current.get("zone_confidence", 0.5)
        else:
            self._v48_hysteresis_count = 0

        # ── Truth-backed TVAR occupancy override (2026-04-03) ─────────────
        # The V48/V60 binary models rely on amp_mean which has overlapping
        # distributions between empty and occupied.  Truth-backed analysis
        # proved that tvar_median gives ZERO-OVERLAP separation:
        #   empty  max tvar_median = 2.26
        #   occupied min tvar_median = 4.36
        # Decision boundary at 3.0 (conservative).  F1 = 1.000 on truth
        # holdout with all three model families.
        _truth_tvar_override = False
        _truth_tvar_diag: dict[str, Any] = {}
        if feat is not None:
            _tvar_nodes = ["node01","node02","node03","node04","node05","node06","node07"]
            _node_tvars = [feat.get(f"{n}_tvar", 0.0) for n in _tvar_nodes]
            _valid_tvars = sorted([t for t in _node_tvars if t > 0])
            if len(_valid_tvars) >= 3:
                _tvar_median = _valid_tvars[len(_valid_tvars) // 2]
                _TVAR_OCCUPIED_THRESHOLD = 4.0
                _TVAR_EMPTY_CEILING = 2.0

                _truth_verdict = "occupied" if _tvar_median >= _TVAR_OCCUPIED_THRESHOLD else "empty"
                _truth_conf = min(1.0, 0.7 + abs(_tvar_median - _TVAR_OCCUPIED_THRESHOLD) * 0.06)

                if _truth_verdict == "occupied" and binary_label == "empty":
                    # V48/V60 says empty but TVAR clearly says occupied → override
                    logger.warning(
                        "TRUTH-TVAR override: %s→occupied (tvar_median=%.2f, threshold=%.1f, "
                        "original p_occ=%.3f, backend=%s)",
                        binary_label, _tvar_median, _TVAR_OCCUPIED_THRESHOLD,
                        p_occupied, self._active_binary_backend,
                    )
                    binary_label = "occupied"
                    bin_pred = 1
                    binary_conf = _truth_conf
                    p_occupied = _truth_conf
                    self._active_binary_backend = "truth_tvar_override"
                    _truth_tvar_override = True
                elif _truth_verdict == "empty" and _tvar_median <= _TVAR_EMPTY_CEILING and binary_label == "occupied":
                    # TVAR clearly empty but model says occupied → override to empty
                    logger.warning(
                        "TRUTH-TVAR override: %s→empty (tvar_median=%.2f, ceiling=%.1f, "
                        "original p_occ=%.3f, backend=%s)",
                        binary_label, _tvar_median, _TVAR_EMPTY_CEILING,
                        p_occupied, self._active_binary_backend,
                    )
                    binary_label = "empty"
                    bin_pred = 0
                    binary_conf = _truth_conf
                    p_occupied = 1.0 - _truth_conf
                    self._active_binary_backend = "truth_tvar_override"
                    _truth_tvar_override = True

                _truth_tvar_diag = {
                    "tvar_median": round(_tvar_median, 3),
                    "valid_nodes": len(_valid_tvars),
                    "override_fired": _truth_tvar_override,
                    "truth_verdict": _truth_verdict,
                    "truth_conf": round(_truth_conf, 3),
                    "node_tvars": {n: round(feat.get(f"{n}_tvar", 0.0), 3) for n in _tvar_nodes},
                }

        # If truth override fired, also fix zone (binary_empty → needs re-eval)
        if _truth_tvar_override and binary_label == "occupied" and zone == "empty":
            # Re-derive zone from RSSI or coordinates
            if _rssi_zone is not None:
                zone = _rssi_zone
                _zone_source = "rssi_zone_after_truth_override"
                _zone_conf = round(_rssi_zone_conf, 3)
            else:
                zone = "center"
                _zone_source = "truth_override_fallback"
                _zone_conf = 0.5
        elif _truth_tvar_override and binary_label == "empty":
            zone = "empty"
            _zone_source = "truth_tvar_empty_override"
            _zone_conf = round(_truth_conf, 3)

        # ── V57 multi-person person count prediction (2026-03-30) ─────────
        # Predict number of people (1 vs 2) using coordinate spread features
        v57_result = None
        if V57_ENABLED and self.v57_model is not None:
            try:
                # Use the same feature extraction as for other models
                logger.info("V57: X shape=%s, ndim=%d, dtype=%s", str(X.shape), X.ndim, X.dtype)
                v57_result = self.predict_person_count(X)  # Pass X directly, not flatten
                logger.info("V57 person count: %d (confidence=%.3f, source=%s)", 
                           v57_result.get('person_count', 0), 
                           v57_result.get('confidence', 0.0),
                           v57_result.get('source', 'unknown'))
            except Exception as e:
                logger.error("V57 prediction failed: %s", e)
                import traceback
                logger.debug("V57 traceback: %s", traceback.format_exc())
                v57_result = {'person_count': None, 'confidence': 0.0, 'source': 'v57_error', 'error': str(e)}

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
            "zone_confidence": _zone_conf,
            "zone_source": _zone_source,
            "zone_probabilities": _zone3_result[2] if _zone3_result is not None and len(_zone3_result) >= 3 else {},
            "nodes_active": active_nodes,
            "packets_in_window": pkt_count,
            "pps": round(total_pps, 1),
            "window_age_sec": round(time.time() - self._start_time - w_end, 1),
            "decision_model_version": self._active_model_version or self.current.get("model_version"),
            "decision_model_id": self._active_model_id or self.current.get("model_id"),
            "decision_model_backend": self._active_binary_backend or self.current.get("decision_model_backend"),
            "legacy_production_overrides_enabled": self._legacy_production_overrides_enabled(),
            "last_prediction_at": time.time(),
            "last_error": None,
            "last_error_traceback": None,
            "feature_status": "prediction_window_ok",
            "history": self._recent_predictions[-30:],
            # V57 multi-person detection
            "multi_person": {
                "person_count": v57_result.get('person_count') if v57_result else None,
                "confidence": round(v57_result.get('confidence', 0.0), 3) if v57_result else 0.0,
                "source": v57_result.get('source', 'unknown') if v57_result else 'v57_disabled',
                "class_probabilities": v57_result.get('class_probabilities', {}) if v57_result else {},
            },
            # Truth-backed TVAR override diagnostics
            "truth_tvar": _truth_tvar_diag,
            # Mesh link state
            "mesh": {
                "enabled": self._mesh_enabled,
                "peer_links": self._mesh.peer_link_count if self._mesh_enabled else 0,
                "total_links": self._mesh.link_count if self._mesh_enabled else 0,
                "spatial_variance": round(feat.get("mesh_spatial_variance", 0.0), 4) if feat else 0.0,
                "link_agreement": round(feat.get("mesh_link_agreement", 1.0), 3) if feat else 1.0,
                "max_link_delta": round(feat.get("mesh_max_link_delta", 0.0), 4) if feat else 0.0,
            },
        })
        self._sync_active_model_contract()

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
        self._last_feat_dict = dict(feat)  # save for zone inject API
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

        # ── Door/center live shadow path (prototype + temporal overlay only) ──
        try:
            prototype_result: dict[str, Any] | None = None
            live_door_result: dict[str, Any] | None = None
            if FEWSHOT_PROTOTYPE_SHADOW_ENABLED or FEWSHOT_TEMPORAL_OVERLAY_ENABLED:
                proto_shadow = self._ensure_fewshot_prototype_shadow_ready()
                if hasattr(proto_shadow, "predict"):
                    prototype_result = proto_shadow.predict(
                        feat,
                        active_nodes,
                        pkt_count=pkt_count,
                        window_t=w_end,
                    )
                    self._fewshot_prototype_shadow = prototype_result

            if LIVE_DOOR_SHADOW_ENABLED:
                live_door_shadow = self._ensure_live_door_shadow_ready()
                if hasattr(live_door_shadow, "predict"):
                    live_door_result = live_door_shadow.predict(
                        feat,
                        active_nodes,
                        pkt_count=pkt_count,
                        window_t=w_end,
                    )
                    self._live_door_shadow = live_door_result

            if FEWSHOT_TEMPORAL_OVERLAY_ENABLED:
                temporal_result = self._predict_fewshot_temporal_overlay(
                    feat,
                    active_nodes,
                    pkt_count=pkt_count,
                    window_t=w_end,
                    prototype_result=prototype_result,
                )
                self._fewshot_temporal_overlay_shadow = temporal_result

            if FEWSHOT_PROTOTYPE_SHADOW_ENABLED or FEWSHOT_TEMPORAL_OVERLAY_ENABLED:
                self._door_center_candidate_shadow = self._build_door_center_candidate_shadow()
                if (
                    isinstance(self._door_center_candidate_shadow, dict)
                    and self._door_center_candidate_shadow.get("status") == "shadow_live"
                ):
                    try:
                        shadow_path = PROJECT / "temp" / "door_center_candidate_shadow_telemetry.ndjson"
                        shadow_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(shadow_path, "a") as sf:
                            sf.write(json.dumps({
                                "ts": time.time(),
                                "window_t": w_end,
                                "v20_binary": binary_label,
                                "v20_zone": zone,
                                "prototype_zone": (self._fewshot_prototype_shadow or {}).get("zone"),
                                "prototype_zone_raw": (self._fewshot_prototype_shadow or {}).get("zone_raw"),
                                "prototype_confidence": (self._fewshot_prototype_shadow or {}).get("confidence"),
                                "temporal_zone": (self._fewshot_temporal_overlay_shadow or {}).get("zone"),
                                "temporal_threshold_zone": (self._fewshot_temporal_overlay_shadow or {}).get("threshold_zone"),
                                "directional_score": (self._fewshot_temporal_overlay_shadow or {}).get("directional_score"),
                                "candidate_zone": self._door_center_candidate_shadow.get("candidate_zone"),
                                "candidate_agreement": self._door_center_candidate_shadow.get("agreement"),
                                "candidate_confidence": self._door_center_candidate_shadow.get("confidence"),
                            }) + "\n")
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Door/center live shadow path skipped: %s", e)

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
        legacy_production_overrides_enabled = self._legacy_production_overrides_enabled()

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

                # ── Runtime calibration override (if calibrated this session) ──
                _cal_sh = self._zone_calibration_shadow
                _cal_status = _cal_sh.get("calibration_status") if _cal_sh else None
                logger.debug("CAL_OVERRIDE check: status=%s zone=%s smoothed=%s",
                             _cal_status,
                             _cal_sh.get("zone") if _cal_sh else None,
                             _cal_sh.get("smoothing_meta", {}).get("smoothed_zone") if _cal_sh else None)
                if _cal_sh and _cal_status not in ("not_calibrated", None, ""):
                    cal_zone = _cal_sh.get("zone")
                    sm = _cal_sh.get("smoothing_meta", {})
                    # Prefer smoothed zone if ready, else raw
                    if sm.get("ready") and sm.get("smoothed_zone"):
                        prod_zone = sm["smoothed_zone"]
                        prod_zone_probs = _cal_sh.get("distances", {})
                        prod_zone_model = "runtime_calibration_smoothed"
                        logger.info("CAL_OVERRIDE applied: smoothed=%s", prod_zone)
                    elif cal_zone and cal_zone != "unknown":
                        prod_zone = cal_zone
                        prod_zone_probs = _cal_sh.get("distances", {})
                        prod_zone_model = "runtime_calibration"
                        logger.info("CAL_OVERRIDE applied: raw=%s", prod_zone)

                if legacy_production_overrides_enabled:
                    self.current.update({
                        "binary": v20_binary,
                        "binary_confidence": round(v20_binary_conf, 3),
                        "coarse": v20_coarse,
                        "decision_model_version": "v21d",
                        "decision_model_id": "v21d_candidate.pkl",
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
                if legacy_production_overrides_enabled:
                    # V40 production override
                    self.current.update({
                        "binary": v40_binary,
                        "binary_confidence": round(v40_conf if v40_binary == "occupied" else 1.0 - v40_conf, 3),
                        "decision_model_version": v26_shadow["track"],
                        "decision_model_id": v26_shadow["candidate_name"],
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

        # ── V45 production override (2026-03-28) ─────────────────────
        # V45: trained on current 7-node setup (PPS ~3.5, WINDOW_SEC=2.0).
        # 288 occupied (11 markers) + 136 empty. CV macro_f1=0.981.
        # Fixes V44 domain shift (V44 trained on 30 PPS / 4 nodes).
        v43_shadow = None
        try:
            v43_shadow = self._shadow_predict_v43(
                feat, w_end, coarse_label, binary_label, binary_conf,
            )
            if v43_shadow is not None:
                v45_binary = v43_shadow["binary"]
                v45_conf = float(v43_shadow.get("binary_conf", 0))
                v45_coarse = v43_shadow["predicted_class"].lower()
                if legacy_production_overrides_enabled:
                    self.current.update({
                        "binary": v45_binary,
                        "binary_confidence": round(v45_conf, 3),
                        "coarse": v45_coarse,
                        "decision_model_version": "v47",
                        "decision_model_id": "v47_binary_newfw.pkl",
                    })
                    binary_label = v45_binary
                    coarse_label = v45_coarse
                    binary_conf = v45_conf
                    logger.debug("V45 production override: binary=%s coarse=%s conf=%.3f",
                                 v45_binary, v45_coarse, v45_conf)
        except Exception as e:
            logger.debug("V44 shadow skipped: %s", e)

        # ── Final zone override from runtime calibration ──────────────
        try:
            _cal = self._zone_calibration_shadow
            if _cal and _cal.get("calibration_status") not in ("not_calibrated", None, ""):
                sm = _cal.get("smoothing_meta", {})
                if sm.get("ready") and sm.get("smoothed_zone"):
                    self.current["zone"] = sm["smoothed_zone"]
                    self.current["target_zone"] = sm["smoothed_zone"]
                    self.current["zone_probabilities"] = _cal.get("distances", {})
                    self.current["zone_model"] = "runtime_calibration_smoothed"
                elif _cal.get("zone") and _cal["zone"] != "unknown":
                    self.current["zone"] = _cal["zone"]
                    self.current["target_zone"] = _cal["zone"]
                    self.current["zone_probabilities"] = _cal.get("distances", {})
                    self.current["zone_model"] = "runtime_calibration"
        except Exception:
            pass

        # ── Zone-probability-based coordinate estimation ──────────────
        # Replaces noisy V8 shadow coords with smooth zone-centroid-weighted
        # coordinates.  Preserves V8 shadow in separate fields for comparison.
        try:
            import math as _math

            def _coord_pair_valid(pair: Any) -> bool:
                return (
                    isinstance(pair, (tuple, list))
                    and len(pair) >= 2
                    and isinstance(pair[0], (int, float))
                    and isinstance(pair[1], (int, float))
                )

            # Authoritative garage layout (3×7m, 5 zones, 11 markers):
            #   door:   x=2-3, y=0-2,   cx=2.5, cy=1.0
            #   center: x=0-3, y=3-5.5, cx=1.5, cy=4.25
            #   deep:   x=0-3, y=5.5-7, cx=1.5, cy=6.25  (cluttered, unused)
            #   zone3:  x=2-3, y=0-3,   cx=2.5, cy=1.5   (passage)
            #   zone4:  x=1-2, y=0-1,   cx=1.5, cy=0.5   (entrance)
            # Primary walkable: door ↔ center (via zone3 passage)
            ZONE_CENTROIDS = {
                "door":   (2.50, 1.00),
                "center": (1.50, 4.25),
            }

            # Save V8 shadow coords for diagnostic comparison
            self.current["v8_target_x"] = self.current.get("target_x", 0.0)
            self.current["v8_target_y"] = self.current.get("target_y", 0.0)

            cur_binary = self.current.get("binary", "unknown")
            if cur_binary == "empty":
                # Empty room: no person, zero out coordinates
                self.current["target_x"] = 0.0
                self.current["target_y"] = 0.0
                self.current["coordinate_source"] = "empty_zeroed"
                self._zone_coord_prev = (0.0, 0.0)
                self._coord_gbr_prev = (0.0, 0.0)
            elif _coord_pair_valid(getattr(self, '_v48_last_coord', None)):
                # ── V48 EPOCH3 COORDINATE MODEL (PRIMARY) ─────────────
                new_x, new_y = self._v48_last_coord
                prev_x, prev_y = self._coord_gbr_prev
                if prev_x == 0.0 and prev_y == 0.0:
                    smooth_x, smooth_y = new_x, new_y
                else:
                    alpha = 0.5
                    smooth_x = prev_x + alpha * (new_x - prev_x)
                    smooth_y = prev_y + alpha * (new_y - prev_y)
                self._coord_gbr_prev = (smooth_x, smooth_y)
                self._zone_coord_prev = (smooth_x, smooth_y)
                self.current["target_x"] = round(smooth_x, 2)
                self.current["target_y"] = round(smooth_y, 2)
                self.current["coordinate_source"] = "v48_epoch3_gbr"
                self._v48_last_coord = None  # consume once
            elif getattr(self, '_v48_last_coord', None) is not None:
                self._v48_last_coord = None
            elif _coord_pair_valid(self._coord_gbr_prev) and self._coord_gbr_prev != (0.0, 0.0):
                # ── HOLD: keep last good V48 coord when skipped (too few nodes) ──
                self.current["target_x"] = round(self._coord_gbr_prev[0], 2)
                self.current["target_y"] = round(self._coord_gbr_prev[1], 2)
                self.current["coordinate_source"] = "v48_epoch3_gbr_hold"
            else:
                # ── LEGACY: Marker-GBR coordinate model ───────────────
                gbr_result = self._predict_coord_gbr(self._last_feat_dict)
                if gbr_result is not None:
                    new_x, new_y = gbr_result
                    # EMA smoothing (alpha=0.3)
                    prev_x, prev_y = self._coord_gbr_prev
                    if not _coord_pair_valid((prev_x, prev_y)) or (prev_x == 0.0 and prev_y == 0.0):
                        smooth_x, smooth_y = new_x, new_y
                    else:
                        alpha = 0.3
                        smooth_x = prev_x + alpha * (new_x - prev_x)
                        smooth_y = prev_y + alpha * (new_y - prev_y)
                    self._coord_gbr_prev = (smooth_x, smooth_y)
                    self._zone_coord_prev = (smooth_x, smooth_y)
                    self.current["target_x"] = round(smooth_x, 2)
                    self.current["target_y"] = round(smooth_y, 2)
                    self.current["coordinate_source"] = "marker_gbr_v1"
                else:
                    # ── FALLBACK: zone_centroid_weighted ───────────────
                    _cal = self._zone_calibration_shadow
                    cal_active = (
                        _cal
                        and _cal.get("calibration_status") not in ("not_calibrated", None, "")
                    )

                    if cal_active:
                        distances = _cal.get("distances", {})
                        if distances:
                            weights = {}
                            for zone_name, dist in distances.items():
                                if zone_name in ZONE_CENTROIDS and isinstance(dist, (int, float)) and dist >= 0:
                                    weights[zone_name] = 1.0 / (dist + 0.1)

                            if weights:
                                total_w = sum(weights.values())
                                new_x = sum(w * ZONE_CENTROIDS[z][0] for z, w in weights.items()) / total_w
                                new_y = sum(w * ZONE_CENTROIDS[z][1] for z, w in weights.items()) / total_w

                                prev_x, prev_y = self._zone_coord_prev
                                if not _coord_pair_valid((prev_x, prev_y)) or (prev_x == 0.0 and prev_y == 0.0):
                                    smooth_x, smooth_y = new_x, new_y
                                else:
                                    alpha = 0.3
                                    smooth_x = prev_x + alpha * (new_x - prev_x)
                                    smooth_y = prev_y + alpha * (new_y - prev_y)

                                self._zone_coord_prev = (smooth_x, smooth_y)
                                self.current["target_x"] = round(smooth_x, 2)
                                self.current["target_y"] = round(smooth_y, 2)
                                self.current["coordinate_source"] = "zone_centroid_weighted"
                            else:
                                self.current["coordinate_source"] = "v8_shadow_fallback"
                        else:
                            self.current["coordinate_source"] = "v8_shadow_fallback"
                    else:
                        raw_x = self.current.get("target_x", 0.0)
                        raw_y = self.current.get("target_y", 0.0)
                        prev_x, prev_y = self._zone_coord_prev

                        if prev_x != 0.0 or prev_y != 0.0:
                            dx = raw_x - prev_x
                            dy = raw_y - prev_y
                            step = _math.hypot(dx, dy)
                            max_step = 0.3
                            if step > max_step and step > 0:
                                scale = max_step / step
                                raw_x = prev_x + dx * scale
                                raw_y = prev_y + dy * scale
                            self.current["target_x"] = round(raw_x, 2)
                            self.current["target_y"] = round(raw_y, 2)

                        self._zone_coord_prev = (
                            self.current.get("target_x", 0.0),
                            self.current.get("target_y", 0.0),
                        )
                        self.current["coordinate_source"] = "v8_shadow_clamped"
        except Exception:
            pass  # coordinate override must never crash prediction

        try:
            self._apply_fresh_empty_baseline_rescue(
                t_start=w_start,
                t_end=w_end,
                active_nodes=active_nodes,
                motion_state=self.current.get("motion_state", motion_state),
            )
        except Exception as e:
            self.current["empty_rescue_guard"] = {
                "eligible": False,
                "applied": False,
                "error": str(e),
            }
            logger.debug("Fresh empty baseline rescue skipped: %s", e)

        try:
            self._apply_outside_door_leakage_guard(
                active_nodes=active_nodes,
                motion_state=self.current.get("motion_state", motion_state),
            )
        except Exception as e:
            logger.debug("Outside-door leakage guard skipped: %s", e)

        provisional_binary = self.current.get("binary", binary_label)
        provisional_binary_conf = round(float(self.current.get("binary_confidence", binary_conf)), 3)
        provisional_coarse = self.current.get("coarse", coarse_label)
        final_motion_state = self.current.get("motion_state", motion_state)
        final_motion_conf = round(float(self.current.get("motion_confidence", motion_conf)), 3)

        try:
            self._shadow_predict_offline_regime(
                w_start,
                w_end,
                window_sec,
                provisional_binary,
                provisional_coarse,
            )
        except Exception as e:
            logger.debug("Offline regime shadow skipped: %s", e)

        if _is_v48:
            try:
                self._shadow_predict_empty_subregime(
                    feat,
                    w_end,
                    provisional_binary,
                    provisional_binary_conf,
                )
            except Exception as e:
                logger.debug("Empty subregime shadow skipped: %s", e)

            try:
                self._apply_empty_subregime_rescue(
                    active_nodes=active_nodes,
                    motion_state=self.current.get("motion_state", motion_state),
                )
            except Exception as e:
                logger.debug("Empty subregime rescue skipped: %s", e)

        try:
            self._apply_v8_empty_priority_guard(
                active_nodes=active_nodes,
                motion_state=self.current.get("motion_state", motion_state),
            )
        except Exception as e:
            logger.debug("V8 empty priority guard skipped: %s", e)

        truth_tvar_diag_runtime = (
            self.current.get("truth_tvar")
            if isinstance(self.current.get("truth_tvar"), dict)
            else {}
        )
        v8_guard_runtime = (
            self.current.get("v8_empty_priority_guard")
            if isinstance(self.current.get("v8_empty_priority_guard"), dict)
            else {}
        )
        if (
            truth_tvar_diag_runtime
            and str(truth_tvar_diag_runtime.get("truth_verdict", "") or "").lower() == "occupied"
            and str(self.current.get("binary", "") or "").lower() == "empty"
            and str(self.current.get("target_zone", "") or "").lower() == "empty"
            and str(self.current.get("motion_state", "") or "").upper() == "NO_MOTION"
            and bool(v8_guard_runtime.get("applied"))
        ):
            reviewed_truth_tvar = dict(truth_tvar_diag_runtime)
            reviewed_truth_tvar.setdefault(
                "raw_truth_verdict",
                truth_tvar_diag_runtime.get("truth_verdict"),
            )
            reviewed_truth_tvar.setdefault(
                "raw_truth_conf",
                truth_tvar_diag_runtime.get("truth_conf"),
            )
            reviewed_truth_tvar["truth_verdict"] = "empty"
            reviewed_truth_tvar["truth_conf"] = round(
                max(
                    float(v8_guard_runtime.get("v8_confidence", 0.0) or 0.0),
                    float(truth_tvar_diag_runtime.get("truth_conf", 0.0) or 0.0),
                ),
                3,
            )
            reviewed_truth_tvar["runtime_review_applied"] = True
            reviewed_truth_tvar["runtime_review_reason"] = "v8_empty_guard_no_motion"
            reviewed_truth_tvar["runtime_review_backend"] = self.current.get("decision_model_backend")
            self.current["truth_tvar"] = reviewed_truth_tvar

        final_target_x = round(float(self.current.get("target_x", target_x)), 2)
        final_target_y = round(float(self.current.get("target_y", target_y)), 2)
        final_zone = self.current.get("target_zone", zone)
        final_zone_source = self.current.get("zone_source", _zone_source)
        final_zone_conf = self.current.get("zone_confidence", _zone_conf)

        final_coordinate_source = self.current.get("coordinate_source")
        final_binary = self.current.get("binary", binary_label)

        final_binary_conf = round(float(self.current.get("binary_confidence", binary_conf)), 3)
        final_coarse = self.current.get("coarse", coarse_label)
        final_coarse_conf = round(float(self.current.get("coarse_confidence", coarse_conf)), 3)

        if _is_v48:
            try:
                self._shadow_predict_deep_right(
                    feat,
                    w_end,
                    final_binary,
                    final_binary_conf,
                    str(final_zone or "unknown"),
                    float(final_target_x),
                    float(final_target_y),
                )
            except Exception as e:
                logger.debug("Deep-right shadow skipped: %s", e)

            try:
                self._apply_deep_right_guidance(
                    active_nodes=active_nodes,
                    packets_per_second=total_pps,
                )
            except Exception as e:
                logger.debug("Deep-right guidance skipped: %s", e)

            final_target_x = round(float(self.current.get("target_x", final_target_x)), 2)
            final_target_y = round(float(self.current.get("target_y", final_target_y)), 2)
            final_zone = self.current.get("target_zone", final_zone)
            final_zone_source = self.current.get("zone_source", final_zone_source)
            final_zone_conf = self.current.get("zone_confidence", final_zone_conf)
            final_coordinate_source = self.current.get("coordinate_source", final_coordinate_source)

            # ── Final zone/coord override (LAST — overrides deep_right etc.) ──
            _coord_prev = getattr(self, '_coord_gbr_prev', (0.0, 0.0))
            if final_binary != "empty" and _coord_pair_valid(_coord_prev) and _coord_prev != (0.0, 0.0):
                # Restore V48 GBR coordinates (undo deep_right_guidance override)
                final_target_x = round(_coord_prev[0], 2)
                final_target_y = round(_coord_prev[1], 2)
                self.current["target_x"] = final_target_x
                self.current["target_y"] = final_target_y
                self.current["coordinate_source"] = "v48_epoch3_gbr"

                # Zone: RSSI-based at low PPS (V48 coords unreliable), coord-based at high PPS
                _rssi_z = getattr(self, '_last_rssi_zone', None)
                if total_pps < 10.0 and _rssi_z is not None:
                    final_zone = _rssi_z
                    final_zone_source = "rssi_zone_final"
                else:
                    final_zone = "door" if _coord_prev[1] < 2.0 else ("deep" if _coord_prev[1] > 5.0 else "center")
                    final_zone_source = "v48_coord_final"
                self.current["target_zone"] = final_zone
                self.current["zone_source"] = final_zone_source

            candidate_shadow = (
                self._door_center_candidate_shadow
                if isinstance(self._door_center_candidate_shadow, dict)
                else {}
            )
            guard_diag = self.current.get("v8_empty_priority_guard") or {}
            stable_candidate_zone = str(
                candidate_shadow.get("stable_zone")
                or candidate_shadow.get("candidate_zone")
                or candidate_shadow.get("zone")
                or ""
            )
            raw_candidate_zone = str(candidate_shadow.get("raw_candidate_zone") or "")
            candidate_agreement = str(candidate_shadow.get("agreement") or "")
            candidate_conf = candidate_shadow.get("confidence")
            try:
                candidate_conf_float = float(candidate_conf) if candidate_conf is not None else None
            except (TypeError, ValueError):
                candidate_conf_float = None
            fewshot_zone = str(candidate_shadow.get("fewshot_zone") or "")
            doorway_override_promote = bool(
                final_zone == "door"
                and final_zone_source == "v48_coord_final"
                and fewshot_zone == "door_passage"
                and bool(candidate_shadow.get("door_gate_support"))
                and bool(candidate_shadow.get("door_signature_active"))
                and int(candidate_shadow.get("door_signature_consecutive") or 0) >= 1
            )
            fewshot_door_promote = bool(
                stable_candidate_zone == "center"
                and fewshot_zone == "door_passage"
                and bool(candidate_shadow.get("door_gate_support"))
                and bool(candidate_shadow.get("door_signature_active"))
                and (
                    float(candidate_shadow.get("fewshot_confidence") or 0.0) >= 0.90
                )
                and active_nodes >= 7
                and final_binary != "empty"
            )
            promote_center = (
                stable_candidate_zone == "center"
                and candidate_agreement == "full"
                and raw_candidate_zone == "center"
                and str(candidate_shadow.get("prototype_zone") or "") == "center"
                and str(candidate_shadow.get("temporal_zone") or "") == "center"
                and str(candidate_shadow.get("threshold_zone") or "") == "center"
                and not doorway_override_promote
                and not fewshot_door_promote
            )
            promote_door = (
                (
                    stable_candidate_zone == "door_passage"
                    and candidate_agreement in {"full", "fewshot_door_gate", "fewshot_runtime_override", "door_raw_assist", "door_raw_hold"}
                    and (fewshot_zone == "door_passage" or candidate_agreement in {"door_raw_assist", "door_raw_hold"})
                    and (candidate_conf_float is None or candidate_conf_float >= 0.82)
                )
                or doorway_override_promote
                or fewshot_door_promote
            )
            if (
                not SAFE_BINARY_ONLY_ZONE_MODE
                and (
                active_nodes >= 7
                and not bool(guard_diag.get("applied"))
                and (promote_center or promote_door)
                )
            ):
                promoted_zone = "door" if stable_candidate_zone == "door_passage" else "center"
                promoted_coords = {
                    "door": (2.50, 1.00),
                    "center": (1.50, 4.25),
                }.get(promoted_zone)
                final_zone = promoted_zone
                final_zone_source = "door_center_candidate_shadow"
                if candidate_conf_float is not None:
                    final_zone_conf = round(candidate_conf_float, 4)
                self.current["target_zone"] = final_zone
                self.current["zone_source"] = final_zone_source
                if candidate_conf_float is not None:
                    self.current["zone_confidence"] = final_zone_conf
                if promoted_coords is not None:
                    final_target_x = round(float(promoted_coords[0]), 2)
                    final_target_y = round(float(promoted_coords[1]), 2)
                    self.current["target_x"] = final_target_x
                    self.current["target_y"] = final_target_y
                    final_coordinate_source = "door_center_candidate_shadow"
                    self.current["coordinate_source"] = final_coordinate_source
                if final_binary == "empty":
                    final_binary = "occupied"
                    final_binary_conf = max(final_binary_conf, 0.85)
                    self.current["binary"] = final_binary
                    self.current["binary_confidence"] = round(final_binary_conf, 3)
                    if str(final_coarse or "") == "empty":
                        final_coarse = "static"
                        final_coarse_conf = max(final_coarse_conf, 0.85)
                        self.current["coarse"] = final_coarse
                        self.current["coarse_confidence"] = round(final_coarse_conf, 3)
                    self.current["decision_model_backend"] = "v48_candidate_zone_promote"

            if SAFE_BINARY_ONLY_ZONE_MODE:
                self.current["zone_overlay_mode"] = "diagnostic_only"
                self.current["experimental_zone_mode"] = "safe_binary_only"
                self.current["coordinate_valid"] = False
                self.current["coordinate_reliability"] = "binary_safe_only"
                if final_binary == "empty":
                    final_zone = "empty"
                    final_zone_source = "binary_safe_only"
                    final_target_x = 0.0
                    final_target_y = 0.0
                    final_coordinate_source = "binary_safe_only"
                else:
                    final_zone = "occupied"
                    final_zone_source = "binary_safe_only"
                    final_target_x = None
                    final_target_y = None
                    final_coordinate_source = "binary_safe_only"
                self.current["target_zone"] = final_zone
                self.current["zone_source"] = final_zone_source
                self.current["target_x"] = final_target_x
                self.current["target_y"] = final_target_y
                self.current["coordinate_source"] = final_coordinate_source

        if self._recent_predictions and self._recent_predictions[-1].get("t") == w_end:
            self._recent_predictions[-1].update({
                "motion_state": final_motion_state,
                "motion_confidence": final_motion_conf,
                "binary": final_binary,
                "binary_confidence": final_binary_conf,
                "coarse": final_coarse,
                "coarse_confidence": final_coarse_conf,
                "target_x": final_target_x,
                "target_y": final_target_y,
                "zone": final_zone,
                "zone_source": final_zone_source,
                "zone_confidence": final_zone_conf,
                "coordinate_source": final_coordinate_source,
            })
            self.current["history"] = self._recent_predictions[-30:]

        # Telemetry: append finalized runtime surface for offline failure analysis.
        try:
            telemetry_path = PROJECT / "temp" / "runtime_telemetry.ndjson"
            with open(telemetry_path, "a") as tf:
                now_m = time.monotonic()
                damped_ips = [ip for ip in NODE_IPS if now_m < self._node_warmup_until.get(ip, 0)]
                outside_guard_diag = self.current.get("outside_door_guard") or {}
                v8_shadow_diag = self._v8_shadow or {}
                v43_shadow_diag = self._v43_shadow or {}
                v29_zone_diag = self._v29_cnn_shadow or {}
                v29_zone_probs = v29_zone_diag.get("probabilities") or {}
                offline_regime_diag = self._offline_regime_shadow or {}
                offline_empty_diag = offline_regime_diag.get("empty_vs_occupied") or {}
                empty_subregime_diag = self._empty_subregime_shadow or {}
                empty_subregime_rescue_diag = self.current.get("empty_subregime_rescue") or {}
                coord_stab_diag = self.current.get("coord_stabilization") or {}
                shallow_coord_diag = self._shallow_coord_shadow or {}
                primary_feat_diag = self._last_feat_dict or {}
                legacy_result_diag = self._get_legacy_bridge_window_result(w_start, w_end)
                legacy_feat_diag = legacy_result_diag[0] if legacy_result_diag is not None else {}
                legacy_packet_count_diag = int(legacy_result_diag[2]) if legacy_result_diag is not None else 0
                telemetry_entry = {
                    "ts": time.time(),
                    "window_t": w_end,
                    "motion_state": final_motion_state,
                    "motion_conf": final_motion_conf,
                    "binary": final_binary,
                    "binary_conf": final_binary_conf,
                    "coarse": final_coarse,
                    "coarse_conf": final_coarse_conf,
                    "nodes": active_nodes,
                    "pps": round(total_pps, 1),
                    "zone": final_zone,
                    "zone_source": final_zone_source,
                    "zone_confidence": final_zone_conf,
                    "target_x": final_target_x,
                    "target_y": final_target_y,
                    "coordinate_source": final_coordinate_source,
                    "decision_model_backend": self.current.get("decision_model_backend"),
                    "outside_door_guard": outside_guard_diag or None,
                    "outside_door_guard_enabled": bool(outside_guard_diag.get("enabled", False)),
                    "outside_door_guard_eligible": bool(outside_guard_diag.get("eligible", False)),
                    "outside_door_guard_would_apply": bool(outside_guard_diag.get("would_apply", False)),
                    "outside_door_guard_applied": bool(outside_guard_diag.get("applied", False)),
                    "outside_door_guard_consecutive": int(outside_guard_diag.get("consecutive", 0) or 0),
                    "outside_door_guard_required": int(outside_guard_diag.get("required_consecutive", 0) or 0),
                    "outside_door_guard_promote_enabled": bool(outside_guard_diag.get("promote_enabled", False)),
                    "v8_shadow_binary": v8_shadow_diag.get("binary"),
                    "v8_shadow_binary_proba": v8_shadow_diag.get("binary_proba"),
                    "v43_shadow_binary": v43_shadow_diag.get("binary"),
                    "v43_shadow_binary_conf": v43_shadow_diag.get("binary_conf"),
                    "v43_shadow_predicted_class": v43_shadow_diag.get("predicted_class"),
                    "v29_cnn_zone_shadow": v29_zone_diag.get("zone"),
                    "v29_cnn_door_proba": v29_zone_probs.get("door"),
                    "offline_regime_empty_binary": offline_empty_diag.get("predicted_class"),
                    "offline_regime_empty_conf": offline_empty_diag.get("confidence"),
                    "empty_subregime_predicted_class": empty_subregime_diag.get("predicted_class"),
                    "empty_subregime_knn_class": empty_subregime_diag.get("knn_predicted_class"),
                    "empty_subregime_empty_like_ratio": empty_subregime_diag.get("empty_like_ratio"),
                    "empty_subregime_diag_ratio": empty_subregime_diag.get("diag_empty_ratio"),
                    "empty_subregime_recommended_action": empty_subregime_diag.get("recommended_action"),
                    "empty_subregime_rescue_eligible": empty_subregime_rescue_diag.get("eligible"),
                    "empty_subregime_rescue_applied": empty_subregime_rescue_diag.get("applied"),
                    "empty_subregime_rescue_consecutive": empty_subregime_rescue_diag.get("consecutive"),
                    "shallow_coord_shadow_x": shallow_coord_diag.get("target_x"),
                    "shallow_coord_shadow_y": shallow_coord_diag.get("target_y"),
                    "coord_stabilization_stable_x": coord_stab_diag.get("stable_x"),
                    "coord_stabilization_stable_y": coord_stab_diag.get("stable_y"),
                    "coord_stabilization_alpha_used": coord_stab_diag.get("alpha_used"),
                    "primary_amp_mean_global": primary_feat_diag.get("amp_mean_global"),
                    "primary_amp_std_global": primary_feat_diag.get("amp_std_global"),
                    "primary_tvar_mean": primary_feat_diag.get("tvar_mean"),
                    "primary_tvar_max": primary_feat_diag.get("tvar_max"),
                    "primary_total_pkt_count": primary_feat_diag.get("total_pkt_count"),
                    "legacy_packet_count": legacy_packet_count_diag,
                    "legacy_x_baseline_amp_dev_max": legacy_feat_diag.get("x_baseline_amp_dev_max"),
                    "legacy_x_baseline_sc_var_dev_max": legacy_feat_diag.get("x_baseline_sc_var_dev_max"),
                    "legacy_agg_mean": legacy_feat_diag.get("agg_mean"),
                    "legacy_agg_std": legacy_feat_diag.get("agg_std"),
                    "legacy_agg_pps": legacy_feat_diag.get("agg_pps"),
                    "legacy_n2_sc_var_lo": legacy_feat_diag.get("n2_sc_var_lo"),
                    "legacy_n3_sc_var_lo": legacy_feat_diag.get("n3_sc_var_lo"),
                    "legacy_n3_tvar_lo": legacy_feat_diag.get("n3_tvar_lo"),
                    "legacy_n6_tvar_lo": legacy_feat_diag.get("n6_tvar_lo"),
                    "legacy_n6_tvar_hi": legacy_feat_diag.get("n6_tvar_hi"),
                    "warmup_damped": damped_ips if damped_ips else None,
                    "v60_mesh": v60_diag if v60_override else None,
                    "node_health_guard": node_health_diag if node_health_override else None,
                    "sc_var_noise_gate": sc_var_noise_diag if sc_var_noise_override else None,
                    "phase_noise_gate": phase_noise_diag if phase_noise_override else None,
                    "amp_drift_gate": amp_drift_diag if amp_drift_override else None,
                    "dead_sc_gate": dead_sc_diag if dead_sc_override else None,
                }
                tf.write(json.dumps(telemetry_entry) + "\n")
        except Exception:
            pass  # telemetry must never crash prediction

        # ── Coordinate stabilization (shadow-only) ───────────────────
        try:
            from .coord_stabilization_service import coord_stabilization_service
            stabilized = coord_stabilization_service.process(
                raw_x=final_target_x,
                raw_y=final_target_y,
                motion_state=final_motion_state,
                zone=final_zone,
                binary=final_binary,
                window_t=w_end,
            )
            self.current["coord_stabilization"] = stabilized
        except Exception as e:
            logger.debug("Coord stabilization skipped: %s", e)

        # Prune old packets
        cutoff = now - MAX_BUFFER_SEC
        for ip in list(self._packets.keys()):
            self._packets[ip] = [(t, r, a, p) for t, r, a, p in self._packets[ip] if t > cutoff]

        # Prune mesh link buffers
        if self._mesh_enabled:
            self._mesh.prune(now)

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

        ip = resolve_ip(addr[0])
        now_mono = time.monotonic()
        self._node_last_seen[ip] = now_mono
        node_name = msg.get("node", ip)
        logger.debug("Keepalive from %s (%s)", node_name, ip)
        return True

    def _handle_raw_packet(self, data: bytes, addr: tuple):
        """Process one incoming raw UDP CSI packet from ESP32 node."""
        ip = resolve_ip(addr[0])

        probe_count = getattr(self, "_udp_probe_count", 0)
        if probe_count < 8:
            prefix = data[:24]
            print(
                f"[UDP-PROBE] ip={ip} len={len(data)} core={ip in NODE_IPS} "
                f"csv={data.startswith(b'CSI_DATA,')} json={data[:1] == b'{'} "
                f"prefix={prefix!r}",
                file=sys.stderr,
                flush=True,
            )
            self._udp_probe_count = probe_count + 1

        # Detect keepalive packets before any CSI processing
        if self._handle_keepalive(data, addr):
            return

        # Compatibility path: current esp32s3_csi_capture firmware may emit
        # CSV CSI_DATA packets on the legacy main UDP port instead of UDP_PORT_CSV.
        # In that case route the datagram through the CSV parser rather than
        # treating it as raw binary CSI.
        if data.startswith(b"CSI_DATA,"):
            self._handle_csv_packet(data, addr)
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

        # ── Feed router link to mesh manager (for unified link tracking) ──
        if self._mesh_enabled:
            receiver_node = self._V48_NODE_NAMES.get(ip, ip)
            if receiver_node.startswith("node"):
                receiver_short = "n" + receiver_node[4:]
            else:
                receiver_short = receiver_node
            link_id = MeshLinkManager.make_link_id(receiver_short, "router")
            self._mesh.ingest(
                link_id=link_id,
                receiver_node=receiver_short,
                source_node="router",
                link_type="router",
                t_sec=t_sec,
                rssi=float(rssi),
                amplitude=amp,
                phase=phase,
            )

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
        """Parse raw binary CSI payload (not base64, direct bytes). Full-resolution.

        Supports V1 (magic=0xC5110001, 20-byte header) and V2 (magic=0xC5110002,
        24-byte header with flags/phase_offset fields) firmware packet formats.

        Phase Sanitization по CMU arXiv:2301.00250 (Section 3.1) применяется
        к вектору фазы каждого входящего пакета: медианный фильтр по субнесущим
        + удаление hardware phase bias (mean removal).
        Полный multi-packet unwrap + linear trend removal применяется позднее
        в feature extractor (_extract_v48_features) на окне пакетов.
        """
        import struct as _struct
        if len(data) < 4:
            return None, None, None

        magic = _struct.unpack_from('<I', data, 0)[0]
        if magic == CSI_MAGIC_V2:
            # V2 format: 24-byte header
            # byte[20] = flags (bit0 = has_phase)
            # bytes[21-22] = phase_offset (uint16, offset from header end to phase data)
            # byte[23] = reserved
            header_size = CSI_HEADER_SIZE_V2
            if len(data) < header_size + 40:
                return None, None, None
            flags = data[20]
            has_hw_phase = bool(flags & 0x01)
            phase_offset_field = _struct.unpack_from('<H', data, 21)[0]
            iq_end = header_size + phase_offset_field if has_hw_phase else len(data)
            iq = data[header_size:iq_end][:256]
        elif magic == CSI_MAGIC_V1:
            # V1 format: 20-byte header, no dedicated phase data block
            header_size = CSI_HEADER_SIZE_V1
            if len(data) < header_size + 40:
                return None, None, None
            iq = data[header_size : header_size + 256]
        else:
            # Unknown magic — fall back to legacy behaviour (treat as V1)
            header_size = CSI_HEADER_SIZE_V1
            if len(data) < header_size + 40:
                return None, None, None
            iq = data[header_size : header_size + 256]

        n = len(iq) // 2
        if n < 40:
            return None, None, None
        arr = np.frombuffer(iq[: n * 2], dtype=np.int8).reshape(-1, 2)
        i_v = arr[:, 0].astype(np.float32)
        q_v = arr[:, 1].astype(np.float32)
        amp = np.sqrt(i_v**2 + q_v**2)
        phase = np.arctan2(q_v, i_v)
        rssi = int(np.frombuffer(data[RSSI_OFFSET : RSSI_OFFSET + 1], dtype=np.int8)[0]) if len(data) > RSSI_OFFSET else 0
        # ── CMU Phase Sanitization (per-packet: median filter + mean removal) ──
        try:
            from .csi_phase_sanitization import sanitize_phase_vector
            phase = sanitize_phase_vector(phase)
        except Exception:
            pass  # деградируем к сырой фазе если модуль недоступен
        # Return full-resolution (not normalized to 64) for V48 band features
        return rssi, amp, phase

    # ── CSV-format handler for ESP32-S3 nodes (port 5006) ──────────

    def _handle_csv_packet(self, data: bytes, addr: tuple):
        """Process CSV CSI_DATA packet from ESP32-S3 nodes (firmware v2.0)."""
        raw_ip = addr[0]

        # Detect keepalive packets before CSV parsing
        if self._handle_keepalive(data, addr):
            return

        try:
            line = data.decode("utf-8", errors="replace").strip()
        except Exception:
            return
        if "CSI_DATA" not in line:
            return

        # Extract MAC from CSV for network-agnostic node identification
        # CSV format: CSI_DATA,role,node_mac,src_mac,rssi,...
        node_mac = None
        try:
            _parts_quick = line.split(",", 4)
            if len(_parts_quick) >= 3:
                node_mac = _parts_quick[2].strip().lower()
        except Exception:
            pass
        ip = resolve_ip(raw_ip, node_mac)

        # Feed to recording service (raw bytes for storage)
        try:
            from .csi_recording_service import csi_recording_service
            csi_recording_service.ingest_packet(data, (ip, addr[1]))
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
            # Handle both space-separated and comma-separated IQ values.
            # ESP32-CSI-Tool may emit either format depending on firmware.
            vals = [int(x) for x in csi_str.replace(",", " ").split()]
            n = len(vals) // 2
            if n < 40:
                return
            arr = np.array(vals[: n * 2], dtype=np.float32).reshape(-1, 2)
            amp = np.sqrt(arr[:, 0] ** 2 + arr[:, 1] ** 2)
            phase = np.arctan2(arr[:, 1], arr[:, 0])
            # ── CMU Phase Sanitization (per-packet: median filter + mean removal) ──
            try:
                from .csi_phase_sanitization import sanitize_phase_vector
                phase = sanitize_phase_vector(phase)
            except Exception:
                pass  # деградируем к сырой фазе если модуль недоступен
            # Store FULL-resolution amplitudes (192 subcarriers) for V48 band features.
            # Previous code normalized to 64 which zeroed band3-band7.
            amp_full = amp  # keep original (typically 192 subcarriers)
            phase_full = phase
        except Exception:
            return

        if self._start_time is None:
            self._start_time = time.time()
        t_sec = time.time() - self._start_time
        self._packets[ip].append((t_sec, rssi, amp_full, phase_full))

        # ── Mesh link ingestion (ESP-NOW peer-to-peer) ────────────────
        # Detect mesh fields after the CSI data block: content after ']"'
        try:
            ei_end = line.find(']"')
            if ei_end >= 0:
                remainder = line[ei_end + 2:]  # everything after ']"'
                if remainder.startswith(","):
                    remainder = remainder[1:]  # strip leading comma
                mesh_parts = remainder.split(",") if remainder.strip() else []
                if len(mesh_parts) >= 4:
                    source_mac = mesh_parts[0].strip()
                    link_type = mesh_parts[1].strip().lower()
                    try:
                        source_node_id = int(mesh_parts[2].strip())
                    except ValueError:
                        source_node_id = -1
                    try:
                        ntp_str = mesh_parts[3].strip()
                        ntp_us = int(ntp_str) if ntp_str and ntp_str != "-1" else None
                    except ValueError:
                        ntp_us = None

                    if link_type in ("router", "peer"):
                        # Resolve receiver node short name from IP
                        receiver_node = self._V48_NODE_NAMES.get(ip, ip)
                        if receiver_node.startswith("node"):
                            receiver_node = "n" + receiver_node[4:]  # node01 -> n01
                        source_node = MeshLinkManager.resolve_source_node(
                            source_node_id, link_type, source_mac
                        )
                        link_id = MeshLinkManager.make_link_id(receiver_node, source_node)

                        self._mesh.ingest(
                            link_id=link_id,
                            receiver_node=receiver_node,
                            source_node=source_node,
                            link_type=link_type,
                            t_sec=t_sec,
                            rssi=float(rssi),
                            amplitude=amp_full,
                            phase=phase_full,
                            ntp_us=ntp_us,
                        )
                        if not self._mesh_enabled:
                            self._mesh_enabled = True
                            logger.info(
                                "Mesh link detected: %s (%s), enabling mesh features",
                                link_id, link_type,
                            )
        except Exception as e:
            logger.debug("Mesh field parse skipped: %s", e)

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
        was_running = bool(
            self._running
            or self._transport is not None
            or self._csv_transport is not None
            or (self._prediction_task is not None and not self._prediction_task.done())
        )

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
        if self._csv_transport:
            close = getattr(self._csv_transport, "close", None)
            if callable(close):
                close()
            self._csv_transport = None
        self._running = False
        logger.info("CSI UDP listener stopped")
        return {
            "status": "stopped" if was_running else "already_stopped",
            "listener_running": False,
            "csv_listener_running": False,
            "prediction_task_running": False,
        }

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
                self._apply_multi_person_coordinate_guard()
                self._voice_announce()
                loop_count += 1
                if loop_count % 100 == 0:  # every ~30s at 0.3s interval
                    self._check_tenda_ap_health()
            except Exception as e:
                self.current["last_error"] = str(e)
                import traceback
                self.current["last_error_traceback"] = traceback.format_exc(limit=12)
                self.current["feature_status"] = "prediction_exception"
                logger.error("Prediction error: %s\n%s", e, self.current["last_error_traceback"])
            await asyncio.sleep(interval)

    # ── Voice announcements (ElevenLabs TTS) ─────────────────────────

    _voice_enabled: bool = False
    _voice_last_binary: str = ""
    _voice_last_zone: str = ""
    _voice_last_announce_t: float = 0.0
    _voice_cooldown_sec: float = 8.0  # minimum seconds between announcements

    def voice_start(self) -> dict:
        """Enable real-time voice announcements."""
        was_enabled = self._voice_enabled
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
                return {
                    "status": "already_running" if was_enabled else "started",
                    "voice_enabled": True,
                    "tts_available": True,
                    "backend": "elevenlabs",
                    "voice": tts._resolved_voice_name,
                }
            return {
                "status": "already_running" if was_enabled else "started",
                "voice_enabled": True,
                "tts_available": False,
                "backend": "macos_say",
                "fallback": "macOS say",
            }
        except Exception as e:
            logger.warning("Voice start: TTS init failed: %s", e)
            return {
                "status": "already_running" if was_enabled else "started",
                "voice_enabled": True,
                "tts_available": False,
                "backend": "macos_say",
                "error": str(e),
            }

    def voice_stop(self) -> dict:
        """Disable voice announcements."""
        was_enabled = self._voice_enabled
        self._voice_enabled = False
        stopped_playback = False
        try:
            from .tts_service import get_tts_service
            stopped_playback = bool(get_tts_service().stop())
        except Exception:
            pass
        return {
            "status": "stopped" if (was_enabled or stopped_playback) else "already_stopped",
            "voice_enabled": False,
            "stopped_playback": stopped_playback,
        }

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
        v8 = self._get_latest_v8_shadow()
        tb = self._track_b_shadow or {}

        prod_binary = str(prod.get("binary", "") or "").lower()

        # ── 1. Coordinate spread between production and V8 shadow ────
        prod_x = prod.get("target_x", 0.0)
        prod_y = prod.get("target_y", 0.0)
        v8_x = v8.get("target_x")
        v8_y = v8.get("target_y")
        v8_binary = str(v8.get("binary", "") or "").lower()
        v8_is_empty_outlier = prod_binary == "occupied" and v8_binary == "empty"
        coord_spread = 0.0
        if not v8_is_empty_outlier and v8_x is not None and v8_y is not None:
            coord_spread = ((prod_x - v8_x) ** 2 + (prod_y - v8_y) ** 2) ** 0.5

        # ── 2. Class disagreement signals ────────────────────────────
        prod_coarse = str(prod.get("coarse", "")).upper()
        v8_class = str(v8.get("predicted_class", "")).upper()
        tb_class = str(tb.get("predicted_class", "")).upper()
        v8_disagree = bool(
            not v8_is_empty_outlier
            and v8_class
            and prod_coarse
            and v8_class != prod_coarse
        )
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
        if v8_is_empty_outlier:
            reasons.append("v8_empty_outlier_ignored")

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
        prod_track_x = None if prod_x is None else round(float(prod_x), 3)
        prod_track_y = None if prod_y is None else round(float(prod_y), 3)
        # Track 0: always the production coordinate
        tracks.append({
            "id": "prod_0",
            "source": "production",
            "x": prod_track_x,
            "y": prod_track_y,
            "zone": prod.get("target_zone", "unknown"),
            "class": prod_coarse.lower() if prod_coarse else "unknown",
            "confidence": round(coarse_conf, 3),
        })

        # Track 1: V8 shadow coordinate (if available and different enough)
        if not v8_is_empty_outlier and v8_x is not None and v8_y is not None and coord_spread > 0.3:
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
            cluster_center = {"x": prod_track_x, "y": prod_track_y}
            cluster_radius = 0.0

        # V58 person count classifier override
        _v58 = self.current.get("multi_person", {})
        _v58_count = _v58.get("person_count")
        _v58_conf = float(_v58.get("confidence", 0) or 0)
        _v58_source = _v58.get("source", "")
        if _v58_count is not None and _v58_conf > 0.5 and "error" not in _v58_source:
            _v58_map = {0: ("single", 0), 1: ("single", 1), 2: ("multi", 3)}
            _v58_state, _v58_est = _v58_map.get(_v58_count, ("single", 1))
            if _v58_est == 0:
                _v58_state = "single"
                _v58_est = 0
            est_count = _v58_est
            state = _v58_state
            score = _v58_conf
            reasons.append(f"v58_person_count={_v58_count}")

        self._mp_estimate = {
            "person_count_estimate": est_count,
            "multi_person_state": state,
            "multi_person_confidence": round(score, 3),
            "diagnostic_tracks": tracks,
            "diagnostic_cluster_center": cluster_center,
            "diagnostic_cluster_radius": cluster_radius,
            "estimator_source": "v58_classifier" if "v58_person_count" in str(reasons) else "runtime_heuristic",
            "estimator_reasons": reasons,
            "recording_hint": rec_hint,
        }

    def _apply_multi_person_coordinate_guard(self) -> None:
        """Suppress misleading single-target coordinates in multi-person scenes."""
        binary = str(self.current.get("binary", "unknown") or "unknown").lower()
        mp = self._mp_estimate or {}
        state = str(mp.get("multi_person_state", "single") or "single").lower()
        conf = float(mp.get("multi_person_confidence", 0.0) or 0.0)
        raw_target_x = self.current.get("target_x")
        raw_target_y = self.current.get("target_y")
        raw_target_zone = self.current.get("target_zone", "unknown")
        raw_coordinate_source = self.current.get("coordinate_source")

        applied = False
        reason = "single_person_assumed"
        coordinate_valid = binary == "occupied"
        coordinate_reliability = "single_person_runtime" if coordinate_valid else "unavailable"

        if binary == "empty":
            coordinate_valid = False
            coordinate_reliability = "empty_zeroed"
            reason = "empty_scene"
        elif binary != "occupied":
            coordinate_valid = False
            coordinate_reliability = "unavailable"
            reason = "binary_not_occupied"
        elif state == "multi" and conf >= self._MULTI_PERSON_COORD_GUARD_THRESHOLD:
            self.current["target_x"] = None
            self.current["target_y"] = None
            self.current["target_zone"] = "multi_person"
            self.current["coordinate_source"] = "multi_person_suppressed"
            coordinate_valid = False
            coordinate_reliability = "single_person_only"
            applied = True
            reason = "multi_person_detected"
        elif state == "unresolved":
            coordinate_reliability = "unresolved_multi_person_hint"
            reason = "multi_person_unresolved"

        self.current["coordinate_valid"] = coordinate_valid
        self.current["coordinate_reliability"] = coordinate_reliability
        self.current["coordinate_guard"] = {
            "applied": applied,
            "reason": reason,
            "raw_target_x": raw_target_x,
            "raw_target_y": raw_target_y,
            "raw_target_zone": raw_target_zone,
            "raw_coordinate_source": raw_coordinate_source,
            "multi_person_state": state,
            "multi_person_confidence": round(conf, 3),
        }

        if self._recent_predictions:
            self._recent_predictions[-1].update({
                "target_x": self.current.get("target_x"),
                "target_y": self.current.get("target_y"),
                "zone": self.current.get("target_zone", raw_target_zone),
                "coordinate_source": self.current.get("coordinate_source", raw_coordinate_source),
                "coordinate_valid": coordinate_valid,
                "coordinate_reliability": coordinate_reliability,
            })
            self.current["history"] = self._recent_predictions[-30:]

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

    def _ensure_fewshot_prototype_shadow_ready(self) -> dict[str, Any]:
        if not FEWSHOT_PROTOTYPE_SHADOW_ENABLED:
            return {
                "enabled": False,
                "status": "disabled",
                "bundle_path": str(FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH),
            }

        try:
            from .fewshot_prototype_shadow_service import (
                fewshot_prototype_shadow_service as _proto_shadow,
            )
            status = _proto_shadow.get_status()
            if not status.get("active"):
                if not FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH.exists():
                    return {
                        "enabled": True,
                        "status": "bundle_missing",
                        "bundle_path": str(FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH),
                    }
                _proto_shadow.activate(FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH)
            return _proto_shadow
        except Exception as error:
            logger.debug("Prototype shadow activation skipped: %s", error)
            return {
                "enabled": True,
                "status": "activation_failed",
                "bundle_path": str(FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH),
                "last_error": str(error),
            }

    def _ensure_fewshot_temporal_overlay_ready(self):
        if not FEWSHOT_TEMPORAL_OVERLAY_ENABLED:
            return None
        if self._fewshot_temporal_overlay_service is not None:
            return self._fewshot_temporal_overlay_service
        if not FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH.exists() or not FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH.exists():
            return None
        try:
            from .fewshot_temporal_zone_overlay_service import TemporalZoneOverlayService
            self._fewshot_temporal_overlay_service = TemporalZoneOverlayService.from_paths(
                prototype_path=FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH,
                temporal_summary_path=FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH,
            )
        except Exception as error:
            logger.debug("Temporal overlay activation skipped: %s", error)
            self._fewshot_temporal_overlay_service = None
        return self._fewshot_temporal_overlay_service

    def _ensure_live_door_shadow_ready(self):
        if not LIVE_DOOR_SHADOW_ENABLED:
            return None
        if self._live_door_shadow_service is not None:
            return self._live_door_shadow_service
        try:
            from .live_door_shadow_service import (
                live_door_shadow_service as _live_door_shadow,
            )
            status = _live_door_shadow.get_status()
            if not status.get("active"):
                _live_door_shadow.activate()
            self._live_door_shadow_service = _live_door_shadow
        except Exception as error:
            logger.debug("Live door shadow activation skipped: %s", error)
            self._live_door_shadow_service = None
        return self._live_door_shadow_service

    def _predict_fewshot_temporal_overlay(
        self,
        feat: dict[str, Any],
        active_nodes: int,
        *,
        pkt_count: int,
        window_t: float,
        prototype_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not FEWSHOT_TEMPORAL_OVERLAY_ENABLED:
            return {
                "enabled": False,
                "loaded": False,
                "status": "disabled",
                "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
            }

        overlay = self._ensure_fewshot_temporal_overlay_ready()
        if overlay is None:
            return {
                "enabled": True,
                "loaded": False,
                "status": "not_loaded",
                "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
            }

        if active_nodes < 3:
            return {
                "enabled": True,
                "loaded": True,
                "status": "insufficient_nodes",
                "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
                "active_nodes": int(active_nodes),
            }

        try:
            from .fewshot_temporal_zone_overlay_service import (
                ZONE_CENTER,
                ZONE_DOOR,
                directional_score,
            )

            rule = overlay.rule
            score = float(directional_score(feat, rule.score_family))
            threshold_zone = ZONE_CENTER if score >= rule.threshold else ZONE_DOOR
            prototype_zone = None
            prototype_zone_raw = None
            prototype_confidence = None
            prototype_margin = None
            if isinstance(prototype_result, dict):
                prototype_zone = prototype_result.get("zone")
                prototype_zone_raw = prototype_result.get("zone_raw")
                prototype_confidence = prototype_result.get("confidence")
                prototype_margin = prototype_result.get("score_margin")

            state = self._fewshot_temporal_overlay_state
            if state not in {ZONE_CENTER, ZONE_DOOR}:
                seed = prototype_zone_raw if prototype_zone_raw in {ZONE_CENTER, ZONE_DOOR} else None
                if seed is None and prototype_zone in {ZONE_CENTER, ZONE_DOOR}:
                    seed = prototype_zone
                if seed in {ZONE_CENTER, ZONE_DOOR}:
                    state = seed
                    self._fewshot_temporal_overlay_bootstrap_scores = []
                else:
                    self._fewshot_temporal_overlay_bootstrap_scores.append(score)
                    bootstrap = self._fewshot_temporal_overlay_bootstrap_scores[-rule.bootstrap_n:]
                    center_votes = sum(1 for value in bootstrap if value >= rule.threshold)
                    state = ZONE_CENTER if center_votes >= (len(bootstrap) / 2.0) else ZONE_DOOR

            pending = self._fewshot_temporal_overlay_pending
            switched = False
            if state == ZONE_CENTER:
                if score < rule.threshold - rule.margin:
                    pending += 1
                    if pending >= rule.dwell:
                        state = ZONE_DOOR
                        pending = 0
                        switched = True
                else:
                    pending = 0
            else:
                if score > rule.threshold + rule.margin:
                    pending += 1
                    if pending >= rule.dwell:
                        state = ZONE_CENTER
                        pending = 0
                        switched = True
                else:
                    pending = 0

            self._fewshot_temporal_overlay_state = state
            self._fewshot_temporal_overlay_pending = pending

            return {
                "enabled": True,
                "loaded": True,
                "status": "shadow_live",
                "consumer": "temporal_directional_zone_overlay",
                "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
                "zone": state,
                "threshold_zone": threshold_zone,
                "directional_score": round(score, 6),
                "score_family": rule.score_family,
                "threshold": round(float(rule.threshold), 6),
                "margin": round(float(rule.margin), 6),
                "dwell": int(rule.dwell),
                "bootstrap_n": int(rule.bootstrap_n),
                "pending": int(pending),
                "switched": switched,
                "prototype_zone": prototype_zone,
                "prototype_zone_raw": prototype_zone_raw,
                "prototype_confidence": round(float(prototype_confidence), 4) if prototype_confidence is not None else None,
                "prototype_margin": round(float(prototype_margin), 6) if prototype_margin is not None else None,
                "agreement_with_prototype": state == prototype_zone or state == prototype_zone_raw,
                "active_nodes": int(active_nodes),
                "pkt_count": int(pkt_count or 0),
                "t": window_t,
            }
        except Exception as error:
            logger.debug("Temporal overlay shadow skipped: %s", error)
            return {
                "enabled": True,
                "loaded": False,
                "status": "predict_failed",
                "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
                "last_error": str(error),
            }

    def _build_door_center_candidate_shadow(self) -> dict[str, Any]:
        prototype = self._fewshot_prototype_shadow if isinstance(self._fewshot_prototype_shadow, dict) else {}
        temporal = self._fewshot_temporal_overlay_shadow if isinstance(self._fewshot_temporal_overlay_shadow, dict) else {}
        live_door = self._live_door_shadow if isinstance(self._live_door_shadow, dict) else {}
        fewshot = self._fewshot_adaptation_shadow if isinstance(self._fewshot_adaptation_shadow, dict) else {}
        feat = self._last_feat_dict if isinstance(self._last_feat_dict, dict) else {}
        runtime_target_zone = str(self.current.get("target_zone", "unknown") or "unknown").lower()
        runtime_binary = str(self.current.get("binary", "unknown") or "unknown").lower()
        runtime_binary_conf = float(self.current.get("binary_confidence", 0.0) or 0.0)
        runtime_pps = float(self.current.get("pps", 0.0) or 0.0)
        runtime_motion_state = str(self.current.get("motion_state", "unknown") or "unknown").upper()
        runtime_coarse = str(self.current.get("coarse", "unknown") or "unknown").lower()
        truth_tvar = self.current.get("truth_tvar") if isinstance(self.current.get("truth_tvar"), dict) else {}
        truth_tvar_verdict = str(truth_tvar.get("truth_verdict", "unknown") or "unknown").lower()
        try:
            truth_tvar_median_runtime = float(truth_tvar.get("tvar_median", 0.0) or 0.0)
        except (TypeError, ValueError):
            truth_tvar_median_runtime = 0.0
        active_nodes = int(
            prototype.get("active_nodes")
            or temporal.get("active_nodes")
            or self.current.get("nodes_active")
            or 0
        )
        proto_zone = prototype.get("zone")
        proto_zone_raw = prototype.get("zone_raw")
        proto_confidence = float(prototype.get("confidence")) if prototype.get("confidence") is not None else None
        proto_margin = float(prototype.get("score_margin")) if prototype.get("score_margin") is not None else None
        temporal_zone = temporal.get("zone")
        threshold_zone = temporal.get("threshold_zone")
        temporal_score = float(temporal.get("directional_score")) if temporal.get("directional_score") is not None else None
        fewshot_zone = fewshot.get("zone")
        fewshot_confidence = float(fewshot.get("confidence")) if fewshot.get("confidence") is not None else None
        available = prototype.get("status") == "shadow_live" or temporal.get("status") == "shadow_live"
        if not available:
            return {
                "enabled": FEWSHOT_PROTOTYPE_SHADOW_ENABLED or FEWSHOT_TEMPORAL_OVERLAY_ENABLED,
                "available": False,
                "status": "not_ready",
                "candidate_zone": None,
                "agreement": "not_ready",
            }

        proposed_zone = None
        agreement = "partial"
        strong_temporal_door = (
            temporal_zone == "door_passage"
            and temporal_score is not None
            and temporal_score <= -0.45
        )
        very_strong_temporal_door = (
            temporal_zone == "door_passage"
            and temporal_score is not None
            and temporal_score <= -1.0
        )
        strong_temporal_center = (
            temporal_zone == "center"
            and temporal_score is not None
            and temporal_score >= 0.75
        )
        very_strong_temporal_center = (
            temporal_zone == "center"
            and temporal_score is not None
            and temporal_score >= 0.95
        )
        very_strong_fewshot_center = (
            fewshot_zone == "center"
            and fewshot_confidence is not None
            and fewshot_confidence >= 0.99
        )
        strong_fewshot_door = (
            fewshot_zone == "door_passage"
            and fewshot_confidence is not None
            and fewshot_confidence >= 0.82
        )
        very_strong_runtime_fewshot_door = (
            runtime_target_zone == "door"
            and fewshot_zone == "door_passage"
            and fewshot_confidence is not None
            and fewshot_confidence >= 0.93
        )
        assisted_runtime_door_context = (
            runtime_target_zone == "door"
            and runtime_binary_conf >= 0.82
            and fewshot_zone == "door_passage"
            and fewshot_confidence is not None
            and fewshot_confidence >= 0.97
        )
        strong_center_consensus = bool(
            proto_zone == "center"
            and temporal_zone == "center"
            and threshold_zone == "center"
        )
        door_signature_votes = 0
        n02_rssi = float(feat.get("node02_rssi_mean", -100.0) or -100.0)
        n04_amp = float(feat.get("node04_amp_mean", 0.0) or 0.0)
        n06_tvar = float(feat.get("node06_tvar", 0.0) or 0.0)
        n05_rssi = float(feat.get("node05_rssi_mean", -100.0) or -100.0)
        n04_rssi = float(feat.get("node04_rssi_mean", -100.0) or -100.0)
        n06_amp = float(feat.get("node06_amp_mean", 0.0) or 0.0)
        if n02_rssi >= -61.5:
            door_signature_votes += 1
        if n04_amp <= 23.0:
            door_signature_votes += 1
        if n06_tvar <= 10.0:
            door_signature_votes += 1
        door_signature_active = door_signature_votes >= 2
        strong_door_signature = bool(
            door_signature_votes >= 3
            or (
                door_signature_votes >= 2
                and n02_rssi >= -60.0
                and n06_tvar <= 8.8
            )
        )
        door_gate_support = (
            fewshot_zone == "door_passage"
            and fewshot_confidence is not None
            and fewshot_confidence >= 0.74
        )
        if (
            door_gate_support
            and door_signature_active
        ):
            self._door_signature_consecutive += 1
        else:
            self._door_signature_consecutive = 0

        raw_door_votes = 0
        if n05_rssi >= -50.8:
            raw_door_votes += 1
        if n04_rssi >= -55.2:
            raw_door_votes += 1
        if n06_amp >= 19.0:
            raw_door_votes += 1
        if n06_tvar <= 11.0:
            raw_door_votes += 1
        def _avg_present(keys: list[str]) -> float:
            vals = []
            for key in keys:
                val = feat.get(key)
                if val is None:
                    continue
                try:
                    vals.append(float(val))
                except (TypeError, ValueError):
                    continue
            return float(sum(vals) / len(vals)) if vals else 0.0

        door_cluster_amp = _avg_present(["node01_amp_mean", "node02_amp_mean", "node04_amp_mean"])
        center_cluster_amp = _avg_present(["node05_amp_mean", "node06_amp_mean", "node07_amp_mean"])
        door_center_amp_gap = float(door_cluster_amp - center_cluster_amp)
        door_tvar_mean_live = _avg_present(["door_tvar_mean", "node01_tvar", "node02_tvar", "node04_tvar"])
        center_tvar_mean_live = _avg_present(["center_tvar_mean", "node05_tvar", "node06_tvar", "node07_tvar"])
        tvar_vals_live = []
        for key in ["node01_tvar", "node02_tvar", "node03_tvar", "node04_tvar", "node05_tvar", "node06_tvar", "node07_tvar"]:
            val = feat.get(key)
            if val is None:
                continue
            try:
                tvar_vals_live.append(float(val))
            except (TypeError, ValueError):
                continue
        if "tvar_median" in feat and feat.get("tvar_median") is not None:
            try:
                tvar_median_live = float(feat.get("tvar_median"))
            except (TypeError, ValueError):
                tvar_median_live = 0.0
        elif tvar_vals_live:
            tvar_vals_live.sort()
            mid = len(tvar_vals_live) // 2
            tvar_median_live = (
                tvar_vals_live[mid]
                if len(tvar_vals_live) % 2 == 1
                else float((tvar_vals_live[mid - 1] + tvar_vals_live[mid]) / 2.0)
            )
        else:
            tvar_median_live = 0.0
        door_phase_std_mean_live = _avg_present(["door_phase_std_mean", "node01_phase_std", "node02_phase_std", "node04_phase_std"])
        phase_std_mean_live = _avg_present(["phase_std_mean", "node01_phase_std", "node02_phase_std", "node03_phase_std", "node04_phase_std", "node05_phase_std", "node06_phase_std", "node07_phase_std"])
        door_amp_std_mean_live = _avg_present(["door_amp_std_mean", "node01_amp_std", "node02_amp_std", "node04_amp_std"])
        current_fw3_door_votes = 0
        if n02_rssi >= -63.0:
            current_fw3_door_votes += 1
        if float(feat.get("node02_tvar", 0.0) or 0.0) >= 4.0:
            current_fw3_door_votes += 1
        if door_tvar_mean_live >= 3.7:
            current_fw3_door_votes += 1
        if tvar_median_live >= 2.8:
            current_fw3_door_votes += 1
        if door_amp_std_mean_live >= 3.8:
            current_fw3_door_votes += 1
        if door_phase_std_mean_live <= 1.05 and phase_std_mean_live <= 1.02:
            current_fw3_door_votes += 1
        current_fw3_door_assist = False
        current_fw3_low_tvar_door = False
        current_fw3_door_hold = False
        current_fw3_tvar_shape_door = False
        current_live_fw3_door = False
        current_live_fw3_door_hold = False
        shadow_empty_scene = bool(
            (runtime_binary == "empty" or runtime_target_zone == "empty")
            and runtime_motion_state == "NO_MOTION"
            and runtime_coarse in {"empty", "static", "unknown"}
            and (
                truth_tvar_verdict == "empty"
                or truth_tvar_median_runtime < 4.0
                or (truth_tvar_median_runtime <= 0.0 and tvar_median_live < 4.0)
            )
        )
        live_door_shadow_confidence = float(live_door.get("confidence", 0.0) or 0.0)
        live_door_shadow_ready = bool(
            live_door.get("status") == "shadow_live"
            and str(live_door.get("zone") or "") == "door_passage"
            and live_door_shadow_confidence >= 0.75
            and active_nodes >= 7
            and runtime_pps >= 18.0
            and not shadow_empty_scene
        )
        center_locked_context = bool(
            strong_center_consensus
            and temporal_score is not None
            and temporal_score >= 8.0
            and door_center_amp_gap <= -1.0
        )

        if proto_zone in {"center", "door_passage"} and temporal_zone in {"center", "door_passage"}:
            if proto_zone == temporal_zone:
                proposed_zone = proto_zone
                agreement = "full"
            else:
                if strong_temporal_door or strong_temporal_center:
                    proposed_zone = temporal_zone
                    agreement = "temporal_override"
                else:
                    strong_proto = (
                        proto_confidence is not None and proto_confidence >= 0.62
                        and proto_margin is not None and proto_margin >= 0.08
                    )
                    if strong_proto:
                        proposed_zone = proto_zone
                        agreement = "prototype_override"
                    else:
                        proposed_zone = temporal_zone
                        agreement = "temporal_threshold"
        elif proto_zone in {"center", "door_passage"}:
            proposed_zone = proto_zone
            agreement = "prototype_only"
        elif temporal_zone in {"center", "door_passage"}:
            proposed_zone = temporal_zone
            agreement = "temporal_only"
        elif threshold_zone in {"center", "door_passage"}:
            proposed_zone = threshold_zone
            agreement = "threshold_only"

        center_candidate = proposed_zone == "center"
        door_override_support = bool(
            temporal_zone == "door_passage"
            or threshold_zone == "door_passage"
            or door_center_amp_gap >= 0.05
        )
        door_hold_support = bool(
            temporal_zone == "door_passage"
            or threshold_zone == "door_passage"
            or door_center_amp_gap >= -0.05
        )
        current_fw3_door_assist = bool(
            center_candidate
            and current_fw3_door_votes >= 5
            and raw_door_votes >= 3
            and door_signature_active
            and door_override_support
            and door_amp_std_mean_live >= 4.0
            and active_nodes >= 6
            and runtime_pps >= 18.0
            and not shadow_empty_scene
        )
        current_fw3_low_tvar_door = bool(
            center_candidate
            and active_nodes >= 7
            and not shadow_empty_scene
            and live_door_shadow_confidence >= 0.75
            and (
                (
                    current_fw3_door_votes >= 5
                    and raw_door_votes >= 4
                    and door_signature_active
                    and door_override_support
                    and tvar_median_live <= 4.0
                    and runtime_pps >= 24.0
                )
                or (
                    current_fw3_door_votes >= 3
                    and raw_door_votes >= 4
                    and door_amp_std_mean_live >= 5.2
                    and door_center_amp_gap >= 0.05
                    and (door_tvar_mean_live - center_tvar_mean_live) >= 0.2
                    and 2.0 <= tvar_median_live <= 3.0
                    and not center_locked_context
                    and runtime_pps >= 18.0
                )
            )
        )
        current_fw3_door_hold = bool(
            center_candidate
            and self._door_center_candidate_state == "door_passage"
            and current_fw3_door_votes >= 5
            and raw_door_votes >= 3
            and door_signature_active
            and (
                door_hold_support
                or (
                    raw_door_votes >= 4
                    and not center_locked_context
                    and tvar_median_live <= 3.8
                )
            )
            and tvar_median_live <= 4.4
            and active_nodes >= 7
            and runtime_pps >= 18.0
            and not shadow_empty_scene
        )
        current_fw3_tvar_shape_door = bool(
            center_candidate
            and door_signature_active
            and raw_door_votes >= 4
            and n02_rssi >= -61.5
            and door_center_amp_gap >= -0.8
            and (door_tvar_mean_live - center_tvar_mean_live) >= 1.0
            and 2.8 <= tvar_median_live <= 4.2
            and active_nodes >= 7
            and runtime_pps >= 18.0
            and not center_locked_context
            and not shadow_empty_scene
        )
        current_live_fw3_door = bool(
            center_candidate
            and current_fw3_door_votes >= 4
            and raw_door_votes >= 3
            and door_signature_active
            and door_override_support
            and live_door_shadow_confidence >= 0.75
            and door_amp_std_mean_live >= 4.3
            and phase_std_mean_live <= 0.92
            and 3.0 <= tvar_median_live <= 5.8
            and active_nodes >= 7
            and runtime_pps >= 20.0
            and not shadow_empty_scene
        )
        current_live_fw3_door_hold = bool(
            center_candidate
            and self._door_center_candidate_state == "door_passage"
            and current_fw3_door_votes >= 4
            and raw_door_votes >= 3
            and door_signature_active
            and door_hold_support
            and live_door_shadow_confidence >= 0.75
            and door_amp_std_mean_live >= 4.0
            and phase_std_mean_live <= 0.95
            and tvar_median_live <= 5.8
            and active_nodes >= 7
            and runtime_pps >= 18.0
            and not shadow_empty_scene
        )

        doorway_assist_override = bool(
            proposed_zone == "center"
            and door_gate_support
            and door_signature_active
            and strong_door_signature
            and self._door_signature_consecutive >= 2
            and fewshot_confidence is not None
            and fewshot_confidence >= 0.77
            and runtime_binary_conf >= 0.60
            and self._door_center_candidate_state == "center"
            and not shadow_empty_scene
        )
        raw_door_assist = bool(
            proposed_zone == "center"
            and not strong_center_consensus
            and raw_door_votes >= 3
            and door_center_amp_gap >= 0.45
            and active_nodes >= 7
            and runtime_pps >= 28.0
            and self._door_center_candidate_state == "center"
            and runtime_binary != "empty"
            and not shadow_empty_scene
        )
        raw_door_hold = bool(
            proposed_zone == "center"
            and not strong_center_consensus
            and (
                (
                    raw_door_votes >= 3
                    and door_center_amp_gap >= 0.45
                )
                or (
                    raw_door_votes >= 2
                    and door_center_amp_gap >= 0.35
                    and fewshot_zone == "door_passage"
                    and fewshot_confidence is not None
                    and fewshot_confidence >= 0.75
                )
            )
            and active_nodes >= 7
            and runtime_pps >= 28.0
            and door_signature_active
            and self._door_center_candidate_state == "door_passage"
            and runtime_binary != "empty"
            and not shadow_empty_scene
        )

        if (
            not shadow_empty_scene
            and proposed_zone == "center"
            and door_gate_support
            and self._door_signature_consecutive >= 2
            and (
                not strong_center_consensus
                or doorway_assist_override
            )
        ):
            proposed_zone = "door_passage"
            agreement = "fewshot_door_gate"
        elif live_door_shadow_ready and not center_locked_context:
            proposed_zone = "door_passage"
            agreement = "live_door_shadow"
        elif current_live_fw3_door:
            proposed_zone = "door_passage"
            agreement = "current_live_fw3_door"
        elif current_fw3_low_tvar_door:
            proposed_zone = "door_passage"
            agreement = "current_fw3_low_tvar_door"
        elif current_fw3_tvar_shape_door:
            proposed_zone = "door_passage"
            agreement = "current_fw3_tvar_shape_door"
        elif (
            proposed_zone == "center"
            and live_door_shadow_confidence >= 0.75
            and current_fw3_door_votes >= 5
            and door_signature_active
            and raw_door_votes >= 3
            and door_amp_std_mean_live >= 4.0
            and (
                (
                    door_center_amp_gap >= 0.20
                    and n02_rssi >= -62.5
                )
                or (
                    n02_rssi >= -58.5
                    and (door_tvar_mean_live - center_tvar_mean_live) >= 1.25
                )
            )
            and active_nodes >= 7
            and runtime_pps >= 18.0
        ):
            proposed_zone = "door_passage"
            agreement = "current_fw3_rssi_door"
        elif current_live_fw3_door_hold:
            proposed_zone = "door_passage"
            agreement = "current_live_fw3_door_hold"
        elif current_fw3_door_hold:
            proposed_zone = "door_passage"
            agreement = "current_fw3_door_hold"
        elif (
            proposed_zone == "center"
            and temporal_zone == "door_passage"
            and threshold_zone == "door_passage"
            and current_fw3_door_votes >= 5
            and raw_door_votes >= 3
            and active_nodes >= 6
            and runtime_pps >= 20.0
        ):
            proposed_zone = "door_passage"
            agreement = "current_fw3_temporal_door"
        elif current_fw3_door_assist:
            proposed_zone = "door_passage"
            agreement = "current_fw3_door_assist"
        elif raw_door_assist:
            proposed_zone = "door_passage"
            agreement = "door_raw_assist"
        elif raw_door_hold:
            proposed_zone = "door_passage"
            agreement = "door_raw_hold"
        elif (
            proposed_zone == "center"
            and very_strong_runtime_fewshot_door
            and (
                not strong_center_consensus
                or assisted_runtime_door_context
            )
        ):
            proposed_zone = "door_passage"
            agreement = "fewshot_runtime_override"
        elif (
            proposed_zone == "door_passage"
            and very_strong_fewshot_center
            and not door_gate_support
        ):
            proposed_zone = "center"
            agreement = "fewshot_center_override"

        candidate_zone = proposed_zone
        stable_zone = self._door_center_candidate_state
        pending_zone = self._door_center_candidate_pending_zone
        pending_count = int(self._door_center_candidate_pending_count or 0)
        hold_applied = False

        if candidate_zone in {"center", "door_passage"}:
            if stable_zone not in {"center", "door_passage"}:
                bootstrap_ready = True
                if candidate_zone == "door_passage":
                    bootstrap_ready = (
                        (
                            agreement in {"full", "prototype_override", "door_raw_assist", "current_fw3_rssi_door", "current_fw3_temporal_door", "current_fw3_door_assist", "current_fw3_low_tvar_door", "current_fw3_tvar_shape_door", "current_fw3_door_hold", "current_live_fw3_door", "current_live_fw3_door_hold", "live_door_shadow"}
                            and (proto_zone == "door_passage" or very_strong_temporal_door)
                        )
                        or (
                            agreement == "temporal_override"
                            and very_strong_temporal_door
                        )
                        or agreement in {"door_raw_assist", "current_fw3_rssi_door", "current_fw3_temporal_door", "current_fw3_door_assist", "current_fw3_low_tvar_door", "current_fw3_tvar_shape_door", "current_fw3_door_hold", "current_live_fw3_door", "current_live_fw3_door_hold", "live_door_shadow"}
                    )
                if bootstrap_ready:
                    stable_zone = candidate_zone
                    pending_zone = None
                    pending_count = 0
                else:
                    if pending_zone == candidate_zone:
                        pending_count += 1
                    else:
                        pending_zone = candidate_zone
                        pending_count = 1
                    hold_applied = True
                    candidate_zone = None
            elif candidate_zone == stable_zone:
                pending_zone = None
                pending_count = 0
            else:
                required = 2
                if stable_zone == "door_passage" and candidate_zone == "center":
                    if shadow_empty_scene:
                        required = 1
                    elif (
                        strong_center_consensus
                        and (
                            fewshot_zone != "door_passage"
                            or fewshot_confidence is None
                            or fewshot_confidence < 0.9
                        )
                    ):
                        required = 1 if very_strong_temporal_center else 2
                    elif agreement == "fewshot_center_override":
                        required = 1
                    elif agreement == "full" and proto_zone == "center":
                        if very_strong_temporal_center and (
                            proto_confidence is None or proto_confidence >= 0.60
                        ):
                            required = 6
                        elif strong_temporal_center and (
                            proto_confidence is None or proto_confidence >= 0.57
                        ):
                            required = 8
                        else:
                            required = 12
                    elif agreement == "temporal_override" and strong_temporal_center and proto_zone == "center":
                        required = 8
                    else:
                        required = 12 if proto_zone == "center" else 6
                    if (
                        runtime_target_zone == "door"
                        and (strong_fewshot_door or not very_strong_fewshot_center)
                        and not (
                            strong_center_consensus
                            and (
                                fewshot_zone != "door_passage"
                                or fewshot_confidence is None
                                or fewshot_confidence < 0.9
                            )
                        )
                    ):
                        required = max(required, 12)
                elif stable_zone == "center" and candidate_zone == "door_passage":
                    if agreement == "full" and proto_zone == "door_passage":
                        required = 1 if temporal_score is not None and temporal_score <= -0.65 else 2
                    elif agreement in {"door_raw_assist", "door_raw_hold", "current_fw3_door_assist", "current_fw3_rssi_door", "current_fw3_temporal_door", "current_fw3_low_tvar_door", "current_fw3_tvar_shape_door", "current_fw3_door_hold", "current_live_fw3_door", "current_live_fw3_door_hold", "live_door_shadow"}:
                        required = 1
                    elif agreement in {"fewshot_door_gate", "fewshot_runtime_override"}:
                        required = 1
                    elif agreement in {"full", "temporal_override"} and proto_zone == "door_passage" and very_strong_temporal_door:
                        required = 1
                    elif agreement in {"full", "temporal_override"} and proto_zone == "door_passage":
                        required = 2
                    elif agreement == "temporal_override":
                        required = 4
                    elif agreement in {"prototype_override", "prototype_temporal"}:
                        required = 2
                    else:
                        required = 3
                if pending_zone == candidate_zone:
                    pending_count += 1
                else:
                    pending_zone = candidate_zone
                    pending_count = 1
                if pending_count >= required:
                    stable_zone = candidate_zone
                    pending_zone = None
                    pending_count = 0
                else:
                    hold_applied = True
                    candidate_zone = stable_zone

        if shadow_empty_scene and (candidate_zone == "door_passage" or stable_zone == "door_passage"):
            empty_safe_zone = (
                proto_zone
                if proto_zone == "center"
                else temporal_zone
                if temporal_zone == "center"
                else threshold_zone
                if threshold_zone == "center"
                else "center"
            )
            candidate_zone = empty_safe_zone
            stable_zone = empty_safe_zone
            pending_zone = None
            pending_count = 0
            hold_applied = False
            if agreement in {
                "live_door_shadow",
                "current_fw3_rssi_door",
                "current_fw3_temporal_door",
                "current_fw3_door_assist",
                "current_fw3_low_tvar_door",
                "current_fw3_tvar_shape_door",
                "current_fw3_door_hold",
                "current_live_fw3_door",
                "current_live_fw3_door_hold",
                "door_raw_assist",
                "door_raw_hold",
                "fewshot_door_gate",
                "fewshot_runtime_override",
            }:
                agreement = "empty_scene_suppressed"

        self._door_center_candidate_state = stable_zone
        self._door_center_candidate_pending_zone = pending_zone
        self._door_center_candidate_pending_count = pending_count

        confidence_values = [
            float(value) for value in (
                prototype.get("confidence"),
                temporal.get("prototype_confidence"),
            ) if value is not None
        ]
        confidence = min(confidence_values) if confidence_values else None
        return {
            "enabled": True,
            "available": True,
            "status": "shadow_live",
            "zone": candidate_zone,
            "candidate_zone": candidate_zone,
            "raw_candidate_zone": proposed_zone,
            "agreement": agreement,
            "prototype_zone": proto_zone,
            "prototype_zone_raw": proto_zone_raw,
            "temporal_zone": temporal_zone,
            "threshold_zone": threshold_zone,
            "fewshot_zone": fewshot_zone,
            "fewshot_confidence": round(fewshot_confidence, 4) if fewshot_confidence is not None else None,
            "door_gate_support": bool(door_gate_support),
            "door_signature_votes": int(door_signature_votes),
            "door_signature_active": bool(door_signature_active),
            "door_signature_consecutive": int(self._door_signature_consecutive),
            "door_signature_features": {
                "node02_rssi_mean": round(n02_rssi, 4),
                "node04_amp_mean": round(n04_amp, 4),
                "node06_tvar": round(n06_tvar, 4),
            },
            "raw_door_votes": int(raw_door_votes),
            "raw_door_assist": bool(raw_door_assist),
            "raw_door_hold": bool(raw_door_hold),
            "current_fw3_door_votes": int(current_fw3_door_votes),
            "current_fw3_door_assist": bool(current_fw3_door_assist),
            "current_fw3_low_tvar_door": bool(current_fw3_low_tvar_door),
            "current_fw3_door_hold": bool(current_fw3_door_hold),
            "current_fw3_tvar_shape_door": bool(current_fw3_tvar_shape_door),
            "current_live_fw3_door": bool(current_live_fw3_door),
            "current_live_fw3_door_hold": bool(current_live_fw3_door_hold),
            "live_door_shadow_ready": bool(live_door_shadow_ready),
            "live_door_shadow_zone": live_door.get("zone"),
            "live_door_shadow_zone_raw": live_door.get("zone_raw"),
            "live_door_shadow_confidence": round(float(live_door.get("confidence", 0.0) or 0.0), 6) if live_door else None,
            "live_door_shadow_probability": round(float(live_door.get("door_probability", 0.0) or 0.0), 6) if live_door else None,
            "shadow_empty_scene": bool(shadow_empty_scene),
            "center_locked_context": bool(center_locked_context),
            "door_center_amp_gap": round(door_center_amp_gap, 6),
            "door_tvar_mean": round(door_tvar_mean_live, 6),
            "center_tvar_mean": round(center_tvar_mean_live, 6),
            "tvar_median": round(tvar_median_live, 6),
            "door_phase_std_mean": round(door_phase_std_mean_live, 6),
            "phase_std_mean": round(phase_std_mean_live, 6),
            "door_amp_std_mean": round(door_amp_std_mean_live, 6),
            "temporal_score": round(temporal_score, 6) if temporal_score is not None else None,
            "confidence": round(confidence, 4) if confidence is not None else None,
            "prototype_confidence": round(proto_confidence, 4) if proto_confidence is not None else None,
            "prototype_margin": round(proto_margin, 6) if proto_margin is not None else None,
            "prototype_status": prototype.get("status"),
            "temporal_status": temporal.get("status"),
            "active_nodes": prototype.get("active_nodes") or temporal.get("active_nodes"),
            "pkt_count": prototype.get("pkt_count") or temporal.get("pkt_count"),
            "stable_zone": stable_zone,
            "pending_zone": pending_zone,
            "pending_count": pending_count,
            "hold_applied": hold_applied,
        }

    def _build_zone_shadow_route_status(self) -> dict[str, Any]:
        """Read-only center/door shadow route snapshot.

        This aggregates the already-built prototype, temporal, and candidate
        shadow surfaces into a single status object for `/api/v1/csi/status`
        without mutating production verdict fields.
        """
        prototype = self._fewshot_prototype_shadow if isinstance(self._fewshot_prototype_shadow, dict) else {}
        temporal = self._fewshot_temporal_overlay_shadow if isinstance(self._fewshot_temporal_overlay_shadow, dict) else {}
        candidate = self._door_center_candidate_shadow if isinstance(self._door_center_candidate_shadow, dict) else {}
        candidate_agreement = str(candidate.get("agreement") or "not_ready")
        candidate_zone = candidate.get("candidate_zone") or candidate.get("zone")
        raw_candidate_zone = candidate.get("raw_candidate_zone")
        stable_zone = candidate.get("stable_zone")
        pending_count = int(candidate.get("pending_count") or 0)
        production_binary = str(self.current.get("binary", "unknown") or "unknown").lower()
        production_target_zone = str(self.current.get("target_zone", "unknown") or "unknown").lower()
        production_motion_state = str(self.current.get("motion_state", "unknown") or "unknown").upper()
        truth_tvar = self.current.get("truth_tvar") if isinstance(self.current.get("truth_tvar"), dict) else {}
        truth_tvar_verdict = str(truth_tvar.get("truth_verdict", "unknown") or "unknown").lower()
        try:
            truth_tvar_median_runtime = float(truth_tvar.get("tvar_median", 0.0) or 0.0)
        except (TypeError, ValueError):
            truth_tvar_median_runtime = 0.0
        shadow_empty_scene = bool(
            candidate.get("shadow_empty_scene")
            or (
                (production_binary == "empty" or production_target_zone == "empty")
                and production_motion_state == "NO_MOTION"
                and (
                    truth_tvar_verdict == "empty"
                    or truth_tvar_median_runtime < 4.0
                )
            )
        )
        strong_live_door_override = bool(
            not shadow_empty_scene
            and (
                candidate_zone == "door_passage"
                or raw_candidate_zone == "door_passage"
            )
            and (
                candidate_agreement in {
                    "live_door_shadow",
                    "current_fw3_rssi_door",
                    "current_fw3_temporal_door",
                    "current_fw3_door_assist",
                    "current_fw3_low_tvar_door",
                    "current_fw3_tvar_shape_door",
                    "current_fw3_door_hold",
                    "current_live_fw3_door",
                    "current_live_fw3_door_hold",
                    "door_raw_assist",
                    "door_raw_hold",
                    "fewshot_door_gate",
                    "fewshot_runtime_override",
                }
                or (
                    bool(candidate.get("door_signature_active"))
                    and int(candidate.get("raw_door_votes") or 0) >= 3
                    and int(candidate.get("current_fw3_door_votes") or 0) >= 4
                    and pending_count >= 1
                )
            )
        )
        route_zone = (
            "door_passage"
            if strong_live_door_override
            else (
                stable_zone
                or candidate_zone
                or temporal.get("zone")
                or prototype.get("zone")
                or None
            )
        )
        route_agreement = candidate_agreement
        if shadow_empty_scene and route_zone == "door_passage":
            route_zone = (
                prototype.get("zone")
                or temporal.get("zone")
                or temporal.get("threshold_zone")
                or candidate.get("prototype_zone")
                or "center"
            )
            route_agreement = "empty_scene_suppressed"
        route_ready = bool(
            candidate.get("status") == "shadow_live"
            or temporal.get("status") == "shadow_live"
            or prototype.get("status") == "shadow_live"
        )
        production_snapshot = {
            "binary": self.current.get("binary"),
            "target_zone": self.current.get("target_zone"),
            "zone_source": self.current.get("zone_source"),
            "decision_model_backend": self.current.get("decision_model_backend"),
            "coordinate_source": self.current.get("coordinate_source"),
        }
        return {
            "enabled": bool(FEWSHOT_PROTOTYPE_SHADOW_ENABLED or FEWSHOT_TEMPORAL_OVERLAY_ENABLED),
            "shadow_only": True,
            "status": "shadow_live" if route_ready else "awaiting_first_window",
            "route_ready": route_ready,
            "route_zone": route_zone,
            "route_agreement": route_agreement,
            "route_confidence": candidate.get("confidence"),
            "prototype_zone": prototype.get("zone"),
            "temporal_zone": temporal.get("zone"),
            "threshold_zone": temporal.get("threshold_zone"),
            "candidate_zone": candidate.get("candidate_zone"),
            "candidate_stable_zone": candidate.get("stable_zone"),
            "candidate_raw_zone": raw_candidate_zone,
            "strong_live_door_override": strong_live_door_override,
            "shadow_empty_scene": shadow_empty_scene,
            "production_snapshot": production_snapshot,
            "production_unchanged": True,
            "last_update_source": "door_center_candidate_shadow",
            "last_sample_t": candidate.get("t") or temporal.get("t") or prototype.get("t"),
        }

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
                "freshest_last_seen_sec": None,
                "stalest_last_seen_sec": None,
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
        freshest_seen = min(seen_ages) if seen_ages else None
        stalest_seen = max(seen_ages) if seen_ages else None
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
            "freshest_last_seen_sec": freshest_seen,
            "stalest_last_seen_sec": stalest_seen,
            # Legacy names kept for compatibility; values now match the names.
            "latest_last_seen_sec": freshest_seen,
            "oldest_last_seen_sec": stalest_seen,
        }

    @staticmethod
    def _resolve_runtime_status(
        *,
        model_loaded: bool,
        listener_running: bool,
        csv_listener_running: bool,
        prediction_task_running: bool,
        warmup_active: bool,
        dropout_summary: dict[str, Any],
    ) -> dict[str, str]:
        core_online = int(dropout_summary.get("core_online_count", 0) or 0)
        core_degraded = int(dropout_summary.get("core_degraded_count", 0) or 0)
        core_offline = int(dropout_summary.get("core_offline_count", 0) or 0)

        if not model_loaded:
            return {
                "status": "model_not_loaded",
                "status_reason": "binary_model_missing",
                "status_message": "CSI runtime model is not loaded.",
            }
        if not listener_running and not prediction_task_running:
            return {
                "status": "inactive",
                "status_reason": "runtime_not_started",
                "status_message": "CSI runtime is not started.",
            }
        if listener_running and not prediction_task_running:
            return {
                "status": "degraded",
                "status_reason": "prediction_loop_inactive",
                "status_message": "CSI listener is up, but the prediction loop is not running.",
            }
        if prediction_task_running and not listener_running:
            return {
                "status": "degraded",
                "status_reason": "listener_not_running",
                "status_message": "CSI prediction loop is active without a live UDP listener.",
            }
        if not csv_listener_running:
            return {
                "status": "degraded",
                "status_reason": "csv_listener_down",
                "status_message": "CSI runtime is active, but the CSV UDP listener is down.",
            }
        if core_online < 3:
            return {
                "status": "degraded",
                "status_reason": "insufficient_core_nodes",
                "status_message": "Fewer than 3 core CSI nodes are online.",
            }
        if core_degraded > 0 or core_offline > 0:
            return {
                "status": "degraded",
                "status_reason": "core_node_dropout",
                "status_message": "One or more core CSI nodes are degraded or offline.",
            }
        if warmup_active:
            return {
                "status": "warming_up",
                "status_reason": "node_warmup_active",
                "status_message": "CSI runtime is warming up after node reconnect.",
            }
        return {
            "status": "healthy",
            "status_reason": "runtime_ready",
            "status_message": "CSI runtime is healthy.",
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
        if OFFLINE_REGIME_SHADOW_ENABLED and not self._offline_regime_loaded:
            try:
                self._load_offline_regime_shadow()
            except Exception:
                pass
        if EMPTY_SUBREGIME_SHADOW_ENABLED and not self._empty_subregime_loaded:
            try:
                self._load_empty_subregime_shadow()
            except Exception:
                pass
        if DEEP_RIGHT_SHADOW_ENABLED and not self._deep_right_shadow_loaded:
            try:
                self._load_deep_right_shadow()
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
        self._sync_active_model_contract()
        listener_running = bool(self._running or self._transport is not None)
        prediction_task_running = bool(self._prediction_task and not self._prediction_task.done())
        status = {
            "running": listener_running,
            "listener_running": listener_running,
            "csv_listener_running": self._csv_transport is not None,
            "prediction_task_running": prediction_task_running,
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
        v8_runtime_shadow = self._get_latest_v8_shadow()
        if self._v8_loaded and v8_runtime_shadow:
            status["v8_shadow"] = v8_runtime_shadow
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
        if self._offline_regime_loaded and self._offline_regime_shadow:
            status["offline_regime_shadow"] = self._offline_regime_shadow
        elif OFFLINE_REGIME_SHADOW_ENABLED:
            status["offline_regime_shadow"] = {
                "candidate_name": OFFLINE_REGIME_CANDIDATE_NAME,
                "loaded": self._offline_regime_loaded,
                "status": "awaiting_first_window" if self._offline_regime_loaded else "not_loaded",
                "feature_count": len(self._offline_regime_feature_cols),
                "analysis_path": str(self._offline_regime_analysis_path) if self._offline_regime_analysis_path else None,
                "verdict": dict(self._offline_regime_verdict),
            }
        if self._empty_subregime_loaded and self._empty_subregime_shadow:
            status["empty_subregime_shadow"] = self._empty_subregime_shadow
        elif EMPTY_SUBREGIME_SHADOW_ENABLED:
            status["empty_subregime_shadow"] = {
                "candidate_name": EMPTY_SUBREGIME_CANDIDATE_NAME,
                "loaded": self._empty_subregime_loaded,
                "status": "awaiting_first_window" if self._empty_subregime_loaded else "not_loaded",
                "feature_count": len(self._empty_subregime_feature_names),
                "analysis_path": str(self._empty_subregime_analysis_path) if self._empty_subregime_analysis_path else None,
                "verdict": dict(self._empty_subregime_verdict),
            }
        if self._deep_right_shadow_loaded and self._deep_right_shadow:
            status["deep_right_shadow"] = self._deep_right_shadow
        elif DEEP_RIGHT_SHADOW_ENABLED:
            status["deep_right_shadow"] = {
                "candidate_name": DEEP_RIGHT_SHADOW_CANDIDATE_NAME,
                "loaded": self._deep_right_shadow_loaded,
                "status": "awaiting_first_window" if self._deep_right_shadow_loaded else "not_loaded",
                "feature_count": len(self._deep_right_shadow_feature_names),
                "trigger_threshold": round(float(self._deep_right_shadow_trigger_threshold), 4),
                "analysis_path": str(self._deep_right_shadow_analysis_path) if self._deep_right_shadow_analysis_path else None,
                "verdict": dict(self._deep_right_shadow_verdict),
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

        # ── Shallow coordinate shadow status ──────────────────────────
        if self._shallow_coord_shadow_loaded and self._shallow_coord_shadow:
            status["shallow_coord_shadow"] = {
                **self._shallow_coord_shadow,
                "source": "v48_shallow_r1_shadow",
            }
        elif self._shallow_coord_shadow_loaded:
            status["shallow_coord_shadow"] = {
                "loaded": True,
                "status": "awaiting_first_window",
                "source": "v48_shallow_r1_shadow",
                "model_path": self._shallow_coord_shadow_path,
            }
        else:
            status["shallow_coord_shadow"] = {
                "loaded": False,
                "status": "not_loaded",
                "source": "v48_shallow_r1_shadow",
                "model_path": None,
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

        # ── Prototype / temporal door-center shadows (standalone live-safe) ──
        if FEWSHOT_PROTOTYPE_SHADOW_ENABLED:
            try:
                proto_shadow = self._ensure_fewshot_prototype_shadow_ready()
                proto_status = proto_shadow.get_status() if hasattr(proto_shadow, "get_status") else dict(proto_shadow)
                proto_last = self._fewshot_prototype_shadow if self._fewshot_prototype_shadow else proto_status.get("last_prediction")
                status["prototype_zone_shadow"] = {
                    **proto_status,
                    "last_prediction": proto_last,
                    "zone": proto_last.get("zone") if isinstance(proto_last, dict) else proto_status.get("zone"),
                    "zone_raw": proto_last.get("zone_raw") if isinstance(proto_last, dict) else proto_status.get("zone_raw"),
                    "confidence": proto_last.get("confidence") if isinstance(proto_last, dict) else proto_status.get("confidence"),
                    "score_margin": proto_last.get("score_margin") if isinstance(proto_last, dict) else proto_status.get("score_margin"),
                    "winner_score": proto_last.get("winner_score") if isinstance(proto_last, dict) else proto_status.get("winner_score"),
                    "runner_up_score": proto_last.get("runner_up_score") if isinstance(proto_last, dict) else proto_status.get("runner_up_score"),
                    "active_nodes": proto_last.get("active_nodes") if isinstance(proto_last, dict) else proto_status.get("active_nodes"),
                    "pkt_count": proto_last.get("pkt_count") if isinstance(proto_last, dict) else proto_status.get("pkt_count"),
                    "t": proto_last.get("t") if isinstance(proto_last, dict) else proto_status.get("t"),
                }
            except Exception as error:
                status["prototype_zone_shadow"] = {
                    "enabled": True,
                    "active": False,
                    "status": "load_failed",
                    "bundle_path": str(FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH),
                    "last_error": str(error),
                }
        else:
            status["prototype_zone_shadow"] = {
                "enabled": False,
                "active": False,
                "status": "disabled",
                "bundle_path": str(FEWSHOT_PROTOTYPE_SHADOW_BUNDLE_PATH),
            }

        if FEWSHOT_TEMPORAL_OVERLAY_ENABLED:
            try:
                overlay = self._ensure_fewshot_temporal_overlay_ready()
                overlay_stub = {
                    "enabled": True,
                    "loaded": overlay is not None,
                    "status": "awaiting_first_window" if overlay is not None else "not_loaded",
                    "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
                }
                if overlay is not None:
                    overlay_stub.update({
                        "consumer": "temporal_directional_zone_overlay",
                        "score_family": overlay.rule.score_family,
                        "threshold": round(float(overlay.rule.threshold), 6),
                        "margin": round(float(overlay.rule.margin), 6),
                        "dwell": int(overlay.rule.dwell),
                        "bootstrap_n": int(overlay.rule.bootstrap_n),
                    })
                status["temporal_zone_overlay_shadow"] = (
                    self._fewshot_temporal_overlay_shadow
                    if self._fewshot_temporal_overlay_shadow
                    else overlay_stub
                )
            except Exception as error:
                status["temporal_zone_overlay_shadow"] = {
                    "enabled": True,
                    "loaded": False,
                    "status": "load_failed",
                    "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
                    "last_error": str(error),
                }
        else:
            status["temporal_zone_overlay_shadow"] = {
                "enabled": False,
                "loaded": False,
                "status": "disabled",
                "summary_path": str(FEWSHOT_TEMPORAL_OVERLAY_SUMMARY_PATH),
            }

        status["door_center_candidate_shadow"] = (
            self._door_center_candidate_shadow
            if self._door_center_candidate_shadow
            else {
                "enabled": FEWSHOT_PROTOTYPE_SHADOW_ENABLED or FEWSHOT_TEMPORAL_OVERLAY_ENABLED,
                "available": False,
                "status": "awaiting_first_window"
                if (FEWSHOT_PROTOTYPE_SHADOW_ENABLED or FEWSHOT_TEMPORAL_OVERLAY_ENABLED)
                else "disabled",
                "candidate_zone": None,
                "agreement": "not_ready",
            }
        )
        status["zone_shadow_route"] = self._build_zone_shadow_route_status()

        # ── Coord stabilization shadow status ──────────────────────────
        try:
            from .coord_stabilization_service import coord_stabilization_service as _coord_stab
            status["coord_stabilization"] = self.current.get("coord_stabilization", {})
            status["coord_diag"] = getattr(self, '_coord_diag', {})
            status["rssi_zone"] = getattr(self, '_last_rssi_zone', None)
            status["n02_rssi_ema"] = round(getattr(self, '_n02_rssi_ema', 0.0), 2)
            _vh = getattr(self, '_rssi_vote_history', [])
            status["rssi_votes"] = f"{sum(1 for v in _vh if v=='center')}c/{sum(1 for v in _vh if v=='door')}d/{len(_vh)}"
        except Exception:
            pass

        # ── Node health (keepalive + CSI packet tracking) ─────────────
        nodes = self.get_node_health()
        status["nodes"] = nodes
        dropout_summary = self._build_dropout_summary(nodes)
        status["dropout_summary"] = dropout_summary
        status.update(
            self._resolve_runtime_status(
                model_loaded=bool(self.binary_model is not None),
                listener_running=listener_running,
                csv_listener_running=bool(self._csv_transport is not None),
                prediction_task_running=prediction_task_running,
                warmup_active=bool(warmup_nodes),
                dropout_summary=dropout_summary,
            )
        )

        # ── V23: Empty baseline calibration status ────────────────────
        status["empty_baseline"] = self.get_baseline_status()
        status["empty_rescue_guard"] = self.current.get("empty_rescue_guard")

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
