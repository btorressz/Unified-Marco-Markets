"""Pure comparison of normalized funding observations."""
from datetime import datetime, timezone

MAX_TIMESTAMP_SKEW_SECONDS = 300
MAX_AGE_SECONDS = 300
SPREAD_THRESHOLD_BPS = 5.0


def _timestamp(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _unavailable(reasons, market=None):
    return {"available": False, "reasons": reasons, "arb_signal": None,
            "spread_bps": None, "persistence_minutes": None,
            "expected_net_carry": None, "direction": None, "confidence": None,
            "metadata": {"market": market, "research_only": True, "no_auto_trade": True}}


class FundingArbDetector:
    def detect_arb(self, hyperliquid: dict | None, drift: dict | None,
                   history: list[dict] | None = None, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        reasons = []
        for name, obs in (("hyperliquid", hyperliquid), ("drift", drift)):
            if not obs:
                reasons.append(f"missing_{name}_observation")
            elif obs.get("contract_version") != 1:
                reasons.append(f"{name}_not_normalized_v1")
            elif obs.get("normalized_funding_rate") is None:
                reasons.append(f"{name}_normalization_unavailable")
            elif obs.get("long_cashflow_rate") is None or obs.get("short_cashflow_rate") is None:
                reasons.append(f"{name}_side_cashflows_unavailable")
        market = (hyperliquid or {}).get("market") or (drift or {}).get("market")
        if reasons:
            return _unavailable(reasons, market)
        if hyperliquid["market"] != drift["market"]:
            return _unavailable(["market_mismatch"], market)
        hl_ts = _timestamp(hyperliquid.get("provider_timestamp") or hyperliquid.get("retrieved_at"))
        drift_ts = _timestamp(drift.get("provider_timestamp") or drift.get("retrieved_at"))
        if not hl_ts or not drift_ts:
            return _unavailable(["invalid_timestamp"], market)
        skew = abs((hl_ts - drift_ts).total_seconds())
        ages = ((now - hl_ts).total_seconds(), (now - drift_ts).total_seconds())
        if skew > MAX_TIMESTAMP_SKEW_SECONDS:
            reasons.append("timestamp_skew_exceeded")
        if max(ages) > MAX_AGE_SECONDS:
            reasons.append("stale_observation")
        if reasons:
            return _unavailable(reasons, market)

        hl_rate = float(hyperliquid["normalized_funding_rate"])
        drift_rate = float(drift["normalized_funding_rate"])
        spread_bps = (hl_rate - drift_rate) * 10_000
        if spread_bps >= 0:
            direction = "short_hl_long_drift"
            carry = float(hyperliquid["short_cashflow_rate"]) * 31557600 / hyperliquid["interval_seconds"] + float(drift["long_cashflow_rate"]) * 31557600 / drift["interval_seconds"]
        else:
            direction = "long_hl_short_drift"
            carry = float(hyperliquid["long_cashflow_rate"]) * 31557600 / hyperliquid["interval_seconds"] + float(drift["short_cashflow_rate"]) * 31557600 / drift["interval_seconds"]
        signal = direction if abs(spread_bps) >= SPREAD_THRESHOLD_BPS else "none"
        return {"available": True, "arb_signal": signal, "spread_bps": round(spread_bps, 2),
                "persistence_minutes": None, "expected_net_carry": carry,
                "direction": direction if signal != "none" else None, "confidence": None,
                "metadata": {"venues": ["hyperliquid", "drift"], "market": market,
                    "intervals": [hyperliquid["interval_seconds"], drift["interval_seconds"]],
                    "timestamp_skew_seconds": skew,
                    "source_ids": [hyperliquid["source_id"], drift["source_id"]],
                    "contract_versions": [1, 1], "research_only": True, "no_auto_trade": True}}


def detect_arb(hyperliquid, drift, history=None, now=None):
    return FundingArbDetector().detect_arb(hyperliquid, drift, history, now)
