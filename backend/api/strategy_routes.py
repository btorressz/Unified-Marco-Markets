from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter

from backend.compute.strategy_performance import compute_strategy_performance
from backend.data.repositories.positions_repo import PositionsRepository

router = APIRouter(prefix="/api/strategy", tags=["strategy"])
_repo = PositionsRepository()


@router.get("/performance")
def performance():
    trades = _repo.get_paper_trades(limit=500)
    if not trades:
        return {"strategies": {}, "summary": {}, "total_trades": 0, "trade_count": 0, "data_status": "no_realized_history", "ts": datetime.now(timezone.utc).isoformat(), "capital_allocation_feedback": "No realized history; no performance feedback is available."}
    result = compute_strategy_performance(trades)
    for sid, row in result.get("strategies", {}).items():
        row.setdefault("exposure", 0.0)
        row.setdefault("last_signal_ts", row.get("ts"))
    result["capital_allocation_feedback"] = "Performance is proposal-only input to allocator; no auto-trading."
    return result
