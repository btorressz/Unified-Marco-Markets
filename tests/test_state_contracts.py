from pathlib import Path

from backend.core.state_keys import (
    COINGECKO_SOL_USD,
    COINGECKO_SOL_USD_NATIVE,
    KRAKEN_SOL_USD,
    KRAKEN_SOL_USD_NATIVE,
    PREDICTION_LATEST,
    PYTH_SOL_USD,
    PYTH_SOL_USD_NATIVE,
    STABLECOIN_HEALTH,
    WITS_AGGREGATE,
    YFINANCE_SOL_USD,
    YFINANCE_SOL_USD_NATIVE,
    normalize_price_symbol,
    price_snapshot_candidates,
)

ROOT = Path(__file__).parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_price_symbols_share_one_canonical_identity():
    assert normalize_price_symbol("SOL/USD") == "SOL_USD"
    assert normalize_price_symbol("SOLUSD") == "SOL_USD"
    assert normalize_price_symbol("SOLANA/USD") == "SOL_USD"
    assert PYTH_SOL_USD == "price:pyth:SOL_USD"
    assert KRAKEN_SOL_USD == "price:kraken:SOL_USD"
    assert COINGECKO_SOL_USD == "price:coingecko:SOL_USD"
    assert YFINANCE_SOL_USD == "price:yfinance:SOL_USD"


def test_canonical_candidates_keep_provider_native_compatibility():
    assert price_snapshot_candidates("pyth", "SOL/USD") == (PYTH_SOL_USD, PYTH_SOL_USD_NATIVE)
    assert price_snapshot_candidates("kraken", "SOL/USD") == (KRAKEN_SOL_USD, KRAKEN_SOL_USD_NATIVE)
    assert price_snapshot_candidates("coingecko", "SOL/USD") == (COINGECKO_SOL_USD, COINGECKO_SOL_USD_NATIVE)
    assert price_snapshot_candidates("yfinance", "SOL/USD") == (YFINANCE_SOL_USD, YFINANCE_SOL_USD_NATIVE)


def test_market_ingestors_dual_write_native_and_canonical_keys():
    for path in (
        "backend/ingest/pyth_ingest.py",
        "backend/ingest/kraken_ingest.py",
        "backend/ingest/coingecko_ingest.py",
        "backend/ingest/yfinance_ingest.py",
    ):
        text = source(path)
        assert "native_key" in text
        assert "canonical_key = price_snapshot_key" in text
        assert "set_snapshot(native_key" in text
        assert "set_snapshot(canonical_key" in text


def test_source_registry_exposes_native_and_canonical_market_keys():
    text = source("backend/ingest/source_registry.py")
    assert '"snapshot_key": PYTH_SOL_USD_NATIVE' in text
    assert '"canonical_snapshot_key": PYTH_SOL_USD' in text
    assert '"snapshot_key": KRAKEN_SOL_USD_NATIVE' in text
    assert '"canonical_snapshot_key": KRAKEN_SOL_USD' in text
    assert '"snapshot_key": COINGECKO_SOL_USD_NATIVE' in text
    assert '"canonical_snapshot_key": COINGECKO_SOL_USD' in text
    assert '"snapshot_key": YFINANCE_SOL_USD_NATIVE' in text
    assert '"canonical_snapshot_key": YFINANCE_SOL_USD' in text
    assert '"research_fallback": True' in text
    assert '"execution_eligible": False' in text


def test_pyth_endpoint_and_bearer_auth_are_configurable_without_exposing_secret():
    config = source("backend/config.py")
    ingest = source("backend/ingest/pyth_ingest.py")
    assert 'PYTH_HERMES_URL: str = _env("PYTH_HERMES_URL"' in config
    assert 'PYTH_API_KEY: str = _env("PYTH_API_KEY", "")' in config
    assert '"pyth_api_key_configured": bool(PYTH_API_KEY)' in config
    assert '"Authorization": f"Bearer {PYTH_API_KEY}"' in ingest
    assert '"pyth_api_key": PYTH_API_KEY' not in config


def test_price_authority_and_integrity_use_contract_helpers():
    authority = source("backend/core/price_authority.py")
    markets = source("backend/api/markets_routes.py")
    validator = source("backend/core/price_validator.py")
    assert "price_snapshot_candidates(venue, symbol)" in authority
    assert 'price_snapshot_candidates(venue, "SOL/USD")' in markets
    assert 'len(execution_prices) < 2' in validator
    assert '"status": "UNKNOWN"' in validator
    assert '"integrity_status": "UNKNOWN"' in validator
    assert '"can_establish_integrity": False' in validator
    assert "_EXECUTION_PRICE_SOURCES" in validator
    assert "_RESEARCH_PRICE_SOURCES" in validator
    assert "include_research_fallback" in authority


def test_wits_aggregate_is_canonical_and_legacy_alias_is_same_payload():
    text = source("backend/ingest/wits_ingest.py")
    assert f'WITS_AGGREGATE = "{WITS_AGGREGATE}"' not in text
    assert "self.state_store.set_snapshot(WITS_AGGREGATE, payload" in text
    assert "self.state_store.set_snapshot(WITS_LATEST_LEGACY, payload" in text
    assert '"tariff_pressure": tariff_pressure' in text
    assert '"fallback_used": False' in text


def test_stablecoin_health_dual_publishes_canonical_and_legacy_keys():
    text = source("backend/api/stablecoin_routes.py")
    assert f'STABLECOIN_HEALTH = "{STABLECOIN_HEALTH}"' not in text
    assert "set_snapshot(STABLECOIN_HEALTH, health" in text
    assert "set_snapshot(STABLECOIN_HEALTH_LEGACY, health" in text
    assert "get_snapshot(STABLECOIN_HEALTH)" in text


def test_prediction_has_canonical_latest_key_and_probability_aliases():
    text = source("backend/api/predict_routes.py")
    assert f'PREDICTION_LATEST = "{PREDICTION_LATEST}"' not in text
    assert "set_snapshot(PREDICTION_LATEST, result" in text
    assert 'result.setdefault("probability", value)' in text
    assert 'result.setdefault("probability_up", value)' in text
    assert 'result.setdefault("prediction_horizon", "4h")' in text


def test_primary_consumers_use_canonical_contracts_and_raw_stablecoin_shape():
    agents = source("backend/api/agents_routes.py")
    ml = source("backend/api/ml_routes.py")
    allocation = source("backend/api/allocation_routes.py")
    macro = source("backend/api/macro_routes.py")
    protection = source("backend/api/protection_routes.py")
    volatility = source("backend/api/volatility_routes.py")

    assert "get_snapshot(PYTH_SOL_USD)" in agents
    assert "get_snapshot(PREDICTION_LATEST)" in agents
    assert "get_snapshot(WITS_AGGREGATE)" in agents
    assert "get_snapshot(WITS_AGGREGATE)" in macro
    assert "get_snapshot(WITS_AGGREGATE)" in protection

    for text in (ml, allocation, volatility):
        assert "def _stable_assets" in text
        assert "get_snapshot(STABLECOIN_HEALTH)" in text

    assert "get_snapshot(PREDICTION_LATEST)" in ml
    assert "get_snapshot(PREDICTION_LATEST)" in allocation
