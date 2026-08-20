from datetime import datetime, timezone
from fastapi import APIRouter, Query

from backend.compute.funding_arb import detect_arb
from backend.data.repositories.derivatives_repo import DerivativesRepository

router = APIRouter(prefix="/api/funding-arb", tags=["funding-arb"])
_repo = DerivativesRepository()


@router.get("/latest")
def get_latest(market: str = Query(default="SOL-PERP")):
    hl = _repo.latest_funding("hyperliquid", market)
    drift = _repo.latest_funding("drift", market)
    return detect_arb(hl[0] if hl else None, drift[0] if drift else None)


@router.get("/history")
def get_arb_history(market: str = Query(default="SOL-PERP"), limit: int = Query(default=200, ge=1, le=1000)):
    # Durable source observations, not GET-mutated process state.
    return {"market": market, "funding_observations": _repo.funding_history(market=market, limit=limit),
            "read_only": True, "ts": datetime.now(timezone.utc).isoformat()}
