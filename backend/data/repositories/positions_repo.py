import logging
from datetime import datetime, timezone

from backend.data.db import execute_query, execute_returning

logger = logging.getLogger(__name__)


class PositionsRepository:

    def save_position(
        self,
        venue: str,
        market: str,
        size: float,
        entry_price: float,
        pnl: float = 0.0,
        margin: float = 0.0,
        liq_price: float | None = None,
        order_id: str | None = None,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
        fees: float = 0.0,
        funding: float = 0.0,
        slippage: float = 0.0,
    ) -> dict | None:
        try:
            return execute_returning(
                """INSERT INTO positions (
                       venue, market, size, entry_price, pnl, margin, liq_price,
                       order_id, realized_pnl, unrealized_pnl, fees, funding,
                       slippage, ts, updated_at
                   ) VALUES (
                       %s, %s, %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s, %s
                   )
                   RETURNING id, venue, market, size, entry_price, pnl, margin,
                             liq_price, order_id, realized_pnl, unrealized_pnl,
                             fees, funding, slippage, ts, updated_at""",
                (
                    venue,
                    market,
                    size,
                    entry_price,
                    pnl,
                    margin,
                    liq_price,
                    order_id,
                    realized_pnl,
                    unrealized_pnl,
                    fees,
                    funding,
                    slippage,
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc),
                ),
            )
        except Exception:
            logger.error("Failed to save position", exc_info=True)
            return None

    def get_all(self) -> list[dict]:
        try:
            return execute_query(
                """SELECT DISTINCT ON (venue, market)
                          id, venue, market, size, entry_price, pnl, margin,
                          liq_price, order_id, realized_pnl, unrealized_pnl,
                          fees, funding, slippage, ts, updated_at
                   FROM positions
                   ORDER BY venue, market, ts DESC"""
            )
        except Exception:
            logger.error("Failed to get positions", exc_info=True)
            return []

    def save_paper_trade(
        self,
        venue: str,
        market: str,
        side: str,
        size: float,
        price: float,
        order_type: str = "limit",
        status: str = "paper_filled",
    ) -> dict | None:
        """Legacy compatibility writer.

        New execution paths use OrdersRepository + paper_orders. This method is
        retained for older callers and existing deployments during migration.
        """
        try:
            return execute_returning(
                """INSERT INTO paper_trades (venue, market, side, size, price, order_type, status, ts)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, venue, market, side, size, price, order_type, status, ts""",
                (venue, market, side, size, price, order_type, status, datetime.now(timezone.utc)),
            )
        except Exception:
            logger.error("Failed to save paper trade", exc_info=True)
            return None

    def get_paper_trades(self, limit: int = 50) -> list[dict]:
        """Legacy compatibility reader for pre-PR #7 paper-trade history."""
        try:
            return execute_query(
                "SELECT id, venue, market, side, size, price, order_type, status, ts FROM paper_trades ORDER BY ts DESC LIMIT %s",
                (limit,),
            )
        except Exception:
            logger.error("Failed to get paper trades", exc_info=True)
            return []
