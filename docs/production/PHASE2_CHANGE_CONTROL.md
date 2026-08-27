# Phase 2 Change Control

**Effective:** 2026-08-27  
**Purpose:** Protect the R4 economic experiment from becoming "we saw something we didn't like → changed the system → declared improvement."

## Core Rule

> **R4 remains frozen until the evidence window is complete.**

The repository is now in measurement mode. The next valuable commit is a qualification report from untouched live data, not another feature.

---

## What Is Allowed

| Category | Examples |
|----------|----------|
| **Safety bug fixes** | Fixes that violate safety invariants |
| **Infrastructure reliability** | Fixes to reconciliation, health, alerts |
| **Evidence/telemetry fixes** | Fixes to data collection accuracy |
| **Broker/execution correctness** | Fixes to order routing, fill handling |
| **Security fixes** | Any security vulnerability |
| **Observability fixes** | Logging, monitoring, dashboard accuracy |

## What Is NOT Allowed

| Category | Rationale |
|----------|-----------|
| Changing R4 parameters | Would invalidate the experiment |
| Changing signal logic | Would invalidate the experiment |
| Changing cadence | Would invalidate the experiment |
| Changing universe | Would invalidate the experiment |
| Changing position sizing | Would invalidate the experiment |
| Adding filters | Would invalidate the experiment |
| Optimizing SL | Would invalidate the experiment |
| Adding TP | Would invalidate the experiment |
| Changing exits | Would invalidate the experiment |
| Promoting capital | Requires evidence gate |
| Changing evidence window | Would invalidate the experiment |

---

## Phase 2 Exit Gate

### 🟢 PASS

**Criteria:**
- Live execution is faithful to research expectations
- Risk containment works as designed
- Operational reliability demonstrated
- Live trade economics sufficiently consistent with research
- Evidence maturity level ≥ E4

**Result:** Proceed to controlled scaling (Phase 3).

### 🟡 CONDITIONAL

**Criteria:**
- Infrastructure is sound
- Economic evidence is still inconclusive
- Evidence maturity level < E4

**Result:** Continue collecting data.

### 🔴 FAIL / PAUSE

**Triggers:**
- Uncontrolled loss
- SL protection failure
- Reconciliation failure
- Authorization bypass
- Unexplained P&L divergence
- Materially degraded live expectancy
- Execution costs destroying the modeled edge
- Portfolio risk materially exceeding assumptions

**Result:** Fix/research before further capital.

---

## Evidence Maturity Requirements

| Level | Minimum for Phase 2 |
|-------|---------------------|
| E0 | System started |
| E1 | 7+ days operational |
| E2 | 14+ days, 10+ trades |
| E3 | 21+ days, 20+ trades |
| E4 | 45+ days, 30+ trades, 30-day observations |
| E5 | 90+ days, 50+ trades, 3+ episodes |
| E6 | 120+ days, 80+ trades, 5+ episodes |

**Phase 2 PASS requires ≥ E4.**

---

## Qualification Report Schedule

| Frequency | Report |
|-----------|--------|
| Per trade closure | Dashboard snapshot |
| Daily | Dashboard review |
| Weekly | Qualification report |
| Monthly | Full forensic review |

---

## Governance

| Rule | Status |
|------|--------|
| R4 signal frozen | 🔒 LOCKED |
| R4 universe frozen | 🔒 LOCKED |
| R4 cadence frozen | 🔒 LOCKED |
| R4 sizing frozen | 🔒 LOCKED |
| R4 exit logic frozen | 🔒 LOCKED |
| R4 risk envelope frozen | 🔒 LOCKED |
| $5K maximum tier | 🔒 LOCKED |
| No optimization | 🔒 LOCKED |
| No capital promotion | 🔒 LOCKED |
| Evidence collection | 🟢 ACTIVE |
| Dashboard updates | 🟢 ACTIVE |
| Safety fixes | 🟢 ALLOWED |
| Infrastructure fixes | 🟢 ALLOWED |

---

## The Most Important Thing

> **The most valuable thing you can buy right now is time.**

Let R4 trade under the exact frozen rules. Let the evidence pipeline accumulate a genuinely untouched sample. Then perform the next forensic qualification report.

If that report says the live economics match the historical thesis, then you have something much more valuable than another 500 tests:

**Evidence that the strategy survives contact with the real market.**
