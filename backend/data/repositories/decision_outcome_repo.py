"""Read-only historical data access for decision outcome evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.data.db import execute_query


class DecisionOutcomeRepository:
    """Bounded SELECT-only adapter over existing historical/execution tables."""

    CONTEXT_MAX_ROWS = 10000

    @staticmethod
    def _dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            result = value
        else:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

    @classmethod
    def _normalize_rows(cls, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key, value in list(item.items()):
                if isinstance(value, datetime):
                    item[key] = value.isoformat()
                elif hasattr(value, "hex") and value.__class__.__name__ == "UUID":
                    item[key] = str(value)
            result.append(item)
        return result

    def load_horizon_prices(
        self,
        *,
        decision_ts: Any,
        symbols: list[str],
        horizons: dict[str, int],
        tolerance_seconds: int = 3600,
    ) -> dict[str, Any]:
        if not symbols:
            return {"available": False, "reason": "decision symbol is unavailable", "observations": []}
        try:
            decision_time = self._dt(decision_ts)
        except Exception:
            return {"available": False, "reason": "decision timestamp is invalid", "observations": []}

        normalized_symbols = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
        rows: list[dict[str, Any]] = []
        try:
            for horizon, seconds in horizons.items():
                target = decision_time + timedelta(seconds=int(seconds))
                end = target + timedelta(seconds=max(0, int(tolerance_seconds)))
                matches = execute_query(
                    """SELECT id, symbol, venue, price, confidence, ts
                       FROM market_ticks
                       WHERE UPPER(symbol) = ANY(%s)
                         AND ts >= %s::timestamptz
                         AND ts <= %s::timestamptz
                       ORDER BY ts ASC, id ASC
                       LIMIT 100""",
                    (normalized_symbols, target.isoformat(), end.isoformat()),
                )
                for row in matches:
                    item = dict(row)
                    observed = self._dt(item.get("ts"))
                    item["horizon"] = horizon
                    item["target_ts"] = target.isoformat()
                    item["lag_seconds"] = max(0.0, (observed - target).total_seconds())
                    item["ts"] = observed.isoformat()
                    rows.append(item)
        except Exception as exc:
            return {"available": False, "reason": f"historical market observations unavailable: {exc}", "observations": []}

        return {"available": True, "observations": rows}

    def load_context_history(self, *, start_ts: Any, end_ts: Any) -> dict[str, Any]:
        """Load bounded persisted context around a decision-performance window.

        One pre-window seed observation is included for regime/index history, and
        one pre-window seed per stablecoin symbol is included for depeg context.
        This remains SELECT-only and never mutates the immutable decision ledger.
        """
        try:
            start = self._dt(start_ts)
            end = self._dt(end_ts)
        except Exception:
            return {
                "available": False,
                "reason": "decision context window is invalid",
                "regime_snapshots": [],
                "index_history": [],
                "stablecoin_ticks": [],
                "errors": {"window": "invalid_timestamp"},
                "truncated": {},
            }
        if start > end:
            start, end = end, start

        payload: dict[str, Any] = {
            "available": True,
            "start_ts": start.isoformat(),
            "end_ts": end.isoformat(),
            "regime_snapshots": [],
            "index_history": [],
            "stablecoin_ticks": [],
            "errors": {},
            "truncated": {},
            "max_rows_per_series": self.CONTEXT_MAX_ROWS,
            "read_only": True,
        }

        def bounded(name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            payload["truncated"][name] = len(rows) > self.CONTEXT_MAX_ROWS
            return rows[: self.CONTEXT_MAX_ROWS]

        try:
            seed = execute_query(
                """SELECT id, shock_state, funding_regime, vol_regime, tariff_index,
                          price, return_4h, return_24h, ts
                   FROM regime_snapshots
                   WHERE ts < %s::timestamptz
                   ORDER BY ts DESC, id DESC
                   LIMIT 1""",
                (start.isoformat(),),
            )
            rows = execute_query(
                """SELECT id, shock_state, funding_regime, vol_regime, tariff_index,
                          price, return_4h, return_24h, ts
                   FROM regime_snapshots
                   WHERE ts >= %s::timestamptz AND ts <= %s::timestamptz
                   ORDER BY ts ASC, id ASC
                   LIMIT %s""",
                (start.isoformat(), end.isoformat(), self.CONTEXT_MAX_ROWS + 1),
            )
            payload["regime_snapshots"] = self._normalize_rows(seed + bounded("regime_snapshots", rows))
        except Exception as exc:
            payload["errors"]["regime_snapshots"] = str(exc)

        try:
            seed = execute_query(
                """SELECT id, index_level, rate_of_change, shock_score, components, ts
                   FROM index_history
                   WHERE ts < %s::timestamptz
                   ORDER BY ts DESC, id DESC
                   LIMIT 1""",
                (start.isoformat(),),
            )
            rows = execute_query(
                """SELECT id, index_level, rate_of_change, shock_score, components, ts
                   FROM index_history
                   WHERE ts >= %s::timestamptz AND ts <= %s::timestamptz
                   ORDER BY ts ASC, id ASC
                   LIMIT %s""",
                (start.isoformat(), end.isoformat(), self.CONTEXT_MAX_ROWS + 1),
            )
            payload["index_history"] = self._normalize_rows(seed + bounded("index_history", rows))
        except Exception as exc:
            payload["errors"]["index_history"] = str(exc)

        try:
            seed = execute_query(
                """SELECT DISTINCT ON (UPPER(symbol))
                          id, symbol, price, depeg_bps, source, ts
                   FROM stablecoin_ticks
                   WHERE ts < %s::timestamptz
                   ORDER BY UPPER(symbol), ts DESC, id DESC""",
                (start.isoformat(),),
            )
            rows = execute_query(
                """SELECT id, symbol, price, depeg_bps, source, ts
                   FROM stablecoin_ticks
                   WHERE ts >= %s::timestamptz AND ts <= %s::timestamptz
                   ORDER BY ts ASC, id ASC
                   LIMIT %s""",
                (start.isoformat(), end.isoformat(), self.CONTEXT_MAX_ROWS + 1),
            )
            payload["stablecoin_ticks"] = self._normalize_rows(seed + bounded("stablecoin_ticks", rows))
        except Exception as exc:
            payload["errors"]["stablecoin_ticks"] = str(exc)

        if len(payload["errors"]) == 3:
            payload["available"] = False
            payload["reason"] = "persisted decision context history is unavailable"
        return payload

    def load_execution_lifecycle(self, admission_decision_id: str) -> dict[str, Any]:
        if not admission_decision_id:
            return {"available": False, "reason": "admission decision link unavailable", "intents": [], "orders": [], "fills": []}
        try:
            intents = execute_query(
                """SELECT id, request_id, client_order_id, idempotency_key, venue, market,
                          side, size, order_type, price, strategy_id, decision_id,
                          status, created_at
                   FROM order_intents
                   WHERE decision_id = %s::uuid
                   ORDER BY created_at ASC, id ASC
                   LIMIT 20""",
                (admission_decision_id,),
            )
            intent_ids = [str(row["id"]) for row in intents]
            orders: list[dict[str, Any]] = []
            fills: list[dict[str, Any]] = []
            if intent_ids:
                orders = execute_query(
                    """SELECT id, intent_id, client_order_id, venue_order_id, venue, market,
                              side, size, order_type, price, execution_mode, status,
                              created_at, updated_at
                       FROM orders
                       WHERE intent_id = ANY(%s::uuid[])
                       ORDER BY created_at ASC, id ASC
                       LIMIT 100""",
                    (intent_ids,),
                )
                order_ids = [str(row["id"]) for row in orders]
                if order_ids:
                    fills = execute_query(
                        """SELECT id, order_id, venue_fill_id, size, price, fee,
                                  funding, slippage, ts
                           FROM fills
                           WHERE order_id = ANY(%s::uuid[])
                           ORDER BY ts ASC, id ASC
                           LIMIT 200""",
                        (order_ids,),
                    )

            return {
                "available": True,
                "intents": self._normalize_rows(intents),
                "orders": self._normalize_rows(orders),
                "fills": self._normalize_rows(fills),
            }
        except Exception as exc:
            return {"available": False, "reason": f"execution lifecycle unavailable: {exc}", "intents": [], "orders": [], "fills": []}