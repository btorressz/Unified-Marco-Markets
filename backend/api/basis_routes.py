from datetime import datetime, timezone
from fastapi import APIRouter, Query

from backend.core.state_keys import basis_snapshot_key
from backend.core.state_store import StateStore
from backend.data.repositories.derivatives_repo import DerivativesRepository

router = APIRouter(prefix="/api/basis", tags=["basis"])
_store, _repo = StateStore(), DerivativesRepository()


@router.get("/latest")
def get_latest(symbol: str = Query(default="SOL/USD"), venue: str = Query(default="hyperliquid")):
    symbol = symbol.upper(); market = symbol.split("/")[0] + "-PERP"
    return (_store.get_snapshot(basis_snapshot_key(venue, market)) or
            {"available": False, "reasons": ["no_materialized_basis"],
             "symbol": symbol, "venue": venue, "market": market, "read_only": True})


@router.get("/history")
def get_history(symbol: str | None = None, venue: str | None = None, market: str | None = None,
                start_ts: datetime | None = None, end_ts: datetime | None = None,
                limit: int = Query(default=200,ge=1,le=1000)):
    return {"history": _repo.basis_history(symbol,venue,market,start_ts,end_ts,limit), "read_only": True}


@router.get("/coverage")
def get_coverage(symbol: str | None = None, venue: str | None = None, market: str | None = None):
    return {"coverage": _repo.basis_coverage(symbol=symbol,venue=venue,market=market), "read_only": True}
