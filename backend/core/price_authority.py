import logging
from datetime import datetime, timezone
from typing import Any

from backend.core.state_keys import price_snapshot_candidates, price_snapshot_key
from backend.core.state_store import StateStore

logger = logging.getLogger(__name__)

_EXECUTION_PRICE_PRIORITY = ["pyth", "kraken", "coingecko"]
_RESEARCH_PRICE_PRIORITY = [*_EXECUTION_PRICE_PRIORITY, "yfinance"]


class PriceResult:
    __slots__ = ("price", "confidence", "source", "ts", "found")

    def __init__(
        self,
        price: float = 0.0,
        confidence: float = 0.0,
        source: str = "",
        ts: datetime | None = None,
        found: bool = False,
    ):
        self.price = price
        self.confidence = confidence
        self.source = source
        self.ts = ts or datetime.now(timezone.utc)
        self.found = found

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "confidence": self.confidence,
            "source": self.source,
            "ts": self.ts.isoformat(),
            "found": self.found,
        }


class PriceAuthority:

    def __init__(self, state_store: StateStore | None = None):
        self._store = state_store or StateStore()

    def get_price(self, symbol: str, include_research_fallback: bool = False) -> PriceResult:
        """Return the first cached price in the requested trust tier.

        The default path remains execution-grade and intentionally excludes
        yfinance.  Callers must opt into research fallback explicitly.
        """
        venues = _RESEARCH_PRICE_PRIORITY if include_research_fallback else _EXECUTION_PRICE_PRIORITY
        for venue in venues:
            for cache_key in price_snapshot_candidates(venue, symbol):
                try:
                    cached = self._store.get_snapshot(cache_key)
                    if cached is None:
                        continue
                    if venue == "yfinance" and (cached.get("synthetic") or cached.get("execution_eligible") is True):
                        continue
                    price = float(cached.get("price", 0))
                    if price <= 0:
                        continue
                    confidence = float(cached.get("confidence", 0.5))
                    ts_raw = cached.get("ts")
                    if ts_raw:
                        if isinstance(ts_raw, str):
                            try:
                                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                            except ValueError:
                                ts = datetime.now(timezone.utc)
                        elif isinstance(ts_raw, (int, float)):
                            ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                        else:
                            ts = datetime.now(timezone.utc)
                    else:
                        ts = datetime.now(timezone.utc)

                    logger.debug("Price hit for %s from %s key=%s: %.4f", symbol, venue, cache_key, price)
                    return PriceResult(
                        price=price,
                        confidence=confidence,
                        source=venue,
                        ts=ts,
                        found=True,
                    )
                except Exception:
                    logger.warning("Error reading price cache for %s/%s", venue, symbol, exc_info=True)
                    continue

        logger.info("No cached price found for %s across venues %s", symbol, venues)
        return PriceResult(price=0.0, confidence=0.0, source="none", found=False)

    def set_price(self, symbol: str, venue: str, price: float, confidence: float = 1.0) -> None:
        cache_key = price_snapshot_key(venue, symbol)
        data = {
            "price": price,
            "confidence": confidence,
            "symbol": symbol,
            "venue": venue,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._store.set_snapshot(cache_key, data, ttl=120)

    def get_all_venues(self, symbol: str, include_research_fallback: bool = False) -> list[dict[str, Any]]:
        results = []
        venues = _RESEARCH_PRICE_PRIORITY if include_research_fallback else _EXECUTION_PRICE_PRIORITY
        for venue in venues:
            for cache_key in price_snapshot_candidates(venue, symbol):
                try:
                    cached = self._store.get_snapshot(cache_key)
                    if cached and float(cached.get("price", 0)) > 0:
                        results.append({"venue": venue, **cached})
                        break
                except Exception:
                    continue
        return results
