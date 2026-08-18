"""Small, deterministic source-observation quality helpers.

The helpers describe whether a value was actually observed. They do not rank
providers, select execution prices, or turn missing/synthetic values into data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


OBSERVATION_CONTRACT_VERSION = 1


def observation_quality(
    *,
    source: str,
    source_id: str,
    available: bool,
    authoritative: bool,
    execution_eligible: bool = False,
    synthetic: bool = False,
    degraded: bool = False,
    as_of: Any = None,
    transformation: str | None = None,
    transformation_version: str | int | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": OBSERVATION_CONTRACT_VERSION,
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
