# EigenCapital Dashboard Architecture

## Overview

The EigenCapital Operations & Risk Console is a **read-only observability layer** over the existing production trading system. It provides real-time visibility into system health, risk state, positions, reconciliation, evidence, and qualification status.

**Critical constraint:** The dashboard is READ-ONLY. It cannot modify R4, risk limits, orders, positions, or qualification results. A dashboard outage must NOT affect trading operations.

## Architecture

```text
                    ┌─────────────────────────┐
                    │       React + Vite       │
                    │       TypeScript         │
                    └────────────┬────────────┘
                                 │
                    REST / WebSocket / SSE
                                 │
                    ┌────────────▼────────────┐
                    │        FastAPI           │
                    │     Dashboard API        │
                    │      (Read Adapter)      │
                    └────────────┬────────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          │                      │                      │
    Live State              Evidence Store         Event Ledger
          │                      │                      │
    ┌─────┴─────┐         ┌─────┴─────┐         ┌─────┴─────┐
    │ MT5 State │         │ Qual Data │         │ Events   │
    │ Health    │         │ Reports   │         │ Alerts   │
    │ Risk Obs  │         │ Attribution│        │ Decisions│
    │ Positions │         │            │         │          │
    └─────┬─────┘         └─────┬─────┘         └─────┬─────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                  ┌──────────────▼──────────────┐
                  │ EigenCapital Production     │
                  │ System (Source of Truth)    │
                  └─────────────────────────────┘
```

## Data Source Mapping

| Dashboard Metric | Source Module | Source Type |
|-----------------|---------------|-------------|
| Equity/Balance | MT5 via broker | Live state |
| Drawdown | `risk_observation.py` | RiskObservation |
| Daily Loss | `daily_loss.py` | DailyLossTracker |
| Position Count | MT5 via broker | Live state |
| Gross/Net Exposure | `risk_observation.py` | RiskObservation |
| Risk State | `risk_observation.py` | RiskState |
| Health State | `health.py` | SystemHealth |
| Trading Auth | `authorization.py` | LiveAuthorization |
| Reconciliation | `reconciliation/engine.py` | ReconciliationResult |
| Alerts | `structured_alerts.py` | AlertManager |
| Events | `production_qual/event_ledger.py` | EventLedger |
| Qualification | `production_qual/qualification.py` | QualificationResult |
| Attribution | `risk_attribution.py` | TradeAttribution |
| Build Identity | `build_pinning.py` | BuildIdentity |
| Watchdog | `watchdog.py` | WatchDecision |

## API Endpoints

### System
- `GET /api/v1/system/health` — Overall system health
- `GET /api/v1/system/authorization` — Trading authorization status
- `GET /api/v1/system/build` — Build identity and verification
- `GET /api/v1/system/watchdog` — Watchdog state

### Portfolio
- `GET /api/v1/portfolio/account` — Account equity, margin, P&L
- `GET /api/v1/portfolio/positions` — All positions with risk state
- `GET /api/v1/portfolio/positions/{ticket}` — Single position detail

### Risk
- `GET /api/v1/risk/observations` — All 14 risk dimensions
- `GET /api/v1/risk/envelope` — Risk limits configuration
- `GET /api/v1/risk/gates` — Current gate results
- `GET /api/v1/risk/attribution` — Trade attribution data

### Reconciliation
- `GET /api/v1/reconciliation/status` — Current reconciliation state
- `GET /api/v1/reconciliation/checks` — Recent reconciliation checks
- `GET /api/v1/reconciliation/discrepancies` — Active discrepancies

### Execution
- `GET /api/v1/execution/orders` — Recent orders
- `GET /api/v1/execution/fills` — Recent fills
- `GET /api/v1/execution/metrics` — Slippage, latency, fill rate

### Evidence
- `GET /api/v1/evidence/events` — Event timeline (paginated)
- `GET /api/v1/evidence/qualification` — Qualification status
- `GET /api/v1/evidence/maturity` — Evidence maturity E0-E6

### Alerts
- `GET /api/v1/alerts` — Active alerts
- `GET /api/v1/alerts/history` — Alert history

## Live Streaming

- WebSocket: `/ws/live` — Real-time account, position, risk, health updates
- SSE: `/api/v1/events/stream` — Event stream

## Security Model

- Authentication required (initial: API key)
- Read-only endpoints only
- No order submission endpoints
- No configuration modification endpoints
- No R4 parameter modification
- CORS restricted to dashboard origin

## Implementation Phases

### Phase B: Backend Read API
- FastAPI application structure
- Domain model adapters
- REST endpoints
- Pydantic schemas

### Phase C: Frontend Foundation
- React + Vite + TypeScript
- Routing and layout
- Theme and design system
- API client with TanStack Query

### Phase D: Core Dashboard
- Overview page
- Positions workspace
- Risk workspace
- Health workspace

### Phase E: Evidence & Qualification
- Event timeline
- Qualification dashboard
- Trade economics
- Shadow REDUCED panel

### Phase F: Live Streaming
- WebSocket integration
- Reconnect handling
- Freshness indicators

### Phase G: Validation
- Adversarial testing
- State accuracy verification

### Phase H: Hardening
- Security hardening
- Performance optimization
- Deployment
