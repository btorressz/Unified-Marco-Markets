import logging
from datetime import datetime, timezone

import httpx

from backend.config import HYPERLIQUID_API_KEY, EXECUTION_MODE, LIVE_EXECUTION_ENABLED
from backend.core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)

API_BASE = "https://api.hyperliquid.xyz"


class HyperliquidExecutor:
    """Research/prototype adapter.

    Live order submission remains disabled until this class is replaced with an
    official/native signed Hyperliquid client flow and integration-tested.
    """

    production_ready = False

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or EventBus()
        self.api_key = HYPERLIQUID_API_KEY
        self.enabled = bool(
            self.api_key
            and EXECUTION_MODE == "live"
            and LIVE_EXECUTION_ENABLED
            and self.production_ready
        )

        if not self.enabled:
            logger.warning(
                "HyperliquidExecutor disabled: prototype adapter is not production-ready"
            )
        else:
            logger.info("HyperliquidExecutor initialised")

    def _disabled_response(self, action: str) -> dict:
        return {
            "status": "error",
            "reason": f"HyperliquidExecutor is prototype-only — cannot {action} until official signing integration is implemented",
        }

    def place_order(
        self,
        market: str,
        side: str,
        size: float,
        price: float,
        order_type: str = "limit",
    ) -> dict:
        if not self.enabled:
            return self._disabled_response("place_order")

        try:
            asset_index = _asset_index(market)
            self.event_bus.emit(
                EventType.ORDER_SENT,
                source="hyperliquid_executor",
                payload={"market": market, "side": side, "size": size, "price": price, "order_type": order_type},
            )

            payload = {
                "type": "order",
                "orders": [
                    {
                        "a": asset_index,
                        "b": side.lower() == "buy",
                        "p": str(price),
                        "s": str(size),
                        "r": False,
                        "t": {"limit": {"tif": "Gtc"}} if order_type == "limit" else {"trigger": {}},
                    }
                ],
                "grouping": "na",
            }

            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{API_BASE}/exchange",
                    json={"action": payload, "nonce": _nonce()},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()

            # An HTTP acknowledgement is not proof of a fill. Do not emit
            # ORDER_FILLED here; reconciliation must determine final state.
            logger.info("Hyperliquid order submission acknowledged: %s %s %s", market, side, size)
            return {
                "status": "submitted",
                "data": data,
                "requires_reconciliation": True,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Hyperliquid place_order error: %s", exc, exc_info=True)
            return {"status": "error", "reason": str(exc)}

    def cancel_order(self, oid: str) -> dict:
        if not self.enabled:
            return self._disabled_response("cancel_order")

        try:
            payload = {"type": "cancel", "cancels": [{"oid": oid}]}
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{API_BASE}/exchange",
                    json={"action": payload, "nonce": _nonce()},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()

            logger.info("Hyperliquid order cancel acknowledged: %s", oid)
            return {"status": "submitted", "data": data, "requires_reconciliation": True}
        except Exception as exc:
            logger.error("Hyperliquid cancel_order error: %s", exc, exc_info=True)
            return {"status": "error", "reason": str(exc)}

    def get_positions(self) -> list:
        if not self.api_key:
            return []

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{API_BASE}/info",
                    json={"type": "clearinghouseState", "user": self.api_key},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()

            positions = data.get("assetPositions", [])
            return [
                {
                    "venue": "hyperliquid",
                    "market": p.get("position", {}).get("coin", ""),
                    "size": float(p.get("position", {}).get("szi", 0)),
                    "entry_price": float(p.get("position", {}).get("entryPx", 0)),
                    "pnl": float(p.get("position", {}).get("unrealizedPnl", 0)),
                }
                for p in positions
                if float(p.get("position", {}).get("szi", 0)) != 0
            ]
        except Exception as exc:
            logger.error("Hyperliquid get_positions error: %s", exc, exc_info=True)
            return []

    def get_open_orders(self) -> list:
        if not self.api_key:
            return []

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{API_BASE}/info",
                    json={"type": "openOrders", "user": self.api_key},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.error("Hyperliquid get_open_orders error: %s", exc, exc_info=True)
            return []


def _asset_index(market: str) -> int:
    known = {"BTC": 0, "ETH": 1, "SOL": 2, "DOGE": 3, "AVAX": 4, "MATIC": 5}
    symbol = market.upper().replace("-PERP", "").replace("-USD", "")
    if symbol not in known:
        raise ValueError(f"Unsupported Hyperliquid market '{market}'")
    return known[symbol]


def _nonce() -> int:
    import time
    return int(time.time() * 1000)
