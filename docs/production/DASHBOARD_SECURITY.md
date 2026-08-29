# Dashboard Security Model

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

## Authentication

### V1: API Key Authentication
- API key required for all endpoints
- Key passed via `Authorization: Bearer <api_key>` header
- Key stored in environment variable `DASHBOARD_API_KEY`

### Future: OAuth2/OIDC
- Integration with identity provider
- Role-based access control
- Session management

## CORS Policy

```python
allow_origins=[
    "http://localhost:5173",   # Dev server
    "http://localhost:3000",   # Production build
    "http://127.0.0.1:5173",  # Dev server (loopback)
]
allow_methods=["GET"]         # Read-only
allow_headers=["*"]
```

## Secrets Handling

- No broker credentials in frontend
- No API keys in frontend bundles
- No filesystem paths exposed
- No internal state leaked

## Rate Limiting

- API endpoints: 100 requests/minute
- WebSocket: 1 connection per client
- SSE: 1 stream per client

## Audit Logging

All API access is logged with:
- Timestamp
- Client IP
- Endpoint accessed
- Response status
- User agent

## Deployment Security

### Network
- Dashboard runs on separate port (8080)
- No direct access to trading process
- Firewall rules restrict access

### Process Isolation
- Dashboard process independent from trading
- Dashboard outage does not affect trading
- Separate restart capabilities

### File System
- Dashboard has read-only access to:
  - `reports/` directory
  - `configs/` directory
- No write access to:
  - `src/` directory
  - Trading state files
  - Configuration files

## Vulnerability Management

- Regular dependency updates
- Security scanning with Snyk/Socket
- No known vulnerabilities in production
