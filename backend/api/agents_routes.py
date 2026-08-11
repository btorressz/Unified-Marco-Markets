import logging
from datetime import datetime, timezone
from fastapi import APIRouter

from backend.core.state_keys import (
    GDELT_LATEST,
    PREDICTION_LATEST,
    PRICE_INTEGRITY,
    PYTH_SOL_USD,
    STABLECOIN_HEALTH,
    STABLECOIN_HEALTH_LEGACY,
    WITS_AGGREGATE,
)
from backend.core.state_store import StateStore
from backend.agents.risk_agent import RiskAgent
from backend.agents.macro_agent import MacroAgent
from backend.agents.execution_agent import ExecutionAgent
from backend.agents.liquidity_agent import LiquidityAgent
from backend.agents.hyperliquid_agent import HyperliquidAgent
from backend.agents.jupiter_agent import JupiterAgent
from backend.agents.hedging_agent import HedgingAgent
from backend.agents.geopolitical_agent import GeopoliticalAgent
from backend.agents.sanctions_agent import SanctionsAgent
from backend.agents.conflict_agent import ConflictAgent
from backend.agents.energy_shock_agent import EnergyShockAgent
from backend.agents.protection_agent import ProtectionAgent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])

_store = StateStore()
_risk_agent = RiskAgent()
_macro_agent = MacroAgent()
_exec_agent = ExecutionAgent()
_liq_agent = LiquidityAgent()
_hl_agent = HyperliquidAgent()
_jup_agent = JupiterAgent()
_hedge_agent = HedgingAgent()
_geo_agent = GeopoliticalAgent()
_sanctions_agent = SanctionsAgent()
_conflict_agent = ConflictAgent()
_energy_agent = EnergyShockAgent()
_protection_agent = ProtectionAgent()


def _build_agent_state() -> dict:
    state = {}
    now = datetime.now(timezone.utc).isoformat()

    idx = _store.get_snapshot("index:latest")
    if idx:
        state["tariff_index"] = idx.get("tariff_index", 0)
        state["tariff_momentum"] = idx.get("rate_of_change", 0)
        state["shock_score"] = idx.get("shock_score", 0)
        state["data_ts"] = idx.get("ts", now)
    else:
        state["data_ts"] = now

    regime = _store.get_snapshot("regime:latest")
    if regime:
        state["vol_regime"] = regime.get("vol_regime", "normal")
        state["funding_regime"] = regime.get("funding_regime", "neutral")

    risk = _store.get_snapshot("risk:status")
    if risk:
        state["margin_usage"] = risk.get("margin_usage", 0)

    stable = _store.get_snapshot(STABLECOIN_HEALTH) or _store.get_snapshot(STABLECOIN_HEALTH_LEGACY)
    if stable:
        state["stablecoin_health"] = stable

    micro = _store.get_snapshot("microstructure:latest")
    if micro:
        state["orderbook_imbalance"] = micro.get("imbalance", 0)
        state["spread_bps"] = micro.get("spread_bps", 0) if "spread_bps" in micro else 0

    integrity = _store.get_snapshot(PRICE_INTEGRITY)
    if integrity:
        state["price_integrity"] = integrity.get("status", "UNKNOWN")

    state["positions"] = []
    state["current_price"] = 0

    price_snap = _store.get_snapshot(PYTH_SOL_USD)
    if not price_snap:
        price_snap = _store.get_snapshot("price:sol:pyth")
    if price_snap:
        state["current_price"] = price_snap.get("price", 0)

    predict = _store.get_snapshot(PREDICTION_LATEST)
    if predict:
        state["predictor_prob"] = predict.get("probability", predict.get("prob_up_next_4h", 0.5))

    carry = _store.get_snapshot("carry:latest")
    if carry:
        scores = carry.get("scores", [])
        if scores:
            state["carry_score"] = scores[0].get("annualized_carry", 0)

    geo = _store.get_snapshot("geopolitical:index:latest")
    if geo:
        state.update(geo)

    return state


@router.get("/signals")
def get_agent_signals():
    state = _build_agent_state()
    signals = []

    try:
        signals.extend(_risk_agent.evaluate(state))
    except Exception:
        logger.debug("Risk agent error", exc_info=True)

    try:
        signals.extend(_macro_agent.evaluate(state))
    except Exception:
        logger.debug("Macro agent error", exc_info=True)

    try:
        signals.extend(_exec_agent.evaluate(state))
    except Exception:
        logger.debug("Execution agent error", exc_info=True)

    try:
        signals.extend(_liq_agent.evaluate(state))
    except Exception:
        logger.debug("Liquidity agent error", exc_info=True)

    try:
        signals.extend(_hl_agent.evaluate(state))
    except Exception:
        logger.debug("Hyperliquid agent error", exc_info=True)

    try:
        signals.extend(_jup_agent.evaluate(state))
    except Exception:
        logger.debug("Jupiter agent error", exc_info=True)

    try:
        signals.extend(_hedge_agent.evaluate(state))
    except Exception:
        logger.debug("Hedging agent error", exc_info=True)

    try:
        from backend.compute.geopolitical_risk import compute_geopolitical_index
        from backend.compute.portfolio_protection import protection_protocol
        geo_state = compute_geopolitical_index({
            "gdelt": _store.get_snapshot(GDELT_LATEST),
            "wits": _store.get_snapshot(WITS_AGGREGATE),
            "stablecoin": _store.get_snapshot(STABLECOIN_HEALTH) or _store.get_snapshot(STABLECOIN_HEALTH_LEGACY),
        })
        protection = protection_protocol({"geopolitical_index": geo_state, "data_quality": geo_state.get("data_quality", "degraded")})
        signals.extend(_geo_agent.evaluate(geo_state))
        signals.extend(_sanctions_agent.evaluate(geo_state))
        signals.extend(_conflict_agent.evaluate(geo_state))
        signals.extend(_energy_agent.evaluate(geo_state))
        signals.extend(_protection_agent.evaluate({**geo_state, **protection}))
    except Exception:
        logger.debug("Geopolitical agents error", exc_info=True)

    _record_signals(signals)
    _store.set_snapshot("agents:signals", {"signals": signals, "ts": datetime.now(timezone.utc).isoformat()}, ttl=30)
    return {"signals": signals, "agent_count": 12, "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/status")
def get_agent_status():
    cached = _store.get_snapshot("agents:signals")
    signal_count = 0
    if cached and "signals" in cached:
        signal_count = len(cached["signals"])

    return {
        "agents": [
            {"name": "risk_agent", "status": "active", "description": "Monitors leverage, margin, drawdown limits and throttle triggers"},
            {"name": "macro_agent", "status": "active", "description": "Evaluates tariff index, shock scores and macro regime signals"},
            {"name": "execution_agent", "status": "active", "description": "Tracks execution quality, slippage and fill metrics"},
            {"name": "liquidity_agent", "status": "active", "description": "Monitors stablecoin health, depeg risk and liquidity conditions"},
            {"name": "hyperliquid_agent", "status": "active", "description": "Analyzes orderbook microstructure, spread and depth on Hyperliquid"},
            {"name": "jupiter_agent", "status": "active", "description": "Monitors Jupiter quote freshness, route complexity, price impact and Solana congestion"},
            {"name": "hedging_agent", "status": "active", "description": "Position-aware hedge recommendations based on shock, vol, funding and margin signals"},
            {"name": "geopolitical_agent", "status": "active", "description": "Proposal-only geopolitical market risk monitor"},
            {"name": "sanctions_agent", "status": "active", "description": "Sanctions and export-control pressure monitor"},
            {"name": "conflict_agent", "status": "active", "description": "Conflict escalation and hotspot monitor"},
            {"name": "energy_shock_agent", "status": "active", "description": "Energy, commodity and chokepoint shock monitor"},
            {"name": "protection_agent", "status": "active", "description": "Portfolio protection protocol proposal agent"},
        ],
        "total_signals": signal_count,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

_signal_history: list[dict] = []


def _record_signals(signals: list[dict]) -> None:
    for s in signals:
        row = dict(s)
        row.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
        _signal_history.append(row)
    del _signal_history[:-500]


@router.get("/history")
def agent_history(limit: int = 100):
    cached = _store.get_snapshot("agents:signals") or {"signals": []}
    if cached.get("signals") and not _signal_history:
        _record_signals(cached.get("signals", []))
    return {"history": list(reversed(_signal_history[-limit:])), "count": min(limit, len(_signal_history)), "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/performance")
def agent_performance():
    if not _signal_history:
        cached = _store.get_snapshot("agents:signals") or {"signals": []}
        _record_signals(cached.get("signals", []))
    by_agent: dict[str, list[dict]] = {}
    for s in _signal_history:
        by_agent.setdefault(s.get("agent", "unknown"), []).append(s)
    perf = []
    for agent, rows in by_agent.items():
        outcomes = [float(r["realized_outcome"]) for r in rows if r.get("realized_outcome") is not None]
        confs = [float(r.get("confidence", 0.0) or 0.0) for r in rows]
        hits = sum(1 for o in outcomes if o >= 0)
        perf.append({"agent": agent, "signal_count": len(rows), "evaluated_count": len(outcomes), "unevaluated_count": len(rows)-len(outcomes), "hit_rate": round(hits / len(outcomes), 4) if outcomes else None, "average_confidence": round(sum(confs) / len(confs), 4) if confs else 0.0, "average_realized_outcome": round(sum(outcomes) / len(outcomes), 6) if outcomes else None, "false_positive_count": sum(1 for o in outcomes if o < 0), "false_negative_count": 0, "best_market_regime": None, "worst_market_regime": None})
    evaluated = [row for row in perf if row["evaluated_count"]]
    best = max(evaluated, key=lambda x: x["hit_rate"], default=None)
    worst = min(evaluated, key=lambda x: x["hit_rate"], default=None)
    return {"agents": perf, "best_agent": best, "worst_agent": worst, "ts": datetime.now(timezone.utc).isoformat()}

@router.get("/consensus")
def agent_consensus():
    try:
        from backend.compute.agent_consensus import build_consensus
        cached = _store.get_snapshot("agents:signals") or {"signals": []}
        return build_consensus(cached.get("signals", []))
    except Exception as exc:
        logger.error("Agent consensus failed: %s", exc, exc_info=True)
        return {"bullish_count": 0, "bearish_count": 0, "neutral_count": 0, "risk_on_risk_off_score": 50.0, "confidence_weighted_consensus": "neutral", "disagreement_level": 0.0, "proposed_action": "hold_monitor", "top_agreeing_agents": [], "conflicting_agents": [], "proposal_only": True, "warnings": [str(exc)], "ts": datetime.now(timezone.utc).isoformat()}
