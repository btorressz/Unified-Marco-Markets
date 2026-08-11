import logging
import math
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.schemas import RiskStatusResponse, StressTestResult
from backend.compute.risk_engine import RiskEngine
from backend.compute.stress_tests import StressTestRunner
from backend.compute.regime_memory import RegimeMemory
from backend.core.state_store import StateStore
from backend.data.repositories.positions_repo import PositionsRepository
from backend.execution.router import ExecutionRouter
from backend import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/risk", tags=["risk"])

_risk_engine = RiskEngine(
    max_leverage=config.MAX_LEVERAGE,
    max_margin_pct=config.MAX_MARGIN_USAGE,
    max_daily_loss=config.MAX_DAILY_LOSS,
    cooldown_seconds=config.COOLDOWN_SECONDS,
)
_stress_runner = StressTestRunner()
_state_store = StateStore()
_positions_repo = PositionsRepository()
_exec_router = ExecutionRouter()
_regime_memory = RegimeMemory()


class StressTestRequest(BaseModel):
    scenario: str = "tariff_shock"
    params: dict | None = None


@router.get("/status", response_model=RiskStatusResponse)
def get_status():
    try:
        status = _risk_engine.get_status()
        throttle = _state_store.get_risk_throttle()

        # Use the durable position view for read-only portfolio metrics. This
        # avoids reporting hard-coded zero leverage/margin values while keeping
        # execution routing and risk policy unchanged.
        positions = _positions_repo.get_all()
        account = dict(_state_store.get_snapshot("execution:account") or {})
        snapshot = _risk_engine.build_portfolio_snapshot(positions, account=account)
        metrics = _risk_engine.calculate_metrics(snapshot)
        leverage = float(metrics.get("gross_leverage", 0.0) or 0.0)
        margin_usage = float(metrics.get("margin_utilization", 0.0) or 0.0)
        if not math.isfinite(leverage):
            leverage = 0.0
        if not math.isfinite(margin_usage):
            margin_usage = 0.0

        return RiskStatusResponse(
            throttle_active=throttle.get("active", False) or status.get("throttle_active", False),
            throttle_reason=throttle.get("reason", "") or status.get("throttle_reason", ""),
            current_leverage=leverage,
            margin_usage=margin_usage,
            daily_pnl=status.get("daily_pnl", 0.0),
            max_leverage=status.get("max_leverage", config.MAX_LEVERAGE),
            max_margin_usage=status.get("max_margin_pct", config.MAX_MARGIN_USAGE),
            max_daily_loss=status.get("max_daily_loss", config.MAX_DAILY_LOSS),
            ts=datetime.now(timezone.utc),
        )
    except Exception as exc:
        logger.error("Error fetching risk status: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch risk status")


@router.post("/stress-test", response_model=StressTestResult)
def run_stress_test(req: StressTestRequest):
    try:
        positions = _exec_router.get_all_positions()
        result = _stress_runner.run_scenario(
            scenario_name=req.scenario,
            positions=positions,
            params=req.params or {},
        )
        if "error" in result:
            raise HTTPException(status_code=400, detail=result)
        return StressTestResult(**result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error running stress test: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to run stress test")


@router.get("/guardrails")
def get_guardrails():
    try:
        return {
            "max_leverage": config.MAX_LEVERAGE,
            "max_margin_usage": config.MAX_MARGIN_USAGE,
            "max_daily_loss": config.MAX_DAILY_LOSS,
            "cooldown_seconds": config.COOLDOWN_SECONDS,
            "execution_mode": config.EXECUTION_MODE,
            "live_execution_enabled": config.LIVE_EXECUTION_ENABLED,
            "supported_execution_venues": config.SUPPORTED_EXECUTION_VENUES,
            "supported_execution_markets": config.SUPPORTED_EXECUTION_MARKETS,
            "supported_order_types": config.SUPPORTED_ORDER_TYPES,
            "max_order_notional": config.MAX_ORDER_NOTIONAL,
            "max_order_slippage_bps": config.MAX_ORDER_SLIPPAGE_BPS,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Error fetching guardrails: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch guardrails")


@router.get("/regime-analogs")
def get_regime_analogs():
    try:
        idx = _state_store.get_snapshot("index:latest") or {}
        regime = _state_store.get_snapshot("regime:latest") or {}

        shock_score = idx.get("shock_score", 0)
        shock_state = "high" if shock_score > 1.5 else ("elevated" if shock_score > 0.5 else "normal")
        funding_regime = regime.get("funding_regime", "neutral")
        vol_regime = regime.get("vol_regime", "normal")

        analogs = _regime_memory.find_analogues(shock_state, funding_regime, vol_regime)
        outcomes = _regime_memory.get_outcome_distribution(shock_state, funding_regime, vol_regime)
        summary = _regime_memory.get_summary()

        return {
            "current_regime": {
                "shock_state": shock_state,
                "funding_regime": funding_regime,
                "vol_regime": vol_regime,
            },
            "analogs": analogs,
            "outcome_distribution": outcomes,
            "memory_summary": summary,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Error fetching regime analogs: %s", exc, exc_info=True)
        return {
            "current_regime": {},
            "analogs": [],
            "outcome_distribution": {},
            "memory_summary": {},
            "ts": datetime.now(timezone.utc).isoformat(),
        }