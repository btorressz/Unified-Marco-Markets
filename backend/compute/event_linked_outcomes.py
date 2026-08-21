"""Pure single-event derivatives and regime outcome computation."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

HORIZONS = {"1h": 3600, "4h": 14400, "24h": 86400, "7d": 604800}
REGIME_MAX_REFERENCE_AGE_SECONDS = 6 * 60 * 60


def _dt(value: Any) -> datetime | None:
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _sign(value: float | None) -> str | None:
    return None if value is None else "POSITIVE" if value > 0 else "NEGATIVE" if value < 0 else "ZERO"


def _coverage_timestamp(coverage: dict[str, Any] | None, *keys: str) -> datetime | None:
    coverage = coverage or {}
    for key in keys:
        value = _dt(coverage.get(key))
        if value is not None:
            return value
    return None


def select_event_points(rows, event_ts, *, timestamp_field, value_field, now=None,
                        reference_max_age_seconds=86400, target_lag_seconds=7200,
                        coverage: dict[str, Any] | None = None):
    """Apply the no-look-ahead scalar observation contract to injected rows.

    ``coverage`` describes the true durable series bounds and is intentionally
    separate from the selected/query rows. This prevents a bounded event-point
    query from making an older event appear to predate the underlying dataset.
    """
    event, current = _dt(event_ts), _dt(now) or datetime.now(timezone.utc)
    valid = []
    for row in rows or []:
        ts, value = _dt(row.get(timestamp_field)), _number(row.get(value_field))
        if ts is not None and value is not None:
            valid.append((ts, value, row))
    valid.sort(key=lambda item: item[0])

    query_first = valid[0][0] if valid else None
    query_latest = valid[-1][0] if valid else None
    dataset_first = _coverage_timestamp(
        coverage, "first_timestamp", "first_observation_ts", "first_provider_timestamp"
    ) or query_first
    dataset_latest = _coverage_timestamp(
        coverage, "latest_timestamp", "last_observation_ts", "latest_observation_ts",
        "last_provider_timestamp",
    ) or query_latest

    reference = next((item for item in reversed(valid) if event and item[0] <= event), None)
    reference_reason = None
    if event and dataset_first and event < dataset_first:
        reference = None
        reference_reason = "event_predates_dataset"
    elif reference and (event - reference[0]).total_seconds() > reference_max_age_seconds:
        reference = None
        reference_reason = "reference_stale"
    elif reference is None:
        reference_reason = "no_valid_pre_event_reference"

    horizons = {}
    for label, seconds in HORIZONS.items():
        target = event.timestamp() + seconds if event else None
        target_dt = datetime.fromtimestamp(target, timezone.utc) if target is not None else None
        base = {
            "target_timestamp": target_dt.isoformat() if target_dt else None,
            "selected_observation_timestamp": None,
            "lag_seconds": None,
        }
        if target_dt and target_dt > current:
            horizons[label] = {**base, "status": "not_matured", "reason": "horizon_not_matured"}
        elif reference is None:
            horizons[label] = {**base, "status": "unavailable", "reason": reference_reason}
        else:
            selected = next((item for item in valid if item[0] >= target_dt), None)
            if selected is None:
                horizons[label] = {**base, "status": "unavaile", "reason": "history_not_yet_available"}
            elif (selected[0] - target_dt).total_seconds() > target_lag_seconds:
                horizons[label] = {
                    **base,
                    "status": "unavailable",
                    "reason": "no_observation_within_target_tolerance",
                }
            else:
                horizons[label] = {
                    **base,
                    "status": "available",
                    "reason": None,
                    "selected_observation_timestamp": selected[0].isoformat(),
                    "lag_seconds": (selected[0] - target_dt).total_seconds(),
                    "value": selected[1],
                    "row": selected[2],
                }

    return {
        "reference": None if reference is None else {
            "timestamp": reference[0].isoformat(), "value": reference[1], "row": reference[2]
        },
        "horizons": horizons,
        "coverage": {
            "first_timestamp": dataset_first.isoformat() if dataset_first else None,
            "latest_timestamp": dataset_latest.isoformat() if dataset_latest else None,
            "query_first_timestamp": query_first.isoformat() if query_first else None,
            "query_latest_timestamp": query_latest.isoformat() if query_latest else None,
        },
    }


def funding_reactions(rows, event_ts, *, now=None, coverage: dict[str, Any] | None = None):
    rows = [
        r for r in (rows or [])
        if r.get("contract_version") == 1
        and r.get("rate_kind") == "realized"
        and r.get("provider_timestamp")
    ]
    selected = select_event_points(
        rows,
        event_ts,
        timestamp_field="provider_timestamp",
        value_field="normalized_funding_rate",
        now=now,
        coverage=coverage,
    )
    ref = selected["reference"]
    for result in selected["horizons"].values():
        result.update({"research_only": True, "execution_eligible": False})
        if not ref or result["status"] != "available":
            continue
        row, rr, value = result.pop("row"), ref["row"], result.pop("value")
        delta = value - ref["value"]
        annualized = _number(row.get("annualized_rate"))
        reference_annualized = _number(rr.get("annualized_rate"))
        result.update({
            "reference_timestamp": ref["timestamp"],
            "reference_normalized_rate": ref["value"],
            "reference_rate_bps": ref["value"] * 10000,
            "reference_annualized_rate": reference_annualized,
            "normalized_rate": value,
            "rate_bps": value * 10000,
            "annualized_rate": annualized,
            "delta_rate": delta,
            "delta_bps": delta * 10000,
            "annualized_delta": (
                annualized - reference_annualized
                if annualized is not None and reference_annualized is not None else None
            ),
            "reference_sign": _sign(ref["value"]),
            "current_sign": _sign(value),
            "sign_flip": ref["value"] * value < 0,
            "direction": "INCREASED" if delta > 0 else "DECREASED" if delta < 0 else "UNCHANGED",
            **{
                key: row.get(key)
                for key in (
                    "provider", "venue", "market", "source_id", "contract_version",
                    "rate_kind", "interval_seconds", "timestamp_semantics", "sign_convention",
                )
            },
        })
    return selected


def basis_reactions(rows, event_ts, *, now=None, coverage: dict[str, Any] | None = None):
    selected = select_event_points(
        rows,
        event_ts,
        timestamp_field="observed_at",
        value_field="basis_bps",
        now=now,
        coverage=coverage,
    )
    ref = selected["reference"]
    for result in selected["horizons"].values():
        result.update({"research_only": True, "execution_eligible": False})
        if not ref or result["status"] != "available":
            continue
        row, value = result.pop("row"), result.pop("value")
        result.update({
            "reference_timestamp": ref["timestamp"],
            "reference_basis_bps": ref["value"],
            "basis_bps": value,
            "delta_bps": value - ref["value"],
            "reference_sign": _sign(ref["value"]),
            "basis_sign": _sign(value),
            "sign_flip": ref["value"] * value < 0,
            "spot_source": row.get("spot_source"),
            "venue": row.get("venue"),
            "market": row.get("market"),
            "reference_lineage": ref["row"].get("lineage"),
            "selected_lineage": row.get("lineage"),
        })
    return selected


def regime_path(rows, event_ts, *, now=None, target_lag_seconds=7200):
    selected = select_event_points(
        rows,
        event_ts,
        timestamp_field="ts",
        value_field="tariff_index",
        now=now,
        reference_max_age_seconds=REGIME_MAX_REFERENCE_AGE_SECONDS,
        target_lag_seconds=target_lag_seconds,
    )
    ref = selected["reference"]
    fields = ("shock_state", "funding_regime", "vol_regime", "tariff_index")
    reference = None if not ref else {
        "status": "available",
        "snapshot_timestamp": ref["timestamp"],
        **{key: ref["row"].get(key) for key in fields},
    }
    for result in selected["horizons"].values():
        if result["status"] == "available":
            row = result.pop("row")
            result.pop("value")
            result.update({
                "snapshot_timestamp": result["selected_observation_timestamp"],
                **{key: row.get(key) for key in fields},
                "changed_fields": [
                    key for key in fields if row.get(key) != ref["row"].get(key)
                ],
                "semantics": "observed after event",
            })
    return {
        "reference": reference,
        "horizons": selected["horizons"],
        "coverage": {
            **selected.get("coverage", {}),
            "max_reference_age_seconds": REGIME_MAX_REFERENCE_AGE_SECONDS,
        },
    }


def event_lag_bucket(seconds):
    if 0 <= seconds <= 3600:
        return "0_to_1h"
    if seconds <= 14400:
        return "1h_to_4h"
    if seconds <= 86400:
        return "4h_to_24h"
    return "24h_to_7d"
