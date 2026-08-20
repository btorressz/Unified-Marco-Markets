from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.core.price_authority import PriceAuthority
from backend.core.price_validator import PriceValidator
from backend.core.state_keys import (
    YFINANCE_BTC_USD,
    YFINANCE_ETH_USD,
    YFINANCE_SOL_USD,
    price_snapshot_key,
)
from backend.ingest import yfinance_ingest as yi


ROOT = Path(__file__).parents[1]


class FakeStore:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = []

    def get_snapshot(self, key):
        return self.values.get(key)

    def set_snapshot(self, key, value, ttl=None):
        self.values[key] = value
        self.writes.append((key, value, ttl))

    def check_throttle(self, *args, **kwargs):
        return False


class FakeMarketRepo:
    def __init__(self):
        self.rows = []

    def save_tick(self, **kwargs):
        self.rows.append(kwargs)
        return {"id": "tick-1", **kwargs}


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def yahoo_payload(symbol="SOL/USD", price=200.0):
    return {
        "symbol": symbol,
        "venue": "yfinance",
        "source": "yfinance",
        "price": price,
        "confidence": 0.35,
        "ts": datetime(2026, 8, 18, tzinfo=timezone.utc).isoformat(),
        "research_grade": True,
        "authoritative": False,
        "execution_eligible": False,
        "synthetic": False,
    }


def test_existing_equity_demo_behavior_is_preserved():
    text = source("backend/ingest/yfinance_ingest.py")
    assert "EQUITY_INDEX_ETFS" in text
    assert "SECTOR_ETFS" in text
    assert "TARIFF_SENSITIVE" in text
    assert "def demo_history" in text
    assert "def fetch_history" in text
    assert "def fetch_quote" in text
    assert 'rows = demo_history(ticker)' in text


def test_new_crypto_paths_are_strict_and_never_use_demo_fallback(monkeypatch):
    monkeypatch.setattr(
        yi,
        "_strict_yahoo_history",
        lambda *args, **kwargs: {
            "provider_symbol": "SOL-USD",
            "history": [],
            "found": False,
            "degraded": True,
            "synthetic": False,
            "provider_status": {"status": "degraded"},
            "error": "provider down",
        },
    )
    quote = yi.fetch_crypto_quote("SOL")
    assert quote["found"] is False
    assert quote["price"] is None
    assert quote["synthetic"] is False
    assert quote["execution_eligible"] is False


def test_crypto_symbol_contracts_cover_btc_eth_sol():
    assert yi.CRYPTO_SYMBOLS == {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
    assert YFINANCE_SOL_USD == "price:yfinance:SOL_USD"
    assert YFINANCE_BTC_USD == "price:yfinance:BTC_USD"
    assert YFINANCE_ETH_USD == "price:yfinance:ETH_USD"
    assert yi.GEOPOLITICAL_MARKET_SYMBOLS["UUP"] == "UUP"
    assert yi.SECTORS["UUP"] == "FX / broad USD ETF proxy"


def test_execution_price_authority_excludes_yahoo_by_default():
    store = FakeStore({YFINANCE_SOL_USD: yahoo_payload()})
    authority = PriceAuthority(state_store=store)
    default = authority.get_price("SOL/USD")
    research = authority.get_price("SOL/USD", include_research_fallback=True)
    assert default.found is False
    assert default.source == "none"
    assert research.found is True
    assert research.source == "yfinance"
    assert research.price == pytest.approx(200.0)


def test_execution_grade_source_still_wins_over_yahoo_in_research_mode():
    pyth_key = price_snapshot_key("pyth", "SOL/USD")
    store = FakeStore({
        pyth_key: {"price": 199.5, "confidence": 1.0, "ts": datetime.now(timezone.utc).isoformat()},
        YFINANCE_SOL_USD: yahoo_payload(price=200.0),
    })
    result = PriceAuthority(state_store=store).get_price("SOL/USD", include_research_fallback=True)
    assert result.source == "pyth"
    assert result.price == pytest.approx(199.5)


def test_yahoo_only_cannot_establish_price_integrity():
    result = PriceValidator(state_store=FakeStore()).validate({"yfinance": 200.0})
    assert result["integrity_status"] == "UNKNOWN"
    assert result["research_corroboration"]["can_establish_integrity"] is False
    assert result["execution_grade_prices"] == {}


def test_yahoo_can_corroborate_but_not_change_execution_integrity_semantics():
    result = PriceValidator(state_store=FakeStore()).validate({
        "pyth": 200.0,
        "kraken": 200.1,
        "yfinance": 200.05,
    })
    assert result["integrity_status"] == "OK"
    corroboration = result["research_corroboration"]
    assert corroboration["execution_eligible"] is False
    assert corroboration["reference_source"] == "pyth"
    assert "yfinance_vs_pyth" in corroboration["deviation_bps"]


def test_yfinance_ingestor_stores_only_real_research_ticks():
    store = FakeStore()
    repo = FakeMarketRepo()
    ingestor = yi.YFinanceIngestor(state_store=store, market_repo=repo)
    stored = ingestor._store_quote({
        "symbol": "SOL/USD",
        "provider_symbol": "SOL-USD",
        "price": 201.0,
        "synthetic": False,
        "data_ts": datetime.now(timezone.utc).isoformat(),
    })
    rejected = ingestor._store_quote({
        "symbol": "SOL/USD",
        "provider_symbol": "SOL-USD",
        "price": 999.0,
        "synthetic": True,
    })
    assert stored["execution_eligible"] is False
    assert stored["confidence"] == pytest.approx(0.35)
    assert rejected is None
    assert len(repo.rows) == 1
    assert repo.rows[0]["venue"] == "yfinance"
    assert repo.rows[0]["source_id"] == "yfinance_crypto_research"


def test_yahoo_news_is_explicitly_market_context_not_geopolitical_authority():
    text = source("backend/ingest/yfinance_ingest.py")
    assert "def search_market_news" in text
    assert "def fetch_ticker_news" in text
    assert "def fetch_geopolitical_market_news" in text
    assert '"market_context_only": True' in text
    assert '"authoritative_geopolitical_event": False' in text
    assert '"authoritative_geopolitical_event_source": False' in text


def test_cross_asset_and_optional_stream_capabilities_live_in_existing_provider_file():
    text = source("backend/ingest/yfinance_ingest.py")
    for token in (
        "GEOPOLITICAL_MARKET_SYMBOLS",
        "def fetch_cross_asset_snapshot",
        "def fetch_geopolitical_market_snapshot",
        "class YFinancePriceStream",
        "yf.AsyncWebSocket",
    ):
        assert token in text


def test_scheduler_registry_and_market_endpoint_wire_research_fallback():
    scheduler = source("backend/ingest/scheduler.py")
    registry = source("backend/ingest/source_registry.py")
    markets = source("backend/api/markets_routes.py")
    readiness = source("backend/core/readiness.py")
    router = source("backend/execution/router.py")

    assert "YFinanceIngestor" in scheduler
    assert 'id="yfinance_crypto_ingest"' in scheduler
    assert '"source_id": "yfinance_crypto_research"' in registry
    assert '"research_fallback": True' in registry
    assert '"execution_eligible": False' in registry
    assert '@router.get("/research-price")' in markets
    assert "include_research_fallback=True" in markets

    # Production readiness and execution continue to use the default authority;
    # neither opts into the Yahoo research tier.
    assert "include_research_fallback=True" not in readiness
    assert "include_research_fallback=True" not in router


def test_strict_history_explicit_limit_retains_more_than_365(monkeypatch):
    import pandas as pd
    import sys
    times = pd.date_range("2026-07-01", periods=1000, freq="5min", tz="UTC")
    frame = pd.DataFrame({"Open": 100.0, "High": 102.0, "Low": 99.0, "Close": 101.0, "Volume": 1}, index=times)
    class Ticker:
        def __init__(self, symbol): self.symbol = symbol
        def history(self, **kwargs): return frame
    monkeypatch.setitem(sys.modules, "yfinance", type("YF", (), {"Ticker": Ticker}))
    result = yi.fetch_crypto_history("BTC", period="1mo", interval="5m", limit=1000)
    assert result["found"] is True
    assert len(result["history"]) == 1000
