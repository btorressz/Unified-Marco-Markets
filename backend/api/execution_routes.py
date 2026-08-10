import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import EXECUTION_MODE, LIVE_EXECUTION_ENABLED
from backend.core.event_bus import EventType
from backend.core.state_store import StateStore
from backend.core.schemas import ExecutionStatusResponse
from backend.execution.router import ExecutionRouter
from backend.execution.jupiter_exec import JupiterExecutor
from backend.data.repositories.positions_repo import PositionsRepository
from backend.compute.smart_execution import create_smart_order, get_all_executions, get_execution

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/execution", tags=["execution"])

_exec_router = ExecutionRouter()
_jupiter = JupiterExecutor()
_positions_repo = PositionsRepository()
_state_store = StateStore()


class OrderRequest(BaseModel):
    venue: str
    market: str
    side: str
    size: float
    price: float | None = None
    client_order_id: str | None = None
    request_id: str | None = None
    strategy_id: str | None = None
    decision_id: str | None = None
    idempotency_key: str | None = None


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


_conditional_orders: dict[str, dict[str, Any]] = {}


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
    typ = (order.get("order_type") or "").lower()
    side = (order.get("side") or "sell").lower()
    trigger = order.get("trigger_price")
    if typ == "trailing_stop":
        if side == "sell":
            order["peak_price"] = max(float(order.get("peak_price") or price), price)
            trigger = order["peak_price"] - float(order.get("trailing_amount") or 0)
        else:
            order["trough_price"] = min(float(order.get("trough_price") or price), price)
            trigger = order["trough_price"] + float(order.get("trailing_amount") or 0)
        order["current_trigger_level"] = trigger
    if typ in ("stop_loss", "trailing_stop"):
        return (price <= float(trigger or 0), None) if side == "sell" else (price >= float(trigger or 0), None)
    if typ == "take_profit":
        return (price >= float(trigger or order.get("take_profit_price") or 0), None) if side == "sell" else (price <= float(trigger or order.get("take_profit_price") or 0), None)
    return False, None


class JupiterQuoteRequest(BaseModel):
    input_mint: str
    output_mint: str
    amount: int
    slippage_bps: int = 50


class JupiterSwapRequest(BaseModel):
    quote_response: dict


@router.post("/order")
def place_order(req: OrderRequest):
    try:
        side = req.side.lower().strip()
        if side not in ("buy", "sell"):
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": f"Invalid side '{req.side}' — must be 'buy' or 'sell'"},
            )
        if req.size <= 0:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": "Order size must be greater than zero"},
            )
        if req.price is not None and req.price <= 0:
            raise HTTPException(
                status_code=400,
                detail={"status": "error", "message": "Order price must be greater than zero when provided"},
            )

        request_id = req.request_id or str(uuid.uuid4())
        client_order_id = req.client_order_id or request_id
        idempotency_key = req.idempotency_key or client_order_id
        order_context = {
            "client_order_id": client_order_id,
            "request_id": request_id,
            "strategy_id": req.strategy_id,
            "decision_id": req.decision_id,
            "idempotency_key": idempotency_key,
        }

        idempotency_status = "degraded"
        if _state_store.get_redis() is not None:
            if not _state_store.set_idempotency_key(idempotency_key, ttl=300):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "status": "duplicate",
                        "message": "Duplicate execution request rejected",
                        **order_context,
                    },
                )
            idempotency_status = "claimed"

        _exec_router.event_bus.emit(
            EventType.ORDER_INTENT_CREATED,
            source="execution_api",
            payload={
                **order_context,
                "venue": req.venue,
                "market": req.market,
                "side": side,
                "size": req.size,
                "price": req.price,
                "idempotency_status": idempotency_status,
            },
        )

        result = _exec_router.route_order(
            venue=req.venue,
            market=req.market,
            side=side,
            size=req.size,
            price=req.price,
            order_context=order_context,
        )
        result["idempotency_status"] = idempotency_status

        if result.get("status") == "blocked":
            raise HTTPException(status_code=403, detail=result)

        if result.get("status") == "execution_state_unknown":
            _exec_router.event_bus.emit(
                EventType.ORDER_EXECUTION_STATE_UNKNOWN,
                source="execution_api",
                payload={**order_context, **result},
            )
            return result

        if result.get("execution_mode") == "paper":
            fill_price = req.price or result.get("fill_price", 0.0)
            _positions_repo.save_paper_trade(
                venue=req.venue,
                market=req.market,
                side=side,
                size=req.size,
                price=fill_price,
                order_type="limit",
                status=result.get("status", "unknown"),
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
        return {
            "live_positions": positions,
            "db_positions": db_positions,
        }
    except Exception as exc:
        logger.error("Error fetching positions: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch positions")


@router.get("/paper-trades")
def get_paper_trades():
    try:
        trades = _positions_repo.get_paper_trades(limit=50)
        return {"trades": trades, "count": len(trades)}
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
    now = datetime.now(timezone.utc).isoformat()
    oid = str(uuid.uuid4())
    order = req.model_dump()
    order.update({"id": oid, "status": "active", "created_at": now, "updated_at": now, "triggered_order": None, "current_trigger_level": req.trigger_price})
    _conditional_orders[oid] = order
    if req.order_type == "bracket_order":
        for child_type, trig in (("take_profit", req.take_profit_price), ("stop_loss", req.stop_loss_price)):
            if trig:
                cid = str(uuid.uuid4())
                child = {**order, "id": cid, "order_type": child_type, "trigger_price": trig, "parent_id": oid, "status": "active", "created_at": now, "updated_at": now}
                _conditional_orders[cid] = child
        order["status"] = "parent_bracket"
    return order


@router.get("/conditional-orders")
def list_conditional_orders():
    return {"orders": list(_conditional_orders.values()), "count": len(_conditional_orders), "ts": datetime.now(timezone.utc).isoformat()}


@router.post("/conditional-orders/evaluate")
def evaluate_conditional_orders(body: dict[str, Any] | None = None):
    body = body or {}
    triggered = []
    warnings = []
    for oid, order in list(_conditional_orders.items()):
        if order.get("status") != "active":
            continue
        price = _latest_price(order.get("market", ""), body.get("prices", {}).get(order.get("market", "")) if isinstance(body.get("prices"), dict) else body.get("price"))
        yes, warn = _conditional_triggered(order, price)
        if warn:
            warnings.append({"id": oid, "warning": warn})
            continue
        if yes:
            result = _exec_router.route_order(order["venue"], order["market"], order["side"], float(order["size"]), price)
            order["status"] = "triggered"
            order["triggered_at"] = datetime.now(timezone.utc).isoformat()
            order["triggered_order"] = result
            triggered.append(order)
    return {"triggered": triggered, "warnings": warnings, "orders": list(_conditional_orders.values()), "ts": datetime.now(timezone.utc).isoformat()}


@router.delete("/conditional-order/{order_id}")
def delete_conditional_order(order_id: str):
    order = _conditional_orders.get(order_id)
    if not order:
        return {"status": "not_found", "id": order_id}
    order["status"] = "cancelled"
    order["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"status": "cancelled", "id": order_id}


@router.post("/smart-order")
def smart_order(req: SmartOrderRequest):
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
