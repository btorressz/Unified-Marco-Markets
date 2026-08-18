from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.compute.geopolitical_evidence import proxy_evidence

SANCTIONS_PROGRAMS = {
    "Russia/Ukraine": {"score": 68, "countries": ["Russia", "Ukraine"], "assets": ["XLE", "XOM", "CVX", "DBA", "ITA", "GLD"], "sectors": ["Energy", "Fertilizer", "Wheat", "Defense"], "terms": ["russia", "ukraine", "sanction"]},
    "China export controls": {"score": 72, "countries": ["China", "Taiwan", "United States"], "assets": ["SMH", "SOXX", "QQQ", "AAPL", "NVDA", "AMD", "TSLA"], "sectors": ["Semiconductors", "Technology", "Hardware"], "terms": ["china", "taiwan", "export control", "semiconductor"]},
    "Iran/Middle East": {"score": 63, "countries": ["Iran", "Israel", "Saudi Arabia"], "assets": ["USO", "XLE", "XOM", "CVX", "ITA", "GLD"], "sectors": ["Oil", "Shipping", "Defense"], "terms": ["iran", "israel", "middle east", "sanction"]},
    "Financial sanctions": {"score": 55, "countries": ["Global"], "assets": ["BTC", "ETH", "SOL", "USDC", "USDT", "DAI"], "sectors": ["Banking", "Crypto", "Liquidity"], "terms": ["financial sanctions", "bank sanctions", "asset freeze"]},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _severity(score: float) -> str:
    return "critical" if score >= 85 else "high" if score >= 70 else "medium" if score >= 45 else "low"


def score_sanctions(gdelt: dict[str, Any] | None = None, ofac: dict[str, Any] | None = None, wits: dict[str, Any] | None = None) -> dict[str, Any]:
    degraded = not gdelt and not ofac
    tone = abs(float((gdelt or {}).get("avg_tone", (gdelt or {}).get("tone", -2.0)) or -2.0))
    shock = abs(float((gdelt or {}).get("shock_score", 0.6) or 0.6))
    tariff = float((wits or {}).get("tariff_pressure", (wits or {}).get("value", 35.0)) or 35.0)
    ofac_delta = float((ofac or {}).get("new_entities", 0) or 0)
    base = min(100.0, 35 + tone * 4 + shock * 8 + tariff * 0.15 + min(ofac_delta, 20) * 1.5)
    programs = []
    for name, meta in SANCTIONS_PROGRAMS.items():
        score = min(100.0, meta["score"] * 0.65 + base * 0.35)
        evidence = proxy_evidence(
            gdelt=gdelt,
            terms=meta["terms"],
            static_mapping=f"sanctions_program:{name}",
            authoritative_evidence=bool(ofac),
        )
        programs.append({
            "program": name,
            "risk_score": round(score, 2),
            "severity": _severity(score),
            "countries": meta["countries"],
            "affected_assets": meta["assets"],
            "affected_sectors": meta["sectors"],
            "reasoning": ["Sanctions/export-control proxy from GDELT tone/shock and tariff pressure", "Static program/exposure mapping is deterministic research context"],
            "data_quality": "degraded" if degraded else "ok",
            **evidence,
        })
    authoritative_observed = bool(ofac) and ofac_delta > 0
    return {
        "sanctions_score": round(base, 2),
        "severity": _severity(base),
        "programs": programs,
        "new_sanctions": authoritative_observed,
        "entity_additions": int(ofac_delta),
        "entity_removals": int((ofac or {}).get("removed_entities", 0) or 0),
        "provider_status": {"gdelt": "ok" if gdelt else "degraded", "ofac_public_download": "ok" if ofac else "not_configured"},
        "data_quality": "degraded" if degraded else "ok",
        "degraded": degraded,
        "claim_type": "observed_evidence" if authoritative_observed else "proxy",
        "observed": authoritative_observed,
        "authoritative_evidence": bool(ofac),
        "evidence_basis": "ofac_plus_context" if ofac else "gdelt_aggregate_and_static_program_mappings",
        "limitations": [] if ofac else ["No authoritative sanctions feed is attached; program-level outputs are research proxies."],
        "timestamp": _now(),
    }


def sanctions_entities(ofac: dict[str, Any] | None = None) -> dict[str, Any]:
    degraded = not ofac
    entities = (ofac or {}).get("entities") or [
        {"name": "Demo Energy Shipping Entity", "program": "Iran/Middle East", "country": "Global", "change": "watch"},
        {"name": "Demo Semiconductor Export Control Entity", "program": "China export controls", "country": "China", "change": "watch"},
        {"name": "Demo Financial Restrictions Entity", "program": "Financial sanctions", "country": "Global", "change": "watch"},
    ]
    return {
        "entities": entities,
        "count": len(entities),
        "degraded": degraded,
        "data_quality": "degraded" if degraded else "ok",
        "claim_type": "static_mapping" if degraded else "observed_evidence",
        "observed": not degraded,
        "authoritative_evidence": not degraded,
        "limitations": ["Demo entities are static research examples, not observed sanctioned entities."] if degraded else [],
        "timestamp": _now(),
    }


def sanctions_impact(score: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for program in score.get("programs", []):
        direction = "bearish" if program["risk_score"] >= 55 else "neutral"
        for asset in program.get("affected_assets", []):
            rows.append({
                "asset": asset,
                "program": program["program"],
                "impact_score": program["risk_score"],
                "direction": direction,
                "suggested_risk_action": "reduce_or_hedge" if direction == "bearish" else "monitor",
                "reason": f"{program['program']} maps to {asset}",
                "claim_type": "expected_market_impact",
                "observed_market_reaction": False,
                "causal_claim": False,
                "evidence_basis": program.get("evidence_basis"),
            })
    return {"impacts": rows, "count": len(rows), "timestamp": _now(), "data_quality": score.get("data_quality", "degraded"), "claim_type": "expected_market_impact", "observed_market_reaction": False, "causal_claim": False}
