from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.compute.geopolitical_evidence import proxy_evidence

CHOKEPOINTS = [
    ("Red Sea / Suez Canal", "Middle East / Europe", ["Shipping", "Oil", "Retail Importers", "Inflation"], ["USO", "XLE", "XRT", "WMT", "NKE"], ["red sea", "suez", "yemen"]),
    ("Strait of Hormuz", "Persian Gulf", ["Crude Oil", "LNG", "Inflation"], ["USO", "XLE", "XOM", "CVX", "GLD"], ["hormuz", "iran", "persian gulf"]),
    ("Taiwan Strait", "East Asia", ["Semiconductors", "Technology", "Hardware"], ["SMH", "SOXX", "QQQ", "AAPL", "NVDA", "AMD"], ["taiwan", "taiwan strait"]),
    ("Panama Canal", "Central America", ["Shipping", "Food", "Industrial Supply Chain"], ["XLI", "XRT", "DBA", "CAT", "DE"], ["panama canal", "panama"]),
    ("Black Sea", "Eastern Europe", ["Wheat", "Fertilizer", "Energy"], ["DBA", "XLE", "NUE", "STLD"], ["black sea", "ukraine", "russia"]),
    ("South China Sea", "East Asia", ["Shipping", "Semiconductors", "Technology"], ["SMH", "SOXX", "QQQ", "AAPL"], ["south china sea", "china"]),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _severity(score: float) -> str:
    return "critical" if score >= 85 else "high" if score >= 70 else "medium" if score >= 45 else "low"


def score_chokepoints(gdelt: dict[str, Any] | None = None) -> dict[str, Any]:
    degraded = not gdelt
    shock = abs(float((gdelt or {}).get("shock_score", 0.7) or 0.7))
    tone = abs(float((gdelt or {}).get("avg_tone", (gdelt or {}).get("tone", -2.0)) or -2.0))
    base = min(100.0, 24 + shock * 10 + tone * 3.5)
    rows = []
    for i, (name, region, sectors, assets, terms) in enumerate(CHOKEPOINTS):
        score = min(100.0, base + (i % 3) * 7)
        evidence = proxy_evidence(gdelt=gdelt, terms=terms, static_mapping=f"chokepoint:{name}")
        evidence["limitations"] = list(evidence.get("limitations", [])) + [
            "Contextual evidence does not establish an observed chokepoint closure or disruption."
        ]
        rows.append({
            "name": name, "region": region, "risk_score": round(score, 2), "severity": _severity(score),
            "affected_sectors": sectors, "affected_assets": assets,
            "market_impact": "higher shipping/energy costs and broader risk-off pressure",
            "reasoning": ["Chokepoint risk uses GDELT shock/tone proxies", "Chokepoint/exposure mapping is deterministic research context"],
            "data_quality": "degraded" if degraded else "ok", **evidence,
        })
    return {
        "chokepoints": rows, "shipping_score": round(max(r["risk_score"] for r in rows), 2),
        "degraded": degraded, "data_quality": "degraded" if degraded else "ok",
        "claim_type": "proxy", "observed": False,
        "evidence_basis": "gdelt_aggregate_with_optional_document_support",
        "limitations": ["Chokepoint risk is a vulnerability proxy and does not establish an observed closure or disruption."],
        "timestamp": _now(),
    }


def score_energy_shock(gdelt: dict[str, Any] | None = None, sanctions: dict[str, Any] | None = None) -> dict[str, Any]:
    degraded = not gdelt and not sanctions
    shock = abs(float((gdelt or {}).get("shock_score", 0.75) or 0.75))
    sanction_score = float((sanctions or {}).get("sanctions_score", 45.0) or 45.0)
    oil = min(100.0, 30 + shock * 12 + sanction_score * 0.35)
    gas = min(100.0, 25 + shock * 10 + sanction_score * 0.30)
    fertilizer = min(100.0, 20 + shock * 8 + sanction_score * 0.25)
    minerals = min(100.0, 22 + shock * 7 + sanction_score * 0.22)
    overall = max(oil, gas, fertilizer, minerals)
    return {
        "energy_shock_score": round(overall, 2), "oil_shock_score": round(oil, 2),
        "natural_gas_shock_score": round(gas, 2), "fertilizer_food_shock": round(fertilizer, 2),
        "critical_minerals_shock": round(minerals, 2),
        "affected_assets": ["XLE", "XOM", "CVX", "USO", "GLD", "SLV", "DBA", "FCX", "NUE", "STLD", "BTC", "ETH", "SOL", "USDC", "USDT", "DAI"],
        "severity": _severity(overall),
        "reasoning": ["Energy shock combines geopolitical shock and sanctions pressure", "Output is a deterministic research proxy, not an observed commodity disruption"],
        "degraded": degraded, "data_quality": "degraded" if degraded else "ok",
        "claim_type": "proxy", "observed": False, "authoritative_evidence": False,
        "evidence_basis": "geopolitical_and_sanctions_proxy_scores",
        "limitations": ["No authoritative physical energy-supply disruption feed is attached."],
        "timestamp": _now(),
    }


def supply_chain_impact(chokepoints: dict[str, Any]) -> dict[str, Any]:
    impacts = []
    for c in chokepoints.get("chokepoints", []):
        impacts.append({
            "chokepoint": c["name"], "risk_score": c["risk_score"], "affected_sectors": c["affected_sectors"],
            "affected_assets": c["affected_assets"], "suggested_risk_action": "hedge_or_reduce_import_sensitive_exposure" if c["risk_score"] >= 55 else "monitor",
            "claim_type": "expected_market_impact", "observed_market_reaction": False, "causal_claim": False,
            "evidence_basis": c.get("evidence_basis"),
        })
    return {"impacts": impacts, "timestamp": _now(), "data_quality": chokepoints.get("data_quality", "degraded"), "claim_type": "expected_market_impact", "observed_market_reaction": False, "causal_claim": False}
