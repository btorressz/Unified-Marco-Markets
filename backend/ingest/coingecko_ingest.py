import logging
from datetime import datetime, timezone

import httpx

from backend.core.models import PriceTick
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)

COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"


class CoinGeckoIngestor:

    def __init__(
        self,
        state_store: StateStore | None = None,
        market_repo: MarketRepository | None = None,
    ):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()

    async def fetch_price(self, coin_id: str = "solana", vs_currency: str = "usd") -> PriceTick | None:
        params = {
            "ids": coin_id,
            "vs_currencies": vs_currency,
            "include_last_updated_at": "true",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(COINGECKO_PRICE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                coin_data = data.get(coin_id)
                if not coin_data:
                    logger.warning("CoinGecko returned no data for coin=%s", coin_id)
                    return None

                price = float(coin_data.get(vs_currency, 0))
                if price <= 0:
                    logger.warning("CoinGecko returned invalid price=%.4f for %s", price, coin_id)
                    return None

                tick = PriceTick(
                    symbol=f"{coin_id.upper()}/{vs_currency.upper()}",
                    venue="coingecko",
                    price=price,
                    ts=datetime.now(timezone.utc),
                )

                self._store_tick(tick)
                return tick
        except Exception:
            logger.warning("CoinGecko fetch failed for %s/%s", coin_id, vs_currency, exc_info=True)
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
