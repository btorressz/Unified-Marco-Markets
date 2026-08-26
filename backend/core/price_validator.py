import logging
import math
from datetime import datetime, timezone
from statistics import median
from typing import Any

from backend import config
from backend.core.event_bus import EventBus, EventType
from backend.core.state_keys import normalize_price_symbol, price_snapshot_candidates
from backend.core.state_store import StateStore

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN_SECONDS = 60
_EXECUTION_PRICE_SOURCES = {"pyth", "kraken", "coingecko"}
_EXECUTION_PRICE_ORDER = ("pyth", "kraken", "coingecko")
_RESEARCH_PRICE_SOURCES = {"yfinance"}
_CURRENT_PRICE_SOURCES = (*_EXECUTION_PRICE_ORDER, "yfinance")
_DEFAULT_QUORUM = 2


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _deviation_bps(left: float, right: float) -> float:
    return abs(left - right) / right * 10_000.0 if right > 0 else 0.0


class PriceValidator:

    def __init__(
        self,
        deviation_threshold_bps: float = 50.0,
        state_store: StateStore | None = None,
        event_bus: EventBus | None = None,
        freshness_threshold_seconds: float | None = None,
        required_quorum: int = _DEFAULT_QUORUM,
    ):
        self.deviation_threshold_bps = float(deviation_threshold_bps)
        self.freshness_threshold_seconds = float(
            freshness_threshold_seconds
            if freshness_threshold_seconds is not None
            else config.PRICE_FRESHNESS_THRESHOLD_S
        )
        self.required_quorum = max(2, int(required_quorum))
        self._status = "UNKNOWN"
        self._reason = "No cross-venue validation performed"
        self._deviations: dict[str, float] = {}
        self._store = state_store or StateStore()
        self._bus = event_bus or EventBus()
        self._last_alert_ts: str | None = None

    def validate(
        self,
        prices: dict[str, float],
        feed_timestamps: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Validate execution-grade price agreement without changing price authority.

        Timestamp-aware calls require fresh independent execution-grade sources for
        integrity. Legacy direct calls without timestamps keep their historical
        price-only behavior so existing callers/tests remain backward compatible.
        """
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)

        valid_prices: dict[str, float] = {}
        for key, raw in (prices or {}).items():
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0 and math.isfinite(value):
                valid_prices[str(key)] = value

        execution_prices = {
            key: value
            for key, value in valid_prices.items()
            if key in _EXECUTION_PRICE_SOURCES
        }
        research_prices = {
            key: value
            for key, value in valid_prices.items()
            if key in _RESEARCH_PRICE_SOURCES
        }

        timestamp_aware = feed_timestamps is not None
        feed_ts = feed_timestamps or {}
        source_diagnostics: dict[str, dict[str, Any]] = {}
        usable_prices: dict[str, float] = {}

        for source in _EXECUTION_PRICE_ORDER:
            price = execution_prices.get(source)
            parsed_ts = _parse_timestamp(feed_ts.get(source)) if timestamp_aware else None
            age_seconds = (
                (current - parsed_ts).total_seconds()
                if parsed_ts is not None
                else None
            )
            future = age_seconds is not None and age_seconds < 0
            age_seconds = max(0.0, age_seconds) if age_seconds is not None else None

            if price is None:
                reason = "missing_price"
                fresh = False
                usable = False
            elif not timestamp_aware:
                reason = None
                fresh = None
                usable = True
            elif parsed_ts is None:
                reason = "missing_or_invalid_timestamp"
                fresh = False
                usable = False
            elif future:
                reason = "future_timestamp"
                fresh = False
                usable = False
            elif age_seconds is not None and age_seconds > self.freshness_threshold_seconds:
                reason = "stale"
                fresh = False
                usable = False
            else:
                reason = None
                fresh = True
                usable = True

            if usable and price is not None:
                usable_prices[source] = price

            source_diagnostics[source] = {
                "source": source,
                "price": round(price, 8) if price is not None else None,
                "available": price is not None,
                "execution_eligible": True,
                "timestamp": parsed_ts.isoformat() if parsed_ts is not None else None,
                "timestamp_present": parsed_ts is not None,
                "age_seconds": round(age_seconds, 2) if age_seconds is not None else None,
                "maximum_age_seconds": self.freshness_threshold_seconds if timestamp_aware else None,
                "fresh": fresh,
                "usable_for_integrity": usable,
                "reason": reason,
                "deviation_from_median_bps": None,
                "outlier": False,
            }

        usable_values = list(usable_prices.values())
        median_price = median(usable_values) if usable_values else None

        deviations: dict[str, float] = {}
        source_names = list(usable_prices)
        for index, left_source in enumerate(source_names):
            for right_source in source_names[index + 1 :]:
                dev = _deviation_bps(usable_prices[left_source], usable_prices[right_source])
                deviations[f"{left_source}_vs_{right_source}"] = round(dev, 2)

        median_deviations: dict[str, float] = {}
        if median_price is not None and median_price > 0:
            for source, price in usable_prices.items():
                dev = abs(price - median_price) / median_price * 10_000.0
                median_deviations[source] = round(dev, 2)
                source_diagnostics[source]["deviation_from_median_bps"] = round(dev, 2)

        outlier_sources: list[str] = []
        if len(usable_prices) >= 3:
            outlier_sources = [
                source
                for source, dev in median_deviations.items()
                if dev > self.deviation_threshold_bps
            ]
            for source in outlier_sources:
                source_diagnostics[source]["outlier"] = True

        max_disagreement = max(deviations.values()) if deviations else None
        dispersion = None
        if len(usable_values) >= 2 and median_price:
            dispersion = (max(usable_values) - min(usable_values)) / median_price * 10_000.0

        quorum_met = len(usable_prices) >= self.required_quorum
        warnings: list[str] = []
        if quorum_met and max_disagreement is not None and max_disagreement > self.deviation_threshold_bps:
            warnings.append(
                f"Execution-grade source disagreement {max_disagreement:.0f}bps exceeds "
                f"{self.deviation_threshold_bps:.0f}bps threshold"
            )

        if not quorum_met:
            status = "UNKNOWN"
            reason = (
                f"Insufficient fresh execution-grade price quorum: "
                f"{len(usable_prices)}/{self.required_quorum} usable sources"
                if timestamp_aware
                else f"Only {len(usable_prices)} execution-grade price source(s) available; "
                f"{self.required_quorum} required for cross-venue integrity"
            )
        elif warnings:
            status = "WARNING"
            reason = "; ".join(warnings)
        else:
            status = "OK"
            reason = ""

        selected_source = next(
            (source for source in _EXECUTION_PRICE_ORDER if source in execution_prices),
            None,
        )
        selected_diag = source_diagnostics.get(selected_source or "", {})
        selected_priority_context = {
            "policy": "priority_first",
            "priority": list(_EXECUTION_PRICE_ORDER),
            "source": selected_source,
            "price": execution_prices.get(selected_source) if selected_source else None,
            "fresh": selected_diag.get("fresh"),
            "usable_for_integrity": selected_diag.get("usable_for_integrity", False),
            "deviation_from_median_bps": selected_diag.get("deviation_from_median_bps"),
            "selection_changed": False,
            "consensus_is_diagnostic_only": True,
        }

        research_corroboration = {
            "sources": {key: round(value, 4) for key, value in research_prices.items()},
            "execution_eligible": False,
            "can_establish_integrity": False,
            "deviation_bps": {},
        }
        if research_prices and execution_prices:
            reference_name = selected_source
            if reference_name:
                reference_price = execution_prices[reference_name]
                for source, research_price in research_prices.items():
                    dev = abs(research_price - reference_price) / reference_price * 10_000.0
                    research_corroboration["reference_source"] = reference_name
                    research_corroboration["deviation_bps"][
                        f"{source}_vs_{reference_name}"
                    ] = round(dev, 2)
                research_corroborroboration["aligned"] = all(
                    value <= self.deviation_threshold_bps
                    for value in research_corroboration["deviation_bps"].values()
                )

        self._status = status
        self._reason = reason
        self._deviations = deviations

        if warnings:
            self._emit_dislocation_alert_throttled(warnings, deviations, current)

        return {
            "contract_version": 2,
            "status": status,
            "integrity_status": status,
            "reason": reason,
            "deviations": deviations,
            "deviation_bps": deviations,
            "median_deviation_bps": median_deviations,
            "prices": {key: round(value, 4) for key, value in valid_prices.items()},
            "execution_grade_prices": {
                key: round(value, 4) for key, value in execution_prices.items()
            },
            "usable_execution_grade_prices": {
                key: round(value, 4) for key, value in usable_prices.items()
            },
            "source_diagnostics": source_diagnostics,
            "usable_source_count": len(usable_prices),
            "available_execution_source_count": len(execution_prices),
            "required_quorum": self.required_quorum,
            "quorum_met": quorum_met,
            "median_reference_price": round(median_price, 8) if median_price is not None else None,
            "max_disagreement_bps": round(max_disagreement, 2) if max_disagreement is not None else None,
            "dispersion_bps": round(dispersion, 2) if dispersion is not None else None,
            "outlier_sources": outlier_sources,
            "deviation_threshold_bps": self.deviation_threshold_bps,
            "freshness_threshold_seconds": self.freshness_threshold_seconds if timestamp_aware else None,
            "freshness_evaluated": timestamp_aware,
            "selected_priority_context": selected_priority_context,
            "research_corroboration": research_corroboration,
            "feed_asof_ts": {
                key: (_parse_timestamp(value).isoformat() if _parse_timestamp(value) else value)
                for key, value in feed_ts.items()
            },
            "last_alert_ts": self._last_alert_ts,
            "consensus_is_diagnostic_only": True,
            "execution_authority_changed": False,
            "ts": current.isoformat(),
        }

    def validate_symbol(self, symbol: str) -> dict:
        """Validate one canonical asset using only that asset's current snapshots."""
        canonical = normalize_price_symbol(symbol).replace("_", "/")
        prices: dict[str, float] = {}
        feed_timestamps: dict[str, Any] = {}
        for venue in _CURRENT_PRICE_SOURCES:
            snapshot = None
            for cache_key in price_snapshot_candidates(venue, canonical):
                snapshot = self._store.get_snapshot(cache_key)
                if snapshot:
                    break
            if not isinstance(snapshot, dict):
                continue
            try:
                price = float(snapshot.get("price", 0.0))
            except (TypeError, ValueError):
                continue
            if price <= 0 or not math.isfinite(price):
                continue
            prices[venue] = price
            if snapshot.get("ts") is not None:
                feed_timestamps[venue] = snapshot["ts"]

        result = self.validate(prices, feed_timestamps=feed_timestamps)
        result["symbol"] = canonical
        return result

    def _emit_dislocation_alert_throttled(
        self,
        warnings: list[str],
        deviations: dict,
        now: datetime,
    ) -> None:
        if not self._store.check_throttle(
            "price_dislocation_alert",
            cooldown_seconds=_ALERT_COOLDOWN_SECONDS,
        ):
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
