# EigenCapital — Future Platform Architecture Roadmap

> "Don't make the system more complicated because sophisticated techniques exist. Make the system more capable only when evidence demonstrates that the additional capability solves a real problem."

**Status:** Reference document — not active development
**Last updated:** 2026-08-29
**Principle:** Evidence-driven capability growth, not feature accumulation

---

## Current State

EigenCapital is in **Phase 2 evidence-collection mode**. The architecture is frozen:

- R4 strategy: frozen
- Dashboard v1: frozen
- Infrastructure: frozen

All energy goes to: **ENTRY → EXECUTION → HOLD → MAE → MFE → EXIT → P&L → RISK → PORTFOLIO → OPERATIONS**

---

## Priority Ranking

### P0 — Build When Evidence Demands

| # | Infrastructure | What It Solves | Parity Required |
|---|---|---|---|
| 1 | Market/Venue Schedule | Asset-agnostic trading hours | Yes — current R4 must produce identical decisions |
| 2 | Data Quality Layer | Bad data → bad decisions | No — additive |
| 3 | No Silent Degradation contracts | UNKNOWN must never silently become 0 | No — contract enforcement |

### P1 — Build During Phase 2/3

| # | Infrastructure | What It Solves |
|---|---|---|
| 4 | Canonical RiskSnapshot | "What did EigenRisk believe at 14:37:22?" |
| 5 | Incident model | Mean time to recovery, recurring failures |
| 6 | Failure/Chaos Lab | "Does EigenCapital fail safely?" |
| 7 | Clock/time integrity | Time-jump protection |

### P2 — Build After R4 Qualification

| # | Infrastructure | What It Solves |
|---|---|---|
| 8 | Portfolio construction framework | Replaceable sizing infrastructure |
| 9 | Execution-cost model | Capital scaling requires accurate cost models |
| 10 | Strategy promotion framework | Evidence-gated capital scaling |

### P3 — Build Only If Evidence Supports

| # | Infrastructure | What It Solves |
|---|---|---|
| 11 | ML-ready dataset/model layer | Entry-quality prediction, regime classification |
| 12 | ML signal generation | Only if evidence supports it |
| 13 | HRP / advanced optimization | Only if simpler sizing proves insufficient |

---

## Detailed Architecture Proposals

### 1. Market/Venue Schedule

Stop thinking in "weekends." Think in: **Is this instrument currently tradable?**

```text
Instrument
    ↓
Venue
    ↓
TradingSchedule
    ↓
MarketState
```

**Separate four independent states:**

| State | Values | Example |
|---|---|---|
| Market availability | OPEN / CLOSED / MAINTENANCE / HALTED / UNKNOWN | BTC: OPEN on Saturday |
| Data availability | FRESH / STALE / MISSING / DISCONNECTED | BTC: STALE during maintenance |
| Broker availability | CONNECTED / DEGRADED / DISCONNECTED | MT5: CONNECTED |
| Strategy eligibility | ELIGIBLE / SUPPRESSED | R4: SUPPRESSED on weekends |

**Risk monitoring must continue even when market is closed.**

**Session types:**

```yaml
instrument: BTCUSD
market_schedule:
  type: CONTINUOUS_24_7
  timezone: UTC
  maintenance_windows:
    - day: Saturday
      start: "04:00"
      end: "04:30"

instrument: EURUSD
market_schedule:
  type: WEEKDAY
  timezone: UTC
```

**Daily risk must be explicit:**

```yaml
risk_periods:
  daily:
    type: CALENDAR
    timezone: UTC
  rolling_24h:
    type: ROLLING
    duration_hours: 24
```

No implicit midnight logic.

### 2. Data Quality Layer

```text
MarketDataQuality
├── freshness
├── completeness
├── continuity
├── spread quality
├── price plausibility
├── timestamp integrity
├── duplicate detection
├── outlier detection
└── source consistency
```

Produces: `Data Quality: 98/100` per instrument.

### 3. No Silent Degradation

Platform-wide contract:

```
UNKNOWN / MISSING / STALE / UNAVAILABLE / CORRUPT / INCONSISTENT
must NEVER silently become
0 / NORMAL / SAFE / VERIFIED
```

### 4. Canonical RiskSnapshot

Immutable record answering: "What did the system believe at time T?"

```text
RiskSnapshot
├── timestamp
├── equity, balance, drawdown
├── gross/net exposure, leverage
├── margin utilization, concentration
├── correlation clusters
├── daily/weekly loss
├── open positions, SL coverage
├── data quality, market state
├── risk envelope, authorization
```

### 5. Incident Model

```text
Incident
├── detected_at, severity, category
├── affected_component, affected_positions
├── detection_event, response, recovery
├── duration, root_cause, resolution
```

Answerable: "How many incidents? Which recur? What's MTTR?"

### 6. Failure/Chaos Lab

Permanent capability, not one-time exercise.

Test: broker disconnect, MT5 frozen, stale/wrong prices, missing/duplicate/partial fills, foreign positions, SL disappeared, equity unavailable, clock jump, system restart, disk full, corrupt JSONL, network partition, WebSocket failure, process crash.

Ask: **"Does EigenCapital fail safely?"** not "Does it work?"

### 7. Clock/Time Integrity

```text
ClockHealth
├── monotonicity
├── wall-clock offset
├── NTP synchronization
└── time-jump detection
```

### 8. Portfolio Construction (Evolutionary)

```
Phase A: Equal / clipped sizing
Phase B: Inverse-volatility
Phase C: Risk parity
Phase D: Correlation-aware sizing
Phase E: HRP
```

Each stage gets its own evidence campaign. Portfolio construction becomes replaceable infrastructure.

### 9. Execution Cost Model

```text
Expected P&L → Gross P&L → Spread → Commission → Slippage → Market impact → Net P&L
```

### 10. Strategy Promotion Framework

```text
$5K → Evidence Gate → $10K → Evidence Gate → $25K → ...
```

Promotion depends on: live expectancy, drawdown, execution fidelity, slippage, operational reliability, reconciliation health, risk containment, evidence maturity, strategy stability.

### 11. ML-Ready Data (Not ML Yet)

Begin with: **"Can we reconstruct every trade correctly?"**

```text
ENTRY → features at entry → signal → risk state → execution → MAE → MFE → holding period → exit → P&L
```

Availability timestamps prevent future leakage.

### 12. Strategy Independence Metric

When adding strategies, measure:

```
Strategy B
Sharpe: 0.9
Correlation with R4: 0.08  ← more valuable
```

vs:

```
Strategy C
Sharpe: 1.3
Correlation with R4: 0.92  ← less valuable
```

Building a **portfolio of sources of return**, not a collection of correlated backtests.

---

## The Overarching Principle

> Be boring, deterministic, observable, and extremely difficult to break while R4 generates evidence. That is much more valuable than adding another shiny capability.

**Don't modify R4. Don't add crypto. Don't add ML. Don't add HRP. Don't add features.**

**Collect evidence. Let the dataset speak. Build infrastructure only when evidence demonstrates a genuine deficiency.**
