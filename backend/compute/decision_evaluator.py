"""Pure component evaluators used only for deterministic audit replay."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable


class ReplayUnavailable(ValueError):
    pass


def _as_of(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception as exc:
        raise ReplayUnavailable("decision timestamp is unavailable") from exc


def evaluate_heuristic(spec: dict[str, Any], decision_ts: Any) -> dict[str, Any]:
    if spec.get("status") == "not_used": return {"status": "not_used"}
    context = spec.get("context")
    heuristic_id = spec.get("heuristic_id") or spec.get("id")
    version = spec.get("heuristic_version", spec.get("version"))
    if not isinstance(context, dict) or not heuristic_id or version is None:
        raise ReplayUnavailable("heuristic replay inputs are incomplete")
    from backend.compute.rules_engine import RulesEngine
    return RulesEngine().evaluate_version(str(heuristic_id), int(str(version).lstrip("v")), context, as_of=_as_of(decision_ts))


def evaluate_ml(spec: dict[str, Any], model_loader: Callable[[str], Any] | None = None) -> dict[str, Any]:
    if spec.get("status") == "not_used": return {"status": "not_used"}
    if spec.get("fallback_used"):
        fallback = spec.get("fallback_inputs")
        if not isinstance(fallback, dict) or "probability" not in fallback:
            raise ReplayUnavailable("deterministic ML fallback inputs are incomplete")
        return {**fallback, "fallback_used": True, "fallback_reason": spec.get("fallback_reason")}
    required = ("model_id", "model_version", "artifact_sha256", "feature_vector", "feature_schema")
    if any(spec.get(key) is None for key in required):
        raise ReplayUnavailable("ML replay inputs are incomplete")
    if model_loader is None:
        from backend.data.repositories.ml_repo import MLRepository
        model_loader = MLRepository().get_model
    model = model_loader(str(spec["model_id"]))
    if not model or str(model.get("model_version")) != str(spec["model_version"]):
        raise ReplayUnavailable("exact ML model/version is unavailable")
    if str(model.get("artifact_sha256")) != str(spec["artifact_sha256"]):
        raise ReplayUnavailable("required ML artifact SHA-256 does not match")
    from backend.ml.governance import deserialize_artifact
    artifact = deserialize_artifact(model.get("artifact_blob"), spec["artifact_sha256"])
    pipeline = artifact.get("pipeline") if isinstance(artifact, dict) else artifact
    vector = list(spec["feature_vector"])
    probability = float(pipeline.predict_proba([vector])[0][1])
    return {"model_id": str(model["id"]), "model_version": str(model["model_version"]),
            "artifact_sha256": str(model["artifact_sha256"]), "probability": probability,
            "predicted_class": int(probability >= 0.5), "feature_schema": spec["feature_schema"]}


class _InertRuntime:
    def available(self): return False


def evaluate_risk(spec: dict[str, Any], decision_ts: Any) -> dict[str, Any]:
    if spec.get("status") == "not_used": return {"status": "not_used"}
    required = ("positions", "portfolio_snapshot", "proposed_action", "limits", "runtime_state", "execution_mode")
    if any(spec.get(key) is None for key in required): raise ReplayUnavailable("risk replay inputs are incomplete")
    from backend.compute.risk_engine import RiskEngine
    limits, state = spec["limits"], spec["runtime_state"]
    engine = RiskEngine(max_leverage=limits["max_leverage"], max_margin_pct=limits["max_margin_pct"],
                        max_daily_loss=limits["max_daily_loss"], cooldown_seconds=limits["cooldown_seconds"],
                        runtime_state=_InertRuntime())
    engine.throttle_active = bool(state.get("throttle_active", False)); engine.throttle_reason = str(state.get("throttle_reason", ""))
    engine.daily_pnl = float(state.get("daily_pnl", 0)); engine.daily_pnl_reset_date = str(state.get("daily_pnl_reset_date") or _as_of(decision_ts).date())
    engine.last_action_ts = float(state.get("last_action_ts", 0))
    allowed, reasons = engine.check_constraints(spec["positions"], spec["proposed_action"], spec["execution_mode"],
                                                 spec["portfolio_snapshot"], as_of=_as_of(decision_ts))
    return {"approved": allowed, "reasons": reasons, "metrics": engine.last_metrics}


def evaluate_allocation(spec: dict[str, Any], decision_ts: Any = None) -> dict[str, Any]:
    if spec.get("status") == "not_used": return {"status": "not_used"}
    state = spec.get("state")
    if not isinstance(state, dict): raise ReplayUnavailable("allocation replay inputs are incomplete")
    from backend.compute.capital_allocator import allocate
    return allocate(state, as_of=_as_of(decision_ts))


def evaluate_execution_boundary(inputs: dict[str, Any], components: dict[str, Any], decision_ts: Any) -> dict[str, Any]:
    boundary = inputs.get("execution_boundary")
    if not isinstance(boundary, dict):
        raise ReplayUnavailable("final execution-boundary inputs are incomplete")
    try:
        from backend.compute.execution_decision import (
            combine_execution_decision,
            evaluate_data_guardrails,
            evaluate_execution_agent,
        )
        data_result = evaluate_data_guardrails(boundary.get("data") or {})
        agent_result = evaluate_execution_agent(boundary.get("agent") or {"status": "not_used"}, as_of=decision_ts)
        return combine_execution_decision(
            data_result=data_result,
            risk_result=components["risk_result"],
            agent_result=agent_result,
            execution_mode=str(boundary.get("execution_mode") or "paper"),
            executor_available=bool(boundary.get("executor_available", True)),
            as_of=decision_ts,
        )
    except ReplayUnavailable:
        raise
    except Exception as exc:
        raise ReplayUnavailable(str(exc)) from exc


def recompute_decision(record: dict[str, Any], *, model_loader=None) -> dict[str, Any]:
    inputs = (record.get("input_state") or {}).get("replay_inputs")
    if not isinstance(inputs, dict): raise ReplayUnavailable("explicit replay inputs are unavailable")
    ts = record.get("decision_ts")
    components = {"heuristic_result": evaluate_heuristic(inputs.get("heuristic") or {}, ts),
                  "ml_result": evaluate_ml(inputs.get("ml") or {}, model_loader),
                  "risk_result": evaluate_risk(inputs.get("risk") or {}, ts),
                  "allocation_result": evaluate_allocation(inputs.get("allocation") or {}, ts)}
    components["final_decision"] = evaluate_execution_boundary(inputs, components, ts)
    return {**record, **components}
