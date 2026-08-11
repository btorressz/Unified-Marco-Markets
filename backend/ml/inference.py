import logging
from datetime import datetime,timezone
from backend.ml.feature_store import features_to_vector,FEATURE_SCHEMA_ID,FEATURE_SCHEMA_VERSION
from backend.ml.training import get_trained_model,set_trained_model
from backend.ml.governance import repository,deserialize_artifact,input_hash
logger=logging.getLogger(__name__); _CACHED_PREDICTION=None

def invalidate_cache():
    global _CACHED_PREDICTION; set_trained_model(None); _CACHED_PREDICTION=None

def _heuristic_predict(features,reason="no_active_model"):
    score=.5-(features.get("tariff_index",30)-30)/200-features.get("shock_score",0)*.05-features.get("vol_regime_encoded",.25)*.10+(features.get("stable_health",1)-.5)*.10+(features.get("predictor_conf",.5)-.5)*.15+(features.get("exec_quality",.8)-.5)*.05
    p=max(.05,min(.95,score)); strength=round(abs(p-.5)*2,4)
    return {"probability":round(p,4),"prediction":int(p>.5),"prediction_strength":strength,
            "probability_calibrated":False,"model_type":"heuristic_fallback","fallback_used":True,
            "fallback_reason":reason,"confidence":strength}

def _load_active():
    try: model=repository().active_model()
    except Exception: return None,"governance_store_unavailable"
    if not model:return None,"no_active_model"
    if model.get("feature_schema_id")!=FEATURE_SCHEMA_ID or model.get("feature_schema_version")!=FEATURE_SCHEMA_VERSION:return None,"feature_schema_mismatch"
    try: artifact=deserialize_artifact(model.get("artifact_blob"),model.get("artifact_sha256"))
    except Exception:return None,"artifact_integrity_failure"
    value={"pipeline":artifact["pipeline"],"record":model}; set_trained_model(value); return value,None

def predict(features,feature_provenance=None,feature_quality=None,timestamp=None,explanation=None):
    global _CACHED_PREDICTION
    ts=timestamp or datetime.now(timezone.utc).isoformat(); data=get_trained_model(); reason=None
    if data is None:data,reason=_load_active()
    if data is None:pred=_heuristic_predict(features,reason)
    else:
        try:
            vec=[features_to_vector(features)]; p=float(data["pipeline"].predict_proba(vec)[0][1]); rec=data["record"]
            pred={"probability":round(p,4),"prediction":int(p>=.5),"prediction_strength":round(abs(p-.5)*2,4),"probability_calibrated":bool((rec.get("calibration_metrics") or {}).get("probability_calibrated",False)),"model_type":rec["model_type"],"model_id":str(rec["id"]),"model_version":rec["model_version"],"training_run_id":str(rec["training_run_id"]),"dataset_id":str(rec["dataset_id"]),"fallback_used":False,"fallback_reason":None}
        except Exception as exc: logger.warning("ML inference failed: %s",exc); pred=_heuristic_predict(features,"inference_failure")
    pred["ts"]=ts; pred["input_hash"]=input_hash(pred.get("model_version","heuristic_fallback"),features_to_vector(features),ts)
    payload={**pred,"features":features,"feature_provenance":feature_provenance or {},"feature_quality":feature_quality or {},"explanation":explanation}
    try: repository().save_prediction(payload)
    except Exception: logger.debug("Prediction persistence unavailable",exc_info=True)
    _CACHED_PREDICTION=pred; return pred

def get_cached_prediction():return _CACHED_PREDICTION
