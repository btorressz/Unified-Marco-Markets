import logging
from datetime import datetime, timezone

import httpx

from backend.core.models import PriceTick
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)

PYTH_HERMES_URL = "https://hermes.pyth.network/v2/updates/price/latest"
SOL_USD_FEED_ID = "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d"


class PythIngestor:

    def __init__(
        self,
        state_store: StateStore | None = None,
        market_repo: MarketRepository | None = None,
    ):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()

    async def fetch_price(self, price_feed_id: str = SOL_USD_FEED_ID) -> PriceTick | None:
        params = {"ids[]": price_feed_id}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(PYTH_HERMES_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                parsed = data.get("parsed", [])
                if not parsed:
                    logger.warning("Pyth returned no parsed price data for feed=%s", price_feed_id[:16])
                    return None

                price_data = parsed[0].get("price", {})
                price_raw = int(price_data.get("price", "0"))
                expo = int(price_data.get("expo", 0))
                conf_raw = int(price_data.get("conf", "0"))
                publish_time = int(price_data.get("publish_time", 0))

                price = price_raw * (10 ** expo)
                confidence = conf_raw * (10 ** expo)

                ts = datetime.fromtimestamp(publish_time, tz=timezone.utc) if publish_time > 0 else datetime.now(timezone.utc)

                tick = PriceTick(
                    symbol="SOL/USD",
                    venue="pyth",
                    price=price,
                    confidence=confidence,
                    ts=ts,
                )

                self._store_tick(tick)
                return tick
        except Exception:
            logger.warning("Pyth fetch failed for feed=%s", price_feed_id[:16], exc_info=True)
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
        )
