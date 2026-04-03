"""Helpers for parsing Aqara FP2 resource payloads."""

from __future__ import annotations

import json
from typing import Any

RESOURCE_TARGET_TRACKS = "4.22.700"


def extract_targets(params: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Extract active tracked targets from Aqara resource params.

    Aqara cloud payload exposes raw tracked targets in resource ``4.22.700`` as a
    JSON string. Example element:

    ``{"rangeId":0,"x":88,"y":104,"targetType":0,"id":0,"state":"1"}``

    Only active targets (``state == "1"``) are returned.
    """
    if not isinstance(params, list):
        return []

    raw_value = None
    for param in params:
        if param.get("resId") == RESOURCE_TARGET_TRACKS:
            raw_value = param.get("value")
            break

    if not raw_value:
        return []

    try:
        items = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(items, list):
        return []

    targets: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("state")) != "1":
            continue

        target_id = item.get("id")
        range_id = item.get("rangeId")
        zone_id = "default"
        if range_id not in ("", None):
            try:
                zone_id = f"range_{int(range_id)}"
            except (TypeError, ValueError):
                zone_id = f"range_{range_id}"

        try:
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
        except (TypeError, ValueError):
            continue

        targets.append(
            {
                "id": str(target_id if target_id is not None else len(targets)),
                "zone_id": zone_id,
                "x": x,
                "y": y,
                "raw_range_id": range_id,
                "target_type": item.get("targetType"),
                "activity": "standing",
            }
        )

    return targets

