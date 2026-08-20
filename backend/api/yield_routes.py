import logging
from datetime import datetime, timezone
from fastapi import APIRouter

from backend.core.state_store import StateStore
from backend.compute.stable_yield import StableYieldCalculator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/yield", tags=["yield"])

_calc = StableYieldCalculator()
_store = StateStore()


@router.get("/carry")
def get_carry_scores():
    funding_rates = {}

    from backend.core.state_keys import funding_snapshot_key
    for venue in ("hyperliquid", "drift"):
        snap = _store.get_snapshot(funding_snapshot_key(venue, "SOL-PERP"))
        if snap and snap.get("contract_version") == 1 and snap.get("normalized_funding_rate") is not None:
            funding_rates[venue] = {"rate": snap["normalized_funding_rate"], "interval_seconds": snap.get("interval_seconds")}

    if not funding_rates:
        return {"available": False, "reason": "normalized_funding_unavailable", "carry_scores": {}}

    scores = _calc.compute_carry_scores(funding_rates)
    return {
        "carry_scores": scores,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/summary")
def get_yield_summary():
    carry = _store.get_snapshot("carry:latest")
    if carry:
        return carry
    return {
        "message": "No carry data cached yet",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
