"""Correctness regressions for PR #20's audit/governance boundaries."""
from datetime import datetime, timezone

from backend.compute.decision_replay import replay_decision
from backend.compute.signal_attribution import attribution_summary, compute_signal_outcomes
from backend.ml.training import train_offline


def test_incomplete_legacy_decision_is_unavailable():
    result = replay_decision({"decision_ts": datetime.now(timezone.utc), "input_state": {}})
    assert result["status"] == "UNAVAILABLE"
    assert result["orders_submitted"] == 0 if "orders_submitted" in result else True


def test_unsupported_training_method_is_truthful():
    result = train_offline([], [], method="lightgbm")
    assert result["success"] is False
    assert result["requested_method"] == "lightgbm"
    assert result["actual_method"] is None


def test_signal_outcomes_are_never_synthesized():
    result = compute_signal_outcomes([{"id": "s1", "direction": "bullish"}])
    assert result["available"] is False
    assert result["outcomes"][0]["outcomes"] == {}
    summary = attribution_summary([{"id": "s1"}])
    assert summary["evaluated_count"] == 0
    assert summary["unevaluated_count"] == 1
    assert summary["hit_rate"] is None
