#!/usr/bin/env python3
from __future__ import annotations

from importlib.machinery import SourceFileLoader
from pathlib import Path


PROJECT = Path("/Users/arsen/Desktop/wifi-densepose")

base = SourceFileLoader(
    "retrain_v40_binary_7node_v41",
    str(PROJECT / "scripts" / "retrain_v40_binary_7node.py"),
).load_module()

base.VERSION = "V41_binary_mixed"
base.PKL_NAME = "v41_binary_mixed.pkl"
base.META_NAME = "v41_binary_mixed_meta.json"
base.RUN_OUTPUT = PROJECT / "output" / "v41_binary_mixed_retrain1"
base.SUMMARY_NAME = "v41_binary_mixed_retrain1_summary_v1.json"
base.NOTE = (
    "Mixed binary candidate: today's 7-node empty + occupied plus historical external "
    "empty anchors from 2026-03-25/26, keeping chunk0002 holdout slices untouched."
)

base.RECORDINGS = [
    # Same-day 7-node empty anchors.
    ("empty_7node_chunk*_20260327_1033*.ndjson.gz", "empty"),
    ("empty_7node_chunk*_20260327_1034*.ndjson.gz", "empty"),
    # Historical empty anchors added to combat external empty collapse.
    ("shadow_eval_s1_empty_closed_door_20260326_v2_chunk0001_20260326_065932.ndjson.gz", "empty"),
    ("v19_shadow_eval_empty_closeddoor_20260325_0400_chunk0001_20260325_040517.ndjson.gz", "empty"),
    # Occupied anchors from the same-day 7-node surface.
    ("center_chunk*_20260327_0752*.ndjson.gz", "occupied"),
    ("center_chunk*_20260327_0801*.ndjson.gz", "occupied"),
    ("center_chunk*_20260327_0802*.ndjson.gz", "occupied"),
    ("center_chunk*_20260327_0835*.ndjson.gz", "occupied"),
    ("center_chunk*_20260327_0836*.ndjson.gz", "occupied"),
    ("center_chunk*_20260327_0943*.ndjson.gz", "occupied"),
    ("door_passage_chunk*_20260327_0749*.ndjson.gz", "occupied"),
    ("door_passage_chunk*_20260327_0750*.ndjson.gz", "occupied"),
    ("door_passage_chunk*_20260327_0803*.ndjson.gz", "occupied"),
    ("door_passage_chunk*_20260327_0804*.ndjson.gz", "occupied"),
    ("door_passage_chunk*_20260327_0837*.ndjson.gz", "occupied"),
    ("door_passage_chunk*_20260327_0948*.ndjson.gz", "occupied"),
]


if __name__ == "__main__":
    raise SystemExit(base.main())
