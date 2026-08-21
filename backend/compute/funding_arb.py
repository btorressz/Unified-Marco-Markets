"""Pure comparison of normalized funding observations."""
from datetime import datetime, timezone

MAX_TIMESTAMP_SKEW_SECONDS = 300
MAX_AGE_SECONDS = 300
MAX_FUTURE_SKEW_SECONDS = 30
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
            "annualized_rate_spread_bps": None,
            "short_a_long_b_carry_annual": None,
            "long_a_short_b_carry_annual": None,
            "selected_carry_annual": None,
            "persistence_reason": "insufficient_comparable_history",
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
        if min(ages) < -MAX_FUTURE_SKEW_SECONDS:
            reasons.append("future_observation")
        if reasons:
            return _unavailable(reasons, market)

        def annual(obs, side):
            interval = int(obs["interval_seconds"])
            if interval <= 0:
                raise ValueError("invalid funding interval")
            return float(obs[f"{side}_cashflow_rate"]) * 31557600 / interval

        short_a_long_b = annual(hyperliquid, "short") + annual(drift, "long")
        long_a_short_b = annual(hyperliquid, "long") + annual(drift, "short")
        if short_a_long_b >= long_a_short_b:
            direction, carry = "short_hl_long_drift", short_a_long_b
        else:
            direction, carry = "long_hl_short_drift", long_a_short_b
        # Spread is annualized and therefore comparable across different intervals.
        hl_annual = annual(hyperliquid, "short")
        drift_annual = annual(drift, "short")
        annualized_spread_bps = (hl_annual - drift_annual) * 10_000
        raw_spread = None
        if hyperliquid["interval_seconds"] == drift["interval_seconds"]:
            left, right = hyperliquid.get("normalized_funding_rate"), drift.get("normalized_funding_rate")
            raw_spread = (float(left) - float(right)) * 10_000 if left is not None and right is not None else None
        signal = direction if carry * 10_000 >= SPREAD_THRESHOLD_BPS else "none"
        persistence, persistence_reason = self._persistence(history, direction, market)
        return {"available": True, "arb_signal": signal, "spread_bps": round(annualized_spread_bps, 2),
                "raw_period_spread_bps": round(raw_spread, 2) if raw_spread is not None else None,
                "spread_semantics": "annualized_short_cashflow_rate_spread_bps",
                "annualized_rate_spread_bps": round(annualized_spread_bps, 2),
                "short_a_long_b_carry_annual": short_a_long_b,
                "long_a_short_b_carry_annual": long_a_short_b,
                "selected_carry_annual": carry,
                "persistence_minutes": persistence, "persistence_reason": persistence_reason,
                "expected_net_carry": carry,
                "direction": direction if signal != "none" else None, "confidence": None,
                "metadata": {"venues": ["hyperliquid", "drift"], "market": market,
                    "intervals": [hyperliquid["interval_seconds"], drift["interval_seconds"]],
                    "timestamp_skew_seconds": skew,
                    "source_ids": [hyperliquid["source_id"], drift["source_id"]],
                    "contract_versions": [1, 1], "research_only": True, "no_auto_trade": True}}

    def _persistence(self, history, direction, market):
        """Measure continuity from caller-supplied durable aligned comparisons."""
        if not history:
            return None, "insufficient_comparable_history"
        matching = []
        for row in history:
            if row.get("market") != market:
                continue
            if row.get("direction") != direction:
                break
            ts = _timestamp(row.get("timestamp") or row.get("observed_at") or row.get("provider_timestamp"))
            if ts:
                matching.append(ts)
            else:
                break
        if len(matching) < 2:
            return None, "insufficient_comparable_history"
        matching.sort()
        if any((right-left).total_seconds() > MAX_TIMESTAMP_SKEW_SECONDS
               for left, right in zip(matching, matching[1:])):
            return None, "history_gap_exceeded"
        return max(0.0, (matching[-1] - matching[0]).total_seconds() / 60), None


def detect_arb(hyperliquid, drift, history=None, now=None):
    return FundingArbDetector().detect_arb(hyperliquid, drift, history, now)


def align_comparison_history(a_rows, b_rows, market, max_rows=500):
    """Deterministically align bounded durable current-observation histories."""
    result, used_b = [], set()
    for a in a_rows[:max_rows]:
        a_ts = _timestamp(a.get("provider_timestamp") or a.get("retrieved_at") or a.get("ts"))
        if not a_ts or a.get("rate_kind") != "current" or a.get("contract_version") != 1:
            continue
        candidates = []
        for index, b in enumerate(b_rows[:max_rows]):
            b_ts = _timestamp(b.get("provider_timestamp") or b.get("retrieved_at") or b.get("ts"))
            if index not in used_b and b_ts and b.get("rate_kind") == "current" and b.get("contract_version") == 1:
                candidates.append((abs((a_ts - b_ts).total_seconds()), index, b, b_ts))
        if not candidates:
            continue
        skew, index, b, b_ts = min(candidates, key=lambda item: item[0])
        if skew > MAX_TIMESTAMP_SKEW_SECONDS:
            continue
        used_b.add(index)
        try:
            carry_ab = (float(a["short_cashflow_rate"]) * 31557600 / int(a["interval_seconds"]) +
                        float(b["long_cashflow_rate"]) * 31557600 / int(b["interval_seconds"]))
            carry_ba = (float(a["long_cashflow_rate"]) * 31557600 / int(a["interval_seconds"]) +
                        float(b["short_cashflow_rate"]) * 31557600 / int(b["interval_seconds"]))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        result.append({"market": market, "timestamp": max(a_ts, b_ts),
            "direction": "short_hl_long_drift" if carry_ab >= carry_ba else "long_hl_short_drift",
            "selected_carry_annual": max(carry_ab, carry_ba), "timestamp_skew_seconds": skew})
    return sorted(result, key=lambda row: row["timestamp"], reverse=True)
