"""Research-only counterfactual replay over immutable decision audit inputs.

Counterfactual replay never persists, routes orders, reads current Redis state, or
changes component identities. It verifies the original decision can replay exactly,
then applies a small allowlisted set of semantic scenario overrides to a deep copy
of the stored replay inputs and invokes the existing deterministic replay evaluators.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Callable

from backend.compute.decision_evaluator import ReplayUnavailable, recompute_decision
from backend.compute.decision_replay import canonical_decision_state, replay_decision, structured_diff
from backend.ml.feature_store import FEATURE_NAMES, build_features


class CounterfactualUnavailable(ValueError):
    pass


_ALLOWED_FIELDS = {
    "shock_score",
    "vol_regime",
    "stable_health",
    "predictor_confidence",
    "tariff_index",
    "tariff_delta",
    "tariff_rate_of_change",
    "funding_skew",
    "basis_spread",
    "divergence_score",
    "orderbook_imbalance",
    "liquidity_score",
    "slippage_score",
    "exec_quality",
    "funding_arb_score",
    "basis_opportunity",
    "tariff_shock",
    "fill_price",
    "order_size",
    "spread_bps",
    "liquidity_depth",
    "integrity_status",
    "price_fresh",
    "price_found",
    "daily_pnl",
    "throttle_active",
}

_NUMERIC_FIELDS = _ALLOWED_FIELDS - {
    "vol_regime", "integrity_status", "price_fresh", "price_found", "throttle_active"
}
_VOL_REGIMES = {"low", "normal", "high", "extreme", "low_volatility", "normal_volatility", "high_volatility", "shock_regime", "liquidity_crunch"}
_INTEGRITY = {"OK", "WARNING", "ERROR", "UNKNOWN"}


def counterfactual_numeric_fields() -> tuple[str, ...]:
    """Public ordered numeric allowlist for bounded sensitivity research."""
    return tuple(sorted(_NUMERIC_FIELDS))


def _active(spec: Any) -> bool:
    return isinstance(spec, dict) and spec.get("status") != "not_used"


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CounterfactualUnavailable(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise CounterfactualUnavailable(f"{field} must be finite")
    return number


def _validate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(scenario, dict) or not scenario:
        raise CounterfactualUnavailable("scenario must be a non-empty object")
    unknown = sorted(set(scenario) - _ALLOWED_FIELDS)
    if unknown:
        raise CounterfactualUnavailable(f"unsupported counterfactual field(s): {', '.join(unknown)}")

    clean: dict[str, Any] = {}
    for field, value in scenario.items():
        if field in _NUMERIC_FIELDS:
            clean[field] = _finite(value, field)
        elif field == "vol_regime":
            regime = str(value).lower().strip()
            if regime not in _VOL_REGIMES:
                raise CounterfactualUnavailable(f"unsupported vol_regime: {value}")
            clean[field] = regime
        elif field == "integrity_status":
            integrity = str(value).upper().strip()
            if integrity not in _INTEGRITY:
                raise CounterfactualUnavailable(f"unsupported integrity_status: {value}")
            clean[field] = integrity
        else:
            if not isinstance(value, bool):
                raise CounterfactualUnavailable(f"{field} must be boolean")
            clean[field] = value

    if "stable_health" in clean and not 0 <= clean["stable_health"] <= 1:
        raise CounterfactualUnavailable("stable_health must be between 0 and 1")
    if "predictor_confidence" in clean and not 0 <= clean["predictor_confidence"] <= 1:
        raise CounterfactualUnavailable("predictor_confidence must be between 0 and 1")
    if "order_size" in clean and clean["order_size"] <= 0:
        raise CounterfactualUnavailable("order_size must be greater than zero")
    if "fill_price" in clean and clean["fill_price"] <= 0:
        raise CounterfactualUnavailable("fill_price must be greater than zero")
    if "spread_bps" in clean and clean["spread_bps"] < 0:
        raise CounterfactualUnavailable("spread_bps cannot be negative")
    if "liquidity_depth" in clean and clean["liquidity_depth"] < 0:
        raise CounterfactualUnavailable("liquidity_depth cannot be negative")
    return clean


def _record_change(
    applied: dict[str, Any],
    field: str,
    component: str,
    path: str,
    original: Any,
    value: Any,
    *,
    semantic_value: bool = True,
) -> None:
    entry = applied.setdefault(field, {"original": [], "counterfactual": value, "components": []})
    entry["original"].append({"path": path, "value": original, "semantic_value": semantic_value})
    if component not in entry["components"]:
        entry["components"].append(component)


def _set_context(spec: dict[str, Any], key: str, value: Any, field: str, applied: dict[str, Any]) -> bool:
    context = spec.get("context")
    if not _active(spec) or not isinstance(context, dict) or key not in context:
        return False
    original = context[key]
    context[key] = value
    _record_change(applied, field, "heuristic", f"heuristic.context.{key}", original, value)
    return True


def _set_allocation(spec: dict[str, Any], key: str, value: Any, field: str, applied: dict[str, Any]) -> bool:
    state = spec.get("state")
    if not _active(spec) or not isinstance(state, dict) or key not in state:
        return False
    original = state[key]
    state[key] = value
    _record_change(applied, field, "allocation", f"allocation.state.{key}", original, value)
    return True


def _set_ml_feature(spec: dict[str, Any], name: str, value: Any, field: str, applied: dict[str, Any]) -> bool:
    if not _active(spec) or spec.get("fallback_used") or not isinstance(spec.get("feature_vector"), list):
        return False
    try:
        index = FEATURE_NAMES.index(name)
    except ValueError:
        return False
    vector = spec["feature_vector"]
    if index >= len(vector):
        return False
    original = vector[index]
    vector[index] = float(value)
    _record_change(applied, field, "ml", f"ml.feature_vector[{index}]/{name}", original, float(value))
    return True


def _apply_macro(inputs: dict[str, Any], field: str, value: Any, applied: dict[str, Any]) -> None:
    heuristic = inputs.get("heuristic") or {}
    ml = inputs.get("ml") or {}
    allocation = inputs.get("allocation") or {}

    if field == "shock_score":
        _set_context(heuristic, "shock_score", value, field, applied)
        changed = _set_ml_feature(ml, "shock_score", value, field, applied)
        if changed:
            original_count = len((applied.get(field) or {}).get("original") or [])
            _set_ml_feature(ml, "shock_abs", abs(float(value)), field, applied)
            if len((applied.get(field) or {}).get("original") or []) > original_count:
                applied[field]["original"][-1]["semantic_value"] = False
    elif field == "vol_regime":
        _set_context(heuristic, "vol_regime", value, field, applied)
        encoded = build_features({"vol_regime": value})["features"]["vol_regime_encoded"]
        _set_ml_feature(ml, "vol_regime_encoded", encoded, field, applied)
        _set_allocation(allocation, "vol_regime", value, field, applied)
    elif field == "stable_health":
        _set_ml_feature(ml, "stable_health", value, field, applied)
        _set_allocation(allocation, "stable_health", value, field, applied)
    elif field == "predictor_confidence":
        _set_ml_feature(ml, "predictor_conf", value, field, applied)
        _set_allocation(allocation, "predictor_confidence", value, field, applied)
    elif field == "tariff_rate_of_change":
        _set_context(heuristic, "tariff_rate_of_change", value, field, applied)
    elif field in {"tariff_index", "tariff_delta", "funding_skew", "basis_spread", "divergence_score", "orderbook_imbalance", "liquidity_score", "slippage_score"}:
        _set_ml_feature(ml, field, value, field, applied)
    elif field == "exec_quality":
        _set_ml_feature(ml, "exec_quality", value, field, applied)
        _set_allocation(allocation, "exec_quality", value, field, applied)
    elif field in {"funding_arb_score", "basis_opportunity", "tariff_shock"}:
        _set_allocation(allocation, field, value, field, applied)


def _set_nested(spec: dict[str, Any], key: str, value: Any, field: str, component: str, path: str, applied: dict[str, Any]) -> bool:
    if not isinstance(spec, dict) or key not in spec:
        return False
    original = spec[key]
    spec[key] = value
    _record_change(applied, field, component, path, original, value)
    return True


def _apply_execution(inputs: dict[str, Any], field: str, value: Any, applied: dict[str, Any]) -> None:
    boundary = inputs.get("execution_boundary") or {}
    data = boundary.get("data") or {}
    agent = boundary.get("agent") or {}
    risk = inputs.get("risk") or {}

    if field in {"fill_price", "price_fresh", "price_found"}:
        _set_nested(data, field, value, field, "execution_boundary", f"execution_boundary.data.{field}", applied)
    elif field == "integrity_status":
        _set_nested(data, "integrity_status", value, field, "execution_boundary", "execution_boundary.data.integrity_status", applied)
        market_state = agent.get("market_state") if _active(agent) else None
        if isinstance(market_state, dict) and "price_integrity" in market_state:
            original = market_state["price_integrity"]
            market_state["price_integrity"] = value
            _record_change(applied, field, "execution_agent", "execution_boundary.agent.market_state.price_integrity", original, value)
        _set_allocation(inputs.get("allocation") or {}, "price_integrity", str(value).lower(), field, applied)
    elif field in {"spread_bps", "liquidity_depth"}:
        market_state = agent.get("market_state") if _active(agent) else None
        if isinstance(market_state, dict) and field in market_state:
            original = market_state[field]
            market_state[field] = value
            _record_change(applied, field, "execution_agent", f"execution_boundary.agent.market_state.{field}", original, value)
    elif field == "daily_pnl":
        state = risk.get("runtime_state") if _active(risk) else None
        if isinstance(state, dict) and "daily_pnl" in state:
            original = state["daily_pnl"]
            state["daily_pnl"] = value
            _record_change(applied, field, "risk", "risk.runtime_state.daily_pnl", original, value)
    elif field == "throttle_active":
        state = risk.get("runtime_state") if _active(risk) else None
        if isinstance(state, dict) and "throttle_active" in state:
            original = state["throttle_active"]
            state["throttle_active"] = value
            _record_change(applied, field, "risk", "risk.runtime_state.throttle_active", original, value)

    if field in {"fill_price", "order_size"}:
        order = data.get("order") if isinstance(data, dict) else None
        proposed = risk.get("proposed_action") if _active(risk) else None
        agent_proposed = agent.get("proposed") if _active(agent) else None
        if field == "fill_price":
            if isinstance(order, dict) and "price" in order:
                original = order["price"]
                order["price"] = value
                _record_change(applied, field, "execution_boundary", "execution_boundary.data.order.price", original, value)
            for component, spec, path in (("risk", proposed, "risk.proposed_action.price"), ("execution_agent", agent_proposed, "execution_boundary.agent.proposed.price")):
                if isinstance(spec, dict) and "price" in spec:
                    original = spec["price"]
                    spec["price"] = value
                    _record_change(applied, field, component, path, original, value)
        else:
            if isinstance(order, dict) and "size" in order:
                original = order["size"]
                order["size"] = value
                _record_change(applied, field, "execution_boundary", "execution_boundary.data.order.size", original, value)
            for component, spec, path in (("risk", proposed, "risk.proposed_action.size"), ("execution_agent", agent_proposed, "execution_boundary.agent.proposed.size")):
                if isinstance(spec, dict) and "size" in spec:
                    original = spec["size"]
                    spec["size"] = value
                    _record_change(applied, field, component, path, original, value)

        price = float(data.get("fill_price") or 0.0)
        size = None
        if isinstance(data.get("order"), dict):
            size = data["order"].get("size")
        if size is not None and price > 0 and "order_notional" in data:
            original = data["order_notional"]
            data["order_notional"] = abs(float(size) * price)
            _record_change(
                applied, field, "execution_boundary", "execution_boundary.data.order_notional",
                original, data["order_notional"], semantic_value=False,
            )


def _apply_scenario(record: dict[str, Any], scenario: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    mutated = copy.deepcopy(record)
    inputs = ((mutated.get("input_state") or {}).get("replay_inputs"))
    if not isinstance(inputs, dict):
        raise CounterfactualUnavailable("explicit replay inputs are unavailable")

    applied: dict[str, Any] = {}
    for field, value in scenario.items():
        _apply_macro(inputs, field, value, applied)
        _apply_execution(inputs, field, value, applied)

    not_applicable = sorted(field for field in scenario if field not in applied)
    if len(not_applicable) == len(scenario):
        raise CounterfactualUnavailable("none of the requested scenario fields apply to this decision")
    return mutated, applied, not_applicable


def prepare_counterfactual(
    record: dict[str, Any],
    *,
    model_loader: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Verify exact replay once and return reusable immutable baseline facts."""
    baseline = replay_decision(record, model_loader=model_loader)
    if not baseline.get("exact_match"):
        raise CounterfactualUnavailable(
            "baseline decision must replay exactly before counterfactual analysis"
            + (f": {baseline.get('reason')}" if baseline.get("reason") else "")
        )
    return {
        "record": record,
        "model_loader": model_loader,
        "baseline": baseline,
        "original": baseline["replayed_decision"],
    }


def recorded_counterfactual_baseline(record: dict[str, Any], field: str) -> dict[str, Any]:
    """Read a numeric field only through its immutable replay-application mapping.

    This deliberately applies a probe to a deep copy, so it cannot mutate the audit
    record or consult runtime state. Direct semantic locations are distinguished from
    dependent values such as ``shock_abs`` and calculated order notional.
    """
    if field not in _NUMERIC_FIELDS:
        raise CounterfactualUnavailable(f"unsupported numeric counterfactual field: {field}")
    try:
        _, applied, not_applicable = _apply_scenario(record, {field: 0.0})
    except CounterfactualUnavailable:
        return {"status": "not_applicable", "consistent": False, "values": []}
    if field in not_applicable or field not in applied:
        return {"status": "not_applicable", "consistent": False, "values": []}

    originals = [
        item for item in applied[field].get("original", [])
        if item.get("semantic_value", True)
    ]
    numeric: list[float] = []
    for item in originals:
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            return {
                "status": "unavailable", "consistent": False, "values": [],
                "reason": "recorded semantic value is not numeric",
            }
        if not math.isfinite(value):
            return {
                "status": "unavailable", "consistent": False, "values": [],
                "reason": "recorded semantic value is not finite",
            }
        if not any(math.isclose(value, known, rel_tol=1e-12, abs_tol=1e-12) for known in numeric):
            numeric.append(value)

    if not numeric:
        return {"status": "not_applicable", "consistent": False, "values": []}
    if len(numeric) != 1:
        return {"status": "inconsistent", "consistent": False, "values": sorted(numeric)}
    return {
        "status": "available",
        "value": numeric[0],
        "values": numeric,
        "consistent": True,
        "sources": [item["path"] for item in originals],
    }


def counterfactual_from_prepared(prepared: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Recompute one scenario from a previously exact-verified baseline."""
    clean = _validate_scenario(scenario)
    record = prepared.get("record")
    baseline = prepared.get("baseline") or {}
    if not isinstance(record, dict) or not baseline.get("exact_match"):
        raise CounterfactualUnavailable("prepared counterfactual baseline is invalid")

    mutated, applied, not_applicable = _apply_scenario(record, clean)
    try:
        counterfactual = recompute_decision(mutated, model_loader=prepared.get("model_loader"))
    except (ReplayUnavailable, ValueError, TypeError) as exc:
        raise CounterfactualUnavailable(str(exc)) from exc

    original = prepared.get("original") or baseline["replayed_decision"]
    counterfactual_state = canonical_decision_state(counterfactual)
    differences = structured_diff(original, counterfactual_state)
    original_final = original.get("final_decision") or {}
    counterfactual_final = counterfactual_state.get("final_decision") or {}

    return {
        "counterfactual_status": "computed",
        "status": "COMPUTED",
        "audit_only": True,
        "persisted": False,
        "orders_submitted": 0,
        "decision_id": str(record.get("id") or ""),
        "decision_ts": record.get("decision_ts"),
        "scenario": clean,
        "applied_changes": applied,
        "not_applicable": not_applicable,
        "baseline": {
            "status": baseline.get("status"),
            "exact_match": True,
            "hash": baseline.get("replay_hash"),
        },
        "original": original,
        "counterfactual": counterfactual_state,
        "differences": differences,
        "effects": {
            "final_decision_changed": original_final != counterfactual_final,
            "original_final": original_final,
            "counterfactual_final": counterfactual_final,
            "changed_fields": len(differences),
        },
    }


def counterfactual_decision(
    record: dict[str, Any],
    scenario: dict[str, Any],
    *,
    model_loader: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Backward-compatible single counterfactual replay."""
    prepared = prepare_counterfactual(record, model_loader=model_loader)
    return counterfactual_from_prepared(prepared, scenario)
