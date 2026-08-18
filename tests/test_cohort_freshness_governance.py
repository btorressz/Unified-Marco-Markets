from datetime import datetime, timedelta, timezone

import pytest

from backend.compute.context_governance import (
    COHORT_DEFINITION_VERSION,
    CONTEXT_FRESHNESS_POLICY,
    FRESHNESS_POLICY_VERSION,
    governed_decision_context,
    governance_contract,
)
from backend.compute.decision_outcomes import evaluate_decision_outcomes, performance_summary
from backend.compute.decision_statistics import enrich_performance_summary


BASE_TS = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def _record(*, decision_id="d1", allowed=True):
    return {
        "id": decision_id,
        "decision_ts": BASE_TS.isoformat(),
        "decision_type": "execution_pre_trade_final",
        "venue": "paper",
        "market": "SOL-PERP",
        "symbol": "SOL-PERP",
        "input_state": {
            "replay_inputs": {
                "heuristic": {"status": "not_used"},
                "ml": {"status": "not_used"},
                "allocation": {"status": "not_used"},
                "execution_boundary": {
                    "data": {
                        "fill_price": 100.0,
                        "order": {
                            "venue": "paper",
                            "market": "SOL-PERP",
                            "side": "buy",
                            "size": 1.0,
                            "price": 100.0,
                        },
                    }
                },
            }
        },
        "execution_intent": {"order": {"side": "buy", "size": 1.0, "price": 100.0}},
        "heuristic_result": {"status": "not_used"},
        "ml_result": {"status": "not_used"},
        "final_decision": {
            "decision": "allow" if allowed else "block",
            "allowed": allowed,
        },
    }


def _history(*, regime=None, index=None, stables=None):
    return {
        "available": True,
        "regime_snapshots": list(regime or []),
        "index_history": list(index or []),
        "stablecoin_ticks": list(stables or []),
        "errors": {},
        "truncated": {},
    }


def _row(age_seconds, **values):
    return {
        "id": values.pop("id", f"row-{age_seconds}"),
        "ts": (BASE_TS - timedelta(seconds=age_seconds)).isoformat(),
        **values,
    }


def _future_outcome(record, price=105.0):
    target = BASE_TS + timedelta(hours=4)
    observations = {
        "available": True,
        "observations": [{
            "id": f"obs-{record['id']}",
            "horizon": "4h",
            "target_ts": target.isoformat(),
            "ts": (target + timedelta(minutes=5)).isoformat(),
            "lag_seconds": 300,
            "symbol": "SOL-PERP",
            "venue": "drift",
            "price": price,
        }],
    }
    return evaluate_decision_outcomes(record, observations)


def test_observation_exactly_at_decision_timestamp_is_fresh():
    context = governed_decision_context(
        _record(),
        _history(regime=[_row(0, vol_regime="high", funding_regime="neutral", shock_state="elevated")]),
    )
    assert context["vol_regime"] == "high"
    meta = context["context_governance"]["vol_regime"]
    assert meta["status"] == "available"
    assert meta["age_seconds"] == 0


def test_regime_observation_exactly_at_max_age_is_accepted():
    max_age = CONTEXT_FRESHNESS_POLICY["regime_snapshots"]["max_age_seconds"]
    context = governed_decision_context(
        _record(),
        _history(regime=[_row(max_age, vol_regime="extreme", funding_regime="backwardation", shock_state="high")]),
    )
    assert context["vol_regime"] == "extreme"
    assert context["funding_regime"] == "backwardation"
    assert context["shock_state"] == "high"


def test_regime_observation_one_second_past_max_age_is_unavailable_stale():
    max_age = CONTEXT_FRESHNESS_POLICY["regime_snapshots"]["max_age_seconds"]
    context = governed_decision_context(
        _record(),
        _history(regime=[_row(max_age + 1, vol_regime="extreme", funding_regime="backwardation", shock_state="high")]),
    )
    assert context["vol_regime"] == "unavailable_stale"
    assert context["funding_regime"] == "unavailable_stale"
    assert context["shock_state"] == "unavailable_stale"
    assert context["regime_signature"] == "unavailable_stale"
    assert context["context_governance"]["vol_regime"]["status"] == "unavailable_stale"


def test_future_observation_is_never_attached():
    context = governed_decision_context(
        _record(),
        _history(regime=[{
            "id": "future",
            "ts": (BASE_TS + timedelta(seconds=1)).isoformat(),
            "vol_regime": "extreme",
            "funding_regime": "backwardation",
            "shock_state": "high",
        }]),
    )
    assert context["vol_regime"] == "unavailable"
    assert context["funding_regime"] == "unavailable"
    assert context["shock_state"] == "unavailable"


def test_recorded_immutable_context_wins_even_when_fallback_history_is_stale():
    record = _record()
    record["input_state"]["replay_inputs"]["heuristic"] = {
        "context": {
            "vol_regime": "normal",
            "funding_regime": "contango",
            "shock_state": "normal",
            "tariff_rate_of_change": 4.0,
        }
    }
    stale_age = CONTEXT_FRESHNESS_POLICY["regime_snapshots"]["max_age_seconds"] + 100
    context = governed_decision_context(
        record,
        _history(regime=[_row(stale_age, vol_regime="extreme", funding_regime="backwardation", shock_state="high")]),
    )
    assert context["vol_regime"] == "normal"
    assert context["funding_regime"] == "contango"
    assert context["shock_state"] == "normal"
    assert context["tariff_escalation"] == "normal"
    assert context["context_governance"]["vol_regime"]["origin"] == "immutable_decision"


def test_stale_index_does_not_classify_tariff_or_shock_fallback():
    max_age = CONTEXT_FRESHNESS_POLICY["index_history"]["max_age_seconds"]
    context = governed_decision_context(
        _record(),
        _history(index=[_row(max_age + 1, shock_score=3.0, rate_of_change=12.0)]),
    )
    assert context["tariff_escalation"] == "unavailable_stale"
    assert context["shock_state"] == "unavailable_stale"


def test_all_stablecoin_observations_stale_yields_unavailable_stale():
    max_age = CONTEXT_FRESHNESS_POLICY["stablecoin_ticks"]["max_age_seconds"]
    context = governed_decision_context(
        _record(),
        _history(stables=[
            _row(max_age + 1, id="usdc", symbol="USDC", depeg_bps=5.0),
            _row(max_age + 20, id="usdt", symbol="USDT", depeg_bps=75.0),
        ]),
    )
    assert context["stablecoin_health"] == "unavailable_stale"
    meta = context["context_governance"]["stablecoin_health"]
    assert meta["fresh_symbol_count"] == 0
    assert meta["stale_symbol_count"] == 2


def test_mixed_fresh_and_stale_stablecoins_use_only_fresh_values_and_disclose_stale_count():
    max_age = CONTEXT_FRESHNESS_POLICY["stablecoin_ticks"]["max_age_seconds"]
    context = governed_decision_context(
        _record(),
        _history(stables=[
            _row(60, id="usdc", symbol="USDC", depeg_bps=10.0),
            _row(max_age + 1, id="usdt", symbol="USDT", depeg_bps=90.0),
        ]),
    )
    assert context["stablecoin_health"] == "healthy"
    meta = context["context_governance"]["stablecoin_health"]
    assert meta["fresh_symbol_count"] == 1
    assert meta["stale_symbol_count"] == 1


def test_existing_pr29_cohort_thresholds_are_unchanged():
    max_index = CONTEXT_FRESHNESS_POLICY["index_history"]["max_age_seconds"]
    assert max_index > 60
    for shock_score, expected in ((0.5, "normal"), (0.5001, "elevated"), (1.5, "elevated"), (1.5001, "high")):
        context = governed_decision_context(
            _record(), _history(index=[_row(60, shock_score=shock_score, rate_of_change=0.0)])
        )
        assert context["shock_state"] == expected
    for roc, expected in ((5.0, "normal"), (5.01, "elevated"), (8.0, "elevated"), (8.01, "severe")):
        context = governed_decision_context(
            _record(), _history(index=[_row(60, shock_score=0.0, rate_of_change=roc)])
        )
        assert context["tariff_escalation"] == expected


def test_governance_contract_is_explicit_and_versioned():
    contract = governance_contract()
    assert contract["cohort_definition_version"] == COHORT_DEFINITION_VERSION
    assert contract["freshness_policy_version"] == FRESHNESS_POLICY_VERSION
    assert contract["stale_label"] == "unavailable_stale"
    assert set(contract["freshness_policy"]) == {"regime_snapshots", "index_history", "stablecoin_ticks"}
    assert contract["definitions"]["shock_state"]["version"] == COHORT_DEFINITION_VERSION


def test_enrichment_rebuilds_stale_regime_groups_and_context_coverage():
    max_age = CONTEXT_FRESHNESS_POLICY["regime_snapshots"]["max_age_seconds"]
    fresh_record = _record(decision_id="fresh")
    stale_record = _record(decision_id="stale")
    pairs = [
        (fresh_record, _future_outcome(fresh_record, 105.0)),
        (stale_record, _future_outcome(stale_record, 95.0)),
    ]
    history = _history(regime=[
        _row(60, id="fresh-regime", vol_regime="high", funding_regime="neutral", shock_state="elevated"),
        _row(max_age + 1, id="stale-regime", vol_regime="extreme", funding_regime="backwardation", shock_state="high"),
    ])

    # Move the second decision far enough forward that the latest prior row is stale,
    # while the first decision sees the fresh row.
    stale_record["decision_ts"] = (BASE_TS + timedelta(seconds=max_age + 120)).isoformat()
    pairs[1] = (stale_record, _future_outcome(stale_record, 95.0))

    base = performance_summary(pairs, primary_horizon="4h", context_history=history)
    enriched = enrich_performance_summary(base, pairs, primary_horizon="4h", context_history=history)
    assert "high" in enriched["performance_by_regime"]["vol_regime"]
    assert "unavailable_stale" in enriched["performance_by_regime"]["vol_regime"]
    assert enriched["context_coverage"]["stale_counts"]["vol_regime"] == 1
    assert enriched["cohort_governance"]["cohort_definition_version"] == COHORT_DEFINITION_VERSION
