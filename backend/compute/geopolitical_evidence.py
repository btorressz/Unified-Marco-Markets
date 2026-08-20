from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from backend.ingest.quality import is_authoritative_observation


CLAIM_OBSERVED = "observed_evidence"
CLAIM_EVIDENCE_SUPPORTED_PROXY = "evidence_supported_proxy"
CLAIM_PROXY = "proxy"
CLAIM_STATIC_MAPPING = "static_mapping"
CLAIM_SCENARIO = "scenario"
CLAIM_EXPECTED_IMPACT = "expected_market_impact"


def deterministic_event_key(*, source_id: str, source_record_id: str, event_type: str,
                            transition: dict[str, Any] | None = None) -> str:
    facts = {"source_id": source_id, "source_record_id": source_record_id,
             "event_type": event_type, "transition": transition or {}}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def normalize_research_event(*, event_family: str, event_type: str, source: str, source_id: str,
                             source_record_id: str, claim_type: str, event_timestamp=None,
                             event_time_basis=None, transition=None, **fields) -> dict[str, Any]:
    """Normalize an immutable provider event without manufacturing time facts."""
    transition = transition or {}
    authoritative = fields.pop("authoritative", fields.pop("authoritative_evidence", False)) is True
    result = {"event_family": event_family, "event_type": event_type, "source": source,
              "source_id": source_id, "source_record_id": source_record_id, "claim_type": claim_type,
              "event_timestamp": event_timestamp, "event_time_basis": event_time_basis,
              "observed": fields.pop("observed", False) is True, "authoritative": authoritative,
              "proxy": fields.pop("proxy", False) is True, "synthetic": fields.pop("synthetic", False) is True,
              "execution_eligible": False, **fields}
    result["event_key"] = deterministic_event_key(source_id=source_id, source_record_id=source_record_id,
                                                   event_type=event_type, transition=transition)
    return result


def authoritative_evidence(record: dict[str, Any] | None, *, source_id: str | None = None) -> dict[str, Any]:
    """Describe a validated v2 provider record without changing downstream claims."""
    observed = is_authoritative_observation(record, source_id=source_id)
    return {
        "claim_type": CLAIM_OBSERVED if observed else CLAIM_PROXY,
        "observed": observed, "proxy": not observed, "scenario": False,
        "authoritative_evidence": observed,
        "evidence_basis": "normalized_authoritative_provider_record" if observed else "unvalidated_provider_input",
    }


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
