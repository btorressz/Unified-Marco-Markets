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
        ingest_run_id=None,
        source_id: str | None = None,
        provenance=None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO market_ticks (symbol, venue, price, confidence, ts)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id, symbol, venue, price, confidence, ts""",
                (symbol, venue, price, confidence, ts or datetime.now(timezone.utc)),
            )
            self._record_provenance(row, "market_tick", ingest_run_id, source_id, provenance)
            return row
        except Exception:
            logger.error("Failed to save market tick", exc_info=True)
            return None

    def save_funding_tick(
        self,
        venue: str,
        market: str,
        funding_rate: float,
        ts: datetime | None = None,
        ingest_run_id=None,
        source_id: str | None = None,
        provenance=None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO funding_ticks (venue, market, funding_rate, ts)
                   VALUES (%s, %s, %s, %s) RETURNING id, venue, market, funding_rate, ts""",
                (venue, market, funding_rate, ts or datetime.now(timezone.utc)),
            )
            self._record_provenance(row, "funding_tick", ingest_run_id, source_id, provenance)
            return row
        except Exception:
            logger.error("Failed to save funding tick", exc_info=True)
            return None

    @staticmethod
    def _record_provenance(row, artifact_type, ingest_run_id, source_id, provenance):
        if not row or not source_id or not (ingest_run_id or provenance):
            return
        try:
            from backend.data.repositories.ingest_repo import IngestRepository
            context = provenance
            IngestRepository().record_provenance(
                ingest_run_id or getattr(context, "run_id", None), source_id, artifact_type,
                artifact_id=row.get("id"), provider_timestamp=getattr(context, "provider_timestamp", None),
                received_at=getattr(context, "received_at", None), fallback_used=getattr(context, "fallback_used", False),
                fallback_source_id=getattr(context, "fallback_source_id", None),
            )
        except Exception:
            logger.warning("Failed to record %s provenance", artifact_type, exc_info=True)

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
