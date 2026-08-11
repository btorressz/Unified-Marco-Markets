"""Deterministic event-time evaluation of immutable, code-defined heuristics."""
from __future__ import annotations

from bisect import bisect_right, bisect_left
from datetime import datetime, timedelta, timezone
from math import sqrt
from statistics import mean, pstdev
from typing import Any

from backend.compute.rules_engine import RulesEngine

HORIZONS = {"1h": 3600, "4h": 14400, "24h": 86400, "7d": 604800}
REGIME_FIELDS = ("vol_regime", "funding_regime", "shock_state")


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result).astimezone(timezone.utc)


def _sorted(rows):
    return sorted(rows or [], key=lambda row: _dt(row["ts"]))


def _latest(rows, times, decision_ts):
    pos = bisect_right(times, decision_ts) - 1
    return rows[pos] if pos >= 0 else None


def reconstruct_context(decision_ts: datetime, *, index_history=None, regime_snapshots=None,
                        funding_ticks=None, events=None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct state strictly from observations at or before decision_ts."""
    decision_ts = _dt(decision_ts)
    groups = [_sorted(x) for x in (index_history, regime_snapshots, funding_ticks, events)]
    times = [[_dt(r["ts"]) for r in rows] for rows in groups]
    index, regime, funding = (_latest(groups[i], times[i], decision_ts) for i in range(3))
    context: dict[str, Any] = {}
    if index:
        if index.get("rate_of_change") is not None: context["tariff_rate_of_change"] = index["rate_of_change"]
        if index.get("shock_score") is not None: context["shock_score"] = index["shock_score"]
    if regime:
        for field in (*REGIME_FIELDS, "tariff_index"):
            if regime.get(field) is not None: context[field] = regime[field]
    if funding and funding.get("funding_rate") is not None:
        context["funding_rate"] = funding["funding_rate"]
    # Events are patches, not inferred features. Only explicitly persisted keys qualify.
    for event in groups[3][:bisect_right(times[3], decision_ts)]:
        payload = event.get("payload") or {}
        if isinstance(payload, dict):
            for key in ("divergence_alert_active", "funding_regime_flipped", "carry_score"):
                if key in payload: context[key] = payload[key]
    return context, {key: context[key] for key in REGIME_FIELDS if key in context}


def classification_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    directional = [r for r in rows if r.get("evaluation_status") == "evaluable"
                   and r.get("primary_return") is not None and r.get("primary_return") != 0]
    tp = fp = tn = fn = 0
    for row in directional:
        actual = row["signed_primary_return"] > 0
        predicted = bool(row["fired"])
        tp += predicted and actual; fp += predicted and not actual
        tn += (not predicted) and (not actual); fn += (not predicted) and actual
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    fired = [r for r in directional if r["fired"]]
    hits = [r for r in fired if r.get("directional_hit") is True]
    accuracy = len(hits) / len(fired) if fired else None
    confidence_rows = [r for r in directional if r.get("confidence") is not None]
    brier = mean((float(r["confidence"]) - (1.0 if r["signed_primary_return"] > 0 else 0.0)) ** 2
                 for r in confidence_rows) if confidence_rows else None
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "confusion_sample_count": len(directional),
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None,
            "directional_accuracy": accuracy, "hit_rate": accuracy, "hit_count": len(hits),
            "miss_count": len(fired) - len(hits), "fired_sample_count": len(fired),
            "brier_score": brier, "calibration_status": "available" if confidence_rows else "unavailable_no_probability",
            "calibration_sample_count": len(confidence_rows)}


def normalized_signal_metrics(rows, horizon_seconds):
    eligible = sorted((r for r in rows if r.get("fired") and r.get("signed_primary_return") is not None), key=lambda r: _dt(r["decision_ts"]))
    selected, next_ts = [], None
    for row in eligible:
        ts = _dt(row["decision_ts"])
        if next_ts is None or ts >= next_ts:
            selected.append(row); next_ts = ts + timedelta(seconds=horizon_seconds)
    returns = [float(r["signed_primary_return"]) for r in selected]
    sharpe = mean(returns) / pstdev(returns) * sqrt(len(returns)) if len(returns) > 1 and pstdev(returns) else None
    equity = 1.0; peak = 1.0; max_dd = 0.0; curve = []
    for row, value in zip(selected, returns):
        equity *= 1 + value; peak = max(peak, equity); max_dd = max(max_dd, (peak - equity) / peak)
        curve.append({"ts": _dt(row["decision_ts"]).isoformat(), "equity": equity})
    return {"signal_return_sharpe": sharpe, "signal_return_max_drawdown": max_dd if returns else None,
            "risk_metric_sample_count": len(returns), "normalized_equity_curve": curve,
            "risk_metric_label": "normalized signal performance"}


def _summary(rows):
    evaluable = [r for r in rows if r.get("evaluation_status") == "evaluable"]
    fired = [r for r in evaluable if r.get("fired")]
    outcomes = [r for r in fired if r.get("primary_return") is not None]
    hits = [r for r in outcomes if r.get("directional_hit") is True]
    return {"sample_count": len(evaluable), "fired_count": len(fired),
            "hit_rate": len(hits) / len(outcomes) if outcomes else None,
            "directional_accuracy": len(hits) / len(outcomes) if outcomes else None,
            "average_raw_return": mean(r["primary_return"] for r in outcomes) if outcomes else None,
            "average_signed_return": mean(r["signed_primary_return"] for r in outcomes if r.get("signed_primary_return") is not None) if outcomes else None}


def aggregate_evaluations(rows, rule, primary_horizon):
    result = classification_metrics(rows) if rule["evaluation_type"] == "directional" else {
        "tp": None, "fp": None, "tn": None, "fn": None, "precision": None, "recall": None, "f1": None,
        "directional_accuracy": None, "hit_rate": None, "brier_score": None,
        "calibration_status": "unavailable_no_probability", "calibration_sample_count": 0}
    evaluable = [r for r in rows if r["evaluation_status"] == "evaluable"]
    fired = [r for r in evaluable if r["fired"]]
    outcomes = [r for r in fired if r.get("primary_return") is not None]
    result.update({"opportunity_count": len(rows), "evaluable_count": len(evaluable), "fired_count": len(fired),
                   "outcome_count": len(outcomes), "average_realized_return": mean(r["primary_return"] for r in outcomes) if outcomes else None,
                   "average_signed_return": mean(r["signed_primary_return"] for r in outcomes if r.get("signed_primary_return") is not None) if outcomes else None})
    result.update(normalized_signal_metrics(rows, HORIZONS[primary_horizon]) if rule["evaluation_type"] == "directional" else
                  {"signal_return_sharpe": None, "signal_return_max_drawdown": None, "risk_metric_sample_count": 0,
                   "normalized_equity_curve": [], "risk_metric_label": "normalized signal performance"})
    by_regime = {}
    for field in REGIME_FIELDS:
        values = sorted({str(r.get("regime", {}).get(field)) for r in evaluable if r.get("regime", {}).get(field) is not None})
        by_regime[field] = {value: _summary([r for r in rows if str(r.get("regime", {}).get(field)) == value]) for value in values}
    result["performance_by_regime"] = by_regime
    end = max((_dt(r["decision_ts"]) for r in rows), default=None)
    full = _summary(rows); decay = {"available": False, "full_window": full}
    if end:
        recent = [r for r in rows if _dt(r["decision_ts"]) > end - timedelta(days=30)]
        prior = [r for r in rows if end - timedelta(days=60) < _dt(r["decision_ts"]) <= end - timedelta(days=30)]
        rs, ps = _summary(recent), _summary(prior)
        decay.update({"recent_30d": rs, "prior_30d": ps, "available": bool(rs["sample_count"] and ps["sample_count"])})
        if decay["available"]:
            decay["changes"] = {"hit_rate_change": rs["hit_rate"] - ps["hit_rate"] if rs["hit_rate"] is not None and ps["hit_rate"] is not None else None,
                                "accuracy_change": rs["directional_accuracy"] - ps["directional_accuracy"] if rs["directional_accuracy"] is not None and ps["directional_accuracy"] is not None else None,
                                "signed_return_change": rs["average_signed_return"] - ps["average_signed_return"] if rs["average_signed_return"] is not None and ps["average_signed_return"] is not None else None}
    result["performance_decay"] = decay
    horizon_stats = {}
    for horizon in HORIZONS:
        hs = [dict(r, primary_return=(r.get("outcomes", {}).get(horizon) or {}).get("raw_return"),
                   signed_primary_return=(r.get("outcomes", {}).get(horizon) or {}).get("signed_return"),
                   directional_hit=(r.get("outcomes", {}).get(horizon) or {}).get("hit")) for r in rows]
        horizon_stats[horizon] = _summary(hs)
    result["outcome_by_horizon"] = horizon_stats
    return result


def evaluate_historical(bundle: dict[str, list[dict[str, Any]]], *, start_ts, end_ts, venue, market, symbol,
                        heuristic_ids=None, primary_horizon="24h", decision_interval_seconds=3600,
                        outcome_tolerance_seconds=3600):
    if primary_horizon not in HORIZONS: raise ValueError("Unsupported primary horizon")
    if decision_interval_seconds < 60: raise ValueError("decision_interval_seconds must be at least 60")
    start, end = _dt(start_ts), _dt(end_ts)
    market_rows = _sorted(bundle.get("market_ticks"))
    decisions = [r for r in market_rows if start <= _dt(r["ts"]) <= end]
    sampled, last = [], None
    for row in decisions:
        ts = _dt(row["ts"])
        if last is None or (ts-last).total_seconds() >= decision_interval_seconds: sampled.append(row); last = ts
    if not sampled: raise ValueError("No persisted historical market data found for requested validation window.")
    price_times = [_dt(r["ts"]) for r in market_rows]
    engine = RulesEngine(); selected = [r for r in engine.rules if r["active"] and (not heuristic_ids or r["id"] in heuristic_ids)]
    unknown = set(heuristic_ids or []) - {r["id"] for r in engine.rules}
    if unknown: raise ValueError(f"Unknown heuristic ID: {sorted(unknown)[0]}")
    reports, all_rows = [], []
    for rule in selected:
        rows = []
        for tick in sampled:
            ts, price = _dt(tick["ts"]), float(tick["price"])
            context, regime = reconstruct_context(ts, index_history=bundle.get("index_history"), regime_snapshots=bundle.get("regime_snapshots"), funding_ticks=bundle.get("funding_ticks"), events=bundle.get("events"))
            context.update({"venue": venue, "market": market})
            missing = [key for key in rule["required_context"] if key not in context]
            evaluable = not missing; fired = bool(rule["condition"](context)) if evaluable else False
            outcomes = {}
            for label, seconds in HORIZONS.items():
                target = ts + timedelta(seconds=seconds); pos = bisect_left(price_times, target)
                outcome = None
                if pos < len(market_rows):
                    observed = price_times[pos]; lag = (observed-target).total_seconds()
                    if lag <= outcome_tolerance_seconds:
                        future_price = float(market_rows[pos]["price"]); raw = future_price / price - 1
                        signed = raw if rule["expected_direction"] == "bullish" else -raw if rule["expected_direction"] == "bearish" else None
                        outcome = {"target_ts": target.isoformat(), "observed_ts": observed.isoformat(), "price": future_price,
                                   "raw_return": raw, "signed_return": signed, "hit": signed > 0 if signed is not None and raw != 0 else None,
                                   "lag_seconds": lag}
                outcomes[label] = outcome
            primary = outcomes[primary_horizon] or {}
            row = {"heuristic_id": rule["id"], "heuristic_version": rule["version"], "evaluation_type": rule["evaluation_type"],
                   "action_type": rule["action_type"], "expected_direction": rule["expected_direction"], "venue": venue, "market": market,
                   "symbol": symbol, "decision_ts": ts.isoformat(), "price_at_decision": price, "fired": fired, "confidence": None,
                   "expected_return": rule.get("expected_return"), "context": context, "regime": regime, "outcomes": outcomes,
                   "primary_horizon": primary_horizon, "primary_return": primary.get("raw_return"),
                   "signed_primary_return": primary.get("signed_return"), "directional_hit": primary.get("hit") if fired else None,
                   "evaluation_status": "evaluable" if evaluable else "not_evaluable", "missing_context": missing, "source": "persisted_event_time"}
            rows.append(row); all_rows.append(row)
        metrics = aggregate_evaluations(rows, rule, primary_horizon)
        missing_union = sorted({x for row in rows for x in row["missing_context"]})
        reports.append({**{k: v for k, v in rule.items() if k != "condition"}, "evaluation_status": "validated" if metrics["evaluable_count"] else "not_evaluable",
                        "missing_context": missing_union, "metrics": metrics})
    return {"mode": "historical", "data_mode": "persisted_event_time", "start_ts": start.isoformat(), "end_ts": end.isoformat(),
            "venue": venue, "market": market, "symbol": symbol, "primary_horizon": primary_horizon,
            "look_ahead_guard": {"enabled": True, "context_cutoff": "observation_ts <= decision_ts", "outcome_start": "observation_ts >= decision_ts + horizon"},
            "data_manifest": {key: len(value) for key, value in bundle.items()}, "heuristics": reports, "evaluations": all_rows,
            "warnings": [], "performance_feedback": "Research-only; no rules, weights, or execution settings were modified."}
