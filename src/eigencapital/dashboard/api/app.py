"""EigenCapital Dashboard API — FastAPI application.

This is a READ-ONLY observability layer over the existing production trading system.
It cannot modify R4, risk limits, orders, positions, or qualification results.

Security (S7): every /api/v1 endpoint (live risk/position/evidence state) is
protected by a bearer API key and a per-IP rate limit. Set DASHBOARD_API_KEY
to a strong random value in production; set DASHBOARD_DISABLE_AUTH=1 only for
local development against localhost.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from eigencapital.dashboard.api.routes import (
    alerts,
    evidence,
    health,
    portfolio,
    reconciliation,
    risk,
    system,
)
from eigencapital.dashboard.streaming.events import router as streaming_router

app = FastAPI(
    title="EigenCapital Operations & Risk Dashboard",
    description="Read-only observability layer for EigenCapital trading system",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS — restrict to dashboard origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get(
            "DASHBOARD_CORS_ORIGINS",
            "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


# ── Auth + rate limiting (S7) ───────────────────────────────────────

_RATE_LIMITS: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 100  # requests per window per client IP


def _api_key() -> str:
    """Read the configured API key (env override each request)."""
    return os.environ.get("DASHBOARD_API_KEY", "dev-key-change-in-production")


@app.middleware("http")
async def require_api_key_and_rate_limit(request: Request, call_next: Any) -> Any:
    """Protect live-state endpoints with API key + per-IP rate limit.

    Only /api/v1/* HTTP routes expose live trading state; /healthz and docs
    stay open for load balancers and tooling. Set DASHBOARD_DISABLE_AUTH=1 to
    disable in local development only.
    """
    path = request.url.path
    if os.environ.get("DASHBOARD_DISABLE_AUTH") == "1" or not path.startswith("/api/v1"):
        return await call_next(request)

    # Rate limit (applied even before auth to blunt brute force)
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    _RATE_LIMITS[client_ip] = [t for t in _RATE_LIMITS[client_ip] if now - t < _RATE_LIMIT_WINDOW]
    if len(_RATE_LIMITS[client_ip]) >= _RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded"},
            headers={"Retry-After": str(_RATE_LIMIT_WINDOW)},
        )
    _RATE_LIMITS[client_ip].append(now)

    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {_api_key()}":
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "detail": "Missing or invalid API key"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


# Include routers
app.include_router(system.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
app.include_router(portfolio.router, prefix="/api/v1")
app.include_router(risk.router, prefix="/api/v1")
app.include_router(evidence.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(reconciliation.router, prefix="/api/v1")
app.include_router(streaming_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Health check endpoint for load balancers."""
    return {"status": "ok"}


@app.get("/")
async def root() -> dict[str, Any]:
    """Dashboard API root."""
    return {
        "name": "EigenCapital Operations & Risk Dashboard",
        "version": "0.1.0",
        "read_only": True,
        "docs": "/api/docs",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/api/v1")
async def api_v1_root() -> dict[str, Any]:
    """API v1 root."""
    return {
        "version": "v1",
        "endpoints": [
            "/api/v1/system/health",
            "/api/v1/system/build",
            "/api/v1/system/info",
            "/api/v1/health",
            "/api/v1/health/authorization",
            "/api/v1/health/watchdog",
            "/api/v1/portfolio/account",
            "/api/v1/portfolio/positions",
            "/api/v1/portfolio/summary",
            "/api/v1/risk",
            "/api/v1/risk/envelope",
            "/api/v1/evidence/events",
            "/api/v1/evidence/qualification",
            "/api/v1/evidence/shadow-reduced",
            "/api/v1/alerts",
        ],
        "read_only": True,
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler — never expose stack traces to browser."""
    import logging

    logging.exception("Unhandled exception: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred",
            "subsystem": "dashboard_api",
            "timestamp": datetime.now(UTC).isoformat(),
        },
        headers={
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
            "Access-Control-Allow-Credentials": "true",
        },
    )
