"""Bounded, read-only Hyperliquid current perpetual-market observations."""
import logging
from datetime import datetime, timezone

import httpx

from backend.core.state_store import StateStore
from backend.core.derivatives_observations import FundingObservation
from backend.core.state_keys import funding_snapshot_key, perp_market_context_key
from backend.data.repositories.derivatives_repo import DerivativesRepository
from backend.data.repositories.market_repo import MarketRepository

logger = logging.getLogger(__name__)
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
COINS = ("BTC", "ETH", "SOL")
FUNDING_INTERVAL_SECONDS = 3600
HISTORY_BOOTSTRAP_HOURS = 168


class HyperliquidMarketIngestor:
    def __init__(self, state_store=None, market_repo=None, derivatives_repo=None):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()
        self.derivatives_repo = derivatives_repo or DerivativesRepository()

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
            self.state_store.set_snapshot(perp_market_context_key("hyperliquid", market), payload, ttl=120)
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
            try:
                rate = float(ctx["funding"])
                funding = FundingObservation.symmetric(
                    source_id="hyperliquid_sol_usd", venue="hyperliquid", market=market,
                    rate_kind="current", raw_rate=rate, normalized_rate=rate,
                    interval_seconds=FUNDING_INTERVAL_SECONDS, provider_timestamp=None,
                    timestamp_semantics="retrieved_at_current_estimate",
                    metadata={"provider_field": "funding", "realized": False},
                )
                self.state_store.set_snapshot(funding_snapshot_key("hyperliquid", market), funding.model_dump(mode="json"), ttl=120)
                funding_row = self.derivatives_repo.insert_funding(
                    funding, ingest_run_id=getattr(run_context, "run_id", None))
                if run_context:
                    run_context.metadata["funding_observations_received"] = run_context.metadata.get("funding_observations_received", 0) + 1
                    run_context.metadata["funding_observations_persisted"] = run_context.metadata.get("funding_observations_persisted", 0) + (1 if funding_row else 0)
                    run_context.record_persisted(1 if funding_row else 0)
            except (KeyError, TypeError, ValueError):
                logger.warning("Hyperliquid current funding unavailable for %s", coin)

        if run_context:
            if observations:
                run_context.mark_success()
            else:
                run_context.mark_failure(ValueError("provider_empty_response"))
        return observations

    async def fetch_funding_history(self, run_context=None):
        """Ingest at most seven days initially, then resume after the latest row."""
        now = datetime.now(timezone.utc)
        persisted = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for coin in COINS:
                market = f"{coin}-PERP"
                try:
                    latest = self.derivatives_repo.latest_provider_timestamp("hyperliquid", market)
                    start = latest.timestamp() * 1000 + 1 if latest else (now.timestamp() - HISTORY_BOOTSTRAP_HOURS * 3600) * 1000
                    response = await client.post(HYPERLIQUID_INFO_URL, json={"type": "fundingHistory", "coin": coin, "startTime": int(start)})
                    response.raise_for_status()
                    rows = response.json()
                    if not isinstance(rows, list):
                        raise ValueError("unexpected fundingHistory response")
                    for row in sorted(rows, key=lambda item: int(item["time"]))[:HISTORY_BOOTSTRAP_HOURS]:
                        provider_ts = datetime.fromtimestamp(int(row["time"]) / 1000, tz=timezone.utc)
                        raw = float(row["fundingRate"])
                        observation = FundingObservation.symmetric(
                            source_id="hyperliquid_funding_history_research", venue="hyperliquid",
                            market=market, rate_kind="realized", raw_rate=raw,
                            normalized_rate=raw, interval_seconds=FUNDING_INTERVAL_SECONDS,
                            provider_timestamp=provider_ts,
                            timestamp_semantics="provider_funding_settlement_time",
                            metadata={"provider_field": "fundingRate", "realized": True},
                        )
                        if self.derivatives_repo.insert_funding(
                                observation, ingest_run_id=getattr(run_context, "run_id", None)):
                            persisted.append(observation)
                    if run_context:
                        run_context.record_received(min(len(rows), HISTORY_BOOTSTRAP_HOURS))
                except Exception as exc:
                    logger.warning("Hyperliquid funding history failed for %s", coin, exc_info=True)
                    if run_context:
                        run_context.metadata.setdefault("asset_failures", {})[coin] = str(exc)[:200]
        if run_context:
            run_context.record_persisted(len(persisted))
            # A valid empty response means the incremental database is current.
            if run_context.metadata.get("asset_failures") and len(run_context.metadata["asset_failures"]) == len(COINS):
                run_context.mark_failure(ValueError("all_provider_requests_failed"))
            else:
                run_context.metadata["no_new_data"] = not persisted
                run_context.mark_success()
        return persisted
