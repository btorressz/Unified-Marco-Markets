from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from backend.data.db import execute_query, execute_returning, execute_write

logger = logging.getLogger(__name__)


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


class BacktestRepository:
    """Historical data access and durable backtest-run persistence."""

    def load_market_ticks(
        self,
        *,
        start_ts: str,
        end_ts: str,
        venue: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ts >= %s::timestamptz", "ts <= %s::timestamptz"]
        params: list[Any] = [start_ts, end_ts]
        if venue:
            clauses.append("LOWER(venue) = LOWER(%s)")
            params.append(venue)
        if symbol:
            clauses.append("UPPER(symbol) = UPPER(%s)")
            params.append(symbol)
        rows = execute_query(
            f"""SELECT id, symbol, venue, price, confidence, ts
                FROM market_ticks
                WHERE {' AND '.join(clauses)}
                ORDER BY ts ASC, id ASC""",
            params,
        )
        return [_normalize_row(row) for row in rows]

    def load_funding_ticks(
        self,
        *,
        start_ts: str,
        end_ts: str,
        venue: str | None = None,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ts >= %s::timestamptz", "ts <= %s::timestamptz"]
        params: list[Any] = [start_ts, end_ts]
        if venue:
            clauses.append("LOWER(venue) = LOWER(%s)")
            params.append(venue)
        if market:
            clauses.append("UPPER(market) = UPPER(%s)")
            params.append(market)
        rows = execute_query(
            f"""SELECT id, venue, market, funding_rate, ts
                FROM funding_ticks
                WHERE {' AND '.join(clauses)}
                ORDER BY ts ASC, id ASC""",
            params,
        )
        return [_normalize_row(row) for row in rows]

    def load_index_history(self, *, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = execute_query(
            """SELECT id, index_level, rate_of_change, shock_score, components, ts
               FROM index_history
               WHERE ts >= %s::timestamptz AND ts <= %s::timestamptz
               ORDER BY ts ASC, id ASC""",
            (start_ts, end_ts),
        )
        return [_normalize_row(row) for row in rows]

    def load_stablecoin_ticks(self, *, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = execute_query(
            """SELECT id, symbol, price, depeg_bps, source, ts
               FROM stablecoin_ticks
               WHERE ts >= %s::timestamptz AND ts <= %s::timestamptz
               ORDER BY ts ASC, id ASC""",
            (start_ts, end_ts),
        )
        return [_normalize_row(row) for row in rows]

    def load_regime_snapshots(self, *, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = execute_query(
            """SELECT id, shock_state, funding_regime, vol_regime, tariff_index,
                      price, return_4h, return_24h, ts
               FROM regime_snapshots
               WHERE ts >= %s::timestamptz AND ts <= %s::timestamptz
               ORDER BY ts ASC, id ASC""",
            (start_ts, end_ts),
        )
        return [_normalize_row(row) for row in rows]

    def load_events(self, *, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = execute_query(
            """SELECT id, event_type, source, payload, ts
               FROM events
               WHERE ts >= %s::timestamptz AND ts <= %s::timestamptz
               ORDER BY ts ASC, id ASC""",
            (start_ts, end_ts),
        )
        return [_normalize_row(row) for row in rows]

    def load_orders(self, *, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = execute_query(
            """SELECT id, intent_id, client_order_id, venue_order_id, venue, market,
                      side, size, order_type, price, execution_mode, status, payload,
                      created_at, updated_at
               FROM orders
               WHERE created_at >= %s::timestamptz AND created_at <= %s::timestamptz
               ORDER BY created_at ASC, id ASC""",
            (start_ts, end_ts),
        )
        return [_normalize_row(row) for row in rows]

    def load_fills(self, *, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
        rows = execute_query(
            """SELECT f.id, f.order_id, f.venue_fill_id, f.size, f.price,
                      f.fee, f.funding, f.slippage, f.payload, f.ts,
                      o.venue, o.market, o.side, oi.strategy_id
               FROM fills f
               JOIN orders o ON o.id = f.order_id
               LEFT JOIN order_intents oi ON oi.id = o.intent_id
               WHERE f.ts >= %s::timestamptz AND f.ts <= %s::timestamptz
               ORDER BY f.ts ASC, f.id ASC""",
            (start_ts, end_ts),
        )
        return [_normalize_row(row) for row in rows]

    def load_historical_bundle(
        self,
        *,
        start_ts: str,
        end_ts: str,
        venue: str | None,
        symbol: str | None,
        market: str | None,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "market_ticks": self.load_market_ticks(
                start_ts=start_ts,
                end_ts=end_ts,
                venue=venue,
                symbol=symbol,
            ),
            "funding_ticks": self.load_funding_ticks(
                start_ts=start_ts,
                end_ts=end_ts,
                venue=venue,
                market=market,
            ),
            "index_history": self.load_index_history(start_ts=start_ts, end_ts=end_ts),
            "stablecoin_ticks": self.load_stablecoin_ticks(start_ts=start_ts, end_ts=end_ts),
            "regime_snapshots": self.load_regime_snapshots(start_ts=start_ts, end_ts=end_ts),
            "events": self.load_events(start_ts=start_ts, end_ts=end_ts),
            "orders": self.load_orders(start_ts=start_ts, end_ts=end_ts),
            "fills": self.load_fills(start_ts=start_ts, end_ts=end_ts),
        }

    def data_coverage(self) -> dict[str, Any]:
        tables = {
            "market_ticks": "ts",
            "funding_ticks": "ts",
            "index_history": "ts",
            "stablecoin_ticks": "ts",
            "regime_snapshots": "ts",
            "events": "ts",
            "orders": "created_at",
            "fills": "ts",
        }
        result: dict[str, Any] = {}
        for table, ts_col in tables.items():
            try:
                row = execute_query(
                    f"SELECT COUNT(*) AS count, MIN({ts_col}) AS earliest, MAX({ts_col}) AS latest FROM {table}"
                )[0]
                result[table] = _normalize_row(row)
            except Exception as exc:
                logger.warning("Backtest coverage query failed for %s", table, exc_info=True)
                result[table] = {"count": 0, "earliest": None, "latest": None, "error": str(exc)}
        return result

    def create_run(self, *, mode: str, config: dict[str, Any]) -> dict[str, Any] | None:
        try:
            row = execute_returning(
                """INSERT INTO backtest_runs
                   (mode, strategy, venue, market, start_ts, end_ts, config, status)
                   VALUES (%s, %s, %s, %s, %s::timestamptz, %s::timestamptz, %s::jsonb, 'running')
                   RETURNING *""",
                (
                    mode,
                    str(config.get("strategy", "momentum")),
                    str(config.get("venue", "")),
                    str(config.get("market", "")),
                    config.get("start_ts"),
                    config.get("end_ts"),
                    json.dumps(config, default=str),
                ),
            )
            return _normalize_row(row) if row else None
        except Exception:
            logger.warning("Failed to persist backtest run start", exc_info=True)
            return None

    def complete_run(
        self,
        run_id: str,
        *,
        status: str,
        data_manifest: dict[str, Any],
        metrics: dict[str, Any],
    ) -> None:
        try:
            execute_write(
                """UPDATE backtest_runs
                   SET status = %s,
                       data_manifest = %s::jsonb,
                       metrics = %s::jsonb,
                       completed_at = NOW()
                   WHERE id = %s::uuid""",
                (
                    status,
                    json.dumps(data_manifest, default=str),
                    json.dumps(metrics, default=str),
                    run_id,
                ),
            )
        except Exception:
            logger.warning("Failed to persist backtest run completion", exc_info=True)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        try:
            rows = execute_query(
                "SELECT * FROM backtest_runs WHERE id = %s::uuid",
                (run_id,),
            )
            return _normalize_row(rows[0]) if rows else None
        except Exception:
            return None

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            rows = execute_query(
                """SELECT * FROM backtest_runs
                   ORDER BY created_at DESC LIMIT %s""",
                (max(1, min(int(limit), 100)),),
            )
            return [_normalize_row(row) for row in rows]
        except Exception:
            return []
