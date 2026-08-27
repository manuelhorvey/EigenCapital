# Phase 2 Infrastructure Implementation Plan

**Status:** DRAFT — Awaiting approval before execution  
**Created:** 2026-08-26  
**Based on:** Architecture review of development prompt  
**Constraint:** Phase-2-safe — no R4 behavior changes, no strategy evolution

---

## Core Principle

> **Do not expand the strategy library or implement new risk behavior inside the same campaign that is validating frozen R4.**

Every item in this plan improves the platform without changing R4's intended behavior. The R4 qualification experiment remains untouched.

---

## Guardrails (Hard Rules for Any Coding Agent)

Before implementing ANY item in this plan, the coding agent must acknowledge:

```
DO NOT perform opportunistic refactors.
DO NOT alter R4 strategy behavior.
DO NOT alter R4 signal generation, universe, cadence, sizing, exits, or parameters.
DO NOT change production risk semantics unless explicitly designated as shadow-only.
DO NOT modify the Phase 2 qualification baseline.
DO require before/after behavioral parity tests for all frozen R4 pathways.
```

---

## Priority Structure

### P0 — Phase 2 Compatible (Implement Now)

These improve the platform without changing R4's intended behavior.

| # | Item | Purpose | Risk to R4 |
|---|---|---|---|
| 1 | Reconciliation Engine | Deterministic broker/internal state comparison | None — read-only |
| 2 | Continuous Risk Observation | OBSERVE/ALERT/CONTAIN/HALT state machine | None — observation only |
| 3 | Live State / Account State | Canonical account state snapshot | None — read-only |
| 4 | Event/Evidence Ledger | Immutable trade lifecycle events | None — append-only |
| 5 | Broker/Internal Consistency | Position attribution, fill verification | None — comparison only |
| 6 | Monitoring + Health States | Machine-readable system health | None — observation only |
| 7 | Alerting | Structured operator alerts | None — downstream of decisions |
| 8 | Execution Edge Cases | Partial fills, rejections, slippage handling | None — defensive |
| 9 | Failure/Recovery Instrumentation | Crash, disconnect, reconnect tracking | None — observability |
| 10 | Phase 2 Qualification Reporting | Evidence collection and reporting | None — analysis only |

### P1 — Shadow / Governance (Build, Don't Activate)

These build infrastructure for future capabilities without activating them.

| # | Item | Purpose | Risk to R4 |
|---|---|---|---|
| 11 | Shadow REDUCED Risk Engine | Feature-flagged REDUCED decision path | None — shadow only |
| 12 | Shadow Portfolio Risk Analytics | DD taper, concentration taper, leverage taper | None — shadow only |
| 13 | Scaling Governance Framework | Tier promotion machinery | None — promotion disabled |
| 14 | Capacity Monitoring | Position sizing headroom tracking | None — observation only |
| 15 | Operational Dashboards | Real-time system status display | None — visualization only |

### P2 — Later (After Phase 2 Verdict)

These are activated only after Phase 2 evidence gates pass.

| # | Item | Purpose | Depends On |
|---|---|---|---|
| 16 | Activate REDUCED Behavior | Use shadow REDUCED decisions live | Phase 2 pass |
| 17 | Capital Promotion | Scale from $5K to $10K+ | Phase 2 pass |
| 18 | Strategy Expansion | New strategies, signals, models | Phase 3 |
| 19 | New Alpha Research | Additional alpha sources | Phase 3 |
| 20 | Universe Expansion | Additional instruments | Phase 3 |

---

## Detailed Specifications

### P0-1: Reconciliation Engine

**Purpose:** Deterministic comparison between broker state and internal state.

**Architecture:**

```
Broker State (MT5)
    ↕
Execution State (fills, orders)
    ↕
Internal Position State (strategy's view)
    ↕
Portfolio State (aggregated exposure)
    ↕
Audit Ledger (immutable record)
```

**Checks to implement:**

| Check | Description | Severity |
|---|---|---|
| Missing fills | Order submitted but no fill recorded | CRITICAL |
| Unexpected positions | Position exists without corresponding order | CRITICAL |
| Quantity mismatch | Internal ≠ broker position size | CRITICAL |
| Side mismatch | Internal ≠ broker position direction | CRITICAL |
| Price mismatch | Fill price deviation beyond threshold | WARNING |
| Duplicate orders | Same order submitted multiple times | CRITICAL |
| Stale positions | Position unchanged for extended period | WARNING |
| Orphaned tickets | Ticket exists without position | WARNING |
| Foreign positions | Positions not created by R4 | CRITICAL |
| P&L discrepancy | Broker ≠ internal P&L calculation | WARNING |

**Self-healing classification:**

```python
class ReconciliationAction(str, Enum):
    SAFE_AUTOFIX = "SAFE_AUTOFIX"      # Can fix automatically
    REQUIRES_REVIEW = "REQUIRES_REVIEW" # Needs operator decision
    HALT = "HALT"                       # Stop trading immediately
```

**Implementation location:** `src/eigencapital/reconciliation/engine.py`

**Key principle:** Reconciliation must never silently "fix" something dangerous.

---

### P0-2: Continuous Risk Observation

**Purpose:** Machine-readable risk state that improves Phase 2 evidence collection.

**Architecture:**

```
Market Event
    ↓
AccountState
    ↓
PortfolioState
    ↓
RiskEvaluation
    ↓
OBSERVE / ALERT / CONTAIN / HALT
```

**Risk observation dimensions:**

| Dimension | What It Measures | Current Implementation |
|---|---|---|
| Drawdown velocity | Rate of equity decline | Partial (daily loss only) |
| Loss clustering | Simultaneous position losses | Not implemented |
| Correlation risk | Portfolio correlation exposure | Not implemented |
| Concentration risk | Single-instrument exposure | Partial (position limit) |
| Volatility regime | Market stress level | Partial (regime gate) |
| Execution quality | Fill vs signal quality | Not implemented |

**Key constraint:** This observes and reports. It does NOT change R4 sizing behavior.

---

### P0-4: Event/Evidence Ledger

**Purpose:** Canonical economic record for Phase 2 qualification.

**Event types:**

| Event | When | Key Fields |
|---|---|---|
| SignalEvent | R4 computes signal | symbol, direction, weight, regime |
| OrderIntent | Strategy wants to trade | symbol, side, quantity, reason |
| OrderSubmitted | Order sent to broker | ticket, timestamp, broker_ref |
| OrderAccepted | Broker accepts order | acceptance_time, status |
| Fill | Order filled | fill_price, fill_quantity, spread, slippage |
| PositionOpened | Position created | ticket, entry_price, notional |
| RiskObservation | Risk state snapshot | all risk dimensions |
| PriceObservation | Price update for position | bid, ask, spread, timestamp |
| RiskAction | Risk engine decision | decision, reason, checks |
| ExitIntent | Strategy wants to exit | ticket, reason |
| ExitSubmitted | Exit order sent | ticket, timestamp |
| ExitFill | Exit filled | fill_price, realized_pnl |
| PositionClosed | Position closed | final_pnl, holding_period |
| Reconciliation | State comparison | status, mismatches |

**Event envelope:**

```python
@dataclass(frozen=True)
class EventEnvelope:
    event_id: str              # UUID
    timestamp: str             # ISO 8601 UTC
    event_type: str            # EventType enum value
    strategy_version: str      # e.g., "R4-2026.08.25"
    build_id: str              # Git commit SHA
    config_fingerprint: str    # Hash of config
    account_id: str            # MT5 account
    tier: str                  # "T1-5K"
    symbol: str | None         # Instrument if applicable
    position_ticket: int | None
    ticket: str | None         # Order ticket
    correlation_id: str        # Links related events
    parent_event_id: str | None
    broker_reference: str | None
    state_transition: str | None
    payload: dict              # Event-specific data
```

**Implementation location:** `src/eigencapital/production_qual/event_ledger.py`

**Key principle:** Every event is immutable. A complete trade becomes reconstructable from events.

---

### P0-6: Monitoring + Health States

**Purpose:** Machine-readable system health for trading authorization.

**Health dimensions:**

| Dimension | States | What It Checks |
|---|---|---|
| SYSTEM_HEALTH | HEALTHY / DEGRADED / BLOCKED | Process alive, resources OK |
| BROKER_HEALTH | HEALTHY / DEGRADED / BLOCKED | MT5 connection, data quality |
| DATA_HEALTH | HEALTHY / DEGRADED / BLOCKED | Price freshness, data completeness |
| POSITION_HEALTH | HEALTHY / DEGRADED / BLOCKED | Position count, attribution |
| RISK_HEALTH | HEALTHY / DEGRADED / BLOCKED | All risk gates |
| EXECUTION_HEALTH | HEALTHY / DEGRADED / BLOCKED | Fill rate, rejection rate |
| RECONCILIATION_HEALTH | HEALTHY / DEGRADED / BLOCKED | State consistency |
| STRATEGY_HEALTH | HEALTHY / DEGRADED / BLOCKED | Signal computation |
| EVIDENCE_HEALTH | HEALTHY / DEGRADED / BLOCKED | Ledger completeness |

**Trading authorization:**

```
Strategy says: BUY EURUSD
        ↓
Risk says: APPROVED
        ↓
Reconciliation says: HEALTHY
        ↓
Broker says: CONNECTED
        ↓
Watchdog says: NORMAL
        ↓
TRADING_AUTHORIZED → EXECUTE

Any critical layer says NO:
        ↓
TRADING_BLOCKED → no new exposure
```

**Implementation location:** `src/eigencapital/live/health.py`

---

### P1-11: Shadow REDUCED Risk Engine

**Purpose:** Feature-flagged REDUCED decision path for future activation.

**Taper paths to implement (shadow only):**

| Taper | Description | When Active |
|---|---|---|
| DD taper | Reduce sizing as drawdown increases | Shadow |
| Concentration taper | Reduce sizing as concentration increases | Shadow |
| Leverage taper | Reduce sizing as leverage increases | Shadow |
| Daily-loss taper | Reduce sizing as daily loss approaches limit | Shadow |

**Architecture:**

```
R4 LIVE
   │
   ├── Current approved sizing → LIVE (active)
   │
   └── REDUCED engine → SHADOW
                          ↓
                    collect evidence
```

**Key question to answer later:**

> Would REDUCED have improved R4's live risk-adjusted performance?

**Implementation location:** `src/eigencapital/risk/reduced_shadow.py`

**Key constraint:** Shadow engine runs in parallel, collects metrics, but its decisions are never applied to live orders.

---

### P1-13: Scaling Governance Framework

**Purpose:** Machinery for future capital promotion (promotion remains disabled).

**Tier progression:**

```
$5K
 ↓
Evidence Gate
 ↓
$10K
 ↓
Evidence Gate
 ↓
$25K
 ↓
Evidence Gate
 ↓
$50K
```

**Evidence gates (not activated):**

| Gate | Requirement | Status |
|---|---|---|
| Economic | Positive expectancy, all gates pass | Not evaluated |
| Risk | No uncontrolled DD breach | Not evaluated |
| Fidelity | Research and live behavior consistent | Not evaluated |
| Operational | Zero unresolved P0 incidents | Not evaluated |

**Implementation location:** `src/eigencapital/production_qual/scaling_governance.py`

**Key constraint:** The machinery exists. Promotion remains disabled until Phase 2 verdict.

---

## Architecture After Implementation

```
                 ┌──────────────────────┐
                 │   FROZEN R4 LIVE     │
                 │     $5K QUAL         │
                 └──────────┬───────────┘
                            │
                  REAL LIVE EVIDENCE
                            │
          ┌─────────────────┼─────────────────┐
          ↓                 ↓                 ↓
    EXECUTION          ECONOMICS          OPERATIONS
          │                 │                 │
          │   ┌─────────────┤                 │
          │   │ Event Ledger│                 │
          │   │ Reconcil.   │                 │
          │   │ Health      │                 │
          │   │ Monitoring  │                 │
          │   └─────────────┤                 │
          │                 │                 │
          └─────────────────┼─────────────────┘
                            ↓
                    PHASE 2 VERDICT
                            │
                 ┌──────────┴──────────┐
                 ↓                     ↓
              PASS                   FAIL
                 ↓                     ↓
          PHASE 3 SCALE         INVESTIGATE
                 │
          $5K → $10K → $25K
                 │
                 ↓
          CAPACITY DISCOVERY
                 │
                 ↓
          FUTURE STRATEGIES
```

---

## Implementation Order

### Week 1: Foundation

1. Event Ledger (P0-4) — immutable record foundation
2. Reconciliation Engine (P0-1) — state comparison
3. Health States (P0-6) — machine-readable health

### Week 2: Integration

4. Continuous Risk Observation (P0-2) — risk state machine
5. Broker/Internal Consistency (P0-5) — position attribution
6. Alerting (P0-7) — structured operator alerts

### Week 3: Hardening

7. Execution Edge Cases (P0-8) — partial fills, rejections
8. Failure/Recovery Instrumentation (P0-9) — crash/disconnect tracking
9. Phase 2 Qualification Reporting (P0-10) — evidence collection

### Week 4: Shadow Infrastructure

10. Shadow REDUCED Risk Engine (P1-11) — feature-flagged
11. Shadow Portfolio Risk Analytics (P1-12) — observation only
12. Scaling Governance Framework (P1-13) — machinery only

---

## Testing Requirements

For every implementation:

1. **Unit tests** — isolated component testing
2. **Integration tests** — component interaction testing
3. **Parity tests** — before/after behavioral verification for frozen R4 pathways
4. **Shadow tests** — verify shadow components don't affect live decisions

**Parity test example:**

```python
def test_r4_signal_unchanged():
    """Verify R4 signal computation is identical before and after infrastructure changes."""
    signal_before = compute_r4_signal(market_data, config)
    # ... infrastructure changes ...
    signal_after = compute_r4_signal(market_data, config)
    assert signal_before == signal_after
```

---

## Success Criteria

After implementation:

- [ ] All P0 items pass unit and integration tests
- [ ] R4 behavioral parity verified (no changes to live behavior)
- [ ] Event ledger captures all trade lifecycle events
- [ ] Reconciliation detects all mismatch types
- [ ] Health states correctly aggregate system status
- [ ] Shadow REDUCED engine collects metrics without affecting live decisions
- [ ] No regressions in existing Phase 2 evidence collection

---

## What This Plan Does NOT Do

- ❌ Change R4 signal generation
- ❌ Change R4 universe selection
- ❌ Change R4 sizing behavior
- ❌ Change R4 exit logic
- ❌ Add new strategies
- ❌ Add new instruments
- ❌ Activate capital scaling
- ❌ Activate REDUCED behavior live
- ❌ Modify Phase 2 qualification baseline

---

## References

- `docs/production/PHASE_STATUS.md` — Current phase status
- `docs/production/RISK_ARCHITECTURE.md` — Risk control documentation
- `docs/production/LIVE_TRADING.md` — Operational procedures
- `docs/production/OPERATIONS_RUNBOOK.md` — Failure procedures
- `src/eigencapital/execution/reconciliation.py` — Existing reconciliation (paper-only)
- `src/eigencapital/risk/engine.py` — Existing risk engine
- `src/eigencapital/live/watchdog.py` — Existing watchdog state machine
- `src/eigencapital/live/risk_enforcement.py` — Existing risk enforcement
