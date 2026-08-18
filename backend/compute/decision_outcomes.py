"""Deterministic realized-outcome evaluation for immutable decision audit records.

This module is research-only. It receives historical observations and lifecycle
rows from callers and never reads Redis, writes persistence, or routes orders.
The output describes subsequent market moves; blocked-decision outcomes are
counterfactual opportunity/avoidance observations, not realized P&L.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any, Callable

HORIZONS = {"1h": 3600, "4h": 14400, "24h": 86400, "7d": 604800}
DEFAULT_OUTCOME_TOLERANCE_SECONDS = 3600


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


def _finite_positive(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _replay_inputs(record: dict[str, Any]) -> dict[str, Any]:
    return ((record.get("input_state") or {}).get("replay_inputs") or {})


def symbol_candidates(record: dict[str, Any]) -> list[str]:
    """Return deterministic historical symbol aliases, exact decision symbol first."""
    raw = str(record.get("symbol") or record.get("market") or "").upper().strip()
    if not raw:
        return []
    base = raw.replace("-PERP", "").split("/")[0].split("_")[0].split("-")[0]
    candidates = [raw, f"{base}-PERP", f"{base}/USD", f"{base}USD", f"{base}_USD"]
    if base == "SOL":
        candidates.append("SOLANA/USD")
    if base == "BTC":
        candidates.append("BITCOIN/USD")
    if base == "ETH":
        candidates.append("ETHEREUM/USD")
    result: list[str] = []
    for candidate in candidates:
        normalized = candidate.upper()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def horizon_targets(decision_ts: Any) -> dict[str, str]:
    decision_time = _dt(decision_ts)
    return {
        label: (decision_time + timedelta(seconds=seconds)).isoformat()
        for label, seconds in HORIZONS.items()
    }


def linked_admission_decision_id(record: dict[str, Any]) -> str:
    """Resolve the order-intent decision ID for admission or final audit records."""
    provenance = record.get("input_provenance") or {}
    intent = record.get("execution_intent") or {}
    return str(
        provenance.get("admission_decision_id")
        or intent.get("admission_decision_id")
        or record.get("id")
        or ""
    )


def _execution_facts(record: dict[str, Any]) -> dict[str, Any]:
    inputs = _replay_inputs(record)
    boundary = inputs.get("execution_boundary") or {}
    data = boundary.get("data") or {}
    order = data.get("order") if isinstance(data.get("order"), dict) else {}
    intent_order = (record.get("execution_intent") or {}).get("order") or {}

    side = str(order.get("side") or intent_order.get("side") or "").lower().strip()
    entry_price = _finite_positive(data.get("fill_price")) or _finite_positive(order.get("price")) or _finite_positive(intent_order.get("price"))
    size = _finite_positive(order.get("size")) or _finite_positive(intent_order.get("size"))

    final = record.get("final_decision") or {}
    if isinstance(final.get("allowed"), bool):
        action = "allow" if final["allowed"] else "block"
    else:
        decision = str(final.get("decision") or "").lower().strip()
        action = decision if decision in {"allow", "block"} else "unknown"

    return {
        "action": action,
        "side": side,
        "entry_price": entry_price,
        "size": size,
        "venue": str(record.get("venue") or order.get("venue") or intent_order.get("venue") or "").lower(),
        "market": str(record.get("market") or order.get("market") or intent_order.get("market") or "").upper(),
        "symbol": str(record.get("symbol") or record.get("market") or "").upper(),
    }


def _venue_rank(venue: str, preferred: str) -> tuple[int, int, str]:
    venue = str(venue or "").lower()
    preferred = str(preferred or "").lower()
    if preferred and preferred != "paper" and venue == preferred:
        return (0, 0, venue)
    preference = ["drift", "pyth", "kraken", "coingecko", "hyperliquid", "paper"]
    try:
        index = preference.index(venue)
    except ValueError:
        index = len(preference)
    return (1, index, venue)


def _select_observation(
    rows: list[dict[str, Any]],
    *,
    horizon: str,
    candidates: list[str],
    preferred_venue: str,
) -> dict[str, Any] | None:
    eligible = [row for row in rows if str(row.get("horizon")) == horizon]
    if not eligible:
        return None
    rank = {symbol: index for index, symbol in enumerate(candidates)}
    eligible.sort(
        key=lambda row: (
            rank.get(str(row.get("symbol") or "").upper(), len(rank) + 1),
            *_venue_rank(str(row.get("venue") or ""), preferred_venue),
            _dt(row.get("ts")),
            str(row.get("id") or ""),
        )
    )
    return eligible[0]


def _market_classification(action: str, signed_return: float) -> str:
    if signed_return == 0:
        return "flat_market_move"
    if action == "allow":
        return "favorable_move_after_allow" if signed_return > 0 else "adverse_move_after_allow"
    if action == "block":
        return "missed_favorable_move_after_block" if signed_return > 0 else "avoided_adverse_move_after_block"
    return "directional_market_move"


def interpret_action_against_outcome(action: str, signed_return: float) -> str:
    action = str(action or "").lower().strip()
    if action == "allow":
        return "requested_side_favorable" if signed_return > 0 else "requested_side_adverse" if signed_return < 0 else "flat"
    if action == "block":
        return "missed_favorable_move" if signed_return > 0 else "avoided_adverse_move" if signed_return < 0 else "flat"
    return "unavailable"


def summarize_execution_lifecycle(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    if payload.get("available") is False:
        return {
            "available": False,
            "status": "unavailable",
            "reason": payload.get("reason") or "execution_lifecycle_unavailable",
            "intent_count": 0,
            "order_count": 0,
            "fill_count": 0,
        }

    intents = list(payload.get("intents") or [])
    orders = list(payload.get("orders") or [])
    fills = list(payload.get("fills") or [])
    total_fill_size = sum(float(row.get("size") or 0.0) for row in fills)
    weighted_notional = sum(float(row.get("size") or 0.0) * float(row.get("price") or 0.0) for row in fills)
    avg_fill = weighted_notional / total_fill_size if total_fill_size > 0 else None
    return {
        "available": True,
        "status": "filled" if fills else "linked_no_fill" if intents or orders else "no_linked_execution",
        "intent_count": len(intents),
        "order_count": len(orders),
        "fill_count": len(fills),
        "filled": bool(fills),
        "filled_size": total_fill_size,
        "average_fill_price": avg_fill,
        "fees": sum(float(row.get("fee") or 0.0) for row in fills),
        "funding": sum(float(row.get("funding") or 0.0) for row in fills),
        "slippage": sum(float(row.get("slippage") or 0.0) for row in fills),
        "order_statuses": sorted({str(row.get("status") or "unknown") for row in orders}),
    }


def evaluate_decision_outcomes(
    record: dict[str, Any],
    observations: dict[str, Any] | list[dict[str, Any]],
    execution_lifecycle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate subsequent market moves for one final execution decision."""
    facts = _execution_facts(record)
    rows = list(observations.get("observations") or []) if isinstance(observations, dict) else list(observations or [])
    observation_available = not isinstance(observations, dict) or observations.get("available", True)

    base = {
        "decision_id": str(record.get("id") or ""),
        "decision_type": record.get("decision_type"),
        "decision_ts": _dt(record.get("decision_ts")).isoformat(),
        "evaluation_scope": "realized market move after requested execution",
        "decision": facts,
        "actual_execution": summarize_execution_lifecycle(execution_lifecycle),
        "horizons": list(HORIZONS),
        "orders_submitted": 0,
        "persisted": False,
        "research_only": True,
    }

    if facts["action"] not in {"allow", "block"}:
        return {**base, "outcome_status": "unavailable", "reason": "decision is not a final ALLOW/BLOCK execution decision", "outcomes": {}}
    if facts["side"] not in {"buy", "sell"}:
        return {**base, "outcome_status": "unavailable", "reason": "execution side is unavailable", "outcomes": {}}
    if facts["entry_price"] is None:
        return {**base, "outcome_status": "unavailable", "reason": "decision reference price is unavailable", "outcomes": {}}
    if not observation_available:
        return {**base, "outcome_status": "unavailable", "reason": (observations or {}).get("reason") or "historical market observations are unavailable", "outcomes": {}}

    candidates = symbol_candidates(record)
    outcomes: dict[str, Any] = {}
    for horizon in HORIZONS:
        observation = _select_observation(rows, horizon=horizon, candidates=candidates, preferred_venue=facts["venue"])
        if not observation:
            outcomes[horizon] = None
            continue
        future_price = _finite_positive(observation.get("price"))
        if future_price is None:
            outcomes[horizon] = None
            continue
        raw_return = future_price / facts["entry_price"] - 1.0
        signed_return = raw_return if facts["side"] == "buy" else -raw_return
        outcomes[horizon] = {
            "target_ts": observation.get("target_ts"),
            "observed_ts": _dt(observation.get("ts")).isoformat(),
            "lag_seconds": observation.get("lag_seconds"),
            "source": {"venue": observation.get("venue"), "symbol": observation.get("symbol")},
            "decision_price": facts["entry_price"],
            "price": future_price,
            "raw_return": raw_return,
            "signed_return": signed_return,
            "requested_side_favorable": signed_return > 0 if signed_return != 0 else None,
            "classification": _market_classification(facts["action"], signed_return),
            "pnl_status": "counterfactual_market_move_only" if facts["action"] == "block" else "market_move_not_realized_pnl",
        }

    available_count = sum(value is not None for value in outcomes.values())
    return {
        **base,
        "outcome_status": "available" if available_count else "unavailable",
        "reason": None if available_count else "no historical market observation matched the requested horizons",
        "available_horizon_count": available_count,
        "outcomes": outcomes,
        "interpretation": "ALLOW/BLOCK evaluation describes the requested side's subsequent market move. BLOCK rows do not represent realized P&L.",
    }


# ---------------------------------------------------------------------------
# Decision cohort / regime reconstruction
# ---------------------------------------------------------------------------


def _container_value(record: dict[str, Any], key: str) -> Any:
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
        if ts <= cutoff and (latest_ts is None or ts > latest_ts or (ts == latest_ts and str(row.get("id") or "") > str((latest or {}).get("id") or ""))):
            latest = row
            latest_ts = ts
    return latest


def _latest_stablecoins_before(rows: list[dict[str, Any]], decision_ts: Any) -> dict[str, dict[str, Any]]:
    cutoff = _dt(decision_ts)
    latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for row in rows or []:
        try:
            ts = _dt(row.get("ts"))
        except Exception:
            continue
        if ts > cutoff:
            continue
        symbol = str(row.get("symbol") or "unknown").upper()
        current = latest.get(symbol)
        if current is None or ts > current[0] or (ts == current[0] and str(row.get("id") or "") > str(current[1].get("id") or "")):
            latest[symbol] = (ts, row)
    return {symbol: row for symbol, (_, row) in latest.items()}


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


def _stablecoin_cohort(record: dict[str, Any], context_history: dict[str, Any], decision_ts: Any) -> str:
    stable_health = _finite(_container_value(record, "stable_health"))
    if stable_health is not None:
        return "stress" if stable_health < 0.7 else "healthy"

    latest = _latest_stablecoins_before(context_history.get("stablecoin_ticks") or [], decision_ts)
    depegs = [_finite(row.get("depeg_bps")) for row in latest.values()]
    valid = [value for value in depegs if value is not None]
    if not valid:
        return "unavailable"
    worst = max(valid)
    if worst > 50.0:
        return "alert_depeg"
    if worst > 20.0:
        return "warning_depeg"
    return "healthy"


def _liquidity_cohort(record: dict[str, Any]) -> str:
    inputs = _replay_inputs(record)
    agent = (inputs.get("execution_boundary") or {}).get("agent") or {}
    market_state = agent.get("market_state") if isinstance(agent.get("market_state"), dict) else {}
    depth = _finite(market_state.get("liquidity_depth"))
    minimum = _finite(agent.get("min_liquidity_depth"))
    if depth is None:
        return "unavailable"
    if depth <= 0:
        return "zero_or_unavailable"
    if minimum is None:
        return "observed_no_threshold"
    return "below_minimum" if depth < minimum else "sufficient"


def decision_regime_context(record: dict[str, Any], context_history: dict[str, Any] | None = None) -> dict[str, str]:
    """Resolve truthful decision-time regimes from recorded or persisted history."""
    context_history = context_history or {}
    decision_ts = record.get("decision_ts")
    regime_row = _latest_before(context_history.get("regime_snapshots") or [], decision_ts)
    index_row = _latest_before(context_history.get("index_history") or [], decision_ts)

    vol = _container_value(record, "vol_regime")
    if vol is None and regime_row:
        vol = regime_row.get("vol_regime")
    vol_regime = str(vol).lower().strip() if vol is not None else "unavailable"

    funding = _container_value(record, "funding_regime")
    if funding is None and regime_row:
        funding = regime_row.get("funding_regime")
    funding_regime = str(funding).lower().strip() if funding is not None else "unavailable"

    shock = _container_value(record, "shock_state")
    if shock is not None:
        shock_state = str(shock).lower().strip()
    elif regime_row and regime_row.get("shock_state") is not None:
        shock_state = str(regime_row.get("shock_state")).lower().strip()
    else:
        score = _container_value(record, "shock_score")
        if score is None and index_row:
            score = index_row.get("shock_score")
        shock_state = _shock_from_score(score)

    tariff_roc = _container_value(record, "tariff_rate_of_change")
    if tariff_roc is None and index_row:
        tariff_roc = index_row.get("rate_of_change")
    tariff = _tariff_cohort(tariff_roc)

    stablecoin = _stablecoin_cohort(record, context_history, decision_ts)
    liquidity = _liquidity_cohort(record)
    signature = f"{shock_state}|{funding_regime}|{vol_regime}"
    if "unavailable" in {shock_state, funding_regime, vol_regime}:
        signature = "unavailable"

    return {
        "vol_regime": vol_regime,
        "funding_regime": funding_regime,
        "shock_state": shock_state,
        "regime_signature": signature,
        "tariff_escalation": tariff,
        "stablecoin_health": stablecoin,
        "liquidity_state": liquidity,
    }


def _component_label(record: dict[str, Any], component: str) -> str:
    versions = record.get("component_versions") or {}
    value = versions.get(component)
    if isinstance(value, dict):
        ident = value.get("id") or value.get("model_id") or value.get("heuristic_id") or component
        version = value.get("version") or value.get("model_version") or value.get("heuristic_version")
        return f"{ident}@{version}" if version is not None else str(ident)
    if value:
        return str(value)
    result = record.get(f"{component}_result") or {}
    ident = result.get("model_id") or result.get("heuristic_id")
    version = result.get("model_version") or result.get("heuristic_version")
    if ident:
        return f"{ident}@{version}" if version is not None else str(ident)
    return "not_used" if result.get("status") == "not_used" else "unavailable"


def _metric_summary(items: list[dict[str, Any]], horizon: str) -> dict[str, Any]:
    evaluated = [item for item in items if (item.get("outcomes") or {}).get(horizon) is not None]
    allows = [item for item in evaluated if (item.get("decision") or {}).get("action") == "allow"]
    blocks = [item for item in evaluated if (item.get("decision") or {}).get("action") == "block"]
    signed = [float(item["outcomes"][horizon]["signed_return"]) for item in evaluated]
    allow_signed = [float(item["outcomes"][horizon]["signed_return"]) for item in allows]
    block_signed = [float(item["outcomes"][horizon]["signed_return"]) for item in blocks]
    favorable = sum(value > 0 for value in signed)
    quality_count = sum(
        1
        for item in evaluated
        if (
            ((item.get("decision") or {}).get("action") == "allow" and float(item["outcomes"][horizon]["signed_return"]) > 0)
            or ((item.get("decision") or {}).get("action") == "block" and float(item["outcomes"][horizon]["signed_return"]) < 0)
        )
    )
    flat_count = sum(value == 0 for value in signed)
    return {
        "sample_count": len(items),
        "evaluated_count": len(evaluated),
        "allow_count": len(allows),
        "block_count": len(blocks),
        "decision_quality_count": quality_count,
        "decision_quality_rate": quality_count / len(evaluated) if evaluated else None,
        "flat_outcome_count": flat_count,
        "requested_side_favorable_rate": favorable / len(signed) if signed else None,
        "average_signed_return": mean(signed) if signed else None,
        "allow_average_signed_return": mean(allow_signed) if allow_signed else None,
        "block_avoided_adverse_move_rate": sum(value < 0 for value in block_signed) / len(block_signed) if block_signed else None,
        "block_opportunity_cost_rate": sum(value > 0 for value in block_signed) / len(block_signed) if block_signed else None,
    }


def _group_metrics(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    key_fn: Callable[[dict[str, Any], dict[str, Any]], Any],
    horizon: str,
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record, result in pairs:
        groups.setdefault(str(key_fn(record, result)), []).append(result)
    return {key: _metric_summary(values, horizon) for key, values in sorted(groups.items())}


def _cohort_groups(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    contexts: dict[str, dict[str, str]],
    field: str,
    horizon: str,
) -> dict[str, Any]:
    return _group_metrics(
        pairs,
        lambda record, result: contexts.get(str(record.get("id") or ""), {}).get(field, "unavailable"),
        horizon,
    )


def performance_summary(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    primary_horizon: str = "4h",
    context_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if primary_horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {primary_horizon}")
    results = [result for _, result in pairs]
    horizon_metrics = {horizon: _metric_summary(results, horizon) for horizon in HORIZONS}
    context_history = context_history or {}
    contexts = {
        str(record.get("id") or ""): decision_regime_context(record, context_history)
        for record, _ in pairs
    }

    by_market = _group_metrics(pairs, lambda record, result: record.get("market") or "unknown", primary_horizon)
    by_venue = _group_metrics(pairs, lambda record, result: record.get("venue") or "unknown", primary_horizon)
    by_type = _group_metrics(pairs, lambda record, result: record.get("decision_type") or "unknown", primary_horizon)
    by_heuristic = _group_metrics(pairs, lambda record, result: _component_label(record, "heuristic"), primary_horizon)
    by_model = _group_metrics(pairs, lambda record, result: _component_label(record, "ml"), primary_horizon)

    performance_by_regime = {
        "vol_regime": _cohort_groups(pairs, contexts, "vol_regime", primary_horizon),
        "funding_regime": _cohort_groups(pairs, contexts, "funding_regime", primary_horizon),
        "shock_state": _cohort_groups(pairs, contexts, "shock_state", primary_horizon),
    }
    performance_by_cohort = {
        "tariff_escalation": _cohort_groups(pairs, contexts, "tariff_escalation", primary_horizon),
        "stablecoin_health": _cohort_groups(pairs, contexts, "stablecoin_health", primary_horizon),
        "liquidity_state": _cohort_groups(pairs, contexts, "liquidity_state", primary_horizon),
    }
    performance_by_signature = _cohort_groups(pairs, contexts, "regime_signature", primary_horizon)

    dated: list[tuple[datetime, dict[str, Any]]] = []
    for record, result in pairs:
        try:
            dated.append((_dt(record.get("decision_ts")), result))
        except Exception:
            pass
    decay: dict[str, Any] = {"available": False}
    if dated:
        end = max(ts for ts, _ in dated)
        recent = [result for ts, result in dated if ts > end - timedelta(days=30)]
        prior = [result for ts, result in dated if end - timedelta(days=60) < ts <= end - timedelta(days=30)]
        recent_metrics = _metric_summary(recent, primary_horizon)
        prior_metrics = _metric_summary(prior, primary_horizon)
        decay = {
            "available": bool(recent_metrics["evaluated_count"] and prior_metrics["evaluated_count"]),
            "recent_30d": recent_metrics,
            "prior_30d": prior_metrics,
        }
        if decay["available"]:
            r = recent_metrics
            p = prior_metrics
            decay["changes"] = {
                "decision_quality_rate_change": (
                    r["decision_quality_rate"] - p["decision_quality_rate"]
                    if r["decision_quality_rate"] is not None and p["decision_quality_rate"] is not None else None
                ),
                "requested_side_favorable_rate_change": (
                    r["requested_side_favorable_rate"] - p["requested_side_favorable_rate"]
                    if r["requested_side_favorable_rate"] is not None and p["requested_side_favorable_rate"] is not None else None
                ),
                "average_signed_return_change": (
                    r["average_signed_return"] - p["average_signed_return"]
                    if r["average_signed_return"] is not None and p["average_signed_return"] is not None else None
                ),
            }

    context_quality = {
        field: sum(1 for value in contexts.values() if value.get(field) != "unavailable")
        for field in (
            "vol_regime", "funding_regime", "shock_state", "regime_signature",
            "tariff_escalation", "stablecoin_health", "liquidity_state",
        )
    }

    return {
        "status": "available" if any(metric["evaluated_count"] for metric in horizon_metrics.values()) else "unavailable",
        "research_only": True,
        "primary_horizon": primary_horizon,
        "horizons": horizon_metrics,
        "performance_by_market": by_market,
        "performance_by_venue": by_venue,
        "performance_by_decision_type": by_type,
        # Backward-compatible alias retained for existing clients.
        "performance_by_vol_regime": performance_by_regime["vol_regime"],
        "performance_by_regime": performance_by_regime,
        "performance_by_regime_signature": performance_by_signature,
        "performance_by_cohort": performance_by_cohort,
        "performance_by_heuristic_version": by_heuristic,
        "performance_by_model_version": by_model,
        "performance_decay": decay,
        "context_coverage": {
            "decision_count": len(pairs),
            "available_counts": context_quality,
            "source_errors": dict(context_history.get("errors") or {}),
            "truncated": dict(context_history.get("truncated") or {}),
            "historical_context_available": bool(context_history.get("available", False)),
        },
        "cohort_definitions": {
            "vol_regime": "Existing recorded regime labels: low / normal / high / extreme when available.",
            "funding_regime": "Existing recorded regime labels: contango / neutral / backwardation when available.",
            "shock_state": "Existing recorded shock_state; otherwise deterministic shock_score buckets: normal <= 0.5, elevated <= 1.5, high > 1.5.",
            "regime_signature": "shock_state|funding_regime|vol_regime; unavailable unless all three are known.",
            "tariff_escalation": "Derived from existing RulesEngine thresholds: normal <= 5, elevated > 5 and <= 8, severe > 8 tariff rate-of-change.",
            "stablecoin_health": "Uses recorded normalized stable_health when present (stress < 0.7); otherwise persisted depeg thresholds: healthy <= 20bps, warning > 20bps, alert > 50bps.",
            "liquidity_state": "Uses recorded execution-agent depth and its recorded minimum: sufficient >= minimum, below_minimum when 0 < depth < minimum; zero is labeled zero_or_unavailable rather than healthy.",
            "decision_quality_rate": "ALLOW is favorable when the requested-side signed return is positive; BLOCK is favorable when it is negative. Flat outcomes are not counted as favorable decisions.",
        },
        "interpretation": "Decision quality evaluates whether the historical ALLOW/BLOCK choice aligned with the requested side's later market move. BLOCK metrics quantify avoided adverse moves versus missed favorable moves, not realized trading P&L.",
    }


def realized_counterfactual_comparison(
    outcome_result: dict[str, Any],
    counterfactual_result: dict[str, Any],
    *,
    horizon: str = "4h",
) -> dict[str, Any]:
    if horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {horizon}")
    outcome = (outcome_result.get("outcomes") or {}).get(horizon)
    if not outcome:
        return {"available": False, "horizon": horizon, "reason": "realized horizon outcome unavailable"}

    signed_return = float(outcome["signed_return"])
    effects = counterfactual_result.get("effects") or {}
    original = effects.get("original_final") or {}
    counterfactual = effects.get("counterfactual_final") or {}

    def action(value: dict[str, Any]) -> str:
        if isinstance(value.get("allowed"), bool):
            return "allow" if value["allowed"] else "block"
        decision = str(value.get("decision") or "").lower()
        return decision if decision in {"allow", "block"} else "unknown"

    warnings: list[str] = []
    if "fill_price" in (counterfactual_result.get("scenario") or {}):
        warnings.append("Counterfactual fill_price differs; realized comparison is measured from the original decision reference price.")

    original_action = action(original)
    counterfactual_action = action(counterfactual)
    return {
        "available": True,
        "horizon": horizon,
        "return_basis": "original_decision_reference_price",
        "realized_signed_return": signed_return,
        "market_classification": outcome.get("classification"),
        "original": {"action": original_action, "interpretation": interpret_action_against_outcome(original_action, signed_return)},
        "counterfactual": {"action": counterfactual_action, "interpretation": interpret_action_against_outcome(counterfactual_action, signed_return)},
        "warnings": warnings,
        "research_only": True,
    }