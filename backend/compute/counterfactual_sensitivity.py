"""Research-only counterfactual sensitivity sweeps over immutable decisions.

This module is a bounded batch-analysis layer over the existing counterfactual
replay engine. It never persists, reads Redis, routes orders, retrains models, or
changes risk/execution policy. Every cell is an actual deterministic replay from
one exact-verified historical baseline.
"""
from __future__ import annotations

import math
from typing import Any

from backend.compute.counterfactual_replay import (
    CounterfactualUnavailable,
    counterfactual_from_prepared,
    counterfactual_numeric_fields,
    prepare_counterfactual,
)

MAX_SENSITIVITY_CELLS = 100
MAX_AXIS_POINTS = 50


class SensitivityUnavailable(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SensitivityUnavailable(f"{field} sensitivity values must be numeric") from exc
    if not math.isfinite(number):
        raise SensitivityUnavailable(f"{field} sensitivity values must be finite")
    return number


def _axis(axis: Any, name: str) -> dict[str, Any]:
    if not isinstance(axis, dict):
        raise SensitivityUnavailable(f"{name} axis must be an object")
    field = str(axis.get("field") or "").strip()
    if field not in counterfactual_numeric_fields():
        raise SensitivityUnavailable(f"unsupported numeric sensitivity field: {field or '<empty>'}")
    raw_values = axis.get("values")
    if not isinstance(raw_values, list) or not raw_values:
        raise SensitivityUnavailable(f"{name} axis values must be a non-empty array")
    if len(raw_values) > MAX_AXIS_POINTS:
        raise SensitivityUnavailable(f"{name} axis exceeds maximum {MAX_AXIS_POINTS} points")
    values = [_finite(value, field) for value in raw_values]
    if len(set(values)) != len(values):
        raise SensitivityUnavailable(f"{name} axis contains duplicate values")
    return {"field": field, "values": values}


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
    return {
        "scenario": scenario,
        "decision": _decision_label(final),
        "allowed": final.get("allowed"),
        "stage": final.get("stage"),
        "reasons": [str(value) for value in (final.get("reasons") or [])],
        "changed_from_original": bool((result.get("effects") or {}).get("final_decision_changed")),
        "not_applicable": list(result.get("not_applicable") or []),
    }


def _transitions(points: list[dict[str, Any]], field: str) -> dict[str, Any]:
    ordered = sorted(points, key=lambda point: float(point["scenario"][field]))
    transitions: list[dict[str, Any]] = []
    labels = []
    previous = None
    for point in ordered:
        label = str(point.get("decision") or "unknown")
        labels.append(label)
        if previous is not None and label != previous["decision"]:
            transitions.append({
                "lower_value": previous["value"],
                "upper_value": point["scenario"][field],
                "from_decision": previous["decision"],
                "to_decision": label,
                "boundary_bracket": [previous["value"], point["scenario"][field]],
            })
        previous = {"value": point["scenario"][field], "decision": label}

    distinct = [label for index, label in enumerate(labels) if index == 0 or label != labels[index - 1]]
    if len(transitions) == 0:
        monotonicity = "no_transition"
    elif len(transitions) == 1 and distinct == ["allow", "block"]:
        monotonicity = "monotonic_allow_to_block"
    elif len(transitions) == 1 and distinct == ["block", "allow"]:
        monotonicity = "monotonic_block_to_allow"
    else:
        monotonicity = "non_monotonic"

    return {
        "analysis_order": "ascending_numeric",
        "monotonicity": monotonicity,
        "transition_count": len(transitions),
        "transitions": transitions,
    }


def _realized_overlay(
    point: dict[str, Any],
    realized_outcome: dict[str, Any] | None,
    horizon: str | None,
) -> dict[str, Any] | None:
    if not realized_outcome or not horizon:
        return None
    outcome = (realized_outcome.get("outcomes") or {}).get(horizon)
    if not outcome:
        return {
            "available": False,
            "horizon": horizon,
            "reason": "realized horizon outcome unavailable",
        }
    signed_return = float(outcome.get("signed_return") or 0.0)
    return {
        "available": True,
        "horizon": horizon,
        "realized_signed_return": signed_return,
        "market_classification": outcome.get("classification"),
        "interpretation": _interpret_action(str(point.get("decision") or "unknown"), signed_return),
        "return_basis": "original_decision_reference_price",
    }


def counterfactual_sensitivity(
    record: dict[str, Any],
    *,
    x: dict[str, Any],
    y: dict[str, Any] | None = None,
    fixed_scenario: dict[str, Any] | None = None,
    realized_outcome: dict[str, Any] | None = None,
    outcome_horizon: str | None = None,
    model_loader=None,
) -> dict[str, Any]:
    """Run one bounded 1-D sweep or 2-D decision-boundary matrix."""
    x_axis = _axis(x, "x")
    y_axis = _axis(y, "y") if y is not None else None
    if y_axis and y_axis["field"] == x_axis["field"]:
        raise SensitivityUnavailable("x and y sensitivity fields must be different")

    fixed = dict(fixed_scenario or {})
    for reserved in (x_axis["field"], y_axis["field"] if y_axis else None):
        if reserved and reserved in fixed:
            raise SensitivityUnavailable(f"fixed_scenario cannot also set swept field: {reserved}")

    total_cells = len(x_axis["values"]) * (len(y_axis["values"]) if y_axis else 1)
    if total_cells > MAX_SENSITIVITY_CELLS:
        raise SensitivityUnavailable(f"sensitivity request exceeds maximum {MAX_SENSITIVITY_CELLS} cells")

    try:
        prepared = prepare_counterfactual(record, model_loader=model_loader)
    except CounterfactualUnavailable as exc:
        raise SensitivityUnavailable(str(exc)) from exc

    original_final = ((prepared.get("original") or {}).get("final_decision") or {})
    warnings: list[str] = []
    if x_axis["field"] == "fill_price" or (y_axis and y_axis["field"] == "fill_price") or "fill_price" in fixed:
        warnings.append("Realized overlay remains measured from the original decision reference price when fill_price is varied.")

    matrix: list[list[dict[str, Any]]] = []
    y_values = y_axis["values"] if y_axis else [None]
    for y_value in y_values:
        row: list[dict[str, Any]] = []
        for x_value in x_axis["values"]:
            scenario = dict(fixed)
            scenario[x_axis["field"]] = x_value
            if y_axis:
                scenario[y_axis["field"]] = y_value
            try:
                replayed = counterfactual_from_prepared(prepared, scenario)
            except CounterfactualUnavailable as exc:
                raise SensitivityUnavailable(str(exc)) from exc
            point = _compact_point(replayed, scenario)
            overlay = _realized_overlay(point, realized_outcome, outcome_horizon)
            if overlay is not None:
                point["realized_outcome"] = overlay
            row.append(point)
        matrix.append(row)

    result: dict[str, Any] = {
        "status": "COMPUTED",
        "sensitivity_status": "computed",
        "research_only": True,
        "audit_only": True,
        "persisted": False,
        "orders_submitted": 0,
        "decision_id": str(record.get("id") or ""),
        "decision_ts": record.get("decision_ts"),
        "dimensions": 2 if y_axis else 1,
        "x": x_axis,
        "y": y_axis,
        "fixed_scenario": fixed,
        "cell_count": total_cells,
        "maximum_cells": MAX_SENSITIVITY_CELLS,
        "baseline": {
            "exact_match": True,
            "hash": (prepared.get("baseline") or {}).get("replay_hash"),
            "final_decision": original_final,
        },
        "matrix": matrix,
        "warnings": warnings,
    }

    if not y_axis:
        result["points"] = matrix[0]
        result["boundary_analysis"] = _transitions(matrix[0], x_axis["field"])
    else:
        result["row_boundary_analysis"] = [
            {
                "y_value": y_value,
                **_transitions(row, x_axis["field"]),
            }
            for y_value, row in zip(y_axis["values"], matrix)
        ]
        columns = [
            [matrix[row_index][column_index] for row_index in range(len(matrix))]
            for column_index in range(len(x_axis["values"]))
        ]
        result["column_boundary_analysis"] = [
            {
                "x_value": x_value,
                **_transitions(column, y_axis["field"]),
            }
            for x_value, column in zip(x_axis["values"], columns)
        ]
        all_monotonic = [
            entry["monotonicity"] for entry in result["row_boundary_analysis"] + result["column_boundary_analysis"]
        ]
        result["surface_monotonicity"] = "non_monotonic" if "non_monotonic" in all_monotonic else "monotonic_or_no_transition"

    if realized_outcome is not None and outcome_horizon:
        outcome = (realized_outcome.get("outcomes") or {}).get(outcome_horizon)
        result["realized_outcome_overlay"] = {
            "available": outcome is not None,
            "horizon": outcome_horizon,
            "realized_signed_return": float(outcome.get("signed_return")) if outcome else None,
            "return_basis": "original_decision_reference_price",
            "interpretation": "Each ALLOW/BLOCK cell is interpreted against the same realized historical market move; blocked cells are counterfactual avoidance/opportunity observations, not realized P&L.",
        }
    return result
