"""Decision audit ledger API. Replay endpoints are strictly read-only."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query

from backend.compute.counterfactual_replay import CounterfactualUnavailable, counterfactual_decision
from backend.compute.decision_replay import decision_hash, replay_decision
from backend.data.repositories.decision_repo import DecisionRepository

router = APIRouter(prefix="/api/decisions", tags=["decision-audit"])
repository = DecisionRepository()


def _record(body: dict[str, Any]) -> dict[str, Any]:
    row = dict(body)
    row["id"] = str(row.get("id") or uuid4())
    row["decision_ts"] = row.get("decision_ts") or datetime.now(timezone.utc)
    row["decision_type"] = row.get("decision_type") or "evaluation"
    provenance = dict(row.get("input_provenance") or {})
    if not provenance.get("provenance_status"):
        references = any(provenance.get(key) for key in ("source_ids", "ingest_run_ids", "provenance_ids"))
        provenance["provenance_status"] = "complete" if references else "partial"
    row["input_provenance"] = provenance
    for field in ("input_state", "derived_state", "heuristic_result", "ml_result", "risk_result",
                  "allocation_result", "execution_intent", "component_versions", "config_snapshot", "final_decision"):
        row.setdefault(field, {})
    row["decision_hash"] = decision_hash(row)
    return repository.create(row)


@router.post("")
def create_decision(body: dict[str, Any]):
    """Explicit orchestration boundary: records metadata but performs no execution."""
    try:
        return _record(body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_decisions(decision_type: str | None = None, venue: str | None = None,
                   market: str | None = None, start_ts: datetime | None = None,
                   end_ts: datetime | None = None, limit: int = Query(50, ge=1, le=200)):
    rows = repository.list(decision_type=decision_type, venue=venue, market=market,
                           start_ts=start_ts, end_ts=end_ts, limit=limit)
    return {"decisions": rows, "count": len(rows), "limit": limit}


def _get_or_404(decision_id: UUID) -> dict[str, Any]:
    row = repository.get(str(decision_id))
    if not row:
        raise HTTPException(status_code=404, detail="Decision not found")
    return row


@router.get("/{decision_id}")
def get_decision(decision_id: UUID):
    return _get_or_404(decision_id)


@router.post("/{decision_id}/replay")
def replay_historical_decision(decision_id: UUID):
    # No state store, Redis, execution router, venue adapter, or order repository is
    # reachable from this endpoint. Only the immutable database row is supplied.
    return replay_decision(_get_or_404(decision_id))


@router.post("/{decision_id}/counterfactual")
def replay_counterfactual_decision(decision_id: UUID, body: dict[str, Any]):
    """Research-only what-if replay over the immutable historical decision inputs."""
    scenario = body.get("scenario") if isinstance(body, dict) else None
    try:
        return counterfactual_decision(_get_or_404(decision_id), scenario)
    except CounterfactualUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
