"""Read-only historical data access for decision outcome evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.data.db import execute_query


class DecisionOutcomeRepository:
    """Bounded SELECT-only adapter over existing historical/execution tables."""

    @staticmethod
    def _dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            result = value
        else:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)

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

            def normalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
                result = []
                for row in rows:
                    item = dict(row)
                    for key, value in list(item.items()):
                        if isinstance(value, datetime):
                            item[key] = value.isoformat()
                        elif hasattr(value, "hex") and value.__class__.__name__ == "UUID":
                            item[key] = str(value)
                    result.append(item)
                return result

            return {
                "available": True,
                "intents": normalize(intents),
                "orders": normalize(orders),
                "fills": normalize(fills),
            }
        except Exception as exc:
            return {"available": False, "reason": f"execution lifecycle unavailable: {exc}", "intents": [], "orders": [], "fills": []}
