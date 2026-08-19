from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.compute.geopolitical_evidence import proxy_evidence

HOTSPOTS = [
    {"region": "Middle East", "countries": ["Iran", "Israel", "Saudi Arabia"], "assets": ["USO", "XLE", "XOM", "CVX", "ITA", "GLD"], "sectors": ["Oil", "Defense", "Airlines", "Inflation"], "terms": ["iran", "israel", "middle east"]},
    {"region": "Taiwan Strait", "countries": ["China", "Taiwan", "United States"], "assets": ["SMH", "SOXX", "QQQ", "AAPL", "NVDA", "AMD"], "sectors": ["Semiconductors", "Technology"], "terms": ["taiwan", "taiwan strait", "china"]},
    {"region": "Russia/Ukraine", "countries": ["Russia", "Ukraine", "Europe"], "assets": ["XLE", "DBA", "ITA", "GLD"], "sectors": ["Energy", "Wheat", "Fertilizer", "Defense"], "terms": ["russia", "ukraine"]},
    {"region": "Red Sea / Suez", "countries": ["Yemen", "Egypt", "Global"], "assets": ["USO", "XLE", "XRT", "WMT", "NKE"], "sectors": ["Shipping", "Oil", "Retail Imports"], "terms": ["red sea", "suez", "yemen"]},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _severity(score: float) -> str:
    return "crisis" if score >= 85 else "high" if score >= 70 else "elevated" if score >= 45 else "watch"


def score_conflicts(gdelt: dict[str, Any] | None = None) -> dict[str, Any]:
    degraded = not gdelt
    shock = abs(float((gdelt or {}).get("shock_score", 0.8) or 0.8))
    tone = abs(float((gdelt or {}).get("avg_tone", (gdelt or {}).get("tone", -2.5)) or -2.5))
    volume = float((gdelt or {}).get("event_volume", (gdelt or {}).get("count", 12)) or 12)
    base = min(100.0, 28 + shock * 12 + tone * 4 + min(volume, 100) * 0.25)
    hotspots = []
    for i, h in enumerate(HOTSPOTS):
        score = min(100.0, base + i * 3)
        evidence = proxy_evidence(gdelt=gdelt, terms=h["terms"], static_mapping=f"conflict_hotspot:{h['region']}")
        hotspots.append({
            "region": h["region"], "countries": h["countries"], "assets": h["assets"], "sectors": h["sectors"],
            "risk_score": round(score, 2), "severity": _severity(score),
            "reasoning": ["GDELT-style conflict tone/event-volume proxy", "Hotspot and exposure mapping is deterministic research context"],
            "data_quality": "degraded" if degraded else "ok", **evidence,
        })
    return {
        "conflict_score": round(base, 2), "severity": _severity(base), "hotspots": hotspots,
        "degraded": degraded, "data_quality": "degraded" if degraded else "ok",
        "claim_type": "proxy", "observed": False,
        "evidence_basis": "gdelt_aggregate_with_optional_document_support",
        "limitations": ["Conflict scores are research proxies and do not establish an observed military escalation."],
        "timestamp": _now(),
    }


def normalized_conflict_events(conflicts: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for h in conflicts.get("hotspots", []):
        events.append({
            "event_id": f"conflict-{h['region'].lower().replace(' ', '-')}", "event_type": "CONFLICT_ESCALATION",
            "title": f"{h['region']} escalation watch", "region": h["region"], "countries": h["countries"],
            "severity": h["severity"], "confidence": 0.62 if conflicts.get("degraded") else 0.78,
            "source": "GDELT contextual evidence" if h.get("evidence_count") else "GDELT aggregate proxy",
            "event_timestamp": conflicts.get("timestamp"), "event_time_basis": "research_proxy_computed_at", "data_timestamp": conflicts.get("timestamp"),
            "affected_sectors": h["sectors"], "affected_assets": h["assets"], "reasoning": h["reasoning"],
            "data_quality": h["data_quality"],
            **{k: h.get(k) for k in ("claim_type", "observed", "proxy", "scenario", "authoritative_evidence", "evidence_basis", "evidence_count", "evidence_ids", "evidence_quality", "limitations")},
        })
    return events


def conflict_market_impact(conflicts: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for h in conflicts.get("hotspots", []):
        for asset in h["assets"]:
            rows.append({
                "asset": asset, "region": h["region"], "impact_score": h["risk_score"],
                "direction": "bullish" if asset in {"GLD", "ITA", "XLE", "XOM", "CVX", "USO"} else "bearish",
                "reason": f"{h['region']} risk maps to {asset}", "claim_type": "expected_market_impact",
                "observed_market_reaction": False, "causal_claim": False, "evidence_basis": h.get("evidence_basis"),
            })
    return {"impacts": rows, "count": len(rows), "timestamp": _now(), "data_quality": conflicts.get("data_quality", "degraded"), "claim_type": "expected_market_impact", "observed_market_reaction": False, "causal_claim": False}
