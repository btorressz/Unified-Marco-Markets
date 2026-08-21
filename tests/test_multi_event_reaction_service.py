from datetime import datetime, timedelta, timezone

from backend.compute.event_linked_outcomes import funding_reactions
from backend.services.multi_event_reaction_service import MultiEventReactionService

T = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _dt(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def event(event_id, *, minutes=0, basis="provider_change_detected_at_retrieval",
          event_type="OFAC_SANCTION_ADDED", family="sanctions"):
    return {
        "id": event_id,
        "event_key": f"key:{event_id}",
        "event_family": family,
        "event_type": event_type,
        "source_id": "ofac_sdn",
        "claim_type": "observed_evidence",
        "study_eligible": True,
        "synthetic": False,
        "event_timestamp": T + timedelta(minutes=minutes),
        "event_time_basis": basis,
    }


class FakeEvents:
    def __init__(self, rows):
        self.rows = rows

    def list_events(self, **kwargs):
        return list(self.rows)


class FakeHistory:
    def __init__(self):
        self.calls = []

    def get_event_points_batch(self, *, symbol, event_targets, interval_seconds, source_id):
        self.calls.append((symbol, len(event_targets)))
        rows = []
        by_event = {}
        for target in event_targets:
            by_event.setdefault(target["event_id"], target["event_ts"])
        for event_id, event_ts in by_event.items():
            rows.append({
                "event_id": event_id,
                "point_kind": "reference",
                "horizon": None,
                "ts": _dt(event_ts),
                "close": 100.0,
            })
        for target in event_targets:
            rows.append({
                "event_id": target["event_id"],
                "point_kind": "target",
                "horizon": target["horizon"],
                "ts": _dt(target["target_ts"]),
                "close": 101.0,
            })
        return {
            "rows": rows,
            "coverage": {
                "first_observation_ts": T - timedelta(days=30),
                "last_observation_ts": T + timedelta(days=30),
                "row_count": 999999,
            },
            "query_mode": "event_target_lateral_v1",
            "truncated": False,
            "requested_target_count": len(event_targets),
        }


class FakeDerivatives:
    def __init__(self):
        self.funding_calls = []
        self.basis_calls = []

    def get_funding_event_points_batch(self, *, venue, market, event_targets):
        self.funding_calls.append((venue, market, len(event_targets)))
        rows = []
        seen = {}
        for target in event_targets:
            seen.setdefault(target["event_id"], target["event_ts"])
        for event_id, event_ts in seen.items():
            rows.append({
                "event_id": event_id,
                "point_kind": "reference",
                "provider_timestamp": _dt(event_ts),
                "normalized_funding_rate": -0.0001,
                "annualized_rate": -0.876,
                "venue": venue,
                "market": market,
                "source_id": "hyperliquid_funding_history_research",
                "rate_kind": "realized",
                "contract_version": 1,
                "interval_seconds": 3600,
                "timestamp_semantics": "provider_settlement",
                "sign_convention": "positive_long_pays_short",
            })
        for target in event_targets:
            rows.append({
                "event_id": target["event_id"],
                "point_kind": "target",
                "horizon": target["horizon"],
                "provider_timestamp": _dt(target["target_ts"]),
                "normalized_funding_rate": 0.0002,
                "annualized_rate": 1.752,
                "venue": venue,
                "market": market,
                "source_id": "hyperliquid_funding_history_research",
                "rate_kind": "realized",
                "contract_version": 1,
                "interval_seconds": 3600,
                "timestamp_semantics": "provider_settlement",
                "sign_convention": "positive_long_pays_short",
            })
        return {
            "rows": rows,
            "coverage": {
                "first_timestamp": T - timedelta(days=30),
                "latest_timestamp": T + timedelta(days=30),
                "row_count": 9999,
            },
            "query_mode": "event_target_lateral_v1",
            "truncated": False,
            "requested_target_count": len(event_targets),
        }

    def get_basis_event_points_batch(self, *, symbol, venue, market, event_targets):
        self.basis_calls.append((symbol, venue, market, len(event_targets)))
        rows = []
        seen = {}
        for target in event_targets:
            seen.setdefault(target["event_id"], target["event_ts"])
        for event_id, event_ts in seen.items():
            rows.append({
                "event_id": event_id,
                "point_kind": "reference",
                "observed_at": _dt(event_ts),
                "basis_bps": -2.0,
                "symbol": symbol,
                "venue": venue,
                "market": market,
                "spot_source": "pyth",
                "lineage": {"point": "reference"},
            })
        for target in event_targets:
            rows.append({
                "event_id": target["event_id"],
                "point_kind": "target",
                "horizon": target["horizon"],
                "observed_at": _dt(target["target_ts"]),
                "basis_bps": 3.0,
                "symbol": symbol,
                "venue": venue,
                "market": market,
                "spot_source": "pyth",
                "lineage": {"point": target["horizon"]},
            })
        return {
            "rows": rows,
            "coverage": {
                "first_timestamp": T - timedelta(days=30),
                "latest_timestamp": T + timedelta(days=30),
                "row_count": 9999,
            },
            "query_mode": "event_target_lateral_v1",
            "truncated": False,
            "requested_target_count": len(event_targets),
        }


class FakeDecisions:
    def __init__(self, decisions=None, truncated=False):
        self.rows = list(decisions or [])
        self.truncated = truncated

    def list_complete_bounded(self, **kwargs):
        candidate = len(self.rows) + (1 if self.truncated else 0)
        return {
            "decisions": list(self.rows),
            "candidate_decision_count": candidate,
            "included_decision_count": len(self.rows),
            "truncated": self.truncated,
            "truncation_reason": "safe_global_bound" if self.truncated else None,
            "global_limit": 5000,
        }


class FakeOutcomes:
    def __init__(self, snapshots=None, prices=None, truncated=False):
        self.snapshots = list(snapshots or [])
        self.prices = prices or {}
        self.truncated = truncated
        self.batch_calls = 0

    def load_context_history(self, **kwargs):
        return {
            "available": True,
            "regime_snapshots": self.snapshots,
            "index_history": [],
            "stablecoin_ticks": [],
            "errors": {},
            "truncated": {"regime_snapshots": self.truncated},
        }

    def load_horizon_prices_batch(self, *, requests, horizons, tolerance_seconds=3600):
        self.batch_calls += 1
        results = {}
        for request in requests:
            decision_id = str(request["request_id"])
            decision_ts = _dt(request["decision_ts"])
            price = float(self.prices.get(decision_id, 100.0))
            results[decision_id] = {
                "available": True,
                "observations": [
                    {
                        "id": f"{decision_id}:{horizon}",
                        "symbol": "BTC-PERP",
                        "venue": "hyperliquid",
                        "price": price,
                        "horizon": horizon,
                        "target_ts": (decision_ts + timedelta(seconds=seconds)).isoformat(),
                        "ts": (decision_ts + timedelta(seconds=seconds)).isoformat(),
                        "lag_seconds": 0.0,
                    }
                    for horizon, seconds in horizons.items()
                ],
            }
        return {
            "available": True,
            "results": results,
            "query_count": 1,
            "batch_fallback": False,
            "read_only": True,
        }


def decision(decision_id, *, minutes, allowed, explicit=False):
    return {
        "id": decision_id,
        "decision_ts": T + timedelta(minutes=minutes),
        "decision_type": "execution_pre_trade_final",
        "venue": "hyperliquid",
        "market": "BTC-PERP",
        "symbol": "BTC-PERP",
        "input_provenance": {"event_id": "e1"} if explicit else {},
        "input_state": {
            "replay_inputs": {
                "execution_boundary": {
                    "data": {"order": {"side": "buy", "price": 100.0, "size": 1.0}}
                }
            }
        },
        "derived_state": {},
        "heuristic_result": {},
        "ml_result": {},
        "risk_result": {},
        "allocation_result": {},
        "execution_intent": {},
        "component_versions": {},
        "config_snapshot": {},
        "final_decision": {"allowed": allowed},
    }


def service(events, *, decisions=None, outcomes=None):
    return MultiEventReactionService(
        events=FakeEvents(events),
        history=FakeHistory(),
        derivatives=FakeDerivatives(),
        decisions=decisions or FakeDecisions(),
        outcomes=outcomes or FakeOutcomes(),
    )


def test_service_sample_accounting_strata_and_batch_queries_are_truthful():
    events = [
        event("e1", event_type="OFAC_SANCTION_ADDED", family="sanctions"),
        event("e2", minutes=180, event_type="WITS_TARIFF_UPDATE", family="trade"),
    ]
    sut = service(events)
    result = sut.build(include_decisions=False, now=T + timedelta(days=10))

    assert result["sample"]["candidate_event_count"] == 2
    assert result["sample"]["included_event_count"] == 2
    assert result["sample"]["excluded_event_count"] == 0
    assert set(result["results_by_event_type"]) == {"OFAC_SANCTION_ADDED", "WITS_TARIFF_UPDATE"}
    assert set(result["results_by_event_family"]) == {"sanctions", "trade"}
    assert result["headline_statistics"]["available"] is True
    assert len(sut.history.calls) == 3
    assert len(sut.derivatives.funding_calls) == 3
    assert len(sut.derivatives.basis_calls) == 6

    for series in result["data_query_integrity"]["price"].values():
        assert series["truncated"] is False
        assert series["query_mode"] == "event_target_lateral_v1"
    for series in result["data_query_integrity"]["funding"].values():
        assert series["truncated"] is False
    for series in result["data_query_integrity"]["basis"].values():
        assert series["truncated"] is False

    funding_1h = result["funding_statistics"]["BTC-PERP:hyperliquid"]["1h"]
    assert funding_1h["funding_reaction_counts"]["increased_count"] == 2
    assert funding_1h["funding_reaction_counts"]["sign_flip_count"] == 2

    basis_1h = result["basis_statistics"]["BTC:hyperliquid"]["1h"]
    assert basis_1h["basis_reaction_counts"]["discount_to_premium_count"] == 2
    assert basis_1h["basis_reaction_counts"]["sign_flip_count"] == 2


def test_heterogeneous_time_basis_suppresses_headline_but_populates_strata():
    events = [
        event("e1", basis="provider_change_detected_at_retrieval"),
        event("e2", minutes=180, basis="published_at"),
    ]
    result = service(events).build(include_decisions=False, now=T + timedelta(days=10))

    assert result["sample"]["heterogeneous_event_time_basis"] is True
    assert result["headline_statistics"] == {
        "available": False, "reason": "heterogeneous_event_time_basis"
    }
    assert result["price_statistics"] == {}
    assert set(result["results_by_event_time_basis"]) == {
        "provider_change_detected_at_retrieval", "published_at"
    }
    assert "suppressed because event_time_basis is heterogeneous" in result["statistics_contract"]["warning"]


def test_regime_overlap_and_coverage_use_same_horizon_policy():
    events = [event("e1"), event("e2", minutes=30)]
    snapshots = [
        {
            "id": 1, "ts": T - timedelta(minutes=5), "tariff_index": 1.0,
            "shock_state": "normal", "funding_regime": "neutral", "vol_regime": "low",
        },
        {
            "id": 2, "ts": T + timedelta(hours=1), "tariff_index": 1.0,
            "shock_state": "high", "funding_regime": "neutral", "vol_regime": "high",
        },
        {
            "id": 3, "ts": T + timedelta(hours=1, minutes=30), "tariff_index": 1.0,
            "shock_state": "high", "funding_regime": "neutral", "vol_regime": "high",
        },
    ]
    result = service(events, outcomes=FakeOutcomes(snapshots=snapshots)).build(
        include_decisions=False, now=T + timedelta(days=10)
    )
    row = result["regime_statistics"]["vol_regime"]["1h"]
    assert row["candidate_event_count"] == 2
    assert row["included_event_count"] == 1
    assert row["overlap_excluded_count"] == 1
    assert row["transition_observed_n"] == 1
    assert row["reference_available_n"] == 1
    assert row["target_available_n"] == 1


def test_decision_outcomes_are_aggregated_and_link_types_stay_separate():
    events = [event("e1")]
    decisions = FakeDecisions([
        decision("d1", minutes=30, allowed=True, explicit=True),
        decision("d2", minutes=120, allowed=False, explicit=False),
    ])
    outcomes = FakeOutcomes(prices={"d1": 110.0, "d2": 90.0})
    result = service(events, decisions=decisions, outcomes=outcomes).build(
        include_decisions=True, now=T + timedelta(days=10)
    )
    stats = result["decision_statistics"]

    assert stats["statistics_available"] is True
    assert stats["candidate_decision_count"] == 2
    assert stats["included_decision_count"] == 2
    assert stats["linked_decision_count"] == 2
    assert stats["link_type_counts"] == {
        "explicit_recorded_link": 1,
        "temporal_proximity_only": 1,
    }
    assert stats["horizons"]["4h"]["classification_counts"] == {
        "avoided_adverse_move_after_block": 1,
        "favorable_move_after_allow": 1,
    }
    assert stats["results_by_link_type"]["explicit_recorded_link"]["allow_count"] == 1
    assert stats["results_by_link_type"]["temporal_proximity_only"]["block_count"] == 1
    assert "not realized P&L" in stats["pnl_semantics"]
    assert stats["query_integrity"]["batch_count"] == 1


def test_truncated_decision_cohort_is_not_treated_as_complete_statistics():
    events = [event("e1")]
    decisions = FakeDecisions([decision("d1", minutes=30, allowed=True)], truncated=True)
    result = service(events, decisions=decisions).build(
        include_decisions=True, now=T + timedelta(days=10)
    )
    stats = result["decision_statistics"]
    assert stats["truncated"] is True
    assert stats["statistics_available"] is False
    assert stats["reason"] == "decision_cohort_truncated"


def test_true_series_coverage_prevents_query_slice_from_becoming_fake_dataset_start():
    rows = [{
        "provider_timestamp": T + timedelta(hours=1),
        "normalized_funding_rate": 0.0002,
        "annualized_rate": 1.752,
        "venue": "hyperliquid",
        "market": "BTC-PERP",
        "source_id": "hyperliquid_funding_history_research",
        "rate_kind": "realized",
        "contract_version": 1,
        "interval_seconds": 3600,
    }]
    result = funding_reactions(
        rows,
        T,
        now=T + timedelta(days=10),
        coverage={
            "first_timestamp": T - timedelta(days=7),
            "latest_timestamp": T + timedelta(days=7),
        },
    )
    assert result["horizons"]["1h"]["reason"] == "no_valid_pre_event_reference"
    assert result["horizons"]["1h"]["reason"] != "event_predates_dataset"
