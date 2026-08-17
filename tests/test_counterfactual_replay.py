"""Focused correctness/safety coverage for research-only counterfactual replay."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.compute.counterfactual_replay import CounterfactualUnavailable, counterfactual_decision
from backend.compute.decision_replay import decision_hash
from backend.compute.execution_decision import combine_execution_decision, evaluate_data_guardrails, evaluate_execution_agent
from backend.core.operator_auth import is_operator_mutation


def _record(*, spread_bps: float = 10.0, final_override: dict | None = None) -> dict:
    ts = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    data = {
        "execution_mode": "paper",
        "live_execution_enabled": False,
        "validation_reasons": [],
        "price_found": True,
        "fill_price": 150.0,
        "order_notional": 150.0,
        "max_order_notional": 100000.0,
        "price_fresh": True,
        "integrity_status": "OK",
        "price_integrity_block_live": True,
        "order": {"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 1.0, "price": 150.0},
    }
    agent = {
        "proposed": {"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 1.0, "price": 150.0},
        "market_state": {"spread_bps": spread_bps, "liquidity_depth": 100.0, "price_integrity": "OK"},
        "max_slippage_bps": 50.0,
        "min_liquidity_depth": 50.0,
    }
    data_result = evaluate_data_guardrails(data)
    agent_result = evaluate_execution_agent(agent, as_of=ts)
    final = combine_execution_decision(
        data_result=data_result,
        risk_result={"status": "not_used"},
        agent_result=agent_result,
        execution_mode="paper",
        executor_available=True,
        as_of=ts,
    )
    row = {
        "id": "00000000-0000-4000-8000-000000000024",
        "decision_ts": ts,
        "decision_type": "execution_pre_trade_final",
        "venue": "paper",
        "market": "SOL-PERP",
        "symbol": "SOL-PERP",
        "input_state": {
            "replay_inputs": {
                "heuristic": {"status": "not_used"},
                "ml": {"status": "not_used"},
                "allocation": {"status": "not_used"},
                "risk": {"status": "not_used"},
                "execution_boundary": {
                    "execution_mode": "paper",
                    "executor_available": True,
                    "agent": agent,
                    "data": data,
                },
            }
        },
        "input_provenance": {"provenance_status": "partial"},
        "derived_state": {},
        "heuristic_result": {"status": "not_used"},
        "ml_result": {"status": "not_used"},
        "risk_result": {"status": "not_used"},
        "allocation_result": {"status": "not_used"},
        "execution_intent": {},
        "component_versions": {"execution_decision": "v1"},
        "config_snapshot": {},
        "final_decision": final_override or final,
    }
    row["decision_hash"] = decision_hash(row)
    return row


def test_counterfactual_requires_exact_baseline():
    row = _record(final_override={"decision": "block", "action": "do_not_submit", "allowed": False})
    with pytest.raises(CounterfactualUnavailable, match="baseline decision must replay exactly"):
        counterfactual_decision(row, {"spread_bps": 80.0})


def test_counterfactual_is_deterministic_and_does_not_mutate_original():
    row = _record()
    original = copy.deepcopy(row)
    first = counterfactual_decision(row, {"spread_bps": 80.0})
    second = counterfactual_decision(row, {"spread_bps": 80.0})

    assert row == original
    assert first["counterfactual"] == second["counterfactual"]
    assert first["persisted"] is False
    assert first["orders_submitted"] == 0
    assert first["audit_only"] is True


def test_counterfactual_can_change_allow_to_block_through_existing_agent():
    result = counterfactual_decision(_record(), {"spread_bps": 80.0})
    assert result["original"]["final_decision"]["decision"] == "allow"
    assert result["counterfactual"]["final_decision"]["decision"] == "block"
    assert result["counterfactual"]["final_decision"]["stage"] == "execution_agent"
    assert result["effects"]["final_decision_changed"] is True
    assert "execution_agent" in result["applied_changes"]["spread_bps"]["components"]


def test_not_used_macro_components_are_not_activated():
    result = counterfactual_decision(_record(), {"shock_score": 3.0, "spread_bps": 80.0})
    assert "shock_score" in result["not_applicable"]
    assert result["counterfactual"]["heuristic_result"] == {"status": "not_used"}
    assert result["counterfactual"]["ml_result"] == {"status": "not_used"}
    assert result["counterfactual"]["allocation_result"] == {"status": "not_used"}


def test_scenario_rejects_unknown_and_non_finite_values():
    with pytest.raises(CounterfactualUnavailable, match="unsupported counterfactual field"):
        counterfactual_decision(_record(), {"model_version": "v2"})
    with pytest.raises(CounterfactualUnavailable, match="must be finite"):
        counterfactual_decision(_record(), {"spread_bps": float("nan")})


def test_counterfactual_endpoint_is_not_classified_as_operator_mutation():
    assert is_operator_mutation("POST", "/api/decisions/00000000-0000-4000-8000-000000000024/counterfactual") is False


def test_counterfactual_module_has_no_execution_or_persistence_boundary_imports():
    source = Path("backend/compute/counterfactual_replay.py").read_text()
    forbidden = (
        "backend.execution",
        "ExecutionRouter",
        "DecisionRepository",
        "OrdersRepository",
        "StateStore",
        "redis",
        ".create(",
        ".save(",
        "place_order(",
        "route_order(",
    )
    for token in forbidden:
        assert token not in source


def test_frontend_and_api_are_wired_research_only():
    routes = Path("backend/api/decision_routes.py").read_text()
    client = Path("frontend/assets/counterfactual_replay.js").read_text()
    main = Path("main.py").read_text()
    assert '@router.post("/{decision_id}/counterfactual")' in routes
    assert "/counterfactual" in client
    assert "COUNTERFACTUAL RESEARCH ONLY" in client
    assert "orders_submitted" in client
    assert "counterfactual_replay.js" in main
