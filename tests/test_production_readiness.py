from pathlib import Path

from backend import config
from backend.core import readiness


def _ok_checks(monkeypatch):
    monkeypatch.setattr(readiness, "_database_check", lambda: {"status": "ok", "blocking_live": False})
    monkeypatch.setattr(readiness, "_schema_check", lambda: {"status": "ok", "blocking_live": False})
    monkeypatch.setattr(readiness, "_redis_check", lambda: {"status": "ok", "blocking_live": False})
    monkeypatch.setattr(readiness, "_market_data_check", lambda: {"status": "ok", "blocking_live": False})
    monkeypatch.setattr(readiness, "_ingestion_check", lambda: {"status": "ok", "blocking_live": False})
    monkeypatch.setattr(readiness, "_risk_runtime_check", lambda: {"status": "ok", "blocking_live": False})
    monkeypatch.setattr(readiness, "_execution_config_check", lambda: {"status": "ok", "blocking_live": False})


def test_paper_mode_can_remain_ready_while_degraded(monkeypatch):
    _ok_checks(monkeypatch)
    monkeypatch.setattr(config, "EXECUTION_MODE", "paper")
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", False)
    monkeypatch.setattr(readiness, "_database_check", lambda: {"status": "error", "blocking_live": True})

    result = readiness.build_readiness()

    assert result["ready"] is True
    assert result["status"] == "degraded"
    assert result["blocking_checks"] == []
    assert any(item["component"] == "database" for item in result["degraded"])


def test_live_mode_blocks_on_database_schema_redis_market_and_risk(monkeypatch):
    _ok_checks(monkeypatch)
    monkeypatch.setattr(config, "EXECUTION_MODE", "live")
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", True)
    for name in ("database", "schema", "redis", "market_data", "risk_runtime"):
        monkeypatch.setattr(readiness, f"_{name}_check", lambda: {"status": "error", "blocking_live": True})

    result = readiness.build_readiness()

    assert result["ready"] is False
    assert result["status"] == "not_ready"
    assert set(result["blocking_checks"]) == {"database", "schema", "redis", "market_data", "risk_runtime"}


def test_research_ingestion_degradation_is_non_blocking_in_live_mode(monkeypatch):
    _ok_checks(monkeypatch)
    monkeypatch.setattr(config, "EXECUTION_MODE", "live")
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", True)
    monkeypatch.setattr(readiness, "_ingestion_check", lambda: {"status": "degraded", "blocking_live": False})

    result = readiness.build_readiness()

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert any(item["component"] == "ingestion" for item in result["degraded"])


def test_execution_config_requires_operator_token_for_live(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_MODE", "live")
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", True)
    monkeypatch.setattr(config, "OPERATOR_AUTH_REQUIRED", False)
    monkeypatch.setattr(config, "OPERATOR_API_TOKEN", "")
    monkeypatch.setattr(config, "SUPPORTED_EXECUTION_VENUES", ["paper", "hyperliquid"])
    monkeypatch.setattr(config, "SUPPORTED_EXECUTION_MARKETS", ["SOL-PERP"])
    monkeypatch.setattr(readiness, "_live_executor_capabilities", lambda: {"hyperliquid": True, "drift": False})

    result = readiness._execution_config_check()

    assert result["status"] == "error"
    assert result["blocking_live"] is True
    assert "operator token is not configured" in result["problems"]


def test_execution_config_rejects_no_production_ready_live_executor(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_MODE", "live")
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", True)
    monkeypatch.setattr(config, "OPERATOR_AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "OPERATOR_API_TOKEN", "configured")
    monkeypatch.setattr(config, "SUPPORTED_EXECUTION_VENUES", ["paper", "hyperliquid", "drift"])
    monkeypatch.setattr(config, "SUPPORTED_EXECUTION_MARKETS", ["SOL-PERP"])
    monkeypatch.setattr(readiness, "_live_executor_capabilities", lambda: {"hyperliquid": False, "drift": False})

    result = readiness._execution_config_check()

    assert result["status"] == "error"
    assert "no configured live executor is production-ready" in result["problems"]


def test_live_execution_enabled_requires_live_mode(monkeypatch):
    monkeypatch.setattr(config, "EXECUTION_MODE", "paper")
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", True)
    monkeypatch.setattr(config, "OPERATOR_AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "OPERATOR_API_TOKEN", "configured")
    monkeypatch.setattr(config, "SUPPORTED_EXECUTION_VENUES", ["paper", "hyperliquid"])
    monkeypatch.setattr(config, "SUPPORTED_EXECUTION_MARKETS", ["SOL-PERP"])
    monkeypatch.setattr(readiness, "_live_executor_capabilities", lambda: {"hyperliquid": True, "drift": False})

    result = readiness._execution_config_check()

    assert "LIVE_EXECUTION_ENABLED requires EXECUTION_MODE=live" in result["problems"]


def test_required_live_schema_is_small_and_execution_specific():
    assert set(readiness._REQUIRED_LIVE_TABLES) == {"order_intents", "orders", "fills", "positions", "decision_audit"}


def test_root_and_health_probe_routes_are_wired():
    health = (Path(__file__).parents[1] / "backend" / "api" / "health_routes.py").read_text()
    main = (Path(__file__).parents[1] / "main.py").read_text()

    assert '@probe_router.get("/live")' in health
    assert '@probe_router.get("/ready")' in health
    assert '@router.get("/live")' in health
    assert '@router.get("/ready")' in health
    assert "health_probe_router" in main


def test_no_github_actions_or_yaml_added_for_readiness():
    root = Path(__file__).parents[1]
    assert not (root / ".github" / "workflows" / "production-readiness.yml").exists()
    assert not (root / ".github" / "workflows" / "production-readiness.yaml").exists()


def test_market_data_readiness_requires_scoped_btc_eth_sol_integrity(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    now = datetime.now(timezone.utc)

    class Authority:
        def get_price(self, symbol):
            return SimpleNamespace(found=True, source="pyth", price=100.0, ts=now)

        def get_all_venues(self, symbol):
            return [{"venue": "pyth", "price": 100.0, "ts": now.isoformat()}]

    class Store:
        def __init__(self):
            self.values = {"price:integrity:SOL_USD": {"status": "OK"}}

        def get_snapshot(self, key):
            return self.values.get(key)

    monkeypatch.setattr(readiness, "PriceAuthority", Authority)
    monkeypatch.setattr(readiness, "StateStore", Store)

    result = readiness._market_data_check()

    assert result["monitored_symbols"] == ["BTC/USD", "ETH/USD", "SOL/USD"]
    assert result["symbols"]["BTC/USD"]["integrity_status"] == "UNKNOWN"
    assert result["symbols"]["ETH/USD"]["integrity_status"] == "UNKNOWN"
    assert result["symbols"]["SOL/USD"]["integrity_status"] == "OK"
    assert result["blocking_live"] is True
