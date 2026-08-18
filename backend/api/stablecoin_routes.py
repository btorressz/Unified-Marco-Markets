import logging
import math
from datetime import datetime, timezone
from fastapi import APIRouter, Query

from backend.core.state_keys import (
    STABLECOIN_HEALTH,
    STABLECOIN_HEALTH_LEGACY,
    price_snapshot_candidates,
)
from backend.core.state_store import StateStore
from backend.compute.stablecoin_health import StablecoinHealthMonitor
from backend.ingest.quality import age_seconds, observation_quality

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stablecoins", tags=["stablecoins"])

_monitor = StablecoinHealthMonitor()
_store = StateStore()
_STABLE_PRICE_VENUES = ("pyth", "kraken")


def _valid_price(value) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def _read_stable_observation(symbol: str) -> dict:
    pair = f"{symbol}/USD"
    for venue in _STABLE_PRICE_VENUES:
        for key in price_snapshot_candidates(venue, pair):
            snap = _store.get_snapshot(key)
            if not isinstance(snap, dict):
                continue
            price = _valid_price(snap.get("price"))
            if price is None:
                continue
            as_of = snap.get("ts") or snap.get("as_of")
            quality = observation_quality(
                source=venue,
                source_id=f"{venue}_stablecoin_snapshot",
                available=True,
                authoritative=venue == "pyth",
                execution_eligible=False,
                synthetic=False,
                degraded=False,
                as_of=as_of,
                transformation="stablecoin_price_snapshot_read",
                transformation_version=1,
            )
            return {
                "symbol": symbol,
                "available": True,
                "price": price,
                "source": venue,
                "source_key": key,
                "as_of": as_of,
                "age_seconds": age_seconds(as_of),
                "quality": quality,
            }

    return {
        "symbol": symbol,
        "available": False,
        "price": None,
        "source": "unavailable",
        "source_key": None,
        "as_of": None,
        "age_seconds": None,
        "status": "unavailable",
        "quality": observation_quality(
            source="unavailable",
            source_id="stablecoin_price_unavailable",
            available=False,
            authoritative=False,
            execution_eligible=False,
            synthetic=False,
            degraded=True,
            as_of=None,
            transformation="stablecoin_price_snapshot_read",
            transformation_version=1,
        ),
    }


def _get_stable_observations() -> dict[str, dict]:
    return {symbol: _read_stable_observation(symbol) for symbol in StablecoinHealthMonitor.STABLES}


def _compute_observed_health(observations: dict[str, dict]) -> dict[str, dict]:
    observed_prices = {
        symbol: observation["price"]
        for symbol, observation in observations.items()
        if observation.get("available") is True and observation.get("price") is not None
    }
    computed = _monitor.compute_health(observed_prices) if observed_prices else {}
    result: dict[str, dict] = {}
    for symbol in StablecoinHealthMonitor.STABLES:
        observation = observations[symbol]
        if observation.get("available") is not True:
            result[symbol] = dict(observation)
            continue
        result[symbol] = {
            **computed.get(symbol, {}),
            **observation,
            "status": computed.get(symbol, {}).get("status", "unavailable"),
        }
    return result


def _save_health(health: dict) -> None:
    _store.set_snapshot(STABLECOIN_HEALTH, health, ttl=60)
    _store.set_snapshot(STABLECOIN_HEALTH_LEGACY, health, ttl=60)


def _load_health() -> dict | None:
    return _store.get_snapshot(STABLECOIN_HEALTH) or _store.get_snapshot(STABLECOIN_HEALTH_LEGACY)


def _health_contract_is_current(health: dict | None) -> bool:
    if not isinstance(health, dict):
        return False
    for symbol in StablecoinHealthMonitor.STABLES:
        row = health.get(symbol)
        quality = row.get("quality") if isinstance(row, dict) else None
        if not isinstance(quality, dict) or quality.get("contract_version") != 1:
            return False
        if "available" not in row:
            return False
    return True


def _load_or_refresh_health() -> dict:
    cached = _load_health()
    if _health_contract_is_current(cached):
        return cached
    refreshed = _compute_observed_health(_get_stable_observations())
    _save_health(refreshed)
    return refreshed


def _observed_health_entries(health: dict) -> dict:
    return {
        symbol: data
        for symbol, data in (health or {}).items()
        if isinstance(data, dict)
        and data.get("available") is True
        and isinstance(data.get("quality"), dict)
        and data["quality"].get("observed") is True
        and data.get("status") in {"ok", "warning", "alert"}
    }


@router.get("/latest")
def get_latest():
    health = _compute_observed_health(_get_stable_observations())
    _save_health(health)
    return health


@router.get("/history")
def get_history(window: str = Query("7d")):
    cached = _store.get_snapshot("stablecoin:history")
    if cached:
        return cached
    return {"window": window, "points": []}


@router.get("/health")
def get_health():
    cached = _load_or_refresh_health()
    observed = _observed_health_entries(cached)
    alerts = _monitor.get_alerts(observed) if observed else []
    stress_data = {}
    for symbol, data in cached.items():
        if not isinstance(data, dict):
            continue
        if data.get("available") is not True or data.get("status") == "unavailable":
            stress_data[symbol] = {**data, "stress": None, "peg_break_probability": None}
            continue
        stress = _monitor.detect_stress(data.get("depeg_bps", 0), 0.0, 0.0)
        peg_prob = _monitor.compute_peg_break_probability(data.get("depeg_bps", 0))
        stress_data[symbol] = {
            **data,
            "stress": stress,
            "peg_break_probability": peg_prob,
        }
    return {"health": stress_data, "alerts": alerts, "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/alerts")
def get_alerts():
    cached = _load_or_refresh_health()
    observed = _observed_health_entries(cached)
    return {"alerts": _monitor.get_alerts(observed) if observed else []}
