from __future__ import annotations

from typing import Any
from fastapi import APIRouter
from backend.core.state_keys import GDELT_LATEST, STABLECOIN_HEALTH, STABLECOIN_HEALTH_LEGACY, WITS_AGGREGATE
from backend.core.state_store import StateStore
from backend.compute.geopolitical_risk import compute_geopolitical_index
from backend.compute.portfolio_protection import protection_protocol

router = APIRouter(prefix="/api/protection", tags=["protection"])
_store = StateStore()


def _geo():
    try:
        state = {
            "gdelt": _store.get_snapshot(GDELT_LATEST),
            "wits": _store.get_snapshot(WITS_AGGREGATE),
            "stablecoin": _store.get_snapshot(STABLECOIN_HEALTH) or _store.get_snapshot(STABLECOIN_HEALTH_LEGACY),
        }
    except Exception:
        state = {"provider_error": True}
    return compute_geopolitical_index(state)


@router.get("/status")
def protection_status():
    geo = _geo()
    return protection_protocol({"geopolitical_index": geo, "data_quality": geo.get("data_quality", "degraded")})


@router.post("/preview")
def protection_preview(body: dict[str, Any] | None = None):
    body = body or {}
    return protection_protocol({**body, "geopolitical_index": body.get("geopolitical_index") or _geo()})
