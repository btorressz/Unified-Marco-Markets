from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from backend.compute.heuristic_performance import HORIZONS, aggregate_evaluations, evaluate_historical
from backend.compute.rules_engine import RulesEngine
from backend.data.repositories.backtest_repo import BacktestRepository
from backend.data.repositories.heuristic_repo import HeuristicRepository

router = APIRouter(prefix="/api/heuristics", tags=["heuristics"])
logger = logging.getLogger(__name__); _history = BacktestRepository(); _repo = HeuristicRepository()


def _window(body):
    try:
        end = datetime.fromisoformat(str(body["end_ts"]).replace("Z", "+00:00")) if body.get("end_ts") else datetime.now(timezone.utc)
        start = datetime.fromisoformat(str(body["start_ts"]).replace("Z", "+00:00")) if body.get("start_ts") else end - timedelta(days=max(1, min(int(body.get("window_days",90)), 3650)))
        if end.tzinfo is None: end=end.replace(tzinfo=timezone.utc)
        if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as exc: raise HTTPException(400, f"Invalid historical date range: {exc}") from exc
    if start >= end: raise HTTPException(400, "start_ts must be earlier than end_ts")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

@router.get("/registry")
def registry():
    return {"heuristics": [{k:v for k,v in rule.items() if k != "condition"} for rule in RulesEngine().rules]}

@router.post("/evaluate")
def evaluate(body: dict[str,Any] | None=None):
    body=dict(body or {}); start,end=_window(body)
    horizon=str(body.get("primary_horizon","24h")); interval=int(body.get("decision_interval_seconds",3600))
    if horizon not in HORIZONS: raise HTTPException(400,"Unsupported primary horizon")
    if interval < 60: raise HTTPException(400,"decision_interval_seconds must be at least 60")
    venue=str(body.get("venue") or "drift").lower(); market=str(body.get("market") or "SOL-PERP").upper(); symbol=str(body.get("symbol") or market).upper()
    outcome_end=end+timedelta(seconds=max(HORIZONS.values())+3600)
    try:
        bundle=_history.load_historical_bundle(start_ts=start.isoformat(), end_ts=outcome_end.isoformat(), venue=venue, symbol=symbol, market=market)
    except Exception as exc:
        logger.warning("Heuristic history unavailable",exc_info=True); raise HTTPException(503,"Historical data store unavailable; no synthetic fallback was used.") from exc
    try:
        result=evaluate_historical(bundle,start_ts=start,end_ts=end,venue=venue,market=market,symbol=symbol,
          heuristic_ids=body.get("heuristic_ids") or [],primary_horizon=horizon,decision_interval_seconds=interval)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    rows=result.pop("evaluations")
    if body.get("persist",True):
        try: result["persisted_count"]=_repo.bulk_upsert(rows)
        except Exception as exc: logger.warning("Heuristic persistence unavailable",exc_info=True); raise HTTPException(503,"Historical evaluation persistence unavailable") from exc
    else: result["persisted_count"]=0
    return result

@router.get("/evaluations")
def evaluations(heuristic_id:str|None=None,version:int|None=None,fired:bool|None=None,start_ts:str|None=None,end_ts:str|None=None,limit:int=Query(100,ge=1,le=5000)):
    try: rows=_repo.query(heuristic_id=heuristic_id,version=version,fired=fired,start_ts=start_ts,end_ts=end_ts,limit=limit)
    except Exception as exc: raise HTTPException(503,"Historical evaluation store unavailable") from exc
    return {"evaluations":rows,"count":len(rows)}

@router.get("/performance")
def performance(heuristic_id:str|None=None,version:int|None=None,primary_horizon:str|None=None,start_ts:str|None=None,end_ts:str|None=None,venue:str|None=None,market:str|None=None):
    if primary_horizon and primary_horizon not in HORIZONS: raise HTTPException(400,"Unsupported primary horizon")
    try: rows=_repo.performance_rows(heuristic_id=heuristic_id,version=version,primary_horizon=primary_horizon,start_ts=start_ts,end_ts=end_ts,venue=venue,market=market)
    except Exception as exc: raise HTTPException(503,"Historical evaluation store unavailable") from exc
    rules={(r["id"],r["version"]):r for r in RulesEngine().rules}; groups={}
    for row in rows: groups.setdefault((row["heuristic_id"],row["heuristic_version"],row["primary_horizon"]),[]).append(row)
    output=[]
    for (hid,ver,horizon), group in groups.items():
        rule=rules.get((hid,ver),{"id":hid,"version":ver,"name":hid,"evaluation_type":group[0]["evaluation_type"],"action_type":group[0]["action_type"],"expected_direction":group[0]["expected_direction"],"required_context":[]})
        output.append({**{k:v for k,v in rule.items() if k != "condition"},"primary_horizon":horizon,"evaluation_status":"validated" if any(r["evaluation_status"]=="evaluable" for r in group) else "not_evaluable","metrics":aggregate_evaluations(group,rule,horizon)})
    return {"performance":output,"count":len(output),"data_mode":"persisted_event_time","performance_feedback":"Research-only; no weights were modified."}
