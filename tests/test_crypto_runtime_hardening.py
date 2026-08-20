import asyncio
from datetime import datetime, timezone

from backend.core import readiness
from backend.core.price_validator import PriceValidator
from backend.core.state_keys import PRICE_INTEGRITY, PRICE_INTEGRITY_LEGACY_LATEST, price_integrity_key
from backend.execution.router import ExecutionRouter
from backend.ingest.source_registry import list_sources


class Store:
    def __init__(self):
        self.values = {}
        self.read = []

    def set_snapshot(self, key, value, ttl=None):
        self.values[key] = value

    def get_snapshot(self, key):
        self.read.append(key)
        return self.values.get(key)


class Repo:
    def __init__(self):
        self.rows = []

    def save_tick(self, **row):
        self.rows.append(row)
        return row


class StrictRepo(Repo):
    def save_tick(self, **row):
        assert row.get("confidence") is not None
        return super().save_tick(**row)


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Client:
    data = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def get(self, *a, **k):
        return Response(self.data)

    async def post(self, url, json):
        return Response(self.data[json["type"]])


def test_readiness_registry_skips_database_only_source_and_reports_missing_snapshots(monkeypatch):
    store = Store()
    monkeypatch.setattr(readiness, "StateStore", lambda: store)
    result = readiness._ingestion_check()
    assert "yfinance_crypto_history_research" not in {x["source_id"] for x in result["sources"]}
    assert result["status"] == "degraded"
    assert any(x["status"] == "degraded" for x in result["sources"])


def test_asset_integrity_keys_are_independent_and_router_fails_closed(monkeypatch):
    assert len({price_integrity_key(x) for x in ("BTC/USD", "ETH/USD", "SOL/USD")}) == 3
    router = ExecutionRouter()
    router._store = Store()
    for market, asset in (("BTC-PERP", "BTC_USD"), ("ETH-PERP", "ETH_USD"), ("SOL-PERP", "SOL_USD")):
        context = router._get_data_context({"found": False, "integrity_symbol": asset.replace("_", "/")})
        assert context["integrity_status"] == "UNKNOWN"
        assert f"price:integrity:{asset}" in router._store.read


def test_pyth_feed_ids_match_official_contract():
    from backend.ingest.pyth_ingest import PRICE_FEEDS

    assert PRICE_FEEDS == {
        "BTC/USD": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
        "ETH/USD": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
        "SOL/USD": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
    }


def test_pyth_official_hermes_without_api_key_fails_before_network(monkeypatch):
    from backend.ingest import pyth_ingest

    class ForbiddenClient:
        def __init__(self, *a, **k):
            raise AssertionError("network client should not be created")

    monkeypatch.setattr(pyth_ingest, "PYTH_API_KEY", "")
    monkeypatch.setattr(pyth_ingest, "PYTH_HERMES_URL", "https://hermes.pyth.network/v2/updates/price/latest")
    monkeypatch.setattr(pyth_ingest.httpx, "AsyncClient", ForbiddenClient)
    assert asyncio.run(pyth_ingest.PythIngestor(Store(), Repo()).fetch_prices()) == []


def test_current_provider_normalization_and_partial_isolation(monkeypatch):
    from backend.ingest import pyth_ingest, kraken_ingest, coingecko_ingest

    now = int(datetime.now(timezone.utc).timestamp())
    monkeypatch.setattr(pyth_ingest, "PYTH_API_KEY", "test-key")
    parsed = []
    for i, (symbol, feed) in enumerate(pyth_ingest.PRICE_FEEDS.items()):
        if symbol != "BTC/USD":
            parsed.append({"id": feed[2:], "price": {"price": str((2000 + i) * 100), "expo": -2, "conf": "2", "publish_time": now}})
    Client.data = {"parsed": parsed}
    monkeypatch.setattr(pyth_ingest.httpx, "AsyncClient", Client)
    ticks = asyncio.run(pyth_ingest.PythIngestor(Store(), Repo()).fetch_prices())
    assert [x.symbol for x in ticks] == ["ETH/USD", "SOL/USD"]

    Client.data = {"error": [], "result": {"XXBTZUSD": {"c": ["70000"]}, "XETHZUSD": {"c": ["3000"]}}}
    monkeypatch.setattr(kraken_ingest.httpx, "AsyncClient", Client)
    ticks = asyncio.run(kraken_ingest.KrakenIngestor(Store(), Repo()).fetch_tickers())
    assert [x.symbol for x in ticks] == ["BTC/USD", "ETH/USD"]

    Client.data = {
        "bitcoin": {"usd": 70000, "last_updated_at": now},
        "ethereum": {"usd": 3000, "last_updated_at": now},
        "solana": {"usd": 150, "last_updated_at": now},
    }
    monkeypatch.setattr(coingecko_ingest.httpx, "AsyncClient", Client)
    ticks = asyncio.run(coingecko_ingest.CoinGeckoIngestor(Store(), Repo()).fetch_prices())
    assert [x.symbol for x in ticks] == ["BTC/USD", "ETH/USD", "SOL/USD"]
    assert all(int(x.ts.timestamp()) == now for x in ticks)


def test_hyperliquid_read_path_keeps_mark_mid_oracle_distinct(monkeypatch):
    from backend.ingest import hyperliquid_ingest

    Client.data = {
        "allMids": {"BTC": "101", "ETH": "201", "SOL": "301"},
        "metaAndAssetCtxs": [
            {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]},
            [{"markPx": "102", "oraclePx": "103"}, {"markPx": "202", "oraclePx": "203"}, {"markPx": "302", "oraclePx": "303"}],
        ],
    }
    monkeypatch.setattr(hyperliquid_ingest.httpx, "AsyncClient", Client)
    store = Store()
    repo = StrictRepo()
    rows = asyncio.run(hyperliquid_ingest.HyperliquidMarketIngestor(store, repo).fetch_market_context())
    assert [x["market"] for x in rows] == ["BTC-PERP", "ETH-PERP", "SOL-PERP"]
    assert rows[0]["mid_price"] == 101 and rows[0]["mark_price"] == 102 and rows[0]["oracle_price"] == 103
    assert all(x["funding_normalized"] is False for x in rows)
    assert all(x["representative_tick"] == "mark_price" and x["execution_eligible_reference_price"] is False for x in rows)
    assert all(x["venue"] == "hyperliquid" and x["confidence"] == 0.0 for x in repo.rows)


def test_price_validator_symbol_reads_do_not_cross_assets():
    store = Store()
    now = datetime.now(timezone.utc).isoformat()
    store.values.update({
        "price:pyth:BTC_USD": {"price": 100.0, "ts": now},
        "price:kraken:BTC_USD": {"price": 100.1, "ts": now},
        "price:pyth:SOL_USD": {"price": 9999.0, "ts": now},
    })
    result = PriceValidator(state_store=store).validate_symbol("BTC/USD")
    assert result["status"] == "OK"
    assert result["symbol"] == "BTC/USD"
    assert result["execution_grade_prices"] == {"pyth": 100.0, "kraken": 100.1}


def test_scheduler_refreshes_all_asset_integrity_snapshots():
    from backend.ingest.scheduler import IngestScheduler

    class Validator:
        def validate_symbol(self, symbol):
            return {"symbol": symbol, "status": "OK"}

    scheduler = IngestScheduler.__new__(IngestScheduler)
    scheduler.state_store = Store()
    scheduler.price_validator = Validator()
    scheduler._refresh_price_integrity()
    for symbol in ("BTC/USD", "ETH/USD", "SOL/USD"):
        assert scheduler.state_store.values[price_integrity_key(symbol)]["status"] == "OK"
    assert scheduler.state_store.values[PRICE_INTEGRITY]["symbol"] == "SOL/USD"
    assert scheduler.state_store.values[PRICE_INTEGRITY_LEGACY_LATEST]["symbol"] == "SOL/USD"


def test_router_market_state_is_asset_scoped_and_missing_is_unknown():
    router = ExecutionRouter()
    router._store = Store()
    router._store.values[price_integrity_key("SOL/USD")] = {"status": "OK"}
    assert router._get_market_state("BTC-PERP")["price_integrity"] == "UNKNOWN"
    assert router._get_market_state("BTC-PERP")["integrity_symbol"] == "BTC_USD"


def test_registry_truthfully_declares_current_coverage_and_history_remains_yahoo_only():
    sources = {x["source_id"]: x for x in list_sources()}
    for source in ("pyth_sol_usd", "kraken_sol_usd", "coingecko_sol_usd"):
        assert sources[source]["supported_symbols"] == ["BTC/USD", "ETH/USD", "SOL/USD"]
    hyperliquid = sources["hyperliquid_sol_usd"]
    assert hyperliquid["category"] == "derivatives_market_context"
    assert hyperliquid["representative_price"] == "mark_price"
    assert hyperliquid["execution_eligible_reference_price"] is False
    assert sources["pyth_sol_usd"]["requires_api_key"] is True
    assert sources["yfinance_crypto_history_research"]["storage_target"] == "research_market_bars"
