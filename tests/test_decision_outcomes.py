from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.compute.decision_outcomes import (
    HORIZONS,
    decision_regime_context,
    evaluate_decision_outcomes,
    linked_admission_decision_id,
    performance_summary,
    realized_counterfactual_comparison,
    symbol_candidates,
)


BASE_TS = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _record(*, allowed=True, side="buy", price=100.0, decision_id="final-1", admission_id="admission-1", decision_ts=None):
    return {
        "id": decision_id,
        "decision_ts": (decision_ts or BASE_TS).isoformat(),
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


def _context_history(*, regime=None, index=None, stables=None):
    return {
        "available": True,
        "regime_snapshots": list(regime or []),
        "index_history": list(index or []),
        "stablecoin_ticks": list(stables or []),
        "errors": {},
        "truncated": {},
    }


def _evaluated_pair(record, future_price):
    target = datetime.fromisoformat(str(record["decision_ts"]).replace("Z", "+00:00")) + timedelta(hours=4)
    observation = {
        "available": True,
        "observations": [{
            "id": f"obs-{record['id']}",
            "horizon": "4h",
            "target_ts": target.isoformat(),
            "ts": (target + timedelta(minutes=5)).isoformat(),
            "lag_seconds": 300,
            "symbol": "SOL-PERP",
            "venue": "drift",
            "price": future_price,
        }],
    }
    return record, evaluate_decision_outcomes(record, observation)


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
    assert metric["decision_quality_count"] == 2
    assert metric["decision_quality_rate"] == pytest.approx(2 / 3)
    assert metric["block_avoided_adverse_move_rate"] == pytest.approx(0.5)
    assert metric["block_opportunity_cost_rate"] == pytest.approx(0.5)
    assert "SOL-PERP" in summary["performance_by_market"]
    assert "paper" in summary["performance_by_venue"]


def test_decision_quality_scores_allow_and_block_against_later_requested_side_move():
    pairs = [
        _evaluated_pair(_record(allowed=True, decision_id="allow-good"), 105),
        _evaluated_pair(_record(allowed=True, decision_id="allow-bad"), 95),
        _evaluated_pair(_record(allowed=False, decision_id="block-good"), 95),
        _evaluated_pair(_record(allowed=False, decision_id="block-bad"), 105),
    ]
    metric = performance_summary(pairs, primary_horizon="4h")["horizons"]["4h"]
    assert metric["decision_quality_count"] == 2
    assert metric["decision_quality_rate"] == pytest.approx(0.5)


def test_regime_context_reuses_persisted_vol_funding_shock_labels_without_lookahead():
    before = (BASE_TS - timedelta(minutes=10)).isoformat()
    after = (BASE_TS + timedelta(minutes=10)).isoformat()
    history = _context_history(regime=[
        {"id": "1", "ts": before, "vol_regime": "extreme", "funding_regime": "backwardation", "shock_state": "high"},
        {"id": "2", "ts": after, "vol_regime": "low", "funding_regime": "contango", "shock_state": "normal"},
    ])
    context = decision_regime_context(_record(), history)
    assert context["vol_regime"] == "extreme"
    assert context["funding_regime"] == "backwardation"
    assert context["shock_state"] == "high"
    assert context["regime_signature"] == "high|backwardation|extreme"


def test_shock_score_fallback_uses_existing_normal_elevated_high_thresholds():
    for score, expected in ((0.5, "normal"), (0.5001, "elevated"), (1.5, "elevated"), (1.5001, "high")):
        history = _context_history(index=[{
            "id": str(score),
            "ts": (BASE_TS - timedelta(minutes=1)).isoformat(),
            "shock_score": score,
            "rate_of_change": 0,
        }])
        assert decision_regime_context(_record(), history)["shock_state"] == expected


def test_tariff_cohort_reuses_existing_rule_thresholds():
    for roc, expected in ((5.0, "normal"), (5.01, "elevated"), (8.0, "elevated"), (8.01, "severe")):
        history = _context_history(index=[{
            "id": str(roc),
            "ts": (BASE_TS - timedelta(minutes=1)).isoformat(),
            "shock_score": 0,
            "rate_of_change": roc,
        }])
        assert decision_regime_context(_record(), history)["tariff_escalation"] == expected


def test_stablecoin_cohort_uses_persisted_depeg_thresholds_without_inventing_health_score():
    for depeg, expected in ((20.0, "healthy"), (20.01, "warning_depeg"), (50.0, "warning_depeg"), (50.01, "alert_depeg")):
        history = _context_history(stables=[{
            "id": str(depeg),
            "symbol": "USDC",
            "ts": (BASE_TS - timedelta(minutes=1)).isoformat(),
            "depeg_bps": depeg,
        }])
        assert decision_regime_context(_record(), history)["stablecoin_health"] == expected


def test_recorded_normalized_stable_health_uses_allocator_threshold_when_present():
    stressed = _record(decision_id="stable-stress")
    stressed["input_state"]["replay_inputs"]["allocation"] = {
        "state": {"stable_health": 0.69}
    }
    healthy = _record(decision_id="stable-ok")
    healthy["input_state"]["replay_inputs"]["allocation"] = {
        "state": {"stable_health": 0.70}
    }
    assert decision_regime_context(stressed, _context_history())["stablecoin_health"] == "stress"
    assert decision_regime_context(healthy, _context_history())["stablecoin_health"] == "healthy"


def test_liquidity_cohort_preserves_current_agent_zero_depth_edge_semantics_truthfully():
    def with_depth(depth):
        record = _record(decision_id=f"depth-{depth}")
        record["input_state"]["replay_inputs"]["execution_boundary"]["agent"] = {
            "market_state": {"liquidity_depth": depth},
            "min_liquidity_depth": 50.0,
        }
        return record

    assert decision_regime_context(with_depth(100), _context_history())["liquidity_state"] == "sufficient"
    assert decision_regime_context(with_depth(50), _context_history())["liquidity_state"] == "sufficient"
    assert decision_regime_context(with_depth(40), _context_history())["liquidity_state"] == "below_minimum"
    assert decision_regime_context(with_depth(0), _context_history())["liquidity_state"] == "zero_or_unavailable"
    assert decision_regime_context(_record(), _context_history())["liquidity_state"] == "unavailable"


def test_performance_summary_groups_final_decisions_by_regime_cohort_and_signature():
    decision = _record(allowed=False, decision_id="regime-decision")
    decision["input_state"]["replay_inputs"]["execution_boundary"]["agent"] = {
        "market_state": {"liquidity_depth": 25.0},
        "min_liquidity_depth": 50.0,
    }
    history = _context_history(
        regime=[{
            "id": "regime-1", "ts": (BASE_TS - timedelta(minutes=5)).isoformat(),
            "vol_regime": "extreme", "funding_regime": "backwardation", "shock_state": "high",
        }],
        index=[{
            "id": "index-1", "ts": (BASE_TS - timedelta(minutes=5)).isoformat(),
            "shock_score": 2.5, "rate_of_change": 9.0,
        }],
        stables=[{
            "id": "stable-1", "symbol": "USDC", "ts": (BASE_TS - timedelta(minutes=5)).isoformat(),
            "depeg_bps": 55.0,
        }],
    )
    pair = _evaluated_pair(decision, 90)
    summary = performance_summary([pair], primary_horizon="4h", context_history=history)
    assert "extreme" in summary["performance_by_regime"]["vol_regime"]
    assert "backwardation" in summary["performance_by_regime"]["funding_regime"]
    assert "high" in summary["performance_by_regime"]["shock_state"]
    assert "high|backwardation|extreme" in summary["performance_by_regime_signature"]
    assert "severe" in summary["performance_by_cohort"]["tariff_escalation"]
    assert "alert_depeg" in summary["performance_by_cohort"]["stablecoin_health"]
    assert "below_minimum" in summary["performance_by_cohort"]["liquidity_state"]
    assert summary["performance_by_regime"]["vol_regime"]["extreme"]["decision_quality_rate"] == 1.0
    assert summary["performance_by_vol_regime"] == summary["performance_by_regime"]["vol_regime"]


def test_missing_context_is_explicitly_unavailable_not_guessed():
    context = decision_regime_context(_record(), _context_history())
    assert context["vol_regime"] == "unavailable"
    assert context["funding_regime"] == "unavailable"
    assert context["shock_state"] == "unavailable"
    assert context["regime_signature"] == "unavailable"
    assert context["tariff_escalation"] == "unavailable"
    assert context["stablecoin_health"] == "unavailable"


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

    assert "def load_context_history" in repo_source
    assert '@router.get("/{decision_id}/outcomes")' in api_source
    assert '@router.get("/performance")' in api_source
    assert "load_context_history" in api_source
    assert "context_history=context_history" in api_source
    assert "realized_counterfactual_comparison" in api_source
    assert "include_lifecycle=False" in api_source
    assert "Decision Performance Lab" in frontend
    assert "Decision Quality" in frontend
    assert "By Funding Regime" in frontend
    assert "By Shock State" in frontend
    assert "By Combined Regime Signature" in frontend
    assert "Tariff Escalation Cohort" in frontend
    assert "Stablecoin Health Cohort" in frontend
    assert "Liquidity State Cohort" in frontend
    assert "BLOCK Opportunity Cost" in frontend
    assert "Realized Market Context" in counterfactual_frontend
    assert "decision_outcomes.js" in main_source
