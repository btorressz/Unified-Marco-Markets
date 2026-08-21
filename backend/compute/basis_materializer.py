"""Scheduled, forward-only materialization of research basis observations."""
from datetime import datetime, timezone

from backend.compute.basis_engine import compute_basis_observation
from backend.core.price_authority import PriceAuthority
from backend.core.state_keys import basis_snapshot_key, perp_market_context_key
from backend.core.state_store import StateStore
from backend.data.repositories.derivatives_repo import DerivativesRepository

PAIRS = (("BTC/USD", "BTC-PERP"), ("ETH/USD", "ETH-PERP"), ("SOL/USD", "SOL-PERP"))
VENUES = ("hyperliquid", "drift")


class BasisMaterializer:
    def __init__(self, state_store=None, price_authority=None, derivatives_repo=None):
        self.state_store = state_store or StateStore()
        self.price_authority = price_authority or PriceAuthority(state_store=self.state_store)
        self.derivatives_repo = derivatives_repo or DerivativesRepository()

    async def materialize(self, run_context=None):
        now = datetime.now(timezone.utc)
        persisted, unavailable = [], {}
        for symbol, market in PAIRS:
            spot = self.price_authority.get_price(symbol)
            for venue in VENUES:
                perp = self.state_store.get_snapshot(perp_market_context_key(venue, market)) or {}
                observation = compute_basis_observation(
                    symbol=symbol, venue=venue, market=market, spot_source=spot.source,
                    spot_price=spot.price if spot.found else None,
                    spot_ts=spot.ts if spot.found else None,
                    perp_price=perp.get("mark_price"), perp_ts=perp.get("ts"), now=now)
                if not observation["available"]:
                    unavailable[f"{venue}:{market}"] = observation["reasons"]
                    continue
                observation["lineage"] = {
                    "spot": {"symbol": symbol, "source": spot.source,
                             "timestamp": spot.ts.isoformat(), "price": spot.price},
                    "perp": {"venue": venue, "market": market,
                             "timestamp": str(perp.get("ts")), "mark_price": perp["mark_price"]},
                    "transformation": {"id": "basis_materializer_v1", "version": 1,
                        "formula": "(perp_mark_price-spot_price)/spot_price*10000",
                        "max_timestamp_skew_seconds": 120, "max_leg_age_seconds": 180},
                    "quality": {"aligned": True, "fresh": True,
                        "timestamp_skew_seconds": observation["timestamp_skew_seconds"]},
                }
                row = self.derivatives_repo.insert_basis(
                    observation, ingest_run_id=getattr(run_context, "run_id", None))
                if row:
                    persisted.append(row)
                payload = {**observation, "compatibility_alias": False}
                self.state_store.set_snapshot(basis_snapshot_key(venue, market), payload, ttl=300)
                if venue == "hyperliquid" and market == "SOL-PERP":
                    self.state_store.set_snapshot("basis:latest",
                        {**payload, "compatibility_alias": True}, ttl=300)
        if run_context:
            run_context.record_received(len(PAIRS) * len(VENUES))
            run_context.record_persisted(len(persisted))
            run_context.metadata["unavailable"] = unavailable
            run_context.mark_success()
        return persisted
