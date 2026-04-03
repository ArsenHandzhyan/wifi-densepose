from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = ROOT / "custom_components/aqara_fp2/payload_parser.py"
SPEC = importlib.util.spec_from_file_location("aqara_fp2_payload_parser", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
extract_targets = MODULE.extract_targets


def test_extract_targets_returns_active_targets_with_coordinates() -> None:
    params = [
        {
            "resId": "4.22.700",
            "value": json.dumps(
                [
                    {"rangeId": 0, "x": 88, "y": 104, "targetType": 0, "id": 0, "state": "1"},
                    {"rangeId": "", "x": 0, "y": 0, "targetType": 0, "id": 1, "state": "0"},
                ]
            ),
        }
    ]

    targets = extract_targets(params)

    assert targets == [
        {
            "id": "0",
            "zone_id": "range_0",
            "x": 88.0,
            "y": 104.0,
            "raw_range_id": 0,
            "target_type": 0,
            "activity": "standing",
        }
    ]


def test_extract_targets_ignores_invalid_payloads() -> None:
    assert extract_targets(None) == []
    assert extract_targets([{"resId": "4.22.700", "value": "not-json"}]) == []
