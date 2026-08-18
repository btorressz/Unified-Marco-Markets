"""Descriptive statistics for the existing decision performance lab.

This module is research-only and additive. It does not change decision outcomes,
cohort definitions, execution behavior, or persisted state. It enriches the
existing performance summary with distribution, coverage, sample-size, and
historical-context governance metadata derived from immutable outcome results.
"""
from __future__ import annotations

from statistics import median, stdev
from typing import Any, Callable

from backend.compute.context_governance import governed_decision_context, governance_contract
from backend.compute.decision_outcomes import (
    HORIZONS,
    _component_label,
    _metric_summary,
)

VERY_LOW_SAMPLE_THRESHOLD = 5
LOW_SAMPLE_THRESHOLD = 20
ESTABLISHED_SAMPLE_THRESHOLD = 50


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _sample_quality(evaluated_count: int) -> tuple[str, str | None]:
    if evaluated_count <= 0:
        return "unavailable", "NO_EVALUATED_OUTCOMES"
    if evaluated_count < VERY_LOW_SAMPLE_THRESHOLD:
        return "very_low", "VERY_LOW_SAMPLE"
    if evaluated_count < LOW_SAMPLE_THRESHOLD:
        return "low", "LOW_SAMPLE"
    if evaluated_count < ESTABLISHED_SAMPLE_THRESHOLD:
        return "moderate", None
    return "established", None


def metric_statistics(items: list[dict[str, Any]], horizon: str) -> dict[str, Any]:
    """Return bounded descriptive statistics for one existing metric cohort."""
    values: list[float] = []
    for item in items:
        outcome = (item.get("outcomes") or {}).get(horizon)
        if not isinstance(outcome, dict) or outcome.get("signed_return") is None:
            continue
        try:
            value = float(outcome["signed_return"])
        except (TypeError, ValueError):
            continue
        if value == value and abs(value) != float("inf"):
            values.append(value)

    sample_count = len(items)
    evaluated_count = len(values)
    missing_count = max(0, sample_count - evaluated_count)
    quality, warning = _sample_quality(evaluated_count)
    p25 = _quantile(values, 0.25)
    p75 = _quantile(values, 0.75)

    return {
        "missing_count": missing_count,
        "missing_rate": missing_count / sample_count if sample_count else None,
        "coverage_rate": evaluated_count / sample_count if sample_count else None,
        "median_signed_return": median(values) if values else None,
        "signed_return_p25": p25,
        "signed_return_p75": p75,
        "signed_return_iqr": (p75 - p25) if p25 is not None and p75 is not None else None,
        "signed_return_stddev": stdev(values) if len(values) >= 2 else None,
        "signed_return_min": min(values) if values else None,
        "signed_return_max": max(values) if values else None,
        "low_sample": evaluated_count < LOW_SAMPLE_THRESHOLD,
        "sample_quality": quality,
        "sample_warning": warning,
    }


def _group_results(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    key_fn: Callable[[dict[str, Any], dict[str, Any]], Any],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record, result in pairs:
        groups.setdefault(str(key_fn(record, result)), []).append(result)
    return groups


def _merge_group_statistics(
    target: dict[str, Any] | None,
    groups: dict[str, list[dict[str, Any]]],
    horizon: str,
) -> None:
    if not isinstance(target, dict):
        return
    for key, items in groups.items():
        metric = target.get(key)
        if isinstance(metric, dict):
            metric.update(metric_statistics(items, horizon))


def _replace_governed_groups(
    target: dict[str, Any] | None,
    groups: dict[str, list[dict[str, Any]]],
    horizon: str,
) -> dict[str, Any]:
    """Replace only cohort/regime groupings after freshness is applied."""
    rebuilt: dict[str, Any] = {}
    for key, items in sorted(groups.items()):
        metric = _metric_summary(items, horizon)
        metric.update(metric_statistics(items, horizon))
        rebuilt[key] = metric
    if isinstance(target, dict):
        target.clear()
        target.update(rebuilt)
        return target
    return rebuilt


def enrich_performance_summary(
    summary: dict[str, Any],
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    primary_horizon: str,
    context_history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add descriptive statistics and governed historical cohort reconstruction."""
    if primary_horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {primary_horizon}")

    results = [result for _, result in pairs]
    horizons = summary.get("horizons") or {}
    for horizon in HORIZONS:
        metric = horizons.get(horizon)
        if isinstance(metric, dict):
            metric.update(metric_statistics(results, horizon))

    context_history = context_history or {}
    contexts = {
        str(record.get("id") or ""): governed_decision_context(record, context_history)
        for record, _ in pairs
    }

    market = _group_results(pairs, lambda record, result: record.get("market") or "unknown")
    venue = _group_results(pairs, lambda record, result: record.get("venue") or "unknown")
    decision_type = _group_results(pairs, lambda record, result: record.get("decision_type") or "unknown")
    heuristic = _group_results(pairs, lambda record, result: _component_label(record, "heuristic"))
    model = _group_results(pairs, lambda record, result: _component_label(record, "ml"))

    def context_groups(field: str) -> dict[str, list[dict[str, Any]]]:
        return _group_results(
            pairs,
            lambda record, result: contexts.get(str(record.get("id") or ""), {}).get(field, "unavailable"),
        )

    _merge_group_statistics(summary.get("performance_by_market"), market, primary_horizon)
    _merge_group_statistics(summary.get("performance_by_venue"), venue, primary_horizon)
    _merge_group_statistics(summary.get("performance_by_decision_type"), decision_type, primary_horizon)
    _merge_group_statistics(summary.get("performance_by_heuristic_version"), heuristic, primary_horizon)
    _merge_group_statistics(summary.get("performance_by_model_version"), model, primary_horizon)

    regimes = summary.setdefault("performance_by_regime", {})
    vol = _replace_governed_groups(regimes.get("vol_regime"), context_groups("vol_regime"), primary_horizon)
    regimes["vol_regime"] = vol
    regimes["funding_regime"] = _replace_governed_groups(regimes.get("funding_regime"), context_groups("funding_regime"), primary_horizon)
    regimes["shock_state"] = _replace_governed_groups(regimes.get("shock_state"), context_groups("shock_state"), primary_horizon)
    summary["performance_by_vol_regime"] = vol
    summary["performance_by_regime_signature"] = _replace_governed_groups(
        summary.get("performance_by_regime_signature"), context_groups("regime_signature"), primary_horizon
    )

    cohorts = summary.setdefault("performance_by_cohort", {})
    cohorts["tariff_escalation"] = _replace_governed_groups(
        cohorts.get("tariff_escalation"), context_groups("tariff_escalation"), primary_horizon
    )
    cohorts["stablecoin_health"] = _replace_governed_groups(
        cohorts.get("stablecoin_health"), context_groups("stablecoin_health"), primary_horizon
    )
    cohorts["liquidity_state"] = _replace_governed_groups(
        cohorts.get("liquidity_state"), context_groups("liquidity_state"), primary_horizon
    )

    context_fields = (
        "vol_regime", "funding_regime", "shock_state", "regime_signature",
        "tariff_escalation", "stablecoin_health", "liquidity_state",
    )
    available_counts: dict[str, int] = {}
    stale_counts: dict[str, int] = {}
    unavailable_counts: dict[str, int] = {}
    recorded_counts: dict[str, int] = {}
    for field in context_fields:
        values = [context.get(field, "unavailable") for context in contexts.values()]
        governance = [
            (context.get("context_governance") or {}).get(field) or {}
            for context in contexts.values()
        ]
        available_counts[field] = sum(value not in {"unavailable", "unavailable_stale"} for value in values)
        stale_counts[field] = sum(value == "unavailable_stale" for value in values)
        unavailable_counts[field] = sum(value == "unavailable" for value in values)
        recorded_counts[field] = sum(item.get("origin") == "immutable_decision" for item in governance)

    coverage = summary.setdefault("context_coverage", {})
    coverage.update({
        "decision_count": len(pairs),
        "available_counts": available_counts,
        "stale_counts": stale_counts,
        "unavailable_counts": unavailable_counts,
        "recorded_decision_counts": recorded_counts,
        "source_errors": dict(context_history.get("errors") or {}),
        "truncated": dict(context_history.get("truncated") or {}),
        "historical_context_available": bool(context_history.get("available", False)),
    })

    summary["statistics_contract"] = {
        "descriptive_only": True,
        "significance_claims": False,
        "very_low_sample_threshold": VERY_LOW_SAMPLE_THRESHOLD,
        "low_sample_threshold": LOW_SAMPLE_THRESHOLD,
        "established_sample_threshold": ESTABLISHED_SAMPLE_THRESHOLD,
        "quantile_method": "linear interpolation over ordered signed returns",
        "dispersion": "sample standard deviation; unavailable when n < 2",
        "missingness": "sample_count minus outcomes available at the selected horizon",
    }
    summary["cohort_governance"] = governance_contract()
    summary["interpretation"] = (
        str(summary.get("interpretation") or "")
        + " Persisted fallback context must also satisfy versioned maximum-age rules; stale observations are labeled unavailable_stale and excluded from named cohorts."
    ).strip()
    return summary
