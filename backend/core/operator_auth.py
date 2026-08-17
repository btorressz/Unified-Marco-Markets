"""Minimal operator authorization for state-changing API surfaces.

This is intentionally not an identity system. It provides one environment-backed
bearer token for trusted operator actions while leaving read-only research routes
unchanged. Secrets are never logged or returned.
"""
from __future__ import annotations

import re
import secrets
from typing import Any

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend import config

_bearer = HTTPBearer(auto_error=False)

# Exact external mutation surfaces. Read-only/calculation POSTs intentionally do
# not appear here so the research dashboard remains usable without operator auth.
_PROTECTED_EXACT: set[tuple[str, str]] = {
    ("POST", "/api/execution/order"),
    ("POST", "/api/execution/conditional-order"),
    ("POST", "/api/execution/conditional-orders/evaluate"),
    ("POST", "/api/execution/smart-order"),
    ("POST", "/api/execution/jupiter/swap"),
    ("POST", "/api/ml/train/offline"),
    ("POST", "/api/decisions"),
    ("POST", "/api/heuristics/evaluate"),
    ("POST", "/api/backtest/run"),
    ("POST", "/api/watchlists"),
}

_PROTECTED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("DELETE", re.compile(r"^/api/execution/conditional-order/[^/]+$")),
    ("POST", re.compile(r"^/api/ml/models/[^/]+/(?:promote|rollback)$")),
    ("PUT", re.compile(r"^/api/watchlists/[^/]+$")),
    ("DELETE", re.compile(r"^/api/watchlists/[^/]+$")),
)


def operator_auth_required() -> bool:
    """Live-capable configurations always require operator authorization."""
    return bool(
        config.OPERATOR_AUTH_REQUIRED
        or config.EXECUTION_MODE == "live"
        or config.LIVE_EXECUTION_ENABLED
    )


def is_operator_mutation(method: str, path: str) -> bool:
    method = str(method or "").upper()
    path = str(path or "")
    if (method, path) in _PROTECTED_EXACT:
        return True
    return any(method == expected and pattern.match(path) for expected, pattern in _PROTECTED_PATTERNS)


def _auth_error(status_code: int, code: str, message: str) -> dict[str, Any]:
    return {"status": "blocked" if status_code == 503 else "unauthorized", "code": code, "message": message}


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
        return 401, _auth_error(401, "operator_auth_required", "Operator bearer token required")

    if not secrets.compare_digest(token, configured):
        return 401, _auth_error(401, "operator_auth_invalid", "Invalid operator credentials")
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


async def enforce_operator_request(request: Request, call_next):
    """HTTP boundary for the small set of state-changing operator surfaces."""
    method = request.method.upper()
    path = request.url.path

    if not is_operator_mutation(method, path):
        return await call_next(request)

    error = _authorize_token(request.headers.get("authorization"))
    if error is not None:
        status_code, detail = error
        headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
        return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)

    # Jupiter has its own independent feature gate because the current adapter is
    # a prototype spot-swap path, not the hardened perp-style ExecutionRouter.
    if method == "POST" and path == "/api/execution/jupiter/swap" and not config.ENABLE_DIRECT_JUPITER_SWAP:
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
