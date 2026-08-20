import logging
from datetime import datetime, timezone

import httpx

from backend.core.models import PriceTick, FundingTick
from backend.core.state_store import StateStore
from backend.core.state_keys import funding_snapshot_key
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

    async def fetch_market_data(self, market: str = "SOL-PERP", run_context=None) -> PriceTick | None:
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
                        if run_context: run_context.mark_success(); run_context.record_received(1)
                        self._store_price(tick, run_context)
                        return tick

                logger.warning("Drift: market %s not found in response", market)
                if run_context: run_context.mark_failure(ValueError("provider_empty_response"))
                return None
        except Exception as exc:
            if run_context: run_context.mark_failure(exc)
            logger.warning("Drift market data fetch failed for %s", market, exc_info=True)
            return None

    async def fetch_funding(self, market: str = "SOL-PERP", run_context=None) -> FundingTick | None:
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
                    if run_context: run_context.mark_failure(ValueError("provider_empty_response"))
                    logger.warning("Drift: no funding rates for %s", market)
                    return None

                # The legacy endpoint does not publish a stable unit/sign contract.
                # Sort by the provider timestamp rather than assuming response order,
                # and retain this only as a contract-v0 raw observation.
                def provider_time(row):
                    return int(row.get("ts", row.get("timestamp", row.get("fundingRateTs", -1))))
                latest = max(rates, key=provider_time)
                raw = latest.get("fundingRate", latest.get("rate"))
                if raw is None:
                    raise ValueError("funding rate missing")
                funding_rate = float(raw)

                tick = FundingTick(
                    venue="drift",
                    market=market,
                    funding_rate=funding_rate,
                    ts=datetime.now(timezone.utc),
                )
                if run_context: run_context.mark_success(); run_context.record_received(1)
                self._store_funding(tick, run_context)
                return tick
        except Exception as exc:
            if run_context: run_context.mark_failure(exc)
            logger.warning("Drift funding fetch failed for %s", market, exc_info=True)
            return None

    def _store_price(self, tick: PriceTick, run_context=None) -> None:
        self.state_store.set_snapshot(
            f"price:{tick.venue}:{tick.symbol}",
            tick.model_dump(mode="json"),
            ttl=120,
        )
        row = self.market_repo.save_tick(
            symbol=tick.symbol,
            venue=tick.venue,
            price=tick.price,
            confidence=tick.confidence,
            ts=tick.ts,
            ingest_run_id=getattr(run_context,"run_id",None), source_id="drift_sol_perp", provenance=run_context,
        )
        if run_context and row: run_context.record_persisted(1)

    def _store_funding(self, tick: FundingTick, run_context=None) -> None:
        self.state_store.set_snapshot(
            funding_snapshot_key(tick.venue, tick.market),
            {**tick.model_dump(mode="json"), "available": False,
             "reason": "drift_units_sign_and_interval_unverified", "contract_version": 0,
             "research_only": True, "execution_eligible": False},
            ttl=300,
        )
        # Transitional alias for pre-v1 SOL consumers; canonical underscore key is primary.
        self.state_store.set_snapshot(
            f"funding:{tick.venue}:{tick.market}",
            {**tick.model_dump(mode="json"), "available": False,
             "reason": "drift_units_sign_and_interval_unverified", "contract_version": 0},
            ttl=300,
        )
        row = self.market_repo.save_funding_tick(
            venue=tick.venue,
            market=tick.market,
            funding_rate=tick.funding_rate,
            ts=tick.ts,
            ingest_run_id=getattr(run_context,"run_id",None), source_id="drift_funding_sol_perp", provenance=run_context,
        )
        if run_context and row: run_context.record_persisted(1)
