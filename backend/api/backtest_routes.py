import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.compute.backtester import run_backtest
from backend.core.state_store import StateStore
from backend.core.event_bus import EventBus, EventType
from backend.data.repositories.backtest_repo import BacktestRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_store = StateStore()
_bus = EventBus()
_repo = BacktestRepository()

_LATEST_KEY = "desk:backtest:latest"
_LATEST_TTL = 1800
_HISTORY: list[dict[str, Any]] = []
_MAX_HISTORY = 20

_HISTORICAL_SYMBOL_BY_VENUE = {
    "drift": "SOL-PERP",
    "pyth": "SOL/USD",
    "kraken": "SOLUSD",
    "coingecko": "SOLANA/USD",
}


def _historical_window(config: dict[str, Any]) -> tuple[str, str]:
    end_raw = config.get("end_ts")
    start_raw = config.get("start_ts")
    try:
        end = (
            datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
            if end_raw
            else datetime.now(timezone.utc)
        )
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        end = end.astimezone(timezone.utc)
        if start_raw:
            start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            start = start.astimezone(timezone.utc)
        else:
            window_days = max(1, min(int(config.get("window_days", 30)), 3650))
            start = end - timedelta(days=window_days)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid historical date range: {exc}") from exc
    if start >= end:
        raise HTTPException(status_code=400, detail="start_ts must be earlier than end_ts")
    return start.isoformat(), end.isoformat()


@router.post("/run")
def run_backtest_endpoint(body: dict[str, Any] | None = None):
    config = dict(body or {})
    mode = str(config.get("mode", "synthetic")).lower().strip()
    if mode not in ("synthetic", "historical"):
        raise HTTPException(status_code=400, detail="mode must be 'synthetic' or 'historical'")

    historical_data = None
    if mode == "historical":
        start_ts, end_ts = _historical_window(config)
        venue = str(config.get("venue") or "drift").lower().strip()
        market = str(config.get("market") or "SOL-PERP").upper().strip()
        symbol = str(config.get("symbol") or _HISTORICAL_SYMBOL_BY_VENUE.get(venue, market)).upper().strip()
        config["start_ts"] = start_ts
        config["end_ts"] = end_ts
        config["venue"] = venue
        config["market"] = market
        config["symbol"] = symbol
        try:
            historical_data = _repo.load_historical_bundle(
                start_ts=start_ts,
                end_ts=end_ts,
                venue=venue,
                symbol=symbol,
                market=market,
            )
            if str(config.get("strategy", "")).lower().strip() == "recorded_orders":
                # Recorded fills already carry their persisted fee/funding/slippage
                # economics; applying funding_ticks again would double count them.
                historical_data["funding_ticks"] = []
        except Exception as exc:
            logger.warning("Historical data load failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=503, detail="Historical data store unavailable") from exc

    _bus.emit(
        EventType.BACKTEST_STARTED,
        source="backtest_routes",
        payload={
            "mode": mode,
            "strategy": config.get("strategy", "momentum"),
            "window_days": config.get("window_days", 30),
            "venue": config.get("venue", "hyperliquid"),
            "market": config.get("market"),
            "start_ts": config.get("start_ts"),
            "end_ts": config.get("end_ts"),
        },
    )

    run_record = _repo.create_run(mode=mode, config=config)
    run_id = str(run_record.get("id")) if run_record and run_record.get("id") else None

    try:
        result = run_backtest(config, historical_data=historical_data)
    except ValueError as exc:
        if run_id:
            _repo.complete_run(
                run_id,
                status="failed",
                data_manifest={name: len(rows) for name, rows in (historical_data or {}).items()},
                metrics={"error": str(exc)},
            )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Backtest failed: %s", exc, exc_info=True)
        if run_id:
            _repo.complete_run(
                run_id,
                status="failed",
                data_manifest={name: len(rows) for name, rows in (historical_data or {}).items()},
                metrics={"error": str(exc)},
            )
        return {
            "success": False,
            "error": str(exc),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    result["success"] = True
    result["run_id"] = run_id
    result["persistence_status"] = "persisted" if run_id else "degraded"
    _store.set_snapshot(_LATEST_KEY, result, ttl=_LATEST_TTL)

    summary = {
        "run_id": run_id,
        "mode": result.get("mode", mode),
        "total_return_pct": result.get("total_return_pct"),
        "sharpe_ratio": result.get("sharpe_ratio"),
        "max_drawdown_pct": result.get("max_drawdown_pct"),
        "trade_count": result.get("trade_count"),
        "fill_count": result.get("fill_count"),
        "config": result.get("config", {}),
        "data_manifest": result.get("data_manifest", {}),
        "ts": result.get("ts"),
    }
    _HISTORY.append(summary)
    if len(_HISTORY) > _MAX_HISTORY:
        _HISTORY.pop(0)

    if run_id:
        metrics = {
            key: result.get(key)
            for key in (
                "total_return",
                "total_return_pct",
                "final_capital",
                "sharpe_ratio",
                "max_drawdown",
                "max_drawdown_pct",
                "win_rate",
                "trade_count",
                "fill_count",
                "avg_slippage_bps",
                "var_95",
                "cvar_95",
                "fees_paid",
                "funding_pnl",
                "slippage_cost",
                "realized_pnl",
                "unrealized_pnl",
            )
            if key in result
        }
        _repo.complete_run(
            run_id,
            status="completed",
            data_manifest=result.get("data_manifest", {}),
            metrics=metrics,
        )

    _bus.emit(
        EventType.BACKTEST_COMPLETED,
        source="backtest_routes",
        payload={
            "run_id": run_id,
            "mode": result.get("mode", mode),
            "total_return_pct": result.get("total_return_pct"),
            "sharpe_ratio": result.get("sharpe_ratio"),
            "max_drawdown_pct": result.get("max_drawdown_pct"),
            "trade_count": result.get("trade_count"),
            "fill_count": result.get("fill_count"),
        },
    )

    return result


@router.get("/latest")
def get_latest_backtest():
    cached = _store.get_snapshot(_LATEST_KEY)
    if cached:
        return cached
    return {
        "available": False,
        "message": "No backtest results yet. POST to /api/backtest/run to start one.",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/history")
def get_backtest_history():
    durable = _repo.list_runs(limit=_MAX_HISTORY)
    if durable:
        return {
            "history": durable,
            "count": len(durable),
            "source": "postgresql",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "history": list(_HISTORY),
        "count": len(_HISTORY),
        "source": "process_fallback",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/data-coverage")
def get_backtest_data_coverage():
    try:
        coverage = _repo.data_coverage()
        return {
            "coverage": coverage,
            "historical_symbol_defaults": _HISTORICAL_SYMBOL_BY_VENUE,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.warning("Backtest data coverage failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Historical data coverage unavailable") from exc


@router.get("/{run_id}")
def get_backtest_run(run_id: str):
    result = _repo.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return result
