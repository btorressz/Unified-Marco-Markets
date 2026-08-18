from __future__ import annotations

import hashlib
from typing import Any, Iterable


CLAIM_OBSERVED = "observed_evidence"
CLAIM_EVIDENCE_SUPPORTED_PROXY = "evidence_supported_proxy"
CLAIM_PROXY = "proxy"
CLAIM_STATIC_MAPPING = "static_mapping"
CLAIM_SCENARIO = "scenario"
CLAIM_EXPECTED_IMPACT = "expected_market_impact"


def evidence_id(document: dict[str, Any]) -> str:
    """Return a stable, non-authoritative identifier for one source document."""
    key = "|".join(
        str(document.get(field) or "")
        for field in ("url", "title", "seendate", "domain")
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def normalize_evidence_document(document: dict[str, Any]) -> dict[str, Any]:
    """Keep only bounded fields needed to explain a deterministic evidence match."""
    return {
        "evidence_id": str(document.get("evidence_id") or evidence_id(document)),
        "title": str(document.get("title") or "")[:500],
        "url": str(document.get("url") or "")[:2000],
        "domain": str(document.get("domain") or "")[:255],
        "sourcecountry": str(document.get("sourcecountry") or "")[:100],
        "seendate": str(document.get("seendate") or "")[:100],
        "tone_avg": document.get("tone_avg"),
    }


def documents_from_gdelt(gdelt: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(gdelt, dict):
        return []
    raw = gdelt.get("evidence_documents")
    if not isinstance(raw, list):
        return []
    return [normalize_evidence_document(row) for row in raw if isinstance(row, dict)]


def match_evidence(
    gdelt: dict[str, Any] | None,
    *,
    terms: Iterable[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Match retained GDELT evidence by literal case-insensitive terms.

    This is intentionally deterministic and conservative. A matching news
    document supports a research proxy; it does not establish an authoritative
    sanction, conflict escalation, shipping closure, or other real-world fact.
    """
    wanted = [str(term).strip().lower() for term in terms if str(term).strip()]
    if not wanted:
        return []
    matches: list[dict[str, Any]] = []
    for document in documents_from_gdelt(gdelt):
        haystack = " ".join(
            str(document.get(field) or "")
            for field in ("title", "domain", "sourcecountry")
        ).lower()
        if any(term in haystack for term in wanted):
            matches.append(document)
            if len(matches) >= max(1, min(int(limit), 20)):
                break
    return matches


def proxy_evidence(
    *,
    gdelt: dict[str, Any] | None,
    terms: Iterable[str],
    static_mapping: str,
    authoritative_evidence: bool = False,
    limit: int = 5,
) -> dict[str, Any]:
    matches = match_evidence(gdelt, terms=terms, limit=limit)
    supported = bool(matches)
    return {
        "claim_type": CLAIM_EVIDENCE_SUPPORTED_PROXY if supported else CLAIM_PROXY,
        "observed": False,
        "proxy": True,
        "scenario": False,
        "authoritative_evidence": bool(authoritative_evidence),
        "evidence_basis": (
            "gdelt_document_evidence_plus_static_mapping"
            if supported
            else "aggregate_gdelt_plus_static_mapping"
        ),
        "static_mapping": static_mapping,
        "evidence_count": len(matches),
        "evidence_ids": [row["evidence_id"] for row in matches],
        "evidence": matches,
        "evidence_quality": "non_authoritative_news_context" if supported else "aggregate_proxy_only",
        "limitations": [
            "GDELT/news evidence is contextual and does not by itself establish an authoritative geopolitical event.",
            "Static exposure mappings express deterministic research relationships, not observed disruptions.",
        ],
    }


def expected_impact_evidence(
    *,
    related_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    event_ids = [
        str(event.get("event_id"))
        for event in (related_events or [])
        if isinstance(event, dict) and event.get("event_id")
    ][:10]
    return {
        "claim_type": CLAIM_EXPECTED_IMPACT,
        "observed": False,
        "proxy": True,
        "scenario": False,
        "authoritative_evidence": False,
        "observed_market_reaction": False,
        "causal_claim": False,
        "evidence_basis": "deterministic_geopolitical_score_and_exposure_mapping",
        "related_evidence_event_ids": event_ids,
        "limitations": [
            "Impact values are deterministic research expectations, not realized returns.",
            "No causal relationship between a geopolitical signal and subsequent market movement is asserted.",
        ],
    }


def scenario_evidence() -> dict[str, Any]:
    return {
        "claim_type": CLAIM_SCENARIO,
        "observed": False,
        "proxy": False,
        "scenario": True,
        "authoritative_evidence": False,
        "evidence_basis": "user_or_template_hypothetical_scenario",
        "limitations": ["Scenario outputs are hypothetical research results and are not observed events."],
    }
