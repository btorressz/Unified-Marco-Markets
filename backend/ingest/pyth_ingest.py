import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from backend.config import PYTH_API_KEY, PYTH_HERMES_URL
from backend.core.models import PriceTick
from backend.core.state_keys import price_snapshot_candidates, price_snapshot_key
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)

PRICE_FEEDS = {
    "BTC/USD": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
    "ETH/USD": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
    "SOL/USD": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
}
SOL_USD_FEED_ID = PRICE_FEEDS["SOL/USD"]

_OFFICIAL_HERMES_HOSTS = {"hermes.pyth.network", "pyth.dourolabs.app"}


def _official_hermes_requires_key(url: str) -> bool:
    return (urlparse(str(url)).hostname or "").lower() in _OFFICIAL_HERMES_HOSTS


class PythIngestor:
    def __init__(self, state_store=None, market_repo=None):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()

    async def fetch_prices(self, run_context=None):
        if _official_hermes_requires_key(PYTH_HERMES_URL) and not PYTH_API_KEY:
            exc = RuntimeError("pyth_api_key_not_configured")
            if run_context:
                run_context.mark_failure(exc)
            logger.warning("Pyth Hermes authentication is required but PYTH_API_KEY is not configured")
            return []

        headers = {"Authorization": f"Bearer {PYTH_API_KEY}"} if PYTH_API_KEY else None
        params = [("ids[]", feed) for feed in PRICE_FEEDS.values()]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(PYTH_HERMES_URL, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            if run_context:
                run_context.mark_failure(exc)
            logger.warning("Pyth current-price request failed", exc_info=True)
            return []

        by_id = {str(row.get("id", "")).lower().removeprefix("0x"): row for row in data.get("parsed", [])}
        ticks = []
        for symbol, feed_id in PRICE_FEEDS.items():
            try:
                row = by_id.get(feed_id.lower().removeprefix("0x"))
                price_data = (row or {}).get("price", {})
                raw = int(price_data["price"])
                expo = int(price_data["expo"])
                publish = int(price_data["publish_time"])
                price = raw * (10 ** expo)
                if price <= 0 or publish <= 0:
                    raise ValueError("invalid_provider_observation")
                conf_raw = price_data.get("conf")
                confidence = int(conf_raw) * (10 ** expo) if conf_raw is not None else None
                tick = PriceTick(
                    symbol=symbol,
                    venue="pyth",
                    price=price,
                    confidence=confidence,
                    ts=datetime.fromtimestamp(publish, tz=timezone.utc),
                )
                self._store_tick(tick, run_context)
                ticks.append(tick)
                if run_context:
                    run_context.record_received(1)
                    run_context.set_provider_timestamp(tick.ts)
            except (KeyError, TypeError, ValueError, OverflowError):
                logger.warning("Skipping malformed Pyth observation for %s", symbol)

        if run_context:
            if ticks:
                run_context.mark_success()
            else:
                run_context.mark_failure(ValueError("provider_empty_response"))
        return ticks

    async def fetch_price(self, price_feed_id=SOL_USD_FEED_ID, run_context=None):
        ticks = await self.fetch_prices(run_context=run_context)
        symbol = next((s for s, f in PRICE_FEEDS.items() if f == price_feed_id), "SOL/USD")
        return next((t for t in ticks if t.symbol == symbol), None)

    def _store_tick(self, tick, run_context=None):
        payload = tick.model_dump(mode="json")
        for key in reversed(price_snapshot_candidates(tick.venue, tick.symbol)):
            self.state_store.set_snapshot(key, payload, ttl=120)
        row = self.market_repo.save_tick(
            symbol=tick.symbol,
            venue=tick.venue,
            price=tick.price,
            confidence=tick.confidence,
            ts=tick.ts,
            ingest_run_id=getattr(run_context, "run_id", None),
            source_id="pyth_sol_usd",
            provenance=run_context,
        )
        if run_context and row:
            run_context.record_persisted(1)
