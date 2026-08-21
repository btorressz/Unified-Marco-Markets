"""Canonical Redis snapshot-key contracts.

Keep source-native ingest keys for feed-health compatibility while providing
stable normalized aliases for cross-module consumers. Legacy aliases are kept
explicit so they can be retired deliberately rather than through silent drift.
"""
from __future__ import annotations


_ASSET_ALIASES = {"SOLANA": "SOL"}


def normalize_price_symbol(symbol: str) -> str:
    value = str(symbol or "").upper().strip().replace("/", "_").replace("-", "_")
    if "_" not in value and value.endswith("USD") and len(value) > 3:
        value = f"{value[:-3]}_USD"
    parts = value.split("_")
    if parts:
        parts[0] = _ASSET_ALIASES.get(parts[0], parts[0])
    return "_".join(parts)


def price_snapshot_key(venue: str, symbol: str) -> str:
    return f"price:{str(venue).lower().strip()}:{normalize_price_symbol(symbol)}"


PYTH_SOL_USD_NATIVE = "price:pyth:SOL/USD"
KRAKEN_SOL_USD_NATIVE = "price:kraken:SOLUSD"
COINGECKO_SOL_USD_NATIVE = "price:coingecko:SOLANA/USD"
YFINANCE_SOL_USD_NATIVE = "price:yfinance:SOL-USD"
YFINANCE_BTC_USD_NATIVE = "price:yfinance:BTC-USD"
YFINANCE_ETH_USD_NATIVE = "price:yfinance:ETH-USD"

PYTH_SOL_USD = price_snapshot_key("pyth", "SOL/USD")
KRAKEN_SOL_USD = price_snapshot_key("kraken", "SOL/USD")
COINGECKO_SOL_USD = price_snapshot_key("coingecko", "SOL/USD")
YFINANCE_SOL_USD = price_snapshot_key("yfinance", "SOL/USD")
YFINANCE_BTC_USD = price_snapshot_key("yfinance", "BTC/USD")
YFINANCE_ETH_USD = price_snapshot_key("yfinance", "ETH/USD")

_NATIVE_BY_VENUE_AND_SYMBOL = {
    ("pyth", "SOL_USD"): PYTH_SOL_USD_NATIVE,
    ("kraken", "SOL_USD"): KRAKEN_SOL_USD_NATIVE,
    ("coingecko", "SOL_USD"): COINGECKO_SOL_USD_NATIVE,
    ("yfinance", "SOL_USD"): YFINANCE_SOL_USD_NATIVE,
    ("yfinance", "BTC_USD"): YFINANCE_BTC_USD_NATIVE,
    ("yfinance", "ETH_USD"): YFINANCE_ETH_USD_NATIVE,
}


def price_snapshot_candidates(venue: str, symbol: str) -> tuple[str, ...]:
    """Return canonical-first keys with a known source-native compatibility key."""
    venue_key = str(venue).lower().strip()
    canonical_symbol = normalize_price_symbol(symbol)
    canonical = price_snapshot_key(venue_key, symbol)
    keys = [canonical]
    native = _NATIVE_BY_VENUE_AND_SYMBOL.get((venue_key, canonical_symbol))
    if native and native not in keys:
        keys.append(native)
    return tuple(keys)


def price_integrity_key(symbol: str) -> str:
    return f"price:integrity:{normalize_price_symbol(symbol)}"


def normalize_perp_market(market: str) -> str:
    value = str(market or "").upper().strip().replace("/", "_").replace("-", "_")
    if value not in {"BTC_PERP", "ETH_PERP", "SOL_PERP"}:
        raise ValueError(f"unsupported perpetual market: {market}")
    return value


def funding_snapshot_key(venue: str, market: str) -> str:
    return f"funding:{str(venue).lower().strip()}:{normalize_perp_market(market)}"


def perp_market_context_key(venue: str, market: str) -> str:
    return f"market:{str(venue).lower().strip()}:{normalize_perp_market(market)}"


def basis_snapshot_key(venue: str, market: str) -> str:
    return f"basis:{str(venue).lower().strip()}:{normalize_perp_market(market)}"


def funding_snapshot_candidates(venue: str, market: str) -> tuple[str, ...]:
    canonical = funding_snapshot_key(venue, market)
    legacy = f"funding:{str(venue).lower().strip()}:{str(market).upper()}"
    return (canonical, legacy) if legacy != canonical else (canonical,)


PRICE_INTEGRITY = "price:integrity"  # legacy SOL/USD alias
PRICE_INTEGRITY_LEGACY_LATEST = "price:integrity:latest"

WITS_AGGREGATE = "wits:tariff:aggregate"
WITS_LATEST_LEGACY = "wits:latest"
GDELT_LATEST = "gdelt:latest"
OFAC_SANCTIONS = "sanctions:ofac:latest"
WTO_TRADE = "trade:wto:latest"

STABLECOIN_HEALTH = "stablecoin:health:latest"
STABLECOIN_HEALTH_LEGACY = "stablecoin:health"

PREDICTION_LATEST = "prediction:latest"
PREDICTION_LATEST_LEGACY = "predict:latest"


def prediction_symbol_key(symbol: str) -> str:
    return f"prediction:{str(symbol or '').upper().strip()}"
