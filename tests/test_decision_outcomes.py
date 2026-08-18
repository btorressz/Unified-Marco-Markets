from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.compute.decision_outcomes import (
    HORIZONS,
    evaluate_decision_outcomes,
    linked_admission_decision_id,
    performance_summary,
    realized_counterfactual_comparison,
    symbol_candidates,
)


BASE_TS = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _record(*, allowed=True, side="buy", price=100.0, decision_id="final-1", admission_id="admission-1"):
    return {
        "id": decision_id,
        "decision_ts": BASE_TS.isoformat(),
        "decision_type": "execution_pre_trade_final",
        "venue": "paper",
        "market": "SOL-PERP",
        "symbol": "SOL-PERP",
        "input_provenance": {"admission_decision_id": admission_id},
        "input_state": {
            "replay_inputs": {
                "heuristic": {"status": "not_used"},
                "ml": {"status": "not_used"},
                "allocation": {"status": "not_used"},
                "execution_boundary": {
                    "data": {
                        "fill_price": price,
                        "order": {
                            "venue": "paper",
                            "market": "SOL-PERP",
                            "side": side,
                            "size": 2.0,
                            "price": price,
                        },
                    }
                },
            }
        },
        "execution_intent": {"order": {"side": side, "size": 2.0, "price": price}},
        "heuristic_result": {"status": "not_used"},
        "ml_result": {"status": "not_used"},
        "allocation_result": {"status": "not_used"},
        "component_versions": {"execution_decision": "v1"},
        "final_decision": {
            "decision": "allow" if allowed else "block",
            "allowed": allowed,
            "action": "submit_order" if allowed else "do_not_submit",
        },
    }


def _observations(prices):
    rows = []
    for horizon, price in prices.items():
        target = BASE_TS + timedelta(seconds=HORIZONS[horizon])
        rows.append({
            "id": f"{horizon}-1",
            "horizon": horizon,
            "target_ts": target.isoformat(),
            "ts": (target + timedelta(minutes=5)).isoformat(),
            "lag_seconds": 300,
            "symbol": "SOL-PERP",
            "venue": "drift",
            "price": price,
        })
    return {"available": True, "observations": rows}


def _lifecycle():
    return {
        "available": True,
        "intents": [{"id": "intent-1", "decision_id": "admission-1"}],
        "orders": [{"id": "order-1", "status": "filled"}],
        "fills": [
            {"id": "fill-1", "size": 1.0, "price": 100.0, "fee": 0.1, "funding": 0.0, "slippage": 0.02},
            {"id": "fill-2", "size": 1.0, "price": 102.0, "fee": 0.1, "funding": 0.0, "slippage": 0.03},
        ],
    }


def test_final_decision_links_back_to_admission_for_execution_lifecycle():
    assert linked_admission_decision_id(_record()) == "admission-1"


def test_symbol_candidates_cover_existing_sol_ingestion_formats():
    candidates = symbol_candidates(_record())
    for expected in ("SOL-PERP", "SOL/USD", "SOLUSD", "SOL_USD", "SOLANA/USD"):
        assert expected in candidates


def test_allow_buy_reports_favorable_and_adverse_market_moves_without_claiming_pnl():
    result = evaluate_decision_outcomes(
        _record(allowed=True, side="buy", price=100),
        _observations({"1h": 102, "4h": 95}),
        _lifecycle(),
    )
    assert result["outcome_status"] == "available"
    assert result["outcomes"]["1h"]["signed_return"] == pytest.approx(0.02)
    assert result["outcomes"]["1h"]["classification"] == "favorable_move_after_allow"
    assert result["outcomes"]["4h"]["signed_return"] == pytest.approx(-0.05)
    assert result["outcomes"]["4h"]["classification"] == "adverse_move_after_allow"
    assert result["outcomes"]["1h"]["pnl_status"] == "market_move_not_realized_pnl"
    assert result["actual_execution"]["filled"] is True
    assert result["actual_execution"]["average_fill_price"] == pytest.approx(101.0)


def test_sell_reverses_signed_return_direction():
    result = evaluate_decision_outcomes(
        _record(allowed=True, side="sell", price=100),
        _observations({"4h": 95}),
    )
    assert result["outcomes"]["4h"]["raw_return"] == pytest.approx(-0.05)
    assert result["outcomes"]["4h"]["signed_return"] == pytest.approx(0.05)
    assert result["outcomes"]["4h"]["classification"] == "favorable_move_after_allow"


def test_block_distinguishes_avoided_adverse_move_from_missed_upside():
    avoided = evaluate_decision_outcomes(
        _record(allowed=False, side="buy", price=100),
        _observations({"4h": 90}),
    )
    missed = evaluate_decision_outcomes(
        _record(allowed=False, side="buy", price=100),
        _observations({"4h": 110}),
    )
    assert avoided["outcomes"]["4h"]["classification"] == "avoided_adverse_move_after_block"
    assert missed["outcomes"]["4h"]["classification"] == "missed_favorable_move_after_block"
    assert avoided["outcomes"]["4h"]["pnl_status"] == "counterfactual_market_move_only"


def test_missing_reference_price_is_truthfully_unavailable():
    record = _record(price=100)
    record["input_state"]["replay_inputs"]["execution_boundary"]["data"]["fill_price"] = 0
    record["input_state"]["replay_inputs"]["execution_boundary"]["data"]["order"]["price"] = None
    record["execution_intent"]["order"]["price"] = None
    result = evaluate_decision_outcomes(record, _observations({"4h": 110}))
    assert result["outcome_status"] == "unavailable"
    assert "reference price" in result["reason"]


def test_performance_summary_reports_allow_block_and_block_quality_rates():
    allow = evaluate_decision_outcomes(_record(allowed=True, decision_id="a"), _observations({"4h": 105}))
    block_good = evaluate_decision_outcomes(_record(allowed=False, decision_id="b"), _observations({"4h": 90}))
    block_cost = evaluate_decision_outcomes(_record(allowed=False, decision_id="c"), _observations({"4h": 110}))
    pairs = [
        (_record(allowed=True, decision_id="a"), allow),
        (_record(allowed=False, decision_id="b"), block_good),
        (_record(allowed=False, decision_id="c"), block_cost),
    ]
    summary = performance_summary(pairs, primary_horizon="4h")
    metric = summary["horizons"]["4h"]
    assert metric["evaluated_count"] == 3
    assert metric["allow_count"] == 1
    assert metric["block_count"] == 2
    assert metric["block_avoided_adverse_move_rate"] == pytest.approx(0.5)
    assert metric["block_opportunity_cost_rate"] == pytest.approx(0.5)
    assert "SOL-PERP" in summary["performance_by_market"]
    assert "paper" in summary["performance_by_venue"]


def test_counterfactual_realized_comparison_uses_market_move_without_fake_pnl():
    outcomes = evaluate_decision_outcomes(
        _record(allowed=True, side="buy", price=100),
        _observations({"4h": 95}),
    )
    counterfactual = {
        "scenario": {"spread_bps": 90},
        "effects": {
            "original_final": {"allowed": True, "decision": "allow"},
            "counterfactual_final": {"allowed": False, "decision": "block"},
        },
    }
    result = realized_counterfactual_comparison(outcomes, counterfactual, horizon="4h")
    assert result["available"] is True
    assert result["original"]["interpretation"] == "requested_side_adverse"
    assert result["counterfactual"]["interpretation"] == "avoided_adverse_move"
    assert result["research_only"] is True


def test_outcome_repository_is_select_only_and_feature_wiring_is_research_only():
    repo_source = Path("backend/data/repositories/decision_outcome_repo.py").read_text()
    compute_source = Path("backend/compute/decision_outcomes.py").read_text()
    api_source = Path("backend/api/decision_routes.py").read_text()
    frontend = Path("frontend/assets/decision_outcomes.js").read_text()
    counterfactual_frontend = Path("frontend/assets/counterfactual_replay.js").read_text()
    main_source = Path("main.py").read_text()

    lowered = repo_source.lower()
    for forbidden in ("insert into", "update ", "delete from", "execute_write", "execute_returning"):
        assert forbidden not in lowered
    for forbidden in (
        "from backend.execution",
        "import backend.execution",
        "from backend.core.state_store",
        "route_order(",
        "place_order(",
    ):
        assert forbidden not in compute_source

    assert '@router.get("/{decision_id}/outcomes")' in api_source
    assert '@router.get("/performance")' in api_source
    assert 'realized_counterfactual_comparison' in api_source
    assert 'include_lifecycle=False' in api_source
    assert 'Decision Performance Lab' in frontend
    assert 'BLOCK Opportunity Cost' in frontend
    assert 'Realized Market Context' in counterfactual_frontend
    assert 'decision_outcomes.js' in main_source
