"""Small, deterministic source-observation quality helpers.

The helpers describe whether a value was actually observed. They do not rank
providers, select execution prices, or turn missing/synthetic values into data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


OBSERVATION_CONTRACT_VERSION = 1
AUTHORITATIVE_EVIDENCE_CONTRACT_VERSION = 2


def observation_quality(
    *,
    source: str,
    source_id: str | None,
    available: bool,
    authoritative: bool,
    execution_eligible: bool = False,
    synthetic: bool = False,
    degraded: bool = False,
    as_of: Any = None,
    transformation: str | None = None,
    transformation_version: str | int | None = None,
    contract_version: int = OBSERVATION_CONTRACT_VERSION,
) -> dict[str, Any]:
    return {
        "contract_version": contract_version,
        "source": source,
        "source_id": source_id,
        "available": bool(available),
        "observed": bool(available and not synthetic),
        "authoritative": bool(authoritative),
        "execution_eligible": bool(execution_eligible),
        "synthetic": bool(synthetic),
        "degraded": bool(degraded or not available or synthetic),
        "as_of": as_of.isoformat() if isinstance(as_of, datetime) else as_of,
        "transformation": transformation,
        "transformation_version": transformation_version,
    }


def authoritative_evidence_envelope(
    *, source: str, source_id: str, authority: str, jurisdiction: str | None,
    dataset: str | None, observation: dict[str, Any], retrieved_at: Any,
    source_record_id: str | None = None, source_record_type: str | None = None,
    published_at: Any = None, effective_at: Any = None,
    provider_updated_at: Any = None, change_type: str | None = None,
    revision: str | None = None, dataset_version: str | None = None,
    content_hash: str | None = None, transformation: str | None = None,
    transformation_version: str | int | None = None,
) -> dict[str, Any]:
    """Build the provider-independent v2 envelope for an observed official record."""
    quality = observation_quality(
        source=source, source_id=source_id, available=True, authoritative=True,
        execution_eligible=False, synthetic=False, degraded=False,
        as_of=provider_updated_at or retrieved_at, transformation=transformation,
        transformation_version=transformation_version,
        contract_version=AUTHORITATIVE_EVIDENCE_CONTRACT_VERSION,
    )
    return {
        "quality": quality,
        "authority": {"name": authority, "jurisdiction": jurisdiction, "dataset": dataset},
        "evidence": {
            "source_record_id": source_record_id,
            "source_record_type": source_record_type,
            "published_at": published_at,
            "effective_at": effective_at,
            "provider_updated_at": provider_updated_at,
            "retrieved_at": retrieved_at,
            "change_type": change_type,
            "revision": revision,
            "dataset_version": dataset_version,
            "content_hash": content_hash,
            "transformation": transformation,
            "transformation_version": transformation_version,
        },
        "observation": observation,
    }


def is_authoritative_observation(value: dict[str, Any] | None, *, source_id: str | None = None) -> bool:
    """Validate v2 authority flags; names and object truthiness are never evidence."""
    if not isinstance(value, dict):
        return False
    quality = value.get("quality")
    if not isinstance(quality, dict):
        return False
    return bool(
        quality.get("contract_version") == AUTHORITATIVE_EVIDENCE_CONTRACT_VERSION
        and quality.get("available") is True
        and quality.get("observed") is True
        and quality.get("authoritative") is True
        and quality.get("synthetic") is False
        and (source_id is None or quality.get("source_id") == source_id)
    )


def is_observed_snapshot(snapshot: dict[str, Any] | None) -> bool:
    """Return False for explicit fallback/synthetic/unavailable snapshots.

    Legacy snapshots without the new quality envelope remain accepted unless
    they already carry fallback/synthetic markers, preserving compatibility
    while preventing known synthetic WITS aggregates from being treated as
    observed evidence.
    """
    if not isinstance(snapshot, dict) or not snapshot:
        return False
    if snapshot.get("fallback_used") is True or snapshot.get("synthetic") is True:
        return False
    if snapshot.get("available") is False:
        return False
    quality = snapshot.get("quality")
    if isinstance(quality, dict):
        if quality.get("available") is False or quality.get("synthetic") is True:
            return False
        if quality.get("observed") is False:
            return False
    return True


def age_seconds(as_of: Any, *, now: datetime | None = None) -> float | None:
    if as_of is None:
        return None
    try:
        if isinstance(as_of, datetime):
            ts = as_of
        else:
            ts = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return max(0.0, (current.astimezone(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None
