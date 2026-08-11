from datetime import datetime,timedelta,timezone
import copy
import pytest
from backend.ml.dataset import create_dataset_manifest,LABEL_DEFINITION_ID,LABEL_DEFINITION_VERSION
from backend.ml.feature_store import build_features,FEATURE_SCHEMA_ID,FEATURE_SCHEMA_VERSION
from backend.ml.governance import serialize_artifact,verify_artifact,deserialize_artifact,set_repository,promote,rollback,model_health
from backend.ml.training import train_offline,set_trained_model
from backend.ml.inference import predict

class MemoryRepo:
 def __init__(self):self.datasets=[];self.runs=[];self.models=[];self.predictions=[]
 def save_dataset(self,x):
  if not any(d['dataset_hash']==x['dataset_hash'] for d in self.datasets):self.datasets.append(copy.deepcopy(x))
  return x
 def save_training_run(self,x):self.runs.append(copy.deepcopy(x));return x
 def create_model(self,x):
  if any(m['model_version']==x['model_version'] for m in self.models):raise ValueError('immutable')
  self.models.append(copy.deepcopy(x));return x
 def list_models(self):return self.models
 def list_datasets(self):return self.datasets
 def list_runs(self):return self.runs
 def get_model(self,x):return next((m for m in self.models if m['id']==x or m['model_version']==x),None)
 def active_model(self):return next((m for m in self.models if m['lifecycle_state']=='active'),None)
 def transition(self,x,state,reason):
  if state=='active':
   for m in self.models:
    if m['lifecycle_state']=='active':m['lifecycle_state']='archived'
  m=self.get_model(x);m['lifecycle_state']=state;return m
 def save_prediction(self,x):self.predictions.append(x);return x
 def prediction_count(self,x):return sum(p.get('model_id')==x for p in self.predictions)

@pytest.fixture
def repo():
 r=MemoryRepo();set_repository(r);set_trained_model(None);return r

def samples(n=30):
 start=datetime(2025,1,1,tzinfo=timezone.utc); out=[]
 for i in range(n):out.append({'timestamp':(start+timedelta(hours=i)).isoformat(),'features':{'tariff_index':20+i,'shock_score':(-1)**i*.1}})
 return out

def labels(n=30):return [i%2 for i in range(n)]

def test_schema_labels_and_visible_defaults():
 f=build_features({'shock_score':None,'tariff_index':40})
 assert (f['feature_schema_id'],f['feature_schema_version'])==(FEATURE_SCHEMA_ID,FEATURE_SCHEMA_VERSION)
 assert (LABEL_DEFINITION_ID,LABEL_DEFINITION_VERSION)==('forward_direction',1)
 assert f['feature_provenance']['shock_abs']['status']=='derived'
 assert f['feature_provenance']['shock_score']['status']=='fallback'
 assert f['quality']['default_feature_count']>0

def test_dataset_sha_is_deterministic_and_temporal_order_required():
 a=create_dataset_manifest(samples(),labels());b=create_dataset_manifest(samples(),labels())
 assert a['dataset_hash']==b['dataset_hash'] and len(a['dataset_hash'])==64
 with pytest.raises(ValueError):create_dataset_manifest(list(reversed(samples())),labels())

def test_leak_free_temporal_pipeline_and_candidate(repo):
 pytest.importorskip('sklearn')
 result=train_offline(samples(),labels())
 assert result['success'] and result['model']['lifecycle_state']=='candidate'
 assert all(f['train_end']<f['validation_start'] for f in result['temporal_validation'])
 artifact=deserialize_artifact(repo.models[0]['artifact_blob'],repo.models[0]['artifact_sha256'])
 assert list(artifact['pipeline'].named_steps)==['scaler','model']
 assert not hasattr(artifact['pipeline'].named_steps['scaler'],'mean_') is False

def test_artifact_promotion_rollback_and_one_active(repo):
 pytest.importorskip('sklearn')
 train_offline(samples(),labels()); train_offline(samples(),labels())
 assert [m['model_version'] for m in repo.models]==['v1','v2']
 blob,digest=serialize_artifact({'trusted':True});assert verify_artifact(blob,digest) and not verify_artifact(blob+b'x',digest)
 promote(repo.models[0]['id'],'reviewed');assert len([m for m in repo.models if m['lifecycle_state']=='active'])==1
 promote(repo.models[1]['id'],'reviewed');assert repo.models[0]['lifecycle_state']=='archived'
 rollback(repo.models[0]['id'],'operator rollback');assert repo.models[0]['lifecycle_state']=='active' and repo.models[1]['lifecycle_state']=='archived'

def test_restart_safe_prediction_provenance_and_health_is_read_only(repo):
 pytest.importorskip('sklearn')
 train_offline(samples(),labels());promote(repo.models[0]['id'],'reviewed');set_trained_model(None)
 before=repo.models[0]['lifecycle_state'];p=predict(samples()[0]['features'],timestamp=samples()[0]['timestamp'])
 assert not p['fallback_used'] and 'confidence' not in p and p['prediction_strength']==pytest.approx(abs(p['probability']-.5)*2,abs=1e-4)
 assert repo.predictions and len(repo.predictions[0]['input_hash'])==64
 assert model_health()['status']=='healthy' and repo.models[0]['lifecycle_state']==before

def test_schema_and_bad_artifact_fallback(repo):
 pytest.importorskip('sklearn')
 train_offline(samples(),labels());m=repo.models[0];m['lifecycle_state']='active';m['feature_schema_version']=99
 assert predict(samples()[0]['features'])['fallback_reason']=='feature_schema_mismatch'
 m['feature_schema_version']=FEATURE_SCHEMA_VERSION;m['artifact_blob']=b'bad';set_trained_model(None)
 assert predict(samples()[0]['features'])['fallback_reason']=='artifact_integrity_failure'
