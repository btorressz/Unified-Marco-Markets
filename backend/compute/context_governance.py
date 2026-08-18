"""Versioned freshness governance for historical research context.

This module governs only fallback reconstruction from persisted historical
observations. Values already recorded on an immutable decision remain the
historical source of truth for that decision and are never invalidated here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

COHORT_DEFINITION_VERSION = "v1"
FRESHNESS_POLICY_VERSION = "research_v1"

# Conservative research validity windows. They are intentionally explicit and
# versioned rather than inferred from wall-clock time or provider defaults.
CONTEXT_FRESHNESS_POLICY: dict[str, dict[str, Any]] = {
    "regime_snapshots": {"max_age_seconds": 6 * 60 * 60, "version": FRESHNESS_POLICY_VERSION},
    "index_history": {"max_age_seconds": 24 * 60 * 60, "version": FRESHNESS_POLICY_VERSION},
    "stablecoin_ticks": {"max_age_seconds": 60 * 60, "version": FRESHNESS_POLICY_VERSION},
}

COHORT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "vol_regime": {"version": COHORT_DEFINITION_VERSION, "definition": "Recorded regime label: low / normal / high / extreme."},
    "funding_regime": {"version": COHORT_DEFINITION_VERSION, "definition": "Recorded regime label: contango / neutral / backwardation."},
    "shock_state": {"version": COHORT_DEFINITION_VERSION, "definition": "Recorded shock_state; fallback shock_score: normal <= 0.5, elevated <= 1.5, high > 1.5."},
    "regime_signature": {"version": COHORT_DEFINITION_VERSION, "definition": "shock_state|funding_regime|vol_regime when all three components are usable."},
    "tariff_escalation": {"version": COHORT_DEFINITION_VERSION, "definition": "normal <= 5, elevated > 5 and <= 8, severe > 8 tariff rate-of-change."},
    "stablecoin_health": {"version": COHORT_DEFINITION_VERSION, "definition": "Recorded stable_health: stress < 0.7; fallback depeg: healthy <= 20bps, warning > 20bps, alert > 50bps."},
    "liquidity_state": {"version": COHORT_DEFINITION_VERSION, "definition": "Recorded execution depth: sufficient >= minimum; below_minimum when 0 < depth < minimum; zero_or_unavailable at depth <= 0."},
}


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _replay_inputs(record: dict[str, Any]) -> dict[str, Any]:
    return ((record.get("input_state") or {}).get("replay_inputs") or {})


def _recorded_value(record: dict[str, Any], key: str) -> Any:
    inputs = _replay_inputs(record)
    locations = (
        (inputs.get("heuristic") or {}).get("context"),
        (inputs.get("allocation") or {}).get("state"),
        (inputs.get("execution_boundary") or {}).get("data"),
        ((inputs.get("execution_boundary") or {}).get("agent") or {}).get("market_state"),
        inputs.get("risk") or {},
        (inputs.get("risk") or {}).get("runtime_state"),
        record.get("derived_state") or {},
    )
    for container in locations:
        if isinstance(container, dict) and container.get(key) is not None:
            return container[key]
    return None


def _latest_before(rows: list[dict[str, Any]], decision_ts: Any) -> dict[str, Any] | None:
    cutoff = _dt(decision_ts)
    latest: dict[str, Any] | None = None
    latest_ts: datetime | None = None
    for row in rows or []:
        try:
            ts = _dt(row.get("ts"))
        except Exception:
            continue
        if ts > cutoff:
            continue
        if latest_ts is None or ts > latest_ts or (ts == latest_ts and str(row.get("id") or "") > str((latest or {}).get("id") or "")):
            latest = row
            latest_ts = ts
    return latest


def _freshness(row: dict[str, Any] | None, decision_ts: Any, source: str) -> dict[str, Any]:
    policy = CONTEXT_FRESHNESS_POLICY[source]
    max_age = int(policy["max_age_seconds"])
    if row is None:
        return {
            "status": "unavailable",
            "origin": source,
            "observation_ts": None,
            "age_seconds": None,
            "max_age_seconds": max_age,
            "freshness_policy_version": policy["version"],
        }
    try:
        observed = _dt(row.get("ts"))
        decision = _dt(decision_ts)
    except Exception:
        return {
            "status": "unavailable",
            "origin": source,
            "observation_ts": row.get("ts"),
            "age_seconds": None,
            "max_age_seconds": max_age,
            "freshness_policy_version": policy["version"],
        }
    age = (decision - observed).total_seconds()
    status = "available" if 0 <= age <= max_age else "unavailable_stale" if age > max_age else "unavailable"
    return {
        "status": status,
        "origin": source,
        "observation_ts": observed.isoformat(),
        "age_seconds": max(0.0, age),
        "max_age_seconds": max_age,
        "freshness_policy_version": policy["version"],
    }


def _recorded_meta(field: str) -> dict[str, Any]:
    return {
        "status": "available",
        "origin": "immutable_decision",
        "observation_ts": None,
        "age_seconds": None,
        "max_age_seconds": None,
        "freshness_policy_version": FRESHNESS_POLICY_VERSION,
        "definition_version": COHORT_DEFINITIONS[field]["version"],
    }


def _historical_meta(field: str, freshness: dict[str, Any]) -> dict[str, Any]:
    return {**freshness, "definition_version": COHORT_DEFINITIONS[field]["version"]}


def _shock_from_score(value: Any) -> str:
    score = _finite(value)
    if score is None:
        return "unavailable"
    return "high" if score > 1.5 else "elevated" if score > 0.5 else "normal"


def _tariff_cohort(value: Any) -> str:
    roc = _finite(value)
    if roc is None:
        return "unavailable"
    return "severe" if roc > 8.0 else "elevated" if roc > 5.0 else "normal"


def governed_decision_context(record: dict[str, Any], context_history: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve decision cohorts with no-look-ahead plus maximum historical ages."""
    context_history = context_history or {}
    decision_ts = record.get("decision_ts")
    regime_row = _latest_before(context_history.get("regime_snapshots") or [], decision_ts)
    index_row = _latest_before(context_history.get("index_history") or [], decision_ts)
    regime_fresh = _freshness(regime_row, decision_ts, "regime_snapshots")
    index_fresh = _freshness(index_row, decision_ts, "index_history")

    governance: dict[str, dict[str, Any]] = {}

    recorded_vol = _recorded_value(record, "vol_regime")
    if recorded_vol is not None:
        vol = str(recorded_vol).lower().strip()
        governance["vol_regime"] = _recorded_meta("vol_regime")
    elif regime_fresh["status"] == "available" and regime_row and regime_row.get("vol_regime") is not None:
        vol = str(regime_row.get("vol_regime")).lower().strip()
        governance["vol_regime"] = _historical_meta("vol_regime", regime_fresh)
    else:
        vol = regime_fresh["status"] if regime_fresh["status"] == "unavailable_stale" else "unavailable"
        governance["vol_regime"] = _historical_meta("vol_regime", regime_fresh)

    recorded_funding = _recorded_value(record, "funding_regime")
    if recorded_funding is not None:
        funding = str(recorded_funding).lower().strip()
        governance["funding_regime"] = _recorded_meta("funding_regime")
    elif regime_fresh["status"] == "available" and regime_row and regime_row.get("funding_regime") is not None:
        funding = str(regime_row.get("funding_regime")).lower().strip()
        governance["funding_regime"] = _historical_meta("funding_regime", regime_fresh)
    else:
        funding = regime_fresh["status"] if regime_fresh["status"] == "unavailable_stale" else "unavailable"
        governance["funding_regime"] = _historical_meta("funding_regime", regime_fresh)

    recorded_shock = _recorded_value(record, "shock_state")
    if recorded_shock is not None:
        shock = str(recorded_shock).lower().strip()
        governance["shock_state"] = _recorded_meta("shock_state")
    elif regime_fresh["status"] == "available" and regime_row and regime_row.get("shock_state") is not None:
        shock = str(regime_row.get("shock_state")).lower().strip()
        governance["shock_state"] = _historical_meta("shock_state", regime_fresh)
    else:
        recorded_score = _recorded_value(record, "shock_score")
        if recorded_score is not None:
            shock = _shock_from_score(recorded_score)
            governance["shock_state"] = _recorded_meta("shock_state")
        elif index_fresh["status"] == "available" and index_row:
            shock = _shock_from_score(index_row.get("shock_score"))
            governance["shock_state"] = _historical_meta("shock_state", index_fresh)
        elif regime_fresh["status"] == "unavailable_stale" or index_fresh["status"] == "unavailable_stale":
            shock = "unavailable_stale"
            stale = regime_fresh if regime_fresh["status"] == "unavailable_stale" else index_fresh
            governance["shock_state"] = _historical_meta("shock_state", stale)
        else:
            shock = "unavailable"
            governance["shock_state"] = _historical_meta("shock_state", index_fresh)

    recorded_tariff = _recorded_value(record, "tariff_rate_of_change")
    if recorded_tariff is not None:
        tariff = _tariff_cohort(recorded_tariff)
        governance["tariff_escalation"] = _recorded_meta("tariff_escalation")
    elif index_fresh["status"] == "available" and index_row:
        tariff = _tariff_cohort(index_row.get("rate_of_change"))
        governance["tariff_escalation"] = _historical_meta("tariff_escalation", index_fresh)
    else:
        tariff = index_fresh["status"] if index_fresh["status"] == "unavailable_stale" else "unavailable"
        governance["tariff_escalation"] = _historical_meta("tariff_escalation", index_fresh)

    recorded_stable = _finite(_recorded_value(record, "stable_health"))
    if recorded_stable is not None:
        stable = "stress" if recorded_stable < 0.7 else "healthy"
        governance["stablecoin_health"] = _recorded_meta("stablecoin_health")
    else:
        latest_by_symbol: dict[str, dict[str, Any]] = {}
        for row in context_history.get("stablecoin_ticks") or []:
            candidate = _latest_before([row], decision_ts)
            if candidate is None:
                continue
            symbol = str(candidate.get("symbol") or "unknown").upper()
            current = latest_by_symbol.get(symbol)
            if current is None or _dt(candidate.get("ts")) > _dt(current.get("ts")) or (
                _dt(candidate.get("ts")) == _dt(current.get("ts")) and str(candidate.get("id") or "") > str(current.get("id") or "")
            ):
                latest_by_symbol[symbol] = candidate

        fresh_rows: list[dict[str, Any]] = []
        stale_rows: list[dict[str, Any]] = []
        for row in latest_by_symbol.values():
            status = _freshness(row, decision_ts, "stablecoin_ticks")
            if status["status"] == "available":
                fresh_rows.append(row)
            elif status["status"] == "unavailable_stale":
                stale_rows.append(row)
        valid_depegs = [_finite(row.get("depeg_bps")) for row in fresh_rows]
        valid_depegs = [value for value in valid_depegs if value is not None]
        if valid_depegs:
            worst = max(valid_depegs)
            stable = "alert_depeg" if worst > 50.0 else "warning_depeg" if worst > 20.0 else "healthy"
            newest = max(fresh_rows, key=lambda row: (_dt(row.get("ts")), str(row.get("id") or "")))
            governance["stablecoin_health"] = {
                **_historical_meta("stablecoin_health", _freshness(newest, decision_ts, "stablecoin_ticks")),
                "fresh_symbol_count": len(fresh_rows),
                "stale_symbol_count": len(stale_rows),
            }
        elif stale_rows:
            stable = "unavailable_stale"
            newest_stale = max(stale_rows, key=lambda row: (_dt(row.get("ts")), str(row.get("id") or "")))
            governance["stablecoin_health"] = {
                **_historical_meta("stablecoin_health", _freshness(newest_stale, decision_ts, "stablecoin_ticks")),
                "fresh_symbol_count": 0,
                "stale_symbol_count": len(stale_rows),
            }
        else:
            stable = "unavailable"
            governance["stablecoin_health"] = {
                **_historical_meta("stablecoin_health", _freshness(None, decision_ts, "stablecoin_ticks")),
                "fresh_symbol_count": 0,
                "stale_symbol_count": 0,
            }

    inputs = _replay_inputs(record)
    agent = (inputs.get("execution_boundary") or {}).get("agent") or {}
    market_state = agent.get("market_state") if isinstance(agent.get("market_state"), dict) else {}
    depth = _finite(market_state.get("liquidity_depth"))
    minimum = _finite(agent.get("min_liquidity_depth"))
    if depth is None:
        liquidity = "unavailable"
    elif depth <= 0:
        liquidity = "zero_or_unavailable"
    elif minimum is None:
        liquidity = "observed_no_threshold"
    else:
        liquidity = "below_minimum" if depth < minimum else "sufficient"
    governance["liquidity_state"] = _recorded_meta("liquidity_state") if depth is not None else {
        **_recorded_meta("liquidity_state"), "status": "unavailable"
    }

    components = (shock, funding, vol)
    if "unavailable_stale" in components:
        signature = "unavailable_stale"
    elif "unavailable" in components:
        signature = "unavailable"
    else:
        signature = f"{shock}|{funding}|{vol}"
    governance["regime_signature"] = {
        "status": "unavailable_stale" if signature == "unavailable_stale" else "unavailable" if signature == "unavailable" else "available",
        "origin": "composite",
        "observation_ts": None,
        "age_seconds": None,
        "max_age_seconds": None,
        "freshness_policy_version": FRESHNESS_POLICY_VERSION,
        "definition_version": COHORT_DEFINITIONS["regime_signature"]["version"],
    }

    return {
        "vol_regime": vol,
        "funding_regime": funding,
        "shock_state": shock,
        "regime_signature": signature,
        "tariff_escalation": tariff,
        "stablecoin_health": stable,
        "liquidity_state": liquidity,
        "context_governance": governance,
    }


def governance_contract() -> dict[str, Any]:
    return {
        "cohort_definition_version": COHORT_DEFINITION_VERSION,
        "freshness_policy_version": FRESHNESS_POLICY_VERSION,
        "freshness_policy": CONTEXT_FRESHNESS_POLICY,
        "definitions": COHORT_DEFINITIONS,
        "recorded_decision_context_policy": "immutable recorded decision values are authoritative; maximum-age rules apply only to persisted fallback reconstruction",
        "stale_label": "unavailable_stale",
    }
