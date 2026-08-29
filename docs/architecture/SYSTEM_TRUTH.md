# EigenCapital — System Truth Map

**STATUS: CURRENT** | Last updated: 2026-08-29

This document maps every critical concept to its authoritative implementation, downstream consumer, test coverage, and documentation. When documentation and code disagree, trace back here.

---

## Canonical Abstractions

### Market Availability
```
Authority:  core/market_schedule.py → MarketSchedule
Consumer:   MarketDataBridge, risk, execution, reconciliation
Tests:      tests/unit/core/test_market_schedule.py (35 tests)
Docs:       docs/architecture/DATA_INVARIANTS.md
Config:     configs/market_schedules/default.toml
```

### Data Quality
```
Authority:  core/data_quality.py → DataQualityAssessor
Consumer:   MarketDataBridge, dashboard (freshness assessment)
Tests:      tests/unit/core/test_data_quality.py (32 tests)
Docs:       docs/architecture/DATA_INVARIANTS.md
```

### Data Truth
```
Authority:  core/data_truth.py → TruthfulValue, TruthRegistry, TruthLevel
Consumer:   Dashboard, risk observation, health
Tests:      tests/unit/core/test_data_truth.py (38 tests)
Docs:       docs/architecture/DATA_INVARIANTS.md
```

### Market Data Bridge
```
Authority:  core/data_quality.py → MarketDataBridge, BridgeResult
Consumer:   Dashboard (freshness), risk observation
Tests:      tests/unit/core/test_integration.py (43 tests)
Docs:       docs/architecture/DATA_INVARIANTS.md
```

### No Silent Degradation
```
Authority:  core/no_silent_degradation.py → guard_*, DegradationViolation
Consumer:   All components (platform-wide invariant)
Tests:      tests/unit/core/test_integration.py
Docs:       docs/architecture/DATA_INVARIANTS.md
```

---

## Trading Pipeline

### R4 Strategy
```
Authority:  scripts/r4_rebalance_loop.py + strategies/
Consumer:   Risk boundary → execution → MT5
Tests:      tests/unit/production_qual/test_phase2_parity.py (34 tests)
Docs:       docs/production/PHASE_STATUS.md
FROZEN:     YES — no modifications permitted during Phase 2
```

### Risk Boundary
```
Authority:  live/risk.py + risk/checks/ + risk_observation.py
Consumer:   Execution boundary (orders must pass risk)
Tests:      tests/unit/risk/ + adversarial tests
Docs:       docs/production/RISK_ARCHITECTURE.md
Invariant:  Strategy → Risk → Execution (never Strategy → Execution)
```

### Trading Authorization
```
Authority:  live/health.py → HealthState + authorization
Consumer:   Execution boundary
Tests:      adversarial tests
Docs:       docs/production/RISK_ARCHITECTURE.md
```

### Reconciliation
```
Authority:  reconciliation/engine.py
Consumer:   Dashboard, health state, alerts
Tests:      tests/unit/dashboard/test_dashboard_contracts.py
Docs:       docs/production/OPERATIONS_RUNBOOK.md
```

### Evidence / Qualification
```
Authority:  production_qual/ (live_qualification, evidence_orchestrator)
Consumer:   Dashboard, Phase 2 governance
Tests:      tests/unit/production_qual/
Docs:       docs/production/PHASE2_GOVERNANCE.md
```

---

## Observability

### Dashboard API
```
Authority:  dashboard/api/routes/ + dashboard/schemas/
Consumer:   React frontend
Tests:      tests/unit/dashboard/test_dashboard_contracts.py (60 tests)
Docs:       docs/production/DASHBOARD_API.md
Invariant:  READ-ONLY — no POST/PUT/PATCH/DELETE routes
```

### Dashboard Frontend
```
Authority:  dashboard/src/
Consumer:   Operator
Tests:      TypeScript compilation (npx tsc --noEmit)
Docs:       docs/production/DASHBOARD_ARCHITECTURE.md
Invariant:  Observer, never controller
```

### WebSocket Streaming
```
Authority:  dashboard/streaming/events.py + dashboard/src/hooks/useLiveStream.ts
Consumer:   Dashboard frontend
Tests:      tests/unit/dashboard/test_websocket_resilience.py (21 tests)
Docs:       docs/production/DASHBOARD_ARCHITECTURE.md
```

---

## Data Flows

### Account State
```
Source:      MT5 broker (account_info)
Path:        MT5 → dashboard_state.py → API → React
Freshness:   DataQualityAssessor (delegated from _assess_freshness)
Truth:       AUTHORITATIVE when fresh, STALE when aged, UNAVAILABLE when missing
```

### Position Data
```
Source:      MT5 broker (positions_get)
Path:        MT5 → dashboard_state.py → API → React
Excursion:   RiskObserver (MAE/MFE tracking)
Persistence: reports/r4_loop/position_excursion.json
```

### Risk State
```
Source:      RiskObserver → reports/r4_loop/risk_state.json
Path:        JSON file → dashboard_state.py → API → React
Dimensions:  14 observation dimensions from risk_observation.py
```

### Health State
```
Source:      6 data sources (supervisor, broker, risk, reconciliation, build, evidence)
Path:        Multiple JSON files → dashboard_state.py → API → React
Dimensions:  6 health dimensions in HealthMatrix
```

### Market Schedule
```
Source:      configs/market_schedules/default.toml
Path:        TOML → load_schedules_from_file() → MarketSchedule
Consumer:    MarketDataBridge → DataQuality → DataTruth
```

---

## Configuration

### Production Config
```
Authority:  configs/production/config.toml
Loaded by:  eigencapital/config.py
Override:   .env (environment variables)
```

### Market Schedules
```
Authority:  configs/market_schedules/default.toml
Loaded by:  core/market_schedule.py → load_schedules_from_file()
25 instruments: 21 FX, 1 metals, 1 indices, 1 energy, 1 crypto
```

### Environment Variables
```
Authority:  .env.example (template)
Production: .env (never committed)
```

---

## Testing

### Test Counts (as of 2026-08-29)
```
Core models:         162 tests
Core data quality:    32 tests
Core data truth:      38 tests
Core integration:     43 tests
Core market schedule: 35 tests
Dashboard contracts:  60 tests
Dashboard MAE/MFE:    12 tests
Dashboard WebSocket:  21 tests
Dashboard adversarial:12 tests
Phase 2 parity:       34 tests
Fingerprint verifier: 12 tests
Total:              ~453+ tests
```

### R4 Parity
```
Authority:  tests/unit/production_qual/test_phase2_parity.py
Verified:   34/34 tests pass
Fingerprint: build_identity verified
```

---

## What Is Frozen

```
R4 strategy logic          — FROZEN
R4 parameters              — FROZEN
R4 universe                — FROZEN
R4 cadence                 — FROZEN
Risk envelope              — FROZEN
Shadow REDUCED             — FROZEN (shadow only)
MarketSchedule             — FROZEN
DataQuality                — FROZEN
DataTruth                  — FROZEN
NoSilentDegradation        — FROZEN
Dashboard v1               — FROZEN
```

## What Is NOT Frozen

```
Documentation              — Can be updated
Test coverage              — Can be expanded
Observability              — Can be improved
Evidence collection        — Active (Phase 2)
```
