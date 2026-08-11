"""Explicit lifecycle governance. This module never promotes models automatically."""
from __future__ import annotations
import hashlib, pickle, uuid
from datetime import datetime, timezone
from typing import Any
from backend.ml.feature_store import FEATURE_SCHEMA_ID, FEATURE_SCHEMA_VERSION
from backend.ml.dataset import LABEL_DEFINITION_ID, LABEL_DEFINITION_VERSION
from backend.data.repositories.ml_repo import MLRepository

_repo: Any = MLRepository()
def repository(): return _repo
def set_repository(repo):
    global _repo; _repo=repo

def serialize_artifact(value) -> tuple[bytes,str]:
    blob=pickle.dumps(value,protocol=pickle.HIGHEST_PROTOCOL); return blob,hashlib.sha256(blob).hexdigest()
def verify_artifact(blob, digest): return bool(blob) and hashlib.sha256(bytes(blob)).hexdigest() == digest
def deserialize_artifact(blob, digest):
    if not verify_artifact(blob,digest): raise ValueError("artifact_integrity_failure")
    return pickle.loads(bytes(blob))

def eligibility(model, dataset=None):
    metrics=model.get("validation_metrics") or {}; folds=metrics.get("folds") or []
    ratio=((dataset or {}).get("default_feature_count",0)/max(1,(dataset or {}).get("sample_count",0)*15))
    checks=[("temporal_validation_complete",bool(folds) and all(f["train_end"] < f["validation_start"] for f in folds)),
            ("minimum_samples_met",(dataset or {}).get("sample_count",0)>=20),
            ("both_classes_exist",bool((dataset or {}).get("positive_count")) and bool((dataset or {}).get("negative_count"))),
            ("artifact_hash_valid",verify_artifact(model.get("artifact_blob"),model.get("artifact_sha256"))),
            ("schema_compatible",model.get("feature_schema_id")==FEATURE_SCHEMA_ID and model.get("feature_schema_version")==FEATURE_SCHEMA_VERSION),
            ("default_feature_ratio_acceptable",ratio<=0.5),("brier_available",metrics.get("brier") is not None)]
    return {"promotion_eligible":all(ok for _,ok in checks),"checks":[{"check":n,"passed":ok} for n,ok in checks]}

def promote(model_id, reason):
    model=_repo.get_model(model_id)
    if not model or model.get("lifecycle_state")!="candidate": raise ValueError("Only candidate models may be promoted")
    datasets=_repo.list_datasets(); dataset=next((d.get("manifest",d) for d in datasets if str(d.get("id",d.get("dataset_id")))==str(model["dataset_id"])),None)
    result=eligibility(model,dataset)
    if not result["promotion_eligible"]: raise ValueError("Model is not promotion eligible")
    activate=getattr(_repo,"activate_transactionally",None)
    return activate(model["id"],reason,expected_state="candidate") if activate else _repo.transition(model["id"],"active",reason)
def rollback(model_id, reason):
    model=_repo.get_model(model_id)
    if not model or model.get("lifecycle_state")!="archived": raise ValueError("Rollback target must be archived")
    activate=getattr(_repo,"activate_transactionally",None)
    return activate(model["id"],reason,expected_state="archived") if activate else _repo.transition(model["id"],"active",reason)

def model_health(model=None):
    model=model or _repo.active_model()
    if not model:return {"status":"unknown","indicators":{"active_model":False}}
    integrity=verify_artifact(model.get("artifact_blob"),model.get("artifact_sha256")); schema=model.get("feature_schema_id")==FEATURE_SCHEMA_ID and model.get("feature_schema_version")==FEATURE_SCHEMA_VERSION
    return {"status":"healthy" if integrity and schema else "degraded","indicators":{"artifact_integrity":integrity,"schema_compatible":schema,"prediction_count":_repo.prediction_count(model["id"])},"lifecycle_state_unchanged":True}

def input_hash(model_version, vector, timestamp):
    import json
    value={"model_version":model_version,"feature_schema_id":FEATURE_SCHEMA_ID,"feature_schema_version":FEATURE_SCHEMA_VERSION,"features":vector,"timestamp":timestamp}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
