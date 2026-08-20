"""Bounded, read-only Hyperliquid current perpetual-market observations."""
import logging
from datetime import datetime, timezone

import httpx

from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
COINS = ("BTC", "ETH", "SOL")


class HyperliquidMarketIngestor:
    def __init__(self, state_store=None, market_repo=None):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()

    async def fetch_market_context(self, run_context=None):
        retrieved = datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                mids_response = await client.post(HYPERLIQUID_INFO_URL, json={"type": "allMids"})
                mids_response.raise_for_status()
                contexts_response = await client.post(HYPERLIQUID_INFO_URL, json={"type": "metaAndAssetCtxs"})
                contexts_response.raise_for_status()
            mids = mids_response.json()
            meta, contexts = contexts_response.json()
            universe = meta.get("universe", [])
        except Exception as exc:
            if run_context:
                run_context.mark_failure(exc)
            logger.warning("Hyperliquid read-only market request failed", exc_info=True)
            return []

        by_coin = {row.get("name"): contexts[i] for i, row in enumerate(universe) if i < len(contexts)}
        observations = []
        for coin in COINS:
            ctx = by_coin.get(coin, {})
            try:
                mid = float(mids[coin])
                mark = float(ctx["markPx"])
                oracle = float(ctx["oraclePx"])
                if min(mid, mark, oracle) <= 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                logger.warning("Skipping malformed Hyperliquid context for %s", coin)
                continue

            market = f"{coin}-PERP"
            payload = {
                "market": market,
                "venue": "hyperliquid",
                "mark_price": mark,
                "mid_price": mid,
                "oracle_price": oracle,
                "open_interest": ctx.get("openInterest"),
                "premium": ctx.get("premium"),
                "raw_funding": ctx.get("funding"),
                "funding_normalized": False,
                "representative_tick": "mark_price",
                "market_tick_confidence": 0.0,
                "execution_eligible_reference_price": False,
                "ts": retrieved.isoformat(),
                "timestamp_semantics": "retrieved_at",
            }
            self.state_store.set_snapshot(f"market:hyperliquid:{coin}_PERP", payload, ttl=120)
            row = self.market_repo.save_tick(
                symbol=market,
                venue="hyperliquid",
                price=mark,
                confidence=0.0,
                ts=retrieved,
                ingest_run_id=getattr(run_context, "run_id", None),
                source_id="hyperliquid_sol_usd",
                provenance=run_context,
            )
            if run_context:
                run_context.record_received(1)
                run_context.record_persisted(1 if row else 0)
            observations.append(payload)

        if run_context:
            if observations:
                run_context.mark_success()
            else:
                run_context.mark_failure(ValueError("provider_empty_response"))
        return observations
