"""Pure final-decision helpers shared by runtime execution and audit replay.

This module never submits orders, reads Redis, or touches persistence. It only
turns explicitly supplied pre-trade facts/component outputs into a deterministic
ALLOW/BLOCK decision.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def as_utc(value: Any | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def canonical_timestamp(value: Any) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def evaluate_data_guardrails(spec: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate deterministic execution/data admission facts from a stored spec."""
    mode = str(spec.get("execution_mode") or "paper")
    reasons = [str(x) for x in (spec.get("validation_reasons") or [])]
    stage = "request_validation" if reasons else None

    if not reasons and mode == "live" and not bool(spec.get("live_execution_enabled", False)):
        reasons = ["Live execution is disabled"]
        stage = "live_execution_gate"

    fill_price = float(spec.get("fill_price") or 0.0)
    if not reasons and not bool(spec.get("price_found", False)) and fill_price <= 0:
        reasons = ["No price data available"]
        stage = "price_availability"

    order_notional = abs(float(spec.get("order_notional") or 0.0))
    max_notional = float(spec.get("max_order_notional") or 0.0)
    if not reasons and max_notional > 0 and order_notional > max_notional:
        reasons = [f"max_notional_exceeded: {order_notional:.2f} > {max_notional:.2f}"]
        stage = "max_notional"

    if not reasons and mode == "live" and bool(spec.get("price_found", False)) and not bool(spec.get("price_fresh", True)):
        reasons = ["Price data stale"]
        stage = "price_freshness"

    integrity = str(spec.get("integrity_status") or "UNKNOWN").upper()
    if (
        not reasons
        and mode == "live"
        and bool(spec.get("price_integrity_block_live", False))
        and integrity != "OK"
    ):
        reason = (
            "Price integrity WARNING — cross-venue deviation too high"
            if integrity == "WARNING"
            else f"Price integrity {integrity} — live execution requires OK"
        )
        reasons = [reason]
        stage = "price_integrity"

    return {
        "allowed": not reasons,
        "stage": stage or "data_guardrails",
        "reasons": reasons,
        "execution_mode": mode,
        "fill_price": fill_price,
        "order_notional": order_notional,
        "integrity_status": integrity,
    }


def evaluate_execution_agent(spec: dict[str, Any], *, as_of: Any = None) -> dict[str, Any]:
    if spec.get("status") == "not_used":
        return {"status": "not_used", "allowed": True, "reasons": []}
    proposed = spec.get("proposed")
    market_state = spec.get("market_state")
    if not isinstance(proposed, dict) or not isinstance(market_state, dict):
        raise ValueError("execution-agent replay inputs are incomplete")

    from backend.agents.execution_agent import ExecutionAgent

    agent = ExecutionAgent(
        max_slippage_bps=float(spec.get("max_slippage_bps", 50.0)),
        min_liquidity_depth=float(spec.get("min_liquidity_depth", 50.0)),
    )
    result = agent.pre_trade_check(dict(proposed), dict(market_state))
    result["ts"] = canonical_timestamp(as_of)
    return result


def combine_execution_decision(
    *,
    data_result: dict[str, Any],
    risk_result: dict[str, Any],
    agent_result: dict[str, Any],
    execution_mode: str,
    executor_available: bool,
    as_of: Any,
) -> dict[str, Any]:
    """Return the final deterministic pre-trade ALLOW/BLOCK decision."""
    mode = str(execution_mode or "paper")

    if not bool(data_result.get("allowed", False)):
        stage = str(data_result.get("stage") or "data_guardrails")
        reasons = [str(x) for x in (data_result.get("reasons") or [])]
        allowed = False
    elif risk_result.get("status") != "not_used" and not bool(risk_result.get("approved", False)):
        stage = "risk"
        reasons = [str(x) for x in (risk_result.get("reasons") or risk_result.get("reasons_applied") or [])]
        allowed = False
    elif agent_result.get("status") != "not_used" and not bool(agent_result.get("allowed", False)):
        stage = "execution_agent"
        reasons = [str(x) for x in (agent_result.get("reasons") or [])]
        allowed = False
    elif mode == "live" and not bool(executor_available):
        stage = "executor_availability"
        reasons = ["No production-ready live executor available"]
        allowed = False
    else:
        stage = "pre_trade_complete"
        reasons = []
        allowed = True

    return {
        "decision": "allow" if allowed else "block",
        "action": "submit_order" if allowed else "do_not_submit",
        "allowed": allowed,
        "stage": stage,
        "reasons": reasons,
        "execution_mode": mode,
        "ts": canonical_timestamp(as_of),
    }
