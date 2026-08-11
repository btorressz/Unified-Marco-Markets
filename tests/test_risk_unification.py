from pathlib import Path

ROOT = Path(__file__).parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_risk_engine_defaults_to_configured_policy_and_shared_runtime():
    text = source("backend/compute/risk_engine.py")
    assert "configured_risk_policy()" in text
    assert "RiskRuntimeState" in text
    assert "self._sync_shared_state()" in text
    assert '"runtime_state": "shared"' in text


def test_risk_policy_exposes_one_configured_limit_source():
    text = source("backend/core/risk_policy.py")
    assert "max_leverage=float(config.MAX_LEVERAGE)" in text
    assert "max_margin_usage=float(config.MAX_MARGIN_USAGE)" in text
    assert "max_daily_loss=float(config.MAX_DAILY_LOSS)" in text
    assert "cooldown_seconds=int(config.COOLDOWN_SECONDS)" in text


def test_shared_runtime_tracks_throttle_daily_pnl_and_cooldown():
    text = source("backend/core/risk_policy.py")
    assert '"risk:last_action"' in text
    assert '"risk:daily_pnl:"' in text
    assert "get_risk_throttle()" in text
    assert "set_risk_throttle(" in text
    assert "incrbyfloat" in text


def test_realized_fill_pnl_updates_risk_state():
    text = source("backend/execution/paper_exec.py")
    assert 'realized_for_fill = float(accounting.get("realized_pnl"' in text
    assert "self.risk_engine.record_pnl(realized_for_fill)" in text


def test_execution_api_rejects_non_finite_numeric_inputs():
    text = source("backend/api/execution_routes.py")
    assert "math.isfinite(numeric)" in text
    assert '_require_finite("size", req.size)' in text
    assert '_require_finite("price", req.price)' in text
    assert '_require_finite("slippage", req.slippage_bps)' in text
    assert '_require_finite("total_size", req.total_size)' in text


def test_risk_engine_has_second_finite_guard():
    text = source("backend/compute/risk_engine.py")
    assert "def _finite_action_reasons" in text
    assert 'invalid_{field}: must be finite' in text


def test_live_new_exposure_fails_closed_on_idempotency_outage():
    text = source("backend/api/execution_routes.py")
    assert 'idempotency_status == "unavailable" and live_new_exposure' in text
    assert '"code": "live_idempotency_unavailable"' in text
    assert "status_code=503" in text


def test_live_new_exposure_fails_closed_on_intent_persistence_outage():
    text = source("backend/api/execution_routes.py")
    assert "if live_new_exposure and not intent:" in text
    assert '"code": "live_audit_persistence_unavailable"' in text
    assert "_state_store.release_idempotency(idempotency_key)" in text


def test_pure_live_reduction_retains_degraded_escape_path():
    text = source("backend/api/execution_routes.py")
    assert "def _is_live_risk_reduction" in text
    assert "risk_engine._is_reducing" in text
    assert "live_new_exposure = _exec_router.mode == \"live\" and not live_risk_reduction" in text


def test_no_operator_auth_or_new_execution_engine_added_in_this_pr():
    # Auth is intentionally a separate deployment-security concern.
    text = source("backend/api/execution_routes.py")
    assert "operator_auth" not in text
