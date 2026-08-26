"""Minimal operator authorization for state-changing API surfaces.

This is intentionally not an identity system. It provides one environment-backed
bearer token for trusted operator actions while leaving read-only research routes
and explicitly classified calculation-only POSTs unchanged. Secrets are never
logged or returned.
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend import config
from backend.core.mutation_policy import (
    MutationClass,
    classify_mutation,
    is_mutating_method,
)

_bearer = HTTPBearer(auto_error=False)


def operator_auth_required() -> bool:
    """Live-capable configurations always require operator authorization."""
    return bool(
        config.OPERATOR_AUTH_REQUIRED
        or config.EXECUTION_MODE == "live"
        or config.LIVE_EXECUTION_ENABLED
    )


def is_operator_mutation(method: str, path: str) -> bool:
    """Backward-compatible helper: true only for classified external mutations."""
    return classify_mutation(method, path) == MutationClass.EXTERNAL_STATE_MUTATION


def _auth_error(status_code: int, code: str, message: str) -> dict[str, Any]:
    return {
        "status": "blocked" if status_code in {403, 503} else "unauthorized",
        "code": code,
        "message": message,
    }


def _authorize_token(raw_authorization: str | None) -> tuple[int, dict[str, Any]] | None:
    if not operator_auth_required():
        return None

    configured = config.OPERATOR_API_TOKEN
    if not configured:
        return 503, _auth_error(
            503,
            "operator_auth_not_configured",
            "Operator authorization is required but no operator token is configured",
        )

    authorization = str(raw_authorization or "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return 401, _auth_error(
            401,
            "operator_auth_required",
            "Operator bearer token required",
        )

    if not secrets.compare_digest(token, configured):
        return 401, _auth_error(
            401,
            "operator_auth_invalid",
            "Invalid operator credentials",
        )
    return None


def require_operator(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Dependency form retained for targeted routes/tests and future reuse."""
    raw = None if credentials is None else f"{credentials.scheme} {credentials.credentials}"
    error = _authorize_token(raw)
    if error is None:
        return
    status_code, detail = error
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    raise HTTPException(status_code=status_code, detail=detail, headers=headers)


def _blocked_unclassified_mutation(method: str, path: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "detail": _auth_error(
                403,
                "unclassified_mutation",
                f"Mutation route is not classified by the authorization policy: {method} {path}",
            )
        },
    )


async def enforce_operator_request(request: Request, call_next):
    """Default-deny HTTP boundary for all state-capable request methods."""
    method = request.method.upper()
    path = request.url.path

    if not is_mutating_method(method):
        return await call_next(request)

    classification = classify_mutation(method, path)
    if classification is None:
        # Runtime defense in depth. Startup/test inventory validation should make
        # this unreachable for registered application routes, but a future route
        # must never become public merely because its policy entry was forgotten.
        return _blocked_unclassified_mutation(method, path)

    if classification == MutationClass.CALCULATION_ONLY:
        return await call_next(request)

    error = _authorize_token(request.headers.get("authorization"))
    if error is not None:
        status_code, detail = error
        headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
        return JSONResponse(
            status_code=status_code,
            content={"detail": detail},
            headers=headers,
        )

    # Jupiter has its own independent feature gate because the current adapter is
    # a prototype spot-swap path, not the hardened perp-style ExecutionRouter.
    if (
        method == "POST"
        and path == "/api/execution/jupiter/swap"
        and not config.ENABLE_DIRECT_JUPITER_SWAP
    ):
        return JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "status": "blocked",
                    "code": "direct_jupiter_swap_disabled",
                    "message": "Direct Jupiter swap execution is disabled by configuration",
                }
            },
        )

    return await call_next(request)
