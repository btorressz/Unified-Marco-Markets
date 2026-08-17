"""Focused regression coverage for the append-only final pre-trade decision boundary."""
from datetime import datetime, timezone
from pathlib import Path

from backend.compute.decision_replay import decision_hash, replay_decision
from backend.compute.execution_decision import combine_execution_decision, evaluate_data_guardrails


def _base_record():
    ts = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    return {
        "id": "00000000-0000-4000-8000-000000000022",
        "decision_ts": ts,
        "decision_type": "execution_pre_trade_final",
        "venue": "paper",
        "market": "SOL-PERP",
        "symbol": "SOL-PERP",
        "input_state": {
            "replay_inputs": {
                "heuristic": {"status": "not_used"},
                "ml": {"status": "not_used"},
                "allocation": {"status": "not_used"},
                "risk": {"status": "not_used"},
                "execution_boundary": {
                    "execution_mode": "paper",
                    "executor_available": True,
                    "agent": {"status": "not_used"},
                    "data": {
                        "execution_mode": "paper",
                        "live_execution_enabled": False,
                        "validation_reasons": [],
                        "price_found": True,
                        "fill_price": 150.0,
                        "order_notional": 150.0,
                        "max_order_notional": 100000.0,
                        "price_fresh": True,
                        "integrity_status": "OK",
                        "price_integrity_block_live": True,
                        "order": {"venue": "paper", "market": "SOL-PERP", "side": "buy", "size": 1.0},
                    },
                },
            }
        },
        "input_provenance": {"provenance_status": "partial"},
        "derived_state": {},
        "heuristic_result": {"status": "not_used"},
        "ml_result": {"status": "not_used"},
        "risk_result": {"status": "not_used"},
        "allocation_result": {"status": "not_used"},
        "execution_intent": {},
        "component_versions": {"execution_decision": "v1"},
        "config_snapshot": {},
        "final_decision": {"decision": "block", "action": "do_not_submit", "allowed": False},
    }


def test_replay_recomputes_final_decision_instead_of_copying_stored_target():
    record = _base_record()
    record["decision_hash"] = decision_hash(record)
    result = replay_decision(record)
    assert result["status"] == "MISMATCH"
    assert result["replayed_decision"]["final_decision"]["decision"] == "allow"
    assert result["replayed_decision"]["final_decision"]["allowed"] is True
    assert any(diff["path"].startswith("final_decision") for diff in result["differences"])


def test_final_combiner_blocks_risk_and_executor_unavailability():
    ts = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
    data = {"allowed": True, "reasons": [], "stage": "data_guardrails"}
    blocked = combine_execution_decision(
        data_result=data,
        risk_result={"approved": False, "reasons": ["risk limit"]},
        agent_result={"status": "not_used", "allowed": True},
        execution_mode="live",
        executor_available=True,
        as_of=ts,
    )
    assert blocked["decision"] == "block"
    assert blocked["stage"] == "risk"

    no_executor = combine_execution_decision(
        data_result=data,
        risk_result={"approved": True, "reasons": []},
        agent_result={"allowed": True, "reasons": []},
        execution_mode="live",
        executor_available=False,
        as_of=ts,
    )
    assert no_executor["decision"] == "block"
    assert no_executor["stage"] == "executor_availability"


def test_data_guardrails_are_deterministic_from_explicit_inputs():
    spec = {
        "execution_mode": "live",
        "live_execution_enabled": True,
        "validation_reasons": [],
        "price_found": True,
        "fill_price": 150.0,
        "order_notional": 150.0,
        "max_order_notional": 100000.0,
        "price_fresh": False,
        "integrity_status": "OK",
        "price_integrity_block_live": True,
    }
    result = evaluate_data_guardrails(spec)
    assert result["allowed"] is False
    assert result["stage"] == "price_freshness"


def test_router_records_final_audit_before_executor_calls():
    source = Path("backend/execution/router.py").read_text()
    boundary = source.index("ctx = self._emit_pre_trade_decision(", source.index("executor = self._get_live_executor"))
    paper_submit = source.index("self.paper.place_order", boundary)
    live_submit = source.index("executor.place_order", boundary)
    assert boundary < paper_submit
    assert boundary < live_submit
    assert '"decision_type": "execution_pre_trade_final"' in source
    assert '"admission_decision_id"' in source
