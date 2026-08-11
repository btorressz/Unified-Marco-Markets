import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from backend.config import (
    EXECUTION_MODE,
    LIVE_EXECUTION_ENABLED,
    MAX_ORDER_NOTIONAL,
    MAX_ORDER_SLIPPAGE_BPS,
    SUPPORTED_EXECUTION_MARKETS,
    SUPPORTED_EXECUTION_VENUES,
    SUPPORTED_ORDER_TYPES,
)
from backend.core.event_bus import EventType
from backend.core.state_store import StateStore
from backend.execution.router import ExecutionRouter
from backend.execution.jupiter_exec import JupiterExecutor
from backend.data.repositories.positions_repo import PositionsRepository
from backend.data.repositories.orders_repo import OrdersRepository
from backend.data.repositories.decision_repo import DecisionRepository
from backend.compute.decision_replay import decision_hash
from backend.compute.smart_execution import create_smart_order, get_all_executions, get_execution

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/execution", tags=["execution"])

_exec_router = ExecutionRouter()
_jupiter = JupiterExecutor()
_positions_repo = PositionsRepository()
_orders_repo = OrdersRepository()
_decision_repo = DecisionRepository()
_state_store = StateStore()


class OrderRequest(BaseModel):
    venue: str
    market: str
    side: str
    size: float
    price: float | None = None
    order_type: str = "limit"
    slippage_bps: float = 0.0
    client_order_id: str | None = None
    request_id: str | None = None
    strategy_id: str | None = None
    decision_id: str | None = None
    idempotency_key: str | None = None

    @field_validator("venue", "side", "order_type", mode="before")
    @classmethod
    def _normalize_lower(cls, value):
        return str(value).lower().strip()

    @field_validator("market", mode="before")
    @classmethod
    def _normalize_market(cls, value):
        return str(value).upper().strip()


class ConditionalOrderRequest(BaseModel):
    venue: str = "paper"
    market: str
    side: str
    size: float
    order_type: str
    trigger_price: float | None = None
    limit_price: float | None = None
    trailing_amount: float | None = None
    take_profit_price: float | None = None
    stop_loss_price: float | None = None
    parent_id: str | None = None

    @field_validator("venue", "side", "order_type", mode="before")
    @classmethod
    def _normalize_lower(cls, value):
        return str(value).lower().strip()

    @field_validator("market", mode="before")
    @classmethod
    def _normalize_market(cls, value):
        return str(value).upper().strip()


class SmartOrderRequest(BaseModel):
    venue: str = "paper"
    market: str
    side: str
    total_size: float
    n_slices: int = 5
    interval_seconds: int = 60
    mode: str = "TWAP"
    max_slippage_bps: float = 25.0
    reference_price: float | None = None


def _reject_order(code: str, message: str) -> None:
    raise HTTPException(
        status_code=400,
        detail={"status": "error", "code": code, "message": message},
    )


def _require_finite(name: str, value: float | None) -> None:
    if value is None:
        return
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        _reject_order(f"invalid_{name}", f"{name} must be numeric")
    if not math.isfinite(numeric):
        _reject_order(f"invalid_{name}", f"{name} must be finite")


def _validate_order_request(req: OrderRequest) -> None:
    _require_finite("size", req.size)
    _require_finite("price", req.price)
    _require_finite("slippage", req.slippage_bps)
    if req.venue not in SUPPORTED_EXECUTION_VENUES:
        _reject_order("unsupported_venue", f"Unsupported execution venue '{req.venue}'")
    if req.market not in SUPPORTED_EXECUTION_MARKETS:
        _reject_order("unsupported_market", f"Unsupported execution market '{req.market}'")
    if req.side not in ("buy", "sell"):
        _reject_order("unsupported_side", f"Invalid side '{req.side}' — must be 'buy' or 'sell'")
    if req.order_type not in SUPPORTED_ORDER_TYPES:
        _reject_order("unsupported_order_type", f"Unsupported order type '{req.order_type}'")
    if req.size <= 0:
        _reject_order("invalid_size", "Order size must be greater than zero")
    if req.price is not None and req.price <= 0:
        _reject_order("invalid_price", "Order price must be greater than zero when provided")
    if req.slippage_bps < 0 or req.slippage_bps > MAX_ORDER_SLIPPAGE_BPS:
        _reject_order(
            "invalid_slippage",
            f"slippage_bps must be between 0 and {MAX_ORDER_SLIPPAGE_BPS}",
        )
    if req.price is not None:
        notional = abs(req.size * req.price)
        if notional > MAX_ORDER_NOTIONAL:
            _reject_order(
                "max_notional_exceeded",
                f"Order notional {notional:.2f} exceeds maximum {MAX_ORDER_NOTIONAL:.2f}",
            )


def _validate_conditional_request(req: ConditionalOrderRequest) -> None:
    for name in ("size", "trigger_price", "limit_price", "trailing_amount", "take_profit_price", "stop_loss_price"):
        _require_finite(name, getattr(req, name))
    if req.venue not in SUPPORTED_EXECUTION_VENUES:
        _reject_order("unsupported_venue", f"Unsupported execution venue '{req.venue}'")
    if req.market not in SUPPORTED_EXECUTION_MARKETS:
        _reject_order("unsupported_market", f"Unsupported execution market '{req.market}'")
    if req.side not in ("buy", "sell"):
        _reject_order("unsupported_side", f"Invalid side '{req.side}'")
    if req.size <= 0:
        _reject_order("invalid_size", "Conditional order size must be greater than zero")
    if req.order_type not in ("stop_loss", "take_profit", "trailing_stop", "bracket_order"):
        _reject_order("unsupported_order_type", f"Unsupported conditional order type '{req.order_type}'")
    if req.order_type == "bracket_order" and (
        req.take_profit_price is None or req.stop_loss_price is None
    ):
        _reject_order("invalid_bracket", "Bracket orders require both take_profit_price and stop_loss_price")
    if req.order_type == "trailing_stop" and (req.trailing_amount is None or req.trailing_amount <= 0):
        _reject_order("invalid_trailing_amount", "Trailing stops require trailing_amount > 0")


def _latest_price(market: str, fallback: float | None = None) -> float | None:
    if fallback and fallback > 0:
        return fallback
    try:
        info = _exec_router._get_live_price(market)
        price = float(info.get("price") or 0)
        return price if price > 0 else None
    except Exception:
        return None


def _conditional_triggered(order: dict[str, Any], price: float | None) -> tuple[bool, str | None]:
    if price is None:
        return False, "missing price; evaluation skipped"

    typ = str(order.get("order_type") or "").lower()
    side = str(order.get("side") or "sell").lower()
    trigger = order.get("trigger_price")
    payload = dict(order.get("payload") or {})

    if typ == "trailing_stop":
        if side == "sell":
            peak = max(float(payload.get("peak_price") or price), price)
            payload["peak_price"] = peak
            trigger = peak - float(order.get("trailing_amount") or 0)
        else:
            trough = min(float(payload.get("trough_price") or price), price)
            payload["trough_price"] = trough
            trigger = trough + float(order.get("trailing_amount") or 0)
        order["payload"] = payload
        order["current_trigger_level"] = trigger

    if typ in ("stop_loss", "trailing_stop"):
        return (price <= float(trigger or 0), None) if side == "sell" else (price >= float(trigger or 0), None)
    if typ == "take_profit":
        return (price >= float(trigger or 0), None) if side == "sell" else (price <= float(trigger or 0), None)
    return False, None


def _record_lifecycle(
    event_type: str,
    *,
    payload: dict,
    intent_id: str | None = None,
    order_id: str | None = None,
    emit_bus: bool = True,
) -> None:
    if emit_bus:
        _exec_router.event_bus.emit(event_type, source="execution_api", payload=payload)
    if intent_id or order_id:
        _orders_repo.record_event(
            event_type=event_type,
            intent_id=intent_id,
            order_id=order_id,
            source="execution_api",
            payload=payload,
        )


def _persist_execution_result(
    req: OrderRequest,
    result: dict,
    order_context: dict,
    intent: dict | None,
) -> dict:
    status = str(result.get("status") or "unknown")
    execution_mode = str(result.get("execution_mode") or EXECUTION_MODE)

    if status in ("blocked", "agent_blocked"):
        durable_status = "rejected"
    elif status == "execution_state_unknown":
        durable_status = "submission_unknown"
    elif status == "paper_filled" or status == "filled":
        durable_status = "filled"
    elif status == "partially_filled":
        durable_status = "partially_filled"
    elif status == "open":
        durable_status = "open"
    elif status == "submitted":
        durable_status = "acknowledged"
    else:
        durable_status = status

    intent_id = intent.get("id") if intent else None
    order = _orders_repo.create_order(
        intent_id=intent_id,
        client_order_id=order_context["client_order_id"],
        venue=req.venue,
        market=req.market,
        side=req.side,
        size=req.size,
        order_type=req.order_type,
        price=req.price or result.get("fill_price"),
        execution_mode=execution_mode,
        status=durable_status,
        venue_order_id=result.get("venue_order_id") or result.get("oid"),
        payload=result,
    )
    order_id = order.get("id") if order else None
    persistence_status = "persisted" if order_id else "degraded"
    result["persistence_status"] = persistence_status
    if order_id:
        result["durable_order_id"] = order_id

    base_payload = {**order_context, **result}

    if status == "blocked":
        _record_lifecycle(EventType.ORDER_REJECTED, payload=base_payload, intent_id=intent_id, order_id=order_id)
        return result

    if status == "agent_blocked":
        _record_lifecycle(EventType.ORDER_RISK_APPROVED, payload=base_payload, intent_id=intent_id, order_id=order_id)
        _record_lifecycle(EventType.ORDER_REJECTED, payload=base_payload, intent_id=intent_id, order_id=order_id)
        return result

    _record_lifecycle(EventType.ORDER_RISK_APPROVED, payload=base_payload, intent_id=intent_id, order_id=order_id)
    _record_lifecycle(EventType.ORDER_SUBMITTED, payload=base_payload, intent_id=intent_id, order_id=order_id)

    if status == "execution_state_unknown":
        _record_lifecycle(EventType.ORDER_SUBMISSION_UNKNOWN, payload=base_payload, intent_id=intent_id, order_id=order_id)
        return result

    if status in ("submitted", "open", "partially_filled", "filled", "paper_filled"):
        _record_lifecycle(EventType.ORDER_ACKNOWLEDGED, payload=base_payload, intent_id=intent_id, order_id=order_id)

    if status in ("open", "partially_filled"):
        _record_lifecycle(EventType.ORDER_OPEN, payload=base_payload, intent_id=intent_id, order_id=order_id)

    if status == "partially_filled":
        _record_lifecycle(EventType.ORDER_PARTIALLY_FILLED, payload=base_payload, intent_id=intent_id, order_id=order_id)

    if status in ("filled", "paper_filled"):
        _record_lifecycle(
            EventType.ORDER_FILLED,
            payload=base_payload,
            intent_id=intent_id,
            order_id=order_id,
            emit_bus=execution_mode != "paper",
        )

        if order_id:
            accounting = dict(result.get("accounting") or {})
            fill = _orders_repo.record_fill(
                order_id=order_id,
                venue_fill_id=result.get("fill_id"),
                size=req.size,
                price=float(result.get("fill_price") or req.price or 0.0),
                fee=float(accounting.get("fees", 0.0) or 0.0),
                funding=float(accounting.get("funding", 0.0) or 0.0),
                slippage=float(accounting.get("slippage", 0.0) or 0.0),
                payload=result,
            )
            if execution_mode == "paper":
                _orders_repo.save_paper_order(
                    order_id=order_id,
                    fill_id=fill.get("id") if fill else None,
                    status="filled",
                    payload=result,
                )

            remaining_size = float(accounting.get("remaining_quantity", 0.0) or 0.0)
            entry_price = float(accounting.get("average_entry") or result.get("fill_price") or req.price or 0.0)
            _positions_repo.save_position(
                venue=req.venue,
                market=req.market,
                size=remaining_size,
                entry_price=entry_price,
                pnl=float(accounting.get("unrealized_pnl", 0.0) or 0.0),
                order_id=order_id,
                realized_pnl=float(accounting.get("realized_pnl", 0.0) or 0.0),
                unrealized_pnl=float(accounting.get("unrealized_pnl", 0.0) or 0.0),
                fees=float(accounting.get("fees", 0.0) or 0.0),
                funding=float(accounting.get("funding", 0.0) or 0.0),
                slippage=float(accounting.get("slippage", 0.0) or 0.0),
            )

    return result


class JupiterQuoteRequest(BaseModel):
    input_mint: str
    output_mint: str
    amount: int
    slippage_bps: int = 50


class JupiterSwapRequest(BaseModel):
    quote_response: dict


def _is_live_risk_reduction(req: OrderRequest) -> bool:
    if _exec_router.mode != "live":
        return False
    try:
        return _exec_router.risk_engine._is_reducing(
            _exec_router._get_risk_positions(),
            {"venue": req.venue, "market": req.market, "side": req.side, "size": req.size},
        )
    except Exception:
        return False


@router.post("/order")
def place_order(req: OrderRequest):
    try:
        _validate_order_request(req)

        request_id = req.request_id or str(uuid.uuid4())
        client_order_id = req.client_order_id or request_id
        idempotency_key = req.idempotency_key or client_order_id
        decision_id = req.decision_id or str(uuid.uuid4())
        order_context = {
            "client_order_id": client_order_id,
            "request_id": request_id,
            "strategy_id": req.strategy_id,
            "decision_id": decision_id,
            "idempotency_key": idempotency_key,
        }

        live_risk_reduction = _is_live_risk_reduction(req)
        live_new_exposure = _exec_router.mode == "live" and not live_risk_reduction

        idempotency_status = _state_store.claim_idempotency_status(
            idempotency_key,
            ttl=300,
            request_id=request_id,
            owner="execution_api",
        )
        if idempotency_status == "duplicate":
            raise HTTPException(
                status_code=409,
                detail={"status": "duplicate", "message": "Duplicate execution request rejected", **order_context},
            )
        if idempotency_status == "unavailable" and live_new_exposure:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "blocked",
                    "code": "live_idempotency_unavailable",
                    "message": "Live new exposure requires an available idempotency store",
                    **order_context,
                },
            )
        if idempotency_status == "unavailable":
            idempotency_status = "degraded"

        decision_ts = datetime.now(timezone.utc)
        audit = {"id": decision_id, "decision_ts": decision_ts, "decision_type": "execution_admission",
                 "venue": req.venue, "market": req.market, "symbol": req.market,
                 "input_state": {"replay_inputs": {"heuristic": {"status": "not_used"}, "ml": {"status": "not_used"},
                    "allocation": {"status": "not_used"}, "risk": {"status": "not_used"},
                    "final_decision": {"action": "submit_to_execution_risk_boundary"}}},
                 "input_provenance": {"provenance_status": "complete", "source": "execution_order_request"},
                 "derived_state": {}, "heuristic_result": {"status": "not_used"}, "ml_result": {"status": "not_used"},
                 "risk_result": {"status": "not_used"}, "allocation_result": {"status": "not_used"},
                 "execution_intent": {"execution_mode": _exec_router.mode, "request_id": request_id,
                    "client_order_id": client_order_id, "order": req.model_dump()},
                 "component_versions": {}, "config_snapshot": {},
                 "final_decision": {"action": "submit_to_execution_risk_boundary"}}
        audit["decision_hash"] = decision_hash(audit)
        try:
            _decision_repo.create(audit)
        except Exception:
            logger.warning("Decision audit persistence unavailable", exc_info=True)

        intent = _orders_repo.create_intent(
            request_id=request_id,
            client_order_id=client_order_id,
            idempotency_key=idempotency_key,
            venue=req.venue,
            market=req.market,
            side=req.side,
            size=req.size,
            order_type=req.order_type,
            price=req.price,
            strategy_id=req.strategy_id,
            decision_id=decision_id,
            payload={"slippage_bps": req.slippage_bps},
        )
        persistence_status = "persisted" if intent else "degraded"
        if live_new_exposure and not intent:
            if idempotency_status == "claimed":
                _state_store.release_idempotency(idempotency_key)
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "blocked",
                    "code": "live_audit_persistence_unavailable",
                    "message": "Live new exposure requires durable order-intent persistence",
                    **order_context,
                },
            )

        intent_payload = {
            **order_context,
            "venue": req.venue,
            "market": req.market,
            "side": req.side,
            "size": req.size,
            "price": req.price,
            "order_type": req.order_type,
            "slippage_bps": req.slippage_bps,
            "idempotency_status": idempotency_status,
            "persistence_status": persistence_status,
            "risk_reducing": live_risk_reduction,
        }
        _record_lifecycle(
            EventType.ORDER_INTENT_CREATED,
            payload=intent_payload,
            intent_id=intent.get("id") if intent else None,
        )

        result = _exec_router.route_order(
            venue=req.venue,
            market=req.market,
            side=req.side,
            size=req.size,
            price=req.price,
            order_type=req.order_type,
            slippage_bps=req.slippage_bps,
            order_context=order_context,
        )
        result["decision_id"] = decision_id
        result["idempotency_status"] = idempotency_status
        result = _persist_execution_result(req, result, order_context, intent)

        if result.get("status") in ("blocked", "agent_blocked"):
            raise HTTPException(status_code=403, detail=result)

        if result.get("status") == "execution_state_unknown":
            _exec_router.event_bus.emit(
                EventType.ORDER_EXECUTION_STATE_UNKNOWN,
                source="execution_api",
                payload={**order_context, **result},
            )

        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error placing order: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail={"status": "error", "message": "Failed to place order"})


@router.get("/positions")
def get_positions():
    try:
        positions = _exec_router.get_all_positions()
        db_positions = _positions_repo.get_all()
        return {"live_positions": positions, "db_positions": db_positions}
    except Exception as exc:
        logger.error("Error fetching positions: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch positions")


@router.get("/paper-trades")
def get_paper_trades():
    try:
        trades = _positions_repo.get_paper_trades(limit=50)
        return {"trades": trades, "count": len(trades), "legacy": True}
    except Exception as exc:
        logger.error("Error fetching paper trades: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch paper trades")


@router.post("/jupiter/quote")
def jupiter_quote(req: JupiterQuoteRequest):
    try:
        result = _jupiter.get_quote(
            input_mint=req.input_mint,
            output_mint=req.output_mint,
            amount=req.amount,
            slippage_bps=req.slippage_bps,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error getting Jupiter quote: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get Jupiter quote")


@router.post("/jupiter/swap")
def jupiter_swap(req: JupiterSwapRequest):
    if EXECUTION_MODE != "live" or not LIVE_EXECUTION_ENABLED:
        raise HTTPException(
            status_code=403,
            detail={
                "status": "blocked",
                "message": "Jupiter swap execution requires EXECUTION_MODE=live and LIVE_EXECUTION_ENABLED=true",
            },
        )
    try:
        build_result = _jupiter.build_swap(req.quote_response)
        if build_result.get("status") == "error":
            raise HTTPException(status_code=400, detail=build_result)

        swap_tx = build_result.get("swap_tx", {})
        exec_result = _jupiter.execute_swap(swap_tx)
        if exec_result.get("status") == "error":
            raise HTTPException(status_code=400, detail=exec_result)

        return exec_result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error executing Jupiter swap: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to execute Jupiter swap")


@router.post("/conditional-order")
def create_conditional_order(req: ConditionalOrderRequest):
    _validate_conditional_request(req)
    oid = str(uuid.uuid4())

    if req.order_type == "bracket_order":
        parent = {
            "id": oid,
            "venue": req.venue,
            "market": req.market,
            "side": req.side,
            "size": req.size,
            "order_type": "bracket_order",
            "trigger_price": None,
            "limit_price": req.limit_price,
            "trailing_amount": None,
            "parent_id": req.parent_id,
            "oco_group_id": None,
            "status": "parent_bracket",
            "trigger_key": None,
            "current_trigger_level": None,
            "payload": {"take_profit_price": req.take_profit_price, "stop_loss_price": req.stop_loss_price},
        }
        saved_parent = _orders_repo.create_conditional_order(parent)
        if not saved_parent:
            raise HTTPException(status_code=503, detail={"status": "error", "message": "Conditional order persistence unavailable"})

        children = []
        for child_type, trigger_price in (("take_profit", req.take_profit_price), ("stop_loss", req.stop_loss_price)):
            child = {
                "id": str(uuid.uuid4()),
                "venue": req.venue,
                "market": req.market,
                "side": req.side,
                "size": req.size,
                "order_type": child_type,
                "trigger_price": trigger_price,
                "limit_price": req.limit_price,
                "trailing_amount": None,
                "parent_id": oid,
                "oco_group_id": oid,
                "status": "active",
                "trigger_key": None,
                "current_trigger_level": trigger_price,
                "payload": {},
            }
            saved_child = _orders_repo.create_conditional_order(child)
            if not saved_child:
                raise HTTPException(status_code=503, detail={"status": "error", "message": "Failed to persist bracket child"})
            children.append(saved_child)

        _exec_router.event_bus.emit(
            EventType.BRACKET_ORDER_CREATED,
            source="execution_api",
            payload={"parent_id": oid, "child_ids": [child["id"] for child in children]},
        )
        return {**saved_parent, "children": children}

    trigger_price = req.trigger_price
    if req.order_type == "take_profit" and trigger_price is None:
        trigger_price = req.take_profit_price
    if req.order_type == "stop_loss" and trigger_price is None:
        trigger_price = req.stop_loss_price
    if req.order_type in ("take_profit", "stop_loss") and trigger_price is None:
        _reject_order("missing_trigger", f"{req.order_type} requires a trigger price")

    order = {
        "id": oid,
        "venue": req.venue,
        "market": req.market,
        "side": req.side,
        "size": req.size,
        "order_type": req.order_type,
        "trigger_price": trigger_price,
        "limit_price": req.limit_price,
        "trailing_amount": req.trailing_amount,
        "parent_id": req.parent_id,
        "oco_group_id": None,
        "status": "active",
        "trigger_key": None,
        "current_trigger_level": trigger_price,
        "payload": {},
    }
    saved = _orders_repo.create_conditional_order(order)
    if not saved:
        raise HTTPException(status_code=503, detail={"status": "error", "message": "Conditional order persistence unavailable"})
    return saved


@router.get("/conditional-orders")
def list_conditional_orders():
    orders = _orders_repo.list_conditional_orders()
    return {"orders": orders, "count": len(orders), "ts": datetime.now(timezone.utc).isoformat()}


@router.post("/conditional-orders/evaluate")
def evaluate_conditional_orders(body: dict[str, Any] | None = None):
    body = body or {}
    triggered: list[dict] = []
    warnings: list[dict] = []

    for order in _orders_repo.list_conditional_orders():
        if order.get("status") != "active":
            continue

        market = str(order.get("market") or "")
        supplied_prices = body.get("prices") if isinstance(body.get("prices"), dict) else None
        fallback_price = supplied_prices.get(market) if supplied_prices else body.get("price")
        price = _latest_price(market, fallback_price)
        yes, warn = _conditional_triggered(order, price)

        if order.get("order_type") == "trailing_stop":
            _orders_repo.update_conditional_runtime(
                str(order["id"]),
                current_trigger_level=order.get("current_trigger_level"),
                payload=order.get("payload"),
            )

        if warn:
            warnings.append({"id": order.get("id"), "warning": warn})
            continue
        if not yes:
            continue

        order_id = str(order["id"])
        trigger_key = str(order.get("trigger_key") or f"conditional:{order_id}")
        claimed = _orders_repo.claim_conditional_order(order_id, trigger_key)
        if not claimed:
            warnings.append({
                "id": order_id,
                "warning": "trigger claim unavailable or already claimed; execution skipped",
            })
            continue

        execution_price = claimed.get("limit_price") or price
        execution_order_type = "limit" if claimed.get("limit_price") else "market"

        try:
            result = place_order(
                OrderRequest(
                    venue=str(claimed["venue"]),
                    market=str(claimed["market"]),
                    side=str(claimed["side"]),
                    size=float(claimed["size"]),
                    price=float(execution_price) if execution_price else None,
                    order_type=execution_order_type,
                    client_order_id=trigger_key,
                    request_id=str(uuid.uuid4()),
                    idempotency_key=trigger_key,
                )
            )
        except HTTPException as exc:
            _orders_repo.release_conditional_claim(order_id, payload={"last_trigger_error": exc.detail})
            warnings.append({"id": order_id, "warning": "triggered execution was rejected", "detail": exc.detail})
            continue

        durable_order_id = result.get("durable_order_id")
        updated = _orders_repo.mark_conditional_triggered(
            order_id,
            triggered_order_id=durable_order_id,
            payload={"triggered_order": result, "trigger_price_observed": price},
        )

        if result.get("status") in ("paper_filled", "filled"):
            filled = _orders_repo.mark_conditional_filled(order_id)
            if filled:
                updated = filled

        triggered.append(updated or {**claimed, "triggered_order": result})

    orders = _orders_repo.list_conditional_orders()
    return {"triggered": triggered, "warnings": warnings, "orders": orders, "ts": datetime.now(timezone.utc).isoformat()}


@router.delete("/conditional-order/{order_id}")
def delete_conditional_order(order_id: str):
    cancelled = _orders_repo.cancel_conditional_order(order_id, reason="user_cancelled")
    if not cancelled:
        return {"status": "not_found_or_not_cancellable", "id": order_id}
    return {"status": "cancelled", "id": order_id}


@router.post("/smart-order")
def smart_order(req: SmartOrderRequest):
    _require_finite("total_size", req.total_size)
    _require_finite("max_slippage_bps", req.max_slippage_bps)
    _require_finite("reference_price", req.reference_price)
    return create_smart_order(req.venue, req.market, req.side, req.total_size, req.n_slices, req.interval_seconds, req.mode, req.max_slippage_bps, req.reference_price or 0.0)


@router.get("/smart-orders")
def smart_orders():
    orders = get_all_executions(limit=50)
    return {"orders": orders, "count": len(orders), "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/smart-order/{order_id}")
def smart_order_detail(order_id: str):
    order = get_execution(order_id)
    if not order:
        return {"status": "not_found", "id": order_id}
    return order
