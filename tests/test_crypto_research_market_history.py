import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import backend.data.repositories.research_market_history_repo as module
from backend.data.repositories.research_market_history_repo import ResearchMarketHistoryRepository, normalize_bar
from backend.ingest import yfinance_ingest as yi


def bar(timestamp, **changes):
    return {"ts": timestamp, "open": 100, "high": 102, "low": 99, "close": 101, "volume": None, **changes}


def test_invalid_bars_are_rejected_without_fabrication():
    ts = datetime.now(timezone.utc)
    assert normalize_bar(bar(ts)) is not None
    for changes in ({"close": 0}, {"open": float("nan")}, {"high": float("inf")}, {"ts": "bad"},
                    {"low": 102}, {"high": 99}, {"synthetic": True}, {"volume": -1}):
        assert normalize_bar(bar(ts, **changes)) is None


def test_coverage_is_inclusive_continuous_and_uses_provider_timestamp(monkeypatch):
    start = datetime(2026, 8, 14, 23, 55, tzinfo=timezone.utc)  # Friday
    timestamps = [start, start + timedelta(minutes=5), start + timedelta(minutes=15)]
    monkeypatch.setattr(module, "execute_query", lambda *args: [{"ts": ts, "synthetic": False} for ts in timestamps])
    coverage = ResearchMarketHistoryRepository().get_coverage("BTC/USD", 300, start, start + timedelta(minutes=15), now=start + timedelta(hours=1))
    assert coverage["expected_observation_count"] == 4
    assert coverage["observed_observation_count"] == 3
    assert coverage["coverage_ratio"] == pytest.approx(.75)
    assert coverage["max_gap_seconds"] == 600
    assert coverage["age_seconds"] == 2700


def test_history_read_is_bounded_and_timestamp_filtered(monkeypatch):
    seen = {}
    def query(sql, params): seen.update(sql=sql, params=params); return []
    monkeypatch.setattr(module, "execute_query", query)
    now = datetime.now(timezone.utc)
    ResearchMarketHistoryRepository().get_history("ETH/USD", 300, now - timedelta(days=1), now, limit=999999)
    assert "ts >= %s AND ts <= %s" in seen["sql"]
    assert seen["params"][-1] == 10000
    with pytest.raises(ValueError): ResearchMarketHistoryRepository().get_history("DOGE/USD", 300, now, now)


def test_bootstrap_and_incremental_modes_and_partial_failure(monkeypatch):
    class Repo:
        def __init__(self): self.existing = {"BTC/USD": 0, "ETH/USD": 1, "SOL/USD": 1}; self.saved=[]
        def get_first_latest(self, symbol, *args): return {"row_count": self.existing[symbol]}
        def insert_bars_idempotent(self, rows, **kwargs): self.saved.append(kwargs["symbol"]); return len(rows)
    calls=[]
    def fetch(symbol, period, interval, limit):
        calls.append((symbol, period, interval, limit))
        if symbol == "ETH/USD": return {"found": False, "synthetic": False, "history": []}
        return {"found": True, "synthetic": False, "history": [bar(datetime.now(timezone.utc).isoformat())]}
    monkeypatch.setattr(yi, "fetch_crypto_history", fetch)
    repo=Repo(); result=asyncio.run(yi.YFinanceHistoryIngestor(repo).fetch_crypto_history())
    assert calls[0][1:3] == ("1mo", "5m")
    assert calls[1][1:3] == ("5d", "5m")
    assert repo.saved == ["BTC/USD", "SOL/USD"]
    assert len(result) == 2


def test_migration_keeps_market_ticks_separate_and_bar_identity_immutable():
    sql = open("backend/data/migrations.sql", encoding="utf-8").read()
    assert "CREATE TABLE IF NOT EXISTS research_market_bars" in sql
    assert "UNIQUE (source_id, symbol, interval_seconds, ts)" in sql
    assert "ON CONFLICT (source_id,symbol,interval_seconds,ts) DO NOTHING" in open(module.__file__, encoding="utf-8").read()
