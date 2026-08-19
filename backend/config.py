import os
import json
import logging

logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    raw = os.environ.get(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r, using default %d", key, raw, default)
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    raw = os.environ.get(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s=%r, using default %s", key, raw, default)
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(key, "")
    if not raw:
        return default or []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [item.strip() for item in raw.split(",") if item.strip()]


DATABASE_URL: str = _env("DATABASE_URL", "")
REDIS_URL: str = _env("REDIS_URL", "redis://localhost:6379")
REDIS_KEY_PREFIX: str = _env("REDIS_KEY_PREFIX", "")
REDIS_MAX_CONNECTIONS: int = max(1, _env_int("REDIS_MAX_CONNECTIONS", 32))
REDIS_CONNECT_TIMEOUT_S: float = max(0.1, _env_float("REDIS_CONNECT_TIMEOUT_S", 2.0))
REDIS_SOCKET_TIMEOUT_S: float = max(0.1, _env_float("REDIS_SOCKET_TIMEOUT_S", 2.0))
REDIS_HEALTH_CHECK_INTERVAL_S: int = max(0, _env_int("REDIS_HEALTH_CHECK_INTERVAL_S", 30))
REDIS_LEASE_TTL_S: int = max(5, _env_int("REDIS_LEASE_TTL_S", 90))
REDIS_PUBSUB_RETRY_S: float = max(0.5, _env_float("REDIS_PUBSUB_RETRY_S", 5.0))

HYPERLIQUID_API_KEY: str = _env("HYPERLIQUID_API_KEY", "")
DRIFT_RPC_URL: str = _env("DRIFT_RPC_URL", "")
SOLANA_RPC_URL: str = _env("SOLANA_RPC_URL", "")
SOLANA_PRIVATE_KEY: str = _env("SOLANA_PRIVATE_KEY", "")
JUPITER_API_URL: str = _env("JUPITER_API_URL", "https://api.jup.ag")
PYTH_HERMES_URL: str = _env("PYTH_HERMES_URL", "https://hermes.pyth.network/v2/updates/price/latest")
PYTH_API_KEY: str = _env("PYTH_API_KEY", "")

EXECUTION_MODE: str = _env("EXECUTION_MODE", "paper")
if EXECUTION_MODE not in ("paper", "live"):
    logger.warning("Invalid EXECUTION_MODE=%r, defaulting to 'paper'", EXECUTION_MODE)
    EXECUTION_MODE = "paper"

# Live execution is intentionally a second, independent safety gate. The venue
# adapters remain research/prototype integrations until they are replaced with
# official/native signing flows and integration-tested.
LIVE_EXECUTION_ENABLED: bool = _env_bool("LIVE_EXECUTION_ENABLED", False)

# Minimal operator-access boundary. Paper/local development remains backward
# compatible by default, while any live-capable configuration forces auth on in
# backend.core.operator_auth regardless of this flag.
OPERATOR_API_TOKEN: str = _env("OPERATOR_API_TOKEN", "")
OPERATOR_AUTH_REQUIRED: bool = _env_bool("OPERATOR_AUTH_REQUIRED", False)

# Direct Jupiter execution is a separate spot-swap surface and must remain
# explicitly disabled until its own production-grade signing/risk path exists.
ENABLE_DIRECT_JUPITER_SWAP: bool = _env_bool("ENABLE_DIRECT_JUPITER_SWAP", False)

SUPPORTED_EXECUTION_VENUES: list[str] = [
    venue.lower()
    for venue in _env_list(
        "SUPPORTED_EXECUTION_VENUES",
        ["paper", "hyperliquid", "drift"],
    )
]
SUPPORTED_EXECUTION_MARKETS: list[str] = [
    market.upper()
    for market in _env_list(
        "SUPPORTED_EXECUTION_MARKETS",
        [
            "BTC-PERP",
            "ETH-PERP",
            "SOL-PERP",
            "DOGE-PERP",
            "AVAX-PERP",
            "MATIC-PERP",
            "APT-PERP",
        ],
    )
]
SUPPORTED_ORDER_TYPES: list[str] = [
    order_type.lower()
    for order_type in _env_list("SUPPORTED_ORDER_TYPES", ["limit", "market"])
]
MAX_ORDER_NOTIONAL: float = _env_float("MAX_ORDER_NOTIONAL", 1_000_000.0)
MAX_ORDER_SLIPPAGE_BPS: float = _env_float("MAX_ORDER_SLIPPAGE_BPS", 500.0)

WITS_COUNTRIES: list[str] = _env_list("WITS_COUNTRIES", ["USA", "CHN", "EU"])
WITS_PRODUCTS: list[str] = _env_list("WITS_PRODUCTS", ["TOTAL", "Capital", "Consumer", "Intermediate", "Raw"])
WTO_API_KEY: str = _env("WTO_API_KEY", "")
WTO_INDICATORS: list[str] = _env_list("WTO_INDICATORS", ["ITS_MTV_AX"])
WTO_REPORTERS: list[str] = _env_list("WTO_REPORTERS", ["USA", "CHN", "EUN"])
WTO_PARTNERS: list[str] = _env_list("WTO_PARTNERS", [])

GDELT_KEYWORDS: list[str] = _env_list(
    "GDELT_KEYWORDS",
    ["tariff", "trade war", "import duty", "export ban", "sanctions", "trade policy"],
)

MAX_LEVERAGE: float = _env_float("MAX_LEVERAGE", 3.0)
MAX_MARGIN_USAGE: float = _env_float("MAX_MARGIN_USAGE", 0.6)
MAX_DAILY_LOSS: float = _env_float("MAX_DAILY_LOSS", 500.0)
COOLDOWN_SECONDS: int = _env_int("COOLDOWN_SECONDS", 300)

PRICE_FRESHNESS_THRESHOLD_S: int = _env_int("PRICE_FRESHNESS_THRESHOLD_S", 30)
PRICE_INTEGRITY_BLOCK_LIVE: bool = _env_bool("PRICE_INTEGRITY_BLOCK_LIVE", True)

LOG_LEVEL: str = _env("LOG_LEVEL", "INFO").upper()


def is_feature_enabled(key: str) -> bool:
    val = _env(key, "")
    return bool(val)


def summary() -> dict:
    effective_operator_auth = bool(OPERATOR_AUTH_REQUIRED or EXECUTION_MODE == "live" or LIVE_EXECUTION_ENABLED)
    return {
        "database_configured": bool(DATABASE_URL),
        "redis_url": REDIS_URL,
        "redis_key_prefix": REDIS_KEY_PREFIX,
        "redis_max_connections": REDIS_MAX_CONNECTIONS,
        "redis_connect_timeout_s": REDIS_CONNECT_TIMEOUT_S,
        "redis_socket_timeout_s": REDIS_SOCKET_TIMEOUT_S,
        "redis_health_check_interval_s": REDIS_HEALTH_CHECK_INTERVAL_S,
        "redis_lease_ttl_s": REDIS_LEASE_TTL_S,
        "execution_mode": EXECUTION_MODE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "operator_auth_required": effective_operator_auth,
        "operator_token_configured": bool(OPERATOR_API_TOKEN),
        "direct_jupiter_swap_enabled": ENABLE_DIRECT_JUPITER_SWAP,
        "supported_execution_venues": SUPPORTED_EXECUTION_VENUES,
        "supported_execution_markets": SUPPORTED_EXECUTION_MARKETS,
        "supported_order_types": SUPPORTED_ORDER_TYPES,
        "max_order_notional": MAX_ORDER_NOTIONAL,
        "max_order_slippage_bps": MAX_ORDER_SLIPPAGE_BPS,
        "hyperliquid_enabled": bool(HYPERLIQUID_API_KEY),
        "drift_enabled": bool(DRIFT_RPC_URL),
        "solana_enabled": bool(SOLANA_RPC_URL),
        "jupiter_api_url": JUPITER_API_URL,
        "pyth_hermes_url": PYTH_HERMES_URL,
        "pyth_api_key_configured": bool(PYTH_API_KEY),
        "wits_countries": WITS_COUNTRIES,
        "wits_products": WITS_PRODUCTS,
        "wto_api_key_configured": bool(WTO_API_KEY),
        "wto_indicators": WTO_INDICATORS,
        "wto_reporters": WTO_REPORTERS,
        "wto_partners": WTO_PARTNERS,
        "gdelt_keywords": GDELT_KEYWORDS,
        "max_leverage": MAX_LEVERAGE,
        "max_margin_usage": MAX_MARGIN_USAGE,
        "max_daily_loss": MAX_DAILY_LOSS,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "log_level": LOG_LEVEL,
    }
