"""Minimal operator authorization for state-changing API surfaces.

This is intentionally not an identity system. It provides one environment-backed
bearer token for trusted operator actions while leaving read-only research routes
unchanged. Secrets are never logged or returned.
"""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend import config

_bearer = HTTPBearer(auto_error=False)


def operator_auth_required() -> bool:
    """Live-capable configurations always require operator authorization."""
    return bool(
        config.OPERATOR_AUTH_REQUIRED
        or config.EXECUTION_MODE == "live"
        or config.LIVE_EXECUTION_ENABLED
    )


def require_operator(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> None:
    """Authorize a state-changing operator request or fail closed."""
    if not operator_auth_required():
        return

    configured = config.OPERATOR_API_TOKEN
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "blocked",
                "code": "operator_auth_not_configured",
                "message": "Operator authorization is required but no operator token is configured",
            },
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "unauthorized",
                "code": "operator_auth_required",
                "message": "Operator bearer token required",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "unauthorized",
                "code": "operator_auth_invalid",
                "message": "Invalid operator credentials",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
