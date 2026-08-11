from pathlib import Path


ROOT = Path(__file__).parents[1]
ALIGNMENT = ROOT / "frontend" / "assets" / "frontend_alignment.js"


def test_frontend_alignment_layer_is_loaded_additively():
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    legacy_html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "frontend_alignment.js" in main_source
    assert "HTMLResponse" in main_source
    assert "StaticFiles" in main_source
    # PR #11 deliberately leaves the large legacy HTML untouched and injects
    # the additive layer from the root response instead of replacing it.
    assert "frontend_alignment.js" not in legacy_html


def test_historical_backtester_frontend_contract_is_explicit():
    source = ALIGNMENT.read_text(encoding="utf-8")

    for token in (
        "Historical Event-Time",
        "mode:historical?'historical':'synthetic'",
        "/api/backtest/data-coverage",
        "/api/backtest/${encodeURIComponent(id)}",
        "maker_fee_bps",
        "taker_fee_bps",
        "latency_ms",
        "fill_model",
        "partial_fill_ratio",
        "walk_forward",
        "recorded_orders",
        "look_ahead_guard",
        "data_manifest",
        "walk_forward_windows",
    ):
        assert token in source


def test_backtest_result_is_preserved_across_strategy_refresh():
    source = ALIGNMENT.read_text(encoding="utf-8")

    assert "alignmentHasResult" in source
    assert "renderStrategyTab" in source
    assert "if(!data.backtestResult&&keep&&next)" in source


def test_execution_safety_accounting_and_lifecycle_are_visible():
    source = ALIGNMENT.read_text(encoding="utf-8")

    for token in (
        "order_type",
        "slippage_bps",
        "live_execution_enabled",
        "idempotency_status",
        "persistence_status",
        "durable_order_id",
        "requires_reconciliation",
        "RECONCILIATION REQUIRED",
        "portfolio_metrics",
        "realized_pnl",
        "unrealized_pnl",
        "fees",
        "funding",
        "slippage",
        "execution-lifecycle-panel",
        "ORDER_SUBMISSION_UNKNOWN",
    ):
        assert token in source


def test_redis_and_portfolio_risk_alignment_are_read_only():
    source = ALIGNMENT.read_text(encoding="utf-8")

    for token in (
        "getRedisHealth",
        "connection_failures",
        "reconnect_count",
        "publish_failures",
        "sync_pool_in_use",
        "key_namespace",
        "getPortfolioRiskContributions",
        "getPortfolioRiskExposures",
        "portfolio-risk-alignment-panel",
        "READ-ONLY",
        "does not start, stop, or manage Redis",
    ):
        assert token in source


def test_guardrails_expose_existing_execution_safety_without_mutation():
    source = (ROOT / "backend" / "api" / "risk_routes.py").read_text(encoding="utf-8")

    for token in (
        '"live_execution_enabled": config.LIVE_EXECUTION_ENABLED',
        '"supported_execution_venues": config.SUPPORTED_EXECUTION_VENUES',
        '"supported_execution_markets": config.SUPPORTED_EXECUTION_MARKETS',
        '"supported_order_types": config.SUPPORTED_ORDER_TYPES',
        '"max_order_notional": config.MAX_ORDER_NOTIONAL',
        '"max_order_slippage_bps": config.MAX_ORDER_SLIPPAGE_BPS',
    ):
        assert token in source

    assert "LIVE_EXECUTION_ENABLED =" not in source


def test_frontend_alignment_does_not_add_orchestration_infrastructure():
    assert not (ROOT / "docker-compose.yml").exists()
    assert not (ROOT / "docker-compose.yaml").exists()
    assert not (ROOT / "kubernetes").exists()
    assert not (ROOT / "k8s").exists()
