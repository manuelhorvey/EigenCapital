"""EigenCapital Dashboard API — FastAPI application.

This is a READ-ONLY observability layer over the existing production trading system.
It cannot modify R4, risk limits, orders, positions, or qualification results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
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
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
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
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
