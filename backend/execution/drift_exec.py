import logging

import httpx

from backend.config import DRIFT_RPC_URL, SOLANA_PRIVATE_KEY, EXECUTION_MODE, LIVE_EXECUTION_ENABLED
from backend.core.event_bus import EventBus

logger = logging.getLogger(__name__)

DRIFT_API_BASE = "https://dlob.drift.trade"


class DriftExecutor:
    """Research/prototype Drift adapter.

    DLOB endpoints are market-data endpoints, not an authenticated transaction
    submission path. Live order submission remains disabled until an official
    Drift client signs and sends transactions on-chain.
    """

    production_ready = False

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or EventBus()
        self.rpc_url = DRIFT_RPC_URL
        self.private_key = SOLANA_PRIVATE_KEY
        self.enabled = bool(
            self.rpc_url
            and self.private_key
            and EXECUTION_MODE == "live"
            and LIVE_EXECUTION_ENABLED
            and self.production_ready
        )

        if not self.enabled:
            logger.warning("DriftExecutor disabled: prototype adapter is not production-ready")
        else:
            logger.info("DriftExecutor initialised")

    def _disabled_response(self, action: str) -> dict:
        return {
            "status": "error",
            "reason": f"DriftExecutor is prototype-only — cannot {action} until official signed transaction integration is implemented",
        }

    def place_order(
        self,
        market: str,
        side: str,
        size: float,
        price: float,
        order_type: str = "limit",
    ) -> dict:
        # Deliberately refuse to present a DLOB GET as an order submission.
        return self._disabled_response("place_order")

    def cancel_order(self, oid: str) -> dict:
        return self._disabled_response("cancel_order")

    def get_positions(self) -> list:
        if not self.rpc_url:
            return []

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{DRIFT_API_BASE}/positions",
                    params={"marketType": "perp"},
                )
                resp.raise_for_status()
                data = resp.json()

            return [
                {
                    "venue": "drift",
                    "market": p.get("marketIndex", ""),
                    "size": float(p.get("baseAssetAmount", 0)),
                    "entry_price": float(p.get("entryPrice", 0)),
                    "pnl": float(p.get("unrealizedPnl", 0)),
                }
                for p in data
                if float(p.get("baseAssetAmount", 0)) != 0
            ]
        except Exception as exc:
            logger.error("Drift get_positions error: %s", exc, exc_info=True)
            return []


def _market_index(market: str) -> int:
    known = {"SOL": 0, "BTC": 1, "ETH": 2, "APT": 3, "MATIC": 4}
    symbol = market.upper().replace("-PERP", "").replace("-USD", "")
    if symbol not in known:
        raise ValueError(f"Unsupported Drift market '{market}'")
    return known[symbol]
