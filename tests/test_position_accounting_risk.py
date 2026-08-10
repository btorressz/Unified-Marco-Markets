import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from backend.api.execution_routes import OrderRequest, _validate_order_request
from backend.compute.risk_engine import RiskEngine
from backend.core.event_bus import EventBus
from backend.core.position_ledger import PositionLedger
from backend.execution.paper_exec import PaperExecutor
from backend.execution.router import ExecutionRouter


def test_partial_long_reduction_preserves_entry_and_realizes_pnl():
    ledger = PositionLedger()
    ledger.apply_fill(venue="paper", market="BTC-PERP", side="buy", size=10.0, price=100.0)

    result = ledger.apply_fill(
        venue="paper", market="BTC-PERP", side="sell", size=4.0, price=120.0
    )
    position = ledger.get_positions()[0]

    assert result["closing_quantity"] == 4.0
    assert result["opening_quantity"] == 0.0
    assert result["gross_realized_pnl"] == pytest.approx(80.0)
    assert position["size"] == pytest.approx(6.0)
    assert position["entry_price"] == pytest.approx(100.0)


def test_long_to_short_flip_realizes_closed_leg_and_reopens_at_fill_price():
    ledger = PositionLedger()
    ledger.apply_fill(venue="paper", market="BTC-PERP", side="buy", size=10.0, price=100.0)

    result = ledger.apply_fill(
        venue="paper", market="BTC-PERP", side="sell", size=15.0, price=120.0
    )
    position = ledger.get_positions()[0]

    assert result["closing_quantity"] == 10.0
    assert result["opening_quantity"] == 5.0
    assert result["flipped"] is True
    assert result["gross_realized_pnl"] == pytest.approx(200.0)
    assert position["size"] == pytest.approx(-5.0)
    assert position["entry_price"] == pytest.approx(120.0)


def test_short_reduction_and_flip_are_symmetric():
    ledger = PositionLedger()
    ledger.apply_fill(venue="paper", market="ETH-PERP", side="sell", size=5.0, price=200.0)

    reduce_result = ledger.apply_fill(
        venue="paper", market="ETH-PERP", side="buy", size=2.0, price=180.0
    )
    position = ledger.get_positions()[0]
    assert reduce_result["gross_realized_pnl"] == pytest.approx(40.0)
    assert position["size"] == pytest.approx(-3.0)
    assert position["entry_price"] == pytest.approx(200.0)

    flip_result = ledger.apply_fill(
        venue="paper", market="ETH-PERP", side="buy", size=5.0, price=170.0
    )
    position = ledger.get_positions()[0]
    assert flip_result["gross_realized_pnl"] == pytest.approx(90.0)
    assert position["size"] == pytest.approx(2.0)
    assert position["entry_price"] == pytest.approx(170.0)


def test_mark_to_market_updates_unrealized_pnl():
    ledger = PositionLedger()
    ledger.apply_fill(venue="paper", market="SOL-PERP", side="buy", size=2.0, price=100.0)

    position = ledger.mark_to_market("paper", "SOL-PERP", 115.0)

    assert position is not None
    assert position["unrealized_pnl"] == pytest.approx(30.0)
    assert ledger.get_account_totals()["unrealized_pnl"] == pytest.approx(30.0)


def test_fees_funding_and_slippage_are_accounted_separately():
    ledger = PositionLedger()
    result = ledger.apply_fill(
        venue="paper",
        market="SOL-PERP",
        side="buy",
        size=1.0,
        price=100.0,
        fee=1.0,
        funding=0.25,
        slippage=0.5,
    )
    totals = ledger.get_account_totals()

    assert result["realized_pnl"] == pytest.approx(-1.25)
    assert totals["fees"] == pytest.approx(1.0)
    assert totals["funding"] == pytest.approx(0.25)
    assert totals["slippage"] == pytest.approx(0.5)
    assert totals["realized_pnl"] == pytest.approx(-1.25)


def test_paper_executor_delegates_accounting_without_breaking_position_shape():
    executor = PaperExecutor(event_bus=MagicMock(spec=EventBus))
    executor.place_order(venue="paper", market="SOL-PERP", side="buy", size=2.0, price=100.0)
    result = executor.place_order(
        venue="paper", market="SOL-PERP", side="sell", size=1.0, price=110.0
    )
    position = executor.get_positions()[0]

    assert result["realized_pnl"] == pytest.approx(10.0)
    assert position["size"] == pytest.approx(1.0)
    assert position["entry_price"] == pytest.approx(100.0)
    for field in ("venue", "market", "side", "pnl", "margin"):
        assert field in position


def test_portfolio_snapshot_uses_account_equity_not_margin_as_equity():
    engine = RiskEngine(max_leverage=3.0, max_margin_pct=0.6)
    positions = [
        {
            "venue": "paper",
            "market": "BTC-PERP",
            "size": 1.0,
            "entry_price": 100.0,
            "mark_price": 110.0,
            "margin": 20.0,
            "unrealized_pnl": 10.0,
        }
    ]
    snapshot = engine.build_portfolio_snapshot(
        positions,
        account={
            "cash": 500.0,
            "collateral": 500.0,
            "realized_pnl": 50.0,
            "unrealized_pnl": 10.0,
            "maintenance_margin": 100.0,
            "open_order_exposure": 100.0,
        },
    )
    metrics = engine.calculate_metrics(snapshot)

    assert snapshot.equity == pytest.approx(1060.0)
    assert metrics["gross_leverage"] == pytest.approx(210.0 / 1060.0)
    assert metrics["net_leverage"] == pytest.approx(110.0 / 1060.0)
    assert metrics["margin_utilization"] == pytest.approx(20.0 / 1060.0)
    assert metrics["liquidation_buffer"] == pytest.approx(960.0)


def test_portfolio_metrics_calculate_asset_and_venue_concentration():
    engine = RiskEngine()
    positions = [
        {"venue": "paper", "market": "BTC-PERP", "size": 2.0, "entry_price": 100.0},
        {"venue": "drift", "market": "ETH-PERP", "size": 1.0, "entry_price": 100.0},
    ]
    snapshot = engine.build_portfolio_snapshot(
        positions,
        account={"cash": 1000.0, "collateral": 0.0},
    )
    metrics = engine.calculate_metrics(snapshot)

    assert snapshot.gross_exposure == pytest.approx(300.0)
    assert metrics["asset_concentration"] == pytest.approx(2.0 / 3.0)
    assert metrics["venue_concentration"] == pytest.approx(2.0 / 3.0)


def test_position_only_risk_call_remains_backward_compatible():
    engine = RiskEngine(max_leverage=3.0, max_margin_pct=0.6, cooldown_seconds=0)
    positions = [
        {
            "venue": "paper",
            "market": "SOL-PERP",
            "size": 2.0,
            "entry_price": 150.0,
            "margin": 100.0,
        }
    ]
    proposed = {
        "venue": "paper",
        "market": "SOL-PERP",
        "side": "sell",
        "size": 1.0,
        "price": 150.0,
    }

    allowed, reasons = engine.check_constraints(positions, proposed, execution_mode="paper")

    assert allowed is True
    assert reasons == []


def test_order_validation_rejects_unsupported_market_explicitly():
    request = OrderRequest(
        venue="paper", market="NOT-A-MARKET", side="buy", size=1.0, price=100.0
    )

    with pytest.raises(HTTPException) as exc:
        _validate_order_request(request)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "unsupported_market"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"venue": "unknown", "market": "SOL-PERP", "side": "buy", "size": 1.0, "price": 100.0}, "unsupported_venue"),
        ({"venue": "paper", "market": "SOL-PERP", "side": "hold", "size": 1.0, "price": 100.0}, "unsupported_side"),
        ({"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 1.0, "price": 100.0, "order_type": "iceberg"}, "unsupported_order_type"),
        ({"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 0.0, "price": 100.0}, "invalid_size"),
        ({"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 1.0, "price": 0.0}, "invalid_price"),
        ({"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 1.0, "price": 100.0, "slippage_bps": 501.0}, "invalid_slippage"),
        ({"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 10001.0, "price": 100.0}, "max_notional_exceeded"),
    ],
)
def test_order_validation_rejects_invalid_execution_requests(payload, code):
    request = OrderRequest(**payload)

    with pytest.raises(HTTPException) as exc:
        _validate_order_request(request)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == code


def test_router_rejects_unknown_market_before_price_lookup(monkeypatch):
    router = ExecutionRouter(event_bus=MagicMock(spec=EventBus))
    called = False

    def fail_if_called(_market):
        nonlocal called
        called = True
        raise AssertionError("price lookup should not run for unsupported market")

    monkeypatch.setattr(router, "_get_live_price", fail_if_called)
    result = router.route_order("paper", "NOT-A-MARKET", "buy", 1.0, price=100.0)

    assert result["status"] == "blocked"
    assert any("unsupported_market" in reason for reason in result["reasons"])
    assert called is False
