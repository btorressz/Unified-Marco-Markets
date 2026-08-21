from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, HTTPException

from backend.core.state_keys import OFAC_SANCTIONS, WITS_AGGREGATE, WITS_LATEST_LEGACY
from backend.core.state_store import StateStore
from backend.compute.geopolitical_risk import compute_geopolitical_index, build_geopolitical_events
from backend.compute.sanctions_risk import score_sanctions, sanctions_impact, sanctions_entities
from backend.compute.conflict_escalation import score_conflicts, conflict_market_impact
from backend.compute.shipping_energy_risk import score_chokepoints, score_energy_shock, supply_chain_impact
from backend.compute.geopolitical_market_impact import estimate_market_impact
from backend.compute.geopolitical_event_study import (ASSET_BUCKETS, HORIZONS, MAX_EVENTS, MAX_SYMBOLS,
    MAX_REFERENCE_AGE_SECONDS, MAX_TARGET_LAG_SECONDS, analyze_symbol, compute_event_study, normalize_study_event)
from backend.compute.portfolio_protection import scenario_protection
from backend.ingest.quality import is_observed_snapshot
from backend.ingest.yfinance_ingest import fetch_market_history
from backend.agents.geopolitical_agent import GeopoliticalAgent
from backend.agents.sanctions_agent import SanctionsAgent
from backend.agents.conflict_agent import ConflictAgent
from backend.agents.energy_shock_agent import EnergyShockAgent
from backend.agents.protection_agent import ProtectionAgent
from backend.data.repositories.research_event_repo import ResearchEventRepository
from backend.data.repositories.research_market_history_repo import INTERVAL_SECONDS, SOURCE_ID, ResearchMarketHistoryRepository
from backend.services.event_reaction_service import EventReactionService
from backend.services.multi_event_reaction_service import MultiEventReactionService
from backend.data.repositories.decision_outcome_repo import DecisionOutcomeRepository

router = APIRouter(prefix="/api/geopolitical", tags=["geopolitical"])
_store = StateStore()
_research_events = ResearchEventRepository()
_research_history = ResearchMarketHistoryRepository()
_reaction_v2 = EventReactionService()
_reaction_statistics = MultiEventReactionService(outcomes=DecisionOutcomeRepository())


def _state() -> dict[str, Any]:
    try:
        raw_wits = _store.get_snapshot(WITS_AGGREGATE) or _store.get_snapshot(WITS_LATEST_LEGACY)
        return {
            "gdelt": _store.get_snapshot("gdelt:latest"),
            "wits": raw_wits if is_observed_snapshot(raw_wits) else None,
            "ofac": _store.get_snapshot(OFAC_SANCTIONS),
            "stablecoin": _store.get_snapshot("stablecoin:health:latest") or _store.get_snapshot("stablecoin:health"),
            "cross_asset": _store.get_snapshot("cross_asset:contagion:latest"),
        }
    except Exception:
        return {"provider_error": True}


def _idx() -> dict[str, Any]:
    return compute_geopolitical_index(_state())


@router.get("/index")
def geopolitical_index():
    return _idx()


@router.get("/events")
def geopolitical_events():
    return build_geopolitical_events(_idx())


def _durable_study_event(row):
    event=normalize_study_event({**row,"event_id":str(row.get("id") or row.get("event_key")),
        "authoritative_evidence":row.get("authoritative") is True,"persisted":True})
    event["study_eligible"]=row.get("study_eligible") is True
    return event


def _reaction_events(limit=MAX_EVENTS, source=None, event_family=None, event_type=None, start_ts=None, end_ts=None):
    try:
        durable=[_durable_study_event(row) for row in _research_events.list_events(limit=limit,event_family=event_family,
            event_type=event_type,source_id=source,study_eligible=True,start_ts=start_ts,end_ts=end_ts)]
    except Exception:
        durable=[]
    runtime=[{**normalize_study_event(event),"persisted":False} for event in geopolitical_events().get("events", [])[:limit]]
    seen={row["event_id"] for row in durable}
    return (durable+[row for row in runtime if row["event_id"] not in seen])[:limit]


@router.get("/reaction-lab/events")
def reaction_lab_events(limit: int=MAX_EVENTS, source: str|None=None, event_family: str|None=None,
                        event_type: str|None=None, start_ts: str|None=None, end_ts: str|None=None):
    limit=max(1,min(limit,MAX_EVENTS)); events = _reaction_events(limit,source,event_family,event_type,start_ts,end_ts)
    return {"events": events, "count": len(events), "max_events": MAX_EVENTS, "read_only": True}


@router.get("/reaction-lab/events/{event_id}")
def reaction_lab_study(event_id: str):
    try:
        durable=_research_events.get_event(event_id=event_id) or _research_events.get_event(event_key=event_id)
    except Exception:
        durable=None
    event=_durable_study_event(durable) if durable else next((row for row in _reaction_events() if row["event_id"] == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Reaction Lab event not found")
    if not event["study_eligible"]:
        raise HTTPException(status_code=422, detail={"message": "Event is not study eligible", "limitations": event["study_limitations"]})
    symbols = list(dict.fromkeys(symbol for meta in ASSET_BUCKETS.values() for symbol in meta["symbols"]))[:MAX_SYMBOLS]
    histories: dict[str, list[dict[str, Any]]] = {}
    provider_status = {}
    history_metadata = {}
    event_ts = datetime.fromisoformat(str(event["event_timestamp"]).replace("Z", "+00:00"))
    start_ts = event_ts - timedelta(seconds=MAX_REFERENCE_AGE_SECONDS)
    end_ts = event_ts + timedelta(seconds=max(HORIZONS.values()) + MAX_TARGET_LAG_SECONDS)
    # Load each crypto series once from durable storage. GET remains read-only.
    for symbol in ("BTC", "ETH", "SOL"):
        try: rows = _research_history.get_history(f"{symbol}/USD", INTERVAL_SECONDS, start_ts, end_ts, SOURCE_ID, 10000)
        except Exception: rows = []
        study = analyze_symbol(rows, event_ts)
        matured = [row for row in study.values() if row.get("status") != "not_matured"]
        # Local history is sufficient only when every matured horizon can be
        # computed under the event-study's reference-age and target-lag rules.
        if rows and all(row.get("status") == "available" for row in matured):
            histories[symbol] = rows
            history_metadata[symbol] = {"history_source": "durable_research_market_bars", "provider": "Yahoo Finance", "source_id": SOURCE_ID, "persisted": True}
            provider_status[symbol] = {"found": True, "synthetic": False, **history_metadata[symbol]}
    remote_symbols = [symbol for symbol in symbols if symbol not in histories]
    # One strict request per missing unique symbol; all horizons are derived locally.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_market_history, symbol, period="1mo", interval="5m", limit=10000): symbol for symbol in remote_symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result(timeout=30)
            except Exception as exc:
                result = {"history": [], "found": False, "synthetic": False, "error": str(exc)}
            # Strict-path defense in depth: synthetic/degraded observations are never analyzed.
            histories[symbol] = list(result.get("history") or [])[:9000] if result.get("found") and result.get("synthetic") is False else []
            history_metadata[symbol] = {"history_source": "yahoo_on_demand", "provider": "Yahoo Finance", "source_id": "yfinance_crypto_research" if symbol in {"BTC","ETH","SOL"} else None, "persisted": False}
            provider_status[symbol] = {"found": bool(histories[symbol]), "synthetic": result.get("synthetic", False), "error": result.get("error"), **history_metadata[symbol]}
    v1 = compute_event_study(event, histories, history_metadata=history_metadata)
    return {**v1, "provider_status": provider_status, "unique_symbol_count": len(symbols), **_reaction_v2.build(event)}


@router.get("/reaction-lab/statistics")
def reaction_lab_statistics(event_family: str|None=None, event_type: str|None=None, source: str|None=None,
                            claim_type: str|None=None, event_time_basis: str|None=None,
                            start_ts: str|None=None, end_ts: str|None=None, limit: int=100,
                            overlap_policy: str="same_series_nonoverlap_v1", include_decisions: bool=True):
    """Recompute a bounded local study; this GET performs no ingestion or writes."""
    if overlap_policy != "same_series_nonoverlap_v1":
        raise HTTPException(status_code=422, detail="Unsupported overlap policy")
    return _reaction_statistics.build(event_family=event_family, event_type=event_type, source_id=source,
        claim_type=claim_type, event_time_basis=event_time_basis, start_ts=start_ts, end_ts=end_ts,
        limit=limit, overlap_policy=overlap_policy, include_decisions=include_decisions)


@router.get("/sanctions")
def sanctions():
    s = _state()
    return score_sanctions(gdelt=s.get("gdelt"), ofac=s.get("ofac"), wits=s.get("wits"))


@router.get("/sanctions/impact")
def sanctions_market_impact():
    return sanctions_impact(sanctions())


@router.get("/sanctions/entities")
def sanctions_entity_feed():
    return sanctions_entities(_state().get("ofac"))


@router.get("/conflicts")
def conflicts():
    return score_conflicts(_state().get("gdelt"))


@router.get("/conflict/hotspots")
def conflict_hotspots():
    c = conflicts()
    return {"hotspots": c.get("hotspots", []), "data_quality": c.get("data_quality", "degraded"), "timestamp": c.get("timestamp")}


@router.get("/conflict/escalation")
def conflict_escalation():
    c = conflicts()
    return {"conflict_score": c.get("conflict_score", 0), "severity": c.get("severity", "watch"), "hotspots": c.get("hotspots", []), "data_quality": c.get("data_quality", "degraded"), "timestamp": c.get("timestamp")}


@router.get("/conflict/market-impact")
def conflict_impact():
    return conflict_market_impact(conflicts())


@router.get("/chokepoints")
def chokepoints():
    return score_chokepoints(_state().get("gdelt"))


@router.get("/shipping-risk")
def shipping_risk():
    c = chokepoints()
    return {"shipping_score": c.get("shipping_score", 0), "chokepoints": c.get("chokepoints", []), "data_quality": c.get("data_quality", "degraded"), "timestamp": c.get("timestamp")}


@router.get("/supply-chain-impact")
def supply_chain():
    return supply_chain_impact(chokepoints())


@router.get("/energy-shock")
def energy_shock():
    return score_energy_shock(_state().get("gdelt"), sanctions())


@router.get("/commodity-impact")
def commodity_impact():
    e = energy_shock()
    rows = [{"asset": a, "impact_score": e.get("energy_shock_score", 0), "direction": "bullish" if a in {"XLE", "XOM", "CVX", "USO", "GLD", "SLV"} else "bearish" if a in {"BTC", "ETH", "SOL"} else "mixed", "reason": "Energy/commodity geopolitical shock proxy"} for a in e.get("affected_assets", [])]
    return {"impacts": rows, "count": len(rows), "data_quality": e.get("data_quality", "degraded"), "timestamp": e.get("timestamp")}


@router.get("/market-impact")
def market_impact():
    events = geopolitical_events().get("events", [])
    return estimate_market_impact(_idx(), events)


SCENARIO_TEMPLATES = [
    "Middle East escalation", "Russia sanctions expansion", "Taiwan semiconductor shock", "Red Sea shipping disruption", "Strait of Hormuz oil shock", "China export-control shock", "cyberattack on financial infrastructure", "election/policy shock", "global risk-off cascade", "stablecoin liquidity shock",
]


@router.get("/scenario-templates")
def scenario_templates():
    return {"templates": [{"name": n, "severity": 65 if i < 5 else 55, "regions": ["Global"], "data_quality": "demo"} for i, n in enumerate(SCENARIO_TEMPLATES)], "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/scenario-run")
def scenario_run(body: dict[str, Any] | None = None):
    body = body or {}
    base = _idx()
    severity = float(body.get("severity", 65) or 65)
    shocks = sum(float(body.get(k, 0) or 0) for k in ["tariff_shock", "sanctions_shock", "conflict_shock", "energy_shock", "shipping_shock", "cyber_policy_shock", "stablecoin_stress", "liquidity_depth_drop", "volatility_spike"])
    scenario_score = min(100.0, max(base.get("overall_score", 40), severity + shocks * 0.4))
    scenario_index = {**base, "overall_score": scenario_score, "regime": "crisis" if scenario_score >= 85 else "high_risk" if scenario_score >= 70 else "elevated", "data_quality": base.get("data_quality", "degraded")}
    events = build_geopolitical_events(scenario_index).get("events", [])
    impacts = estimate_market_impact(scenario_index, events).get("impacts", [])
    protection = scenario_protection({**body, "severity": scenario_score, "data_quality": scenario_index.get("data_quality")}, scenario_index)
    agent_signals = _geo_signals(scenario_index, protection)
    return {"portfolio_pnl_impact": round(-100000 * scenario_score / 100 * 0.08, 2), "affected_assets": sorted({a for r in impacts[:20] for a in [r["asset"]]}), "market_impact_table": impacts, "agent_signals": agent_signals, "hedge_suggestions": protection.get("hedge_suggestions", []), "allocation_changes": {"cash": round(0.1 + scenario_score / 300, 4), "risk_assets": round(max(0, 0.8 - scenario_score / 180), 4)}, "execution_warnings": ["proposal-only scenario", "use conservative paper execution previews"], "protection_mode": protection.get("protection_mode"), "suggested_risk_posture": "defensive" if scenario_score >= 65 else "watch", "conditional_order_suggestions": protection.get("stop_loss_or_bracket_order_suggestions", []), "confidence": scenario_index.get("confidence", 0.55), "reasoning": ["Scenario combines user shocks with current geopolitical index", "No orders submitted"], "data_quality": scenario_index.get("data_quality", "degraded"), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/agents/signals")
def geopolitical_agent_signals():
    idx = _idx()
    return {"signals": _geo_signals(idx), "agent_count": 5, "timestamp": datetime.now(timezone.utc).isoformat()}


def _geo_signals(index: dict[str, Any], protection: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    protection = protection or scenario_protection({"severity": index.get("overall_score", 0), "data_quality": index.get("data_quality", "degraded")}, index)
    return (
        GeopoliticalAgent().evaluate(index)
        + SanctionsAgent().evaluate(index)
        + ConflictAgent().evaluate(index)
        + EnergyShockAgent().evaluate(index)
        + ProtectionAgent().evaluate({**index, **protection})
    )


def _report(kind: str) -> dict[str, Any]:
    idx = _idx()
    events = geopolitical_events().get("events", [])[:5]
    protection = scenario_protection({"severity": idx.get("overall_score", 0), "data_quality": idx.get("data_quality")}, idx)
    details = idx.get("component_details", {})
    sections = [
        {"title": "Top Drivers", "items": [d["driver"] for d in idx.get("top_drivers", [])]},
        {"title": "Sanctions Risk Brief", "items": [p.get("program") for p in details.get("sanctions", {}).get("programs", [])[:4]]},
        {"title": "Conflict Escalation Brief", "items": [h.get("region") for h in details.get("conflicts", {}).get("hotspots", [])[:4]]},
        {"title": "Energy/Shipping Shock Brief", "items": [c.get("name") for c in details.get("shipping", {}).get("chokepoints", [])[:4]] + details.get("energy", {}).get("affected_assets", [])[:4]},
        {"title": "Portfolio Protection Brief", "items": protection.get("recommended_actions", [])},
    ]
    return {"report_type": kind, "headline": f"{kind.replace('_', ' ').title()}: {idx.get('regime')} regime", "risk_regime": idx.get("regime"), "top_events": events, "affected_assets": idx.get("affected_assets", [])[:20], "portfolio_protection_suggestions": protection.get("recommended_actions", []), "agent_consensus": "proposal-only geopolitical risk posture", "data_quality": idx.get("data_quality", "degraded"), "limitations": ["Research/development only", "Not legal, financial, or investment advice", "Fallback data may be degraded"], "sections": sections, "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/reports/daily-brief")
def daily_brief():
    return _report("daily_geopolitical_risk_brief")


@router.get("/reports/protection-brief")
def protection_brief():
    return _report("portfolio_protection_brief")
