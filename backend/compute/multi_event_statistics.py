"""Pure, deterministic descriptive statistics for bounded event samples."""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable

STATISTICS_CONTRACT_VERSION = "multi_event_stats_v1"
OVERLAP_POLICY_VERSION = "same_series_nonoverlap_v1"
WINSORIZATION_POLICY_VERSION = "quantile_2_5_97_5_v1"
BOOTSTRAP_METHOD_VERSION = "percentile_bootstrap_v1"
BOOTSTRAP_SEED = 42
BOOTSTRAP_ITERATIONS = 2000
BOOTSTRAP_MIN_N = 5
MISSING_REASONS = (
    "event_predates_dataset", "no_valid_pre_event_reference", "reference_stale",
    "horizon_not_matured", "history_not_yet_available",
    "no_observation_within_target_tolerance", "contract_unverified",
    "overlap_excluded", "malformed_observation", "insufficient_coverage",
    "other_unavailable",
)


def _finite(values: Iterable[Any]) -> list[float]:
    result = []
    for value in values:
        try: value = float(value)
        except (TypeError, ValueError): continue
        if math.isfinite(value): result.append(value)
    return result


def quantile(values: Iterable[Any], probability: float) -> float | None:
    """Linear (R-7/Python inclusive) quantile, independent of numpy."""
    data = sorted(_finite(values))
    if not data: return None
    position = (len(data) - 1) * probability
    lower, fraction = math.floor(position), position - math.floor(position)
    return data[lower] if lower == len(data)-1 else data[lower] + fraction * (data[lower+1]-data[lower])


def sample_quality(n: int) -> str:
    if n <= 0: return "UNAVAILABLE"
    if n < 5: return "VERY_LOW_SAMPLE"
    if n < 20: return "LOW_SAMPLE"
    if n < 50: return "MODERATE_SAMPLE"
    return "ESTABLISHED_SAMPLE"


def bootstrap_interval(values, *, seed=BOOTSTRAP_SEED, iterations=BOOTSTRAP_ITERATIONS,
                       statistic="median", confidence_level=.95) -> dict[str, Any]:
    data = _finite(values)
    if len(data) < BOOTSTRAP_MIN_N:
        return {"available": False, "reason": "very_low_sample", "method": BOOTSTRAP_METHOD_VERSION,
                "descriptive": True, "n": len(data)}
    fn = statistics.median if statistic == "median" else statistics.mean
    rng = random.Random(seed)
    estimates = [fn(rng.choices(data, k=len(data))) for _ in range(iterations)]
    alpha = (1-confidence_level)/2
    return {"available": True, "estimate": fn(data), "ci_low": quantile(estimates, alpha),
            "ci_high": quantile(estimates, 1-alpha), "confidence_level": confidence_level,
            "iterations": iterations, "seed": seed, "method": BOOTSTRAP_METHOD_VERSION,
            "label": "bootstrap interval for descriptive sample statistic", "descriptive": True}


def descriptive_statistics(values, *, neutral_band=0.0) -> dict[str, Any]:
    data = _finite(values); n = len(data)
    if not data:
        return {"n": 0, "sample_quality": sample_quality(0), "available": False,
                "bootstrap": bootstrap_interval([])}
    p25, p75 = quantile(data, .25), quantile(data, .75)
    low, high = quantile(data, .025), quantile(data, .975)
    winsorized = [min(high, max(low, x)) for x in data]
    positive = sum(x > neutral_band for x in data); negative = sum(x < -neutral_band for x in data)
    flat = n-positive-negative
    return {"n": n, "available": True, "sample_quality": sample_quality(n),
            "mean": statistics.mean(data), "median": statistics.median(data), "p25": p25,
            "p75": p75, "iqr": p75-p25, "sample_stddev": statistics.stdev(data) if n > 1 else None,
            "min": min(data), "max": max(data), "positive_count": positive,
            "negative_count": negative, "flat_count": flat, "positive_rate": positive/n,
            "negative_rate": negative/n, "flat_rate": flat/n,
            "winsorized": {"policy": WINSORIZATION_POLICY_VERSION, "lower_bound": low,
                "upper_bound": high, "winsorized_mean": statistics.mean(winsorized),
                "winsorized_stddev": statistics.stdev(winsorized) if n > 1 else None},
            "bootstrap": bootstrap_interval(data)}


def coverage_summary(observations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(observations); reasons = Counter()
    for row in rows:
        if row.get("reason"): reasons[row["reason"] if row["reason"] in MISSING_REASONS else "other_unavailable"] += 1
    candidate = len(rows); not_matured = reasons["horizon_not_matured"]
    overlap = reasons["overlap_excluded"]
    observed = sum(row.get("status") == "available" for row in rows)
    matured = candidate-not_matured
    denominator = matured-overlap
    missing = max(0, denominator-observed)
    return {"candidate_n": candidate, "matured_n": matured, "observed_n": observed,
            "not_matured_n": not_matured, "missing_n": missing, "overlap_excluded_n": overlap,
            "coverage_denominator_n": denominator, "coverage_rate": observed/denominator if denominator else None,
            "missing_reason_counts": {reason: reasons.get(reason, 0) for reason in MISSING_REASONS}}


def filter_overlaps(events, *, horizon_seconds: int, timestamp_key="event_timestamp", id_key="event_id"):
    """First chronological event wins; touching windows do not overlap."""
    def stamp(row):
        value = row[timestamp_key]
        value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    accepted, excluded, previous_end = [], [], None
    for row in sorted(events, key=lambda x: (stamp(x), str(x.get(id_key, "")))):
        ts = stamp(row)
        if previous_end is not None and ts.timestamp() < previous_end: excluded.append(str(row.get(id_key))); continue
        accepted.append(row); previous_end = ts.timestamp()+horizon_seconds
    return {"policy": OVERLAP_POLICY_VERSION, "candidate_event_count": len(accepted)+len(excluded),
            "included_event_count": len(accepted), "overlap_excluded_count": len(excluded),
            "overlap_excluded_event_ids": excluded, "included": accepted}


def transition_matrix(pairs: Iterable[tuple[Any, Any]]) -> dict[str, Any]:
    valid = [(str(a), str(b)) for a, b in pairs if a is not None and b is not None]
    counts = Counter(valid); origins = Counter(a for a, _ in valid); n = len(valid)
    cells = [{"from": a, "to": b, "count": count, "rate": count/origins[a]}
             for (a, b), count in sorted(counts.items())]
    changed = sum(a != b for a, b in valid)
    return {"transition_observed_n": n, "cells": cells, "changed_count": changed,
            "unchanged_count": n-changed, "changed_rate": changed/n if n else None}


def sample_hash(*, event_ids, filters, horizons, overlap_policy=OVERLAP_POLICY_VERSION) -> str:
    payload = {"contract_version": STATISTICS_CONTRACT_VERSION, "event_ids": list(event_ids),
               "filters": filters, "horizons": horizons, "overlap_policy": overlap_policy}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
