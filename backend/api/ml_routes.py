import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.ml.feature_store import build_features
from backend.ml.inference import predict, get_cached_prediction
from backend.ml.training import train_offline, get_training_history
from backend.ml.explainability import explain
from backend.ml.governance import repository, promote, rollback, eligibility, model_health
from backend.ml.inference import invalidate_cache
from backend.data.repositories.heuristic_repo import HeuristicRepository
from backend.compute.heuristic_performance import aggregate_evaluations
from backend.compute.rules_engine import RulesEngine
from backend.core.state_keys import (
    PREDICTION_LATEST,
    PREDICTION_LATEST_LEGACY,
    STABLECOIN_HEALTH,
    STABLECOIN_HEALTH_LEGACY,
)
from backend.core.state_store import StateStore
from backend.core.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ml", tags=["ml"])

_store = StateStore()
_bus = EventBus()

_FEATURES_KEY = "desk:ml:features:latest"
_FEATURES_TTL = 120
_PREDICTION_KEY = "desk:ml:prediction:latest"
_PREDICTION_TTL = 120


def _stable_assets(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    assets = snapshot.get("assets")
    if isinstance(assets, dict):
        return assets
    return {key: value for key, value in snapshot.items() if isinstance(value, dict) and "depeg_bps" in value}


def _utc_timestamp_key(value: Any) -> str | None:
    """Normalize equivalent timestamp spellings before exact-sample alignment."""
    if value is None:
        return None
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


def _collect_state() -> dict[str, Any]:
    state: dict[str, Any] = {}

    idx = _store.get_snapshot("desk:index:latest") or _store.get_snapshot("index:latest")
    if idx:
        state["tariff_index"] = idx.get("value", 30.0)
        state["tariff_delta"] = idx.get("rate_of_change", 0.0)

    shock = _store.get_snapshot("desk:shock:latest") or _store.get_snapshot("shock:latest")
    if shock:
        state["shock_score"] = shock.get("shock_score", 0.0)

    pred = _store.get_snapshot(PREDICTION_LATEST) or _store.get_snapshot(PREDICTION_LATEST_LEGACY)
    if pred:
        state["predictor_confidence"] = pred.get("confidence", 0.5)

    arb = _store.get_snapshot("funding_arb:latest")
    if arb:
        state["funding_skew"] = arb.get("hl_rate", 0.0)

    basis = _store.get_snapshot("basis:latest")
    if basis:
        state["basis_spread"] = basis.get("basis_bps", 0.0) / 10000.0

    vr = _store.get_snapshot("desk:vol_regime:latest") or _store.get_snapshot("vol_regime:latest")
    if vr:
        state["vol_regime"] = vr.get("regime", "normal")

    stable = _store.get_snapshot(STABLECOIN_HEALTH) or _store.get_snapshot(STABLECOIN_HEALTH_LEGACY)
    assets = _stable_assets(stable)
    if assets:
        state["stable_health"] = sum(
            1.0 - min(abs(a.get("depeg_bps", 0)) / 100.0, 1.0)
            for a in assets.values()
        ) / len(assets)

    sf = _store.get_snapshot("stable_flow:latest")
    if sf:
        state["stable_flow"] = sf.get("momentum", 0.0)

    eqi = _store.get_snapshot("execution:metrics:latest")
    if eqi:
        state["exec_quality"] = eqi.get("eqi_score", 0.8)

    ms = _store.get_snapshot("microstructure:latest")
    if ms:
        state["orderbook_imbalance"] = ms.get("imbalance", 0.0)

    return state


@router.get("/features/latest")
def get_latest_features():
    cached = _store.get_snapshot(_FEATURES_KEY)
    if cached:
        return cached

    state = _collect_state()
    result = build_features(state)

    _store.set_snapshot(_FEATURES_KEY, result, ttl=_FEATURES_TTL)

    _bus.emit(
        EventType.ML_FEATURES_UPDATED,
        source="ml_routes",
        payload={"feature_count": len(result.get("features", {}))},
    )

    return result


@router.get("/prediction/latest")
def get_latest_prediction():
    cached = _store.get_snapshot(_PREDICTION_KEY)
    if cached:
        return cached

    state = _collect_state()
    feature_result = build_features(state)
    features = feature_result.get("features", {})
    explanation = explain(features)
    pred = predict(features, feature_result.get("feature_provenance"), feature_result.get("quality"), explanation=explanation)

    result = {
        "prediction": pred,
        "top_drivers": explanation.get("top_positive_drivers", [])[:3]
        + explanation.get("top_negative_drivers", [])[:2],
        "explanation_method": explanation.get("method", "heuristic"),
        "features_used": features,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    _store.set_snapshot(_PREDICTION_KEY, result, ttl=_PREDICTION_TTL)

    _bus.emit(
        EventType.ML_INFERENCE_UPDATE,
        source="ml_routes",
        payload={
            "probability": pred.get("probability"),
            "prediction_strength": pred.get("prediction_strength"),
            "model_type": pred.get("model_type"),
        },
    )

    return result


@router.post("/train/offline")
def train_model_offline(body: dict[str, Any] | None = None):
    body = body or {}

    samples = body.get("samples", [])
    labels = body.get("labels", [])
    method = str(body.get("method", "logistic"))

    if not samples or not labels:
        return {
            "success": False,
            "reason": "No training data provided. Supply 'samples' (list of feature dicts) and 'labels' (list of 0/1).",
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    result = train_offline(samples, labels, method=method, venue=body.get("venue"), market=body.get("market"),
                           symbol=body.get("symbol"), source_ids=body.get("source_ids"), ingest_run_ids=body.get("ingest_run_ids"),
                           provenance_ids=body.get("provenance_ids"))

    if result.get("success"):
        _store.set_snapshot(_PREDICTION_KEY, None, ttl=1)
        _bus.emit(
            EventType.ML_MODEL_TRAINED,
            source="ml_routes",
            payload={
                "method": result.get("method"),
                "n_samples": result.get("n_samples"),
                "train_accuracy": result.get("train_accuracy"),
            },
        )

    return result


@router.get("/training/history")
def get_training_history_route():
    try:
        return {"history": repository().list_runs(), "source": "postgres", "durable": True,
                "ts": datetime.now(timezone.utc).isoformat()}
    except Exception:
        logger.warning("Durable training history unavailable", exc_info=True)
        return {"history": get_training_history(), "source": "process_fallback", "durable": False,
                "ts": datetime.now(timezone.utc).isoformat()}

def _public(model):
    return {k: v for k, v in (model or {}).items() if k != "artifact_blob"}

@router.get("/models")
def models(): return {"models": [_public(x) for x in repository().list_models()]}

@router.get("/models/active")
def active_model(): return {"model": _public(repository().active_model())}

@router.get("/models/{model_id}")
def model_detail(model_id: str):
    model=repository().get_model(model_id)
    if not model: raise HTTPException(404,"Model not found")
    dataset=next((d.get("manifest",d) for d in repository().list_datasets() if str(d.get("id",d.get("dataset_id")))==str(model["dataset_id"])),None)
    return {"model":_public(model),"eligibility":eligibility(model,dataset)}

@router.post("/models/{model_id}/promote")
def promote_model(model_id: str, body: dict[str,Any]|None=None):
    try: model=promote(model_id,str((body or {}).get("reason") or "explicit operator promotion")); invalidate_cache(); return {"model":_public(model)}
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc

@router.post("/models/{model_id}/rollback")
def rollback_model(model_id: str, body: dict[str,Any]|None=None):
    try: model=rollback(model_id,str((body or {}).get("reason") or "explicit operator rollback")); invalidate_cache(); return {"model":_public(model)}
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc

@router.get("/datasets")
def datasets(): return {"datasets":repository().list_datasets()}

@router.get("/training/runs")
def training_runs(): return {"runs":repository().list_runs()}

@router.get("/model-health")
def health(): return model_health()

@router.get("/comparison")
def comparison():
    model=repository().active_model()
    if not model:return {"comparable":False,"reason":"No active governed ML model"}
    manifest=next((d.get("manifest",d) for d in repository().list_datasets() if str(d.get("id",d.get("dataset_id")))==str(model["dataset_id"])),{})
    records=(model.get("validation_metrics") or {}).get("validation_records") or []
    if not records:return {"comparable":False,"reason":"ML validation sample identities are unavailable"}
    try: rows=HeuristicRepository().performance_rows(primary_horizon="24h",venue=manifest.get("venue"),market=manifest.get("market"),start_ts=manifest.get("observation_start"),end_ts=manifest.get("observation_end"))
    except Exception:return {"comparable":False,"reason":"Compatible heuristic evaluations are unavailable"}
    by_ts={key:r for r in records if (key:=_utc_timestamp_key(r.get("timestamp"))) is not None}
    aligned=[]
    for row in rows:
        key=_utc_timestamp_key(row.get("decision_ts"))
        if key is not None and key in by_ts:
            aligned.append((row,by_ts[key]))
    if not aligned:return {"comparable":False,"reason":"No exact aligned evaluation samples","aligned_sample_count":0,"alignment":"exact_timestamp_utc"}
    rule=next((r for r in RulesEngine().rules if r["id"]==aligned[0][0]["heuristic_id"]),None)
    if not rule:return {"comparable":False,"reason":"Heuristic version is not registered"}
    hm=aggregate_evaluations([x[0] for x in aligned],rule,"24h")
    truth=[int(x[1]["true_label"]) for x in aligned]; pred=[int(x[1]["predicted_class"]) for x in aligned]; probs=[float(x[1]["probability"]) for x in aligned]
    tp=sum(p==1 and y==1 for p,y in zip(pred,truth)); fp=sum(p==1 and y==0 for p,y in zip(pred,truth)); fn=sum(p==0 and y==1 for p,y in zip(pred,truth))
    mm={"accuracy":sum(p==y for p,y in zip(pred,truth))/len(truth),"precision":tp/(tp+fp) if tp+fp else None,"recall":tp/(tp+fn) if tp+fn else None,"brier":sum((p-y)**2 for p,y in zip(probs,truth))/len(truth)}
    mm["f1"]=2*mm["precision"]*mm["recall"]/(mm["precision"]+mm["recall"]) if mm["precision"] is not None and mm["recall"] is not None and mm["precision"]+mm["recall"] else None
    return {"comparable":True,"aligned_sample_count":len(aligned),"alignment":"exact_timestamp_utc","window":{"start":manifest.get("observation_start"),"end":manifest.get("observation_end"),"venue":manifest.get("venue"),"market":manifest.get("market"),"horizon":"24h"},"model":{"id":str(model["id"]),"version":model["model_version"],"sample_count":len(aligned),**mm},"heuristic":{"id":rule["id"],"version":rule["version"],"sample_count":hm.get("evaluable_count"),"accuracy":hm.get("directional_accuracy"),"precision":hm.get("precision"),"recall":hm.get("recall"),"f1":hm.get("f1"),"brier":hm.get("brier_score")}}
