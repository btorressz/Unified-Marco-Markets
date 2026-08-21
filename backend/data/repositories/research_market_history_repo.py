"""Bounded, immutable access to observed BTC/ETH/SOL research bars."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from backend.data.db import execute_query, get_connection, release_connection

SOURCE_ID = "yfinance_crypto_history_research"
PROVIDER = "Yahoo Finance"
INTERVAL_SECONDS = 300
SUPPORTED_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")
MAX_HISTORY_LIMIT = 10_000
_INSERT_COLUMNS = (
    "source_id", "provider", "symbol", "provider_symbol", "interval_seconds", "ts",
    "open", "high", "low", "close", "volume", "research_grade", "authoritative",
    "execution_eligible", "synthetic", "ingest_run_id", "retrieved_at",
)


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def normalize_bar(bar: dict[str, Any]) -> dict[str, Any] | None:
    """Reject malformed or synthetic provider observations without repair."""
    try:
        ts = _utc(bar.get("ts"))
        values = {key: float(bar[key]) for key in ("open", "high", "low", "close")}
        if any(not math.isfinite(value) or value <= 0 for value in values.values()):
            return None
        if values["high"] < max(values["open"], values["close"]):
            return None
        if values["low"] > min(values["open"], values["close"]):
            return None
        if values["high"] < values["low"] or bar.get("synthetic") is True:
            return None
        volume = bar.get("volume")
        if volume is not None:
            volume = int(volume)
            if volume < 0:
                return None
        return {**bar, **values, "ts": ts, "volume": volume}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


class ResearchMarketHistoryRepository:
    def insert_bars_idempotent(self, bars: list[dict[str, Any]], *, source_id: str = SOURCE_ID,
                               provider: str = PROVIDER, symbol: str, provider_symbol: str | None = None,
                               interval_seconds: int = INTERVAL_SECONDS, ingest_run_id=None,
                               retrieved_at: datetime | None = None, chunk_size: int = 1000) -> int:
        if symbol not in SUPPORTED_SYMBOLS or interval_seconds != INTERVAL_SECONDS:
            raise ValueError("unsupported research history contract")
        normalized = [row for bar in bars if (row := normalize_bar(bar)) is not None]
        if not normalized:
            return 0
        retrieved_at = retrieved_at or datetime.now(timezone.utc)
        inserted = 0
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for offset in range(0, len(normalized), max(1, min(chunk_size, 1000))):
                    values = [
                        (
                            source_id, provider, symbol, provider_symbol, interval_seconds, row["ts"],
                            row["open"], row["high"], row["low"], row["close"], row["volume"],
                            True, False, False, False, ingest_run_id, retrieved_at,
                        )
                        for row in normalized[offset:offset + chunk_size]
                    ]
                    psycopg2.extras.execute_values(
                        cur,
                        f"INSERT INTO research_market_bars ({','.join(_INSERT_COLUMNS)}) VALUES %s "
                        "ON CONFLICT (source_id,symbol,interval_seconds,ts) DO NOTHING",
                        values,
                        page_size=1000,
                    )
                    inserted += max(0, cur.rowcount)
            return inserted
        finally:
            release_connection(conn)

    def get_history(self, symbol: str, interval_seconds: int, start_ts, end_ts,
                    source_id: str = SOURCE_ID, limit: int = MAX_HISTORY_LIMIT) -> list[dict]:
        if symbol not in SUPPORTED_SYMBOLS or interval_seconds != INTERVAL_SECONDS:
            raise ValueError("unsupported research history contract")
        limit = max(1, min(int(limit), MAX_HISTORY_LIMIT))
        return execute_query(
            "SELECT * FROM research_market_bars WHERE source_id=%s AND symbol=%s "
            "AND interval_seconds=%s AND ts >= %s AND ts <= %s ORDER BY ts ASC LIMIT %s",
            (source_id, symbol, interval_seconds, _utc(start_ts), _utc(end_ts), limit),
        )

    def get_first_latest(self, symbol: str, interval_seconds: int = INTERVAL_SECONDS,
                         source_id: str = SOURCE_ID) -> dict:
        rows = execute_query(
            "SELECT MIN(ts) first_observation_ts,MAX(ts) last_observation_ts,COUNT(*) row_count "
            "FROM research_market_bars WHERE source_id=%s AND symbol=%s AND interval_seconds=%s "
            "AND synthetic=false",
            (source_id, symbol, interval_seconds),
        )
        return rows[0] if rows else {
            "first_observation_ts": None, "last_observation_ts": None, "row_count": 0
        }

    def get_event_points_batch(self, *, symbol: str, event_targets: list[dict[str, Any]],
                               interval_seconds: int = INTERVAL_SECONDS,
                               source_id: str = SOURCE_ID) -> dict[str, Any]:
        """Select one reference plus one first post-target bar per event/horizon.

        The query is driven by the bounded event sample rather than by every
        five-minute row in the requested calendar span, so no historical slice
        is silently censored by ``MAX_HISTORY_LIMIT``.
        """
        if symbol not in SUPPORTED_SYMBOLS or interval_seconds != INTERVAL_SECONDS:
            raise ValueError("unsupported research history contract")
        coverage = self.get_first_latest(symbol, interval_seconds, source_id)
        if not event_targets:
            return {
                "rows": [], "coverage": coverage, "truncated": False,
                "query_mode": "event_target_lateral_v1", "requested_target_count": 0,
            }
        payload = json.dumps(event_targets, default=str)
        rows = execute_query(
            """WITH targets AS (
                   SELECT * FROM jsonb_to_recordset(%s::jsonb)
                     AS t(event_id text,event_ts timestamptz,horizon text,target_ts timestamptz)
               ), events AS (
                   SELECT DISTINCT event_id,event_ts FROM targets
               ), refs AS (
                   SELECT e.event_id,'reference'::text AS point_kind,NULL::text AS horizon,b.*
                   FROM events e
                   LEFT JOIN LATERAL (
                       SELECT * FROM research_market_bars b
                       WHERE b.source_id=%s AND b.symbol=%s AND b.interval_seconds=%s
                         AND b.synthetic=false AND b.close>0 AND b.ts<=e.event_ts
                       ORDER BY b.ts DESC,b.id DESC LIMIT 1
                   ) b ON TRUE
               ), hits AS (
                   SELECT t.event_id,'target'::text AS point_kind,t.horizon,b.*
                   FROM targets t
                   LEFT JOIN LATERAL (
                       SELECT * FROM research_market_bars b
                       WHERE b.source_id=%s AND b.symbol=%s AND b.interval_seconds=%s
                         AND b.synthetic=false AND b.close>0 AND b.ts>=t.target_ts
                       ORDER BY b.ts ASC,b.id ASC LIMIT 1
                   ) b ON TRUE
               )
               SELECT * FROM refs
               UNION ALL
               SELECT * FROM hits
               ORDER BY event_id,point_kind,horizon NULLS FIRST""",
            (payload, source_id, symbol, interval_seconds, source_id, symbol, interval_seconds),
        )
        return {
            "rows": rows,
            "coverage": coverage,
            "truncated": False,
            "query_mode": "event_target_lateral_v1",
            "requested_target_count": len(event_targets),
            "max_expected_rows": len({str(row["event_id"]) for row in event_targets}) + len(event_targets),
        }

    def get_coverage(self, symbol: str, interval_seconds: int, start_ts, end_ts,
                     source_id: str = SOURCE_ID, now: datetime | None = None) -> dict:
        start, end = _utc(start_ts), _utc(end_ts)
        if end < start:
            raise ValueError("end_ts must be at or after start_ts")
        rows = self.get_history(symbol, interval_seconds, start, end, source_id, MAX_HISTORY_LIMIT)
        timestamps = [_utc(row["ts"]) for row in rows]
        expected = math.floor((end - start).total_seconds() / interval_seconds) + 1
        latest = timestamps[-1] if timestamps else None
        max_gap = max(
            ((right - left).total_seconds() for left, right in zip(timestamps, timestamps[1:])),
            default=0,
        )
        return {
            "source_id": source_id,
            "provider": PROVIDER,
            "symbol": symbol,
            "interval_seconds": interval_seconds,
            "row_count": len(rows),
            "first_observation_ts": timestamps[0] if timestamps else None,
            "last_observation_ts": latest,
            "requested_start_ts": start,
            "requested_end_ts": end,
            "expected_observation_count": expected,
            "observed_observation_count": len(rows),
            "coverage_ratio": min(1.0, len(rows) / expected) if expected else 0.0,
            "max_gap_seconds": max_gap,
            "age_seconds": max(
                0.0, ((_utc(now) if now else datetime.now(timezone.utc)) - latest).total_seconds()
            ) if latest else None,
            "synthetic_count": sum(1 for row in rows if row.get("synthetic")),
            "research_grade": True,
            "authoritative": False,
            "execution_eligible": False,
            "query_truncated": len(rows) >= MAX_HISTORY_LIMIT,
        }
