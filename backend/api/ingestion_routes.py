"""Read-only ingestion audit and provenance API."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Query

from backend.core.state_store import StateStore
from backend.data.repositories.ingest_repo import IngestRepository
from backend.ingest.source_registry import list_sources

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])
repo = IngestRepository(); state = StateStore()


def _json(value):
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, dict): return {k:_json(v) for k,v in value.items()}
    if isinstance(value, list): return [_json(v) for v in value]
    return value


@router.get("/registry")
def registry(): return {"sources": list_sources()}


@router.get("/status")
def status():
    sources=list_sources()
    try:
        history=repo.get_registry_status([s["source_id"] for s in sources]); available=True
    except Exception:
        logger.warning("Ingestion provenance unavailable", exc_info=True); history={}; available=False
    now=datetime.now(timezone.utc); output=[]
    for source in sources:
        item=history.get(source["source_id"],{}); last=item.get("last_run") or {}; age=None
        try:
            snapshot=state.get_snapshot(source.get("snapshot_key"))
            raw=(snapshot or {}).get("ts")
            if raw:
                ts=datetime.fromisoformat(raw) if isinstance(raw,str) else datetime.fromtimestamp(raw,tz=timezone.utc)
                if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
                age=round((now-ts).total_seconds(),1)
        except Exception: pass
        output.append({**{k:source[k] for k in ("source_id","provider","category")},"status":last.get("status") if available else None,
          **{k:item.get(k) for k in ("last_attempt","last_success","last_failure","failure_streak","recent_window_runs","recent_run_count","recent_success_count","recent_failure_count","recent_fallback_count","recent_success_rate","recent_failure_rate")},
          "last_duration_ms":last.get("duration_ms"),"records_received":last.get("records_received"),"records_persisted":last.get("records_persisted"),"fallback_used":last.get("fallback_used"),"fallback_source_id":last.get("fallback_source_id"),"provider_timestamp":last.get("provider_timestamp"),"freshness_age_seconds":age,"provenance_available":available})
    return _json({"sources":output,"recent_window_runs":30,"provenance_available":available})


@router.get("/runs")
def runs(source_id: str|None=None,status: str|None=None,start_ts: datetime|None=None,end_ts: datetime|None=None,limit:int=Query(100,ge=1,le=1000)):
    try: return _json({"runs":repo.get_recent_runs(source_id,status,start_ts,end_ts,limit),"provenance_available":True})
    except Exception: logger.warning("Ingest runs unavailable",exc_info=True); return {"runs":[],"provenance_available":False}


@router.get("/provenance")
def provenance(source_id:str|None=None,ingest_run_id:str|None=None,artifact_type:str|None=None,artifact_id:str|None=None,start_ts:datetime|None=None,end_ts:datetime|None=None,limit:int=Query(100,ge=1,le=1000)):
    try: return _json({"provenance":repo.get_provenance(source_id,ingest_run_id,artifact_type,artifact_id,start_ts,end_ts,limit),"provenance_available":True})
    except Exception: logger.warning("Provenance unavailable",exc_info=True); return {"provenance":[],"provenance_available":False}
