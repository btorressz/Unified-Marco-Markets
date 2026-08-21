"""Bounded, append-only access to normalized research events."""
import json
import logging
from backend.data.db import execute_query, execute_returning
logger = logging.getLogger(__name__)

MAX_LIST_LIMIT = 250
_COLUMNS = ("event_key", "event_family", "event_type", "source", "source_id", "authority", "jurisdiction",
 "claim_type", "observed", "authoritative", "proxy", "synthetic", "execution_eligible", "event_timestamp",
 "event_time_basis", "published_at", "effective_at", "provider_updated_at", "detected_at", "retrieved_at",
 "source_record_id", "source_record_type", "change_type", "evidence_contract_version", "transformation",
 "transformation_version", "content_hash", "dataset_version", "study_eligible", "payload", "evidence", "lineage")

class ResearchEventRepository:
    def insert_event_idempotent(self, event):
        try:
            values=[json.dumps(event.get(c) or {},default=str) if c in {"payload","evidence","lineage"} else event.get(c) for c in _COLUMNS]
            row=execute_returning(f"INSERT INTO research_events ({','.join(_COLUMNS)}) VALUES ({','.join(['%s']*len(_COLUMNS))}) ON CONFLICT(event_key) DO NOTHING RETURNING *",tuple(values))
            return row or self.get_event(event_key=event["event_key"])
        except Exception:
            logger.warning("Research event persistence unavailable", exc_info=True)
            return None

    def get_event(self, *, event_id=None, event_key=None):
        if event_id is None and event_key is None: return None
        col,value=("id",event_id) if event_id is not None else ("event_key",event_key)
        rows=execute_query(f"SELECT * FROM research_events WHERE {col}=%s LIMIT 1",(value,))
        return rows[0] if rows else None

    def list_events(self, *, limit=100, event_family=None, event_type=None, source_id=None, claim_type=None,
                    study_eligible=None, synthetic=None, event_time_basis=None, start_ts=None, end_ts=None):
        limit=max(1,min(int(limit),MAX_LIST_LIMIT)); clauses=[]; params=[]
        for col,val,op in (("event_family",event_family,"="),("event_type",event_type,"="),("source_id",source_id,"="),
                           ("claim_type",claim_type,"="),("study_eligible",study_eligible,"="),
                           ("synthetic",synthetic,"="),("event_time_basis",event_time_basis,"="),
                           ("event_timestamp",start_ts,">="),("event_timestamp",end_ts,"<=")):
            if val is not None: clauses.append(f"{col} {op} %s"); params.append(val)
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        return execute_query(f"SELECT * FROM research_events{where} ORDER BY event_timestamp DESC NULLS LAST,created_at DESC LIMIT %s",tuple(params+[limit]))
