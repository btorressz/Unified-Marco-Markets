import logging
from datetime import datetime, timezone

import httpx

from backend.config import JUPITER_API_URL, SOLANA_PRIVATE_KEY, EXECUTION_MODE, LIVE_EXECUTION_ENABLED
from backend.core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)


class JupiterExecutor:
    """Research/prototype Jupiter execution adapter.

    Quote/build functionality remains available when credentials permit, but
    transaction submission is fail-closed until real signing is implemented.
    """

    production_ready = False

    def __init__(self, event_bus: EventBus | None = None):
        self.event_bus = event_bus or EventBus()
        self.api_url = JUPITER_API_URL or "https://api.jup.ag"
        self.private_key = SOLANA_PRIVATE_KEY
        self.enabled = bool(self.private_key)
        self.execution_enabled = bool(
            self.private_key
            and EXECUTION_MODE == "live"
            and LIVE_EXECUTION_ENABLED
            and self.production_ready
        )

        if not self.enabled:
            logger.warning("JupiterExecutor disabled: SOLANA_PRIVATE_KEY not set")
        elif not self.execution_enabled:
            logger.warning("Jupiter execution disabled: prototype adapter is not production-ready")
        else:
            logger.info("JupiterExecutor initialised")

    def _disabled_response(self, action: str) -> dict:
        return {
            "status": "error",
            "reason": f"JupiterExecutor disabled — cannot {action}",
        }

    def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> dict:
        if not self.enabled:
            return self._disabled_response("get_quote")

        try:
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": str(amount),
                "slippageBps": slippage_bps,
            }

            with httpx.Client(timeout=15) as client:
                resp = client.get(f"{self.api_url}/swap/v1/quote", params=params)
                resp.raise_for_status()
                quote = resp.json()

            self.event_bus.emit(
                EventType.SWAP_QUOTED,
                source="jupiter_executor",
                payload={
                    "input_mint": input_mint,
                    "output_mint": output_mint,
                    "amount": amount,
                    "slippage_bps": slippage_bps,
                    "out_amount": quote.get("outAmount"),
                },
            )

            logger.info(
                "Jupiter quote: %s -> %s amount=%s out=%s",
                input_mint[:8], output_mint[:8], amount, quote.get("outAmount"),
            )
            return {"status": "ok", "quote": quote, "ts": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            logger.error("Jupiter get_quote error: %s", exc, exc_info=True)
            return {"status": "error", "reason": str(exc)}

    def build_swap(self, quote_response: dict) -> dict:
        if not self.enabled:
            return self._disabled_response("build_swap")

        try:
            body = {
                "quoteResponse": quote_response,
                "userPublicKey": self._get_pubkey(),
                "wrapAndUnwrapSol": True,
            }

            with httpx.Client(timeout=15) as client:
                resp = client.post(f"{self.api_url}/swap/v1/swap", json=body)
                resp.raise_for_status()
                swap_data = resp.json()

            logger.info("Jupiter swap TX built")
            return {"status": "ok", "swap_tx": swap_data, "ts": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            logger.error("Jupiter build_swap error: %s", exc, exc_info=True)
            return {"status": "error", "reason": str(exc)}

    def execute_swap(self, swap_tx: dict) -> dict:
        if not self.execution_enabled:
            return {
                "status": "error",
                "reason": "Jupiter live execution is prototype-only and transaction signing is not implemented",
            }

        try:
            from backend.execution.solana_tx import SolanaTxHelper

            tx_helper = SolanaTxHelper()
            tx_data = swap_tx.get("swapTransaction", "")

            if not tx_data:
                return {"status": "error", "reason": "No swapTransaction in swap_tx"}

            import base64
            tx_bytes = base64.b64decode(tx_data)
            result = tx_helper.sign_and_send(tx_bytes)
            if not result or result.startswith("error:"):
                return {
                    "status": "error",
                    "reason": result or "Solana transaction submission failed without a signature",
                }

            self.event_bus.emit(
                EventType.SWAP_SENT,
                source="jupiter_executor",
                payload={"tx_signature": result, "swap_tx_keys": list(swap_tx.keys())},
            )

            logger.info("Jupiter swap submitted: %s", result)
            return {
                "status": "submitted",
                "tx_signature": result,
                "requires_reconciliation": True,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error("Jupiter execute_swap error: %s", exc, exc_info=True)
            return {"status": "error", "reason": str(exc)}

    def _get_pubkey(self) -> str:
        try:
            import base58
            key_bytes = base58.b58decode(self.private_key)
            pub_bytes = key_bytes[32:] if len(key_bytes) == 64 else key_bytes
            return base58.b58encode(pub_bytes).decode()
        except Exception:
            return ""
