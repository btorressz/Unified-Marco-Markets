import asyncio

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend import config
from backend.core import operator_auth
from backend.core.mutation_policy import (
    MUTATION_POLICIES,
    MutationClass,
    classify_mutation,
    get_mutation_policy,
    mutation_route_inventory,
    validate_mutation_route_inventory,
)


def _set_auth(monkeypatch, *, required=False, mode="paper", live_enabled=False, token="secret-token"):
    monkeypatch.setattr(config, "OPERATOR_AUTH_REQUIRED", required)
    monkeypatch.setattr(config, "EXECUTION_MODE", mode)
    monkeypatch.setattr(config, "LIVE_EXECUTION_ENABLED", live_enabled)
    monkeypatch.setattr(config, "OPERATOR_API_TOKEN", token)


def _request(method: str, path: str, authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": headers,
            "client": ("test", 1234),
            "server": ("testserver", 80),
        }
    )


def test_real_application_mutation_inventory_is_complete():
    from main import app

    report = mutation_route_inventory(app)
    assert report["complete"] is True
    assert report["mutation_route_count"] == 31
    assert report["policy_count"] == 31
    assert report["classified_count"] == 31
    assert report["external_state_mutation_count"] == 15
    assert report["calculation_only_count"] == 16
    assert report["unclassified"] == []
    assert report["stale_registry_entries"] == []
    assert validate_mutation_route_inventory(app) == report


def test_every_policy_is_unique_and_has_a_reason():
    keys = [(row.method, row.path) for row in MUTATION_POLICIES]
    assert len(keys) == len(set(keys)) == 31
    assert all(row.reason.strip() for row in MUTATION_POLICIES)


def test_dynamic_paths_resolve_to_expected_security_class():
    cases = {
        ("DELETE", "/api/execution/conditional-order/abc-123"): MutationClass.EXTERNAL_STATE_MUTATION,
        ("POST", "/api/ml/models/model-1/promote"): MutationClass.EXTERNAL_STATE_MUTATION,
        ("POST", "/api/ml/models/model-1/rollback"): MutationClass.EXTERNAL_STATE_MUTATION,
        ("PUT", "/api/watchlists/one"): MutationClass.EXTERNAL_STATE_MUTATION,
        ("DELETE", "/api/watchlists/one"): MutationClass.EXTERNAL_STATE_MUTATION,
        ("POST", "/api/decisions/00000000-0000-0000-0000-000000000000/replay"): MutationClass.CALCULATION_ONLY,
        ("POST", "/api/decisions/00000000-0000-0000-0000-000000000000/counterfactual"): MutationClass.CALCULATION_ONLY,
        ("POST", "/api/decisions/00000000-0000-0000-0000-000000000000/sensitivity"): MutationClass.CALCULATION_ONLY,
    }
    for (method, path), expected in cases.items():
        policy = get_mutation_policy(method, path)
        assert policy is not None, (method, path)
        assert policy.classification == expected, (method, path)
        assert classify_mutation(method, path) == expected


def test_known_calculation_posts_remain_explicitly_unprotected():
    calculation_routes = [
        "/api/execution/jupiter/quote",
        "/api/risk/stress-test",
        "/api/risk/montecarlo/run",
        "/api/allocation/rebalance-preview",
        "/api/allocation/execution-preview",
        "/api/scenario/run",
        "/api/geopolitical/scenario-run",
        "/api/protection/preview",
        "/api/hedge/preview",
        "/api/slippage/estimate",
        "/api/replay/run",
        "/api/replay/trade-simulation",
        "/api/sandbox/run",
    ]
    for path in calculation_routes:
        assert classify_mutation("POST", path) == MutationClass.CALCULATION_ONLY
        assert operator_auth.is_operator_mutation("POST", path) is False


def test_unknown_mutating_route_fails_inventory_validation():
    app = FastAPI()

    @app.post("/api/new-dangerous-route")
    def new_dangerous_route():
        return {"unsafe": True}

    report = mutation_route_inventory(app)
    assert report["complete"] is False
    assert report["unclassified"] == [
        {"method": "POST", "path": "/api/new-dangerous-route"}
    ]
    with pytest.raises(RuntimeError, match="POST /api/new-dangerous-route"):
        validate_mutation_route_inventory(app, require_all_policies=False)


def test_runtime_blocks_unclassified_mutation_even_when_auth_disabled(monkeypatch):
    _set_auth(monkeypatch, required=False, mode="paper", live_enabled=False)
    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        return JSONResponse({"allowed": True})

    response = asyncio.run(
        operator_auth.enforce_operator_request(
            _request("POST", "/api/unclassified"),
            call_next,
        )
    )
    assert response.status_code == 403
    assert called is False
    assert b"unclassified_mutation" in response.body


def test_runtime_allows_calculation_only_post_without_operator_token(monkeypatch):
    _set_auth(monkeypatch, required=True, token="expected-token")
    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        return JSONResponse({"allowed": True})

    response = asyncio.run(
        operator_auth.enforce_operator_request(
            _request("POST", "/api/risk/stress-test"),
            call_next,
        )
    )
    assert response.status_code == 200
    assert called is True


def test_runtime_external_mutation_still_requires_operator_token_when_policy_active(monkeypatch):
    _set_auth(monkeypatch, required=True, token="expected-token")

    async def call_next(_request):
        return JSONResponse({"allowed": True})

    missing = asyncio.run(
        operator_auth.enforce_operator_request(
            _request("POST", "/api/execution/order"),
            call_next,
        )
    )
    assert missing.status_code == 401
    assert b"operator_auth_required" in missing.body

    valid = asyncio.run(
        operator_auth.enforce_operator_request(
            _request(
                "POST",
                "/api/execution/order",
                authorization="Bearer expected-token",
            ),
            call_next,
        )
    )
    assert valid.status_code == 200


def test_get_requests_do_not_require_mutation_classification(monkeypatch):
    _set_auth(monkeypatch, required=True)
    called = False

    async def call_next(_request):
        nonlocal called
        called = True
        return JSONResponse({"allowed": True})

    response = asyncio.run(
        operator_auth.enforce_operator_request(
            _request("GET", "/api/anything"),
            call_next,
        )
    )
    assert response.status_code == 200
    assert called is True
