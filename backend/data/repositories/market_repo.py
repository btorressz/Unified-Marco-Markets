import json
import logging
from datetime import datetime, timezone

from backend.data.db import execute_query, execute_returning

logger = logging.getLogger(__name__)


class MarketRepository:

    def save_tick(
        self,
        symbol: str,
        venue: str,
        price: float,
        confidence: float = 1.0,
        ts: datetime | None = None,
    ) -> dict | None:
        try:
            return execute_returning(
                """INSERT INTO market_ticks (symbol, venue, price, confidence, ts)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id, symbol, venue, price, confidence, ts""",
                (symbol, venue, price, confidence, ts or datetime.now(timezone.utc)),
            )
        except Exception:
            logger.error("Failed to save market tick", exc_info=True)
            return None

    def save_funding_tick(
        self,
        venue: str,
        market: str,
        funding_rate: float,
        ts: datetime | None = None,
    ) -> dict | None:
        try:
            return execute_returning(
                """INSERT INTO funding_ticks (venue, market, funding_rate, ts)
                   VALUES (%s, %s, %s, %s) RETURNING id, venue, market, funding_rate, ts""",
                (venue, market, funding_rate, ts or datetime.now(timezone.utc)),
            )
        except Exception:
            logger.error("Failed to save funding tick", exc_info=True)
            return None

    def get_latest_by_venue(self, venue: str) -> list[dict]:
        try:
            return execute_query(
                """SELECT DISTINCT ON (symbol) id, symbol, venue, price, confidence, ts
                   FROM market_ticks
                   WHERE venue = %s
                   ORDER BY symbol, ts DESC""",
                (venue,),
            )
        except Exception:
            logger.error("Failed to get latest by venue", exc_info=True)
            return []

    def get_all_latest(self) -> list[dict]:
        try:
            return execute_query(
                """SELECT DISTINCT ON (venue, symbol) id, symbol, venue, price, confidence, ts
                   FROM market_ticks
                   ORDER BY venue, symbol, ts DESC"""
            )
        except Exception:
            logger.error("Failed to get all latest ticks", exc_info=True)
            return []

    def get_history(self, venue: str, window_seconds: int = 3600) -> list[dict]:
        try:
            return execute_query(
                """SELECT id, symbol, venue, price, confidence, ts
                   FROM market_ticks
                   WHERE venue = %s AND ts >= NOW() - INTERVAL '%s seconds'
                   ORDER BY ts ASC""",
                (venue, window_seconds),
            )
        except Exception:
            logger.error("Failed to get market history", exc_info=True)
            return []

    def get_latest_funding(self) -> list[dict]:
        try:
            return execute_query(
                """SELECT DISTINCT ON (venue, market) id, venue, market, funding_rate, ts
                   FROM funding_ticks
                   ORDER BY venue, market, ts DESC"""
            )
        except Exception:
            logger.error("Failed to get latest funding", exc_info=True)
            return []
