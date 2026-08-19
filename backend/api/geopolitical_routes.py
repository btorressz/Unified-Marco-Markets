from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter

from backend.core.state_keys import OFAC_SANCTIONS, WITS_AGGREGATE, WITS_LATEST_LEGACY
from backend.core.state_store import StateStore
from backend.compute.geopolitical_risk import compute_geopolitical_index, build_geopolitical_events
from backend.compute.sanctions_risk import score_sanctions, sanctions_impact, sanctions_entities
from backend.compute.conflict_escalation import score_conflicts, conflict_market_impact
from backend.compute.shipping_energy_risk import score_chokepoints, score_energy_shock, supply_chain_impact
from backend.compute.geopolitical_market_impact import estimate_market_impact
from backend.compute.portfolio_protection import scenario_protection
from backend.ingest.quality import is_observed_snapshot
from backend.agents.geopolitical_agent import GeopoliticalAgent
from backend.agents.sanctions_agent import SanctionsAgent
from backend.agents.conflict_agent import ConflictAgent
from backend.agents.energy_shock_agent import EnergyShockAgent
from backend.agents.protection_agent import ProtectionAgent

router = APIRouter(prefix="/api/geopolitical", tags=["geopolitical"])
_store = StateStore()


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
