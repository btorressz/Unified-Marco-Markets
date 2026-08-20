"""Fail-open yfinance equity ingestion helpers.

The app must run without API keys and without yfinance installed.  These helpers
therefore treat yfinance as an optional MVP research provider and always return
safe demo data with degraded provider status when anything goes wrong.

The existing equity/demo behavior below is intentionally preserved.  Additional
crypto, cross-asset, news, and streaming helpers are strict research-provider
paths: they never substitute synthetic/demo prices for a failed Yahoo response.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from backend.core.state_keys import price_snapshot_key
from backend.core.state_store import StateStore
from backend.data.repositories.market_repo import MarketRepository
from backend.data.repositories.research_market_history_repo import (
    INTERVAL_SECONDS, MAX_HISTORY_LIMIT, ResearchMarketHistoryRepository,
)

logger = logging.getLogger(__name__)

EQUITY_INDEX_ETFS = ["SPY", "QQQ", "DIA", "IWM"]
SECTOR_ETFS = ["XLI", "XLY", "XLP", "XLK", "XLE", "XLF", "XLB", "XLV", "SMH", "SOXX", "ITA", "XRT", "KWEB", "FXI", "EEM"]
TARIFF_SENSITIVE = ["AAPL", "TSLA", "NVDA", "AMD", "INTC", "MSFT", "AMZN", "NKE", "LULU", "WMT", "TGT", "COST", "HD", "CAT", "DE", "BA", "F", "GM", "XOM", "CVX", "FCX", "NUE", "STLD"]
EQUITY_UNIVERSE = EQUITY_INDEX_ETFS + SECTOR_ETFS + TARIFF_SENSITIVE

# Yahoo-specific provider symbols.  Canonical internal symbols remain BTC/USD,
# ETH/USD, and SOL/USD when data leaves this module.
CRYPTO_SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
}
MAX_STRICT_HISTORY_ROWS = MAX_HISTORY_LIMIT

# Cross-asset universe useful for macro/geopolitical market-reaction research.
# This is observation data only; geopolitical interpretation remains under
# backend/compute rather than inside this provider adapter.
GEOPOLITICAL_MARKET_SYMBOLS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "XLE": "XLE",
    "XOM": "XOM",
    "CVX": "CVX",
    "GLD": "GLD",
    "SLV": "SLV",
    "ITA": "ITA",
    "SMH": "SMH",
    "SOXX": "SOXX",
    "FXI": "FXI",
    "KWEB": "KWEB",
    "EEM": "EEM",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    # UUP is an exchange-traded broad US-dollar index proxy, not spot FX.
    "UUP": "UUP",
}

GEOPOLITICAL_NEWS_QUERIES = [
    "oil geopolitics",
    "shipping disruption",
    "sanctions markets",
    "semiconductor export controls",
    "Middle East markets",
    "China trade markets",
    "Bitcoin macro",
]

SECTORS = {
    "SPY": "Broad Market", "QQQ": "Growth/Technology", "DIA": "Large Cap", "IWM": "Small Cap",
    "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLK": "Technology",
    "XLE": "Energy", "XLF": "Financials", "XLB": "Materials", "XLV": "Health Care", "SMH": "Semiconductors",
    "SOXX": "Semiconductors", "ITA": "Aerospace/Defense", "XRT": "Retail", "KWEB": "China Internet",
    "FXI": "China Large Cap", "EEM": "Emerging Markets", "AAPL": "Technology", "TSLA": "Autos",
    "NVDA": "Semiconductors", "AMD": "Semiconductors", "INTC": "Semiconductors", "MSFT": "Technology",
    "AMZN": "Retail/Cloud", "NKE": "Apparel", "LULU": "Apparel", "WMT": "Retail", "TGT": "Retail",
    "COST": "Retail", "HD": "Retail", "CAT": "Machinery", "DE": "Machinery", "BA": "Aerospace",
    "F": "Autos", "GM": "Autos", "XOM": "Energy", "CVX": "Energy", "FCX": "Materials",
    "NUE": "Steel", "STLD": "Steel", "UUP": "FX / broad USD ETF proxy",
}

_BASE_PRICES = {ticker: 80.0 + i * 7.5 for i, ticker in enumerate(EQUITY_UNIVERSE)} | {
    "SPY": 540.0, "QQQ": 460.0, "DIA": 390.0, "IWM": 205.0, "AAPL": 195.0,
    "TSLA": 185.0, "NVDA": 120.0, "AMD": 160.0, "MSFT": 430.0, "AMZN": 185.0,
}


def _provider(name: str, status: str, message: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        "research_grade": name == "yfinance",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def demo_history(ticker: str, days: int = 90) -> list[dict[str, Any]]:
    ticker = ticker.upper()
    days = max(5, min(int(days or 90), 365))
    base = float(_BASE_PRICES.get(ticker, 100.0))
    seed = sum(ord(c) for c in ticker) % 17
    rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).replace(hour=21, minute=0, second=0, microsecond=0)
    price = base
    for i in range(days):
        d = now - timedelta(days=days - i - 1)
        drift = 0.0005 + (seed - 8) * 0.00008
        cyc = math.sin((i + seed) / 5.0) * 0.006
        shock = -0.012 if ticker in {"AAPL", "TSLA", "NKE", "CAT", "DE", "BA", "F", "GM", "FCX", "NUE", "STLD"} and i > days - 18 else 0.0
        ret = drift + cyc + shock / max(1, days - i)
        open_p = price
        close = max(1.0, open_p * (1.0 + ret))
        high = max(open_p, close) * (1.0 + 0.004 + (seed % 3) * 0.001)
        low = min(open_p, close) * (1.0 - 0.004 - (seed % 4) * 0.001)
        volume = int(1_000_000 + seed * 125_000 + (1 + abs(cyc) * 50) * 120_000)
        rows.append({"ts": d.isoformat(), "open": round(open_p, 4), "high": round(high, 4), "low": round(low, 4), "close": round(close, 4), "volume": volume})
        price = close
    return rows


def fetch_history(ticker: str, period: str = "3mo", interval: str = "1d") -> dict[str, Any]:
    ticker = ticker.upper().strip()
    try:
        import yfinance as yf  # type: ignore
        hist = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        rows: list[dict[str, Any]] = []
        if hist is not None and not hist.empty:
            for idx, row in hist.tail(365).iterrows():
                ts = idx.to_pydatetime().astimezone(timezone.utc).isoformat() if hasattr(idx, "to_pydatetime") else datetime.now(timezone.utc).isoformat()
                close = float(row.get("Close", 0) or 0)
                if close <= 0:
                    continue
                rows.append({
                    "ts": ts,
                    "open": float(row.get("Open", close) or close),
                    "high": float(row.get("High", close) or close),
                    "low": float(row.get("Low", close) or close),
                    "close": close,
                    "volume": int(row.get("Volume", 0) or 0),
                })
        if rows:
            return {"ticker": ticker, "history": rows, "provider_status": _provider("yfinance", "ok", "MVP research-grade provider"), "degraded": False}
        raise RuntimeError("empty yfinance response")
    except Exception as exc:
        rows = demo_history(ticker)
        return {"ticker": ticker, "history": rows, "provider_status": _provider("yfinance", "degraded", f"fallback demo data: {exc}"), "degraded": True}


def fetch_quote(ticker: str) -> dict[str, Any]:
    data = fetch_history(ticker, period="1mo")
    hist = data.get("history", [])
    last = hist[-1] if hist else demo_history(ticker, 5)[-1]
    prev = hist[-2] if len(hist) > 1 else last
    return {
        "ticker": ticker.upper(),
        "price": last["close"],
        "previous_close": prev["close"],
        "daily_return": ((last["close"] / prev["close"]) - 1.0) if prev.get("close") else 0.0,
        "volume": last.get("volume", 0),
        "sector": SECTORS.get(ticker.upper(), "Unknown"),
        "data_ts": last.get("ts"),
        "provider_status": data.get("provider_status"),
        "degraded": data.get("degraded", False),
    }


# ---------------------------------------------------------------------------
# Strict provider normalization for crypto / cross-asset research paths
# ---------------------------------------------------------------------------


def _provider_failure(message: str) -> dict[str, Any]:
    return {
        **_provider("yfinance", "degraded", message),
        "research_grade": True,
        "authoritative": False,
        "execution_eligible": False,
        "synthetic": False,
    }


def _provider_ok(message: str = "Yahoo Finance research provider") -> dict[str, Any]:
    return {
        **_provider("yfinance", "ok", message),
        "research_grade": True,
        "authoritative": False,
        "execution_eligible": False,
        "synthetic": False,
    }


def _crypto_identity(symbol: str) -> tuple[str, str]:
    value = str(symbol or "").upper().strip().replace("_", "-").replace("/", "-")
    if value.endswith("USD") and "-" not in value:
        value = f"{value[:-3]}-USD"
    base = value.split("-")[0]
    provider_symbol = CRYPTO_SYMBOLS.get(base)
    if not provider_symbol:
        raise ValueError(f"Unsupported yfinance crypto symbol: {symbol}")
    return f"{base}/USD", provider_symbol


def _market_identity(symbol: str) -> tuple[str, str]:
    value = str(symbol or "").upper().strip()
    try:
        return _crypto_identity(value)
    except ValueError:
        provider_symbol = GEOPOLITICAL_MARKET_SYMBOLS.get(value, value)
        return value, provider_symbol


def _history_rows(hist: Any, limit: int = MAX_STRICT_HISTORY_ROWS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if hist is None or getattr(hist, "empty", True):
        return rows
    for idx, row in hist.tail(max(1, int(limit))).iterrows():
        try:
            ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else datetime.now(timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            values = {name: float(row.get(name.title())) for name in ("open", "high", "low", "close")}
            if any(not math.isfinite(value) or value <= 0 for value in values.values()):
                continue
            if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]) or values["high"] < values["low"]:
                continue
            raw_volume = row.get("Volume")
            volume = None if raw_volume is None or (isinstance(raw_volume, float) and math.isnan(raw_volume)) else int(raw_volume)
            if volume is not None and volume < 0: continue
            rows.append({
                "ts": ts.isoformat(),
                **values, "volume": volume,
            })
        except (TypeError, ValueError, OverflowError):
            continue
    return rows


def _strict_yahoo_history(provider_symbol: str, period: str, interval: str, limit: int = MAX_STRICT_HISTORY_ROWS) -> dict[str, Any]:
    """Fetch only real Yahoo observations; never return demo/synthetic prices."""
    try:
        import yfinance as yf  # type: ignore

        hist = yf.Ticker(provider_symbol).history(period=period, interval=interval, auto_adjust=False)
        rows = _history_rows(hist, limit=max(1, min(int(limit), MAX_STRICT_HISTORY_ROWS)))
        if not rows:
            raise RuntimeError("empty yfinance response")
        return {
            "provider_symbol": provider_symbol,
            "history": rows,
            "found": True,
            "degraded": False,
            "synthetic": False,
            "provider_status": _provider_ok(),
        }
    except Exception as exc:
        return {
            "provider_symbol": provider_symbol,
            "history": [],
            "found": False,
            "degraded": True,
            "synthetic": False,
            "provider_status": _provider_failure(str(exc)),
            "error": str(exc),
        }


def fetch_crypto_history(symbol: str, period: str = "7d", interval: str = "5m", limit: int = MAX_STRICT_HISTORY_ROWS) -> dict[str, Any]:
    canonical, provider_symbol = _crypto_identity(symbol)
    result = _strict_yahoo_history(provider_symbol, period=period, interval=interval, limit=limit)
    return {"symbol": canonical, **result}


def fetch_crypto_quote(symbol: str) -> dict[str, Any]:
    """Strict near-live crypto quote path used by the research fallback.

    Unlike the legacy equity helpers above, failure returns found=False/price=None
    and never reaches demo_history().
    """
    canonical, provider_symbol = _crypto_identity(symbol)
    data = _strict_yahoo_history(provider_symbol, period="1d", interval="1m", limit=1440)
    rows = data.get("history") or []
    if not rows:
        return {
            "symbol": canonical,
            "provider_symbol": provider_symbol,
            "price": None,
            "found": False,
            "source": "yfinance",
            "research_grade": True,
            "authoritative": False,
            "execution_eligible": False,
            "synthetic": False,
            "data_ts": None,
            "provider_status": data.get("provider_status"),
            "degraded": True,
            "error": data.get("error"),
        }
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else last
    return {
        "symbol": canonical,
        "provider_symbol": provider_symbol,
        "price": float(last["close"]),
        "previous_observation": float(prev["close"]),
        "observation_return": ((float(last["close"]) / float(prev["close"])) - 1.0) if prev.get("close") else 0.0,
        "volume": last.get("volume", 0),
        "found": True,
        "source": "yfinance",
        "research_grade": True,
        "authoritative": False,
        "execution_eligible": False,
        "synthetic": False,
        "data_ts": last.get("ts"),
        "provider_status": data.get("provider_status"),
        "degraded": False,
    }


def fetch_crypto_quotes(symbols: Iterable[str] | None = None) -> dict[str, Any]:
    requested = list(symbols or CRYPTO_SYMBOLS.keys())
    quotes: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for symbol in requested:
        try:
            quote = fetch_crypto_quote(symbol)
            quotes[quote["symbol"]] = quote
            if not quote.get("found"):
                failures.append(quote["symbol"])
        except Exception as exc:
            canonical = str(symbol).upper()
            quotes[canonical] = {
                "symbol": canonical,
                "price": None,
                "found": False,
                "source": "yfinance",
                "research_grade": True,
                "authoritative": False,
                "execution_eligible": False,
                "synthetic": False,
                "degraded": True,
                "error": str(exc),
                "provider_status": _provider_failure(str(exc)),
            }
            failures.append(canonical)
    return {
        "quotes": quotes,
        "count": len(quotes),
        "found_count": sum(1 for row in quotes.values() if row.get("found")),
        "failures": failures,
        "provider_status": _provider_ok() if not failures else _provider_failure(f"unavailable symbols: {', '.join(failures)}"),
        "research_only": True,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def fetch_market_history(symbol: str, period: str = "1mo", interval: str = "1d", limit: int = MAX_STRICT_HISTORY_ROWS) -> dict[str, Any]:
    canonical, provider_symbol = _market_identity(symbol)
    result = _strict_yahoo_history(provider_symbol, period=period, interval=interval, limit=limit)
    return {"symbol": canonical, **result}


def fetch_market_quote(symbol: str) -> dict[str, Any]:
    """Strict cross-asset quote with daily context and no demo fallback."""
    canonical, provider_symbol = _market_identity(symbol)
    data = _strict_yahoo_history(provider_symbol, period="5d", interval="1d", limit=10)
    rows = data.get("history") or []
    if not rows:
        return {
            "symbol": canonical,
            "provider_symbol": provider_symbol,
            "price": None,
            "found": False,
            "daily_return": None,
            "source": "yfinance",
            "research_grade": True,
            "authoritative": False,
            "execution_eligible": False,
            "synthetic": False,
            "data_ts": None,
            "provider_status": data.get("provider_status"),
            "degraded": True,
            "error": data.get("error"),
        }
    last = rows[-1]
    prev = rows[-2] if len(rows) > 1 else last
    return {
        "symbol": canonical,
        "provider_symbol": provider_symbol,
        "price": float(last["close"]),
        "previous_close": float(prev["close"]),
        "daily_return": ((float(last["close"]) / float(prev["close"])) - 1.0) if prev.get("close") else 0.0,
        "volume": last.get("volume", 0),
        "found": True,
        "source": "yfinance",
        "research_grade": True,
        "authoritative": False,
        "execution_eligible": False,
        "synthetic": False,
        "data_ts": last.get("ts"),
        "provider_status": data.get("provider_status"),
        "degraded": False,
    }


def fetch_cross_asset_snapshot(symbols: Iterable[str] | None = None) -> dict[str, Any]:
    requested = list(symbols or GEOPOLITICAL_MARKET_SYMBOLS.keys())
    observations = {str(symbol).upper(): fetch_market_quote(str(symbol)) for symbol in requested}
    found = sum(1 for row in observations.values() if row.get("found"))
    return {
        "observations": observations,
        "count": len(observations),
        "found_count": found,
        "degraded": found != len(observations),
        "provider_status": _provider_ok() if found == len(observations) else _provider_failure("one or more cross-asset observations unavailable"),
        "research_only": True,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def fetch_geopolitical_market_snapshot() -> dict[str, Any]:
    """Raw Yahoo cross-asset observations for later geopolitical interpretation."""
    result = fetch_cross_asset_snapshot(GEOPOLITICAL_MARKET_SYMBOLS.keys())
    result["scope"] = "geopolitical_market_reaction_observations"
    result["interpretation_applied"] = False
    return result


# ---------------------------------------------------------------------------
# Yahoo Finance market-news acquisition (context only, not event authority)
# ---------------------------------------------------------------------------


def _normalize_news_item(item: dict[str, Any], query: str | None = None) -> dict[str, Any]:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    canonical = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
    click = content.get("clickThroughUrl") if isinstance(content.get("clickThroughUrl"), dict) else {}
    title = item.get("title") or content.get("title") or ""
    link = item.get("link") or canonical.get("url") or click.get("url")
    publisher = item.get("publisher") or provider.get("displayName") or provider.get("name")
    published = item.get("providerPublishTime") or content.get("pubDate") or content.get("displayTime")
    return {
        "title": str(title),
        "link": link,
        "publisher": publisher,
        "published": published,
        "query": query,
        "source": "yfinance",
        "market_context_only": True,
        "authoritative_geopolitical_event": False,
    }


def search_market_news(query: str, count: int = 8) -> dict[str, Any]:
    count = max(1, min(int(count or 8), 25))
    try:
        import yfinance as yf  # type: ignore

        search = yf.Search(str(query), max_results=0, news_count=count, lists_count=0, include_cb=False, recommended=0)
        rows = [_normalize_news_item(dict(item), str(query)) for item in (search.news or [])[:count]]
        return {
            "query": str(query),
            "news": rows,
            "count": len(rows),
            "provider_status": _provider_ok("Yahoo Finance market-news context"),
            "degraded": False,
            "market_context_only": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "query": str(query),
            "news": [],
            "count": 0,
            "provider_status": _provider_failure(str(exc)),
            "degraded": True,
            "market_context_only": True,
            "error": str(exc),
            "ts": datetime.now(timezone.utc).isoformat(),
        }


def fetch_ticker_news(ticker: str, count: int = 8) -> dict[str, Any]:
    ticker = str(ticker or "").upper().strip()
    count = max(1, min(int(count or 8), 25))
    try:
        import yfinance as yf  # type: ignore

        rows = yf.Ticker(ticker).get_news(count=count, tab="news") or []
        normalized = [_normalize_news_item(dict(item), ticker) for item in rows[:count]]
        return {
            "ticker": ticker,
            "news": normalized,
            "count": len(normalized),
            "provider_status": _provider_ok("Yahoo Finance ticker-news context"),
            "degraded": False,
            "market_context_only": True,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "ticker": ticker,
            "news": [],
            "count": 0,
            "provider_status": _provider_failure(str(exc)),
            "degraded": True,
            "market_context_only": True,
            "error": str(exc),
            "ts": datetime.now(timezone.utc).isoformat(),
        }


def fetch_geopolitical_market_news(
    queries: Iterable[str] | None = None,
    *,
    count_per_query: int = 4,
    total_limit: int = 20,
) -> dict[str, Any]:
    """Collect market-news context without treating Yahoo as geopolitical authority."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    degraded = False
    for query in list(queries or GEOPOLITICAL_NEWS_QUERIES):
        result = search_market_news(query, count=count_per_query)
        degraded = degraded or bool(result.get("degraded"))
        for item in result.get("news") or []:
            key = (str(item.get("title") or ""), item.get("link"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
            if len(rows) >= max(1, int(total_limit)):
                break
        if len(rows) >= max(1, int(total_limit)):
            break
    return {
        "news": rows,
        "count": len(rows),
        "degraded": degraded,
        "market_context_only": True,
        "authoritative_geopolitical_event_source": False,
        "provider_status": _provider_failure("one or more Yahoo news queries degraded") if degraded else _provider_ok("Yahoo Finance geopolitical market-news context"),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Scheduled/cache integration for the research-only crypto fallback
# ---------------------------------------------------------------------------


def _parse_provider_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        seconds = float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
        result = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif value:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        result = datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


class YFinanceIngestor:
    """Persist strict Yahoo crypto observations as research-only fallback ticks."""

    source_id = "yfinance_crypto_research"
    confidence = 0.35

    def __init__(
        self,
        state_store: StateStore | None = None,
        market_repo: MarketRepository | None = None,
    ):
        self.state_store = state_store or StateStore()
        self.market_repo = market_repo or MarketRepository()

    async def fetch_crypto_prices(self, symbols: Iterable[str] | None = None, run_context=None) -> list[dict[str, Any]]:
        batch = await asyncio.to_thread(fetch_crypto_quotes, list(symbols) if symbols is not None else None)
        found_rows = [row for row in (batch.get("quotes") or {}).values() if row.get("found") and row.get("price")]
        if not found_rows:
            error = RuntimeError("yfinance crypto research provider returned no real prices")
            if run_context:
                run_context.mark_failure(error)
            return []

        persisted: list[dict[str, Any]] = []
        provider_times: list[datetime] = []
        for quote in found_rows:
            row = self._store_quote(quote, run_context=run_context)
            if row:
                persisted.append(row)
            try:
                provider_times.append(_parse_provider_ts(quote.get("data_ts")))
            except Exception:
                pass

        if run_context:
            run_context.mark_success()
            run_context.record_received(len(found_rows))
            if provider_times:
                run_context.set_provider_timestamp(max(provider_times))
        return persisted

    def _store_quote(self, quote: dict[str, Any], run_context=None) -> dict[str, Any] | None:
        canonical_symbol, provider_symbol = _crypto_identity(str(quote.get("symbol") or quote.get("provider_symbol") or ""))
        price = float(quote.get("price") or 0.0)
        if not math.isfinite(price) or price <= 0 or bool(quote.get("synthetic")):
            return None
        ts = _parse_provider_ts(quote.get("data_ts"))
        payload = {
            "symbol": canonical_symbol,
            "provider_symbol": provider_symbol,
            "venue": "yfinance",
            "source": "yfinance",
            "price": price,
            "confidence": self.confidence,
            "ts": ts.isoformat(),
            "research_grade": True,
            "authoritative": False,
            "execution_eligible": False,
            "synthetic": False,
        }
        native_key = f"price:yfinance:{provider_symbol}"
        canonical_key = price_snapshot_key("yfinance", canonical_symbol)
        self.state_store.set_snapshot(native_key, payload, ttl=180)
        if canonical_key != native_key:
            self.state_store.set_snapshot(canonical_key, payload, ttl=180)
        db_row = self.market_repo.save_tick(
            symbol=canonical_symbol,
            venue="yfinance",
            price=price,
            confidence=self.confidence,
            ts=ts,
            ingest_run_id=getattr(run_context, "run_id", None),
            source_id=self.source_id,
            provenance=run_context,
        )
        if run_context and db_row:
            run_context.record_persisted(1)
        return payload


class YFinanceHistoryIngestor:
    """Coverage-aware bounded persistence for observed five-minute crypto bars."""
    source_id = "yfinance_crypto_history_research"

    def __init__(self, history_repo: ResearchMarketHistoryRepository | None = None):
        self.history_repo = history_repo or ResearchMarketHistoryRepository()

    async def fetch_crypto_history(self, symbols: Iterable[str] | None = None, run_context=None) -> list[dict[str, Any]]:
        persisted = []; failures = []; received = 0; provider_times = []
        for symbol in list(symbols or CRYPTO_SYMBOLS.keys()):
            canonical, provider_symbol = _crypto_identity(symbol)
            existing = self.history_repo.get_first_latest(canonical, INTERVAL_SECONDS, self.source_id)
            period = "5d" if int(existing.get("row_count") or 0) else "1mo"
            result = await asyncio.to_thread(fetch_crypto_history, canonical, period, "5m", MAX_STRICT_HISTORY_ROWS)
            rows = result.get("history") or []
            if not result.get("found") or result.get("synthetic") is not False:
                failures.append(canonical); continue
            received += len(rows)
            count = self.history_repo.insert_bars_idempotent(rows, symbol=canonical, provider_symbol=provider_symbol,
                ingest_run_id=getattr(run_context, "run_id", None))
            persisted.append({"symbol": canonical, "period": period, "received": len(rows), "persisted": count})
            if rows: provider_times.append(_parse_provider_ts(rows[-1]["ts"]))
            if run_context: run_context.record_persisted(count)
        if run_context:
            run_context.record_received(received)
            run_context.metadata.update({"symbols": persisted, "failed_symbols": failures, "interval_seconds": INTERVAL_SECONDS})
            if provider_times: run_context.set_provider_timestamp(max(provider_times))
            if failures and not persisted: run_context.mark_failure(RuntimeError("Yahoo history unavailable for all symbols"))
            else:
                run_context.mark_success()
                if failures: run_context.metadata["partial_provider_failure"] = True
        return persisted


class YFinancePriceStream:
    """Optional Yahoo AsyncWebSocket helper for research snapshots.

    This helper is intentionally not started by application startup.  The
    scheduler-based strict snapshot path is the default integration; callers may
    opt into an always-on Yahoo stream later without introducing another provider
    module or changing execution-grade price authority.
    """

    def __init__(self, ingestor: YFinanceIngestor | None = None):
        self.ingestor = ingestor or YFinanceIngestor()
        self._ws = None

    def _handle_message(self, message: dict[str, Any]) -> None:
        try:
            provider_symbol = str(message.get("id") or message.get("symbol") or "").upper()
            price = float(message.get("price") or message.get("regularMarketPrice") or 0.0)
            if not provider_symbol or not math.isfinite(price) or price <= 0:
                return
            canonical, _ = _crypto_identity(provider_symbol)
            quote = {
                "symbol": canonical,
                "provider_symbol": provider_symbol,
                "price": price,
                "found": True,
                "synthetic": False,
                "data_ts": message.get("time") or message.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            }
            self.ingestor._store_quote(quote)
        except Exception:
            logger.debug("Ignoring invalid yfinance stream message", exc_info=True)

    async def run(self, symbols: Iterable[str] | None = None) -> None:
        import yfinance as yf  # type: ignore

        provider_symbols = [_crypto_identity(symbol)[1] for symbol in list(symbols or CRYPTO_SYMBOLS.keys())]
        self._ws = yf.AsyncWebSocket(verbose=False)
        await self._ws.subscribe(provider_symbols)
        await self._ws.listen(self._handle_message)

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
