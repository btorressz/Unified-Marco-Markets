"""Pure, read-only geopolitical event-time market-reaction analysis.

The functions in this module compare deterministic directional expectations
with real, injected price observations.  They do not perform causal inference,
provider I/O, persistence, model calibration, or execution.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any

HORIZONS = {"1h": 3600, "4h": 14400, "24h": 86400, "7d": 604800}
ASSET_BUCKET_VERSION = "geo_market_buckets_v1"
ASSET_BUCKETS = {
    "energy": {"label": "Energy", "symbols": ["XLE"]},
    "gold": {"label": "Gold", "symbols": ["GLD"]},
    "defense": {"label": "Defense", "symbols": ["ITA"]},
    "semiconductors": {"label": "Semiconductors", "symbols": ["SMH"]},
    "china_em": {"label": "China / EM", "symbols": ["FXI", "EEM"]},
    "crypto": {"label": "Crypto", "symbols": ["BTC", "ETH", "SOL"]},
    "fx": {"label": "FX / broad USD ETF proxy", "symbols": ["UUP"], "proxy": "UUP tracks a broad US-dollar index through an ETF; it is not spot FX."},
}
EXPECTATION_MAP_VERSION = "geo_event_direction_v1"
_DEFAULT_EXPECTATIONS = {
    "energy": "UP", "gold": "UP", "defense": "UP", "semiconductors": "DOWN",
    "china_em": "DOWN", "crypto": "UNKNOWN", "fx": "UP",
}
_ENERGY_EXPECTATIONS = {**_DEFAULT_EXPECTATIONS, "semiconductors": "MIXED", "china_em": "MIXED", "fx": "UNKNOWN"}
EXPECTATION_MAP = {
    "OFAC_SANCTION_ADDED": _DEFAULT_EXPECTATIONS,
    "OFAC_SANCTION_UPDATED": _DEFAULT_EXPECTATIONS,
    "OFAC_SANCTION_REMOVED": {key: "UNKNOWN" for key in ASSET_BUCKETS},
    "SANCTIONS": _DEFAULT_EXPECTATIONS, "EXPORT_CONTROL": _DEFAULT_EXPECTATIONS,
    "SHIPPING_DISRUPTION": _ENERGY_EXPECTATIONS, "ENERGY_SHOCK": _ENERGY_EXPECTATIONS,
    "CONFLICT_ESCALATION": _DEFAULT_EXPECTATIONS, "WITS_TARIFF_UPDATE": _DEFAULT_EXPECTATIONS,
}
OBSERVED_DIRECTION_VERSION = "return_sign_v1"
NEUTRAL_BAND = 0.001
AGGREGATION_VERSION = "equal_weight_min_half_v1"
MAX_REFERENCE_AGE_SECONDS = 86400
MAX_TARGET_LAG_SECONDS = 7200
MAX_EVENTS = 25
MAX_SYMBOLS = 12
CAUSALITY_NOTICE = (
    "Observed price movement occurred after the event timestamp. "
    "This study does not establish that the event caused the movement."
)


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)


def normalize_study_event(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize an existing event without changing its evidence authority."""
    timestamp = _datetime(event.get("event_timestamp"))
    limitations = list(event.get("study_limitations") or event.get("limitations") or [])
    basis = event.get("event_time_basis")
    if timestamp is None:
        limitations.append("A valid event timestamp is required for event-time analysis.")
    if not basis:
        limitations.append("The event-time basis is not available.")
    event_type = str(event.get("event_type") or "UNKNOWN").upper()
    event_id = str(event.get("event_id") or hashlib.sha1(f"{event_type}|{event.get('title')}|{event.get('event_timestamp')}".encode()).hexdigest()[:12])
    return {
        **event,
        "event_id": event_id,
        "event_type": event_type,
        "event_timestamp": timestamp.isoformat() if timestamp else event.get("event_timestamp"),
        "event_time_basis": basis,
        "claim_type": event.get("claim_type", "proxy"),
        "observed": event.get("observed") is True,
        "proxy": event.get("proxy") is not False,
        "authoritative_evidence": event.get("authoritative_evidence") is True,
        "study_eligible": timestamp is not None and bool(basis) and event.get("synthetic") is not True,
        "study_limitations": list(dict.fromkeys(limitations)),
    }


def expected_directions(event_type: str) -> dict[str, str]:
    mapping = EXPECTATION_MAP.get(str(event_type or "").upper(), {})
    return {bucket: mapping.get(bucket, "UNKNOWN") for bucket in ASSET_BUCKETS}


def _observations(rows: list[dict[str, Any]] | None) -> list[tuple[datetime, float]]:
    result = []
    for row in rows or []:
        ts, price = _datetime(row.get("ts") or row.get("timestamp")), row.get("close", row.get("price"))
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if ts and math.isfinite(price) and price > 0:
            result.append((ts, price))
    return sorted(result)


def analyze_symbol(rows: list[dict[str, Any]] | None, event_timestamp: Any, *, now: Any = None,
                   max_reference_age_seconds: int = MAX_REFERENCE_AGE_SECONDS,
                   max_target_lag_seconds: int = MAX_TARGET_LAG_SECONDS) -> dict[str, dict[str, Any]]:
    event_ts = _datetime(event_timestamp)
    current = _datetime(now) or datetime.now(timezone.utc)
    parsed = _observations(rows)
    reference = max((row for row in parsed if event_ts and row[0] <= event_ts), default=None)
    reference_age = (event_ts - reference[0]).total_seconds() if event_ts and reference else None
    if reference_age is not None and reference_age > max_reference_age_seconds:
        reference = None
    output = {}
    for name, seconds in HORIZONS.items():
        target = event_ts + timedelta(seconds=seconds) if event_ts else None
        common = {
            "target_timestamp": target.isoformat() if target else None,
            "selected_observation_timestamp": None, "lag_seconds": None,
            "reference_timestamp": reference[0].isoformat() if reference else None,
            "reference_age_seconds": reference_age if reference else None,
            "reference_price": reference[1] if reference else None, "horizon_price": None,
            "observed_return": None, "return": None, "observed_market_reaction": False,
        }
        if target and target > current:
            output[name] = {**common, "status": "not_matured", "reason": "target horizon has not occurred"}
            continue
        if not event_ts or not reference:
            output[name] = {**common, "status": "unavailable", "reason": "no valid pre-event reference observation"}
            continue
        selected = next((row for row in parsed if row[0] >= target), None)
        lag = (selected[0] - target).total_seconds() if selected else None
        if selected is None or lag > max_target_lag_seconds:
            output[name] = {**common, "status": "unavailable", "reason": "no observation within target tolerance"}
            continue
        observed_return = selected[1] / reference[1] - 1.0
        output[name] = {
            **common, "status": "available", "selected_observation_timestamp": selected[0].isoformat(),
            "lag_seconds": lag, "horizon_price": selected[1], "observed_return": observed_return,
            "return": observed_return, "observed_market_reaction": True,
        }
    return output


def classify_observed(value: float | None, status: str = "available") -> str:
    if status == "not_matured": return "NOT_MATURED"
    if status != "available" or value is None: return "UNAVAILABLE"
    if abs(value) <= NEUTRAL_BAND: return "FLAT"
    return "UP" if value > 0 else "DOWN"


def compare_directions(expected: str, observed: str) -> str:
    if observed == "NOT_MATURED": return "NOT_MATURED"
    if observed == "UNAVAILABLE": return "UNAVAILABLE"
    if expected not in {"UP", "DOWN"}: return "UNSCORABLE" if expected == "UNKNOWN" else "MIXED"
    if observed == "FLAT": return "MIXED"
    return "MATCH" if expected == observed else "CONTRADICT"


def aggregate_bucket(symbol_results: dict[str, dict[str, dict[str, Any]]], symbols: list[str], expected: str) -> dict[str, Any]:
    observations = {}
    minimum = max(1, math.ceil(len(symbols) / 2))
    for horizon in HORIZONS:
        constituent = {symbol: symbol_results.get(symbol, {}).get(horizon, {}) for symbol in symbols}
        available = {symbol: row for symbol, row in constituent.items() if row.get("status") == "available"}
        not_matured = [row for row in constituent.values() if row.get("status") == "not_matured"]
        coverage = {"available_constituent_count": len(available), "total_constituent_count": len(symbols), "minimum_required": minimum}
        representative = next(iter(constituent.values()), {})
        timing = {key: representative.get(key) for key in (
            "target_timestamp", "selected_observation_timestamp", "lag_seconds", "reference_timestamp",
            "reference_age_seconds", "reference_price", "horizon_price",
        )}
        if not_matured and len(not_matured) == len(symbols):
            observations[horizon] = {**timing, "status": "not_matured", "return": None, "observed_return": None, "observed_market_reaction": False, "observed_direction": "NOT_MATURED", "classification": "NOT_MATURED", **coverage}
        elif len(available) < minimum:
            observations[horizon] = {**timing, "status": "unavailable", "reason": "insufficient constituent coverage", "return": None, "observed_return": None, "observed_market_reaction": False, "observed_direction": "UNAVAILABLE", "classification": "UNAVAILABLE", **coverage}
        else:
            value = sum(row["observed_return"] for row in available.values()) / len(available)
            direction = classify_observed(value)
            representative = min(available.values(), key=lambda row: row.get("selected_observation_timestamp") or "")
            observations[horizon] = {
                **representative, "return": value, "observed_return": value, "observed_direction": direction,
                "classification": compare_directions(expected, direction), "constituents": constituent, **coverage,
            }
    return {"observations": observations, "coverage_rule": AGGREGATION_VERSION}


def compute_event_study(event: dict[str, Any], histories: dict[str, list[dict[str, Any]]], *, now: Any = None,
                        history_metadata: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    normalized = normalize_study_event(event)
    directions = expected_directions(normalized["event_type"])
    symbol_results = {symbol: analyze_symbol(histories.get(symbol), normalized.get("event_timestamp"), now=now) for symbol in {s for meta in ASSET_BUCKETS.values() for s in meta["symbols"]}}
    buckets = []
    for bucket, meta in ASSET_BUCKETS.items():
        expected = directions[bucket]
        aggregate = aggregate_bucket(symbol_results, meta["symbols"], expected)
        buckets.append({"bucket": bucket, **meta, "expected_direction": expected, **aggregate})
    summary = {f"{name.lower()}_count": 0 for name in ("MATCH", "CONTRADICT", "MIXED", "UNSCORABLE", "UNAVAILABLE", "NOT_MATURED")}
    for bucket in buckets:
        for row in bucket["observations"].values(): summary[f"{row['classification'].lower()}_count"] += 1
    return {
        "event": normalized,
        "expectation_model": {"version": EXPECTATION_MAP_VERSION, "claim_type": "expected_market_impact", "observed": False, "causal_claim": False},
        "observation_model": {"version": OBSERVED_DIRECTION_VERSION, "neutral_band": NEUTRAL_BAND,
                              "market_history": "injected observed research history", "history_metadata": history_metadata or {},
                              "synthetic_allowed": False},
        "asset_bucket_model": {"version": ASSET_BUCKET_VERSION, "aggregation_version": AGGREGATION_VERSION},
        "horizons": list(HORIZONS), "buckets": buckets, "summary": summary,
        "event_study": True, "causal_claim": False, "claim_boundary": CAUSALITY_NOTICE,
        "persisted": False, "orders_submitted": 0,
    }
