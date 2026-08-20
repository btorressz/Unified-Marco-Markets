import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from backend.config import (
    EXECUTION_MODE,
    LIVE_EXECUTION_ENABLED,
    MAX_ORDER_NOTIONAL,
    MAX_ORDER_SLIPPAGE_BPS,
    PRICE_FRESHNESS_THRESHOLD_S,
    PRICE_INTEGRITY_BLOCK_LIVE,
    SUPPORTED_EXECUTION_MARKETS,
    SUPPORTED_EXECUTION_VENUES,
    SUPPORTED_ORDER_TYPES,
)
from backend.core.event_bus import EventBus, EventType
from backend.core.state_store import StateStore
from backend.core.state_keys import price_integrity_key, price_snapshot_candidates
from backend.core.price_authority import PriceAuthority
from backend.compute.risk_engine import RiskEngine
from backend.compute.execution_decision import combine_execution_decision, evaluate_data_guardrails
from backend.compute.decision_replay import decision_hash
from backend.data.repositories.decision_repo import DecisionRepository
from backend.agents.execution_agent import ExecutionAgent
from backend.execution.paper_exec import PaperExecutor
from backend.execution.hyperliquid_exec import HyperliquidExecutor
from backend.execution.drift_exec import DriftExecutor

logger = logging.getLogger(__name__)


def _symbol_from_market(market: str) -> str:
    m = market.upper().replace("-PERP", "_USD").replace("/", "_")
    normalized = market.upper().strip()
    if normalized not in SUPPORTED_EXECUTION_MARKETS:
        raise ValueError(f"Unsupported execution market '{market}'")
    if not m.endswith("_USD") and not m.endswith("_USDC") and not m.endswith("_USDT"):
        m = m.split("-")[0].split("/")[0] + "_USD"
    return m


class ExecutionRouter:

    def __init__(self, event_bus: EventBus | None = None, risk_engine: RiskEngine | None = None):
        self.event_bus = event_bus or EventBus()
        self.risk_engine = risk_engine or RiskEngine()
        self.mode = EXECUTION_MODE
        self.live_execution_enabled = LIVE_EXECUTION_ENABLED
        self._store = StateStore()
        self._price_authority = PriceAuthority(state_store=self._store)
        self._exec_agent = ExecutionAgent()
        self._decision_repo = DecisionRepository()
        self.paper = PaperExecutor(event_bus=self.event_bus)
        self.hyperliquid: HyperliquidExecutor | None = None
        self.drift: DriftExecutor | None = None
        if self.mode == "live" and self.live_execution_enabled:
            try:
                self.hyperliquid = HyperliquidExecutor(event_bus=self.event_bus)
            except Exception as exc:
                logger.error("Failed to init HyperliquidExecutor: %s", exc, exc_info=True)
            try:
                self.drift = DriftExecutor(event_bus=self.event_bus)
            except Exception as exc:
                logger.error("Failed to init DriftExecutor: %s", exc, exc_info=True)
        elif self.mode == "live":
            logger.warning("EXECUTION_MODE=live requested but LIVE_EXECUTION_ENABLED is false; real execution is hard-disabled")
        logger.info("ExecutionRouter initialised mode=%s live_execution_enabled=%s", self.mode, self.live_execution_enabled)

    def _get_live_price(self, market: str) -> dict:
        symbol = _symbol_from_market(market)
        result = self._price_authority.get_price(symbol)
        now = datetime.now(timezone.utc)
        if not result.found or result.price <= 0:
            return {"price": 0.0, "source": "none", "ts": now.isoformat(), "age_s": 0, "fresh": False, "found": False, "integrity_symbol": symbol}
        age_s = (now - result.ts).total_seconds()
        return {
            "price": result.price,
            "source": result.source,
            "ts": result.ts.isoformat(),
            "age_s": round(age_s, 1),
            "fresh": age_s <= PRICE_FRESHNESS_THRESHOLD_S,
            "found": True,
            "integrity_symbol": symbol,
        }

    def _get_data_context(self, live_price: dict | None = None, order_context: dict | None = None) -> dict:
        ctx = {"execution_mode": self.mode}
        now = datetime.now(timezone.utc)
        integrity_symbol = (live_price or {}).get("integrity_symbol", "SOL/USD")
        if order_context:
            ctx.update({k: v for k, v in order_context.items() if v is not None})
        idx = self._store.get_snapshot("index:latest")
        if idx:
            ctx["tariff_ts"] = idx.get("ts", now.isoformat())
            ctx["shock_ts"] = idx.get("ts", now.isoformat())
        else:
            ctx["tariff_ts"] = now.isoformat()
            ctx["shock_ts"] = now.isoformat()
        if live_price and live_price.get("found"):
            ctx["price_ts"] = live_price["ts"]
            ctx["price_source"] = live_price["source"]
            ctx["price_asof_ts"] = live_price["ts"]
            ctx["data_age_ms"] = int(live_price["age_s"] * 1000)
        else:
            price_snap = None
            for cache_key in price_snapshot_candidates("pyth", integrity_symbol):
                price_snap = self._store.get_snapshot(cache_key)
                if price_snap:
                    break
            if price_snap:
                ctx["price_ts"] = price_snap.get("ts", now.isoformat())
                ctx["price_source"] = "pyth"
                price_ts = price_snap.get("ts", now.isoformat())
                try:
                    if isinstance(price_ts, str):
                        ctx["data_age_ms"] = int((now - datetime.fromisoformat(price_ts.replace("Z", "+00:00"))).total_seconds() * 1000)
                except Exception:
                    pass
            else:
                ctx["price_ts"] = now.isoformat()
                ctx["price_source"] = "none"
        integrity = self._store.get_snapshot(price_integrity_key(integrity_symbol))
        ctx["integrity_status"] = integrity.get("status", "UNKNOWN") if integrity else "UNKNOWN"
        return ctx

    def _get_market_state(self, market: str) -> dict:
        ms = {}
        micro = self._store.get_snapshot("microstructure:latest")
        if micro:
            ms["spread_bps"] = micro.get("spread_bps", 0)
            ms["liquidity_depth"] = micro.get("liquidity_depth", 0)
        integrity_symbol = _symbol_from_market(market)
        integrity = self._store.get_snapshot(price_integrity_key(integrity_symbol))
        ms["price_integrity"] = integrity.get("status", "UNKNOWN") if integrity else "UNKNOWN"
        ms["integrity_symbol"] = integrity_symbol
        return ms

    def _get_risk_positions(self) -> list[dict]:
        return self.get_all_positions() if self.mode == "live" else list(self.paper.get_positions())

    def _get_risk_snapshot(self, positions: list[dict]):
        account = dict(self._store.get_snapshot("execution:account") or {})
        if self.mode == "paper":
            totals = self.paper.get_account_totals()
            for key in ("realized_pnl", "unrealized_pnl", "margin_used", "gross_exposure", "net_exposure"):
                account.setdefault(key, totals.get(key, 0.0))
        return self.risk_engine.build_portfolio_snapshot(positions, account=account)

    def _risk_replay_spec(self, positions: list[dict], portfolio_snapshot, proposed: dict) -> dict[str, Any]:
        self.risk_engine._sync_shared_state()
        return {
            "positions": positions,
            "portfolio_snapshot": portfolio_snapshot.model_dump(),
            "proposed_action": dict(proposed),
            "limits": {
                "max_leverage": self.risk_engine.max_leverage,
                "max_margin_pct": self.risk_engine.max_margin_pct,
                "max_daily_loss": self.risk_engine.max_daily_loss,
                "cooldown_seconds": self.risk_engine.cooldown_seconds,
            },
            "runtime_state": {
                "throttle_active": self.risk_engine.throttle_active,
                "throttle_reason": self.risk_engine.throttle_reason,
                "daily_pnl": self.risk_engine.daily_pnl,
                "daily_pnl_reset_date": self.risk_engine.daily_pnl_reset_date,
                "last_action_ts": self.risk_engine.last_action_ts,
            },
            "execution_mode": self.mode,
        }

    def _persist_final_decision(self, context: dict[str, Any], order_context: dict | None) -> str | None:
        order_context = dict(order_context or {})
        data_spec = context["replay_inputs"]["execution_boundary"]["data"]
        order = dict(data_spec.get("order") or {})
        final_id = str(uuid.uuid4())
        audit = {
            "id": final_id,
            "decision_ts": context["decision_ts"],
            "decision_type": "execution_pre_trade_final",
            "venue": order.get("venue"),
            "market": order.get("market"),
            "symbol": order.get("market"),
            "input_state": {"replay_inputs": context["replay_inputs"]},
            "input_provenance": {
                "provenance_status": "partial",
                "source": "execution_router_pre_trade",
                "admission_decision_id": order_context.get("decision_id"),
            },
            "derived_state": {"data_result": context["data_result"], "execution_agent_result": context["agent_result"]},
            "heuristic_result": {"status": "not_used"},
            "ml_result": {"status": "not_used"},
            "risk_result": context["risk_result"],
            "allocation_result": {"status": "not_used"},
            "execution_intent": {
                **{k: v for k, v in order_context.items() if v is not None},
                "admission_decision_id": order_context.get("decision_id"),
                "order": order,
                "execution_mode": self.mode,
            },
            "component_versions": {"execution_decision": "v1"},
            "config_snapshot": {
                "data_guardrails": {
                    "max_order_notional": data_spec.get("max_order_notional"),
                    "price_integrity_block_live": data_spec.get("price_integrity_block_live"),
                },
                "risk": (context["replay_inputs"].get("risk") or {}).get("limits", {}),
            },
            "final_decision": context["final_decision"],
        }
        audit["decision_hash"] = decision_hash(audit)
        try:
            self._decision_repo.create(audit)
            self.event_bus.emit(
                EventType.DECISION_RECORDED,
                source="execution_router",
                payload={"decision_id": final_id, "decision_type": "execution_pre_trade_final", "final_decision": context["final_decision"]},
            )
            return final_id
        except Exception:
            logger.warning("Final pre-trade decision audit persistence unavailable", exc_info=True)
            return None

    def _emit_pre_trade_decision(
        self,
        decision_hook: Callable[[dict[str, Any]], None] | None,
        *,
        as_of: datetime,
        data_spec: dict[str, Any],
        order_context: dict | None,
        risk_spec: dict[str, Any] | None = None,
        risk_result: dict[str, Any] | None = None,
        agent_spec: dict[str, Any] | None = None,
        agent_result: dict[str, Any] | None = None,
        executor_available: bool = True,
        data_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data_result = data_result or evaluate_data_guardrails(data_spec)
        risk_result = risk_result or {"status": "not_used"}
        agent_result = agent_result or {"status": "not_used", "allowed": True, "reasons": []}
        final_decision = combine_execution_decision(
            data_result=data_result,
            risk_result=risk_result,
            agent_result=agent_result,
            execution_mode=self.mode,
            executor_available=executor_available,
            as_of=as_of,
        )
        context = {
            "decision_ts": as_of,
            "replay_inputs": {
                "heuristic": {"status": "not_used"},
                "ml": {"status": "not_used"},
                "allocation": {"status": "not_used"},
                "risk": risk_spec or {"status": "not_used"},
                "execution_boundary": {
                    "data": data_spec,
                    "agent": agent_spec or {"status": "not_used"},
                    "execution_mode": self.mode,
                    "executor_available": executor_available,
                },
            },
            "data_result": data_result,
            "risk_result": risk_result,
            "agent_result": agent_result,
            "final_decision": final_decision,
        }
        final_id = self._persist_final_decision(context, order_context)
        context["final_decision_id"] = final_id
        api_linked = bool((order_context or {}).get("decision_id"))
        if self.mode == "live" and api_linked and final_decision["allowed"] and final_id is None:
            risk_reducing = False
            if risk_spec and risk_spec.get("status") != "not_used":
                try:
                    risk_reducing = self.risk_engine._is_reducing(risk_spec.get("positions") or [], risk_spec.get("proposed_action") or {})
                except Exception:
                    risk_reducing = False
            if not risk_reducing:
                raise RuntimeError("live_final_decision_audit_unavailable")
        if decision_hook is not None:
            decision_hook(context)
        return context

    def route_order(
        self,
        venue: str,
        market: str,
        side: str,
        size: float,
        price: float | None = None,
        order_type: str = "limit",
        slippage_bps: float = 0.0,
        order_context: dict | None = None,
        decision_hook: Callable[[dict[str, Any]], None] | None = None,
        decision_ts: datetime | None = None,
    ) -> dict:
        now = decision_ts or datetime.now(timezone.utc)
        venue = str(venue).lower().strip()
        market = str(market).upper().strip()
        side = str(side).lower().strip()
        order_type = str(order_type).lower().strip()
        validation_reasons: list[str] = []
        if venue not in SUPPORTED_EXECUTION_VENUES:
            validation_reasons.append(f"unsupported_venue: '{venue}'")
        if market not in SUPPORTED_EXECUTION_MARKETS:
            validation_reasons.append(f"unsupported_market: '{market}'")
        if side not in ("buy", "sell"):
            validation_reasons.append(f"unsupported_side: '{side}'")
        if order_type not in SUPPORTED_ORDER_TYPES:
            validation_reasons.append(f"unsupported_order_type: '{order_type}'")
        if size <= 0:
            validation_reasons.append("invalid_size: size must be greater than zero")
        if price is not None and price <= 0:
            validation_reasons.append("invalid_price: price must be greater than zero when provided")
        if slippage_bps < 0 or slippage_bps > MAX_ORDER_SLIPPAGE_BPS:
            validation_reasons.append(f"invalid_slippage: {slippage_bps} bps exceeds allowed range 0-{MAX_ORDER_SLIPPAGE_BPS}")

        order_snapshot = {
            "venue": venue,
            "market": market,
            "side": side,
            "size": size,
            "price": price,
            "order_type": order_type,
            "slippage_bps": slippage_bps,
        }
        base_data_spec = {
            "execution_mode": self.mode,
            "live_execution_enabled": self.live_execution_enabled,
            "validation_reasons": validation_reasons,
            "price_found": False,
            "fill_price": float(price or 0.0),
            "order_notional": abs(float(size) * float(price or 0.0)),
            "max_order_notional": MAX_ORDER_NOTIONAL,
            "price_fresh": True,
            "integrity_status": "UNKNOWN",
            "price_integrity_block_live": PRICE_INTEGRITY_BLOCK_LIVE,
            "order": order_snapshot,
        }
        if validation_reasons:
            ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=base_data_spec, order_context=order_context)
            return {"status": "blocked", "reasons": validation_reasons, "execution_mode": self.mode, "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **(order_context or {}), "ts": now.isoformat()}
        if self.mode == "live" and not self.live_execution_enabled:
            ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=base_data_spec, order_context=order_context)
            return {"status": "blocked", "reasons": ["Live execution is disabled. Set both EXECUTION_MODE=live and LIVE_EXECUTION_ENABLED=true only after venue adapters are production-ready."], "execution_mode": "live", "live_execution_enabled": False, "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **(order_context or {}), "ts": now.isoformat()}

        live_price_info = self._get_live_price(market)
        fill_price = price if price is not None and price > 0 else live_price_info.get("price", 0.0)
        data_ctx = self._get_data_context(live_price_info, order_context=order_context)
        order_notional = abs(float(size) * float(fill_price))
        data_spec = {
            **base_data_spec,
            "price_found": bool(live_price_info.get("found", False)),
            "fill_price": float(fill_price),
            "order_notional": order_notional,
            "price_fresh": bool(live_price_info.get("fresh", True)),
            "integrity_status": str(data_ctx.get("integrity_status", "UNKNOWN")),
        }
        data_result = evaluate_data_guardrails(data_spec)

        if not live_price_info.get("found") and fill_price <= 0:
            self.event_bus.emit(EventType.TRADE_BLOCKED_STALE_DATA, source="execution_router", payload={**data_ctx, "reason": "No price data available for " + market, "market": market, "side": side})
            ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=data_spec, data_result=data_result, order_context=order_context)
            return {"status": "blocked", "reasons": ["No price data available — try again when feeds are active"], "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}
        if order_notional > MAX_ORDER_NOTIONAL:
            ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=data_spec, data_result=data_result, order_context=order_context)
            return {"status": "blocked", "reasons": [f"max_notional_exceeded: {order_notional:.2f} > {MAX_ORDER_NOTIONAL:.2f}"], "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}
        if not live_price_info.get("fresh", True) and live_price_info.get("found"):
            age_s = live_price_info.get("age_s", 0)
            if self.mode == "live":
                self.event_bus.emit(EventType.TRADE_BLOCKED_STALE_DATA, source="execution_router", payload={**data_ctx, "reason": f"Price data stale ({age_s:.0f}s old, threshold {PRICE_FRESHNESS_THRESHOLD_S}s)", "market": market, "side": side, "age_s": age_s})
                ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=data_spec, data_result=data_result, order_context=order_context)
                return {"status": "blocked", "reasons": [f"Price data stale ({age_s:.0f}s old) — refresh and try again"], "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}
            data_ctx["data_quality"] = "DEGRADED"
            self.event_bus.emit(EventType.TRADE_DEGRADED_DATA, source="execution_router", payload={**data_ctx, "reason": f"Paper trade with stale data ({age_s:.0f}s old)", "market": market, "side": side})

        integrity_status = str(data_ctx.get("integrity_status", "UNKNOWN")).upper()
        if integrity_status != "OK":
            reason = "Price integrity WARNING — cross-venue deviation too high" if integrity_status == "WARNING" else f"Price integrity {integrity_status} — live execution requires OK"
            if self.mode == "live" and PRICE_INTEGRITY_BLOCK_LIVE:
                self.event_bus.emit(EventType.TRADE_BLOCKED_STALE_DATA, source="execution_router", payload={**data_ctx, "reason": reason, "market": market, "side": side})
                ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=data_spec, data_result=data_result, order_context=order_context)
                return {"status": "blocked", "reasons": [reason], "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}
            data_ctx["data_quality"] = data_ctx.get("data_quality", "DEGRADED")
            self.event_bus.emit(EventType.TRADE_DEGRADED_DATA, source="execution_router", payload={**data_ctx, "reason": f"Paper trade with integrity {integrity_status}", "market": market, "side": side})

        if self.mode == "paper" and fill_price > 0:
            self.paper.mark_to_market(venue, market, fill_price)
        positions = self._get_risk_positions()
        portfolio_snapshot = self._get_risk_snapshot(positions)
        proposed = {"venue": venue, "market": market, "side": side, "size": size, "price": fill_price, "order_type": order_type, "slippage_bps": slippage_bps}
        risk_spec = self._risk_replay_spec(positions, portfolio_snapshot, proposed)
        allowed, reasons = self.risk_engine.check_constraints(positions, proposed, execution_mode=self.mode, portfolio_snapshot=portfolio_snapshot, as_of=now)
        risk_result = {"approved": allowed, "reasons": reasons, "metrics": self.risk_engine.last_metrics}
        if not allowed:
            self.event_bus.emit(EventType.RISK_THROTTLE_ON, source="execution_router", payload={**data_ctx, "reasons": reasons, "proposed": proposed, "portfolio_metrics": self.risk_engine.last_metrics})
            logger.warning("Order blocked by risk engine: %s", reasons)
            ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=data_spec, data_result=data_result, order_context=order_context, risk_spec=risk_spec, risk_result=risk_result)
            return {"status": "blocked", "reasons": reasons, "portfolio_metrics": self.risk_engine.last_metrics, "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}

        agent_spec: dict[str, Any] = {"status": "not_used"}
        agent_result: dict[str, Any] = {"status": "not_used", "allowed": True, "reasons": []}
        if self.mode == "live":
            market_state = self._get_market_state(market)
            agent_spec = {
                "proposed": proposed,
                "market_state": market_state,
                "max_slippage_bps": float(getattr(self._exec_agent, "max_slippage_bps", 50.0)),
                "min_liquidity_depth": float(getattr(self._exec_agent, "min_liquidity_depth", 50.0)),
            }
            check = self._exec_agent.pre_trade_check(proposed, market_state)
            agent_result = dict(check)
            agent_result["ts"] = now.isoformat()
            if not check.get("allowed", True):
                self.event_bus.emit(EventType.AGENT_BLOCKED, source="execution_agent", payload={**data_ctx, "reasons": check.get("reasons", []), "proposed": proposed, "message": "Trade blocked by execution agent: " + "; ".join(check.get("reasons", []))})
                logger.warning("Trade blocked by execution agent: %s", check.get("reasons"))
                ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=data_spec, data_result=data_result, order_context=order_context, risk_spec=risk_spec, risk_result=risk_result, agent_spec=agent_spec, agent_result=agent_result)
                return {"status": "agent_blocked", "reasons": check.get("reasons", []), "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}

        executor = self._get_live_executor(venue) if self.mode == "live" else None
        executor_available = True if self.mode == "paper" else executor is not None
        ctx = self._emit_pre_trade_decision(decision_hook, as_of=now, data_spec=data_spec, data_result=data_result, order_context=order_context, risk_spec=risk_spec, risk_result=risk_result, agent_spec=agent_spec, agent_result=agent_result, executor_available=executor_available)
        if not ctx["final_decision"]["allowed"]:
            logger.error("Pre-trade decision blocked before submission: %s", ctx["final_decision"].get("reasons"))
            return {"status": "blocked", "reasons": ctx["final_decision"].get("reasons", []), "execution_mode": self.mode, "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}
        if self.mode == "paper":
            result = self.paper.place_order(venue=venue, market=market, side=side, size=size, order_type=order_type, price=fill_price, data_context=data_ctx)
            result["execution_mode"] = "paper"
            result["portfolio_metrics"] = self.risk_engine.last_metrics
            result["final_decision"] = ctx["final_decision"]
            result["final_decision_id"] = ctx["final_decision_id"]
            result.update({k: v for k, v in (order_context or {}).items() if v is not None})
            return result
        if executor is None:
            logger.error("No production-ready live executor available for venue=%s", venue)
            return {"status": "blocked", "reasons": [f"No production-ready live executor available for venue '{venue}'"], "execution_mode": "live", "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}
        try:
            result = executor.place_order(market=market, side=side, size=size, price=fill_price, order_type=order_type)
            if result.get("status") == "error":
                return {"status": "execution_state_unknown", "requires_reconciliation": True, "reason": result.get("reason", "Live venue returned an execution error"), "venue": venue, "market": market, "side": side, "size": size, "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}
            result["execution_mode"] = "live"
            result["venue"] = venue
            result["final_decision"] = ctx["final_decision"]
            result["final_decision_id"] = ctx["final_decision_id"]
            result.update(data_ctx)
            return result
        except Exception as exc:
            logger.error("Live execution state unknown for %s after submission attempt: %s", venue, exc, exc_info=True)
            return {"status": "execution_state_unknown", "requires_reconciliation": True, "reason": "Live submission raised after execution may have reached the venue", "venue": venue, "market": market, "side": side, "size": size, "error": str(exc), "final_decision": ctx["final_decision"], "final_decision_id": ctx["final_decision_id"], **data_ctx, "ts": now.isoformat()}

    def _get_live_executor(self, venue: str):
        if not self.live_execution_enabled:
            return None
        venue_lower = venue.lower()
        if venue_lower == "hyperliquid" and self.hyperliquid and self.hyperliquid.enabled:
            return self.hyperliquid
        if venue_lower == "drift" and self.drift and self.drift.enabled:
            return self.drift
        return None

    def get_all_positions(self) -> list[dict]:
        positions = list(self.paper.get_positions())
        if self.mode == "live" and self.live_execution_enabled:
            if self.hyperliquid and self.hyperliquid.enabled:
                try:
                    positions.extend(self.hyperliquid.get_positions())
                except Exception as exc:
                    logger.error("Failed to get Hyperliquid positions: %s", exc)
            if self.drift and self.drift.enabled:
                try:
                    positions.extend(self.drift.get_positions())
                except Exception as exc:
                    logger.error("Failed to get Drift positions: %s", exc)
        return positions

    def get_status(self) -> dict:
        return {
            "execution_mode": self.mode,
            "live_execution_enabled": self.live_execution_enabled,
            "paper_enabled": self.paper.enabled,
            "hyperliquid_enabled": self.hyperliquid.enabled if self.hyperliquid else False,
            "drift_enabled": self.drift.enabled if self.drift else False,
            "risk_status": self.risk_engine.get_status(),
        }
