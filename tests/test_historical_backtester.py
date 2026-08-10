from datetime import datetime, timedelta, timezone

import pytest

from backend.compute.backtester import run_backtest
from backend.core.position_ledger import PositionLedger


def _ts(minutes: int) -> str:
    return (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _bundle(prices=None, funding=None, fills=None):
    return {
        "market_ticks": prices or [],
        "funding_ticks": funding or [],
        "index_history": [],
        "stablecoin_ticks": [],
        "regime_snapshots": [],
        "events": [],
        "orders": [],
        "fills": fills or [],
    }


def test_default_mode_remains_synthetic():
    result = run_backtest({"window_days": 5, "initial_capital": 10000})
    assert result["mode"] == "synthetic"
    assert result["data_mode"] == "synthetic_research_simulation"
    assert result["data_manifest"]["synthetic_price_steps"] == 6


def test_historical_mode_never_silently_falls_back_to_synthetic():
    with pytest.raises(ValueError, match="No historical market_ticks"):
        run_backtest(
            {
                "mode": "historical",
                "venue": "hyperliquid",
                "market": "SOL-PERP",
                "symbol": "SOL_USD",
            },
            historical_data=_bundle(),
        )


def test_position_ledger_applies_funding_without_changing_size():
    ledger = PositionLedger()
    ledger.apply_fill(
        venue="hyperliquid",
        market="SOL-PERP",
        side="buy",
        size=2,
        price=100,
    )
    before = ledger.get_positions()[0]
    updated = ledger.apply_funding("hyperliquid", "SOL-PERP", -3.5)
    totals = ledger.get_account_totals()

    assert updated is not None
    assert updated["size"] == before["size"] == 2
    assert updated["entry_price"] == before["entry_price"] == 100
    assert totals["funding"] == -3.5
    assert totals["realized_pnl"] == -3.5


def test_historical_decision_fills_on_later_tick_not_signal_tick():
    prices = [
        {"id": 1, "venue": "hyperliquid", "symbol": "SOL_USD", "price": 100.0, "confidence": 1.0, "ts": _ts(0)},
        {"id": 2, "venue": "hyperliquid", "symbol": "SOL_USD", "price": 101.0, "confidence": 1.0, "ts": _ts(1)},
        {"id": 3, "venue": "hyperliquid", "symbol": "SOL_USD", "price": 102.0, "confidence": 1.0, "ts": _ts(2)},
    ]
    result = run_backtest(
        {
            "mode": "historical",
            "strategy": "buy_hold",
            "venue": "hyperliquid",
            "market": "SOL-PERP",
            "symbol": "SOL_USD",
            "latency_ms": 0,
            "decision_interval_seconds": 0,
            "slippage_bps": 0,
            "taker_fee_bps": 0,
            "close_at_end": False,
        },
        historical_data=_bundle(prices=prices),
    )

    assert result["fill_count"] == 1
    fill = result["fills"][0]
    assert fill["signal_ts"] == _ts(0)
    assert fill["ts"] == _ts(1)
    assert fill["observed_price"] == 101.0
    assert result["look_ahead_guard"]["enabled"] is True


def test_historical_funding_uses_signed_position_direction():
    prices = [
        {"id": 1, "venue": "hyperliquid", "symbol": "SOL_USD", "price": 100.0, "confidence": 1.0, "ts": _ts(0)},
        {"id": 2, "venue": "hyperliquid", "symbol": "SOL_USD", "price": 100.0, "confidence": 1.0, "ts": _ts(1)},
        {"id": 3, "venue": "hyperliquid", "symbol": "SOL_USD", "price": 100.0, "confidence": 1.0, "ts": _ts(3)},
    ]
    funding = [
        {"id": 1, "venue": "hyperliquid", "market": "SOL-PERP", "funding_rate": 0.01, "ts": _ts(2)},
    ]
    result = run_backtest(
        {
            "mode": "historical",
            "strategy": "buy_hold",
            "venue": "hyperliquid",
            "market": "SOL-PERP",
            "symbol": "SOL_USD",
            "initial_capital": 10000,
            "allocation_limit": 0.5,
            "latency_ms": 0,
            "slippage_bps": 0,
            "taker_fee_bps": 0,
            "close_at_end": False,
        },
        historical_data=_bundle(prices=prices, funding=funding),
    )

    assert result["funding_pnl"] < 0
    assert result["final_capital"] < 10000


def test_recorded_orders_replays_persisted_fill_economics():
    prices = [
        {"id": 1, "venue": "paper", "symbol": "SOL_USD", "price": 100.0, "confidence": 1.0, "ts": _ts(0)},
        {"id": 2, "venue": "paper", "symbol": "SOL_USD", "price": 120.0, "confidence": 1.0, "ts": _ts(3)},
    ]
    fills = [
        {"id": "a", "venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 1.0, "price": 100.0, "fee": 1.0, "funding": 0.0, "slippage": 0.5, "ts": _ts(1)},
        {"id": "b", "venue": "paper", "market": "SOL-PERP", "side": "sell", "size": 1.0, "price": 120.0, "fee": 1.0, "funding": 0.0, "slippage": 0.5, "ts": _ts(2)},
    ]
    result = run_backtest(
        {
            "mode": "historical",
            "strategy": "recorded_orders",
            "venue": "paper",
            "market": "SOL-PERP",
            "symbol": "SOL_USD",
            "initial_capital": 10000,
        },
        historical_data=_bundle(prices=prices, fills=fills),
    )

    assert result["fill_count"] == 2
    assert result["fees_paid"] == 2.0
    assert result["slippage_cost"] == 1.0
    assert result["realized_pnl"] == 17.0
    assert result["final_capital"] == 10017.0


def test_walk_forward_windows_are_evaluation_only_and_deterministic():
    prices = []
    for day in range(15):
        prices.append({
            "id": day + 1,
            "venue": "hyperliquid",
            "symbol": "SOL_USD",
            "price": 100.0 + day,
            "confidence": 1.0,
            "ts": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day)).isoformat(),
        })
    result = run_backtest(
        {
            "mode": "historical",
            "strategy": "buy_hold",
            "venue": "hyperliquid",
            "market": "SOL-PERP",
            "symbol": "SOL_USD",
            "latency_ms": 0,
            "slippage_bps": 0,
            "taker_fee_bps": 0,
            "close_at_end": False,
            "walk_forward": True,
            "train_window_days": 5,
            "test_window_days": 3,
            "step_days": 3,
        },
        historical_data=_bundle(prices=prices),
    )

    assert result["walk_forward_windows"]
    first = result["walk_forward_windows"][0]
    assert "train_start" in first
    assert "test_return_pct" in first
