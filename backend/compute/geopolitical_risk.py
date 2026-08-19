from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from backend.compute.sanctions_risk import score_sanctions
from backend.compute.conflict_escalation import score_conflicts, normalized_conflict_events
from backend.compute.shipping_energy_risk import score_chokepoints, score_energy_shock
from backend.ingest.quality import is_observed_snapshot
from backend.ingest.quality import is_authoritative_observation


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _regime(score: float) -> str:
    return "crisis" if score >= 85 else "high_risk" if score >= 70 else "elevated" if score >= 50 else "watch" if score >= 30 else "calm"


def _sev(score: float) -> str:
    return "critical" if score >= 85 else "high" if score >= 70 else "medium" if score >= 45 else "low"


def compute_geopolitical_index(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or {}
    gdelt = state.get("gdelt")
    raw_wits = state.get("wits")
    wits = raw_wits if is_observed_snapshot(raw_wits) else None
    stable = state.get("stablecoin") or {}
    cross = state.get("cross_asset") or {}
    sanctions = score_sanctions(gdelt=gdelt, ofac=state.get("ofac"), wits=wits)
    conflicts = score_conflicts(gdelt=gdelt)
    shipping = score_chokepoints(gdelt=gdelt)
    energy = score_energy_shock(gdelt=gdelt, sanctions=sanctions)
    tariff_score = _clamp(float((wits or {}).get("tariff_pressure", (wits or {}).get("value", state.get("tariff_score", 35.0))) or 35.0))
    tone = abs(float((gdelt or {}).get("avg_tone", (gdelt or {}).get("tone", -2.0)) or -2.0))
    cyber_policy_score = _clamp(25 + tone * 5 + sanctions["sanctions_score"] * 0.20)
    stable_stress = _clamp(abs(float(stable.get("depeg_bps", state.get("stablecoin_stress", 5.0)) or 5.0)) * 2)
    risk_off = _clamp(float(cross.get("contagion_score", state.get("cross_asset_risk_off", 35.0)) or 35.0))
    market_stress = _clamp(stable_stress * 0.45 + risk_off * 0.55)
    components = {
        "tariff_score": tariff_score,
        "sanctions_score": sanctions["sanctions_score"],
        "conflict_score": conflicts["conflict_score"],
        "shipping_score": shipping["shipping_score"],
        "energy_score": energy["energy_shock_score"],
        "cyber_policy_score": cyber_policy_score,
        "market_stress_score": market_stress,
    }
    weights = {"tariff_score": .12, "sanctions_score": .16, "conflict_score": .18, "shipping_score": .13, "energy_score": .14, "cyber_policy_score": .12, "market_stress_score": .15}
    overall = _clamp(sum(components[k] * weights[k] for k in components))
    degraded = not gdelt or not wits
    regional = {h["region"]: h["risk_score"] for h in conflicts.get("hotspots", [])}
    regional.update({c["name"]: c["risk_score"] for c in shipping.get("chokepoints", [])[:3]})
    top = sorted(components.items(), key=lambda kv: kv[1], reverse=True)[:5]
    affected = sorted({a for h in conflicts.get("hotspots", []) for a in h.get("assets", [])} | {a for c in shipping.get("chokepoints", []) for a in c.get("affected_assets", [])} | set(energy.get("affected_assets", [])))
    confidence = 0.55 if degraded else 0.78
    evidence_count = int((gdelt or {}).get("evidence_count", 0) or 0)
    return {
        "overall_score": round(overall, 2), "regime": _regime(overall), **{k: round(v, 2) for k, v in components.items()},
        "regional_breakdown": regional, "top_drivers": [{"driver": k, "score": round(v, 2)} for k, v in top], "affected_assets": affected,
        "confidence": confidence, "data_quality": "degraded" if degraded else "healthy",
        "provider_status": {"gdelt": "ok" if gdelt else "degraded", "wits": "ok" if wits else "degraded", "ofac_public_download": (state.get("ofac") or {}).get("provider_status", "not_configured") if is_authoritative_observation(state.get("ofac"), source_id="ofac_sanctions") else "not_configured"},
        "claim_type": "composite_research_proxy", "observed": False, "proxy": True,
        "evidence_basis": "weighted_proxy_components_with_source_context",
        "evidence_count": evidence_count,
        "authoritative_component_evidence": is_authoritative_observation(state.get("ofac"), source_id="ofac_sanctions"),
        "limitations": ["The composite index is a deterministic research proxy; it is not itself an observed geopolitical event."],
        "reasoning": ["Weighted index combines sanctions, conflict, shipping, energy, cyber/policy, tariff, and market stress components", "All outputs are informational/proposal-only; no autonomous trading"], "timestamp": _now(),
        "component_details": {"sanctions": sanctions, "conflicts": conflicts, "shipping": shipping, "energy": energy},
    }


def _evidence_fields(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "claim_type", "observed", "proxy", "scenario", "authoritative_evidence",
        "evidence_basis", "evidence_count", "evidence_ids", "evidence_quality", "limitations",
    )
    return {key: item.get(key) for key in keys if key in item}


def build_geopolitical_events(index: dict[str, Any]) -> dict[str, Any]:
    details = index.get("component_details", {})
    events = []
    events.extend(normalized_conflict_events(details.get("conflicts", {})))
    sanctions = details.get("sanctions", {})
    for change in sanctions.get("authoritative_changes", [])[:10]:
        change_type = str(change.get("change_type") or "UPDATED").upper()
        detected_at = change.get("change_detected_at")
        uid = str(change.get("source_record_id") or "unknown")
        events.append({
            "event_id": _event_id(f"OFAC_{change_type}", f"{uid}|{detected_at}"),
            "event_type": f"OFAC_SANCTION_{change_type}",
            "title": f"OFAC SDN {change_type.lower()}: {change.get('entity_name') or uid}",
            "source": "OFAC", "source_id": "ofac_sanctions", "source_record_id": uid,
            "change_type": change_type, "event_timestamp": detected_at,
            "event_time_basis": "provider_change_detected_at_retrieval",
            "programs": list(change.get("programs") or []),
            "countries": sorted(set((change.get("nationalities") or []) + (change.get("citizenships") or []))),
            "region": " / ".join((change.get("nationalities") or [])[:2]) or "Global",
            "severity": sanctions.get("severity", "medium"), "affected_sectors": [], "affected_assets": [],
            "claim_type": "observed_evidence", "observed": True, "proxy": False,
            "authoritative_evidence": True, "evidence_basis": "normalized_authoritative_provider_record",
            "limitations": [], "data_quality": "ok",
        })
    for p in sanctions.get("programs", [])[:4]:
        events.append({
            "event_id": _event_id("SANCTIONS", p["program"]),
            "event_type": "SANCTIONS" if "export" not in p["program"].lower() else "EXPORT_CONTROL",
            "title": f"{p['program']} sanctions/export-control watch", "region": p["program"], "countries": p["countries"],
            "severity": p["severity"], "confidence": index.get("confidence", 0.55),
            "source": "GDELT contextual evidence" if p.get("evidence_count") else "static sanctions research proxy",
            "event_timestamp": index.get("timestamp"), "event_time_basis": "research_proxy_computed_at", "data_timestamp": index.get("timestamp"),
            "affected_sectors": p["affected_sectors"], "affected_assets": p["affected_assets"],
            "reasoning": p["reasoning"], "data_quality": p["data_quality"], **_evidence_fields(p),
        })
    for c in details.get("shipping", {}).get("chokepoints", [])[:4]:
        events.append({
            "event_id": _event_id("SHIPPING", c["name"]), "event_type": "SHIPPING_DISRUPTION",
            "title": f"{c['name']} chokepoint stress", "region": c["region"], "countries": [c["region"]],
            "severity": c["severity"], "confidence": index.get("confidence", 0.55),
            "source": "GDELT contextual evidence" if c.get("evidence_count") else "static chokepoint research proxy",
            "event_timestamp": index.get("timestamp"), "event_time_basis": "research_proxy_computed_at", "data_timestamp": index.get("timestamp"),
            "affected_sectors": c["affected_sectors"], "affected_assets": c["affected_assets"],
            "reasoning": c["reasoning"], "data_quality": c["data_quality"], **_evidence_fields(c),
        })
    energy = details.get("energy", {})
    events.append({
        "event_id": _event_id("ENERGY", "monitor"), "event_type": "ENERGY_SHOCK",
        "title": "Energy / commodity shock monitor", "region": "Global", "countries": ["Global"],
        "severity": energy.get("severity", "medium"), "confidence": index.get("confidence", 0.55),
        "source": "geopolitical proxy model", "event_timestamp": index.get("timestamp"), "event_time_basis": "research_proxy_computed_at", "data_timestamp": index.get("timestamp"),
        "affected_sectors": ["Energy", "Food", "Critical Minerals"], "affected_assets": energy.get("affected_assets", []),
        "reasoning": energy.get("reasoning", []), "data_quality": energy.get("data_quality", "degraded"), **_evidence_fields(energy),
    })
    return {
        "events": events, "count": len(events), "data_quality": index.get("data_quality", "degraded"),
        "claim_boundary": "Events may be observed evidence, evidence-supported proxies, or static proxies; inspect claim_type and evidence fields.",
        "timestamp": _now(),
    }


def _event_id(kind: str, key: str) -> str:
    return hashlib.sha1(f"{kind}|{key}".encode()).hexdigest()[:12]
