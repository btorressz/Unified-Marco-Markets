import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from backend.core.schemas import MarketDataResponse
from backend.core.timeutils import window_to_seconds
from backend.core.state_keys import PRICE_INTEGRITY, PRICE_INTEGRITY_LEGACY_LATEST, price_integrity_key, price_snapshot_candidates
from backend.core.state_store import StateStore
from backend.core.price_authority import PriceAuthority
from backend.core.price_validator import PriceValidator
from backend.data.repositories.market_repo import MarketRepository
from backend.data.repositories.derivatives_repo import DerivativesRepository
from backend.data.repositories.research_market_history_repo import (
    INTERVAL_SECONDS, MAX_HISTORY_LIMIT, SOURCE_ID, SUPPORTED_SYMBOLS, ResearchMarketHistoryRepository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets"])

_market_repo = MarketRepository()
_store = StateStore()
_validator = PriceValidator(state_store=_store)
_price_authority = PriceAuthority(state_store=_store)
_research_history = ResearchMarketHistoryRepository()
_derivatives = DerivativesRepository()


@router.get("/latest", response_model=list[MarketDataResponse])
def get_latest():
    try:
        rows = _market_repo.get_all_latest()
        results = []
        for r in rows:
            results.append(MarketDataResponse(
                symbol=r["symbol"],
                price=r["price"],
                source=r["venue"],
                confidence=r.get("confidence", 1.0),
                ts=r["ts"],
            ))
        return results
    except Exception as exc:
        logger.error("Error fetching latest market data: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch latest market data")


@router.get("/research-price")
def get_research_price(symbol: str = Query(default="SOL/USD")):
    """Return the normal price chain plus explicit Yahoo research fallback."""
    result = _price_authority.get_price(symbol, include_research_fallback=True)
    venue = result.source
    return {
        **result.to_dict(),
        "symbol": symbol.upper(),
        "research_fallback_allowed": True,
        "research_grade": result.source == "yfinance",
        "execution_eligible": result.source != "yfinance",
        "degraded": result.source == "yfinance" or not result.found,
        "snapshot_candidates": price_snapshot_candidates(venue, symbol),
    }


@router.get("/history")
def get_history(venue: str = Query(default="hyperliquid"), window: str = Query(default="1h")):
    try:
        seconds = window_to_seconds(window)
        rows = _market_repo.get_history(venue, seconds)
        return {"venue": venue, "window": window, "count": len(rows), "ticks": rows}
    except Exception as exc:
        logger.error("Error fetching market history: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch market history")


@router.get("/research-history/coverage")
def get_research_history_coverage(symbol: str | None = None, start_ts: datetime | None = None,
                                  end_ts: datetime | None = None, interval: int = INTERVAL_SECONDS):
    symbols = [symbol.upper()] if symbol else list(SUPPORTED_SYMBOLS)
    if any(item not in SUPPORTED_SYMBOLS for item in symbols) or interval != INTERVAL_SECONDS:
        raise HTTPException(status_code=422, detail="Supported contract: BTC/USD, ETH/USD, SOL/USD at 300 seconds")
    end = end_ts or datetime.now(timezone.utc)
    start = start_ts or end - timedelta(days=30)
    return {"coverage": [_research_history.get_coverage(item, interval, start, end, SOURCE_ID) for item in symbols], "read_only": True}


@router.get("/research-history")
def get_research_history(symbol: str, start_ts: datetime, end_ts: datetime,
                         interval: int = INTERVAL_SECONDS, source: str = SOURCE_ID,
                         limit: int = Query(default=MAX_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT)):
    if symbol.upper() not in SUPPORTED_SYMBOLS or interval != INTERVAL_SECONDS:
        raise HTTPException(status_code=422, detail="Supported contract: BTC/USD, ETH/USD, SOL/USD at 300 seconds")
    if end_ts < start_ts:
        raise HTTPException(status_code=422, detail="end_ts must be at or after start_ts")
    rows = _research_history.get_history(symbol.upper(), interval, start_ts, end_ts, source, limit)
    return {"source_id": source, "symbol": symbol.upper(), "interval_seconds": interval, "count": len(rows), "bars": rows, "read_only": True}


@router.get("/funding")
def get_funding(venue: str | None = None, market: str | None = None):
    try:
        rows = _derivatives.funding_history(venue=venue, market=market, limit=50)
        return {"funding_rates": rows, "count": len(rows), "contract_version": 1, "read_only": True}
    except Exception as exc:
        logger.error("Error fetching funding rates: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch funding rates")


@router.get("/funding/history")
def get_funding_history(venue: str | None = None, market: str | None = None,
                        start_ts: datetime | None = None, end_ts: datetime | None = None,
                        limit: int = Query(default=200, ge=1, le=1000)):
    rows = _derivatives.funding_history(venue, market, start_ts, end_ts, limit)
    return {"observations": rows, "count": len(rows), "read_only": True}


@router.get("/funding/coverage")
def get_funding_coverage(venue: str | None = None, market: str | None = None):
    return {"coverage": _derivatives.funding_coverage(venue, market), "read_only": True}


@router.get("/integrity")
def get_integrity(symbol: str = Query(default="SOL/USD")):
    symbol = symbol.upper().replace("-PERP", "/USD")
    if symbol not in {"BTC/USD", "ETH/USD", "SOL/USD"}:
        raise HTTPException(status_code=422, detail="Supported integrity symbols: BTC/USD, ETH/USD, SOL/USD")
    result = _validator.validate_symbol(symbol)
    _store.set_snapshot(price_integrity_key(symbol), result, ttl=60)
    if symbol == "SOL/USD":
        _store.set_snapshot(PRICE_INTEGRITY, result, ttl=60)
        _store.set_snapshot(PRICE_INTEGRITY_LEGACY_LATEST, result, ttl=60)
    return result
