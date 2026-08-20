"""Code-defined, read-only registry of ingestion and feed sources."""
from backend.core.state_keys import (
    COINGECKO_SOL_USD,
    COINGECKO_SOL_USD_NATIVE,
    GDELT_LATEST,
    OFAC_SANCTIONS,
    KRAKEN_SOL_USD,
    KRAKEN_SOL_USD_NATIVE,
    PYTH_SOL_USD,
    PYTH_SOL_USD_NATIVE,
    WITS_AGGREGATE,
    WTO_TRADE,
    YFINANCE_SOL_USD,
    YFINANCE_SOL_USD_NATIVE,
)

SOURCES = (
    {"source_id": "pyth_sol_usd", "provider": "Pyth", "category": "market_price", "enabled": True, "expected_cadence_seconds": 30, "authoritative": True, "fallback_chain": ["kraken_sol_usd", "coingecko_sol_usd", "yfinance_crypto_research"], "storage_target": "market_ticks", "snapshot_key": PYTH_SOL_USD_NATIVE, "canonical_snapshot_key": PYTH_SOL_USD, "description": "Pyth SOL/USD oracle price."},
    {"source_id": "kraken_sol_usd", "provider": "Kraken", "category": "market_price", "enabled": True, "expected_cadence_seconds": 30, "authoritative": False, "fallback_chain": ["coingecko_sol_usd", "yfinance_crypto_research"], "storage_target": "market_ticks", "snapshot_key": KRAKEN_SOL_USD_NATIVE, "canonical_snapshot_key": KRAKEN_SOL_USD, "description": "Kraken SOL/USD ticker."},
    {"source_id": "coingecko_sol_usd", "provider": "CoinGecko", "category": "market_price", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "fallback_chain": ["yfinance_crypto_research"], "storage_target": "market_ticks", "snapshot_key": COINGECKO_SOL_USD_NATIVE, "canonical_snapshot_key": COINGECKO_SOL_USD, "description": "CoinGecko SOL/USD price."},
    {"source_id": "yfinance_crypto_research", "provider": "Yahoo Finance", "category": "market_price_research", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "research_fallback": True, "execution_eligible": False, "fallback_chain": [], "storage_target": "market_ticks", "snapshot_key": YFINANCE_SOL_USD_NATIVE, "canonical_snapshot_key": YFINANCE_SOL_USD, "description": "Yahoo Finance BTC/ETH/SOL research-only crypto price fallback; never sufficient for live execution readiness."},
    {"source_id": "hyperliquid_sol_usd", "provider": "Hyperliquid", "category": "websocket_market_price", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "fallback_chain": [], "storage_target": "redis_snapshot", "snapshot_key": "price:hyperliquid:SOL/USD", "description": "Hyperliquid SOL/USD websocket midpoint snapshot."},
    {"source_id": "drift_sol_perp", "provider": "Drift", "category": "market_price", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "fallback_chain": [], "storage_target": "market_ticks", "snapshot_key": "price:drift:SOL-PERP", "description": "Drift SOL perpetual mark price."},
    {"source_id": "drift_funding_sol_perp", "provider": "Drift", "category": "funding", "enabled": True, "expected_cadence_seconds": 60, "authoritative": True, "fallback_chain": [], "storage_target": "funding_ticks", "snapshot_key": "funding:drift:SOL-PERP", "description": "Drift SOL perpetual funding rate."},
    {"source_id": "wits_tariffs", "provider": "WITS", "category": "macro", "enabled": True, "expected_cadence_seconds": 21600, "authoritative": True, "execution_eligible": False, "observation_contract_version": 1, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance+research_events", "snapshot_key": WITS_AGGREGATE, "description": "World Bank WITS observed tariff records plus immutable, non-discrete research observations; provider failures never become synthetic canonical observations."},
    {"source_id": "gdelt_macro_news", "provider": "GDELT", "category": "macro_news", "enabled": True, "expected_cadence_seconds": 300, "authoritative": False, "execution_eligible": False, "observation_contract_version": 1, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance", "snapshot_key": GDELT_LATEST, "description": "GDELT aggregate macro-news shock plus bounded normalized article evidence for non-authoritative geopolitical research context."},
    {"source_id": "ofac_sanctions", "provider": "OFAC", "category": "sanctions", "enabled": True, "expected_cadence_seconds": 21600, "authoritative": True, "execution_eligible": False, "research_fallback": False, "observation_contract_version": 2, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance+research_events", "snapshot_key": OFAC_SANCTIONS, "description": "Official OFAC SLS SDN observations with restart-safe local-baseline deltas and immutable research events."},
    {"source_id": "wto_trade", "provider": "WTO", "category": "trade", "enabled": True, "expected_cadence_seconds": 86400, "authoritative": True, "execution_eligible": False, "research_fallback": False, "observation_contract_version": 2, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance+research_events", "snapshot_key": WTO_TRADE, "description": "Optional-key, bounded WTO Timeseries authoritative trade observations with non-discrete durable research history."},
)

SOURCE_REGISTRY = {source["source_id"]: source for source in SOURCES}


def get_source(source_id: str) -> dict:
    return dict(SOURCE_REGISTRY[source_id])


def list_sources() -> list[dict]:
    return [dict(source) for source in SOURCES]
