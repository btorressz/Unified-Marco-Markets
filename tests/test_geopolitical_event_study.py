from datetime import datetime, timedelta, timezone

import pytest

from backend.compute.geopolitical_event_study import (
    ASSET_BUCKETS, HORIZONS, NEUTRAL_BAND, aggregate_bucket, analyze_symbol,
    classify_observed, compare_directions, compute_event_study, normalize_study_event,
)


EVENT = {
    "event_id": "ofac-1", "event_type": "OFAC_SANCTION_ADDED", "title": "OFAC addition",
    "source": "OFAC", "event_timestamp": "2026-08-19T10:02:00+00:00",
    "event_time_basis": "provider_change_detected_at_retrieval", "claim_type": "observed_evidence",
    "observed": True, "proxy": False, "authoritative_evidence": True,
}


def row(ts, close):
    return {"ts": ts, "close": close}


def test_reference_and_horizon_selection_never_look_ahead_and_expose_lag():
    history = [
        row("2026-08-19T09:55:00+00:00", 99), row("2026-08-19T10:00:00+00:00", 100),
        row("2026-08-19T10:05:00+00:00", 500), row("2026-08-19T14:03:00+00:00", 102),
    ]
    result = analyze_symbol(history, EVENT["event_timestamp"], now="2026-08-20T12:00:00+00:00")
    assert result["4h"]["reference_timestamp"] == "2026-08-19T10:00:00+00:00"
    assert result["4h"]["reference_price"] == 100
    assert result["4h"]["selected_observation_timestamp"] == "2026-08-19T14:03:00+00:00"
    assert result["4h"]["lag_seconds"] == 60
    assert result["4h"]["observed_return"] == pytest.approx(102 / 100 - 1)


def test_not_matured_and_missing_observations_are_truthful_not_zero():
    result = analyze_symbol([], EVENT["event_timestamp"], now="2026-08-19T12:02:00+00:00")
    assert result["1h"]["status"] == "unavailable"
    assert result["1h"]["return"] is None
    assert result["4h"]["status"] == "not_matured"
    assert result["24h"]["status"] == "not_matured"
    assert result["7d"]["status"] == "not_matured"


@pytest.mark.parametrize(("expected", "observed", "classification"), [
    ("UP", "UP", "MATCH"), ("UP", "DOWN", "CONTRADICT"),
    ("DOWN", "DOWN", "MATCH"), ("DOWN", "UP", "CONTRADICT"),
    ("UNKNOWN", "UP", "UNSCORABLE"), ("UP", "FLAT", "MIXED"),
    ("MIXED", "UP", "MIXED"),
])
def test_directional_classifications(expected, observed, classification):
    assert compare_directions(expected, observed) == classification


def test_neutral_band_is_explicit_and_inclusive():
    assert classify_observed(NEUTRAL_BAND) == "FLAT"
    assert classify_observed(-NEUTRAL_BAND) == "FLAT"
    assert classify_observed(NEUTRAL_BAND + 0.000001) == "UP"


def test_equal_weight_basket_uses_available_values_and_exposes_coverage():
    symbol_results = {
        "A": {h: {"status": "available", "observed_return": .02, "selected_observation_timestamp": "2026-08-19T11:02:00+00:00"} for h in HORIZONS},
        "B": {h: {"status": "available", "observed_return": -.01, "selected_observation_timestamp": "2026-08-19T11:03:00+00:00"} for h in HORIZONS},
        "C": {h: {"status": "unavailable", "observed_return": None} for h in HORIZONS},
    }
    result = aggregate_bucket(symbol_results, ["A", "B", "C"], "UP")["observations"]["1h"]
    assert result["return"] == pytest.approx(.005)
    assert result["available_constituent_count"] == 2
    assert result["total_constituent_count"] == 3
    assert result["classification"] == "MATCH"
    insufficient = aggregate_bucket({"A": symbol_results["A"]}, ["A", "B", "C"], "UP")["observations"]["1h"]
    assert insufficient["status"] == "unavailable" and insufficient["return"] is None


def test_complete_study_preserves_evidence_and_non_causal_research_boundary():
    event_time = datetime.fromisoformat(EVENT["event_timestamp"])
    history = [row((event_time - timedelta(minutes=2)).isoformat(), 100)]
    for seconds in HORIZONS.values(): history.append(row((event_time + timedelta(seconds=seconds)).isoformat(), 101))
    study = compute_event_study(EVENT, {symbol: history for meta in ASSET_BUCKETS.values() for symbol in meta["symbols"]}, now=event_time + timedelta(days=8))
    assert study["event"]["claim_type"] == "observed_evidence"
    assert study["event"]["authoritative_evidence"] is True
    assert study["event_study"] is True and study["causal_claim"] is False
    assert study["persisted"] is False and study["orders_submitted"] == 0
    assert study["expectation_model"]["observed"] is False
    assert study["buckets"][0]["observations"]["1h"]["observed_market_reaction"] is True


def test_proxy_event_does_not_become_observed_because_market_history_exists():
    proxy = normalize_study_event({**EVENT, "event_id": "red-sea", "event_type": "SHIPPING_DISRUPTION", "claim_type": "evidence_supported_proxy", "observed": False, "proxy": True, "authoritative_evidence": False})
    assert proxy["claim_type"] == "evidence_supported_proxy"
    assert proxy["observed"] is False and proxy["authoritative_evidence"] is False


def test_compute_module_has_no_state_execution_or_repository_imports():
    import inspect
    import backend.compute.geopolitical_event_study as module
    source = inspect.getsource(module)
    for forbidden in ("ExecutionRouter", "OrdersRepository", "StateStore", "venue adapter"):
        assert forbidden not in source
