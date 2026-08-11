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


def _core_frontend_source():
    return "\n".join((ROOT / "frontend" / path).read_text(encoding="utf-8") for path in ("index.html", "assets/api.js", "assets/app.js", "assets/ui.js", "assets/styles.css"))


def test_historical_backtester_frontend_contract_is_explicit():
    source = _core_frontend_source()
    for token in ("Historical Event-Time", "/api/backtest/data-coverage", "maker_fee_bps", "taker_fee_bps", "latency_ms", "fill_model", "partial_fill_ratio", "walk_forward", "recorded_orders", "look_ahead_guard", "data_manifest", "walk_forward_windows"):
        assert token in source


def test_execution_safety_accounting_and_lifecycle_are_visible():
    source = _core_frontend_source()
    for token in ("order_type", "slippage_bps", "persistence_status", "requires_reconciliation", "portfolio_metrics", "realized_pnl", "unrealized_pnl", "fees", "funding", "slippage", "execution-lifecycle-panel"):
        assert token in source


def test_redis_and_portfolio_risk_alignment_are_read_only():
    source = _core_frontend_source()
    for token in ("getRedisHealth", "connection_failures", "reconnect_count", "publish_failures", "getPortfolioRiskContributions", "getPortfolioRiskExposures"):
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


def test_risk_status_uses_existing_position_and_risk_engine_math():
    source = (ROOT / "backend" / "api" / "risk_routes.py").read_text(encoding="utf-8")

    assert "PositionsRepository" in source
    assert "build_portfolio_snapshot" in source
    assert "calculate_metrics" in source
    assert 'metrics.get("gross_leverage"' in source
    assert 'metrics.get("margin_utilization"' in source
    assert "current_leverage=0.0" not in source
    assert "margin_usage=0.0" not in source


def test_frontend_alignment_does_not_add_orchestration_infrastructure():
    assert not (ROOT / "docker-compose.yml").exists()
    assert not (ROOT / "docker-compose.yaml").exists()
    assert not (ROOT / "kubernetes").exists()
    assert not (ROOT / "k8s").exists()
