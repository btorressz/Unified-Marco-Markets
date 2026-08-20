import json
import logging
from datetime import datetime, timezone

from backend.data.db import execute_query, execute_returning
from backend.ingest.provenance import sanitize_error

logger = logging.getLogger(__name__)
RECENT_WINDOW_RUNS = 30


class IngestRepository:
    def start_run(self, source_id, provider, data_type=None, worker_id=None, lease_acquired=None, metadata=None):
        row = execute_returning("""INSERT INTO ingest_runs (source_id,provider,data_type,status,started_at,worker_id,lease_acquired,metadata)
            VALUES (%s,%s,%s,'running',%s,%s,%s,%s) RETURNING id,started_at""",
            (source_id, provider, data_type, datetime.now(timezone.utc), worker_id, lease_acquired, json.dumps(metadata or {})))
        return row

    def finish_run(self, run_id, **facts):
        if not run_id: return None
        completed = datetime.now(timezone.utc)
        return execute_returning("""UPDATE ingest_runs SET status=%s,completed_at=%s,
            duration_ms=EXTRACT(EPOCH FROM (%s-started_at))*1000,records_received=%s,records_persisted=%s,
            fallback_used=%s,fallback_source_id=%s,fallback_type=%s,provider_timestamp=%s,lease_acquired=COALESCE(%s,lease_acquired),
            lease_skipped=%s,error_type=%s,error_message=%s,metadata=%s WHERE id=%s RETURNING *""",
            (facts.get("status", "success"), completed, completed, facts.get("records_received",0), facts.get("records_persisted",0), facts.get("fallback_used",False), facts.get("fallback_source_id"), facts.get("fallback_type"), facts.get("provider_timestamp"), facts.get("lease_acquired"), facts.get("lease_skipped",False), facts.get("error_type"), sanitize_error(facts.get("error_message")) if facts.get("error_message") else None, json.dumps(facts.get("metadata") or {}, default=str), run_id))

    def mark_failure(self, run_id, error):
        return self.finish_run(run_id, status="failure", error_type=type(error).__name__, error_message=sanitize_error(error))

    def record_provenance(self, ingest_run_id, source_id, artifact_type, artifact_id=None, artifact_key=None, provider_timestamp=None, received_at=None, persisted_at=None, fallback_used=False, fallback_source_id=None, quality=None, lineage=None, metadata=None):
        return execute_returning("""INSERT INTO data_provenance (ingest_run_id,source_id,artifact_type,artifact_id,artifact_key,provider_timestamp,received_at,persisted_at,fallback_used,fallback_source_id,quality,lineage,metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (ingest_run_id,source_id,artifact_type,str(artifact_id) if artifact_id is not None else None,artifact_key,provider_timestamp,received_at,persisted_at or datetime.now(timezone.utc),fallback_used,fallback_source_id,json.dumps(quality or {}),json.dumps(lineage or {},default=str),json.dumps(metadata or {},default=str)))

    def record_source_observation(
        self,
        *,
        ingest_run_id,
        source_id: str,
        artifact_type: str,
        artifact_key: str,
        observation: dict,
        quality: dict,
        lineage: dict,
        provider_timestamp=None,
        received_at=None,
    ):
        """Persist one normalized observation in the existing provenance ledger.

        This deliberately reuses data_provenance rather than introducing another
        generic observation table. Source-specific historical tables can still be
        added later when a concrete analytical query requires one.
        """
        return self.record_provenance(
            ingest_run_id,
            source_id,
            artifact_type,
            artifact_key=artifact_key,
            provider_timestamp=provider_timestamp,
            received_at=received_at,
            fallback_used=False,
            quality=quality,
            lineage=lineage,
            metadata={"observation": observation},
        )

    def get_recent_runs(self, source_id=None, status=None, start_ts=None, end_ts=None, limit=100):
        limit=max(1,min(int(limit),1000)); clauses=[]; params=[]
        for col,val,op in (("source_id",source_id,"="),("status",status,"="),("started_at",start_ts,">="),("started_at",end_ts,"<=")):
            if val is not None: clauses.append(f"{col} {op} %s"); params.append(val)
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        return execute_query(f"SELECT * FROM ingest_runs{where} ORDER BY started_at DESC LIMIT %s", tuple(params+[limit]))

    def get_source_runs(self, source_id, limit=RECENT_WINDOW_RUNS): return self.get_recent_runs(source_id=source_id,limit=limit)

    def get_latest_completed_run(self, source_id):
        rows=execute_query("SELECT * FROM ingest_runs WHERE source_id=%s AND status='success' AND completed_at IS NOT NULL ORDER BY completed_at DESC LIMIT 1",(source_id,))
        return rows[0] if rows else None

    def load_source_observations_for_run(self, source_id, ingest_run_id, artifact_type, limit=100000):
        limit=max(1,min(int(limit),100000))
        return execute_query("SELECT * FROM data_provenance WHERE source_id=%s AND ingest_run_id=%s AND artifact_type=%s ORDER BY created_at ASC LIMIT %s",(source_id,ingest_run_id,artifact_type,limit))

    def get_provenance(self, source_id=None, ingest_run_id=None, artifact_type=None, artifact_id=None, start_ts=None, end_ts=None, limit=100):
        limit=max(1,min(int(limit),1000)); clauses=[]; params=[]
        for col,val,op in (("source_id",source_id,"="),("ingest_run_id",ingest_run_id,"="),("artifact_type",artifact_type,"="),("artifact_id",artifact_id,"="),("created_at",start_ts,">="),("created_at",end_ts,"<=")):
            if val is not None: clauses.append(f"{col} {op} %s"); params.append(val)
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        return execute_query(f"SELECT * FROM data_provenance{where} ORDER BY created_at DESC LIMIT %s",tuple(params+[limit]))

    def get_registry_status(self, source_ids):
        result={}
        for source_id in source_ids:
            runs=self.get_source_runs(source_id)
            eligible=[r for r in runs if r.get("status") != "skipped_lease"]
            streak=0
            for run in eligible:
                if run.get("status")=="failure": streak+=1
                else: break
            successes=sum(r.get("status")=="success" for r in eligible); failures=sum(r.get("status")=="failure" for r in eligible); fallbacks=sum(r.get("status")=="fallback" for r in eligible)
            last=eligible[0] if eligible else None
            result[source_id]={"last_attempt": last.get("started_at") if last else None,"last_success":next((r.get("completed_at") for r in eligible if r.get("status")=="success"),None),"last_failure":next((r.get("completed_at") for r in eligible if r.get("status")=="failure"),None),"failure_streak":streak,"recent_window_runs":RECENT_WINDOW_RUNS,"recent_run_count":len(eligible),"recent_success_count":successes,"recent_failure_count":failures,"recent_fallback_count":fallbacks,"recent_success_rate":successes/len(eligible) if eligible else None,"recent_failure_rate":failures/len(eligible) if eligible else None,"last_run":last}
        return result
