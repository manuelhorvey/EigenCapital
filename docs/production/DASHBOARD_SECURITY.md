# Dashboard Security Model

**Status:** GOVERNING · **Verified:** 2026-09-25 against code (`src/eigencapital/dashboard/`, `dashboard/src/`)
**Rule:** every statement in this document must match implemented behavior. Claims that are not implemented are labeled *Not implemented* — never described as active.

## Overview

The EigenCapital Operations & Risk Dashboard is a **read-only observability layer**. It cannot modify R4, risk limits, orders, positions, or qualification results.

## Security Boundaries

### What the Dashboard CAN Do
- Read system health state
- Read risk observations
- Read position data from MT5
- Read reconciliation status
- Read event ledger
- Read qualification status
- Display alerts

### What the Dashboard CANNOT Do
- Submit orders
- Close positions
- Modify R4 parameters
- Modify risk limits
- Activate REDUCED mode
- Modify qualification results
- Access broker credentials
- Write to production state

## Authentication (implemented)

- Bearer API key required for all `/api/v1/*` routes (`app.py` middleware).
- Key source: environment variable `DASHBOARD_API_KEY`.
- **Default key is `dev-key-change-in-production`.** The default is for local
  development only; production deployments **must** set `DASHBOARD_API_KEY` to a
  secret value or the API is effectively open to anyone who can reach the port.
- Constant-time comparison (`secrets.compare_digest`) on both HTTP and
  WebSocket handshakes.
- `/healthz` and OpenAPI `/docs` remain unauthenticated for load balancers and
  tooling; they expose no trading state.
- `DASHBOARD_DISABLE_AUTH=1` bypasses authentication — **development only**,
  never set in production.
- WebSocket handshake authenticates via `?token=<key>` (browsers cannot set
  headers on handshakes) or the `Authorization: Bearer` header.

### Roadmap (not implemented)
- OAuth2/OIDC, role-based access control, session management.

## Frontend Key Handling (known limitation)

- The frontend reads `VITE_API_KEY` (see `.env.example`). Vite **inlines**
  `VITE_*` values into the JavaScript bundle, so the API key is recoverable by
  anyone who can load the dashboard assets.
- Mitigation: the production bundle only embeds a key if one is provided at
  build time; the development fallback key exists only in `vite dev` builds
  (`import.meta.env.DEV`), so production builds fail closed (401 → UI error
  state) instead of shipping a shared default.
- Until a server-side or runtime-injected key exists, **serve the dashboard
  only behind a trusted network or reverse proxy** that enforces access.
  This limitation is intentional and documented, not a hidden defect.

## CORS Policy (implemented)

```python
allow_origins=[  # env: DASHBOARD_CORS_ORIGINS (comma-separated)
    "http://localhost:5173",   # Vite dev server
    "http://localhost:3000",   # Static build preview
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
allow_methods=["GET"]         # Read-only
allow_headers=["*"]
allow_credentials=True
```

## Rate Limiting (implemented)

- **600 requests / 60 seconds / client IP** (`DASHBOARD_RATE_LIMIT_MAX`,
  `DASHBOARD_RATE_LIMIT_WINDOW` derived), applied *before* authentication to
  blunt brute force. Exceeding it returns `429` with `Retry-After`.
- WebSocket connection caps: **not implemented** (connections are
  authenticated; no per-client cap).

## Security Headers (implemented)

Set on every response: `X-Content-Type-Options: nosniff`,
`X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`,
`Referrer-Policy: strict-origin-when-cross-origin`,
`Cache-Control: no-store, no-cache, must-revalidate`.

## Secrets Handling

- Broker credentials live inside MT5 only; they never reach the frontend or
  the dashboard process.
- The dashboard API key **does** reach the frontend bundle when built with
  `VITE_API_KEY` (see *Frontend Key Handling* above).
- No `.env` file is committed (`.env` is git-ignored; `.env.example` carries
  placeholders only).

## Audit Logging

- **Not implemented.** Unhandled exceptions are logged; per-request access
  logs (timestamp, IP, endpoint, status, user agent) are **not** produced.
  Treat any statement elsewhere that access logging is active as stale.

## Deployment Guidance (recommended, not enforced by code)

- Run the dashboard on its own port (8080); never expose it directly to the
  internet — front it with a reverse proxy that enforces network access.
- The dashboard process is separate from the trading loop; a dashboard outage
  does not affect trading.
- Read-only *behavior* is enforced by contract (`docs/production/DASHBOARD_CONTRACT.md`
  §1/§4 single-writer rule) and by the API surface (GET-only CORS), not by
  OS-level filesystem permissions. The process user's filesystem rights are
  whatever the operator grants it.

## Vulnerability Management

- No automated dependency scanning is configured in this repository.
  Run `npm audit` (dashboard) and `pip-audit` (Python) before releases.
