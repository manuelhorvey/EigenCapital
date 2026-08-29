"""Dashboard API dependencies — authentication, authorization, and request context."""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# API Key authentication
API_KEY = os.environ.get("DASHBOARD_API_KEY", "dev-key-change-in-production")
security = HTTPBearer(auto_error=False)

# Rate limiting
_rate_limits: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 100  # requests per window


async def get_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security)],
) -> str:
    """Validate API key from Authorization header.

    In development, accepts the default key.
    In production, requires a valid API key.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


async def check_rate_limit(request: Request) -> None:
    """Check rate limit for client IP."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Clean old entries
    _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < RATE_LIMIT_WINDOW]

    if len(_rate_limits[client_ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(RATE_LIMIT_WINDOW)},
        )

    _rate_limits[client_ip].append(now)


async def get_request_context(request: Request) -> dict[str, Any]:
    """Get request context for audit logging."""
    return {
        "client_ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
        "method": request.method,
        "path": request.url.path,
    }


class DashboardUser:
    """Dashboard user context."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.is_authenticated = True
        self.role = "operator"  # V1: single role


async def get_current_user(
    api_key: str = Depends(get_api_key),
) -> DashboardUser:
    """Get current authenticated user."""
    return DashboardUser(api_key=api_key)
