from datetime import datetime, timezone

from backend.ingest.provenance import IngestRunContext, sanitize_error
from backend.ingest.source_registry import SOURCE_REGISTRY, list_sources


def test_registry_has_stable_source_contracts():
    expected = {"pyth_sol_usd", "kraken_sol_usd", "coingecko_sol_usd", "drift_sol_perp", "drift_funding_sol_perp", "wits_tariffs", "gdelt_macro_news"}
    assert expected == set(SOURCE_REGISTRY)
    assert SOURCE_REGISTRY["pyth_sol_usd"]["fallback_chain"] == ["kraken_sol_usd", "coingecko_sol_usd"]
    assert all(s["provider"] and s["expected_cadence_seconds"] > 0 and s["storage_target"] for s in list_sources())
    assert SOURCE_REGISTRY["pyth_sol_usd"]["authoritative"] is True


def test_context_distinguishes_provider_timestamp_counts_and_fallback():
    context = IngestRunContext("wits_tariffs")
    ts = datetime.now(timezone.utc)
    context.set_provider_timestamp(ts); context.record_received(3); context.record_persisted(2)
    context.mark_fallback(fallback_type="sample", reason="provider_request_failure")
    assert context.status == "fallback"
    assert context.provider_success is False
    assert context.finish_fields()["records_received"] == 3
    assert context.metadata["fallback_reason"] == "provider_request_failure"


def test_context_failure_and_error_messages_are_bounded():
    context = IngestRunContext("gdelt_macro_news")
    context.mark_failure(RuntimeError("x" * 3000))
    assert context.status == "failure"
    assert len(context.error_message) == 1500
    assert len(sanitize_error("x" * 3000)) == 1500


def test_skipped_lease_reliability_exclusion(monkeypatch):
    import pytest
    pytest.importorskip("psycopg2")
    import backend.data.repositories.ingest_repo as module
    rows = [
        {"status": "skipped_lease", "started_at": 4},
        {"status": "failure", "started_at": 3, "completed_at": 3},
        {"status": "fallback", "started_at": 2, "completed_at": 2},
        {"status": "success", "started_at": 1, "completed_at": 1},
    ]
    monkeypatch.setattr(module.IngestRepository, "get_source_runs", lambda self, source_id: rows)
    status = module.IngestRepository().get_registry_status(["pyth_sol_usd"])["pyth_sol_usd"]
    assert status["recent_run_count"] == 3
    assert status["failure_streak"] == 1
    assert status["recent_success_rate"] == 1 / 3
    assert status["recent_failure_rate"] == 1 / 3
