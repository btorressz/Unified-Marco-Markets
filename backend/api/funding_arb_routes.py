from datetime import datetime, timezone
from fastapi import APIRouter, Query

from backend.compute.funding_arb import align_comparison_history, detect_arb
from backend.data.repositories.derivatives_repo import DerivativesRepository

router = APIRouter(prefix="/api/funding-arb", tags=["funding-arb"])
_repo = DerivativesRepository()


@router.get("/latest")
def get_latest(market: str = Query(default="SOL-PERP")):
    hl = _repo.latest_funding("hyperliquid", market, rate_kind="current", contract_version=1)
    drift = _repo.latest_funding("drift", market, rate_kind="current", contract_version=1)
    history = align_comparison_history(
        _repo.funding_history(venue="hyperliquid", market=market, rate_kind="current", limit=500),
        _repo.funding_history(venue="drift", market=market, rate_kind="current", limit=500), market)
    return detect_arb(hl[0] if hl else None, drift[0] if drift else None, history=history)


@router.get("/history")
def get_arb_history(market: str = Query(default="SOL-PERP"), limit: int = Query(default=200, ge=1, le=1000)):
    # Durable source observations, not GET-mutated process state.
    hl = _repo.funding_history(venue="hyperliquid", market=market, rate_kind="current", limit=limit)
    drift = _repo.funding_history(venue="drift", market=market, rate_kind="current", limit=limit)
    comparisons = align_comparison_history(hl, drift, market, max_rows=limit)
    return {"market": market, "comparisons": comparisons[:limit],
            "semantics": "read-only deterministic alignment of durable v1 current observations",
            "read_only": True, "ts": datetime.now(timezone.utc).isoformat()}
