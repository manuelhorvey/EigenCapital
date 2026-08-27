# Phase 2 Governance

This document establishes the formal governance rules for Phase 2: Live Economic Validation.

Last updated: 2026-08-27

## Current Status

**🟢 Infrastructure Track: COMPLETE**
**🟡 Live Economic Qualification: ACTIVE**
**🔒 Phase 3 Capital Scaling: LOCKED**
**⛔ Strategy Optimization: LOCKED**

## Core Principle

> **Phase 2 is an observation phase, not an optimization phase.**

The purpose is to establish whether the frozen R4 strategy and production execution stack behave as expected in live markets.

Any discovered weakness is recorded as evidence and converted into a separately preregistered research hypothesis. No live tuning is permitted.

## Infrastructure Track Complete

The following infrastructure has been validated and is now COMPLETE:

- ✅ Event/evidence ledger (immutable, reconstructable)
- ✅ Reconciliation engine (fail-closed, never silently repairs)
- ✅ Health-state model (9 dimensions, TRADING_AUTHORIZATION)
- ✅ Risk observation (observe/alert/contain only)
- ✅ Structured alerting (deduplicated, state-transition tied)
- ✅ Failure instrumentation (comprehensive tracking)
- ✅ Phase 2 qualification dataset (per-trade evidence)
- ✅ Phase 2 report generator (structured verdict)
- ✅ Evidence maturity framework (E0-E6)
- ✅ Parity tests (R4 frozen, 22/22 passing)
- ✅ Adversarial validation (40 hostile-condition tests)
- ✅ Long-duration infrastructure tests (memory, performance)

**The next valuable commit is a qualification report from another week/month of untouched live data, not another feature.**

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

## Evidence Maturity Framework

Because R4 is a slow-tail strategy, positive expectancy in a dashboard could be based on a tiny sample. This framework prevents premature conclusions.

### Evidence Levels

| Level | Name | Requirements | What It Proves |
|-------|------|--------------|----------------|
| **E0** | No Evidence | System just started | Nothing |
| **E1** | Operational | 7+ days running | System survives, no critical incidents |
| **E2** | Execution | 14+ days, 10+ trades | Fills match expectations, costs measured |
| **E3** | Early Economic | 21+ days, 20+ trades, 1+ episodes | First lifecycle data, holding period ongoing |
| **E4** | Full Holding | 45+ days, 30+ trades, 2+ episodes, 30-day observations | Edge expression timeline visible |
| **E5** | Replicated | 90+ days, 50+ trades, 3+ episodes, 40-day observations | Statistically meaningful, ready for promotion consideration |
| **E6** | Promotion Ready | 120+ days, 80+ trades, 5+ episodes, 40-day observations | Statistically defensible for scaling |

### Key Insight

> **PASS ≠ enough evidence.**

You can have:
- 🟢 all safety gates passing
- 🟢 zero critical incidents
- 🟢 perfect reconciliation
- 🟡 only 17 days of economic data

And the correct verdict is still:

> **INCONCLUSIVE — CONTINUE QUALIFICATION**

## Evidence Window

The qualification gate is based on **trade count + completed holding-period cohorts + regime coverage + operational exposure**, not simply "X days have passed."

Example:
- 40 days with 3 completed trades = insufficient evidence
- 40 days with 40 completed trades across multiple regimes = meaningful evidence
- 100 short-duration trades = insufficient for a slow-edge strategy

For a portfolio strategy with 19 positions, track three sample sizes:

```
N_positions (total entries)     — may be correlated
N_completed_trades              — individual trade lifecycles
N_independent_episodes          — statistically valid sample size
```

**Never overstate statistical evidence because correlated positions aren't independent observations.**

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

## Reporting: R4 Economic Truth Dashboard

The primary Phase 2 artifact is `scripts/r4_qualification_dashboard.py`.

This is NOT a generic monitoring dashboard. It is a dedicated qualification
source of truth that continuously answers:

> Does R4, exactly as frozen and deployed, produce a statistically
> credible positive net edge in live conditions while remaining
> inside its risk envelope?

The dashboard tracks:

| Section | What It Answers |
|---------|------------------|
| Execution | Are fills close to expected prices? |
| Entry | Do strong signals actually outperform weak ones? |
| Holding | How long until positive expectancy appears? |
| MAE/MFE | How far underwater do winners go? |
| Risk | Is the portfolio within risk bounds? |
| Exit | Are rotation/sign-flip exits adding value? |
| Operations | Does the system survive continuously? |
| Economics | Is realized net expectancy positive? |
| Qualification | GREEN/YELLOW/RED for each dimension |
| Capital | Current tier and promotion status |

**Run after every trade closure, daily as a snapshot, or on-demand.**

The next valuable commit is a qualification report from another week/month
of untouched live data, not another feature.

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
