import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from backend.compute.vol_regime_engine import classify_regime, get_recommendations
from backend.core.state_keys import STABLECOIN_HEALTH, STABLECOIN_HEALTH_LEGACY
from backend.core.state_store import StateStore
from backend.core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/volatility", tags=["volatility"])

_store = StateStore()
_bus = EventBus()

_REGIME_KEY = "desk:vol_regime:latest"
_REGIME_TTL = 60
_PREV_REGIME: str | None = None


def _stable_assets(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    assets = snapshot.get("assets")
    if isinstance(assets, dict):
        return assets
    return {key: value for key, value in snapshot.items() if isinstance(value, dict) and "depeg_bps" in value}


def _collect_vol_state() -> dict[str, Any]:
    state: dict[str, Any] = {}

    idx = _store.get_snapshot("desk:index:latest") or _store.get_snapshot("index:latest")
    if idx:
        state["tariff_index"] = idx.get("value", 30.0)

    shock = _store.get_snapshot("desk:shock:latest") or _store.get_snapshot("shock:latest")
    if shock:
        state["shock_score"] = shock.get("shock_score", 0.0)

    for source in ["pyth", "kraken", "coingecko"]:
        snap = _store.get_snapshot(f"price:{source}:SOL_USD")
        if snap and "vol_annualized" in snap:
            state["annualized_vol"] = snap["vol_annualized"]
            break
    if "annualized_vol" not in state:
        state["annualized_vol"] = 0.45

    stable = _store.get_snapshot(STABLECOIN_HEALTH) or _store.get_snapshot(STABLECOIN_HEALTH_LEGACY)
    assets = _stable_assets(stable)
    if assets:
        state["stable_health"] = sum(
            1.0 - min(abs(a.get("depeg_bps", 0)) / 100.0, 1.0)
            for a in assets.values()
        ) / len(assets)

    ms = _store.get_snapshot("microstructure:latest")
    if ms:
        state["orderbook_depth_score"] = max(0.0, 1.0 - abs(ms.get("imbalance", 0.0)))
        state["funding_skew"] = ms.get("funding_rate", 0.0)

    eqi = _store.get_snapshot("execution:metrics:latest")
    if eqi:
        state["exec_quality"] = eqi.get("eqi_score", 0.8)

    div = _store.get_snapshot("divergence:latest")
    if div:
        alerts = div.get("alerts", [])
        state["divergence_score"] = min(len(alerts) / 5.0, 1.0)

    return state


@router.get("/regime")
def get_vol_regime():
    global _PREV_REGIME

    cached = _store.get_snapshot(_REGIME_KEY)
    if cached:
        return cached

    state = _collect_vol_state()
    result = classify_regime(state)

    _store.set_snapshot(_REGIME_KEY, result, ttl=_REGIME_TTL)

    new_regime = result.get("regime", "normal_volatility")
    if _PREV_REGIME is not None and _PREV_REGIME != new_regime:
        _bus.emit(
            EventType.VOL_REGIME_CHANGED,
            source="volatility_routes",
            payload={
                "previous": _PREV_REGIME,
                "current": new_regime,
                "confidence": result.get("confidence"),
            },
        )
    _PREV_REGIME = new_regime

    return result


@router.get("/recommendations")
def get_vol_recommendations():
    cached = _store.get_snapshot(_REGIME_KEY)
    if cached:
        regime = cached.get("regime", "normal_volatility")
        confidence = cached.get("confidence", 0.5)
    else:
        state = _collect_vol_state()
        regime_result = classify_regime(state)
        regime = regime_result.get("regime", "normal_volatility")
        confidence = regime_result.get("confidence", 0.5)
        _store.set_snapshot(_REGIME_KEY, regime_result, ttl=_REGIME_TTL)

    return get_recommendations(regime, confidence)
