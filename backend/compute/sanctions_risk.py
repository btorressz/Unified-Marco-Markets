from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.compute.geopolitical_evidence import proxy_evidence
from backend.ingest.quality import is_authoritative_observation

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
    authoritative = is_authoritative_observation(ofac, source_id="ofac_sanctions")
    degraded = not gdelt and not authoritative
    tone = abs(float((gdelt or {}).get("avg_tone", (gdelt or {}).get("tone", -2.0)) or -2.0))
    shock = abs(float((gdelt or {}).get("shock_score", 0.6) or 0.6))
    tariff = float((wits or {}).get("tariff_pressure", (wits or {}).get("value", 35.0)) or 35.0)
    ofac_delta = float((ofac or {}).get("added_count", 0) or 0) if authoritative and (ofac or {}).get("changes_available") else 0.0
    base = min(100.0, 35 + tone * 4 + shock * 8 + tariff * 0.15 + min(ofac_delta, 20) * 1.5)
    programs = []
    for name, meta in SANCTIONS_PROGRAMS.items():
        score = min(100.0, meta["score"] * 0.65 + base * 0.35)
        evidence = proxy_evidence(
            gdelt=gdelt,
            terms=meta["terms"],
            static_mapping=f"sanctions_program:{name}",
            # An OFAC snapshot cannot substantiate these broader static program
            # mappings; authority remains attached only to normalized records
            # and deterministic dataset deltas.
            authoritative_evidence=False,
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
    authoritative_observed = authoritative and ofac_delta > 0
    return {
        "sanctions_score": round(base, 2),
        "severity": _severity(base),
        "programs": programs,
        "new_sanctions": authoritative_observed,
        "entity_additions": int(ofac_delta),
        "entity_updates": int((ofac or {}).get("updated_count", 0) or 0) if authoritative else 0,
        "entity_removals": int((ofac or {}).get("removed_count", 0) or 0) if authoritative else 0,
        "authoritative_changes": list((ofac or {}).get("recent_changes", []))[:100] if authoritative else [],
        "provider_status": {"gdelt": "ok" if gdelt else "degraded", "ofac_public_download": (ofac or {}).get("provider_status", "not_configured") if authoritative else "not_configured"},
        "data_quality": "degraded" if degraded else "ok",
        "degraded": degraded,
        "claim_type": "observed_evidence" if authoritative_observed else "proxy",
        "observed": authoritative_observed,
        "authoritative_evidence": authoritative,
        "evidence_basis": "ofac_plus_context" if authoritative else "gdelt_aggregate_and_static_program_mappings",
        "limitations": [] if authoritative else ["No authoritative sanctions feed is attached; program-level outputs are research proxies."],
        "timestamp": _now(),
    }


def sanctions_entities(ofac: dict[str, Any] | None = None) -> dict[str, Any]:
    authoritative = is_authoritative_observation(ofac, source_id="ofac_sanctions")
    degraded = not authoritative
    entities = (ofac or {}).get("recent_changes", []) if authoritative else []
    return {
        "entities": entities,
        "count": len(entities),
        "degraded": degraded,
        "data_quality": "degraded" if degraded else "ok",
        "claim_type": "proxy" if degraded else "observed_evidence",
        "observed": authoritative,
        "authoritative_evidence": authoritative,
        "provider_status": (ofac or {}).get("provider_status", "not_configured") if authoritative else "not_configured",
        "limitations": ["Authoritative current OFAC entity changes are unavailable; no demo entities are substituted."] if degraded else [],
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
