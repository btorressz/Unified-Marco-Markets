import logging
from datetime import datetime, timezone

import httpx

from backend.core.models import PriceTick
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)

KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker"


class KrakenIngestor:

    def __init__(
        self,
        state_store: StateStore | None = None,
        market_repo: MarketRepository | None = None,
    ):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()

    async def fetch_ticker(self, pair: str = "SOLUSD") -> PriceTick | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(KRAKEN_TICKER_URL, params={"pair": pair})
                resp.raise_for_status()
                data = resp.json()

                errors = data.get("error", [])
                if errors:
                    logger.warning("Kraken API errors: %s", errors)
                    return None

                result = data.get("result", {})
                if not result:
                    logger.warning("Kraken returned empty result for pair=%s", pair)
                    return None

                pair_key = next(iter(result))
                ticker = result[pair_key]
                last_price = float(ticker["c"][0])

                tick = PriceTick(
                    symbol=pair,
                    venue="kraken",
                    price=last_price,
                    ts=datetime.now(timezone.utc),
                )

                self._store_tick(tick)
                return tick
        except Exception:
            logger.warning("Kraken fetch failed for pair=%s", pair, exc_info=True)
            return None

    def _store_tick(self, tick: PriceTick) -> None:
        self.state_store.set_snapshot(
            f"price:{tick.venue}:{tick.symbol}",
            tick.model_dump(mode="json"),
            ttl=120,
        )
        self.market_repo.save_tick(
            symbol=tick.symbol,
            venue=tick.venue,
            price=tick.price,
            confidence=tick.confidence,
            ts=tick.ts,
        )
