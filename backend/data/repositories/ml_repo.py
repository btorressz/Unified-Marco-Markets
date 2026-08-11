"""PostgreSQL persistence boundary for ML governance."""
from __future__ import annotations
import json
from typing import Any

def _db():
    from backend.data import db
    return db

class MLRepository:
    def save_dataset(self, row):
        return _db().execute_returning("""INSERT INTO ml_datasets (id,dataset_hash,manifest) VALUES (%s,%s,%s::jsonb)
          ON CONFLICT (dataset_hash) DO UPDATE SET dataset_hash=EXCLUDED.dataset_hash RETURNING *""",
          (row["dataset_id"],row["dataset_hash"],json.dumps(row,default=str)))
    def save_training_run(self, row):
        return _db().execute_returning("""INSERT INTO ml_training_runs (id,dataset_id,status,method,fold_metrics,metrics)
          VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb) RETURNING *""",(row["id"],row["dataset_id"],row["status"],row["method"],json.dumps(row.get("fold_metrics",[])),json.dumps(row.get("metrics",{}))))
    def create_model(self,row):
        return _db().execute_returning("""INSERT INTO ml_models (id,model_key,model_version,training_run_id,dataset_id,model_type,lifecycle_state,
          feature_schema_id,feature_schema_version,label_definition_id,label_definition_version,validation_metrics,calibration_metrics,
          artifact_blob,artifact_sha256,library_versions) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s::jsonb) RETURNING *""",
          (row["id"],row["model_key"],row["model_version"],row["training_run_id"],row["dataset_id"],row["model_type"],row["lifecycle_state"],row["feature_schema_id"],row["feature_schema_version"],row["label_definition_id"],row["label_definition_version"],json.dumps(row["validation_metrics"]),json.dumps(row["calibration_metrics"]),row["artifact_blob"],row["artifact_sha256"],json.dumps(row["library_versions"])))
    def list_models(self): return _db().execute_query("SELECT * FROM ml_models ORDER BY created_at DESC")
    def get_model(self, model_id):
        rows=_db().execute_query("SELECT * FROM ml_models WHERE id=%s OR model_version=%s LIMIT 1",(model_id,model_id)); return rows[0] if rows else None
    def active_model(self):
        rows=_db().execute_query("SELECT * FROM ml_models WHERE model_key='macro_direction' AND lifecycle_state='active' ORDER BY promoted_at DESC LIMIT 1"); return rows[0] if rows else None
    def transition(self, model_id, state, reason):
        if state == "active":
            _db().execute_write("UPDATE ml_models SET lifecycle_state='archived',archived_at=NOW() WHERE model_key='macro_direction' AND lifecycle_state='active' AND id<>%s",(model_id,))
        return _db().execute_returning("UPDATE ml_models SET lifecycle_state=%s,promotion_reason=%s,promoted_at=CASE WHEN %s='active' THEN NOW() ELSE promoted_at END,archived_at=CASE WHEN %s='archived' THEN NOW() ELSE archived_at END WHERE id=%s RETURNING *",(state,reason,state,state,model_id))
    def list_datasets(self): return _db().execute_query("SELECT * FROM ml_datasets ORDER BY created_at DESC")
    def list_runs(self): return _db().execute_query("SELECT * FROM ml_training_runs ORDER BY created_at DESC")
    def save_prediction(self,row):
        return _db().execute_returning("INSERT INTO ml_predictions (input_hash,payload) VALUES (%s,%s::jsonb) RETURNING *",(row["input_hash"],json.dumps(row,default=str)))
    def prediction_count(self,model_id): return _db().execute_query("SELECT COUNT(*) AS count FROM ml_predictions WHERE payload->>'model_id'=%s",(str(model_id),))[0]["count"]
