import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from backend.core.schemas import MarketDataResponse
from backend.core.timeutils import window_to_seconds
from backend.core.state_keys import PRICE_INTEGRITY, PRICE_INTEGRITY_LEGACY_LATEST, price_snapshot_candidates
from backend.core.state_store import StateStore
from backend.core.price_validator import PriceValidator
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets"])

_market_repo = MarketRepository()
_store = StateStore()
_validator = PriceValidator()


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


@router.get("/history")
def get_history(venue: str = Query(default="hyperliquid"), window: str = Query(default="1h")):
    try:
        seconds = window_to_seconds(window)
        rows = _market_repo.get_history(venue, seconds)
        return {"venue": venue, "window": window, "count": len(rows), "ticks": rows}
    except Exception as exc:
        logger.error("Error fetching market history: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch market history")


@router.get("/funding")
def get_funding():
    try:
        rows = _market_repo.get_latest_funding()
        return {"funding_rates": rows, "count": len(rows)}
    except Exception as exc:
        logger.error("Error fetching funding rates: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch funding rates")


@router.get("/integrity")
def get_integrity():
    prices = {}
    feed_ts = {}
    for venue in ["pyth", "kraken", "coingecko"]:
        snap = None
        for key in price_snapshot_candidates(venue, "SOL/USD"):
            snap = _store.get_snapshot(key)
            if snap:
                break
        if snap and snap.get("price"):
            prices[venue] = snap["price"]
            feed_ts[venue] = snap.get("ts", datetime.now(timezone.utc).isoformat())

    result = _validator.validate(prices, feed_timestamps=feed_ts)
    _store.set_snapshot(PRICE_INTEGRITY, result, ttl=60)
    _store.set_snapshot(PRICE_INTEGRITY_LEGACY_LATEST, result, ttl=60)
    return result
