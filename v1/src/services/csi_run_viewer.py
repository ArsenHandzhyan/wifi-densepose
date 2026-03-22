"""
CSI Run Viewer — builds a lightweight summary/viewer dict from a completed training run.
"""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CAPTURES_DIR = _PROJECT_ROOT / "temp" / "captures"


def _load_ndjson_gz(path: Path, max_lines: int = 500) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
    return rows


def build_run_viewer(run: dict[str, Any]) -> dict[str, Any]:
    """
    Build a viewer payload for a completed capture run.
    Returns a dict with `available`, and optionally `clips`, `summary`, `stats`.
    """
    label_prefix = run.get("label_prefix")
    if not label_prefix:
        return {
            "available": False,
            "reason": "Run has no label_prefix — cannot locate capture files.",
        }

    # Try manifest first
    manifest_path = _CAPTURES_DIR / f"{label_prefix}.manifest.json"
    if not manifest_path.exists():
        # Search for any matching manifest
        candidates = sorted(_CAPTURES_DIR.glob(f"*{label_prefix}*.manifest.json"))
        if candidates:
            manifest_path = candidates[-1]

    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse manifest %s: %s", manifest_path, exc)

    clips_info: list[dict[str, Any]] = []

    if manifest and isinstance(manifest.get("clips"), list):
        for clip in manifest["clips"]:
            if not isinstance(clip, dict):
                continue
            capture_file = clip.get("capture_file") or clip.get("csi_file")
            clip_summary: dict[str, Any] = {
                "label": clip.get("capture_label") or clip.get("label"),
                "step_name": clip.get("step_name"),
                "duration_sec": clip.get("duration_sec"),
                "frame_count": None,
                "capture_file": capture_file,
            }
            if capture_file:
                p = Path(str(capture_file))
                if p.exists():
                    rows = _load_ndjson_gz(p, max_lines=10)
                    clip_summary["frame_count_sample"] = len(rows)
            clips_info.append(clip_summary)
    elif label_prefix:
        # Fallback: scan capture dir for matching files
        for gz_path in sorted(_CAPTURES_DIR.glob(f"*{label_prefix}*.ndjson.gz"))[:10]:
            clips_info.append({
                "label": gz_path.stem.replace(".ndjson", ""),
                "capture_file": str(gz_path),
            })

    return {
        "available": True,
        "label_prefix": label_prefix,
        "manifest": str(manifest_path) if manifest_path.exists() else None,
        "clips": clips_info,
        "clip_count": len(clips_info),
        "summary": manifest.get("summary") if manifest else None,
    }
