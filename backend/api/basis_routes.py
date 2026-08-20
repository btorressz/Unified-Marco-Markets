from datetime import datetime, timezone
from fastapi import APIRouter, Query

from backend.compute.basis_engine import compute_basis_observation
from backend.core.price_authority import PriceAuthority
from backend.core.state_keys import perp_market_context_key
from backend.core.state_store import StateStore
from backend.data.repositories.derivatives_repo import DerivativesRepository

router = APIRouter(prefix="/api/basis", tags=["basis"])
_store, _prices, _repo = StateStore(), PriceAuthority(), DerivativesRepository()


@router.get("/latest")
def get_latest(symbol: str = Query(default="SOL/USD"), venue: str = Query(default="hyperliquid")):
    symbol = symbol.upper(); market = symbol.split("/")[0] + "-PERP"
    spot = _prices.get_price(symbol)  # canonical chain; Yahoo is intentionally excluded
    perp = _store.get_snapshot(perp_market_context_key(venue, market)) or {}
    return compute_basis_observation(symbol=symbol, venue=venue, market=market,
        spot_source=spot.source, spot_price=spot.price if spot.found else None, spot_ts=spot.ts if spot.found else None,
        perp_price=perp.get("mark_price"), perp_ts=perp.get("ts"))


@router.get("/history")
def get_history(symbol: str | None = None, market: str | None = None, limit: int = Query(default=200,ge=1,le=1000)):
    return {"history": _repo.basis_history(symbol=symbol,market=market,limit=limit), "read_only": True}


@router.get("/coverage")
def get_coverage(symbol: str | None = None, market: str | None = None):
    return {"coverage": _repo.basis_coverage(symbol=symbol,market=market), "read_only": True}
