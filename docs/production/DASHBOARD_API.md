# Dashboard API Documentation

## Base URL
```
http://localhost:8080/api/v1
```

## Authentication
```
Authorization: Bearer <api_key>
```

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
      "dimension": "SYSTEM_HEALTH",
      "state": "HEALTHY",
      "message": "System operating normally",
      "timestamp": "2026-08-28T23:00:00Z"
    }
  ],
  "blocking_dimensions": [],
  "timestamp": "2026-08-28T23:00:00Z"
}
```

### Portfolio

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
    "protected": true,
    "risk_state": "NORMAL",
    "last_update": "2026-08-28T23:00:00Z"
  }
]
```

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

### Evidence

#### GET /api/v1/evidence/events?page=1&page_size=50
Get event timeline with pagination.

**Response:**
```json
{
  "events": [
    {
      "event_id": "uuid-123",
      "event_type": "ORDER_SUBMITTED",
      "timestamp": "2026-08-28T23:00:00Z",
      "symbol": "XAUUSD",
      "correlation_id": "corr-456",
      "message": "Order submitted for XAUUSD"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 50,
  "has_more": true
}
```

#### GET /api/v1/evidence/qualification
Get Phase 2 qualification status.

**Response:**
```json
{
  "campaign_id": "R4-5K-20260826-v2",
  "overall_status": "INSUFFICIENT",
  "evidence_insufficient": true,
  "evidence_maturity": {
    "e0_count": 100,
    "e1_count": 85,
    "observation_days": 3
  },
  "timestamp": "2026-08-28T23:00:00Z"
}
```

### WebSocket

#### ws://localhost:8080/ws/live
Real-time state updates.

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

**Messages sent:**
```json
{"type": "request_state"}
{"type": "ping"}
```
