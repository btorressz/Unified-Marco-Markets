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

PYTH_SOL_USD = price_snapshot_key("pyth", "SOL/USD")
KRAKEN_SOL_USD = price_snapshot_key("kraken", "SOL/USD")
COINGECKO_SOL_USD = price_snapshot_key("coingecko", "SOL/USD")

_SOL_USD_NATIVE_BY_VENUE = {
    "pyth": PYTH_SOL_USD_NATIVE,
    "kraken": KRAKEN_SOL_USD_NATIVE,
    "coingecko": COINGECKO_SOL_USD_NATIVE,
}


def price_snapshot_candidates(venue: str, symbol: str) -> tuple[str, ...]:
    """Return canonical-first keys with a known source-native compatibility key."""
    venue_key = str(venue).lower().strip()
    canonical = price_snapshot_key(venue_key, symbol)
    keys = [canonical]
    if normalize_price_symbol(symbol) == "SOL_USD":
        native = _SOL_USD_NATIVE_BY_VENUE.get(venue_key)
        if native and native not in keys:
            keys.append(native)
    return tuple(keys)


PRICE_INTEGRITY = "price:integrity"
PRICE_INTEGRITY_LEGACY_LATEST = "price:integrity:latest"

WITS_AGGREGATE = "wits:tariff:aggregate"
WITS_LATEST_LEGACY = "wits:latest"
GDELT_LATEST = "gdelt:latest"

STABLECOIN_HEALTH = "stablecoin:health:latest"
STABLECOIN_HEALTH_LEGACY = "stablecoin:health"

PREDICTION_LATEST = "prediction:latest"
PREDICTION_LATEST_LEGACY = "predict:latest"


def prediction_symbol_key(symbol: str) -> str:
    return f"prediction:{str(symbol or '').upper().strip()}"
