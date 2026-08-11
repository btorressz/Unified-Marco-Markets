from datetime import datetime, timedelta, timezone
from backend.compute.heuristic_performance import classification_metrics, evaluate_historical, reconstruct_context
from backend.compute.rules_engine import RulesEngine

T = datetime(2025, 1, 1, tzinfo=timezone.utc)
def row(hours, price): return {"ts": (T + timedelta(hours=hours)).isoformat(), "price": price}

def test_registry_metadata_and_backward_compatible_action():
    engine=RulesEngine(); assert len(engine.rules)==5
    assert all(r["id"] and r["version"]==1 and r["required_context"] and r["evaluation_type"] for r in engine.rules)
    action=engine.evaluate({"tariff_rate_of_change":6,"vol_regime":"high"})[0]
    assert action["rule_name"]=="tariff_vol_reduce" and action["rule_id"]=="tariff_vol_reduce"

def test_context_has_no_look_ahead():
    context,regime=reconstruct_context(T,index_history=[{"ts":T-timedelta(seconds=1),"rate_of_change":6,"shock_score":1},{"ts":T+timedelta(seconds=1),"rate_of_change":99,"shock_score":99}],regime_snapshots=[{"ts":T,"vol_regime":"high"},{"ts":T+timedelta(seconds=1),"vol_regime":"extreme"}],events=[{"ts":T+timedelta(seconds=1),"payload":{"carry_score":-1}}])
    assert context["tariff_rate_of_change"]==6 and context["vol_regime"]=="high" and "carry_score" not in context

def test_real_horizon_outcomes_and_missing_context():
    ticks=[row(0,100),row(1,90),row(4,80),row(24,70),row(168,60)]
    bundle={"market_ticks":ticks,"index_history":[{"ts":T,"rate_of_change":6,"shock_score":1}],"regime_snapshots":[{"ts":T,"vol_regime":"high","funding_regime":"normal","shock_state":"normal"}],"funding_ticks":[],"events":[]}
    result=evaluate_historical(bundle,start_ts=T,end_ts=T,venue="drift",market="SOL-PERP",symbol="SOL-PERP",heuristic_ids=["tariff_vol_reduce"],decision_interval_seconds=3600)
    report=result["heuristics"][0]; evaluation=result["evaluations"][0]
    assert report["evaluation_status"]=="validated" and evaluation["fired"]
    assert [evaluation["outcomes"][h]["price"] for h in ("1h","4h","24h","7d")]==[90,80,70,60]
    assert abs(evaluation["primary_return"] + .3) < 1e-12 and abs(evaluation["signed_primary_return"] - .3) < 1e-12
    missing=evaluate_historical(bundle,start_ts=T,end_ts=T,venue="drift",market="SOL-PERP",symbol="SOL-PERP",heuristic_ids=["negative_carry_reduce"])
    assert missing["heuristics"][0]["evaluation_status"]=="not_evaluable" and "carry_score" in missing["evaluations"][0]["missing_context"]

def test_confusion_and_brier():
    def r(fired,signed,confidence=None): return {"evaluation_status":"evaluable","primary_return":signed,"signed_primary_return":signed,"fired":fired,"directional_hit":signed>0 if fired else None,"confidence":confidence}
    metrics=classification_metrics([r(True,1,.8),r(True,-1,.7),r(False,-1,.2),r(False,1,.1)])
    assert (metrics["tp"],metrics["fp"],metrics["tn"],metrics["fn"])==(1,1,1,1)
    assert metrics["precision"]==metrics["recall"]==metrics["f1"]==metrics["directional_accuracy"]==.5
    assert abs(metrics["brier_score"] - ((.8-1)**2+.7**2+.2**2+(.1-1)**2)/4)<1e-12
