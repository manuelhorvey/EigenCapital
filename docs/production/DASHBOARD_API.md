# Dashboard API Documentation

Last updated: 2026-09-25 (completed — all `/api/v1` endpoints documented; see completeness note under Portfolio)

## Base URL
```
http://localhost:8080/api/v1
```

## Authentication
```
Authorization: Bearer <api_key>
```

All `/api/v1/*` routes require the bearer key (set via `DASHBOARD_API_KEY`) and are rate-limited per client IP (default 600 req/min, `DASHBOARD_RATE_LIMIT_MAX`). `/healthz` stays open for load balancers. `DASHBOARD_DISABLE_AUTH=1` disables auth for local development only. Only GET is allowed — the dashboard has no mutation endpoints (contract-tested).

## Endpoints

### System

#### GET /api/v1/system/health
Get overall system health status.

**Response:**
```json
{
  "status": "ok",
  "trading_authorization": "TRADING_AUTHORIZED",
  "timestamp": "2026-08-28T23:00:00Z"
}
```

#### GET /api/v1/system/build
Get build identity and verification status.

**Response:**
```json
{
  "git_head": "abc123...",
  "manifest_identity": "def456...",
  "config_fingerprint": "ghi789...",
  "loop_script_sha256": "jkl012...",
  "build_id": "R4-5K-20260826-v2",
  "verified": true,
  "drift_detected": false,
  "timestamp": "2026-08-28T23:00:00Z"
}
```

#### GET /api/v1/system/info
Get dashboard system information.

**Response:**
```json
{
  "dashboard_version": "0.1.0",
  "read_only": true,
  "can_submit_orders": false,
  "can_modify_r4": false,
  "can_modify_risk_limits": false,
  "can_activate_reduced": false
}
```

### Health

#### GET /api/v1/health
Get system health with all dimensions.

**Response:**
```json
{
  "overall_state": "HEALTHY",
  "trading_authorization": "TRADING_AUTHORIZED",
  "dimensions": [
    {
      "dimension": "supervisor",
      "state": "HEALTHY",
      "message": "Supervisor running (PID 407153)",
      "timestamp": "2026-09-25T06:00:00Z"
    }
  ],
  "blocking_dimensions": [],
  "timestamp": "2026-09-25T06:00:00Z",
  "freshness": "LIVE"
}
```

Dimension names: `supervisor`, `broker`, `risk_envelope`, `reconciliation`, `build`, `evidence`. States: `HEALTHY` / `DEGRADED` / `BLOCKED` / `CONTAINED` / `HALTED` (+ `UNKNOWN`). `overall_state` never uses risk vocabulary (`NORMAL` is not a health state, audit F-15).

### Portfolio

#### GET /api/v1/portfolio/account

**Query parameters (all endpoints):** none. Authentication: `Authorization: Bearer <DASHBOARD_API_KEY>` on every `/api/v1` route; unauthorized requests receive `401`.

> **Completeness note (2026-09-25):** this document previously omitted the alerts, reconciliation, health/authorization, health/watchdog, and portfolio/summary endpoints. All documented endpoints below match `src/eigencapital/dashboard/api/routes/` as of that date; the canonical machine-readable contract is the OpenAPI schema at `/api/docs`.

#### GET /api/v1/portfolio/account
Get account state snapshot.

**Response:**
```json
{
  "equity": 7009.98,
  "balance": 7011.54,
  "free_margin": 6500.00,
  "margin_used": 509.98,
  "margin_utilization": 0.07,
  "daily_pnl": -1.56,
  "timestamp": "2026-08-28T23:00:00Z"
}
```

#### GET /api/v1/portfolio/positions
Get all current positions.

**Response:**
```json
[
  {
    "ticket": 12345,
    "symbol": "XAUUSD",
    "direction": "SELL",
    "size": 0.01,
    "entry_price": 2500.0,
    "current_price": 2510.0,
    "unrealized_pnl": -10.0,
    "unrealized_pnl_pct": -0.004,
    "stop_loss": 2520.0,
    "distance_to_sl": 10.0,
    "mae": null,
    "mfe": null,
    "holding_time": "3h",
    "protected": true,
    "risk_state": "NORMAL",
    "attribution_state": null,
    "last_update": "2026-08-28T23:00:00Z",
    "freshness": "LIVE",
    "source": "mt5"
  }
]
```

`mae`/`mfe` are populated from `reports/r4_loop/position_excursion.json` when the RiskObserver excursion tracker has data for the ticket; `null` otherwise (never zero-fabricated).

#### GET /api/v1/portfolio/summary
Get portfolio-level aggregates derived from live positions.

**Response:**
```json
{
  "position_count": 2,
  "long_count": 1,
  "short_count": 1,
  "gross_exposure": 5010.0,
  "net_exposure": -10.0,
  "exposure_pct": 0.0019,
  "concentration": 0.498,
  "largest_position_symbol": "XAUUSD",
  "protected_count": 2,
  "unprotected_count": 0,
  "timestamp": "2026-08-28T23:00:00Z",
  "freshness": "LIVE"
}
```

`gross_exposure`/`net_exposure`/`concentration` are notional aggregates (`size × current_price`); `exposure_pct` is net exposure / equity.

### Risk

#### GET /api/v1/risk
Get current risk state with all observation dimensions.

**Response:**
```json
{
  "overall_level": "NORMAL",
  "observations": [
    {
      "dimension": "DRAWDOWN",
      "level": "NORMAL",
      "value": 0.02,
      "limit": 0.10,
      "message": "Drawdown within limits",
      "timestamp": "2026-08-28T23:00:00Z"
    }
  ],
  "any_critical": false,
  "any_warning": false,
  "timestamp": "2026-08-28T23:00:00Z"
}
```

### Health — Authorization & Watchdog

#### GET /api/v1/health/authorization
Trading authorization with real build-verification status.

**Response:**
```json
{
  "status": "TRADING_AUTHORIZED",
  "execution_mode": "live",
  "fingerprint_status": "VERIFIED",
  "timestamp": "2026-08-28T23:00:00Z"
}
```

`fingerprint_status` is `VERIFIED` only when `compute_build_identity().all_verified` is true, otherwise `DRIFT_DETECTED` (never fabricated).

#### GET /api/v1/health/watchdog
Watchdog state derived from trading authorization.

**Response:**
```json
{
  "state": "NORMAL",
  "previous_state": null,
  "authorize_trading": true,
  "authorize_flatten_on_reconnect": false,
  "reason": "HEALTHY",
  "last_transition": null,
  "evidence": {},
  "timestamp": "2026-08-28T23:00:00Z"
}
```

Note: this endpoint derives the watchdog label from the health state. The authoritative watchdog state machine lives in `src/eigencapital/live/watchdog.py` and is reported through `reports/r4_loop/` health files; when both views are needed, prefer the loop-authored files.

### Alerts

#### GET /api/v1/alerts?limit=50&severity=WARNING
Recent alerts, **newest first** (ordering fixed 2026-09-25, audit F-03).

**Query parameters:**
- `limit` (1–500, default 50) — maximum alerts to return
- `severity` (optional) — exact-match filter, e.g. `CRITICAL`, `WARNING`, `INFO`, `TRADE`

**Response:**
```json
[
  {
    "alert_id": "monitor-1756400000",
    "timestamp": "2026-09-25T06:00:00Z",
    "severity": "WARNING",
    "category": "SYSTEM",
    "event_type": "RISK",
    "message": "Daily loss budget at 60%",
    "event_id": null,
    "correlation_id": "corr-456",
    "state_transition": null,
    "consecutive_count": 1,
    "details": {},
    "acknowledged": false
  }
]
```

Notes: sources are `monitor.jsonl` and `alerts.jsonl`. Observed severities: `CRITICAL`, `WARNING` (`WARN` normalized), `INFO`, `TRADE` (trade-execution notification, not a system fault). `consecutive_count` is per-record — aggregate dedup is not implemented; `acknowledged` mirrors the source record — there is **no acknowledge API** (the dashboard is read-only).

### Reconciliation

#### GET /api/v1/reconciliation
Broker ↔ internal state comparison summary.

**Response:**
```json
{
  "overall_status": "CLEAN",
  "last_reconciliation": "2026-09-25T06:00:00Z",
  "checks_performed": 20,
  "checks_passed": 20,
  "checks_warning": 0,
  "checks_critical": 0,
  "checks_blocking": 0,
  "stale_positions": 0,
  "missing_fills": 0,
  "duplicate_orders": 0,
  "foreign_positions": 0,
  "timestamp": "2026-09-25T06:00:00Z",
  "freshness": "LIVE"
}
```

`overall_status` vocabulary: `CLEAN` (all positions matched) / `WARNING` (foreign or unmatched entries) / `NO_DATA` (no reconciliation run recorded) / `UNKNOWN`.

### Evidence

#### GET /api/v1/evidence/events?page=1&page_size=50
Get event timeline with pagination.

**Response:**
```json
{
  "events": [
    {
      "event_id": "uuid-123",
      "event_type": "ORDER SUBMITTED",
      "timestamp": "2026-08-28T23:00:00Z",
      "symbol": "XAUUSD",
      "ticket": null,
      "correlation_id": "corr-456",
      "severity": "INFO",
      "message": "Order submitted for XAUUSD",
      "details": {},
      "build_id": null,
      "strategy_version": null
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 50,
  "has_more": true,
  "oldest_timestamp": "2026-08-28T20:00:00Z",
  "newest_timestamp": "2026-08-28T23:00:00Z"
}
```

Events come from `reports/r4_loop/decisions.jsonl` (chronological); `oldest_timestamp` is the first event of the page and `newest_timestamp` the last.

#### GET /api/v1/evidence/qualification
Get Phase 2 qualification status.

**Response:**
```json
{
  "campaign_id": "R4-5K-20260826-v2",
  "overall_status": "COLLECTING",
  "evidence_insufficient": true,
  "evidence_maturity": {
    "e0_count": 100,
    "e1_count": 85,
    "e2_count": 0,
    "e3_count": 0,
    "e4_count": 0,
    "e5_count": 0,
    "e6_count": 0,
    "total_trades": 185,
    "open_trades": 2,
    "completed_lifecycles": 90,
    "observation_days": 3,
    "timestamp": "2026-08-28T23:00:00Z"
  },
  "gates": [
    {
      "gate_id": "A",
      "name": "Minimum Trades",
      "status": "SUFFICIENT",
      "details": {"required": 10, "current": 185},
      "timestamp": "2026-08-28T23:00:00Z"
    }
  ],
  "timestamp": "2026-08-28T23:00:00Z",
  "freshness": "LIVE"
}
```

**Gate status vocabulary:** `SUFFICIENT` (threshold met) / `COLLECTING` (accumulating). These are the only values the backend emits; `overall_status` uses the same vocabulary.

### WebSocket

#### ws://localhost:8080/ws/live
Authenticated real-time state updates (fixed 2026-09-25, audit F-04).

**Authentication (required):** pass the dashboard API key as `?token=<DASHBOARD_API_KEY>` (browsers cannot set headers on the WS handshake) or `Authorization: Bearer <key>`. Unauthorized handshakes are closed with code `1008` before any state is sent. `DASHBOARD_DISABLE_AUTH=1` bypasses auth for local development only.

**Transport:** ONE shared broadcaster task pushes a cached state snapshot (max age 5s) to all connected clients every 5 seconds — broker load does not scale with connection count. An initial snapshot is sent on connect; heartbeats every 30s.

**Messages received:**
```json
{
  "type": "state_update",
  "timestamp": "2026-08-28T23:00:00Z",
  "data": {
    "account": {...},
    "positions": [...],
    "health": {...},
    "risk": {...},
    "alerts": [...]
  }
}
```

Heartbeat and error frames:
```json
{"type": "heartbeat", "timestamp": "..."}
{"type": "error", "timestamp": "...", "error": "..."}
```

**Messages sent:**
```json
{"type": "request_state"}
{"type": "ping"}
```

#### GET /api/v1/events/stream (Server-Sent Events)
Same cached state snapshot as the WebSocket, streamed in SSE format (`event: state_update`, `event: heartbeat`). Protected by the same bearer-key middleware as every `/api/v1/*` route. Browsers' `EventSource` cannot set an `Authorization` header, so browser clients should use the WebSocket; the SSE stream is intended for scripts/curl that can send the header.

#### GET /api/v1/evidence/shadow-reduced
Get shadow REDUCED counterfactual data.

**Response:**
```json
{
  "mode": "SHADOW_ONLY",
  "observations": 120,
  "hypothetical_reductions": 14,
  "average_scale": 0.5,
  "actual_size": 0.02,
  "hypothetical_size": 0.01,
  "actual_pnl": -3.2,
  "hypothetical_pnl": -1.8,
  "counterfactual_difference": 1.4,
  "label": "Would Have Happened — NOT APPLIED LIVE",
  "timestamp": "2026-08-28T23:00:00Z",
  "freshness": "LIVE"
}
```

All fields are hypothetical/counterfactual; the label is always present and must be rendered with the data. When `shadow_reduced.json` is absent, counts are 0 and values are `null` with `freshness: UNKNOWN` — never presented as measured results.

---

## Error Semantics

| Condition | Response |
|---|---|
| Missing/invalid key on `/api/v1/*` | `401` with `WWW-Authenticate: Bearer` |
| Rate limit exceeded | `429` with `Retry-After: 60` |
| Risk enforcement module unavailable (`/risk/envelope`) | `503` with structured error detail — **not** hardcoded defaults |
| Unhandled server error | `500` with generic message (no stack traces reach the browser) |
| Backend data absent | Endpoint returns its documented empty/UNKNOWN fallback; freshness is `UNKNOWN`, never fake `LIVE` |
