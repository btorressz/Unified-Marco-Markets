import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from backend.compute.capital_allocator import allocate, execution_preview
from backend.core.state_keys import (
    PREDICTION_LATEST,
    PREDICTION_LATEST_LEGACY,
    PRICE_INTEGRITY,
    PRICE_INTEGRITY_LEGACY_LATEST,
    STABLECOIN_HEALTH,
    STABLECOIN_HEALTH_LEGACY,
)
from backend.core.state_store import StateStore
from backend.core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/allocation", tags=["allocation"])

_store = StateStore()
_bus = EventBus()

_CACHE_KEY = "desk:allocation:latest"
_CACHE_TTL = 60


def _stable_assets(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    assets = snapshot.get("assets")
    if isinstance(assets, dict):
        return assets
    return {key: value for key, value in snapshot.items() if isinstance(value, dict) and "depeg_bps" in value}


def _build_state_from_redis() -> dict[str, Any]:
    state: dict[str, Any] = {}

    idx = _store.get_snapshot("desk:index:latest") or _store.get_snapshot("index:latest")
    if idx:
        state["tariff_index"] = idx.get("value", 30.0)
        state["tariff_shock"] = min(idx.get("value", 30.0) / 100.0, 1.0)

    shock = _store.get_snapshot("desk:shock:latest") or _store.get_snapshot("shock:latest")
    if shock:
        state["shock_score"] = shock.get("shock_score", 0.0)

    for key in ["vol_regime", "annualized_vol"]:
        snap = _store.get_snapshot("desk:vol_regime:latest") or _store.get_snapshot("vol_regime:latest")
        if snap:
            state["vol_regime"] = snap.get("regime", "normal")
            break

    pred = _store.get_snapshot(PREDICTION_LATEST) or _store.get_snapshot(PREDICTION_LATEST_LEGACY)
    if pred:
        state["predictor_confidence"] = pred.get("confidence", 0.5)
        state["predictor_prob"] = pred.get("probability", pred.get("probability_up", 0.5))

    arb = _store.get_snapshot("funding_arb:latest")
    if arb and arb.get("available") is True and arb.get("spread_bps") is not None:
        state["funding_arb_score"] = abs(arb["spread_bps"]) / 100.0

    basis = _store.get_snapshot("basis:latest")
    if basis and basis.get("available") is True and basis.get("feasibility_score") is not None:
        state["basis_opportunity"] = basis["feasibility_score"]

    stable = _store.get_snapshot(STABLECOIN_HEALTH) or _store.get_snapshot(STABLECOIN_HEALTH_LEGACY)
    assets = _stable_assets(stable)
    if assets:
        avg_health = sum(
            1.0 - min(abs(a.get("depeg_bps", 0)) / 100.0, 1.0)
            for a in assets.values()
        ) / len(assets)
        state["stable_health"] = avg_health

    eqi = _store.get_snapshot("execution:metrics:latest")
    if eqi:
        state["exec_quality"] = eqi.get("eqi_score", 0.8)

    integrity = _store.get_snapshot(PRICE_INTEGRITY) or _store.get_snapshot(PRICE_INTEGRITY_LEGACY_LATEST)
    if integrity:
        state["price_integrity"] = integrity.get("status", "UNKNOWN")

    portfolio = _store.get_snapshot("portfolio:latest")
    if portfolio:
        state["portfolio_weights"] = portfolio.get("allocation", {})

    return state


@router.get("/latest")
def get_latest_allocation():
    cached = _store.get_snapshot(_CACHE_KEY)
    if cached:
        return cached

    state = _build_state_from_redis()
    result = allocate(state)

    _store.set_snapshot(_CACHE_KEY, result, ttl=_CACHE_TTL)
    return result


@router.post("/rebalance-preview")
def rebalance_preview(body: dict[str, Any] | None = None):
    body = body or {}

    state = _build_state_from_redis()
    state.update(body)

    result = allocate(state)
    result["preview"] = True
    result["preview_note"] = "Proposal only — no auto-trade executed"

    _bus.emit(
        EventType.CAPITAL_ALLOCATION_UPDATE,
        source="allocation_routes",
        payload={
            "weights": result.get("weights", {}),
            "confidence": result.get("confidence", 0.0),
            "preview": True,
        },
    )

    return result


@router.post("/execution-preview")
def allocation_execution_preview(body: dict[str, Any] | None = None):
    body = body or {}
    try:
        state = _build_state_from_redis()
        allocation = allocate(state)
        portfolio = _store.get_snapshot("portfolio:latest") or {}
        return execution_preview(body, allocation=allocation, portfolio=portfolio)
    except Exception as exc:
        logger.warning("Allocation execution preview degraded: %s", exc, exc_info=True)
        return {"preview": True, "paper_mode_only": True, "auto_trade": False, "allowed_size": 0.0, "suggested_size": 0.0, "blocked_reason": "preview unavailable", "warnings": [str(exc)], "reasoning": ["fail-open degraded preview"], "ts": datetime.now(timezone.utc).isoformat()}
