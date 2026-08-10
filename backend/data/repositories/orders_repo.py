import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.data.db import execute_query, execute_returning, execute_write

logger = logging.getLogger(__name__)


def _json(value: dict | list | None) -> str:
    return json.dumps(value or {}, default=str)


def _normalize_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, uuid.UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


class OrdersRepository:
    """Persistence boundary for order lifecycle and conditional orders.

    The repository deliberately keeps database details out of execution routing.
    Methods fail closed for atomic state transitions and fail soft for ordinary
    audit persistence so an unavailable database cannot be mistaken for a
    successful trigger claim.
    """

    def create_intent(
        self,
        *,
        request_id: str,
        client_order_id: str,
        idempotency_key: str,
        venue: str,
        market: str,
        side: str,
        size: float,
        order_type: str,
        price: float | None,
        strategy_id: str | None = None,
        decision_id: str | None = None,
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO order_intents (
                       request_id, client_order_id, idempotency_key, venue, market,
                       side, size, order_type, price, strategy_id, decision_id,
                       payload, status
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'created')
                   ON CONFLICT (idempotency_key) DO NOTHING
                   RETURNING *""",
                (
                    request_id,
                    client_order_id,
                    idempotency_key,
                    venue,
                    market,
                    side,
                    size,
                    order_type,
                    price,
                    strategy_id,
                    decision_id,
                    _json(payload),
                ),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to create order intent", exc_info=True)
            return None

    def create_order(
        self,
        *,
        intent_id: str | None,
        client_order_id: str,
        venue: str,
        market: str,
        side: str,
        size: float,
        order_type: str,
        price: float | None,
        execution_mode: str,
        status: str,
        venue_order_id: str | None = None,
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO orders (
                       intent_id, client_order_id, venue_order_id, venue, market,
                       side, size, order_type, price, execution_mode, status, payload
                   ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                   RETURNING *""",
                (
                    intent_id,
                    client_order_id,
                    venue_order_id,
                    venue,
                    market,
                    side,
                    size,
                    order_type,
                    price,
                    execution_mode,
                    status,
                    _json(payload),
                ),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to create order", exc_info=True)
            return None

    def update_order_status(
        self,
        order_id: str,
        status: str,
        *,
        venue_order_id: str | None = None,
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """UPDATE orders
                   SET status = %s,
                       venue_order_id = COALESCE(%s, venue_order_id),
                       payload = CASE WHEN %s::jsonb = '{}'::jsonb THEN payload ELSE payload || %s::jsonb END,
                       updated_at = NOW()
                   WHERE id = %s::uuid
                   RETURNING *""",
                (status, venue_order_id, _json(payload), _json(payload), order_id),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to update order status", exc_info=True)
            return None

    def record_event(
        self,
        *,
        event_type: str,
        order_id: str | None = None,
        intent_id: str | None = None,
        source: str = "execution_api",
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO order_events (order_id, intent_id, event_type, source, payload)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb)
                   RETURNING *""",
                (order_id, intent_id, event_type, source, _json(payload)),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to record order event %s", event_type, exc_info=True)
            return None

    def record_fill(
        self,
        *,
        order_id: str,
        venue_fill_id: str | None,
        size: float,
        price: float,
        fee: float = 0.0,
        funding: float = 0.0,
        slippage: float = 0.0,
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO fills (
                       order_id, venue_fill_id, size, price, fee, funding, slippage, payload
                   ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb)
                   RETURNING *""",
                (order_id, venue_fill_id, size, price, fee, funding, slippage, _json(payload)),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to record fill", exc_info=True)
            return None

    def save_paper_order(
        self,
        *,
        order_id: str,
        fill_id: str | None,
        status: str,
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO paper_orders (order_id, fill_id, status, payload)
                   VALUES (%s::uuid, %s::uuid, %s, %s::jsonb)
                   ON CONFLICT (order_id) DO UPDATE
                   SET fill_id = EXCLUDED.fill_id,
                       status = EXCLUDED.status,
                       payload = paper_orders.payload || EXCLUDED.payload,
                       updated_at = NOW()
                   RETURNING *""",
                (order_id, fill_id, status, _json(payload)),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to save paper order", exc_info=True)
            return None

    def get_order(self, order_id: str) -> dict | None:
        try:
            rows = execute_query("SELECT * FROM orders WHERE id = %s::uuid", (order_id,))
            return _normalize_row(rows[0]) if rows else None
        except Exception:
            logger.error("Failed to get order", exc_info=True)
            return None

    def create_conditional_order(self, order: dict[str, Any]) -> dict | None:
        try:
            row = execute_returning(
                """INSERT INTO conditional_orders (
                       id, venue, market, side, size, order_type, trigger_price,
                       limit_price, trailing_amount, parent_id, oco_group_id,
                       status, trigger_key, payload, current_trigger_level
                   ) VALUES (
                       %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s::uuid, %s::uuid, %s, %s, %s::jsonb, %s
                   ) RETURNING *""",
                (
                    order["id"],
                    order["venue"],
                    order["market"],
                    order["side"],
                    order["size"],
                    order["order_type"],
                    order.get("trigger_price"),
                    order.get("limit_price"),
                    order.get("trailing_amount"),
                    order.get("parent_id"),
                    order.get("oco_group_id"),
                    order.get("status", "active"),
                    order.get("trigger_key"),
                    _json(order.get("payload")),
                    order.get("current_trigger_level"),
                ),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to create conditional order", exc_info=True)
            return None

    def list_conditional_orders(self) -> list[dict]:
        try:
            return [
                _normalize_row(row) or {}
                for row in execute_query(
                    """SELECT * FROM conditional_orders
                       WHERE status <> 'deleted'
                       ORDER BY created_at ASC"""
                )
            ]
        except Exception:
            logger.error("Failed to list conditional orders", exc_info=True)
            return []

    def update_conditional_runtime(
        self,
        order_id: str,
        *,
        current_trigger_level: float | None = None,
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """UPDATE conditional_orders
                   SET current_trigger_level = COALESCE(%s, current_trigger_level),
                       payload = CASE WHEN %s::jsonb = '{}'::jsonb THEN payload ELSE payload || %s::jsonb END,
                       updated_at = NOW()
                   WHERE id = %s::uuid AND status = 'active'
                   RETURNING *""",
                (current_trigger_level, _json(payload), _json(payload), order_id),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to update conditional runtime state", exc_info=True)
            return None

    def claim_conditional_order(self, order_id: str, trigger_key: str) -> dict | None:
        """Atomically claim one active conditional order.

        A missing row means another worker already claimed/cancelled it or the
        database is unavailable. Callers must never execute without a claim.
        """
        try:
            row = execute_returning(
                """UPDATE conditional_orders
                   SET status = 'triggering',
                       trigger_key = COALESCE(trigger_key, %s),
                       claimed_at = NOW(),
                       updated_at = NOW()
                   WHERE id = %s::uuid
                     AND status = 'active'
                     AND (trigger_key IS NULL OR trigger_key = %s)
                   RETURNING *""",
                (trigger_key, order_id, trigger_key),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to claim conditional order", exc_info=True)
            return None

    def mark_conditional_triggered(
        self,
        order_id: str,
        *,
        triggered_order_id: str | None,
        payload: dict | None = None,
    ) -> dict | None:
        try:
            row = execute_returning(
                """UPDATE conditional_orders
                   SET status = 'triggered',
                       triggered_order_id = %s::uuid,
                       triggered_at = NOW(),
                       payload = CASE WHEN %s::jsonb = '{}'::jsonb THEN payload ELSE payload || %s::jsonb END,
                       updated_at = NOW()
                   WHERE id = %s::uuid AND status = 'triggering'
                   RETURNING *""",
                (triggered_order_id, _json(payload), _json(payload), order_id),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to mark conditional order triggered", exc_info=True)
            return None

    def release_conditional_claim(self, order_id: str, payload: dict | None = None) -> dict | None:
        try:
            row = execute_returning(
                """UPDATE conditional_orders
                   SET status = 'active',
                       claimed_at = NULL,
                       payload = CASE WHEN %s::jsonb = '{}'::jsonb THEN payload ELSE payload || %s::jsonb END,
                       updated_at = NOW()
                   WHERE id = %s::uuid AND status = 'triggering'
                   RETURNING *""",
                (_json(payload), _json(payload), order_id),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to release conditional order claim", exc_info=True)
            return None

    def cancel_conditional_order(self, order_id: str, reason: str = "cancelled") -> dict | None:
        try:
            row = execute_returning(
                """UPDATE conditional_orders
                   SET status = 'cancelled',
                       cancel_reason = %s,
                       cancelled_at = NOW(),
                       updated_at = NOW()
                   WHERE id = %s::uuid
                     AND status IN ('active', 'triggering', 'parent_bracket')
                   RETURNING *""",
                (reason, order_id),
            )
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to cancel conditional order", exc_info=True)
            return None

    def cancel_oco_siblings(self, order_id: str, reason: str = "oco_sibling_filled") -> int:
        try:
            return execute_write(
                """UPDATE conditional_orders target
                   SET status = 'cancelled',
                       cancel_reason = %s,
                       cancelled_at = NOW(),
                       updated_at = NOW()
                   FROM conditional_orders source
                   WHERE source.id = %s::uuid
                     AND source.oco_group_id IS NOT NULL
                     AND target.oco_group_id = source.oco_group_id
                     AND target.id <> source.id
                     AND target.status = 'active'""",
                (reason, order_id),
            )
        except Exception:
            logger.error("Failed to cancel OCO siblings", exc_info=True)
            return 0

    def mark_conditional_filled(self, order_id: str) -> dict | None:
        try:
            row = execute_returning(
                """UPDATE conditional_orders
                   SET status = 'filled', updated_at = NOW()
                   WHERE id = %s::uuid AND status = 'triggered'
                   RETURNING *""",
                (order_id,),
            )
            if row:
                self.cancel_oco_siblings(order_id)
            return _normalize_row(row)
        except Exception:
            logger.error("Failed to mark conditional order filled", exc_info=True)
            return None
