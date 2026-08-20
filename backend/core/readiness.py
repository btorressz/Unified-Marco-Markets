"""Mode-aware liveness/readiness aggregation for the existing application stack.

This module reuses current DB, Redis, price, ingestion, risk, and execution
configuration boundaries. It does not create a second monitoring system.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from backend import config
from backend.core.operator_auth import operator_auth_required
from backend.core.price_authority import PriceAuthority
from backend.core.risk_policy import RiskRuntimeState, configured_risk_policy
from backend.core.redis_runtime import get_redis_runtime
from backend.core.state_keys import PRICE_INTEGRITY, PRICE_INTEGRITY_LEGACY_LATEST, price_integrity_key
from backend.core.state_store import StateStore
from backend.data.db import check_connection, check_required_tables
from backend.ingest.source_registry import list_sources

_REQUIRED_LIVE_TABLES = (
    "order_intents",
    "orders",
    "fills",
    "positions",
    "decision_audit",
)
_PRICE_SYMBOL = "SOL/USD"
_PRICE_SYMBOLS = ("BTC/USD", "ETH/USD", "SOL/USD")


def _check(status: str, **details: Any) -> dict[str, Any]:
    return {"status": status, **details}


def _utc_age_seconds(ts: datetime) -> float:
    value = ts
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _database_check() -> dict[str, Any]:
    ok = check_connection()
    return _check("ok" if ok else "error", blocking_live=not ok)


def _schema_check() -> dict[str, Any]:
    try:
        present, missing = check_required_tables(_REQUIRED_LIVE_TABLES)
    except Exception:
        present, missing = False, list(_REQUIRED_LIVE_TABLES)
    return _check(
        "ok" if present else "error",
        required_tables=list(_REQUIRED_LIVE_TABLES),
        missing_tables=missing,
        blocking_live=not present,
    )


def _redis_check() -> dict[str, Any]:
    runtime = get_redis_runtime()
    connected, latency_ms = runtime.ping()
    return _check(
        "ok" if connected else "error",
        connected=connected,
        ping_latency_ms=latency_ms,
        blocking_live=not connected,
    )


def _market_data_check() -> dict[str, Any]:
    authority = PriceAuthority()
    store = StateStore()
    symbol_checks: dict[str, dict[str, Any]] = {}

    for symbol in _PRICE_SYMBOLS:
        price = authority.get_price(symbol)
        raw_source = next(
            (row for row in authority.get_all_venues(symbol) if row.get("venue") == price.source),
            {},
        )
        source_ts = _parse_ts(raw_source.get("ts"))
        age = _utc_age_seconds(source_ts) if price.found and source_ts is not None else None
        fresh = bool(price.found and source_ts is not None and age is not None and age <= config.PRICE_FRESHNESS_THRESHOLD_S)

        integrity = store.get_snapshot(price_integrity_key(symbol)) or {}
        if symbol == _PRICE_SYMBOL and not integrity:
            integrity = store.get_snapshot(PRICE_INTEGRITY) or store.get_snapshot(PRICE_INTEGRITY_LEGACY_LATEST) or {}
        integrity_status = str(integrity.get("status") or integrity.get("integrity_status") or "UNKNOWN").upper()

        symbol_checks[symbol] = {
            "source": price.source,
            "price_found": price.found,
            "source_timestamp_present": source_ts is not None,
            "age_seconds": round(age, 2) if age is not None else None,
            "maximum_ready_age_seconds": config.PRICE_FRESHNESS_THRESHOLD_S,
            "fresh": fresh,
            "integrity_status": integrity_status,
            "blocking_live": not fresh or integrity_status != "OK",
        }

    all_fresh = all(row["fresh"] for row in symbol_checks.values())
    all_integrity_ok = all(row["integrity_status"] == "OK" for row in symbol_checks.values())
    status = "ok" if all_fresh and all_integrity_ok else "warning" if all_fresh else "error"
    legacy = symbol_checks[_PRICE_SYMBOL]

    return _check(
        status,
        symbol=_PRICE_SYMBOL,
        monitored_symbols=list(_PRICE_SYMBOLS),
        symbols=symbol_checks,
        source=legacy["source"],
        price_found=legacy["price_found"],
        source_timestamp_present=legacy["source_timestamp_present"],
        age_seconds=legacy["age_seconds"],
        maximum_ready_age_seconds=config.PRICE_FRESHNESS_THRESHOLD_S,
        integrity_status=legacy["integrity_status"],
        blocking_live=not (all_fresh and all_integrity_ok),
    )


def _ingestion_check() -> dict[str, Any]:
    store = StateStore()
    now = datetime.now(timezone.utc)
    sources = []
    degraded = False
    for source in list_sources():
        snapshot_key = source.get("snapshot_key")
        if not snapshot_key:
            continue
        snap = store.get_snapshot(snapshot_key)
        ts_raw = (snap or {}).get("ts") if isinstance(snap, dict) else None
        ts = _parse_ts(ts_raw)
        age = max(0.0, (now - ts).total_seconds()) if ts is not None else None
        expected = max(1, int(source.get("expected_cadence_seconds") or 1))
        healthy = age is not None and age <= expected * 3
        if not healthy:
            degraded = True
        sources.append({
            "source_id": source.get("source_id"),
            "provider": source.get("provider"),
            "status": "ok" if healthy else "degraded",
            "age_seconds": round(age, 2) if age is not None else None,
            "expected_cadence_seconds": expected,
        })
    return _check("degraded" if degraded else "ok", sources=sources, blocking_live=False)


def _risk_runtime_check() -> dict[str, Any]:
    try:
        policy = configured_risk_policy()
        numeric_ok = all(
            math.isfinite(float(value))
            for value in (policy.max_leverage, policy.max_margin_usage, policy.max_daily_loss)
        )
        numeric_ok = numeric_ok and policy.max_leverage > 0 and 0 < policy.max_margin_usage <= 1 and policy.max_daily_loss > 0 and policy.cooldown_seconds >= 0
        shared_available = RiskRuntimeState().available()
        status = "ok" if numeric_ok and shared_available else "warning" if numeric_ok else "error"
        return _check(
            status,
            policy_valid=numeric_ok,
            shared_state_available=shared_available,
            blocking_live=(not numeric_ok or not shared_available),
        )
    except Exception:
        return _check("error", policy_valid=False, shared_state_available=False, blocking_live=True)


def _live_executor_capabilities() -> dict[str, bool]:
    from backend.execution.drift_exec import DriftExecutor
    from backend.execution.hyperliquid_exec import HyperliquidExecutor

    return {
        "hyperliquid": bool(HyperliquidExecutor.production_ready),
        "drift": bool(DriftExecutor.production_ready),
    }


def _execution_config_check() -> dict[str, Any]:
    live_capable = config.EXECUTION_MODE == "live" or config.LIVE_EXECUTION_ENABLED
    auth_required = operator_auth_required()
    token_ok = bool(config.OPERATOR_API_TOKEN) if auth_required else True
    capabilities = _live_executor_capabilities()
    configured_live_venues = [venue for venue in config.SUPPORTED_EXECUTION_VENUES if venue != "paper"]
    ready_live_venues = [venue for venue in configured_live_venues if capabilities.get(venue, False)]

    problems: list[str] = []
    if config.LIVE_EXECUTION_ENABLED and config.EXECUTION_MODE != "live":
        problems.append("LIVE_EXECUTION_ENABLED requires EXECUTION_MODE=live")
    if config.EXECUTION_MODE == "live" and not config.LIVE_EXECUTION_ENABLED:
        problems.append("live execution is not enabled")
    if live_capable and not auth_required:
        problems.append("operator authorization is not required")
    if live_capable and not token_ok:
        problems.append("operator token is not configured")
    if live_capable and not config.SUPPORTED_EXECUTION_MARKETS:
        problems.append("no execution markets are configured")
    if live_capable and not configured_live_venues:
        problems.append("no live execution venues are configured")
    if live_capable and configured_live_venues and not ready_live_venues:
        problems.append("no configured live executor is production-ready")

    return _check(
        "ok" if not problems else "error",
        execution_mode=config.EXECUTION_MODE,
        live_execution_enabled=config.LIVE_EXECUTION_ENABLED,
        operator_auth_required=auth_required,
        operator_token_configured=bool(config.OPERATOR_API_TOKEN),
        configured_live_venues=configured_live_venues,
        production_ready_venues=ready_live_venues,
        executor_capabilities=capabilities,
        problems=problems,
        blocking_live=bool(problems),
    )


def build_readiness() -> dict[str, Any]:
    live_mode = config.EXECUTION_MODE == "live" or config.LIVE_EXECUTION_ENABLED
    checks = {
        "database": _database_check(),
        "schema": _schema_check(),
        "redis": _redis_check(),
        "market_data": _market_data_check(),
        "ingestion": _ingestion_check(),
        "risk_runtime": _risk_runtime_check(),
        "execution_config": _execution_config_check(),
    }

    blocking = [
        {"component": name, "reason": _reason(name, result)}
        for name, result in checks.items()
        if live_mode and result.get("blocking_live")
    ]
    blocking_names = {item["component"] for item in blocking}
    degraded = [
        {"component": name, "reason": _reason(name, result)}
        for name, result in checks.items()
        if result.get("status") != "ok" and name not in blocking_names
    ]

    if live_mode:
        ready = not blocking
        status = "ready" if ready else "not_ready"
    else:
        ready = True
        status = "degraded" if any(result.get("status") != "ok" for result in checks.values()) else "ready"

    return {
        "live": True,
        "ready": ready,
        "status": status,
        "mode": config.EXECUTION_MODE,
        "live_execution_enabled": config.LIVE_EXECUTION_ENABLED,
        "checks": checks,
        "blocking": blocking,
        "blocking_checks": [item["component"] for item in blocking],
        "degraded": degraded,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def _reason(name: str, result: dict[str, Any]) -> str:
    if name == "database":
        return "PostgreSQL connection unavailable"
    if name == "schema":
        missing = result.get("missing_tables") or []
        return "Required schema tables missing" + (f": {', '.join(missing)}" if missing else "")
    if name == "redis":
        return "Redis unavailable; shared idempotency/risk state is unavailable"
    if name == "market_data":
        symbols = result.get("symbols") or {}
        if symbols:
            unavailable = [symbol for symbol, row in symbols.items() if not row.get("price_found")]
            if unavailable:
                return "No execution price is available for: " + ", ".join(unavailable)
            missing_ts = [symbol for symbol, row in symbols.items() if not row.get("source_timestamp_present")]
            if missing_ts:
                return "Execution price source has no authoritative timestamp for: " + ", ".join(missing_ts)
            bad_integrity = [f"{symbol}={row.get('integrity_status', 'UNKNOWN')}" for symbol, row in symbols.items() if row.get("integrity_status") != "OK"]
            if bad_integrity:
                return "Price integrity is not OK: " + ", ".join(bad_integrity)
            return "One or more execution prices are stale"
        if not result.get("price_found"):
            return "No execution price is available"
        if not result.get("source_timestamp_present"):
            return "Execution price source has no authoritative timestamp"
        if result.get("integrity_status") != "OK":
            return f"Price integrity is {result.get('integrity_status', 'UNKNOWN')}"
        return "Execution price is stale"
    if name == "ingestion":
        return "One or more research ingestion feeds are stale or unavailable"
    if name == "risk_runtime":
        return "Configured risk policy or shared runtime state is unavailable"
    if name == "execution_config":
        return "; ".join(result.get("problems") or ["Execution configuration is invalid"])
    return f"{name} is degraded"
