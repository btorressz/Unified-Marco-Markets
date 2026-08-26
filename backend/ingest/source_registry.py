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
    {"source_id": "pyth_sol_usd", "provider": "Pyth", "category": "market_price", "enabled": True, "expected_cadence_seconds": 30, "authoritative": True, "requires_api_key": True, "fallback_chain": ["kraken_sol_usd", "coingecko_sol_usd", "yfinance_crypto_research"], "storage_target": "market_ticks", "snapshot_key": PYTH_SOL_USD_NATIVE, "canonical_snapshot_key": PYTH_SOL_USD, "supported_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"], "description": "Pyth BTC/ETH/SOL USD current oracle prices; official Hermes access requires PYTH_API_KEY."},
    {"source_id": "kraken_sol_usd", "provider": "Kraken", "category": "market_price", "enabled": True, "expected_cadence_seconds": 30, "authoritative": False, "fallback_chain": ["coingecko_sol_usd", "yfinance_crypto_research"], "storage_target": "market_ticks", "snapshot_key": KRAKEN_SOL_USD_NATIVE, "canonical_snapshot_key": KRAKEN_SOL_USD, "supported_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"], "description": "Kraken BTC/ETH/SOL USD current tickers."},
    {"source_id": "coingecko_sol_usd", "provider": "CoinGecko", "category": "market_price", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "fallback_chain": ["yfinance_crypto_research"], "storage_target": "market_ticks", "snapshot_key": COINGECKO_SOL_USD_NATIVE, "canonical_snapshot_key": COINGECKO_SOL_USD, "supported_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"], "description": "CoinGecko BTC/ETH/SOL USD current prices."},
    {"source_id": "yfinance_crypto_research", "provider": "Yahoo Finance", "category": "market_price_research", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "research_fallback": True, "execution_eligible": False, "fallback_chain": [], "storage_target": "market_ticks", "snapshot_key": YFINANCE_SOL_USD_NATIVE, "canonical_snapshot_key": YFINANCE_SOL_USD, "description": "Yahoo Finance BTC/ETH/SOL research-only crypto price fallback; never sufficient for live execution readiness."},
    {"source_id": "yfinance_crypto_history_research", "provider": "Yahoo Finance", "category": "market_history_research", "enabled": True, "expected_cadence_seconds": 3600, "authoritative": False, "research_only": True, "research_fallback": True, "execution_eligible": False, "fallback_chain": [], "storage_target": "research_market_bars", "description": "Durable observed BTC/ETH/SOL five-minute Yahoo history for research only; never execution eligible."},
    {"source_id": "hyperliquid_sol_usd", "provider": "Hyperliquid", "category": "derivatives_market_context", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "research_only": True, "execution_eligible": False, "execution_eligible_reference_price": False, "observation_contract_version": 1, "funding_interval_seconds": 3600, "rate_kind": "current", "historical_support": True, "fallback_chain": [], "storage_target": "market_ticks+funding_ticks+redis_snapshot", "snapshot_key": "market:hyperliquid:SOL_PERP", "supported_markets": ["BTC-PERP", "ETH-PERP", "SOL-PERP"], "representative_price": "mark_price", "timestamp_basis": "retrieved_at for current estimate", "description": "Legacy-named scheduled read-only Hyperliquid BTC/ETH/SOL perpetual context and normalized hourly current funding; not canonical spot authority."},
    {"source_id": "hyperliquid_funding_history_research", "provider": "Hyperliquid", "category": "funding_history", "enabled": True, "expected_cadence_seconds": 3600, "authoritative": False, "research_only": True, "execution_eligible": False, "observation_contract_version": 1, "funding_interval_seconds": 3600, "rate_kind": "realized", "historical_support": True, "fallback_chain": [], "storage_target": "funding_ticks", "supported_markets": ["BTC-PERP", "ETH-PERP", "SOL-PERP"], "timestamp_basis": "provider settlement timestamp", "description": "Bounded, incremental Hyperliquid realized hourly funding history."},
    {"source_id": "basis_materializer_v1", "provider": "Internal transformation", "category": "derived_market_research", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "research_only": True, "execution_eligible": False, "observation_contract_version": 1, "fallback_chain": [], "storage_target": "basis_observations+data_provenance+redis_snapshot", "supported_markets": ["BTC-PERP", "ETH-PERP", "SOL-PERP"], "description": "Forward-only scheduled basis transformation; not an external provider."},
    {"source_id": "drift_sol_perp", "provider": "Velocity Protocol (legacy Drift namespace)", "category": "market_price", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "fallback_chain": [], "storage_target": "market_ticks", "snapshot_key": "price:drift:SOL-PERP", "description": "Drift SOL perpetual mark price."},
    {"source_id": "drift_funding_sol_perp", "provider": "Velocity Protocol (legacy Drift namespace)", "category": "funding", "enabled": True, "expected_cadence_seconds": 60, "authoritative": False, "research_only": True, "execution_eligible": False, "observation_contract_version": 0, "rate_kind": "raw_unverified", "historical_support": False, "fallback_chain": [], "storage_target": "funding_ticks+redis_snapshot", "snapshot_key": "funding:drift:SOL_PERP", "supported_markets": ["SOL-PERP"], "timestamp_basis": "retrieved_at; provider semantics unverified", "description": "Legacy Drift raw SOL funding payload; unavailable for normalized comparison until units, interval and sign are verified."},
    {"source_id": "wits_tariffs", "provider": "WITS", "category": "macro", "enabled": True, "expected_cadence_seconds": 21600, "authoritative": True, "execution_eligible": False, "observation_contract_version": 1, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance+research_events", "snapshot_key": WITS_AGGREGATE, "description": "World Bank WITS observed tariff records plus immutable, non-discrete research observations; provider failures never become synthetic canonical observations."},
    {"source_id": "gdelt_macro_news", "provider": "GDELT", "category": "macro_news", "enabled": True, "expected_cadence_seconds": 300, "authoritative": False, "execution_eligible": False, "observation_contract_version": 1, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance", "snapshot_key": GDELT_LATEST, "description": "GDELT aggregate macro-news shock plus bounded normalized article evidence for non-authoritative geopolitical research context."},
    {"source_id": "gdelt_events", "provider": "GDELT", "category": "conflict_diplomatic_political_events", "enabled": True, "expected_cadence_seconds": 900, "authoritative": False, "research_only": True, "execution_eligible": False, "observation_contract_version": 1, "fallback_chain": [], "storage_target": "research_events", "timestamp_basis": "provider DATEADDED", "description": "Durable observed GDELT CAMEO media-coded events; non-authoritative and eligible for event-time Reaction Lab studies."},
    {"source_id": "ofac_sanctions", "provider": "OFAC", "category": "sanctions", "enabled": True, "expected_cadence_seconds": 21600, "authoritative": True, "execution_eligible": False, "research_fallback": False, "observation_contract_version": 2, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance+research_events", "snapshot_key": OFAC_SANCTIONS, "description": "Official OFAC SLS SDN observations with restart-safe local-baseline deltas and immutable research events."},
    {"source_id": "wto_trade", "provider": "WTO", "category": "trade", "enabled": True, "expected_cadence_seconds": 86400, "authoritative": True, "execution_eligible": False, "research_fallback": False, "observation_contract_version": 2, "fallback_chain": [], "storage_target": "redis_snapshot+data_provenance+research_events", "snapshot_key": WTO_TRADE, "description": "Optional-key, bounded WTO Timeseries authoritative trade observations with non-discrete durable research history."},
)

SOURCE_REGISTRY = {source["source_id"]: source for source in SOURCES}


def get_source(source_id: str) -> dict:
    return dict(SOURCE_REGISTRY[source_id])


def list_sources() -> list[dict]:
    return [dict(source) for source in SOURCES]
