from pathlib import Path

from backend import config
from backend.core import operator_auth


def _set_auth(monkeypatch, *, required=False, mode="paper", live_enabled=False, token="secret-token", jupiter=False):
    monkeypatch.setattr(config, "OPERATOR_AUTH_REQUIRED", required)
    monkeypatch.setattr(config, "EXECUTION_MODE", mode)
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", live_enabled)
    monkeypatch.setattr(config, "OPERATOR_API_TOKEN", token)
    monkeypatch.setattr(config, "ENABLE_DIRECT_JUPITER_SWAP", jupiter)


def test_live_capable_configuration_always_requires_operator_auth(monkeypatch):
    _set_auth(monkeypatch, required=False, mode="live", live_enabled=False)
    assert operator_auth.operator_auth_required() is True

    _set_auth(monkeypatch, required=False, mode="paper", live_enabled=True)
    assert operator_auth.operator_auth_required() is True


def test_paper_local_mode_preserves_existing_behavior_when_auth_disabled(monkeypatch):
    _set_auth(monkeypatch, required=False, mode="paper", live_enabled=False)
    assert operator_auth.operator_auth_required() is False
    assert operator_auth._authorize_token(None) is None


def test_missing_and_invalid_operator_tokens_are_rejected(monkeypatch):
    _set_auth(monkeypatch, required=True)

    status_code, detail = operator_auth._authorize_token(None)
    assert status_code == 401
    assert detail["code"] == "operator_auth_required"

    status_code, detail = operator_auth._authorize_token("Bearer wrong-token")
    assert status_code == 401
    assert detail["code"] == "operator_auth_invalid"


def test_valid_operator_token_is_accepted(monkeypatch):
    _set_auth(monkeypatch, required=True, token="expected-token")
    assert operator_auth._authorize_token("Bearer expected-token") is None


def test_required_auth_without_server_token_fails_closed(monkeypatch):
    _set_auth(monkeypatch, required=True, token="")
    status_code, detail = operator_auth._authorize_token("Bearer anything")
    assert status_code == 503
    assert detail["code"] == "operator_auth_not_configured"


def test_only_real_mutation_surfaces_are_protected():
    protected = [
        ("POST", "/api/execution/order"),
        ("POST", "/api/execution/conditional-order"),
        ("POST", "/api/execution/conditional-orders/evaluate"),
        ("DELETE", "/api/execution/conditional-order/abc"),
        ("POST", "/api/execution/smart-order"),
        ("POST", "/api/execution/jupiter/swap"),
        ("POST", "/api/ml/train/offline"),
        ("POST", "/api/ml/models/model-1/promote"),
        ("POST", "/api/ml/models/model-1/rollback"),
        ("POST", "/api/decisions"),
        ("POST", "/api/heuristics/evaluate"),
        ("POST", "/api/backtest/run"),
        ("POST", "/api/watchlists"),
        ("PUT", "/api/watchlists/one"),
        ("DELETE", "/api/watchlists/one"),
    ]
    for method, path in protected:
        assert operator_auth.is_operator_mutation(method, path), (method, path)

    public_or_read_only = [
        ("GET", "/api/execution/positions"),
        ("GET", "/api/ml/models"),
        ("POST", "/api/decisions/00000000-0000-0000-0000-000000000000/replay"),
        ("POST", "/api/risk/stress-test"),
        ("POST", "/api/allocation/rebalance-preview"),
        ("POST", "/api/scenario/run"),
        ("POST", "/api/execution/jupiter/quote"),
        ("GET", "/api/watchlists"),
    ]
    for method, path in public_or_read_only:
        assert not operator_auth.is_operator_mutation(method, path), (method, path)


def test_config_summary_never_exposes_operator_token(monkeypatch):
    monkeypatch.setattr(config, "OPERATOR_API_TOKEN", "super-secret")
    summary = config.summary()
    assert summary["operator_token_configured"] is True
    assert "OPERATOR_API_TOKEN" not in summary
    assert "super-secret" not in str(summary)


def test_direct_jupiter_swap_default_is_fail_closed_in_source():
    source = (Path(__file__).parents[1] / "backend" / "config.py").read_text()
    assert 'ENABLE_DIRECT_JUPITER_SWAP: bool = _env_bool("ENABLE_DIRECT_JUPITER_SWAP", False)' in source


def test_frontend_operator_token_is_session_only():
    script = (Path(__file__).parents[1] / "frontend" / "assets" / "operator_access.js").read_text()
    assert "sessionStorage" in script
    assert "localStorage" not in script
    assert "Authorization" in script
    assert "protectedMutation" in script


def test_main_installs_operator_boundary_and_client():
    source = (Path(__file__).parents[1] / "main.py").read_text()
    assert 'app.middleware("http")(enforce_operator_request)' in source
    assert "/frontend/assets/operator_access.js" in source
