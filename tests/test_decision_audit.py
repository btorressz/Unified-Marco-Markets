"""Focused regression coverage for the read-only decision audit boundary."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from backend.compute.decision_replay import decision_hash, replay_decision, structured_diff
from backend.data.repositories.decision_repo import DecisionRepository


def sample():
    return {
        "id": "00000000-0000-4000-8000-000000000017",
        "decision_ts": datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        "decision_type": "allocation_preview", "venue": "paper", "market": "BTC-USD",
        "input_state": {"shock_score": 2.1, "vol_regime": "high"},
        "input_provenance": {"source_ids": ["market"], "ingest_run_ids": ["run-1"]},
        "derived_state": {"risk_regime": "high"},
        "heuristic_result": {"heuristic_id": "shock_throttle", "version": 1, "fired": True},
        "ml_result": {"fallback_used": True, "model_version": "heuristic_fallback"},
        "risk_result": {"approved": False, "limits_applied": {"max_leverage": 3.0}},
        "allocation_result": {"proposed_size": 0},
        "execution_intent": {"execution_mode": "paper", "guardrail_result": "blocked"},
        "component_versions": {"heuristic": "shock_throttle:v1", "model_version": "heuristic_fallback"},
        "config_snapshot": {"risk": {"max_leverage": 3.0}},
        "final_decision": {"decision": "reject"},
    }


def test_canonical_hash_is_stable_and_sensitive():
    first = sample()
    reordered = {key: first[key] for key in reversed(first)}
    reordered["input_state"] = {"vol_regime": "high", "shock_score": 2.1}
    assert decision_hash(first) == decision_hash(reordered)
    changed = deepcopy(first); changed["input_state"]["shock_score"] = 1.0
    assert decision_hash(first) != decision_hash(changed)
    assert len(decision_hash(first)) == 64


def test_exact_replay_uses_stored_snapshot_and_submits_nothing():
    record = sample(); record["decision_hash"] = decision_hash(record)
    result = replay_decision(record, heuristic_versions={"shock_throttle:v1"})
    assert result["exact_match"] is True
    assert result["status"] == "EXACT MATCH"
    assert result["orders_submitted"] == 0
    assert result["replayed_decision"]["input_state"] == record["input_state"]
    assert result["replayed_decision"]["config_snapshot"] == record["config_snapshot"]


def test_replay_mismatch_has_structured_paths():
    record = sample(); record["decision_hash"] = decision_hash(record)
    def changed(value):
        value = deepcopy(value); value["risk_result"]["limits_applied"]["max_leverage"] = 2.0
        return value
    result = replay_decision(record, replay_builder=changed)
    assert result["status"] == "MISMATCH"
    assert result["differences"] == [{"path": "risk_result.limits_applied.max_leverage", "original": 3.0, "replay": 2.0}]


def test_missing_exact_versions_fail_honestly():
    record = sample(); record["decision_hash"] = decision_hash(record)
    result = replay_decision(record, heuristic_versions={"shock_throttle:v2"})
    assert result["replay_status"] == "unavailable"
    governed = deepcopy(record)
    governed["ml_result"] = {"model_id": "model-1", "artifact_sha256": "a" * 64, "fallback_used": False}
    governed["decision_hash"] = decision_hash(governed)
    result = replay_decision(governed, model_loader=lambda _model_id: None)
    assert result["replay_status"] == "unavailable"
    assert "model unavailable" in result["reason"]


def test_repository_persists_all_audit_sections(monkeypatch):
    captured = {}
    class DB:
        @staticmethod
        def execute_returning(sql, params): captured.update(sql=sql, params=params); return {"id": sample()["id"]}
    import backend.data.repositories.decision_repo as module
    monkeypatch.setattr(module, "_db", lambda: DB)
    row = sample(); row["decision_hash"] = decision_hash(row)
    DecisionRepository().create(row)
    for field in ("input_provenance", "component_versions", "config_snapshot", "decision_hash"):
        assert field in captured["sql"]


def test_replay_module_has_no_execution_or_live_state_dependency():
    source = Path("backend/compute/decision_replay.py").read_text()
    assert "backend.execution" not in source
    assert "from backend.core.state_store" not in source
    assert "from backend.core.redis_runtime" not in source


def test_frontend_exposes_audit_and_replay_language():
    text = "\n".join(Path(path).read_text() for path in ("frontend/index.html", "frontend/assets/ui.js"))
    for phrase in ("Decision Audit", "Replay Decision", "EXACT MATCH", "MISMATCH", "RESEARCH / AUDIT ONLY"):
        assert phrase in text
