"""
Coordinate Stabilization Service -- Shadow-Only EMA + Zone-Constraint Filter

Problem: V25 production coordinates jump wildly for static presence because
the signal-deviation weighted centroid is noisy window-to-window. A person
standing still can show x swinging from -1.5 to +1.5 within seconds.

Solution: shadow-mode post-filter that applies:
  1. Motion-aware EMA: aggressive smoothing (alpha=0.05) for NO_MOTION,
     lighter smoothing (alpha=0.40) for MOTION_DETECTED.
  2. Zone-boundary constraints: clamp coordinates to plausible sub-regions
     based on the current zone label (door / center / deep).
  3. Jump detector: flag when raw production coords move >1m in <=2 windows
     (10s) while motion_state is NO_MOTION -- likely a false coordinate.
  4. Calibration snapshots: store recent stabilized vs raw coords for
     offline analysis.

Contract:
  - NEVER modifies production self.current dict
  - Attaches stabilized coords as shadow metadata only
  - All state is resettable; no persistent side-effects
"""

import json
import logging
import math
import time
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Garage geometry ────────────────────────────────────────────────
GARAGE_WIDTH = 3.0    # x in [-1.5, +1.5]
GARAGE_HEIGHT = 7.0   # y in [0, 7]

# Zone Y-boundaries (from prediction service zone logic)
ZONE_BOUNDS: dict[str, tuple[float, float, float, float]] = {
    # (x_min, x_max, y_min, y_max)
    "door":   (-1.5, 1.5, 0.0, 1.5),
    "center": (-1.5, 1.5, 1.5, 5.0),
    "deep":   (-1.5, 1.5, 5.0, 7.0),
}

# ── EMA parameters ─────────────────────────────────────────────────
ALPHA_STATIC = 0.15    # moderate tracking for static presence (was 0.05, too laggy)
ALPHA_MOTION = 0.40    # responsive tracking during motion
ALPHA_TRANSITION = 0.20  # first window after motion stops

# ── Jump detection ─────────────────────────────────────────────────
JUMP_THRESHOLD_M = 1.0          # meters
JUMP_WINDOW_LIMIT = 2           # within N windows (each 5s)
MAX_STATIC_VELOCITY_MPS = 0.05  # m/s -- person is not moving

# ── Snapshot buffer ────────────────────────────────────────────────
SNAPSHOT_BUFFER_SIZE = 360       # 30 min at 5s windows
SNAPSHOT_EXPORT_DIR = Path(__file__).resolve().parents[3] / "temp"


class CoordStabilizationService:
    """Shadow-mode coordinate stabilizer.

    Call process() after each prediction window. It returns stabilized
    coordinates and diagnostic metadata but never touches production state.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """Clear all state. Safe to call at any time."""
        self._ema_x: float | None = None
        self._ema_y: float | None = None
        self._prev_motion_state: str = "NO_MOTION"
        self._prev_raw_x: float = 0.0
        self._prev_raw_y: float = 0.0
        self._prev_t: float = 0.0
        self._window_count: int = 0
        self._jump_count: int = 0
        self._snapshots: deque[dict] = deque(maxlen=SNAPSHOT_BUFFER_SIZE)
        self._enabled: bool = True
        logger.info("CoordStabilizationService reset")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val

    def process(
        self,
        raw_x: float,
        raw_y: float,
        motion_state: str,
        zone: str,
        binary: str,
        window_t: float | None = None,
    ) -> dict[str, Any]:
        """Process one prediction window and return stabilized coordinates.

        Args:
            raw_x: production target_x from prediction service
            raw_y: production target_y from prediction service
            motion_state: "MOTION_DETECTED" or "NO_MOTION"
            zone: "door", "center", "deep", or "empty"
            binary: "occupied" or "empty"
            window_t: window end timestamp (monotonic seconds), or None for now

        Returns:
            Dict with stabilized coords and diagnostics. Keys:
              stable_x, stable_y, raw_x, raw_y, zone, alpha_used,
              jump_detected, jump_distance, clamped, diagnostics
        """
        if not self._enabled or binary == "empty" or zone == "empty":
            # Nothing to stabilize when room is empty
            self._ema_x = None
            self._ema_y = None
            return self._make_result(
                raw_x, raw_y, raw_x, raw_y, zone, 0.0,
                jump=False, jump_dist=0.0, clamped=False,
                note="passthrough_empty",
            )

        t = window_t if window_t is not None else time.monotonic()
        self._window_count += 1
        is_static = motion_state == "NO_MOTION"

        # ── 1. Detect jumps ────────────────────────────────────────
        jump_dist = 0.0
        jump_detected = False
        if self._ema_x is not None:
            jump_dist = math.hypot(raw_x - self._prev_raw_x,
                                   raw_y - self._prev_raw_y)
            dt = t - self._prev_t if self._prev_t > 0 else 5.0
            if (is_static
                    and jump_dist > JUMP_THRESHOLD_M
                    and dt <= JUMP_WINDOW_LIMIT * 5.0 + 1.0):
                jump_detected = True
                self._jump_count += 1

        # ── 2. Choose alpha ────────────────────────────────────────
        if self._ema_x is None:
            # First window: seed EMA directly
            alpha = 1.0
        elif is_static and self._prev_motion_state == "MOTION_DETECTED":
            # Transition: motion just stopped, settle faster for 1 window
            alpha = ALPHA_TRANSITION
        elif is_static:
            alpha = ALPHA_STATIC
        else:
            alpha = ALPHA_MOTION

        # If jump detected during static, reject the raw input entirely
        # by using alpha=0 (keep previous EMA)
        if jump_detected:
            alpha = 0.0

        # ── 3. EMA update ──────────────────────────────────────────
        if self._ema_x is None:
            stable_x = raw_x
            stable_y = raw_y
        else:
            stable_x = self._ema_x + alpha * (raw_x - self._ema_x)
            stable_y = self._ema_y + alpha * (raw_y - self._ema_y)

        # ── 4. Zone-boundary clamping ──────────────────────────────
        clamped = False
        if is_static and zone in ZONE_BOUNDS:
            x_min, x_max, y_min, y_max = ZONE_BOUNDS[zone]
            cx = max(x_min, min(x_max, stable_x))
            cy = max(y_min, min(y_max, stable_y))
            if cx != stable_x or cy != stable_y:
                clamped = True
                stable_x, stable_y = cx, cy

        # Global garage clamp (always)
        stable_x = max(-GARAGE_WIDTH / 2, min(GARAGE_WIDTH / 2, stable_x))
        stable_y = max(0.0, min(GARAGE_HEIGHT, stable_y))

        # ── 5. Update state ────────────────────────────────────────
        self._ema_x = stable_x
        self._ema_y = stable_y
        self._prev_raw_x = raw_x
        self._prev_raw_y = raw_y
        self._prev_motion_state = motion_state
        self._prev_t = t

        result = self._make_result(
            stable_x, stable_y, raw_x, raw_y, zone, alpha,
            jump=jump_detected, jump_dist=jump_dist, clamped=clamped,
        )

        # ── 6. Store snapshot ──────────────────────────────────────
        self._snapshots.append({
            "t": t,
            "ts": time.time(),
            **result,
        })

        return result

    def _make_result(
        self,
        sx: float, sy: float,
        rx: float, ry: float,
        zone: str, alpha: float,
        jump: bool, jump_dist: float, clamped: bool,
        note: str = "",
    ) -> dict[str, Any]:
        return {
            "stable_x": round(sx, 3),
            "stable_y": round(sy, 3),
            "raw_x": round(rx, 3),
            "raw_y": round(ry, 3),
            "zone": zone,
            "alpha_used": round(alpha, 3),
            "jump_detected": jump,
            "jump_distance": round(jump_dist, 3),
            "clamped": clamped,
            "window_count": self._window_count,
            "total_jumps": self._jump_count,
            "note": note,
        }

    # ── Snapshot management ────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return current stabilization status for API/UI."""
        return {
            "enabled": self._enabled,
            "window_count": self._window_count,
            "total_jumps": self._jump_count,
            "ema_position": (
                {"x": round(self._ema_x, 3), "y": round(self._ema_y, 3)}
                if self._ema_x is not None else None
            ),
            "snapshot_buffer_size": len(self._snapshots),
            "snapshot_buffer_capacity": SNAPSHOT_BUFFER_SIZE,
        }

    def get_recent_snapshots(self, n: int = 30) -> list[dict]:
        """Return the last N snapshots for UI overlay or debugging."""
        return list(self._snapshots)[-n:]

    def export_snapshots(self, tag: str = "") -> str | None:
        """Write snapshot buffer to NDJSON file for offline analysis.

        Returns the file path on success, None on failure.
        """
        if not self._snapshots:
            return None
        try:
            SNAPSHOT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            suffix = f"_{tag}" if tag else ""
            path = SNAPSHOT_EXPORT_DIR / f"coord_stabilization{suffix}_{ts}.ndjson"
            with open(path, "w") as f:
                for snap in self._snapshots:
                    f.write(json.dumps(snap, default=str) + "\n")
            logger.info("Exported %d snapshots to %s", len(self._snapshots), path)
            return str(path)
        except Exception as e:
            logger.warning("Snapshot export failed: %s", e)
            return None


# ── Singleton ──────────────────────────────────────────────────────
coord_stabilization_service = CoordStabilizationService()
