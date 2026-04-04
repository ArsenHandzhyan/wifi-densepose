#!/usr/bin/env python3

from __future__ import annotations

import json
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


UI_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = UI_DIR.parent
ANALYSIS_DIR = WORKSPACE_ROOT / "temp" / "analysis"
MANUAL_ZONE_REVIEW_DIR = WORKSPACE_ROOT / "output" / "video_curation" / "newrouter_manual_zone_review1"
MANUAL_ZONE_REVIEW_MANIFEST = MANUAL_ZONE_REVIEW_DIR / "newrouter_manual_zone_review_manifest_v1.json"

FORENSIC_KINDS = {
    "bundle": "paired_forensic_bundle",
    "watcher": ".watcher.json",
    "raw_step": ".live_pose_step.json",
    "started": ".started.json",
    "finished": ".finished.json",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
      return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover - best effort local API
      return None, str(exc)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_workspace_path(relative_path: str) -> Path | None:
    rel = (relative_path or "").lstrip("/")
    candidate = (WORKSPACE_ROOT / rel).resolve()
    try:
      candidate.relative_to(WORKSPACE_ROOT.resolve())
    except Exception:
      return None
    return candidate


def load_manual_zone_manifest() -> dict[str, Any] | None:
    payload, error = read_json(MANUAL_ZONE_REVIEW_MANIFEST)
    if error or not isinstance(payload, dict):
      return None
    return payload


def find_manual_zone_session(session_label: str) -> dict[str, Any] | None:
    manifest = load_manual_zone_manifest()
    if not manifest:
      return None
    for session in manifest.get("sessions") or []:
      if session.get("session_label") == session_label:
        return session
    return None


def detect_kind(path: Path) -> str | None:
    name = path.name
    if FORENSIC_KINDS["bundle"] in name:
      return "bundle"
    if name.endswith(FORENSIC_KINDS["watcher"]):
      return "watcher"
    if name.endswith(FORENSIC_KINDS["raw_step"]):
      return "raw_step"
    if name.endswith(FORENSIC_KINDS["started"]):
      return "started"
    if name.endswith(FORENSIC_KINDS["finished"]):
      return "finished"
    return None


def best_timestamp(*values: Any) -> str | None:
    candidates = [value for value in values if isinstance(value, str) and value]
    if not candidates:
      return None
    return sorted(candidates)[-1]


def parse_timestamp(value: str | None) -> datetime:
    if not value:
      return datetime.min.replace(tzinfo=timezone.utc)
    try:
      normalized = value.replace("Z", "+00:00")
      return datetime.fromisoformat(normalized)
    except ValueError:
      return datetime.min.replace(tzinfo=timezone.utc)


def build_display_label(run_id: str, record: dict[str, Any]) -> str:
    label = (
      record["meta"].get("label")
      or record["meta"].get("artifact_label")
      or run_id
    )
    sort_ts = record.get("sort_ts")
    if not sort_ts:
      return label
    return f"{label} · {sort_ts[11:19]}"


def detect_evidence_sensitivity(ordered_semantics: dict[str, Any]) -> tuple[str, str]:
    if not ordered_semantics:
      return "unknown", "Ordered semantics недоступны."

    first_pulse = ordered_semantics.get("first_strong_pulse") or {}
    first_assignment = ordered_semantics.get("first_direction_assignment") or {}

    if ordered_semantics.get("exit_first_prebaseline_aliasing"):
      return "contamination_sensitive", "зафиксирован exit-first prebaseline aliasing."

    pulse_index = first_pulse.get("sample_index")
    pulse_side = first_pulse.get("assigned_side")
    assignment_index = first_assignment.get("sample_index")
    assignment_side = first_assignment.get("assigned_side")

    if pulse_index == 0 and pulse_side == "exit":
      return "contamination_sensitive", "первый сильный pulse начинается с sample_index=0 с exit-семантикой."

    if assignment_index == 0 and assignment_side == "exit":
      return "contamination_sensitive", "первое назначение направления начинается с sample_index=0 как exit."

    return "robust", "раннего exit-first contamination marker нет."


CRITERIA_SUMMARY_MAP = {
    "same_run_paired_bundle_present": {
      "text": "нет same-run paired bundle",
      "priority": 70,
    },
    "topology_matches_required_four_node": {
      "text": "топология не совпала с обязательной four-node схемой",
      "priority": 80,
    },
    "frozen_threshold_is_0996": {
      "text": "runtime-threshold ушёл от frozen 0.996",
      "priority": 90,
    },
    "clean_entry_first_possible": {
      "text": "clean entry-first progression не стала возможной",
      "priority": 10,
    },
    "first_direction_assignment_is_entry": {
      "text": "первое назначение направления не было entry",
      "priority": 20,
    },
    "entry_active_seen_before_entry_resolved": {
      "text": "entry_active не появился до entry_resolved",
      "priority": 30,
    },
    "entry_resolved_before_any_context_invalid": {
      "text": "entry не успел resolved до context-invalid",
      "priority": 40,
    },
    "no_unexpected_exit_before_entry_before_resolve": {
      "text": "неожиданный exit появился до resolved-entry",
      "priority": 50,
    },
    "paired_raw_covers_entry_resolved": {
      "text": "paired raw coverage не покрывает resolved-entry event",
      "priority": 60,
    },
}

ARTIFACT_LABELS = {
    "bundle": "paired bundle",
    "watcher": "watcher",
    "raw_step": "raw-step",
    "started": "стартовый сигнал",
    "finished": "финишный сигнал",
}


def humanize_token(value: str | None) -> str:
    if not value:
      return "unknown"
    return str(value).replace("_", " ")


def display_failure_label(value: str | None) -> str:
    if value == "exit_first_prebaseline_aliasing":
      return "exit-first до quiet-базы"
    if value == "strong_pulse_without_direction_assignment":
      return "сильный pulse без стабилизации направления"
    if value == "unexpected_exit_before_entry":
      return "exit раньше entry"
    if value == "exit_assigned_before_entry":
      return "exit назначен раньше entry"
    return humanize_token(value)


def oxford_join(items: list[str]) -> str:
    values = [item for item in items if item]
    if not values:
      return ""
    if len(values) == 1:
      return values[0]
    if len(values) == 2:
      return f"{values[0]} и {values[1]}"
    return f"{', '.join(values[:-1])} и {values[-1]}"


def describe_event_progression(ordered_semantics: dict[str, Any], failure_family: str | None) -> str:
    first_pulse = ordered_semantics.get("first_strong_pulse") or {}
    first_assignment = ordered_semantics.get("first_direction_assignment") or {}
    first_resolution = ordered_semantics.get("first_resolution_event") or {}

    pulse_index = first_pulse.get("sample_index")
    assignment_index = first_assignment.get("sample_index")
    assignment_side = first_assignment.get("assigned_side")

    if failure_family == "strong_pulse_without_direction_assignment":
      if pulse_index is not None:
        return f"сильный pulse появился на sample {pulse_index}, но direction assignment не стабилизировался до ambiguity"
      return "сильный pulse появился, но direction assignment не стабилизировался до ambiguity"

    if failure_family == "exit_first_prebaseline_aliasing":
      if pulse_index is not None:
        return f"первый сильный pulse возник на sample {pulse_index} до quiet-outside интервала, и direction assignment сразу ушёл в exit"
      return "первый сильный pulse возник на нулевом окне до quiet-outside интервала"

    if failure_family == "unexpected_exit_before_entry":
      return "exit-семантика появилась раньше clean entry-first progression"

    if failure_family == "exit_assigned_before_entry":
      return "direction assignment стабилизировался как exit раньше entry"

    if failure_family == "no_strong_pulse":
      return "в наблюдаемом окне не было сильного pulse"

    if first_pulse and first_assignment:
      if assignment_side:
        return (
          f"сильный pulse появился на sample {pulse_index}, а direction assignment ушёл в "
          f"{assignment_side} на sample {assignment_index}"
        )
      return f"сильный pulse появился на sample {pulse_index}, а direction marker появился на sample {assignment_index}"

    if first_pulse:
      reason = first_pulse.get("shadow_invalidation_reason") or first_pulse.get("shadow_reason")
      if reason and pulse_index is not None:
        return f"сильный pulse появился на sample {pulse_index}, после чего контекст ушёл в {humanize_token(reason)}"
      if pulse_index is not None:
        return f"сильный pulse появился на sample {pulse_index}"
      return "зафиксирован marker сильного pulse"

    if first_assignment:
      if assignment_side and assignment_index is not None:
        return f"direction assignment стабилизировался как {assignment_side} на sample {assignment_index}"
      return "зафиксирован marker direction assignment"

    if first_resolution:
      return "resolution marker появился без более раннего strong-pulse marker"

    return "сильный pulse и direction marker не были зафиксированы"


def summarize_failed_criteria(failed_criteria: list[str], failure_family: str | None) -> tuple[str | None, int]:
    if not failed_criteria:
      return None, 0

    skipped = set()
    if failure_family == "strong_pulse_without_direction_assignment":
      skipped.add("first_direction_assignment_is_entry")
    if failure_family in {"exit_first_prebaseline_aliasing", "unexpected_exit_before_entry", "exit_assigned_before_entry"}:
      skipped.update({"first_direction_assignment_is_entry", "clean_entry_first_possible"})

    descriptors = [
      {
        "text": CRITERIA_SUMMARY_MAP.get(item, {}).get("text", humanize_token(item)),
        "priority": CRITERIA_SUMMARY_MAP.get(item, {}).get("priority", 999),
      }
      for item in failed_criteria
      if item not in skipped
    ]
    if not descriptors:
      descriptors = [
        {
          "text": CRITERIA_SUMMARY_MAP.get(item, {}).get("text", humanize_token(item)),
          "priority": CRITERIA_SUMMARY_MAP.get(item, {}).get("priority", 999),
        }
        for item in failed_criteria
      ]

    if not descriptors:
      return None, 0

    descriptors.sort(key=lambda item: item["priority"])
    return descriptors[0]["text"], max(0, len(descriptors) - 1)


def build_gap_to_canonical(
    resolved: dict[str, Any],
    ordered_semantics: dict[str, Any],
    missing_artifacts: list[str],
    failure_family: str | None,
) -> tuple[str, int]:
    if missing_artifacts:
      missing_labels = oxford_join([ARTIFACT_LABELS.get(item, humanize_token(item)) for item in missing_artifacts])
      return f"не хватает {missing_labels}", max(0, len(missing_artifacts) - 1)

    failed_clause, extra_count = summarize_failed_criteria(resolved.get("failed_criteria") or [], failure_family)
    if failed_clause:
      return failed_clause, extra_count

    if ordered_semantics.get("clean_entry_first_possible") is False:
      return "clean entry-first progression не стала возможной", 0

    if not (ordered_semantics.get("first_direction_assignment") or {}):
      return "direction assignment не стабилизировался", 0

    if not (ordered_semantics.get("first_resolution_event") or {}):
      return "resolved-entry event не был захвачен", 0

    return "resolved-strong критерии остаются предварительными", 0


def format_extra_blockers(extra_count: int) -> str:
    if extra_count <= 0:
      return ""
    if extra_count == 1:
      return " Ещё 1 критерий вне нормы."
    return f" Ещё {extra_count} критерия вне нормы."


def build_operator_summary_preview(
    classification: dict[str, Any],
    ordered_semantics: dict[str, Any],
    resolved: dict[str, Any],
    missing_artifacts: list[str],
    sensitivity: str,
) -> str:
    status = classification.get("status") or "classification_unavailable"
    failure_family = classification.get("failure_family") or ordered_semantics.get("ordered_failure_mode")
    blocker, _ = build_gap_to_canonical(resolved, ordered_semantics, missing_artifacts, failure_family)

    if status == "canonical_resolved_strong":
      return "Канонический resolved-strong: clean entry-first подтверждён."

    if missing_artifacts:
      return f"Неполный bundle: {blocker}."

    if sensitivity == "contamination_sensitive":
      return f"Тайминг-сдвиг: {display_failure_label(failure_family or ordered_semantics.get('ordered_failure_mode'))}. Блокер: {blocker}."

    if status == "failure_family_evidence":
      return f"Семейство сбоев: {display_failure_label(failure_family)}. Блокер: {blocker}."

    if failure_family:
      return f"Предварительный forensic-read: {display_failure_label(failure_family)}. Блокер: {blocker}."

    return f"Предварительный forensic-read: {blocker}."


def build_operator_summary(
    classification: dict[str, Any],
    ordered_semantics: dict[str, Any],
    resolved: dict[str, Any],
    missing_artifacts: list[str],
    availability: dict[str, bool],
    sensitivity: str,
    sensitivity_reason: str,
) -> str:
    status = classification.get("status") or "classification_unavailable"
    failure_family = classification.get("failure_family") or ordered_semantics.get("ordered_failure_mode")
    event_clause = describe_event_progression(ordered_semantics, failure_family)
    blocker, extra_count = build_gap_to_canonical(resolved, ordered_semantics, missing_artifacts, failure_family)

    available_labels = oxford_join([
      ARTIFACT_LABELS.get(key, humanize_token(key))
      for key, present in availability.items()
      if present
    ])

    if status == "canonical_resolved_strong":
      return (
        "Канонический resolved-strong run: clean entry-first progression подтверждён, "
        "paired raw coverage покрывает resolved-entry event."
      )

    if status == "failure_family_evidence":
      summary = f"Evidence семейства сбоев: {event_clause}."
      if sensitivity == "contamination_sensitive":
        summary += f" Run чувствителен к тайминг-сдвигу: {sensitivity_reason.rstrip('.')}."
      summary += f" Главный блокер до canonical: {blocker}."
      summary += format_extra_blockers(extra_count)
      return summary.strip()

    if missing_artifacts:
      lead = (
        f"Неполный forensic bundle: есть {available_labels}"
        if available_labels
        else "Неполный forensic bundle: есть только частичные артефакты"
      )
      summary = f"{lead}, но {blocker}."
      if failure_family:
        summary += f" Предварительный read указывает на {display_failure_label(failure_family)}."
      if sensitivity == "contamination_sensitive":
        summary += " Run остаётся чувствительным к тайминг-сдвигу."
      return summary.strip()

    if sensitivity == "contamination_sensitive":
      family_label = display_failure_label(failure_family or "forensic run")
      summary = (
        f"Тайминг-сдвиг / {family_label}: {event_clause}. "
        f"Главный блокер до canonical: {blocker}."
      )
      summary += format_extra_blockers(extra_count)
      return summary.strip()

    if failure_family:
      summary = (
        f"Предварительный forensic-read: {event_clause}. "
        f"Текущий failure path: {display_failure_label(failure_family)}. "
        f"Главный блокер до canonical: {blocker}."
      )
      summary += format_extra_blockers(extra_count)
      return summary.strip()

    summary = f"Предварительный forensic-read: {event_clause}. Главный блокер до canonical: {blocker}."
    summary += format_extra_blockers(extra_count)
    return summary.strip()


def determine_fate_group(classification: dict[str, Any], sensitivity: str) -> str:
    status = classification.get("status")

    if status == "canonical_resolved_strong":
      return "canonical"
    if sensitivity == "contamination_sensitive":
      return "timing_bias"
    if status == "failure_family_evidence":
      return "failure"
    return "incomplete"


def build_run_groups() -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}

    for path in sorted(ANALYSIS_DIR.glob("*.json")):
      kind = detect_kind(path)
      if not kind:
        continue

      payload, error = read_json(path)
      if error or not isinstance(payload, dict):
        continue

      run_id = payload.get("run_id")
      if not isinstance(run_id, str) or not run_id:
        continue

      entry = runs.setdefault(
        run_id,
        {
          "run_id": run_id,
          "paths": {},
          "meta": {},
          "payloads": {},
          "sort_ts": None,
        },
      )
      entry["paths"][kind] = str(path)
      entry["payloads"][kind] = payload
      if kind in {"bundle", "watcher", "raw_step"}:
        entry["meta"]["label"] = entry["meta"].get("label") or payload.get("label")
      entry["meta"]["artifact_label"] = entry["meta"].get("artifact_label") or payload.get("artifact_type")
      entry["sort_ts"] = best_timestamp(
        entry["sort_ts"],
        payload.get("generated_at"),
        payload.get("recording_started_at"),
        payload.get("started_at"),
        payload.get("signal_written_at"),
      )

    for entry in runs.values():
      bundle = entry["payloads"].get("bundle") or {}
      watcher = entry["payloads"].get("watcher") or {}
      raw_step = entry["payloads"].get("raw_step") or {}

      pairing_paths = {
        "watcher": raw_step.get("pairing", {}).get("watcher_artifact_path"),
        "bundle": watcher.get("pairing", {}).get("paired_bundle_path") or raw_step.get("pairing", {}).get("paired_bundle_path"),
        "raw_step": watcher.get("pairing", {}).get("raw_step_artifact_path"),
        "started": watcher.get("pairing", {}).get("started_signal_path") or raw_step.get("pairing", {}).get("started_signal_path"),
        "finished": watcher.get("pairing", {}).get("finished_signal_path") or raw_step.get("pairing", {}).get("finished_signal_path"),
      }

      expected_paths = {kind: value for kind, value in pairing_paths.items() if isinstance(value, str) and value}
      entry["expected_paths"] = expected_paths
      entry["missing_artifacts"] = [
        kind for kind in ["bundle", "watcher", "raw_step", "started", "finished"]
        if kind not in entry["paths"]
      ]

      ordered = bundle.get("ordered_semantics") or watcher.get("ordered_semantics") or {}
      sensitivity, sensitivity_reason = detect_evidence_sensitivity(ordered)
      resolved = bundle.get("resolved_strong_assessment") or {}
      status = resolved.get("status")
      availability = {kind: kind in entry["paths"] for kind in ["bundle", "watcher", "raw_step", "started", "finished"]}

      if status == "canonical_resolved_strong":
        classification = {
          "status": "canonical_resolved_strong",
          "label": "canonical_resolved_strong",
          "failure_family": None,
          "ready": True,
        }
      elif status == "failure_family_evidence":
        classification = {
          "status": "failure_family_evidence",
          "label": resolved.get("failure_family") or ordered.get("ordered_failure_mode") or "failure_family_evidence",
          "failure_family": resolved.get("failure_family") or ordered.get("ordered_failure_mode"),
          "ready": True,
        }
      else:
        classification = {
          "status": "incomplete_artifact_bundle",
          "label": ordered.get("ordered_failure_mode") or "classification_unavailable",
          "failure_family": None,
          "ready": False,
        }

      entry["classification"] = {
        **classification,
        "evidence_sensitivity": sensitivity,
        "evidence_sensitivity_reason": sensitivity_reason,
      }
      entry["fate_group"] = determine_fate_group(entry["classification"], sensitivity)
      entry["availability"] = availability
      entry["operator_summary_preview"] = build_operator_summary_preview(
        classification=entry["classification"],
        ordered_semantics=ordered,
        resolved=resolved,
        missing_artifacts=entry["missing_artifacts"],
        sensitivity=sensitivity,
      )
      entry["display_label"] = build_display_label(entry["run_id"], entry)

    return runs


def select_rows_by_sample(rows: list[dict[str, Any]], marker_indices: list[int], limit: int = 12) -> list[dict[str, Any]]:
    if not rows:
      return []

    total = len(rows)
    selected = {0, total - 1}

    for marker_index in marker_indices:
      if marker_index is None:
        continue
      selected.add(max(0, min(total - 1, int(marker_index))))
      selected.add(max(0, min(total - 1, int(marker_index) - 1)))
      selected.add(max(0, min(total - 1, int(marker_index) + 1)))

    if len(selected) > limit:
      selected = set(sorted(selected)[:limit])

    return [rows[index] for index in sorted(selected)]


def summarize_watcher_series(series: list[dict[str, Any]], ordered_semantics: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(series, list):
      return []

    first_strong_pulse = ordered_semantics.get("first_strong_pulse") or {}
    first_direction_assignment = ordered_semantics.get("first_direction_assignment") or {}
    first_resolution_event = ordered_semantics.get("first_resolution_event") or {}

    markers = {
      first_strong_pulse.get("elapsed_sec"): "first_strong_pulse",
      first_direction_assignment.get("elapsed_sec"): "first_direction_assignment",
      first_resolution_event.get("elapsed_sec"): "first_resolution_event",
    }

    result = []
    last_shadow_status = None
    for row in series:
      if not isinstance(row, dict):
        continue
      elapsed = row.get("elapsed_sec")
      marker_hits = [
        label
        for marker_elapsed, label in markers.items()
        if marker_elapsed is not None and elapsed is not None and abs(float(marker_elapsed) - float(elapsed)) <= 0.55
      ]
      shadow_status = row.get("shadow_status")
      row_summary = {
        "elapsed_sec": elapsed,
        "occupancy_state": row.get("occupancy_state"),
        "occupancy_event": row.get("occupancy_event"),
        "shadow_status": shadow_status,
        "shadow_reason": row.get("shadow_reason"),
        "shadow_context_validity": row.get("shadow_context_validity"),
        "shadow_pending_direction": row.get("shadow_pending_direction"),
        "live_total_packets": row.get("live_total_packets"),
        "markers": marker_hits,
      }
      if shadow_status != last_shadow_status or marker_hits:
        result.append(row_summary)
        last_shadow_status = shadow_status

    if not result:
      return [
        {
          "elapsed_sec": row.get("elapsed_sec"),
          "occupancy_state": row.get("occupancy_state"),
          "occupancy_event": row.get("occupancy_event"),
          "shadow_status": row.get("shadow_status"),
          "shadow_reason": row.get("shadow_reason"),
          "shadow_context_validity": row.get("shadow_context_validity"),
          "shadow_pending_direction": row.get("shadow_pending_direction"),
          "live_total_packets": row.get("live_total_packets"),
          "markers": [],
        }
        for row in series[:12]
        if isinstance(row, dict)
      ]

    return result[:18]


def summarize_raw_rows(raw_step: dict[str, Any], ordered_semantics: dict[str, Any]) -> list[dict[str, Any]]:
    rows = raw_step.get("rows") or []
    if not isinstance(rows, list):
      return []

    first_strong_pulse = ordered_semantics.get("first_strong_pulse") or {}
    first_direction_assignment = ordered_semantics.get("first_direction_assignment") or {}
    first_resolution_event = ordered_semantics.get("first_resolution_event") or {}

    marker_indices = [
      first_strong_pulse.get("sample_index"),
      first_direction_assignment.get("sample_index"),
      first_resolution_event.get("sample_index"),
    ]

    selected_rows = select_rows_by_sample(rows, marker_indices, limit=14)
    return [
      {
        "sample_index": row.get("sample_index"),
        "elapsed_sec": row.get("elapsed_sec"),
        "occupancy_state": row.get("occupancy_state"),
        "motion_state": row.get("motion_state"),
        "activity": row.get("activity"),
        "presence": row.get("presence"),
        "occupancy_probability": row.get("occupancy_probability"),
        "presence_probability": row.get("presence_probability"),
        "live_total_packets": row.get("metadata", {}).get("live_total_packets"),
        "topology_signature": "+".join(row.get("metadata", {}).get("live_source_signature", [])),
      }
      for row in selected_rows
      if isinstance(row, dict)
    ]


def summarize_paired_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    rows = bundle.get("paired_rows") or []
    if not isinstance(rows, list):
      return []

    interesting = []
    last_status = None
    for row in rows:
      if not isinstance(row, dict):
        continue
      markers = row.get("ordered_sequence_markers") or []
      watcher_status = row.get("watcher_shadow_status")
      if markers or watcher_status != last_status:
        interesting.append(row)
        last_status = watcher_status

    if not interesting:
      interesting = rows[:10]

    return [
      {
        "window_index": row.get("window_index"),
        "timestamp": row.get("timestamp"),
        "phase_label": row.get("phase_label"),
        "scenario_phase_label": row.get("scenario_phase_label"),
        "ordered_sequence_markers": row.get("ordered_sequence_markers") or [],
        "ordered_failure_mode": row.get("ordered_failure_mode"),
        "watcher_shadow_status": row.get("watcher_shadow_status"),
        "watcher_shadow_reason": row.get("watcher_shadow_reason"),
        "motion_state": row.get("motion_state"),
        "activity": row.get("activity"),
        "topology_signature": row.get("topology_signature"),
        "live_total_packets": row.get("live_window_summary", {}).get("total_packets"),
      }
      for row in interesting[:16]
      if isinstance(row, dict)
    ]


def build_run_detail(run_id: str) -> tuple[dict[str, Any] | None, HTTPStatus]:
    runs = build_run_groups()
    entry = runs.get(run_id)
    if not entry:
      return None, HTTPStatus.NOT_FOUND

    bundle = entry["payloads"].get("bundle") or {}
    watcher = entry["payloads"].get("watcher") or {}
    raw_step = entry["payloads"].get("raw_step") or {}
    started = entry["payloads"].get("started") or {}
    finished = entry["payloads"].get("finished") or {}

    ordered = bundle.get("ordered_semantics") or watcher.get("ordered_semantics") or {}
    sensitivity = entry["classification"]["evidence_sensitivity"]
    sensitivity_reason = entry["classification"]["evidence_sensitivity_reason"]
    classification = entry["classification"]
    resolved = bundle.get("resolved_strong_assessment") or {}
    availability = entry.get("availability") or {
      "bundle": "bundle" in entry["paths"],
      "watcher": "watcher" in entry["paths"],
      "raw_step": "raw_step" in entry["paths"],
      "started": "started" in entry["paths"],
      "finished": "finished" in entry["paths"],
    }
    operator_summary = build_operator_summary(
      classification=classification,
      ordered_semantics=ordered,
      resolved=resolved,
      missing_artifacts=entry["missing_artifacts"],
      availability=availability,
      sensitivity=sensitivity,
      sensitivity_reason=sensitivity_reason,
    )

    detail = {
      "generated_at": utc_now_iso(),
      "run_id": run_id,
      "display_label": entry["display_label"],
      "sort_ts": entry["sort_ts"],
      "label": entry["meta"].get("label"),
      "operator_summary": operator_summary,
      "operator_summary_preview": entry.get("operator_summary_preview"),
      "fate_group": entry.get("fate_group"),
      "artifact_paths": {
        "bundle": entry["paths"].get("bundle") or entry["expected_paths"].get("bundle"),
        "watcher": entry["paths"].get("watcher") or entry["expected_paths"].get("watcher"),
        "raw_step": entry["paths"].get("raw_step") or entry["expected_paths"].get("raw_step"),
        "started": entry["paths"].get("started") or entry["expected_paths"].get("started"),
        "finished": entry["paths"].get("finished") or entry["expected_paths"].get("finished"),
      },
      "availability": availability,
      "missing_artifacts": entry["missing_artifacts"],
      "classification": classification,
      "evidence": {
        "sensitivity": sensitivity,
        "sensitivity_reason": sensitivity_reason,
        "robust_for_selected_run": sensitivity == "robust",
        "contamination_sensitive_for_selected_run": sensitivity == "contamination_sensitive",
      },
      "ordered_semantics": ordered,
      "resolved_strong_assessment": resolved,
      "watcher": {
        "preflight": watcher.get("preflight"),
        "preflight_ok": watcher.get("preflight_ok"),
        "sequence": watcher.get("sequence"),
        "truth_preserving_checks": watcher.get("truth_preserving_checks"),
        "scenario_phase_windows": watcher.get("scenario_phase_windows") or bundle.get("scenario_phase_windows") or [],
        "series_excerpt": summarize_watcher_series(watcher.get("series") or [], ordered),
        "series_count": len(watcher.get("series") or []),
      },
      "raw_step": {
        "label": raw_step.get("label"),
        "setup_prompt": raw_step.get("setup_prompt"),
        "prompt": raw_step.get("prompt"),
        "phase_cues": raw_step.get("phase_cues") or [],
        "seconds": raw_step.get("seconds"),
        "samples": raw_step.get("samples"),
        "presence_true_count": raw_step.get("presence_true_count"),
        "occupancy_states": raw_step.get("occupancy_states"),
        "motion_states": raw_step.get("motion_states"),
        "activities": raw_step.get("activities"),
        "rows_excerpt": summarize_raw_rows(raw_step, ordered),
      },
      "paired_bundle": {
        "sample_counts": bundle.get("sample_counts"),
        "scenario_phase_windows": bundle.get("scenario_phase_windows") or [],
        "watcher_stage_markers": bundle.get("watcher_stage_markers") or [],
        "paired_rows_excerpt": summarize_paired_rows(bundle),
      },
      "signals": {
        "started": started,
        "finished": finished,
      },
    }
    return detail, HTTPStatus.OK


class NoCacheHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
      parsed = urlparse(path)
      if parsed.path.startswith("/workspace/"):
        rel = parsed.path.removeprefix("/workspace/")
        candidate = safe_workspace_path(rel)
        if candidate:
          return str(candidate)
      return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
      parsed = urlparse(self.path)

      if parsed.path == "/api/agent7/forensics/runs":
        runs = build_run_groups()
        payload = {
          "generated_at": utc_now_iso(),
          "runs": sorted(
            [
              {
                "run_id": entry["run_id"],
                "display_label": entry["display_label"],
                "label": entry["meta"].get("label"),
                "sort_ts": entry["sort_ts"],
                "operator_summary_preview": entry.get("operator_summary_preview"),
                "fate_group": entry.get("fate_group"),
                "classification": entry["classification"],
                "missing_artifacts": entry["missing_artifacts"],
                "availability": entry.get("availability") or {kind: kind in entry["paths"] for kind in ["bundle", "watcher", "raw_step", "started", "finished"]},
              }
              for entry in runs.values()
            ],
            key=lambda item: parse_timestamp(item.get("sort_ts")),
            reverse=True,
          ),
        }
        return self.send_json(payload)

      if parsed.path == "/api/agent7/forensics/run":
        query = parse_qs(parsed.query)
        run_id = query.get("run_id", [None])[0]
        if not run_id:
          return self.send_json({"error": "run_id query parameter is required"}, HTTPStatus.BAD_REQUEST)

        detail, status = build_run_detail(run_id)
        if not detail:
          return self.send_json({"error": f"Run '{run_id}' was not found"}, status)
        return self.send_json(detail, status)

      if parsed.path == "/api/manual-zone-review/sessions":
        manifest = load_manual_zone_manifest()
        if not manifest:
          return self.send_json(
            {
              "error": "manual zone review manifest not found",
              "expected_path": str(MANUAL_ZONE_REVIEW_MANIFEST),
            },
            HTTPStatus.NOT_FOUND,
          )
        return self.send_json(manifest)

      if parsed.path == "/api/manual-zone-review/labels":
        query = parse_qs(parsed.query)
        session_label = query.get("session_label", [None])[0]
        if not session_label:
          return self.send_json({"error": "session_label query parameter is required"}, HTTPStatus.BAD_REQUEST)
        session = find_manual_zone_session(session_label)
        if not session:
          return self.send_json({"error": f"Unknown session_label '{session_label}'"}, HTTPStatus.NOT_FOUND)
        label_path = safe_workspace_path(session.get("label_output_relpath") or "")
        if not label_path or not label_path.exists():
          return self.send_json({"ok": True, "exists": False, "session_label": session_label, "labels": None})
        payload, error = read_json(label_path)
        if error:
          return self.send_json({"error": error, "session_label": session_label}, HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.send_json({"ok": True, "exists": True, "session_label": session_label, "labels": payload})

      return super().do_GET()

    def do_POST(self):
      parsed = urlparse(self.path)

      if parsed.path == "/api/manual-zone-review/labels":
        try:
          content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
          content_length = 0
        try:
          raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
          payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
          return self.send_json({"error": f"invalid json payload: {exc}"}, HTTPStatus.BAD_REQUEST)

        session_label = payload.get("session_label")
        if not isinstance(session_label, str) or not session_label:
          return self.send_json({"error": "session_label is required"}, HTTPStatus.BAD_REQUEST)

        session = find_manual_zone_session(session_label)
        if not session:
          return self.send_json({"error": f"Unknown session_label '{session_label}'"}, HTTPStatus.NOT_FOUND)

        label_path = safe_workspace_path(session.get("label_output_relpath") or "")
        if not label_path:
          return self.send_json({"error": "label_output_relpath is invalid"}, HTTPStatus.BAD_REQUEST)

        record = {
          "session_label": session_label,
          "saved_at": utc_now_iso(),
          "schema_version": 1,
          "window_sec": payload.get("window_sec"),
          "duration_sec": payload.get("duration_sec"),
          "source_video_relpath": session.get("video_relpath"),
          "source_video_url": session.get("video_url"),
          "labels": payload.get("labels") or [],
          "meta": payload.get("meta") or {},
        }
        write_json(label_path, record)
        return self.send_json(
          {
            "ok": True,
            "session_label": session_label,
            "saved_path": str(label_path),
            "label_count": len(record["labels"]),
          }
        )

      return self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK):
      body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
      self.send_response(status)
      self.send_header("Content-Type", "application/json; charset=utf-8")
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 3000), lambda *args, **kwargs: NoCacheHandler(*args, directory=str(UI_DIR), **kwargs))
    print("Serving UI on http://127.0.0.1:3000 (cache disabled)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
