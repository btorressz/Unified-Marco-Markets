from datetime import datetime, timedelta, timezone

import pytest

from backend.compute.decision_outcomes import HORIZONS, evaluate_decision_outcomes, performance_summary
from backend.compute.decision_statistics import enrich_performance_summary, metric_statistics
from backend.data.repositories.decision_outcome_repo import DecisionOutcomeRepository


BASE_TS = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _record(decision_id: str, *, allowed: bool = True, price: float = 100.0):
    return {
        "id": decision_id,
        "decision_ts": BASE_TS.isoformat(),
        "decision_type": "execution_pre_trade_final",
        "venue": "paper",
        "market": "SOL-PERP",
        "symbol": "SOL-PERP",
        "input_state": {
            "replay_inputs": {
                "execution_boundary": {
                    "data": {
                        "fill_price": price,
                        "order": {
                            "venue": "paper",
                            "market": "SOL-PERP",
                            "side": "buy",
                            "size": 1.0,
                            "price": price,
                        },
                    }
                }
            }
        },
        "execution_intent": {"order": {"side": "buy", "size": 1.0, "price": price}},
        "final_decision": {
            "decision": "allow" if allowed else "block",
            "allowed": allowed,
        },
    }


def _outcome(record, signed_return: float | None):
    if signed_return is None:
        observations = {"available": True, "observations": []}
    else:
        target = BASE_TS + timedelta(hours=4)
        observations = {
            "available": True,
            "observations": [{
                "id": f"obs-{record['id']}",
                "horizon": "4h",
                "target_ts": target.isoformat(),
                "ts": target.isoformat(),
                "lag_seconds": 0,
                "symbol": "SOL-PERP",
                "venue": "drift",
                "price": 100.0 * (1.0 + signed_return),
            }],
        }
    return evaluate_decision_outcomes(record, observations)


def test_metric_statistics_reports_distribution_missingness_and_low_sample():
    values = [-0.04, 0.01, 0.02, 0.08]
    items = [_outcome(_record(f"d-{i}"), value) for i, value in enumerate(values)]
    items.append(_outcome(_record("missing"), None))

    stats = metric_statistics(items, "4h")

    assert stats["missing_count"] == 1
    assert stats["missing_rate"] == pytest.approx(0.2)
    assert stats["coverage_rate"] == pytest.approx(0.8)
    assert stats["median_signed_return"] == pytest.approx(0.015)
    assert stats["signed_return_p25"] == pytest.approx(-0.0025)
    assert stats["signed_return_p75"] == pytest.approx(0.035)
    assert stats["signed_return_min"] == pytest.approx(-0.04)
    assert stats["signed_return_max"] == pytest.approx(0.08)
    assert stats["signed_return_stddev"] is not None
    assert stats["low_sample"] is True
    assert stats["sample_quality"] == "very_low"
    assert stats["sample_warning"] == "VERY_LOW_SAMPLE"


def test_statistics_enrichment_is_additive_and_preserves_existing_quality_metrics():
    allow = _record("allow", allowed=True)
    block = _record("block", allowed=False)
    pairs = [
        (allow, _outcome(allow, 0.05)),
        (block, _outcome(block, -0.03)),
    ]
    summary = performance_summary(pairs, primary_horizon="4h")
    original_quality = summary["horizons"]["4h"]["decision_quality_rate"]

    enriched = enrich_performance_summary(summary, pairs, primary_horizon="4h", context_history={})
    metric = enriched["horizons"]["4h"]

    assert metric["decision_quality_rate"] == original_quality == 1.0
    assert metric["average_signed_return"] == pytest.approx(0.01)
    assert metric["median_signed_return"] == pytest.approx(0.01)
    assert metric["coverage_rate"] == 1.0
    assert enriched["statistics_contract"]["descriptive_only"] is True
    assert enriched["statistics_contract"]["significance_claims"] is False


def test_batch_loader_matches_single_loader_window_semantics(monkeypatch):
    import backend.data.repositories.decision_outcome_repo as module

    target_1h = BASE_TS + timedelta(hours=1)
    target_4h = BASE_TS + timedelta(hours=4)
    rows = [
        {"id": "1", "symbol": "SOL-PERP", "venue": "kraken", "price": 101.0, "confidence": 1, "ts": target_1h},
        {"id": "2", "symbol": "SOL-PERP", "venue": "drift", "price": 102.0, "confidence": 1, "ts": target_1h + timedelta(seconds=10)},
        {"id": "3", "symbol": "SOL/USD", "venue": "pyth", "price": 103.0, "confidence": 1, "ts": target_4h},
        {"id": "4", "symbol": "BTC/USD", "venue": "pyth", "price": 99999.0, "confidence": 1, "ts": target_4h},
    ]
    calls = []

    def fake_execute_query(sql, params):
        calls.append((sql, params))
        symbols = {str(value).upper() for value in params[0]}
        start = datetime.fromisoformat(str(params[1]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(params[2]).replace("Z", "+00:00"))
        limit = int(params[3]) if len(params) > 3 else 100
        eligible = [
            row for row in rows
            if row["symbol"].upper() in symbols and start <= row["ts"] <= end
        ]
        eligible.sort(key=lambda row: (row["ts"], row["id"]))
        return eligible[:limit]

    monkeypatch.setattr(module, "execute_query", fake_execute_query)
    repo = DecisionOutcomeRepository()
    horizons = {"1h": HORIZONS["1h"], "4h": HORIZONS["4h"]}
    symbols = ["SOL-PERP", "SOL/USD"]

    single = repo.load_horizon_prices(
        decision_ts=BASE_TS,
        symbols=symbols,
        horizons=horizons,
        tolerance_seconds=60,
    )
    single_call_count = len(calls)
    calls.clear()

    batch = repo.load_horizon_prices_batch(
        requests=[{"request_id": "d1", "decision_ts": BASE_TS, "symbols": symbols}],
        horizons=horizons,
        tolerance_seconds=60,
    )

    assert single_call_count == 2
    assert len(calls) == 1
    assert batch["query_count"] == 1
    assert batch["batch_fallback"] is False
    assert batch["results"]["d1"]["observations"] == single["observations"]


def test_batch_loader_falls_back_to_existing_loader_when_global_bound_is_exceeded(monkeypatch):
    import backend.data.repositories.decision_outcome_repo as module

    monkeypatch.setattr(DecisionOutcomeRepository, "BATCH_MARKET_MAX_ROWS", 1)
    target = BASE_TS + timedelta(hours=1)
    rows = [
        {"id": "1", "symbol": "SOL-PERP", "venue": "drift", "price": 101.0, "confidence": 1, "ts": target},
        {"id": "2", "symbol": "SOL-PERP", "venue": "drift", "price": 102.0, "confidence": 1, "ts": target + timedelta(seconds=1)},
    ]

    def fake_execute_query(sql, params):
        if len(params) == 4 and int(params[3]) == 2:
            return rows
        return rows[:1]

    monkeypatch.setattr(module, "execute_query", fake_execute_query)
    repo = DecisionOutcomeRepository()
    batch = repo.load_horizon_prices_batch(
        requests=[{"request_id": "d1", "decision_ts": BASE_TS, "symbols": ["SOL-PERP"]}],
        horizons={"1h": HORIZONS["1h"]},
        tolerance_seconds=60,
    )

    assert batch["batch_fallback"] is True
    assert batch["fallback_reason"] == "bounded batch market window exceeded safety limit"
    assert batch["results"]["d1"]["available"] is True


def test_performance_route_and_frontend_keep_research_only_contracts():
    from pathlib import Path

    api_source = Path("backend/api/decision_routes.py").read_text()
    repo_source = Path("backend/data/repositories/decision_outcome_repo.py").read_text()
    stats_source = Path("backend/compute/decision_statistics.py").read_text()
    frontend = Path("frontend/assets/decision_outcomes.js").read_text()

    assert "load_horizon_prices_batch" in api_source
    assert "enrich_performance_summary" in api_source
    assert "def load_horizon_prices_batch" in repo_source
    assert "BATCH_MARKET_MAX_ROWS" in repo_source
    assert "significance_claims" in stats_source
    assert "Median Signed Return" in frontend
    assert "25th Percentile" in frontend
    assert "75th Percentile" in frontend
    assert "LOW SAMPLE" in frontend
    assert "Outcome market queries" in frontend

    lowered = repo_source.lower()
    for forbidden in ("insert into", "update ", "delete from", "execute_write", "execute_returning"):
        assert forbidden not in lowered
