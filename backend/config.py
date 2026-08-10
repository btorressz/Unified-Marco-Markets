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

HYPERLIQUID_API_KEY: str = _env("HYPERLIQUID_API_KEY", "")
DRIFT_RPC_URL: str = _env("DRIFT_RPC_URL", "")
SOLANA_RPC_URL: str = _env("SOLANA_RPC_URL", "")
SOLANA_PRIVATE_KEY: str = _env("SOLANA_PRIVATE_KEY", "")
JUPITER_API_URL: str = _env("JUPITER_API_URL", "https://api.jup.ag")

EXECUTION_MODE: str = _env("EXECUTION_MODE", "paper")
if EXECUTION_MODE not in ("paper", "live"):
    logger.warning("Invalid EXECUTION_MODE=%r, defaulting to 'paper'", EXECUTION_MODE)
    EXECUTION_MODE = "paper"

# Live execution is intentionally a second, independent safety gate. The venue
# adapters remain research/prototype integrations until they are replaced with
# official/native signing flows and integration-tested.
LIVE_EXECUTION_ENABLED: bool = _env_bool("LIVE_EXECUTION_ENABLED", False)

WITS_COUNTRIES: list[str] = _env_list("WITS_COUNTRIES", ["USA", "CHN", "EU"])
WITS_PRODUCTS: list[str] = _env_list("WITS_PRODUCTS", ["TOTAL", "Capital", "Consumer", "Intermediate", "Raw"])

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
    return {
        "database_configured": bool(DATABASE_URL),
        "redis_url": REDIS_URL,
        "execution_mode": EXECUTION_MODE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "hyperliquid_enabled": bool(HYPERLIQUID_API_KEY),
        "drift_enabled": bool(DRIFT_RPC_URL),
        "solana_enabled": bool(SOLANA_RPC_URL),
        "jupiter_api_url": JUPITER_API_URL,
        "wits_countries": WITS_COUNTRIES,
        "wits_products": WITS_PRODUCTS,
        "gdelt_keywords": GDELT_KEYWORDS,
        "max_leverage": MAX_LEVERAGE,
        "max_margin_usage": MAX_MARGIN_USAGE,
        "max_daily_loss": MAX_DAILY_LOSS,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "log_level": LOG_LEVEL,
    }
