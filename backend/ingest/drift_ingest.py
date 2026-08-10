import logging
from datetime import datetime, timezone

import httpx

from backend.core.models import PriceTick, FundingTick
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)

DRIFT_API_BASE = "https://mainnet-beta.api.drift.trade"


class DriftIngestor:

    def __init__(
        self,
        state_store: StateStore | None = None,
        market_repo: MarketRepository | None = None,
    ):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()

    async def fetch_market_data(self, market: str = "SOL-PERP") -> PriceTick | None:
        url = f"{DRIFT_API_BASE}/markets"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()

                markets = data if isinstance(data, list) else data.get("markets", data.get("data", []))
                if not isinstance(markets, list):
                    markets = [markets] if markets else []

                for m in markets:
                    name = m.get("marketName", m.get("symbol", ""))
                    if market.replace("-", "").upper() in name.replace("-", "").upper():
                        price = float(m.get("markPrice", m.get("oraclePrice", m.get("price", 0))))
                        if price <= 0:
                            continue
                        tick = PriceTick(
                            symbol=market,
                            venue="drift",
                            price=price,
                            ts=datetime.now(timezone.utc),
                        )
                        self._store_price(tick)
                        return tick

                logger.warning("Drift: market %s not found in response", market)
                return None
        except Exception:
            logger.warning("Drift market data fetch failed for %s", market, exc_info=True)
            return None

    async def fetch_funding(self, market: str = "SOL-PERP") -> FundingTick | None:
        url = f"{DRIFT_API_BASE}/fundingRates"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params={"marketName": market})
                resp.raise_for_status()
                data = resp.json()

                rates = data if isinstance(data, list) else data.get("fundingRates", data.get("data", []))
                if not isinstance(rates, list):
                    rates = [rates] if rates else []

                if not rates:
                    logger.warning("Drift: no funding rates for %s", market)
                    return None

                latest = rates[0] if rates else {}
                funding_rate = float(latest.get("fundingRate", latest.get("rate", 0)))

                tick = FundingTick(
                    venue="drift",
                    market=market,
                    funding_rate=funding_rate,
                    ts=datetime.now(timezone.utc),
                )
                self._store_funding(tick)
                return tick
        except Exception:
            logger.warning("Drift funding fetch failed for %s", market, exc_info=True)
            return None

    def _store_price(self, tick: PriceTick) -> None:
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

    def _store_funding(self, tick: FundingTick) -> None:
        self.state_store.set_snapshot(
            f"funding:{tick.venue}:{tick.market}",
            tick.model_dump(mode="json"),
            ttl=300,
        )
        self.market_repo.save_funding_tick(
            venue=tick.venue,
            market=tick.market,
            funding_rate=tick.funding_rate,
            ts=tick.ts,
        )
