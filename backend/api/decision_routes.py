"""Decision audit ledger API. Replay/evaluation endpoints are research-only."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query

from backend.compute.counterfactual_replay import CounterfactualUnavailable, counterfactual_decision
from backend.compute.counterfactual_sensitivity import SensitivityUnavailable, counterfactual_sensitivity
from backend.compute.decision_outcomes import (
    DEFAULT_OUTCOME_TOLERANCE_SECONDS,
    HORIZONS,
    evaluate_decision_outcomes,
    horizon_targets,
    linked_admission_decision_id,
    performance_summary,
    realized_counterfactual_comparison,
    symbol_candidates,
)
from backend.compute.decision_replay import decision_hash, replay_decision
from backend.compute.decision_statistics import enrich_performance_summary
from backend.data.repositories.decision_outcome_repo import DecisionOutcomeRepository
from backend.data.repositories.decision_repo import DecisionRepository

router = APIRouter(prefix="/api/decisions", tags=["decision-audit"])
repository = DecisionRepository()
outcome_repository = DecisionOutcomeRepository()


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


def _decision_outcomes(
    record: dict[str, Any],
    *,
    tolerance_seconds: int = DEFAULT_OUTCOME_TOLERANCE_SECONDS,
    include_lifecycle: bool = True,
) -> dict[str, Any]:
    observations = outcome_repository.load_horizon_prices(
        decision_ts=record.get("decision_ts"),
        symbols=symbol_candidates(record),
        horizons=HORIZONS,
        tolerance_seconds=tolerance_seconds,
    )
    lifecycle = (
        outcome_repository.load_execution_lifecycle(linked_admission_decision_id(record))
        if include_lifecycle else {"available": False, "reason": "not requested for aggregate evaluation"}
    )
    result = evaluate_decision_outcomes(record, observations, lifecycle)
    result["target_horizons"] = horizon_targets(record.get("decision_ts"))
    result["outcome_tolerance_seconds"] = tolerance_seconds
    return result


@router.get("/performance")
def decision_performance(
    venue: str | None = None,
    market: str | None = None,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
    primary_horizon: str = Query("4h"),
    tolerance_seconds: int = Query(DEFAULT_OUTCOME_TOLERANCE_SECONDS, ge=0, le=86400),
    limit: int = Query(50, ge=1, le=100),
):
    """Evaluate final execution decisions and decision-time cohorts from persisted history."""
    if primary_horizon not in HORIZONS:
        raise HTTPException(status_code=422, detail=f"Unsupported horizon: {primary_horizon}")
    rows = repository.list(
        decision_type="execution_pre_trade_final",
        venue=venue,
        market=market,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
    )

    batch = outcome_repository.load_horizon_prices_batch(
        requests=[
            {
                "request_id": str(row.get("id") or index),
                "decision_ts": row.get("decision_ts"),
                "symbols": symbol_candidates(row),
            }
            for index, row in enumerate(rows)
        ],
        horizons=HORIZONS,
        tolerance_seconds=tolerance_seconds,
    )
    batch_results = batch.get("results") or {}
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, row in enumerate(rows):
        request_id = str(row.get("id") or index)
        observations = batch_results.get(request_id) or {
            "available": False,
            "reason": "batched historical market observations unavailable",
            "observations": [],
        }
        outcome = evaluate_decision_outcomes(
            row,
            observations,
            {"available": False, "reason": "not requested for aggregate evaluation"},
        )
        outcome["target_horizons"] = horizon_targets(row.get("decision_ts"))
        outcome["outcome_tolerance_seconds"] = tolerance_seconds
        pairs.append((row, outcome))

    context_history: dict[str, Any] = {
        "available": False,
        "reason": "no final execution decisions in the requested window",
        "regime_snapshots": [],
        "index_history": [],
        "stablecoin_ticks": [],
        "errors": {},
        "truncated": {},
        "read_only": True,
    }
    valid_times: list[datetime] = []
    for row in rows:
        try:
            value = row.get("decision_ts")
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            valid_times.append(parsed.astimezone(timezone.utc))
        except Exception:
            continue
    if valid_times:
        context_history = outcome_repository.load_context_history(
            start_ts=min(valid_times),
            end_ts=max(valid_times),
        )

    result = performance_summary(
        pairs,
        primary_horizon=primary_horizon,
        context_history=context_history,
    )
    result = enrich_performance_summary(
        result,
        pairs,
        primary_horizon=primary_horizon,
        context_history=context_history,
    )
    result.update({
        "decision_count": len(rows),
        "filters": {
            "decision_type": "execution_pre_trade_final",
            "venue": venue,
            "market": market,
            "start_ts": start_ts.isoformat() if start_ts else None,
            "end_ts": end_ts.isoformat() if end_ts else None,
            "limit": limit,
            "outcome_tolerance_seconds": tolerance_seconds,
        },
        "outcome_evaluation": {
            "batched": not bool(batch.get("batch_fallback")),
            "batch_fallback": bool(batch.get("batch_fallback")),
            "query_count": int(batch.get("query_count") or 0),
            "market_row_count": batch.get("market_row_count"),
            "fallback_reason": batch.get("fallback_reason"),
            "read_only": True,
        },
        "persisted": False,
        "orders_submitted": 0,
    })
    return result


@router.get("/{decision_id}")
def get_decision(decision_id: UUID):
    return _get_or_404(decision_id)


@router.get("/{decision_id}/outcomes")
def decision_outcomes(
    decision_id: UUID,
    tolerance_seconds: int = Query(DEFAULT_OUTCOME_TOLERANCE_SECONDS, ge=0, le=86400),
):
    """Return realized market outcomes without mutating the immutable decision."""
    return _decision_outcomes(_get_or_404(decision_id), tolerance_seconds=tolerance_seconds)


@router.post("/{decision_id}/replay")
def replay_historical_decision(decision_id: UUID):
    # No state store, Redis, execution router, venue adapter, or order repository is
    # reachable from this endpoint. Only the immutable database row is supplied.
    return replay_decision(_get_or_404(decision_id))


@router.post("/{decision_id}/counterfactual")
def replay_counterfactual_decision(decision_id: UUID, body: dict[str, Any]):
    """Research-only what-if replay plus optional realized-market interpretation."""
    scenario = body.get("scenario") if isinstance(body, dict) else None
    outcome_horizon = str((body or {}).get("outcome_horizon") or "4h") if isinstance(body, dict) else "4h"
    if outcome_horizon not in HORIZONS:
        raise HTTPException(status_code=422, detail=f"Unsupported horizon: {outcome_horizon}")
    record = _get_or_404(decision_id)
    try:
        result = counterfactual_decision(record, scenario)
    except CounterfactualUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    outcome_result = _decision_outcomes(record, include_lifecycle=False)
    result["realized_outcome"] = realized_counterfactual_comparison(
        outcome_result,
        result,
        horizon=outcome_horizon,
    )
    return result


@router.post("/{decision_id}/sensitivity")
def replay_counterfactual_sensitivity(decision_id: UUID, body: dict[str, Any]):
    """Run bounded research-only 1-D/2-D counterfactual decision sensitivity."""
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Sensitivity request must be an object")
    outcome_horizon = str(body.get("outcome_horizon") or "4h")
    if outcome_horizon not in HORIZONS:
        raise HTTPException(status_code=422, detail=f"Unsupported horizon: {outcome_horizon}")
    try:
        tolerance_seconds = int(body.get("tolerance_seconds", DEFAULT_OUTCOME_TOLERANCE_SECONDS))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="tolerance_seconds must be an integer") from exc
    if tolerance_seconds < 0 or tolerance_seconds > 86400:
        raise HTTPException(status_code=422, detail="tolerance_seconds must be between 0 and 86400")

    record = _get_or_404(decision_id)
    outcome_result = _decision_outcomes(
        record,
        tolerance_seconds=tolerance_seconds,
        include_lifecycle=False,
    )
    try:
        result = counterfactual_sensitivity(
            record,
            x=body.get("x"),
            y=body.get("y"),
            fixed_scenario=body.get("fixed_scenario") or {},
            realized_outcome=outcome_result,
            outcome_horizon=outcome_horizon,
        )
    except SensitivityUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["outcome_tolerance_seconds"] = tolerance_seconds
    return result