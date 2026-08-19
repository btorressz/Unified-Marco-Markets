"""Bounded, research-only sensitivity and sampled robustness over immutable decisions.

Every cell is an actual deterministic replay from one exact-verified historical
baseline. This module never persists, reads runtime state, routes orders, searches
for a boundary, or changes risk/execution policy.
"""
from __future__ import annotations

import math
from typing import Any

from backend.compute.counterfactual_replay import (
    CounterfactualUnavailable,
    counterfactual_from_prepared,
    counterfactual_numeric_fields,
    prepare_counterfactual,
    recorded_counterfactual_baseline,
)

MAX_SENSITIVITY_CELLS = 100
MAX_AXIS_POINTS = 50
PRESET_VERSION = "baseline_neighborhood_v1"
ROBUSTNESS_VERSION = "sampled_local_v1"

# Bounds mirror replay validation. None means that no hard bound is substantiated.
_FIELD_METADATA: dict[str, dict[str, Any]] = {
    "spread_bps": {"label": "Spread", "unit": "bps", "semantic_minimum": 0.0, "semantic_maximum": None, "range_type": "non_negative", "reference_scale": 10.0},
    "liquidity_depth": {"label": "Liquidity depth", "unit": "depth units", "semantic_minimum": 0.0, "semantic_maximum": None, "range_type": "non_negative", "reference_scale": 50.0},
    "order_size": {"label": "Order size", "unit": "base/order units", "semantic_minimum": 0.0, "semantic_maximum": None, "range_type": "positive", "reference_scale": 1.0},
    "fill_price": {"label": "Fill price", "unit": "quote price", "semantic_minimum": 0.0, "semantic_maximum": None, "range_type": "positive", "reference_scale": 1.0},
    "daily_pnl": {"label": "Daily P&L", "unit": "quote/P&L units", "semantic_minimum": None, "semantic_maximum": None, "range_type": "unbounded", "reference_scale": 100.0},
    "shock_score": {"label": "Shock score", "unit": "score units", "semantic_minimum": None, "semantic_maximum": None, "range_type": "unbounded", "reference_scale": 1.0},
    "stable_health": {"label": "Stable health", "unit": "normalized 0–1", "semantic_minimum": 0.0, "semantic_maximum": 1.0, "range_type": "closed_interval", "reference_scale": 1.0},
    "predictor_confidence": {"label": "Predictor confidence", "unit": "normalized 0–1", "semantic_minimum": 0.0, "semantic_maximum": 1.0, "range_type": "closed_interval", "reference_scale": 1.0},
    "tariff_index": {"label": "Tariff index", "unit": "index points", "semantic_minimum": None, "semantic_maximum": None, "range_type": "unbounded", "reference_scale": 1.0},
    "tariff_delta": {"label": "Tariff delta", "unit": "index points", "semantic_minimum": None, "semantic_maximum": None, "range_type": "unbounded", "reference_scale": 1.0},
}

# The replay contract does not substantiate canonical units or hard ranges for these.
for _field in counterfactual_numeric_fields():
    _FIELD_METADATA.setdefault(_field, {
        "label": _field.replace("_", " ").title(),
        "unit": "unspecified",
        "semantic_minimum": None,
        "semantic_maximum": None,
        "range_type": "unbounded",
        "reference_scale": 1.0,
    })


class SensitivityUnavailable(ValueError):
    pass


def counterfactual_field_metadata(field: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    """Return deterministic semantic metadata for supported numeric fields."""
    def public(name: str) -> dict[str, Any]:
        return {"field": name, **_FIELD_METADATA[name], "preset_support": True}
    if field is not None:
        if field not in _FIELD_METADATA:
            raise SensitivityUnavailable(f"unsupported numeric sensitivity field: {field}")
        return public(field)
    return [public(name) for name in counterfactual_numeric_fields()]


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SensitivityUnavailable(f"{field} sensitivity values must be numeric") from exc
    if not math.isfinite(number):
        raise SensitivityUnavailable(f"{field} sensitivity values must be finite")
    return number


def _request_axis(axis: Any, name: str) -> dict[str, Any]:
    if not isinstance(axis, dict):
        raise SensitivityUnavailable(f"{name} axis must be an object")
    field = str(axis.get("field") or "").strip()
    if field not in counterfactual_numeric_fields():
        raise SensitivityUnavailable(f"unsupported numeric sensitivity field: {field or '<empty>'}")
    preset = str(axis.get("preset") or "manual").lower().strip()
    if preset not in {"manual", "local", "standard", "wide"}:
        raise SensitivityUnavailable(f"unsupported {name} axis preset: {preset}")
    raw = axis.get("values")
    if preset == "manual":
        if not isinstance(raw, list) or not raw:
            raise SensitivityUnavailable(f"{name} axis values must be a non-empty array")
        if len(raw) > MAX_AXIS_POINTS:
            raise SensitivityUnavailable(f"{name} axis exceeds maximum {MAX_AXIS_POINTS} points")
        values = [_finite(value, field) for value in raw]
        if len(set(values)) != len(values):
            raise SensitivityUnavailable(f"{name} axis contains duplicate values")
    else:
        if raw not in (None, []):
            raise SensitivityUnavailable(f"{name} preset axis must not also supply values")
        values = []
    return {"field": field, "preset": preset, "requested_values": values}


def _same(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _preset_values(baseline: float, metadata: dict[str, Any], preset: str) -> list[float]:
    fractions = {"local": 0.05, "standard": 0.20, "wide": 0.50}
    step = fractions[preset] * max(abs(baseline), float(metadata["reference_scale"]))
    values = [baseline + offset * step for offset in (-2, -1, 0, 1, 2)]
    minimum, maximum = metadata["semantic_minimum"], metadata["semantic_maximum"]
    clipped = [max(minimum, value) if minimum is not None else value for value in values]
    clipped = [min(maximum, value) if maximum is not None else value for value in clipped]
    if metadata["range_type"] == "positive":
        clipped = [value for value in clipped if value > 0]
    unique: list[float] = []
    for value in clipped:
        value = float(value)
        if not any(_same(value, known) for known in unique):
            unique.append(value)
    return sorted(unique)


def _resolve_axis(request: dict[str, Any], baseline: dict[str, Any], name: str) -> dict[str, Any]:
    field, preset = request["field"], request["preset"]
    metadata = counterfactual_field_metadata(field)
    assert isinstance(metadata, dict)
    baseline = {**baseline, "unit": metadata["unit"]}
    scalar = baseline.get("status") == "available" and baseline.get("consistent") is True
    if preset != "manual" and not scalar:
        raise SensitivityUnavailable(f"{name} axis preset requires an available consistent recorded baseline")
    requested = list(request["requested_values"])
    values = _preset_values(float(baseline["value"]), metadata, preset) if preset != "manual" else list(requested)
    inserted = False
    if scalar and not any(_same(float(baseline["value"]), value) for value in values):
        values.append(float(baseline["value"]))
        values.sort()
        inserted = True
    if len(values) > MAX_AXIS_POINTS:
        raise SensitivityUnavailable(f"{name} resolved axis exceeds maximum {MAX_AXIS_POINTS} points after baseline insertion")
    return {
        "field": field,
        "values": values,  # backwards-compatible resolved alias
        "requested_values": requested,
        "resolved_values": values,
        "preset": preset,
        "preset_version": PRESET_VERSION if preset != "manual" else None,
        "baseline": baseline,
        "baseline_value": baseline.get("value") if scalar else None,
        "baseline_inserted": inserted,
        "metadata": metadata,
        "unit": metadata["unit"],
    }


def _decision_label(final: dict[str, Any] | None) -> str:
    final = final or {}
    if isinstance(final.get("allowed"), bool):
        return "allow" if final["allowed"] else "block"
    value = str(final.get("decision") or "").lower().strip()
    return value if value in {"allow", "block"} else "unknown"


def _interpret_action(action: str, signed_return: float) -> str:
    if action == "allow":
        return "requested_side_favorable" if signed_return > 0 else "requested_side_adverse" if signed_return < 0 else "flat"
    if action == "block":
        return "missed_favorable_move" if signed_return > 0 else "avoided_adverse_move" if signed_return < 0 else "flat"
    return "unavailable"


def _compact_point(result: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    final = ((result.get("counterfactual") or {}).get("final_decision") or {})
    return {"scenario": scenario, "decision": _decision_label(final), "allowed": final.get("allowed"), "stage": final.get("stage"), "reasons": [str(v) for v in (final.get("reasons") or [])], "changed_from_original": bool((result.get("effects") or {}).get("final_decision_changed")), "not_applicable": list(result.get("not_applicable") or [])}


def _transitions(points: list[dict[str, Any]], field: str) -> dict[str, Any]:
    ordered = sorted(points, key=lambda point: float(point["scenario"][field]))
    transitions, labels, previous = [], [], None
    for point in ordered:
        label = str(point.get("decision") or "unknown")
        labels.append(label)
        if previous is not None and label != previous["decision"]:
            transitions.append({"lower_value": previous["value"], "upper_value": point["scenario"][field], "from_decision": previous["decision"], "to_decision": label, "boundary_bracket": [previous["value"], point["scenario"][field]]})
        previous = {"value": point["scenario"][field], "decision": label}
    distinct = [label for index, label in enumerate(labels) if index == 0 or label != labels[index - 1]]
    if not transitions:
        monotonicity = "no_transition"
    elif len(transitions) == 1 and distinct == ["allow", "block"]:
        monotonicity = "monotonic_allow_to_block"
    elif len(transitions) == 1 and distinct == ["block", "allow"]:
        monotonicity = "monotonic_block_to_allow"
    else:
        monotonicity = "non_monotonic"
    return {"analysis_order": "ascending_numeric", "monotonicity": monotonicity, "transition_count": len(transitions), "transitions": transitions}


def _robustness(axis: dict[str, Any], boundary: dict[str, Any], baseline_decision: str) -> dict[str, Any]:
    baseline = axis["baseline"]
    common = {"research_only": True, "sampled_only": True, "field": axis["field"], "unit": axis["unit"]}
    if baseline.get("status") != "available" or not baseline.get("consistent"):
        return {**common, "status": "unavailable", "baseline": baseline, "nearest_sampled_boundary": {"available": False, "reason": "baseline_unavailable_or_inconsistent"}, "distance": {"available": False}, "local_robustness": {"classification": "UNAVAILABLE", "version": ROBUSTNESS_VERSION}}
    value = float(baseline["value"])
    candidates = [item for item in boundary["transitions"] if {item["from_decision"], item["to_decision"]} == {"allow", "block"}]
    baseline_info = {"status": "available", "value": value, "decision": baseline_decision, "inserted": axis["baseline_inserted"], "consistent": True}
    if not candidates:
        return {**common, "status": "no_boundary_observed", "baseline": baseline_info, "nearest_sampled_boundary": {"available": False, "sampled": True, "reason": "no_transition_in_sampled_range"}, "distance": {"available": False, "unit": axis["unit"]}, "local_robustness": {"classification": "NO_BOUNDARY_OBSERVED", "version": ROBUSTNESS_VERSION, "interpretation": "No decision boundary was observed in the sampled range."}}
    def key(item: dict[str, Any]) -> tuple[float, float, float]:
        lower, upper = map(float, item["boundary_bracket"])
        return min(abs(lower - value), abs(upper - value)), lower, upper
    nearest = min(candidates, key=key)
    lower, upper = map(float, nearest["boundary_bracket"])
    distances = sorted((abs(lower - value), abs(upper - value)))
    relation = "baseline_below_boundary" if value < lower else "baseline_above_boundary" if value > upper else "baseline_within_sampled_bracket"
    reference = max(abs(value), float(axis["metadata"]["reference_scale"]))
    normalized = distances[0] / reference
    classification = "LOW" if normalized <= 0.05 else "MEDIUM" if normalized <= 0.20 else "HIGH"
    return {
        **common, "status": "available", "baseline": baseline_info,
        "nearest_sampled_boundary": {"available": True, "sampled": True, "baseline_value": value, "baseline_decision": baseline_decision, "boundary_bracket": [lower, upper], "from_decision": nearest["from_decision"], "to_decision": nearest["to_decision"], "relation": relation, "unit": axis["unit"], "qualifying_boundary_count": len(candidates)},
        "distance": {"available": True, "min": distances[0], "max": distances[1], "distance_min": distances[0], "distance_max": distances[1], "lower_delta": lower - value, "upper_delta": upper - value, "unit": axis["unit"], "sampled_interval": True},
        "local_robustness": {"classification": classification, "version": ROBUSTNESS_VERSION, "baseline_value": value, "reference_scale": reference, "distance_min": distances[0], "normalized_distance": normalized, "unit": axis["unit"], "bands": {"LOW": "<= 0.05", "MEDIUM": "> 0.05 and <= 0.20", "HIGH": "> 0.20"}, "interpretation": "Descriptive robustness within sampled values only; not probability, confidence, a live safety margin, or policy advice."},
    }


def _realized_overlay(point: dict[str, Any], realized_outcome: dict[str, Any] | None, horizon: str | None) -> dict[str, Any] | None:
    if not realized_outcome or not horizon:
        return None
    outcome = (realized_outcome.get("outcomes") or {}).get(horizon)
    if not outcome:
        return {"available": False, "horizon": horizon, "reason": "realized horizon outcome unavailable"}
    signed_return = float(outcome.get("signed_return") or 0.0)
    return {"available": True, "horizon": horizon, "realized_signed_return": signed_return, "market_classification": outcome.get("classification"), "interpretation": _interpret_action(str(point.get("decision") or "unknown"), signed_return), "return_basis": "original_decision_reference_price"}


def counterfactual_sensitivity(record: dict[str, Any], *, x: dict[str, Any], y: dict[str, Any] | None = None, fixed_scenario: dict[str, Any] | None = None, realized_outcome: dict[str, Any] | None = None, outcome_horizon: str | None = None, model_loader=None) -> dict[str, Any]:
    """Run one bounded 1-D sweep or 2-D decision-boundary matrix."""
    x_request, y_request = _request_axis(x, "x"), _request_axis(y, "y") if y is not None else None
    if y_request and y_request["field"] == x_request["field"]:
        raise SensitivityUnavailable("x and y sensitivity fields must be different")
    fixed = dict(fixed_scenario or {})
    for reserved in (x_request["field"], y_request["field"] if y_request else None):
        if reserved and reserved in fixed:
            raise SensitivityUnavailable(f"fixed_scenario cannot also set swept field: {reserved}")
    try:
        prepared = prepare_counterfactual(record, model_loader=model_loader)
        x_baseline = recorded_counterfactual_baseline(record, x_request["field"])
        y_baseline = recorded_counterfactual_baseline(record, y_request["field"]) if y_request else None
    except CounterfactualUnavailable as exc:
        raise SensitivityUnavailable(str(exc)) from exc
    x_axis = _resolve_axis(x_request, x_baseline, "x")
    y_axis = _resolve_axis(y_request, y_baseline, "y") if y_request and y_baseline else None
    total_cells = len(x_axis["values"]) * (len(y_axis["values"]) if y_axis else 1)
    if total_cells > MAX_SENSITIVITY_CELLS:
        raise SensitivityUnavailable(f"sensitivity request exceeds maximum {MAX_SENSITIVITY_CELLS} cells after baseline insertion")

    original_final = ((prepared.get("original") or {}).get("final_decision") or {})
    warnings: list[str] = []
    if x_axis["field"] == "fill_price" or (y_axis and y_axis["field"] == "fill_price") or "fill_price" in fixed:
        warnings.append("Realized overlay remains measured from the original decision reference price when fill_price is varied.")
    matrix = []
    for y_value in y_axis["values"] if y_axis else [None]:
        row = []
        for x_value in x_axis["values"]:
            scenario = dict(fixed); scenario[x_axis["field"]] = x_value
            if y_axis: scenario[y_axis["field"]] = y_value
            try: replayed = counterfactual_from_prepared(prepared, scenario)
            except CounterfactualUnavailable as exc: raise SensitivityUnavailable(str(exc)) from exc
            point = _compact_point(replayed, scenario)
            point["is_baseline_x"] = x_axis["baseline_value"] is not None and _same(x_value, x_axis["baseline_value"])
            point["is_baseline_y"] = bool(y_axis and y_axis["baseline_value"] is not None and _same(y_value, y_axis["baseline_value"]))
            point["is_baseline"] = point["is_baseline_x"] and (not y_axis or point["is_baseline_y"])
            overlay = _realized_overlay(point, realized_outcome, outcome_horizon)
            if overlay is not None: point["realized_outcome"] = overlay
            row.append(point)
        matrix.append(row)
    result = {"status": "COMPUTED", "sensitivity_status": "computed", "research_only": True, "audit_only": True, "persisted": False, "orders_submitted": 0, "decision_id": str(record.get("id") or ""), "decision_ts": record.get("decision_ts"), "dimensions": 2 if y_axis else 1, "x": x_axis, "y": y_axis, "field_metadata": counterfactual_field_metadata(), "fixed_scenario": fixed, "cell_count": total_cells, "maximum_cells": MAX_SENSITIVITY_CELLS, "baseline": {"exact_match": True, "hash": (prepared.get("baseline") or {}).get("replay_hash"), "final_decision": original_final}, "matrix": matrix, "warnings": warnings}
    if not y_axis:
        result["points"] = matrix[0]
        result["boundary_analysis"] = _transitions(matrix[0], x_axis["field"])
        result["robustness"] = _robustness(x_axis, result["boundary_analysis"], _decision_label(original_final))
    else:
        result["row_boundary_analysis"] = [{"y_value": value, **_transitions(row, x_axis["field"])} for value, row in zip(y_axis["values"], matrix)]
        columns = [[matrix[r][c] for r in range(len(matrix))] for c in range(len(x_axis["values"]))]
        result["column_boundary_analysis"] = [{"x_value": value, **_transitions(column, y_axis["field"])} for value, column in zip(x_axis["values"], columns)]
        analyses = result["row_boundary_analysis"] + result["column_boundary_analysis"]
        result["surface_monotonicity"] = "non_monotonic" if any(item["monotonicity"] == "non_monotonic" for item in analyses) else "monotonic_or_no_transition"
    if realized_outcome is not None and outcome_horizon:
        outcome = (realized_outcome.get("outcomes") or {}).get(outcome_horizon)
        result["realized_outcome_overlay"] = {"available": outcome is not None, "horizon": outcome_horizon, "realized_signed_return": float(outcome.get("signed_return")) if outcome else None, "return_basis": "original_decision_reference_price", "interpretation": "Each ALLOW/BLOCK cell is interpreted against the same realized historical market move; blocked cells are counterfactual avoidance/opportunity observations, not realized P&L."}
    return result
