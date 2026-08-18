"""Focused correctness/safety coverage for counterfactual sensitivity maps."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest

import backend.compute.counterfactual_sensitivity as sensitivity_module
from backend.compute.counterfactual_replay import counterfactual_decision
from backend.compute.counterfactual_sensitivity import (
    MAX_SENSITIVITY_CELLS,
    SensitivityUnavailable,
    counterfactual_sensitivity,
)
from backend.compute.decision_replay import decision_hash
from backend.compute.execution_decision import combine_execution_decision, evaluate_data_guardrails, evaluate_execution_agent
from backend.core.operator_auth import is_operator_mutation


def _record(*, spread_bps: float = 10.0, liquidity_depth: float = 100.0, final_override: dict | None = None) -> dict:
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
        "market_state": {"spread_bps": spread_bps, "liquidity_depth": liquidity_depth, "price_integrity": "OK"},
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
        "id": "00000000-0000-4000-8000-000000000028",
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


def test_single_counterfactual_remains_backward_compatible_after_prepared_refactor():
    result = counterfactual_decision(_record(), {"spread_bps": 80.0})
    assert result["status"] == "COMPUTED"
    assert result["counterfactual"]["final_decision"]["decision"] == "block"
    assert result["persisted"] is False
    assert result["orders_submitted"] == 0


def test_spread_sweep_reports_observed_transition_bracket():
    result = counterfactual_sensitivity(
        _record(),
        x={"field": "spread_bps", "values": [10, 20, 30, 40, 50, 60, 70, 80]},
    )
    assert [point["decision"] for point in result["points"]] == ["allow", "allow", "allow", "allow", "allow", "block", "block", "block"]
    boundary = result["boundary_analysis"]
    assert boundary["monotonicity"] == "monotonic_allow_to_block"
    assert boundary["transition_count"] == 1
    assert boundary["transitions"][0]["boundary_bracket"] == [50.0, 60.0]
    assert boundary["transitions"][0]["from_decision"] == "allow"
    assert boundary["transitions"][0]["to_decision"] == "block"


def test_liquidity_sweep_truthfully_detects_non_monotonic_current_rule():
    result = counterfactual_sensitivity(
        _record(),
        x={"field": "liquidity_depth", "values": [0, 25, 50, 75]},
    )
    assert [point["decision"] for point in result["points"]] == ["allow", "block", "allow", "allow"]
    boundary = result["boundary_analysis"]
    assert boundary["monotonicity"] == "non_monotonic"
    assert boundary["transition_count"] == 2
    assert boundary["transitions"][0]["boundary_bracket"] == [0.0, 25.0]
    assert boundary["transitions"][1]["boundary_bracket"] == [25.0, 50.0]


def test_two_dimensional_spread_liquidity_matrix_contains_real_replay_cells():
    result = counterfactual_sensitivity(
        _record(),
        x={"field": "spread_bps", "values": [40, 60]},
        y={"field": "liquidity_depth", "values": [25, 100]},
    )
    assert result["dimensions"] == 2
    assert result["cell_count"] == 4
    assert [[cell["decision"] for cell in row] for row in result["matrix"]] == [
        ["block", "block"],
        ["allow", "block"],
    ]
    assert result["matrix"][0][0]["stage"] == "execution_agent"
    assert result["matrix"][1][0]["stage"] == "pre_trade_complete"
    assert result["row_boundary_analysis"][1]["transitions"][0]["boundary_bracket"] == [40.0, 60.0]


def test_sensitivity_reuses_exact_baseline_once(monkeypatch):
    calls = {"count": 0}
    original = sensitivity_module.prepare_counterfactual

    def counted(record, **kwargs):
        calls["count"] += 1
        return original(record, **kwargs)

    monkeypatch.setattr(sensitivity_module, "prepare_counterfactual", counted)
    result = sensitivity_module.counterfactual_sensitivity(
        _record(),
        x={"field": "spread_bps", "values": [10, 20, 30, 40]},
        y={"field": "liquidity_depth", "values": [25, 100]},
    )
    assert result["cell_count"] == 8
    assert calls["count"] == 1


def test_original_decision_is_not_mutated_and_repeated_requests_are_deterministic():
    row = _record()
    original = copy.deepcopy(row)
    first = counterfactual_sensitivity(row, x={"field": "spread_bps", "values": [40, 60]})
    second = counterfactual_sensitivity(row, x={"field": "spread_bps", "values": [40, 60]})
    assert row == original
    assert first == second


def test_sensitivity_requires_exact_baseline():
    row = _record(final_override={"decision": "block", "action": "do_not_submit", "allowed": False})
    with pytest.raises(SensitivityUnavailable, match="baseline decision must replay exactly"):
        counterfactual_sensitivity(row, x={"field": "spread_bps", "values": [40, 60]})


def test_numeric_field_validation_and_cell_bounds():
    with pytest.raises(SensitivityUnavailable, match="unsupported numeric sensitivity field"):
        counterfactual_sensitivity(_record(), x={"field": "integrity_status", "values": [1, 2]})
    with pytest.raises(SensitivityUnavailable, match="must be finite"):
        counterfactual_sensitivity(_record(), x={"field": "spread_bps", "values": [10, float("nan")]})
    with pytest.raises(SensitivityUnavailable, match="maximum 100 cells"):
        counterfactual_sensitivity(
            _record(),
            x={"field": "spread_bps", "values": list(range(11))},
            y={"field": "liquidity_depth", "values": list(range(10, 110, 10))},
        )
    assert MAX_SENSITIVITY_CELLS == 100


def test_same_field_cannot_be_both_axes_or_fixed():
    with pytest.raises(SensitivityUnavailable, match="must be different"):
        counterfactual_sensitivity(
            _record(),
            x={"field": "spread_bps", "values": [10, 20]},
            y={"field": "spread_bps", "values": [30, 40]},
        )
    with pytest.raises(SensitivityUnavailable, match="fixed_scenario cannot also set swept field"):
        counterfactual_sensitivity(
            _record(),
            x={"field": "spread_bps", "values": [10, 20]},
            fixed_scenario={"spread_bps": 30},
        )


def test_not_used_components_are_not_activated_by_sensitivity():
    with pytest.raises(SensitivityUnavailable, match="none of the requested scenario fields apply"):
        counterfactual_sensitivity(
            _record(),
            x={"field": "shock_score", "values": [1, 2, 3]},
        )


def test_realized_outcome_overlay_uses_same_historical_move_for_all_cells():
    realized = {
        "outcomes": {
            "4h": {
                "signed_return": -0.052,
                "classification": "adverse_move_after_allow",
            }
        }
    }
    result = counterfactual_sensitivity(
        _record(),
        x={"field": "spread_bps", "values": [40, 60]},
        realized_outcome=realized,
        outcome_horizon="4h",
    )
    assert result["realized_outcome_overlay"]["realized_signed_return"] == -0.052
    assert result["points"][0]["realized_outcome"]["interpretation"] == "requested_side_adverse"
    assert result["points"][1]["realized_outcome"]["interpretation"] == "avoided_adverse_move"
    assert result["persisted"] is False
    assert result["orders_submitted"] == 0
    assert result["research_only"] is True


def test_fill_price_sensitivity_warns_about_original_reference_basis():
    result = counterfactual_sensitivity(
        _record(),
        x={"field": "fill_price", "values": [140, 150, 160]},
        realized_outcome={"outcomes": {"4h": {"signed_return": 0.02, "classification": "favorable_move_after_allow"}}},
        outcome_horizon="4h",
    )
    assert any("original decision reference price" in warning for warning in result["warnings"])


def test_sensitivity_endpoint_is_not_operator_mutation():
    path = "/api/decisions/00000000-0000-4000-8000-000000000028/sensitivity"
    assert is_operator_mutation("POST", path) is False


def test_sensitivity_module_has_no_execution_persistence_or_state_boundary_imports():
    source = Path("backend/compute/counterfactual_sensitivity.py").read_text()
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
        "promote",
        "retrain",
    )
    for token in forbidden:
        assert token not in source


def test_api_frontend_and_main_are_wired_research_only():
    routes = Path("backend/api/decision_routes.py").read_text()
    client = Path("frontend/assets/counterfactual_sensitivity.js").read_text()
    main = Path("main.py").read_text()
    assert '@router.post("/{decision_id}/sensitivity")' in routes
    assert "counterfactual_sensitivity(" in routes
    assert "/sensitivity" in client
    assert "SENSITIVITY RESEARCH ONLY" in client
    assert "Maximum 100 cells" in client
    assert "counterfactual_sensitivity.js" in main
