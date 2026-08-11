import logging, platform, uuid
from datetime import datetime, timezone
from typing import Any
from backend.ml.feature_store import FEATURE_NAMES, FEATURE_SCHEMA_ID, FEATURE_SCHEMA_VERSION, features_to_vector
from backend.ml.dataset import create_dataset_manifest, LABEL_DEFINITION_ID, LABEL_DEFINITION_VERSION
from backend.ml.governance import repository, serialize_artifact
logger=logging.getLogger(__name__)
_TRAINED_MODEL=None; _TRAINING_HISTORY=[]; MIN_SAMPLES=20

def _try_import_sklearn():
    try:
        import sklearn
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.metrics import accuracy_score,precision_score,recall_score,f1_score,roc_auc_score,brier_score_loss
        return (sklearn,LogisticRegression,Pipeline,StandardScaler,TimeSeriesSplit,accuracy_score,precision_score,recall_score,f1_score,roc_auc_score,brier_score_loss)
    except ImportError:return None

def train_offline(samples:list[dict[str,Any]],labels:list[int],method="logistic",**metadata):
    global _TRAINED_MODEL,_TRAINING_HISTORY
    now=datetime.now(timezone.utc).isoformat(); requested_method=str(method).lower().strip()
    if requested_method not in ("logistic", "logistic_regression"):
        return {"success":False,"reason":f"Unsupported training method: {method}","requested_method":requested_method,"actual_method":None,"ts":now}
    if len(samples)<MIN_SAMPLES:return {"success":False,"reason":f"Insufficient training data: {len(samples)} samples, minimum {MIN_SAMPLES} required","samples_provided":len(samples),"samples_needed":MIN_SAMPLES,"ts":now}
    try: manifest=create_dataset_manifest(samples,labels,**metadata)
    except ValueError as exc:return {"success":False,"reason":str(exc),"ts":now}
    if len(set(int(x) for x in labels))<2:return {"success":False,"reason":"Both label classes are required","ts":now}
    sk=_try_import_sklearn()
    if sk is None:return {"success":False,"reason":"scikit-learn not installed","ts":now}
    sklearn,LR,Pipeline,Scaler,TSS,accuracy,precision,recall,f1,auc,brier=sk
    X=[features_to_vector(s.get("features",s)) for s in samples]; y=[int(x) for x in labels]
    stamps=[s.get("timestamp",s.get("ts")) for s in samples]
    folds=[]; validation_records=[]
    for train_idx,val_idx in TSS(n_splits=min(5,max(2,len(y)//10))).split(X):
        if len(set(y[i] for i in train_idx))<2: continue
        pipe=Pipeline([("scaler",Scaler()),("model",LR(max_iter=500,C=1.0,random_state=42))])
        xt=[X[i] for i in train_idx]; yt=[y[i] for i in train_idx]; xv=[X[i] for i in val_idx]; yv=[y[i] for i in val_idx]
        pipe.fit(xt,yt); prob=pipe.predict_proba(xv)[:,1]; pred=pipe.predict(xv)
        validation_records.extend({"timestamp":str(stamps[i]),"true_label":int(y[i]),"predicted_class":int(p),"probability":float(q)} for i,p,q in zip(val_idx,pred,prob))
        folds.append({"train_start":str(stamps[train_idx[0]]),"train_end":str(stamps[train_idx[-1]]),"validation_start":str(stamps[val_idx[0]]),"validation_end":str(stamps[val_idx[-1]]),"train_samples":len(train_idx),"validation_samples":len(val_idx),"accuracy":accuracy(yv,pred),"precision":precision(yv,pred,zero_division=0),"recall":recall(yv,pred,zero_division=0),"f1":f1(yv,pred,zero_division=0),"roc_auc":auc(yv,prob) if len(set(yv))>1 else None,"brier":brier(yv,prob)})
    if not folds:return {"success":False,"reason":"Temporal validation could not produce a two-class training fold","ts":now}
    pipe=Pipeline([("scaler",Scaler()),("model",LR(max_iter=500,C=1.0,random_state=42))]); pipe.fit(X,y)
    metric=lambda key:sum(f[key] for f in folds if f[key] is not None)/sum(f[key] is not None for f in folds)
    metrics={"folds":folds,"validation_records":validation_records,**{key:metric(key) for key in ("accuracy","precision","recall","f1","brier")}}
    repo=repository(); repo.save_dataset(manifest)
    run_id=str(uuid.uuid4()); run={"id":run_id,"dataset_id":manifest["dataset_id"],"status":"completed","method":"logistic_regression","requested_method":requested_method,"actual_method":"logistic_regression","fold_metrics":folds,"metrics":metrics}; repo.save_training_run(run)
    blob,digest=serialize_artifact({"pipeline":pipe,"feature_names":FEATURE_NAMES})
    versions=repo.list_models(); number=max([int(str(m["model_version"]).lstrip("v")) for m in versions if str(m.get("model_version","")).lstrip("v").isdigit()] or [0])+1
    model={"id":str(uuid.uuid4()),"model_key":"macro_direction","model_version":f"v{number}","training_run_id":run_id,"dataset_id":manifest["dataset_id"],"model_type":"sklearn_logistic","lifecycle_state":"candidate","feature_schema_id":FEATURE_SCHEMA_ID,"feature_schema_version":FEATURE_SCHEMA_VERSION,"label_definition_id":LABEL_DEFINITION_ID,"label_definition_version":LABEL_DEFINITION_VERSION,"validation_metrics":metrics,"calibration_metrics":{"brier":metrics["brier"],"probability_calibrated":False},"artifact_blob":blob,"artifact_sha256":digest,"library_versions":{"python":platform.python_version(),"sklearn":sklearn.__version__}}
    saved=repo.create_model(model) or model
    result={"success":True,"method":"logistic_regression","requested_method":requested_method,"actual_method":"logistic_regression","n_samples":len(X),"dataset":manifest,"training_run":run,"model":{k:v for k,v in saved.items() if k!="artifact_blob"},"temporal_validation":folds,"cv_scores":[f["accuracy"] for f in folds],"cv_mean":metrics["accuracy"],"ts":now}
    _TRAINING_HISTORY=(_TRAINING_HISTORY+[result])[-10:]; return result

def get_trained_model(): return _TRAINED_MODEL
def set_trained_model(value):
    global _TRAINED_MODEL; _TRAINED_MODEL=value
def get_training_history(): return list(_TRAINING_HISTORY)
