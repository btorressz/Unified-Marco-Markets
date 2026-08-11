import logging
import math
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "tariff_index",
    "tariff_delta",
    "shock_score",
    "shock_abs",
    "funding_skew",
    "basis_spread",
    "vol_regime_encoded",
    "stable_health",
    "stable_flow",
    "divergence_score",
    "orderbook_imbalance",
    "liquidity_score",
    "slippage_score",
    "exec_quality",
    "predictor_conf",
]
FEATURE_SCHEMA_ID = "macro_signal_features"
FEATURE_SCHEMA_VERSION = 1
feature_schema_id = FEATURE_SCHEMA_ID
feature_schema_version = FEATURE_SCHEMA_VERSION

_VOL_REGIME_ENCODING = {
    "low": 0.0,
    "normal": 0.25,
    "high": 0.75,
    "extreme": 1.0,
    "low_volatility": 0.0,
    "normal_volatility": 0.25,
    "high_volatility": 0.75,
    "shock_regime": 1.0,
    "liquidity_crunch": 1.0,
}


def _safe_float(v: Any, default: float = 0.0, lo: float = -1e9, hi: float = 1e9) -> float:
    try:
        result = float(v)
        if math.isnan(result) or math.isinf(result):
            return default
        return max(lo, min(hi, result))
    except (TypeError, ValueError):
        return default


def build_features(state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state or {}

    tariff_index = _safe_float(state.get("tariff_index", 30.0), 30.0, 0.0, 100.0)
    tariff_delta = _safe_float(state.get("tariff_delta", 0.0), 0.0, -50.0, 50.0)
    shock_score = _safe_float(state.get("shock_score", 0.0), 0.0, -5.0, 5.0)
    shock_abs = abs(shock_score)
    funding_skew = _safe_float(state.get("funding_skew", 0.0), 0.0, -0.1, 0.1)
    basis_spread = _safe_float(state.get("basis_spread", 0.0), 0.0, -0.5, 0.5)
    vol_regime_raw = str(state.get("vol_regime", "normal"))
    vol_regime_encoded = _VOL_REGIME_ENCODING.get(vol_regime_raw.lower(), 0.25)
    stable_health = _safe_float(state.get("stable_health", 1.0), 1.0, 0.0, 1.0)
    stable_flow = _safe_float(state.get("stable_flow", 0.0), 0.0, -1.0, 1.0)
    divergence_score = _safe_float(state.get("divergence_score", 0.0), 0.0, 0.0, 1.0)
    orderbook_imbalance = _safe_float(state.get("orderbook_imbalance", 0.0), 0.0, -1.0, 1.0)
    liquidity_score = _safe_float(state.get("liquidity_score", 0.8), 0.8, 0.0, 1.0)
    slippage_score = _safe_float(state.get("slippage_score", 0.1), 0.1, 0.0, 1.0)
    exec_quality = _safe_float(state.get("exec_quality", 0.8), 0.8, 0.0, 1.0)
    predictor_conf = _safe_float(state.get("predictor_confidence", 0.5), 0.5, 0.0, 1.0)

    features = {
        "tariff_index": round(tariff_index, 4),
        "tariff_delta": round(tariff_delta, 4),
        "shock_score": round(shock_score, 4),
        "shock_abs": round(shock_abs, 4),
        "funding_skew": round(funding_skew, 6),
        "basis_spread": round(basis_spread, 6),
        "vol_regime_encoded": round(vol_regime_encoded, 4),
        "stable_health": round(stable_health, 4),
        "stable_flow": round(stable_flow, 4),
        "divergence_score": round(divergence_score, 4),
        "orderbook_imbalance": round(orderbook_imbalance, 4),
        "liquidity_score": round(liquidity_score, 4),
        "slippage_score": round(slippage_score, 4),
        "exec_quality": round(exec_quality, 4),
        "predictor_conf": round(predictor_conf, 4),
    }

    # Status augments (rather than replaces) the ingestion lineage carried by
    # snapshots.  A computed field is derived; supplied values are observed;
    # invalid supplied values are fallbacks; absent inputs are explicit defaults.
    source_keys = {"predictor_conf": "predictor_confidence", "vol_regime_encoded": "vol_regime"}
    derived = {"shock_abs"}
    provenance = {}
    for name, value in features.items():
        source = source_keys.get(name, name)
        if name in derived:
            status, reason = "derived", "derived_from_shock_score"
        elif source not in state:
            status, reason = "default", "source_unavailable"
        else:
            raw = state.get(source)
            try:
                valid = raw is not None and (source == "vol_regime" or math.isfinite(float(raw)))
            except (TypeError, ValueError):
                valid = False
            status, reason = ("observed", "source_observation") if valid else ("fallback", "invalid_source_value")
        provenance[name] = {"value": value, "status": status, "reason": reason}
    counts = {s: sum(p["status"] == s for p in provenance.values()) for s in ("observed", "derived", "fallback", "default")}

    quality_checks = {
        "all_present": len(features) == len(FEATURE_NAMES),
        "no_nulls": all(v is not None for v in features.values()),
        "feature_count": len(features),
        **{f"{key}_feature_count": value for key, value in counts.items()},
        "default_feature_ratio": counts["default"] / len(FEATURE_NAMES),
    }

    return {
        "features": features,
        "feature_names": FEATURE_NAMES,
        "feature_schema_id": FEATURE_SCHEMA_ID,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_provenance": provenance,
        "quality": quality_checks,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def features_to_vector(features: dict[str, float]) -> list[float]:
    return [features.get(name, 0.0) for name in FEATURE_NAMES]
