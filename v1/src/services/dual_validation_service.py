"""
Dual Validation Service
========================
Validates video-annotated segments against CSI signal patterns.

Pipeline:
1. Load gold annotations from JSON files (manual_annotations_v1.json)
2. Load corresponding CSI capture data (ndjson.gz files from temp/captures/)
3. Extract CSI features for each gold-annotated time window
4. Build zone fingerprints: statistical profiles of CSI features per zone
5. Validate segments by comparing CSI features against zone fingerprints

Video is the PRIMARY truth source. CSI is VERIFICATION only.
Conflicts are always recorded, never masked.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from scipy.spatial.distance import cosine as cosine_distance
from scipy.stats import entropy, kurtosis, skew

from .csi_node_inventory import CSI_NODE_INVENTORY, NODE_IPS, NODE_NAMES

logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parents[3]

# CSI parsing constants (mirrored from csi_prediction_service.py)
# V1/V2 firmware packet format constants
CSI_MAGIC_V1 = 0xC5110001
CSI_MAGIC_V2 = 0xC5110002
CSI_HEADER_SIZE_V1 = 20  # V1: 20-byte header, no phase data
CSI_HEADER_SIZE_V2 = 24  # V2: 24-byte header (byte[20]=flags, [21-22]=phase_offset, [23]=reserved)
CSI_HEADER = CSI_HEADER_SIZE_V1  # backward-compat alias
RSSI_OFFSET = 16

# Feature keys used for zone fingerprinting (per-node).
# These are the most zone-discriminative features based on
# spatial signal propagation differences across garage zones.
FINGERPRINT_FEATURE_KEYS = [
    "amp_mean",
    "sc_var_mean",
    "rssi_mean",
    "motion_mean",
    "tvar",
    "diff1",
]

# Extended features for transition↔door discrimination.
# Shadow nodes (n05, n07) see the person clearly at door but lose them in transition.
# Inter-node ratios capture spatial geometry differences between zones.
EXTENDED_FEATURE_KEYS = [
    "pps",               # packets-per-second (shadow dropout indicator)
    "shadow_pps_ratio",  # shadow_avg_pps / core_avg_pps (per window, global)
]

# Node pairs for inter-node amplitude ratios that discriminate zones.
# n01/n02 and n02/n06 shift between door and transition zones.
RATIO_PAIRS = [
    ("node01", "node02"),
    ("node02", "node06"),
    ("node05", "node01"),  # shadow/core — drops in transition
    ("node07", "node01"),  # shadow/core — drops in transition
]

CORE_NODE_IDS = {"node01", "node02", "node03", "node04"}
SHADOW_NODE_IDS = {"node05", "node06", "node07"}

# Validation thresholds (calibrated for z-score normalized cosine similarity)
# With z-score normalization, cosine sim range is ~[-0.5, 0.6] instead of [0.9, 1.0]
SIMILARITY_VALIDATED_THRESHOLD = 0.15   # z-norm cosine sim >= this -> validated
SIMILARITY_AMBIGUOUS_THRESHOLD = 0.05   # z-norm cosine sim < this -> ambiguous
MARGIN_AMBIGUOUS_THRESHOLD = 0.08       # top-2 margin < this -> ambiguous

# Window size for feature extraction (seconds)
FEATURE_WINDOW_SEC = 2.0


# ── CSI Parsing (mirrors CsiPredictionService._parse_csi) ─────────────


def _normalize_to_64(amp: np.ndarray, phase: np.ndarray | None) -> tuple:
    """Normalize subcarrier arrays to exactly 64 subcarriers."""
    n = len(amp)
    if n == 64:
        return amp, phase
    elif n > 64:
        k = n // 64
        usable = 64 * k
        a64 = amp[:usable].reshape(64, k).mean(axis=1)
        p64 = phase[:usable:k][:64] if phase is not None else None
    else:
        a64 = np.pad(amp, (0, 64 - n), mode="constant")
        p64 = np.pad(phase, (0, 64 - n), mode="constant") if phase is not None else None
    return a64, p64


def parse_csi_payload(b64_payload: str) -> tuple[np.ndarray | None, np.ndarray | None, float]:
    """
    Parse a base64-encoded CSI payload into amplitude, phase arrays, and RSSI.

    Supports V1 (magic=0xC5110001, 20-byte header) and V2 (magic=0xC5110002,
    24-byte header with flags/phase_offset fields) firmware packet formats.

    Returns:
        (amp_64, phase_64, rssi) or (None, None, 0.0) if parsing fails.
    """
    import struct as _struct
    raw = base64.b64decode(b64_payload)
    if len(raw) < 4:
        return None, None, 0.0

    magic = _struct.unpack_from('<I', raw, 0)[0]
    if magic == CSI_MAGIC_V2:
        # V2 format: 24-byte header
        # byte[20] = flags (bit0 = has_phase)
        # bytes[21-22] = phase_offset (uint16, offset from header end to phase data)
        # byte[23] = reserved
        header_size = CSI_HEADER_SIZE_V2
        if len(raw) < header_size + 40:
            return None, None, 0.0
        flags = raw[20]
        has_hw_phase = bool(flags & 0x01)
        phase_offset_field = _struct.unpack_from('<H', raw, 21)[0]
        iq_end = header_size + phase_offset_field if has_hw_phase else len(raw)
        iq_block = raw[header_size:iq_end][:256]
    elif magic == CSI_MAGIC_V1:
        # V1 format: 20-byte header, no dedicated phase data block
        header_size = CSI_HEADER_SIZE_V1
        if len(raw) < header_size + 40:
            return None, None, 0.0
        iq_block = raw[header_size : header_size + 256]
    else:
        # Unknown magic — fall back to legacy V1 behaviour
        header_size = CSI_HEADER_SIZE_V1
        if len(raw) < header_size + 40:
            return None, None, 0.0
        iq_block = raw[header_size : header_size + 256]

    # Extract RSSI from header
    rssi = 0.0
    if len(raw) > RSSI_OFFSET:
        rssi_byte = raw[RSSI_OFFSET]
        rssi = float(rssi_byte) - 256 if rssi_byte > 127 else float(rssi_byte)

    n = len(iq_block) // 2
    if n < 40:
        return None, None, rssi

    arr = np.frombuffer(iq_block[: n * 2], dtype=np.int8).reshape(-1, 2)
    i_v = arr[:, 0].astype(np.float32)
    q_v = arr[:, 1].astype(np.float32)
    amp = np.sqrt(i_v ** 2 + q_v ** 2)
    phase = np.arctan2(q_v, i_v)
    a64, p64 = _normalize_to_64(amp, phase)
    return a64, p64, rssi


# ── Capture Data Loading ──────────────────────────────────────────────


def load_ndjson_capture(path: Path) -> list[dict]:
    """Load packets from a gzipped ndjson capture file."""
    packets = []
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    packets.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning(f"Failed to load capture {path}: {e}")
    return packets


def find_capture_files(captures_dir: Path, recording_label: str) -> list[Path]:
    """
    Find all ndjson.gz capture chunks matching a recording label.

    Recording labels are matched by prefix against chunk filenames.
    E.g. recording_label="v26_shadow_live_test_20260327" matches
    "v26_shadow_live_test_20260327_chunk0001_*.ndjson.gz".
    """
    matches = []
    if not captures_dir.exists():
        return matches

    # Try exact label prefix match
    for p in sorted(captures_dir.glob("*.ndjson.gz")):
        if p.name.startswith(recording_label):
            matches.append(p)

    # If no match, try partial match (recording label may be a substring)
    if not matches:
        label_parts = recording_label.replace("_cam", "").split("_")
        # Use first 3-4 parts as search key
        search_key = "_".join(label_parts[:4]) if len(label_parts) >= 4 else recording_label
        for p in sorted(captures_dir.glob("*.ndjson.gz")):
            if search_key in p.name:
                matches.append(p)

    return matches


# ── Feature Extraction ────────────────────────────────────────────────


def extract_features_from_packets(
    packets: list[dict],
    t_start_ns: int,
    t_end_ns: int,
) -> dict[str, float] | None:
    """
    Extract per-node CSI features for a time window from raw packets.

    Mirrors the feature extraction in CsiPredictionService._extract_window_features
    but operates on stored packets rather than a live buffer.

    Args:
        packets: List of packet dicts with ts_ns, src_ip, payload_b64.
        t_start_ns: Window start timestamp in nanoseconds.
        t_end_ns: Window end timestamp in nanoseconds.

    Returns:
        Feature dict keyed by "{node_id}_{feature_name}", or None if
        no valid data in the window.
    """
    # Group packets by node IP within the time window
    node_packets: dict[str, list[tuple[int, float, np.ndarray, np.ndarray]]] = defaultdict(list)

    for pkt in packets:
        ts_ns = int(pkt["ts_ns"])
        if ts_ns < t_start_ns or ts_ns >= t_end_ns:
            continue

        ip = pkt["src_ip"]
        amp, phase, rssi = parse_csi_payload(pkt["payload_b64"])
        if amp is None:
            continue

        node_packets[ip].append((ts_ns, rssi, amp, phase))

    if not node_packets:
        return None

    features: dict[str, float] = {}
    active_nodes = 0

    for entry in CSI_NODE_INVENTORY:
        ip = str(entry["ip"])
        node_id = str(entry["node_id"])
        pkts = node_packets.get(ip, [])

        if len(pkts) < 5:
            # Zero-fill features for inactive/sparse nodes
            for key in FINGERPRINT_FEATURE_KEYS:
                features[f"{node_id}_{key}"] = 0.0
            features[f"{node_id}_pps"] = 0.0
            features[f"{node_id}_std"] = 0.0
            continue

        active_nodes += 1
        rssi_vals = np.array([r for _, r, _, _ in pkts], dtype=np.float32)
        amp_mat = np.array([a for _, _, a, _ in pkts], dtype=np.float32)
        amps = amp_mat.mean(axis=1)  # mean across subcarriers per packet

        duration_sec = (t_end_ns - t_start_ns) / 1e9
        pps = len(pkts) / max(duration_sec, 0.1)
        motion_mean = float(np.std(np.diff(amps))) if len(amps) > 1 else 0.0

        features[f"{node_id}_amp_mean"] = float(np.mean(amps))
        features[f"{node_id}_std"] = float(np.std(amps))
        features[f"{node_id}_rssi_mean"] = float(np.mean(rssi_vals))
        features[f"{node_id}_motion_mean"] = motion_mean
        features[f"{node_id}_pps"] = pps

        # Temporal variance
        tv = float(np.var(np.diff(amps))) if len(amps) > 1 else 0.0
        features[f"{node_id}_tvar"] = tv

        # First-order difference (mean absolute change)
        d1 = np.abs(np.diff(amps))
        features[f"{node_id}_diff1"] = float(np.mean(d1)) if len(d1) > 0 else 0.0

        # Subcarrier variance mean
        sc_var = amp_mat.var(axis=0)
        features[f"{node_id}_sc_var_mean"] = float(sc_var.mean())

    if active_nodes == 0:
        return None

    features["_active_nodes"] = float(active_nodes)

    # ── Extended features: inter-node ratios ──
    for nid_a, nid_b in RATIO_PAIRS:
        amp_a = features.get(f"{nid_a}_amp_mean", 0.0)
        amp_b = features.get(f"{nid_b}_amp_mean", 0.0)
        ratio = amp_a / max(amp_b, 0.01)
        features[f"ratio_{nid_a}_{nid_b}"] = ratio

    # ── Extended features: shadow node availability ──
    core_pps = [features.get(f"{n}_pps", 0.0) for n in sorted(CORE_NODE_IDS)]
    shadow_pps = [features.get(f"{n}_pps", 0.0) for n in sorted(SHADOW_NODE_IDS)]
    avg_core_pps = np.mean(core_pps) if core_pps else 0.0
    avg_shadow_pps = np.mean(shadow_pps) if shadow_pps else 0.0
    features["_shadow_pps_ratio"] = float(avg_shadow_pps / max(avg_core_pps, 0.01))

    return features


def extract_windows_for_segment(
    packets: list[dict],
    session_start_ns: int,
    seg_start_sec: float,
    seg_end_sec: float,
    window_sec: float = FEATURE_WINDOW_SEC,
) -> list[dict[str, float]]:
    """
    Extract feature vectors for all windows within an annotated segment.

    Slides a window across the segment and extracts features for each.

    Args:
        packets: All packets for the session.
        session_start_ns: Timestamp of the first packet (nanoseconds).
        seg_start_sec: Segment start offset in seconds from session start.
        seg_end_sec: Segment end offset in seconds from session start.
        window_sec: Window duration in seconds.

    Returns:
        List of feature dicts, one per window.
    """
    windows = []
    t = seg_start_sec

    while t + window_sec <= seg_end_sec:
        t_start_ns = session_start_ns + int(t * 1e9)
        t_end_ns = session_start_ns + int((t + window_sec) * 1e9)

        feat = extract_features_from_packets(packets, t_start_ns, t_end_ns)
        if feat is not None:
            windows.append(feat)

        t += window_sec  # non-overlapping windows for fingerprinting stability

    return windows


# ── Zone Fingerprinting ───────────────────────────────────────────────


class ZoneFingerprint:
    """Statistical profile of CSI features for a given zone."""

    def __init__(self, zone_name: str):
        self.zone_name = zone_name
        self._feature_values: dict[str, list[float]] = defaultdict(list)
        self._n_windows = 0

    def add_window(self, features: dict[str, float]) -> None:
        """Accumulate feature values from one window."""
        for key, val in features.items():
            if key == "_active_nodes":
                continue
            self._feature_values[key].append(val)
        self._n_windows += 1

    @property
    def n_windows(self) -> int:
        return self._n_windows

    def compute_stats(self) -> dict[str, dict[str, float]]:
        """Compute mean and std for all accumulated features."""
        stats = {}
        for key, vals in self._feature_values.items():
            arr = np.array(vals)
            stats[key] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "n": len(vals),
            }
        return stats

    def to_vector(self, feature_keys: list[str] | None = None) -> np.ndarray:
        """
        Return the fingerprint as a mean-feature vector for similarity computation.

        Args:
            feature_keys: Ordered list of feature keys. If None, uses all keys
                sorted alphabetically.

        Returns:
            1D numpy array of mean feature values.
        """
        if feature_keys is None:
            feature_keys = sorted(self._feature_values.keys())

        vec = []
        for key in feature_keys:
            vals = self._feature_values.get(key, [])
            vec.append(float(np.mean(vals)) if vals else 0.0)

        return np.array(vec, dtype=np.float64)

    def to_dict(self) -> dict:
        """Serialize the fingerprint for JSON output."""
        return {
            "zone": self.zone_name,
            "n_windows": self._n_windows,
            "stats": self.compute_stats(),
        }


def build_fingerprint_feature_keys(
    node_ids: list[str],
    mode: str = "7node",
) -> list[str]:
    """
    Build the canonical ordered list of feature keys for fingerprint vectors.

    Args:
        node_ids: List of node IDs to include.
        mode: "7node" includes shadow features and ratios,
              "4node" uses only core-node features (no shadow ratios).
    """
    if mode == "4node":
        core_ids = sorted(n for n in node_ids if n in CORE_NODE_IDS)
    else:
        core_ids = sorted(node_ids)

    keys = []
    for node_id in core_ids:
        for feat_name in FINGERPRINT_FEATURE_KEYS:
            keys.append(f"{node_id}_{feat_name}")
        keys.append(f"{node_id}_pps")

    if mode == "7node":
        # Inter-node amplitude ratios (including shadow)
        for nid_a, nid_b in RATIO_PAIRS:
            keys.append(f"ratio_{nid_a}_{nid_b}")
        # Global shadow availability
        keys.append("_shadow_pps_ratio")
    else:
        # 4-node: only core-to-core ratios
        core_ratios = [
            (a, b) for a, b in RATIO_PAIRS
            if a in CORE_NODE_IDS and b in CORE_NODE_IDS
        ]
        for nid_a, nid_b in core_ratios:
            keys.append(f"ratio_{nid_a}_{nid_b}")

    return keys


# ── Session-level Feature Normalization ───────────────────────────────


def normalize_session_features(
    windows: list[dict[str, float]],
) -> list[dict[str, float]]:
    """
    Normalize feature windows within a session to zero-mean unit-variance.

    This removes domain shift caused by different routers, firmware,
    or environmental conditions producing different absolute CSI values.
    The relative pattern across nodes and features is preserved.

    Args:
        windows: List of feature dicts from extract_windows_for_segment().

    Returns:
        New list of feature dicts with normalized values.
    """
    if len(windows) < 2:
        return windows

    # Collect all feature keys (excluding metadata)
    all_keys = set()
    for w in windows:
        all_keys.update(k for k in w if k != "_active_nodes")

    # Compute per-feature mean and std across all windows in this session
    stats: dict[str, tuple[float, float]] = {}
    for key in all_keys:
        vals = [w.get(key, 0.0) for w in windows]
        arr = np.array(vals)
        mu = float(np.mean(arr))
        sigma = float(np.std(arr))
        if sigma < 1e-10:
            sigma = 1.0
        stats[key] = (mu, sigma)

    # Normalize each window
    normed = []
    for w in windows:
        nw = {}
        for key in all_keys:
            mu, sigma = stats[key]
            nw[key] = (w.get(key, 0.0) - mu) / sigma
        if "_active_nodes" in w:
            nw["_active_nodes"] = w["_active_nodes"]
        normed.append(nw)

    return normed


# ── Similarity Computation ────────────────────────────────────────────


def compute_cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """
    Compute cosine similarity between two feature vectors.

    Returns a value in [0, 1] where 1 = identical direction.
    Returns 0.0 if either vector is all-zero.
    """
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0

    # scipy cosine_distance returns 1 - similarity, so we invert
    try:
        return float(1.0 - cosine_distance(vec_a, vec_b))
    except ValueError:
        return 0.0


def compute_normalization_stats(
    fingerprints: dict[str, "ZoneFingerprint"],
    feature_keys: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Compute per-feature mean and std across all zone fingerprint vectors."""
    vecs = []
    for fp in fingerprints.values():
        vecs.append(fp.to_vector(feature_keys))
    if not vecs:
        d = len(feature_keys)
        return np.zeros(d), np.ones(d)
    mat = np.array(vecs)
    mu = mat.mean(axis=0)
    sigma = mat.std(axis=0)
    sigma[sigma < 1e-10] = 1.0  # avoid division by zero
    return mu, sigma


def find_closest_zone(
    feature_vec: np.ndarray,
    fingerprints: dict[str, ZoneFingerprint],
    feature_keys: list[str],
    norm_stats: tuple[np.ndarray, np.ndarray] | None = None,
) -> tuple[str, float, dict[str, float]]:
    """
    Find the zone whose fingerprint is most similar to the given feature vector.

    Uses z-score normalization so that all features contribute equally
    to cosine similarity regardless of their natural scale.

    Args:
        feature_vec: Feature vector for the segment/window.
        fingerprints: Dict of zone_name -> ZoneFingerprint.
        feature_keys: Ordered feature key list for consistent vectorization.
        norm_stats: Optional (mean, std) arrays for z-score normalization.
            If None, computed on the fly from fingerprints.

    Returns:
        (closest_zone_name, similarity_score, all_similarities)
    """
    if norm_stats is None:
        norm_stats = compute_normalization_stats(fingerprints, feature_keys)
    mu, sigma = norm_stats

    # Normalize the input vector
    norm_input = (feature_vec - mu) / sigma

    similarities = {}
    for zone_name, fp in fingerprints.items():
        fp_vec = fp.to_vector(feature_keys)
        norm_fp = (fp_vec - mu) / sigma
        sim = compute_cosine_similarity(norm_input, norm_fp)
        similarities[zone_name] = sim

    if not similarities:
        return "unknown", 0.0, {}

    closest = max(similarities, key=similarities.get)
    return closest, similarities[closest], similarities


# ── Validation Logic ──────────────────────────────────────────────────


def _normalize_zone_label(label: str) -> str:
    """
    Normalize zone labels for comparison.

    Handles variants like 'door_passage_inside' -> 'door_passage',
    'door_passage' -> 'door_passage', etc.
    """
    label = label.lower().strip()
    # Map common variants to canonical forms used in fingerprinting
    mapping = {
        "door_passage_inside": "door_passage_inside",
        "door_passage": "door_passage_inside",
        "door": "door_passage_inside",
        "center": "center",
        "transition": "transition",
        "deep": "deep",
        "mixed": "mixed",
    }
    return mapping.get(label, label)


def validate_segment(
    segment_features: list[dict[str, float]],
    video_label: str,
    fingerprints: dict[str, ZoneFingerprint],
    feature_keys: list[str],
    fewshot_hint: str | None = None,
    fewshot_conf: float | None = None,
) -> dict[str, Any]:
    """
    Validate a single segment against zone fingerprints.

    Args:
        segment_features: List of feature dicts for windows in the segment.
        video_label: The video-annotated zone label (PRIMARY truth).
        fingerprints: Built zone fingerprints.
        feature_keys: Ordered feature keys for vectorization.
        fewshot_hint: Optional fewshot zone prediction.
        fewshot_conf: Optional fewshot confidence.

    Returns:
        Validation result dict with status, similarities, etc.
    """
    if not segment_features:
        return {
            "csi_closest_zone": None,
            "csi_similarity": 0.0,
            "all_similarities": {},
            "status": "ambiguous",
            "conflict_reason": "no CSI data available for segment time window",
        }

    # Average feature vectors across all windows in the segment
    all_keys = set()
    for feat in segment_features:
        all_keys.update(k for k in feat.keys() if k != "_active_nodes")

    avg_features = {}
    for key in all_keys:
        vals = [f.get(key, 0.0) for f in segment_features]
        avg_features[key] = float(np.mean(vals))

    # Build feature vector using the canonical key order
    feature_vec = np.array(
        [avg_features.get(k, 0.0) for k in feature_keys],
        dtype=np.float64,
    )

    # Compute normalization stats once (caller can cache for batch)
    norm_stats = compute_normalization_stats(fingerprints, feature_keys)

    closest_zone, best_sim, all_sims = find_closest_zone(
        feature_vec, fingerprints, feature_keys, norm_stats=norm_stats
    )

    # Determine validation status
    norm_video = _normalize_zone_label(video_label)
    norm_closest = _normalize_zone_label(closest_zone)

    # Skip validation for 'mixed' labels -- they span multiple zones
    if norm_video == "mixed":
        return {
            "csi_closest_zone": closest_zone,
            "csi_similarity": round(best_sim, 4),
            "all_similarities": {k: round(v, 4) for k, v in all_sims.items()},
            "status": "validated",
            "conflict_reason": None,
        }

    # Compute similarity to the video-assigned zone
    video_zone_sim = all_sims.get(norm_video, 0.0)
    # Also check un-normalized video label
    if video_zone_sim == 0.0 and video_label in all_sims:
        video_zone_sim = all_sims[video_label]

    # Sort similarities descending to check margin
    sorted_sims = sorted(all_sims.values(), reverse=True)
    margin = (sorted_sims[0] - sorted_sims[1]) if len(sorted_sims) >= 2 else sorted_sims[0]

    status: str
    conflict_reason: str | None = None

    if norm_video == norm_closest:
        # Video and CSI agree
        if best_sim >= SIMILARITY_VALIDATED_THRESHOLD:
            status = "validated"
        elif best_sim >= SIMILARITY_AMBIGUOUS_THRESHOLD:
            status = "validated"  # agrees but weak signal
        else:
            status = "ambiguous"
            conflict_reason = (
                f"video and CSI agree on {video_label} but similarity is low "
                f"(sim={best_sim:.3f})"
            )
    else:
        # Video and CSI disagree
        if best_sim < SIMILARITY_AMBIGUOUS_THRESHOLD:
            status = "ambiguous"
            conflict_reason = (
                f"CSI signal too weak to validate (best sim={best_sim:.3f} "
                f"to {closest_zone})"
            )
        elif margin < MARGIN_AMBIGUOUS_THRESHOLD:
            status = "ambiguous"
            conflict_reason = (
                f"video={video_label} but CSI is ambiguous between zones "
                f"(margin={margin:.3f})"
            )
        else:
            status = "conflict"
            conflict_reason = (
                f"video={video_label} but CSI fingerprint matches {closest_zone} "
                f"(sim={best_sim:.3f} vs {video_zone_sim:.3f})"
            )

    return {
        "csi_closest_zone": closest_zone,
        "csi_similarity": round(best_sim, 4),
        "csi_similarity_to_video_zone": round(video_zone_sim, 4),
        "all_similarities": {k: round(v, 4) for k, v in all_sims.items()},
        "status": status,
        "conflict_reason": conflict_reason,
    }


# ── Main Service Class ────────────────────────────────────────────────


class DualValidationService:
    """
    Validates video-annotated segments against CSI signal fingerprints.

    Usage:
        svc = DualValidationService(gold_dir, captures_dir)
        svc.load_gold_annotations()
        svc.load_capture_data()
        svc.build_zone_fingerprints()
        results = svc.validate_all()
        svc.save_results(output_dir)
    """

    def __init__(
        self,
        gold_dir: Path,
        captures_dir: Path,
        feature_window_sec: float = FEATURE_WINDOW_SEC,
    ):
        self.gold_dir = Path(gold_dir)
        self.captures_dir = Path(captures_dir)
        self.feature_window_sec = feature_window_sec

        # Loaded data
        self.gold_annotations: list[dict] = []
        self.capture_packets: dict[str, list[dict]] = {}  # recording_label -> packets

        # Built fingerprints
        self.fingerprints: dict[str, ZoneFingerprint] = {}
        self.feature_keys: list[str] = []

        # Results
        self.validated_segments: list[dict] = []
        self.conflicts: list[dict] = []

    def load_gold_annotations(self) -> int:
        """
        Load all gold-standard annotations from the gold directory.

        Searches recursively for manual_annotations_v1.json files
        that have gold_standard=true.

        Returns:
            Number of annotation files loaded.
        """
        count = 0
        for ann_path in sorted(self.gold_dir.rglob("manual_annotations_v1.json")):
            try:
                with open(ann_path) as f:
                    data = json.load(f)

                if not data.get("gold_standard", False):
                    logger.info(f"Skipping non-gold annotation: {ann_path}")
                    continue

                self.gold_annotations.append({
                    "source_path": str(ann_path),
                    "recording_label": data.get("recording_label", ""),
                    "annotations": data.get("annotations", []),
                    "gold_reason": data.get("gold_reason", ""),
                })
                count += 1
                n_segs = len(data.get("annotations", []))
                logger.info(
                    f"Loaded gold annotations: {ann_path.name} "
                    f"({n_segs} segments, label={data.get('recording_label', '?')})"
                )
            except Exception as e:
                logger.warning(f"Failed to load {ann_path}: {e}")

        logger.info(f"Total gold annotation files loaded: {count}")
        return count

    def load_capture_data(self) -> int:
        """
        Load CSI capture data for all recordings referenced by gold annotations.

        Returns:
            Number of recording sessions with loaded capture data.
        """
        loaded = 0
        for gold in self.gold_annotations:
            label = gold["recording_label"]
            if label in self.capture_packets:
                continue  # already loaded

            capture_files = find_capture_files(self.captures_dir, label)
            if not capture_files:
                logger.warning(
                    f"No capture files found for recording '{label}' "
                    f"in {self.captures_dir}"
                )
                continue

            all_packets = []
            for cf in capture_files:
                pkts = load_ndjson_capture(cf)
                all_packets.extend(pkts)
                logger.debug(f"  Loaded {len(pkts)} packets from {cf.name}")

            # Sort by timestamp
            all_packets.sort(key=lambda p: int(p.get("ts_ns", 0)))
            self.capture_packets[label] = all_packets
            loaded += 1
            logger.info(
                f"Loaded {len(all_packets)} packets for '{label}' "
                f"from {len(capture_files)} chunk(s)"
            )

        logger.info(f"Capture data loaded for {loaded}/{len(self.gold_annotations)} recordings")
        return loaded

    def build_zone_fingerprints(self) -> dict[str, ZoneFingerprint]:
        """
        Build CSI zone fingerprints from gold-annotated segments.

        Builds TWO sets of fingerprints:
        - 7-node (full): uses all nodes + shadow ratios
        - 4-node (core): uses only core nodes (n01-n04)

        This allows correct validation of both old 4-node and new 7-node
        capture sessions without systematic bias from missing shadow nodes.

        Returns:
            Dict of zone_name -> ZoneFingerprint (7-node set, stored as default).
        """
        node_ids = [str(e["node_id"]) for e in CSI_NODE_INVENTORY]
        self.feature_keys = build_fingerprint_feature_keys(node_ids, mode="7node")
        self.feature_keys_4node = build_fingerprint_feature_keys(node_ids, mode="4node")

        fingerprints_7node: dict[str, ZoneFingerprint] = {}
        fingerprints_4node: dict[str, ZoneFingerprint] = {}
        total_windows = 0

        for gold in self.gold_annotations:
            label = gold["recording_label"]
            packets = self.capture_packets.get(label, [])
            if not packets:
                continue

            session_start_ns = int(packets[0]["ts_ns"])

            # Collect ALL windows for this gold session first
            # so we can normalize per-session before fingerprinting
            session_windows: list[tuple[str, dict[str, float]]] = []

            for seg in gold["annotations"]:
                zone_label = seg.get("label", "").lower().strip()
                if zone_label in ("mixed", "unknown", ""):
                    continue

                start_sec = float(seg.get("start_sec", 0))
                end_sec = float(seg.get("end_sec", 0))

                if end_sec <= start_sec:
                    continue

                windows = extract_windows_for_segment(
                    packets, session_start_ns,
                    start_sec, end_sec,
                    self.feature_window_sec,
                )

                if not windows:
                    logger.debug(
                        f"No CSI windows for segment {seg.get('id', '?')} "
                        f"[{start_sec:.1f}-{end_sec:.1f}s] in '{label}'"
                    )
                    continue

                for w in windows:
                    session_windows.append((zone_label, w))

            if not session_windows:
                continue

            # Per-session normalization: removes domain shift
            raw_wins = [w for _, w in session_windows]
            normed_wins = normalize_session_features(raw_wins)

            for (zone_label, _), norm_w in zip(session_windows, normed_wins):
                for fp_dict in (fingerprints_7node, fingerprints_4node):
                    if zone_label not in fp_dict:
                        fp_dict[zone_label] = ZoneFingerprint(zone_label)

                fingerprints_7node[zone_label].add_window(norm_w)
                fingerprints_4node[zone_label].add_window(norm_w)
                total_windows += 1

        self.fingerprints = fingerprints_7node
        self.fingerprints_4node = fingerprints_4node

        for zone_name, fp in fingerprints_7node.items():
            logger.info(
                f"Zone fingerprint '{zone_name}': {fp.n_windows} windows"
            )
        logger.info(f"Total fingerprinted windows: {total_windows}")
        logger.info(
            f"Feature dims: 7-node={len(self.feature_keys)}, "
            f"4-node={len(self.feature_keys_4node)}"
        )

        return fingerprints_7node

    def validate_all(self) -> list[dict]:
        """
        Validate all gold-annotated segments against built fingerprints.

        Returns:
            List of validation result dicts.
        """
        if not self.fingerprints:
            logger.error("No fingerprints built. Call build_zone_fingerprints() first.")
            return []

        results = []

        for gold in self.gold_annotations:
            label = gold["recording_label"]
            packets = self.capture_packets.get(label, [])
            session_start_ns = int(packets[0]["ts_ns"]) if packets else 0

            # Phase 1: extract all windows for the session
            seg_windows_raw: list[tuple[dict, list[dict[str, float]]]] = []
            all_flat: list[dict[str, float]] = []

            for seg in gold["annotations"]:
                start_sec = float(seg.get("start_sec", 0))
                end_sec = float(seg.get("end_sec", 0))

                if packets and end_sec > start_sec:
                    wins = extract_windows_for_segment(
                        packets, session_start_ns,
                        start_sec, end_sec,
                        self.feature_window_sec,
                    )
                else:
                    wins = []

                seg_windows_raw.append((seg, wins))
                all_flat.extend(wins)

            # Normalize all windows per-session
            if all_flat:
                normed_flat = normalize_session_features(all_flat)
            else:
                normed_flat = []

            # Reassemble
            flat_idx = 0
            for seg, raw_wins in seg_windows_raw:
                n = len(raw_wins)
                seg_features = normed_flat[flat_idx: flat_idx + n]
                flat_idx += n

                seg_id = seg.get("id", "unknown")
                video_label = seg.get("label", "unknown")
                start_sec = float(seg.get("start_sec", 0))
                end_sec = float(seg.get("end_sec", 0))
                fewshot_hint = seg.get("fewshot_zone_hint")
                fewshot_conf = seg.get("fewshot_conf_hint")

                validation = validate_segment(
                    seg_features,
                    video_label,
                    self.fingerprints,
                    self.feature_keys,
                    fewshot_hint=fewshot_hint,
                    fewshot_conf=fewshot_conf,
                )

                result = {
                    "id": seg_id,
                    "recording_label": label,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "video_label": video_label,
                    "csi_closest_zone": validation["csi_closest_zone"],
                    "csi_similarity": validation["csi_similarity"],
                    "csi_similarity_to_video_zone": validation.get(
                        "csi_similarity_to_video_zone", None
                    ),
                    "all_similarities": validation.get("all_similarities", {}),
                    "fewshot_hint": fewshot_hint,
                    "fewshot_conf": fewshot_conf,
                    "status": validation["status"],
                    "conflict_reason": validation["conflict_reason"],
                    "n_csi_windows": len(seg_features),
                }
                results.append(result)

        self.validated_segments = results

        # Collect conflicts
        self.conflicts = [r for r in results if r["status"] == "conflict"]

        # Summary
        status_counts = defaultdict(int)
        for r in results:
            status_counts[r["status"]] += 1

        logger.info(
            f"Validation complete: {len(results)} segments. "
            f"validated={status_counts['validated']}, "
            f"conflict={status_counts['conflict']}, "
            f"ambiguous={status_counts['ambiguous']}"
        )

        return results

    def get_output_bundle(self) -> tuple[dict, dict]:
        """
        Build the output JSON bundle for validated_segments.json and conflicts.json.

        Returns:
            (validated_segments_doc, conflicts_doc)
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        status_counts = defaultdict(int)
        for r in self.validated_segments:
            status_counts[r["status"]] += 1

        # Serialize fingerprints
        fp_serialized = {}
        for zone_name, fp in self.fingerprints.items():
            fp_serialized[zone_name] = fp.to_dict()

        validated_doc = {
            "schema": "dual_validation_v1",
            "generated": now_iso,
            "gold_fingerprints": fp_serialized,
            "segments": self.validated_segments,
            "summary": {
                "total": len(self.validated_segments),
                "validated": status_counts.get("validated", 0),
                "conflict": status_counts.get("conflict", 0),
                "ambiguous": status_counts.get("ambiguous", 0),
            },
        }

        conflicts_doc = {
            "schema": "dual_validation_conflicts_v1",
            "generated": now_iso,
            "conflicts": [
                {
                    "id": c["id"],
                    "recording_label": c["recording_label"],
                    "start_sec": c["start_sec"],
                    "end_sec": c["end_sec"],
                    "video_label": c["video_label"],
                    "csi_closest_zone": c["csi_closest_zone"],
                    "csi_similarity_to_video_zone": c.get(
                        "csi_similarity_to_video_zone", 0.0
                    ),
                    "csi_similarity_to_closest_zone": c["csi_similarity"],
                    "fewshot_hint": c.get("fewshot_hint"),
                    "conflict_reason": c["conflict_reason"],
                }
                for c in self.conflicts
            ],
        }

        return validated_doc, conflicts_doc

    def save_results(self, output_dir: Path) -> tuple[Path, Path]:
        """
        Save validation results to output directory.

        Returns:
            (validated_segments_path, conflicts_path)
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        validated_doc, conflicts_doc = self.get_output_bundle()

        validated_path = output_dir / "validated_segments.json"
        conflicts_path = output_dir / "conflicts.json"

        with open(validated_path, "w") as f:
            json.dump(validated_doc, f, indent=2, ensure_ascii=False)

        with open(conflicts_path, "w") as f:
            json.dump(conflicts_doc, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved validated segments to {validated_path}")
        logger.info(f"Saved conflicts to {conflicts_path}")

        return validated_path, conflicts_path


# ── Batch Manifest Validation ─────────────────────────────────────────


def validate_manifest(
    manifest_path: Path,
    captures_dir: Path,
    fingerprints: dict[str, ZoneFingerprint],
    feature_keys: list[str],
    window_sec: float = FEATURE_WINDOW_SEC,
) -> list[dict[str, Any]]:
    """
    Batch-validate all intervals in a video-teacher manifest against
    pre-built zone fingerprints.

    Each manifest entry must have: recording_label, start_sec, end_sec,
    label (the video-annotated zone).

    Args:
        manifest_path: Path to manifest JSON (list of interval dicts).
        captures_dir: Directory containing ndjson.gz capture files.
        fingerprints: Pre-built zone fingerprints (from calibration data).
        feature_keys: Canonical feature key ordering.
        window_sec: Window size for feature extraction.

    Returns:
        List of validation result dicts, one per manifest interval.
    """
    with open(manifest_path) as f:
        raw = json.load(f)

    # The manifest can be a dict with an "intervals" key or a plain list
    if isinstance(raw, dict):
        intervals = raw.get("intervals", raw.get("segments", []))
    elif isinstance(raw, list):
        intervals = raw
    else:
        logger.error(f"Unexpected manifest format in {manifest_path}")
        return []

    logger.info(f"Batch validating {len(intervals)} intervals from {manifest_path.name}")

    # Cache loaded packets per recording label
    packets_cache: dict[str, list[dict]] = {}
    session_start_cache: dict[str, int] = {}
    results: list[dict[str, Any]] = []

    # Pre-compute normalization stats once for the whole batch
    norm_stats = compute_normalization_stats(fingerprints, feature_keys)

    for idx, interval in enumerate(intervals):
        rec_label = interval.get("recording_label", "")
        video_label = interval.get("label", interval.get("zone", "unknown"))
        start_sec = float(interval.get("start_sec", 0))
        end_sec = float(interval.get("end_sec", 0))
        seg_id = interval.get("id", f"manifest_seg_{idx:04d}")

        # Load packets if not cached
        if rec_label and rec_label not in packets_cache:
            capture_files = find_capture_files(captures_dir, rec_label)
            if capture_files:
                all_pkts: list[dict] = []
                for cf in capture_files:
                    all_pkts.extend(load_ndjson_capture(cf))
                all_pkts.sort(key=lambda p: int(p.get("ts_ns", 0)))
                packets_cache[rec_label] = all_pkts
                if all_pkts:
                    session_start_cache[rec_label] = int(all_pkts[0]["ts_ns"])
            else:
                packets_cache[rec_label] = []

        packets = packets_cache.get(rec_label, [])
        session_start_ns = session_start_cache.get(rec_label, 0)

        # Extract features
        if packets and end_sec > start_sec:
            seg_features = extract_windows_for_segment(
                packets, session_start_ns,
                start_sec, end_sec,
                window_sec,
            )
        else:
            seg_features = []

        # Run validation (reuse cached norm_stats for speed)
        if not seg_features:
            validation = {
                "csi_closest_zone": None,
                "csi_similarity": 0.0,
                "csi_similarity_to_video_zone": 0.0,
                "all_similarities": {},
                "status": "ambiguous",
                "conflict_reason": "no CSI data available for segment time window",
            }
        else:
            # Average features across windows
            all_keys_set: set[str] = set()
            for feat in seg_features:
                all_keys_set.update(k for k in feat.keys() if k != "_active_nodes")

            avg_features: dict[str, float] = {}
            for key in all_keys_set:
                vals = [f.get(key, 0.0) for f in seg_features]
                avg_features[key] = float(np.mean(vals))

            feature_vec = np.array(
                [avg_features.get(k, 0.0) for k in feature_keys],
                dtype=np.float64,
            )

            closest_zone, best_sim, all_sims = find_closest_zone(
                feature_vec, fingerprints, feature_keys, norm_stats=norm_stats
            )

            norm_video = _normalize_zone_label(video_label)
            norm_closest = _normalize_zone_label(closest_zone)

            video_zone_sim = all_sims.get(norm_video, all_sims.get(video_label, 0.0))
            sorted_sims = sorted(all_sims.values(), reverse=True)
            margin = (sorted_sims[0] - sorted_sims[1]) if len(sorted_sims) >= 2 else sorted_sims[0]

            if norm_video == "mixed":
                status = "validated"
                conflict_reason = None
            elif norm_video == norm_closest:
                if best_sim >= SIMILARITY_AMBIGUOUS_THRESHOLD:
                    status = "validated"
                    conflict_reason = None
                else:
                    status = "ambiguous"
                    conflict_reason = (
                        f"video and CSI agree on {video_label} but similarity is low "
                        f"(sim={best_sim:.3f})"
                    )
            else:
                if best_sim < SIMILARITY_AMBIGUOUS_THRESHOLD:
                    status = "ambiguous"
                    conflict_reason = (
                        f"CSI signal too weak to validate (best sim={best_sim:.3f} "
                        f"to {closest_zone})"
                    )
                elif margin < MARGIN_AMBIGUOUS_THRESHOLD:
                    status = "ambiguous"
                    conflict_reason = (
                        f"video={video_label} but CSI is ambiguous between zones "
                        f"(margin={margin:.3f})"
                    )
                else:
                    status = "conflict"
                    conflict_reason = (
                        f"video={video_label} but CSI fingerprint matches {closest_zone} "
                        f"(sim={best_sim:.3f} vs {video_zone_sim:.3f})"
                    )

            validation = {
                "csi_closest_zone": closest_zone,
                "csi_similarity": round(best_sim, 4),
                "csi_similarity_to_video_zone": round(video_zone_sim, 4),
                "all_similarities": {k: round(v, 4) for k, v in all_sims.items()},
                "status": status,
                "conflict_reason": conflict_reason,
            }

        result = {
            "id": seg_id,
            "recording_label": rec_label,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "video_label": video_label,
            "n_csi_windows": len(seg_features),
            **validation,
        }
        results.append(result)

    # Summary log
    status_counts: dict[str, int] = defaultdict(int)
    for r in results:
        status_counts[r["status"]] += 1

    logger.info(
        f"Manifest batch validation complete: {len(results)} intervals. "
        f"validated={status_counts['validated']}, "
        f"conflict={status_counts['conflict']}, "
        f"ambiguous={status_counts['ambiguous']}"
    )

    return results
