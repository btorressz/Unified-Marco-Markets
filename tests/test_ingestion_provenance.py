from datetime import datetime, timezone
from pathlib import Path

from backend.ingest.provenance import IngestRunContext, sanitize_error
from backend.ingest.source_registry import SOURCE_REGISTRY, list_sources


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_registry_has_stable_source_contracts():
    expected = {
        "pyth_sol_usd",
        "kraken_sol_usd",
        "coingecko_sol_usd",
        "yfinance_crypto_research",
        "yfinance_crypto_history_research",
        "hyperliquid_sol_usd",
        "hyperliquid_funding_history_research",
        "drift_sol_perp",
        "drift_funding_sol_perp",
        "wits_tariffs",
        "gdelt_macro_news",
        "ofac_sanctions",
        "wto_trade",
        "basis_materializer_v1",
    }
    assert expected == set(SOURCE_REGISTRY)
    assert SOURCE_REGISTRY["pyth_sol_usd"]["fallback_chain"] == ["kraken_sol_usd", "coingecko_sol_usd", "yfinance_crypto_research"]
    assert SOURCE_REGISTRY["kraken_sol_usd"]["fallback_chain"] == ["coingecko_sol_usd", "yfinance_crypto_research"]
    assert SOURCE_REGISTRY["coingecko_sol_usd"]["fallback_chain"] == ["yfinance_crypto_research"]
    assert all(s["provider"] and s["expected_cadence_seconds"] > 0 and s["storage_target"] for s in list_sources())
    assert SOURCE_REGISTRY["pyth_sol_usd"]["authoritative"] is True
    yahoo = SOURCE_REGISTRY["yfinance_crypto_research"]
    assert yahoo["authoritative"] is False
    assert yahoo["research_fallback"] is True
    assert yahoo["execution_eligible"] is False
    history = SOURCE_REGISTRY["yfinance_crypto_history_research"]
    assert history["storage_target"] == "research_market_bars"
    assert history["execution_eligible"] is False
    assert history["expected_cadence_seconds"] == 3600
    assert SOURCE_REGISTRY["ofac_sanctions"]["observation_contract_version"] == 2
    assert SOURCE_REGISTRY["wto_trade"]["execution_eligible"] is False


def test_wits_registry_uses_canonical_aggregate_freshness_key():
    source = SOURCE_REGISTRY["wits_tariffs"]
    assert source["snapshot_key"] == "wits:tariff:aggregate"
    wits = _source("backend/ingest/wits_ingest.py")
    assert 'WITS_AGGREGATE_SNAPSHOT_KEY = "wits:tariff:aggregate"' in wits
    assert "_store_aggregate_freshness(results, run_context=run_context)" in wits
    assert '"countries": list(WITS_COUNTRIES)' in wits
    assert '"products": list(WITS_PRODUCTS)' in wits


def test_hyperliquid_feed_health_compatibility_is_preserved():
    source = SOURCE_REGISTRY["hyperliquid_sol_usd"]
    assert source["provider"] == "Hyperliquid"
    assert source["snapshot_key"] == "market:hyperliquid:SOL_PERP"
    assert source["storage_target"] == "market_ticks+funding_ticks+redis_snapshot"
    health = _source("backend/api/health_routes.py")
    assert "for s in list_sources()" in health


def test_context_distinguishes_provider_timestamp_counts_and_fallback():
    context = IngestRunContext("wits_tariffs")
    ts = datetime.now(timezone.utc)
    context.set_provider_timestamp(ts)
    context.record_received(3)
    context.record_persisted(2)
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


def test_gdelt_counts_processed_articles_and_bounded_evidence_separately():
    gdelt = _source("backend/ingest/gdelt_ingest.py")
    assert 'run_context.metadata["records_processed"] = len(df)' in gdelt
    assert 'run_context.metadata["evidence_documents_persisted"] = persisted' in gdelt
    assert "run_context.record_persisted(1 + persisted)" in gdelt
    assert "run_context.record_persisted(len(df))" not in gdelt
    assert "MAX_EVIDENCE_DOCUMENTS = 20" in gdelt
    assert 'artifact_type="gdelt_article_evidence"' in gdelt
    assert 'self.state_store.set_snapshot("gdelt:latest"' in gdelt


def test_scheduler_preserves_run_ledger_and_lease_semantics():
    scheduler = _source("backend/ingest/scheduler.py")
    assert "async def _run_source" in scheduler
    assert "self.ingest_repo.start_run" in scheduler
    assert 'status="skipped_lease"' in scheduler
    assert "lease_skipped=True" in scheduler
    assert '"drift_sol_perp", "drift-market"' in scheduler
    assert '"drift_funding_sol_perp", "drift-funding"' in scheduler
    assert '"yfinance_crypto_research"' in scheduler
    assert "if self.state_store.get_redis() is None:" in scheduler


def test_ingestion_api_and_frontend_remain_read_only_and_wired():
    routes = _source("backend/api/ingestion_routes.py")
    assert '@router.get("/registry")' in routes
    assert '@router.get("/status")' in routes
    assert '@router.get("/runs")' in routes
    assert '@router.get("/provenance")' in routes
    assert "@router.post" not in routes
    assert "@router.put" not in routes
    assert "@router.delete" not in routes

    api = _source("frontend/assets/api.js")
    app = _source("frontend/assets/app.js")
    ui = _source("frontend/assets/ui.js")
    html = _source("frontend/index.html")
    assert "getIngestionRegistry" in api
    assert "getIngestionStatus" in api
    assert "getIngestionRuns" in api
    assert "getDataProvenance" in api
    assert "initProvenanceInspector" in app
    assert "renderIngestionStatus" in ui
    assert "renderDataProvenance" in ui
    assert 'id="provenance-form"' in html


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
