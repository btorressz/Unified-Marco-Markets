"""Code-defined, read-only registry of durable ingestion sources."""

SOURCES = (
    {"source_id": "pyth_sol_usd", "provider": "Pyth", "category": "market_price", "enabled": True, "expected_cadence_seconds": 30, "authoritative": True, "fallback_chain": ["kraken_sol_usd", "coingecko_sol_usd"], "storage_target": "market_ticks", "snapshot_key": "price:pyth:SOL/USD", "description": "Pyth SOL/USD oracle price."},
    {"source_id": "kraken_sol_usd", "provider": "Kraken", "category": "market_price", "enabled": True, "expected_cadence_seconds": 30, "authoritative": False, "fallback_chain": ["coingecko_sol_usd"], "storage_target": "market_ticks", "snapshot_key": "price:kraken:SOLUSD", "description": "Kraken SOL/USD ticker."},
    {"source_id": "coingecko_sol_usd", "provider": "CoinGecko", "category": "market_price", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "fallback_chain": [], "storage_target": "market_ticks", "snapshot_key": "price:coingecko:SOLANA/USD", "description": "CoinGecko SOL/USD price."},
    {"source_id": "drift_sol_perp", "provider": "Drift", "category": "market_price", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "fallback_chain": [], "storage_target": "market_ticks", "snapshot_key": "price:drift:SOL-PERP", "description": "Drift SOL perpetual mark price."},
    {"source_id": "drift_funding_sol_perp", "provider": "Drift", "category": "funding", "enabled": True, "expected_cadence_seconds": 60, "authoritative": True, "fallback_chain": [], "storage_target": "funding_ticks", "snapshot_key": "funding:drift:SOL-PERP", "description": "Drift SOL perpetual funding rate."},
    {"source_id": "wits_tariffs", "provider": "WITS", "category": "macro", "enabled": True, "expected_cadence_seconds": 21600, "authoritative": True, "fallback_chain": [], "storage_target": "redis_snapshot", "snapshot_key": "wits:tariff:840:156:TOTAL", "description": "World Bank WITS tariff observations."},
    {"source_id": "gdelt_macro_news", "provider": "GDELT", "category": "macro_news", "enabled": True, "expected_cadence_seconds": 300, "authoritative": False, "fallback_chain": [], "storage_target": "redis_snapshot", "snapshot_key": "gdelt:latest", "description": "GDELT macro-news observations."},
)

SOURCE_REGISTRY = {source["source_id"]: source for source in SOURCES}


def get_source(source_id: str) -> dict:
    return dict(SOURCE_REGISTRY[source_id])


def list_sources() -> list[dict]:
    return [dict(source) for source in SOURCES]
