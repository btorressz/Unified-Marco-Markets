from pathlib import Path

import pytest

from backend.compute.execution_decision import evaluate_data_guardrails
from backend.compute.risk_engine import RiskEngine
from backend.execution.hyperliquid_exec import _asset_index
from backend.execution.drift_exec import _market_index
from backend.execution.router import ExecutionRouter
from backend.execution.solana_tx import SolanaTxHelper


class _AllowExecutionAgent:
    def pre_trade_check(self, proposed, market_state):
        return {"allowed": True, "reasons": []}


class _RaisingExecutor:
    enabled = True

    def place_order(self, **kwargs):
        raise TimeoutError("submission response lost")


class _LivePositions:
    enabled = True

    def get_positions(self):
        return [
            {
                "venue": "hyperliquid",
                "market": "BTC-PERP",
                "size": 0.25,
                "entry_price": 50000.0,
                "margin": 5000.0,
            }
        ]


def _configure_live_router(router: ExecutionRouter) -> None:
    router.mode = "live"
    router.live_execution_enabled = True
    router._exec_agent = _AllowExecutionAgent()
    router._get_live_price = lambda market: {
        "price": 100.0,
        "source": "test",
        "ts": "2026-08-10T00:00:00+00:00",
        "age_s": 0.0,
        "fresh": True,
        "found": True,
    }
    router._get_data_context = lambda live_price=None, order_context=None: {
        "execution_mode": "live",
        "integrity_status": "OK",
        **(order_context or {}),
    }
    router._get_market_state = lambda market=None: {"price_integrity": "OK"}


def test_live_data_guardrail_blocks_unknown_integrity():
    result = evaluate_data_guardrails(
        {
            "execution_mode": "live",
            "live_execution_enabled": True,
            "validation_reasons": [],
            "price_found": True,
            "fill_price": 100.0,
            "order_notional": 100.0,
            "max_order_notional": 1000.0,
            "price_fresh": True,
            "integrity_status": "UNKNOWN",
            "price_integrity_block_live": True,
        }
    )

    assert result["allowed"] is False
    assert result["stage"] == "price_integrity"
    assert "requires OK" in result["reasons"][0]


def test_live_router_blocks_unknown_integrity_before_executor():
    router = ExecutionRouter()
    _configure_live_router(router)
    router._get_data_context = lambda live_price=None, order_context=None: {
        "execution_mode": "live",
        "integrity_status": "UNKNOWN",
        **(order_context or {}),
    }
    router._get_risk_positions = lambda: []
    router._get_live_executor = lambda venue: _RaisingExecutor()

    result = router.route_order("hyperliquid", "BTC-PERP", "buy", 0.001, price=100.0)

    assert result["status"] == "blocked"
    assert "requires OK" in result["reasons"][0]
    assert router.paper.get_positions() == []


def test_live_execution_hard_gate_blocks_before_submission():
    router = ExecutionRouter()
    router.mode = "live"
    router.live_execution_enabled = False

    result = router.route_order("hyperliquid", "BTC-PERP", "buy", 0.01, price=100.0)

    assert result["status"] == "blocked"
    assert result["live_execution_enabled"] is False
    assert router.paper.get_positions() == []


def test_live_risk_positions_include_enabled_live_venue_positions():
    router = ExecutionRouter()
    router.mode = "live"
    router.live_execution_enabled = True
    router.hyperliquid = _LivePositions()
    router.drift = None

    positions = router._get_risk_positions()

    assert any(p.get("venue") == "hyperliquid" for p in positions)


def test_oversized_reduce_that_flips_is_not_risk_bypassed():
    engine = RiskEngine(max_leverage=100.0, max_margin_pct=100.0, cooldown_seconds=0)
    engine.activate_throttle("risk-off")
    positions = [
        {
            "venue": "paper",
            "market": "BTC-PERP",
            "size": 1.0,
            "entry_price": 100.0,
            "margin": 100.0,
        }
    ]

    allowed, reasons = engine.check_constraints(
        positions,
        {
            "venue": "paper",
            "market": "BTC-PERP",
            "side": "sell",
            "size": 5.0,
            "price": 100.0,
        },
    )

    assert allowed is False
    assert any("Throttle" in reason for reason in reasons)


def test_partial_reduce_still_bypasses_new_exposure_controls():
    engine = RiskEngine(max_leverage=0.1, max_margin_pct=0.01, cooldown_seconds=300)
    engine.activate_throttle("risk-off")
    engine.daily_pnl = -10000.0
    positions = [
        {
            "venue": "paper",
            "market": "BTC-PERP",
            "size": 1.0,
            "entry_price": 100.0,
            "margin": 100.0,
        }
    ]

    allowed, reasons = engine.check_constraints(
        positions,
        {
            "venue": "paper",
            "market": "BTC-PERP",
            "side": "sell",
            "size": 0.5,
            "price": 100.0,
        },
        execution_mode="live",
    )

    assert allowed is True
    assert reasons == []


def test_missing_live_executor_never_falls_back_to_paper():
    router = ExecutionRouter()
    _configure_live_router(router)
    router._get_risk_positions = lambda: []
    router._get_live_executor = lambda venue: None

    result = router.route_order("hyperliquid", "BTC-PERP", "buy", 0.001, price=100.0)

    assert result["status"] == "blocked"
    assert "paper_fallback" not in str(result)
    assert router.paper.get_positions() == []


def test_uncertain_live_submission_never_creates_paper_fill():
    router = ExecutionRouter()
    _configure_live_router(router)
    router._get_risk_positions = lambda: []
    router._get_live_executor = lambda venue: _RaisingExecutor()

    result = router.route_order(
        "hyperliquid",
        "BTC-PERP",
        "buy",
        0.001,
        price=100.0,
        order_context={"client_order_id": "cid-1"},
    )

    assert result["status"] == "execution_state_unknown"
    assert result["requires_reconciliation"] is True
    assert result["client_order_id"] == "cid-1"
    assert router.paper.get_positions() == []


def test_unknown_hyperliquid_market_does_not_default_to_btc():
    with pytest.raises(ValueError):
        _asset_index("NOT-A-MARKET-PERP")


def test_unknown_drift_market_does_not_default_to_sol():
    with pytest.raises(ValueError):
        _market_index("NOT-A-MARKET-PERP")


def test_solana_helper_refuses_to_claim_unsigned_transaction_is_signed():
    helper = SolanaTxHelper(rpc_url="http://example.invalid")

    result = helper.sign_and_send(b"unsigned-transaction")

    assert result == "error:transaction_signing_not_implemented"


def test_events_migration_uses_uuid_primary_key():
    migration = (Path(__file__).parents[1] / "backend" / "data" / "migrations.sql").read_text()

    assert "id UUID PRIMARY KEY DEFAULT gen_random_uuid()" in migration
    assert "ALTER TABLE events ALTER COLUMN id TYPE UUID" in migration
