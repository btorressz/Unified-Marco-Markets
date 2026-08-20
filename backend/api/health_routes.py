import time
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.core.schemas import HealthResponse
from backend.core.state_store import StateStore
from backend.core.redis_runtime import get_redis_runtime
from backend.core.readiness import build_readiness
from backend.data.db import check_connection
from backend.data.repositories.ingest_repo import IngestRepository
from backend.ingest.source_registry import list_sources

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])
probe_router = APIRouter(tags=["health"])

_state_store = StateStore()
_start_time = time.time()

_FEED_DEFINITIONS: list[dict[str, Any]] = [{"name":s["provider"],"source_id":s["source_id"],"key":s["snapshot_key"],"is_authoritative":s["authoritative"],"interval_seconds":s["expected_cadence_seconds"]} for s in list_sources() if s.get("snapshot_key")]

_WARNING_MULTIPLIER = 3
_ERROR_MULTIPLIER = 10


def _get_feed_status(feed_def: dict[str, Any], now: datetime) -> dict[str, Any]:
    name = feed_def["name"]
    key = feed_def["key"]
    is_auth = feed_def["is_authoritative"]
    interval = feed_def["interval_seconds"]

    result: dict[str, Any] = {
        "name": name,
        "last_update_ts": None,
        "age_seconds": None,
        "status": "error",
        "is_authoritative": is_auth,
    }

    try:
        snapshot = _state_store.get_snapshot(key)
        if snapshot is None:
            result["status"] = "error"
            return result

        ts_raw = snapshot.get("ts")
        if ts_raw:
            if isinstance(ts_raw, str):
                try:
                    ts = datetime.fromisoformat(ts_raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except ValueError:
                    ts = None
            elif isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
            else:
                ts = None
        else:
            ts = None

        if ts is None:
            result["status"] = "fallback"
            return result

        age = (now - ts).total_seconds()
        result["last_update_ts"] = ts.isoformat()
        result["age_seconds"] = round(age, 1)

        if age <= interval * _WARNING_MULTIPLIER:
            result["status"] = "ok"
        elif age <= interval * _ERROR_MULTIPLIER:
            result["status"] = "warning"
        else:
            result["status"] = "error"

    except Exception:
        logger.warning("Error checking feed status for %s", name, exc_info=True)
        result["status"] = "fallback"

    return result


@probe_router.get("/live")
def liveness_probe():
    """Process-level probe: if this handler responds, the API process is alive."""
    return {
        "live": True,
        "status": "live",
        "uptime_seconds": round(time.time() - _start_time, 2),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@probe_router.get("/ready")
def readiness_probe():
    """Mode-aware operational readiness; returns 503 only when truly not ready."""
    result = build_readiness()
    return JSONResponse(status_code=200 if result["ready"] else 503, content=result)


@router.get("/live")
def health_liveness_probe():
    return liveness_probe()


@router.get("/ready")
def health_readiness_probe():
    return readiness_probe()


@router.get("/", response_model=HealthResponse)
def health_check():
    try:
        db_ok = check_connection()
    except Exception:
        db_ok = False

    runtime = get_redis_runtime()
    redis_ok, _ = runtime.ping()

    uptime = time.time() - _start_time

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version="0.1.0",
        database=db_ok,
        redis=redis_ok,
        uptime_seconds=round(uptime, 2),
        ts=datetime.now(timezone.utc),
    )


@router.get("/feeds")
def feed_status():
    now = datetime.now(timezone.utc)
    feeds = [_get_feed_status(fd, now) for fd in _FEED_DEFINITIONS]
    ok_count = sum(1 for f in feeds if f["status"] == "ok")
    total = len(feeds)
    overall = "ok" if ok_count == total else "degraded" if ok_count > 0 else "error"
    return {
        "status": overall,
        "feeds": feeds,
        "ok_count": ok_count,
        "total": total,
        "ts": now.isoformat(),
    }


@router.get("/redis")
def redis_health():
    runtime = get_redis_runtime()
    connected, latency_ms = runtime.ping()
    runtime_health = runtime.health_snapshot()

    result: dict[str, Any] = {
        **runtime_health,
        "connected": connected,
        "ping_latency_ms": latency_ms,
        "memory_used_mb": None,
        "key_count_estimate": None,
        "pubsub_status": "unknown",
        "fallback_mode": not connected,
        "key_namespace": runtime.key_prefix,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if not connected:
        return result

    r = runtime.get_client(ping=False)
    if r is None:
        result["connected"] = False
        result["fallback_mode"] = True
        return result

    try:
        info = r.info("memory")
        used_bytes = info.get("used_memory", 0)
        result["memory_used_mb"] = round(used_bytes / 1024 / 1024, 2)
    except Exception:
        pass

    try:
        result["key_count_estimate"] = r.dbsize()
    except Exception:
        pass

    try:
        pubsub_info = r.info("clients")
        result["pubsub_status"] = "ok" if pubsub_info else "unknown"
    except Exception:
        result["pubsub_status"] = "unknown"

    return result


@router.get("/data-quality")
def data_quality_dashboard():
    now = datetime.now(timezone.utc)
    feeds = [_get_feed_status(fd, now) for fd in _FEED_DEFINITIONS + [
        {"name": "yfinance", "key": "equity:yfinance:latest", "is_authoritative": False, "interval_seconds": 900},
        {"name": "Stooq", "key": "equity:stooq:latest", "is_authoritative": False, "interval_seconds": 86400},
        {"name": "mock/demo equity fallback", "key": "equity:demo:latest", "is_authoritative": False, "interval_seconds": 31536000},
    ]]
    enriched = []
    try: reliability=IngestRepository().get_registry_status([f.get("source_id") for f in _FEED_DEFINITIONS]); provenance_available=True
    except Exception: reliability={}; provenance_available=False
    priorities = {"Pyth": 1, "Kraken": 2, "CoinGecko": 3, "yfinance": 1, "Stooq": 2, "mock/demo equity fallback": 3}
    fallback = {"Pyth": "Kraken", "Kraken": "CoinGecko", "CoinGecko": "demo", "yfinance": "Stooq", "Stooq": "mock/demo equity fallback"}
    for f in feeds:
        status = f.get("status")
        age = f.get("age_seconds")
        stale = status in ("warning", "error")
        run=reliability.get(f.get("source_id"),{})
        enriched.append({
            **f,
            "authoritative_source": f.get("is_authoritative", False),
            "source_priority": priorities.get(f["name"], 5),
            "source_age_seconds": age,
            "staleness": "fresh" if status == "ok" else "stale" if stale else "degraded",
            "error_rate": run.get("recent_failure_rate"),
            "fallback_source": (run.get("last_run") or {}).get("fallback_source_id"),
            "degraded_mode": status != "ok",
            "last_successful_fetch": run.get("last_success"),
            "confidence_score": None,
            "last_attempt":run.get("last_attempt"),"last_failure":run.get("last_failure"),"failure_streak":run.get("failure_streak"),"recent_success_rate":run.get("recent_success_rate"),"provenance_available":provenance_available,
        })
    ok = sum(1 for f in enriched if f["status"] == "ok")
    configured_chains = [s["fallback_chain"] for s in list_sources() if s["fallback_chain"]]
    return {"status": "ok" if ok == len(enriched) else "degraded", "sources": enriched, "configured_fallback_chains": configured_chains, "provenance_available":provenance_available, "ts": now.isoformat()}
