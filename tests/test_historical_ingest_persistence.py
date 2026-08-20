from backend.core.models import FundingTick, PriceTick
from backend.ingest.coingecko_ingest import CoinGeckoIngestor
from backend.ingest.drift_ingest import DriftIngestor
from backend.ingest.kraken_ingest import KrakenIngestor
from backend.ingest.pyth_ingest import PythIngestor


class FakeStore:
    def __init__(self):
        self.snapshots = []

    def set_snapshot(self, key, data, ttl=None):
        self.snapshots.append((key, data, ttl))
        return True


class FakeMarketRepo:
    def __init__(self):
        self.market_ticks = []
        self.funding_ticks = []

    def save_tick(self, **kwargs):
        self.market_ticks.append(kwargs)
        return kwargs

    def save_funding_tick(self, **kwargs):
        self.funding_ticks.append(kwargs)
        return kwargs


def _price(symbol: str, venue: str, price: float = 100.0) -> PriceTick:
    return PriceTick(symbol=symbol, venue=venue, price=price)


def test_pyth_store_keeps_redis_and_appends_history():
    store = FakeStore()
    repo = FakeMarketRepo()
    ingestor = PythIngestor(state_store=store, market_repo=repo)
    tick = _price("SOL/USD", "pyth")
    ingestor._store_tick(tick)

    assert store.snapshots[0][0] == "price:pyth:SOL/USD"
    assert repo.market_ticks[0]["symbol"] == "SOL/USD"
    assert repo.market_ticks[0]["venue"] == "pyth"
    assert repo.market_ticks[0]["price"] == 100.0
    assert repo.market_ticks[0]["confidence"] == 1.0
    assert repo.market_ticks[0]["ts"] == tick.ts


def test_kraken_store_keeps_redis_and_appends_history():
    store = FakeStore()
    repo = FakeMarketRepo()
    ingestor = KrakenIngestor(state_store=store, market_repo=repo)
    tick = _price("SOLUSD", "kraken")
    ingestor._store_tick(tick)

    assert store.snapshots[0][0] == "price:kraken:SOLUSD"
    assert repo.market_ticks[0]["symbol"] == "SOLUSD"
    assert repo.market_ticks[0]["ts"] == tick.ts


def test_coingecko_store_keeps_redis_and_appends_history():
    store = FakeStore()
    repo = FakeMarketRepo()
    ingestor = CoinGeckoIngestor(state_store=store, market_repo=repo)
    tick = _price("SOLANA/USD", "coingecko")
    ingestor._store_tick(tick)

    assert store.snapshots[0][0] == "price:coingecko:SOLANA/USD"
    assert repo.market_ticks[0]["venue"] == "coingecko"
    assert repo.market_ticks[0]["ts"] == tick.ts


def test_drift_store_persists_market_and_funding_history():
    store = FakeStore()
    repo = FakeMarketRepo()
    ingestor = DriftIngestor(state_store=store, market_repo=repo)

    price_tick = _price("SOL-PERP", "drift")
    funding_tick = FundingTick(venue="drift", market="SOL-PERP", funding_rate=0.0001)
    ingestor._store_price(price_tick)
    ingestor._store_funding(funding_tick)

    assert store.snapshots[0][0] == "price:drift:SOL-PERP"
    assert store.snapshots[1][0] == "funding:drift:SOL_PERP"
    assert store.snapshots[2][0] == "funding:drift:SOL-PERP"
    assert repo.market_ticks[0]["symbol"] == "SOL-PERP"
    assert repo.market_ticks[0]["ts"] == price_tick.ts
    assert repo.funding_ticks[0]["venue"] == "drift"
    assert repo.funding_ticks[0]["market"] == "SOL-PERP"
    assert repo.funding_ticks[0]["funding_rate"] == 0.0001
    assert repo.funding_ticks[0]["ts"] == funding_tick.ts
