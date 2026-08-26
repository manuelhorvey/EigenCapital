# Phase 2 Governance

This document establishes the formal governance rules for Phase 2: Live Economic Validation.

Last updated: 2026-08-26

## Core Principle

> **Phase 2 is an observation phase, not an optimization phase.**

The purpose is to establish whether the frozen R4 strategy and production execution stack behave as expected in live markets.

Any discovered weakness is recorded as evidence and converted into a separately preregistered research hypothesis. No live tuning is permitted.

## Execution Order

**2A → 2F first, 2B/2C/2D/2G concurrently as data accumulates.**

Do not spend 30 days interpreting profitability if later you discover execution or reconciliation data was incomplete.

## Data Integrity Requirement

Every live position must be reconstructable end-to-end:

```
SIGNAL
  ↓
TARGET
  ↓
ORDER
  ↓
REQUEST
  ↓
FILL
  ↓
LIVE POSITION
  ↓
MAE/MFE
  ↓
RISK STATE
  ↓
EXIT DECISION
  ↓
EXIT FILL
  ↓
REALIZED P&L
  ↓
PORTFOLIO IMPACT
```

Every transition needs a timestamp and immutable audit record.

## Evidence Window

The qualification gate is based on **trade count + completed holding-period cohorts + regime coverage + operational exposure**, not simply "X days have passed."

Example:
- 40 days with 3 completed trades = insufficient evidence
- 40 days with 40 completed trades across multiple regimes = meaningful evidence
- 100 short-duration trades = insufficient for a slow-edge strategy

## Evidence Milestones

The system should be able to say `INSUFFICIENT_EVIDENCE` rather than forcing GREEN/YELLOW/RED prematurely.

### Minimum Evidence for Qualification

- Meaningful number of completed trades
- Sufficient exposure across regimes
- Sufficient holding-period observations (20-40+ day cohorts)
- Multiple weekly/monthly cycles
- At least one meaningful volatility transition
- Weekend/open-gap observations
- Execution statistics
- Zero unresolved P0 safety incidents
- Complete trade-level attribution

## Alert Framework

### 🔴 Safety Alert (Immediate)

Any unexpected condition:
- Foreign position detected
- Reconciliation mismatch
- Risk gate failure
- Watchdog containment
- Unexpected SL behavior
- Unauthorized order

### 🟡 Economic-Drift Alert (Investigate)

Something materially diverges from research:
- Slippage degradation
- Spread increase
- Holding period anomaly
- MAE/MFE outside bounds
- Win rate deviation
- Expectancy deviation
- Turnover anomaly

### 🔵 Evidence Milestone (Report)

- 10 completed trades
- 25 completed trades
- 50 completed trades
- First 20-day cohort completed
- First 40-day cohort completed
- First complete monthly cycle
- First major regime transition

Milestones trigger **reports, not parameter changes**.

## What NOT to Do

| Action | Status |
|---|---|
| Modify R4 signal | 🔒 FROZEN |
| Change universe | 🔒 FROZEN |
| Adjust sizing | 🔒 FROZEN |
| Add/remove instruments | 🔒 FROZEN |
| Change cadence | 🔒 FROZEN |
| Optimize parameters | 🔒 FROZEN |
| Raise capital tier | 🔒 FROZEN |
| Force regime | 🔒 FROZEN |
| Skip pre-flight | 🔒 FROZEN |

## What TO Do

| Action | Status |
|---|---|
| Collect evidence | 🟢 ACTIVE |
| Record all trades | 🟢 ACTIVE |
| Monitor risk gates | 🟢 ACTIVE |
| Track MAE/MFE | 🟢 ACTIVE |
| Measure execution quality | 🟢 ACTIVE |
| Update documentation | 🟢 ALLOWED |
| Fix safety defects | 🟢 ALLOWED (separately governed) |

## Strategic Rule

> **You're now in the part of the project where doing less is actually doing more.**

Let R4 trade. Let the evidence accumulate. Then let the evidence determine whether Phase 3 ever opens.

## Reporting

The qualification monitor should continuously produce:

- Live-vs-research execution comparison
- Entry-quality statistics
- Holding-period cohorts
- MAE/MFE distributions
- Catastrophic-SL statistics
- Exit attribution
- Portfolio correlation/concentration
- DD/daily-loss trajectory
- Execution friction
- Operational incidents
- Broker reconciliation status

## Implementation Priorities

### P0 — Phase 2 Compatible (Now)

| # | Item | Purpose |
|---|---|---|
| 1 | Reconciliation | Broker/internal state consistency |
| 2 | Continuous risk observation | OBSERVE/ALERT/CONTAIN/HALT |
| 3 | Live state/account state | End-to-end position reconstruction |
| 4 | Event/evidence ledger | Canonical economic record |
| 5 | Monitoring + health states | SYSTEM_HEALTH aggregation |
| 6 | Alerting | Safety/drift/milestone alerts |
| 7 | Execution edge-case handling | Partial fills, rejections |
| 8 | Failure/recovery instrumentation | Timestamped recovery records |
| 9 | Phase 2 qualification reporting | Continuous evidence reports |

### P1 — Phase 2 Shadow (Build, Don't Activate)

| # | Item | Purpose |
|---|---|---|
| 10 | Shadow REDUCED risk engine | Evidence collection only |
| 11 | Shadow portfolio risk analytics | Evidence collection only |
| 12 | Scaling governance framework | Phase 3 infrastructure |
| 13 | Capacity monitoring | Future tier readiness |
| 14 | Operational dashboards | Visibility |

### P2 — Phase 3+ (Later)

| # | Item | Purpose |
|---|---|---|
| 15 | Activate REDUCED behavior | After Phase 2 evidence |
| 16 | Capital promotion | After evidence gates |
| 17 | Strategy expansion | Phase 5 |
| 18 | New alpha research | Phase 5 |
| 19 | Universe expansion | Phase 5 |

### Explicit Constraints

> Do not perform opportunistic refactors.
> Do not alter R4 strategy behavior.
> Do not alter R4 signal generation, universe, cadence, sizing, exits, or parameters.
> Do not change production risk semantics unless explicitly designated as shadow-only.
> Do not modify the Phase 2 qualification baseline.

Required: Before/after behavioral parity tests for all frozen R4 pathways.

## Phase 3 Gate

Phase 3 (Capital Scaling) opens only when:

1. All evidence milestones achieved
2. Live net expectancy > 0
3. Confidence intervals don't contradict research
4. No unresolved safety incidents
5. Research and live behavior sufficiently consistent
6. Formal review and approval

Phase 3 machinery can exist. **Promotion remains disabled.**
