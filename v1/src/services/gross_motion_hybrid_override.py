from __future__ import annotations

from typing import Any, Dict, Iterable


def signature_key_from_source_signature(source_signature: Iterable[str] | str | None) -> str:
    if source_signature is None:
        return "none"
    if isinstance(source_signature, str):
        value = source_signature.strip()
        return value or "none"
    normalized = [str(item).strip() for item in source_signature if str(item).strip()]
    if not normalized:
        return "none"
    return "+".join(normalized)


def _evaluate_threshold(value: float | None, op: str, threshold: float) -> bool:
    if value is None:
        return False
    if op == ">=":
        return value >= threshold
    if op == ">":
        return value > threshold
    if op == "<=":
        return value <= threshold
    if op == "<":
        return value < threshold
    if op == "==":
        return value == threshold
    return False


def apply_gross_motion_hybrid_override_candidate(
    candidate: Dict[str, Any],
    *,
    source_signature: Iterable[str] | str | None,
    baseline_probability: float,
    baseline_prediction: int | bool,
    baseline_threshold: float,
    feature_map: Dict[str, Any],
) -> Dict[str, Any]:
    signature_key = signature_key_from_source_signature(source_signature)
    rule = candidate.get("override_rule") or {}
    feature_conditions = list(rule.get("feature_conditions") or [])
    prob_band = rule.get("probability_band") or {}
    override_action = rule.get("override_action") or {}
    required_signature = str((rule.get("source_signature_condition") or {}).get("exact") or "").strip()
    prob_min = float(prob_band.get("min") or 0.0)
    prob_max = float(prob_band.get("max") or 1.0)
    inclusive_min = bool(prob_band.get("inclusive_min", True))
    exclusive_max = bool(prob_band.get("exclusive_max", True))
    require_baseline_negative = bool(prob_band.get("requires_baseline_negative", True))

    signature_match = bool(required_signature and signature_key == required_signature)
    if inclusive_min:
        prob_min_match = float(baseline_probability) >= prob_min
    else:
        prob_min_match = float(baseline_probability) > prob_min
    if exclusive_max:
        prob_max_match = float(baseline_probability) < prob_max
    else:
        prob_max_match = float(baseline_probability) <= prob_max
    probability_band_match = bool(prob_min_match and prob_max_match)
    baseline_negative_match = (not bool(baseline_prediction)) if require_baseline_negative else True

    evaluated_conditions = []
    conditions_match = True
    for condition in feature_conditions:
        feature_name = str(condition.get("feature") or "").strip()
        op = str(condition.get("op") or "").strip()
        threshold = float(condition.get("threshold") or 0.0)
        raw_value = feature_map.get(feature_name)
        feature_value = None if raw_value in (None, "") else float(raw_value)
        matched = _evaluate_threshold(feature_value, op, threshold)
        evaluated_conditions.append(
            {
                "feature": feature_name,
                "op": op,
                "threshold": threshold,
                "value": feature_value,
                "matched": matched,
            }
        )
        conditions_match &= matched

    override_applied = bool(
        signature_match and probability_band_match and baseline_negative_match and conditions_match
    )
    final_prediction = bool(baseline_prediction)
    final_probability = float(baseline_probability)
    reason = "baseline_kept"
    if override_applied:
        final_prediction = True
        min_probability = float(
            override_action.get("promote_probability_to_at_least")
            or override_action.get("min_probability")
            or baseline_threshold
            or baseline_probability
        )
        final_probability = max(float(baseline_probability), min_probability)
        reason = "hybrid_narrow_override_applied"
    elif not signature_match:
        reason = "signature_mismatch"
    elif not baseline_negative_match:
        reason = "baseline_already_positive"
    elif not probability_band_match:
        reason = "probability_band_mismatch"
    elif not conditions_match:
        reason = "feature_conditions_mismatch"

    return {
        "signature_key": signature_key,
        "required_signature": required_signature or None,
        "signature_match": signature_match,
        "baseline_probability": float(baseline_probability),
        "baseline_threshold": float(baseline_threshold),
        "baseline_prediction": bool(baseline_prediction),
        "baseline_negative_match": baseline_negative_match,
        "probability_band": {
            "min": prob_min,
            "max": prob_max,
            "inclusive_min": inclusive_min,
            "exclusive_max": exclusive_max,
        },
        "probability_band_match": probability_band_match,
        "feature_conditions": evaluated_conditions,
        "conditions_match": conditions_match,
        "override_applied": override_applied,
        "final_prediction": bool(final_prediction),
        "final_probability": float(final_probability),
        "override_action": override_action,
        "reason": reason,
    }
