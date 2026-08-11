import uuid
import logging
from datetime import datetime, timezone

from backend.core.event_bus import EventBus, EventType
from backend.core.models import PositionState
from backend.core.position_ledger import PositionLedger
from backend.compute.risk_engine import RiskEngine

logger = logging.getLogger(__name__)


class PaperExecutor:

    def __init__(self, event_bus: EventBus | None = None, risk_engine: RiskEngine | None = None):
        self.event_bus = event_bus or EventBus()
        self.risk_engine = risk_engine or RiskEngine()
        self._ledger = PositionLedger()
        self._positions = self._ledger._positions
        self._orders: dict[str, dict] = {}
        self.enabled = True
        logger.info("PaperExecutor initialised (paper mode)")

    def place_order(
        self,
        venue: str,
        market: str,
        side: str,
        size: float,
        order_type: str = "limit",
        price: float | None = None,
        data_context: dict | None = None,
        fee: float = 0.0,
        funding: float = 0.0,
        slippage: float = 0.0,
    ) -> dict:
        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        fill_price = price if price is not None and price > 0 else 0.0
        ctx = data_context or {}

        self.event_bus.emit(
            EventType.ORDER_SENT,
            source="paper_executor",
            payload={
                "order_id": order_id,
                "venue": venue,
                "market": market,
                "side": side,
                "size": size,
                "order_type": order_type,
                "price": fill_price,
                "tariff_ts": ctx.get("tariff_ts"),
                "shock_ts": ctx.get("shock_ts"),
                "price_ts": ctx.get("price_ts"),
                "price_source": ctx.get("price_source", "unknown"),
                "price_asof_ts": ctx.get("price_asof_ts"),
                "integrity_status": ctx.get("integrity_status", "OK"),
                "execution_mode": ctx.get("execution_mode", "paper"),
                "data_age_ms": ctx.get("data_age_ms"),
                "data_quality": ctx.get("data_quality", "OK"),
                "message": f"Paper {side.upper()} {size} {market} @ {fill_price:.4f}",
            },
        )

        accounting = self._ledger.apply_fill(
            venue=venue,
            market=market,
            side=side,
            size=size,
            price=fill_price,
            fee=fee,
            funding=funding,
            slippage=slippage,
        )

        realized_for_fill = float(accounting.get("realized_pnl", 0.0) or 0.0)
        if realized_for_fill != 0.0:
            self.risk_engine.record_pnl(realized_for_fill)

        self._orders[order_id] = {
            "order_id": order_id,
            "venue": venue,
            "market": market,
            "side": side,
            "size": size,
            "order_type": order_type,
            "price": fill_price,
            "status": "paper_filled",
            "fill_price": fill_price,
            "ts": now.isoformat(),
            "accounting": accounting,
        }

        self.event_bus.emit(
            EventType.ORDER_FILLED,
            source="paper_executor",
            payload={
                "order_id": order_id,
                "venue": venue,
                "market": market,
                "side": side,
                "size": size,
                "fill_price": fill_price,
                "realized_pnl": accounting["realized_pnl"],
                "gross_realized_pnl": accounting["gross_realized_pnl"],
                "unrealized_pnl": accounting["unrealized_pnl"],
                "fees": accounting["fees"],
                "funding": accounting["funding"],
                "slippage": accounting["slippage"],
                "tariff_ts": ctx.get("tariff_ts"),
                "shock_ts": ctx.get("shock_ts"),
                "price_ts": ctx.get("price_ts"),
                "price_source": ctx.get("price_source", "unknown"),
                "price_asof_ts": ctx.get("price_asof_ts"),
                "integrity_status": ctx.get("integrity_status", "OK"),
                "execution_mode": ctx.get("execution_mode", "paper"),
                "data_age_ms": ctx.get("data_age_ms"),
                "data_quality": ctx.get("data_quality", "OK"),
                "message": f"Paper {side.upper()} {size} {market} filled @ {fill_price:.4f}",
            },
        )

        logger.info(
            "Paper order filled: %s %s %s size=%.4f price=%.4f id=%s",
            venue, market, side, size, fill_price, order_id,
        )

        return {
            "order_id": order_id,
            "status": "paper_filled",
            "fill_price": fill_price,
            "side": side,
            "market": market,
            "venue": venue,
            "size": size,
            "realized_pnl": accounting["realized_pnl"],
            "unrealized_pnl": accounting["unrealized_pnl"],
            "accounting": accounting,
            "ts": now.isoformat(),
        }

    def cancel_order(self, order_id: str) -> dict:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            logger.info("Paper order cancelled: %s", order_id)
            return {"order_id": order_id, "status": "cancelled"}
        logger.warning("Paper cancel: order %s not found", order_id)
        return {"order_id": order_id, "status": "not_found"}

    def get_positions(self) -> list[dict]:
        results = []
        for pos in self._ledger.get_positions():
            size = pos["size"]
            side = "long" if size > 0 else "short"
            results.append(
                PositionState(
                    venue=pos["venue"],
                    market=pos["market"],
                    size=size,
                    entry_price=pos["entry_price"],
                    pnl=pos.get("unrealized_pnl", 0.0),
                    margin=pos.get("margin", 0.0),
                ).model_dump()
                | {
                    "side": side,
                    "mark_price": pos.get("mark_price", pos["entry_price"]),
                    "realized_pnl": pos.get("realized_pnl", 0.0),
                    "unrealized_pnl": pos.get("unrealized_pnl", 0.0),
                    "fees": pos.get("fees", 0.0),
                    "funding": pos.get("funding", 0.0),
                    "slippage": pos.get("slippage", 0.0),
                }
            )
        return results

    def get_account_totals(self) -> dict:
        return self._ledger.get_account_totals()

    def mark_to_market(self, venue: str, market: str, mark_price: float) -> dict | None:
        return self._ledger.mark_to_market(venue, market, mark_price)

    def _update_position(self, venue: str, market: str, side: str, size: float, price: float) -> None:
        """Compatibility shim for older internal tests/callers."""
        self._ledger.apply_fill(
            venue=venue,
            market=market,
            side=side,
            size=size,
            price=price,
        )
