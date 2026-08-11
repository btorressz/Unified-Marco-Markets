import logging
from datetime import datetime, timezone

from backend.core.state_store import StateStore
from backend.core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN_SECONDS = 60


class PriceValidator:

    def __init__(self, deviation_threshold_bps: float = 50.0, state_store: StateStore | None = None, event_bus: EventBus | None = None):
        self.deviation_threshold_bps = deviation_threshold_bps
        self._status = "UNKNOWN"
        self._reason = "No cross-venue validation performed"
        self._deviations: dict[str, float] = {}
        self._store = state_store or StateStore()
        self._bus = event_bus or EventBus()
        self._last_alert_ts: str | None = None

    def validate(self, prices: dict[str, float], feed_timestamps: dict[str, str] | None = None) -> dict:
        pyth = prices.get("pyth", 0.0)
        kraken = prices.get("kraken", 0.0)
        coingecko = prices.get("coingecko", 0.0)

        feed_ts = feed_timestamps or {}
        valid_prices = {key: value for key, value in prices.items() if value > 0}
        deviations = {}
        warnings = []
        now = datetime.now(timezone.utc)

        if len(valid_prices) < 2:
            reason = "No prices available" if not valid_prices else "Only one valid price source available; cross-venue integrity is unverified"
            self._status = "UNKNOWN"
            self._reason = reason
            self._deviations = {}
            return {
                "status": "UNKNOWN",
                "integrity_status": "UNKNOWN",
                "reason": reason,
                "deviations": {},
                "deviation_bps": {},
                "prices": {k: round(v, 4) for k, v in valid_prices.items()},
                "feed_asof_ts": feed_ts,
                "last_alert_ts": self._last_alert_ts,
                "ts": now.isoformat(),
            }

        if pyth > 0 and kraken > 0:
            dev = abs(pyth - kraken) / kraken * 10000.0
            deviations["pyth_vs_kraken"] = round(dev, 2)
            if dev > self.deviation_threshold_bps:
                warnings.append(f"Pyth vs Kraken deviation {dev:.0f}bps")

        if pyth > 0 and coingecko > 0:
            dev = abs(pyth - coingecko) / coingecko * 10000.0
            deviations["pyth_vs_coingecko"] = round(dev, 2)
            if dev > self.deviation_threshold_bps:
                warnings.append(f"Pyth vs CoinGecko deviation {dev:.0f}bps")

        if kraken > 0 and coingecko > 0 and pyth == 0:
            dev = abs(kraken - coingecko) / coingecko * 10000.0
            deviations["kraken_vs_coingecko"] = round(dev, 2)
            if dev > self.deviation_threshold_bps:
                warnings.append(f"Kraken vs CoinGecko deviation {dev:.0f}bps")

        status = "WARNING" if warnings else "OK"
        self._status = status
        self._reason = "; ".join(warnings) if warnings else ""
        self._deviations = deviations

        if warnings:
            self._emit_dislocation_alert_throttled(warnings, deviations, now)

        result = {
            "status": status,
            "integrity_status": status,
            "reason": self._reason,
            "deviations": deviations,
            "deviation_bps": deviations,
            "prices": {k: round(v, 4) for k, v in valid_prices.items()},
            "feed_asof_ts": feed_ts,
            "last_alert_ts": self._last_alert_ts,
            "ts": now.isoformat(),
        }
        return result

    def _emit_dislocation_alert_throttled(self, warnings: list[str], deviations: dict, now: datetime) -> None:
        if not self._store.check_throttle("price_dislocation_alert", cooldown_seconds=_ALERT_COOLDOWN_SECONDS):
            return
        self._last_alert_ts = now.isoformat()
        try:
            self._bus.emit(
                EventType.PRICE_DISLOCATION_ALERT,
                source="price_validator",
                payload={
                    "message": "; ".join(warnings),
                    "deviations": deviations,
                    "threshold_bps": self.deviation_threshold_bps,
                },
            )
        except Exception:
            logger.debug("Failed to emit dislocation alert", exc_info=True)

    @property
    def status(self) -> str:
        return self._status

    @property
    def is_safe(self) -> bool:
        return self._status == "OK"
