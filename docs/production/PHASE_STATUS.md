# EigenCapital Phase Status

Last updated: 2026-08-26

## Official Status

| Phase | Status | Description |
|---|---|---|
| Phase 1 | 🟢 COMPLETE | Production Hardening & Safety Qualification |
| Phase 2 | 🟡 ACTIVE | Live Economic Validation & Capacity Discovery |
| Phase 3 | 🔒 LOCKED | Capital Scaling (requires Phase 2 evidence gates) |

## Phase 1: Production Hardening & Safety Qualification ✅

**Completed:** 2026-08-26

| Deliverable | Status |
|---|---|
| Strategy/research foundation | ✅ Complete |
| Forensic audit | ✅ Complete |
| Risk architecture | ✅ Complete |
| Execution hardening | ✅ Complete |
| Platform portability | ✅ Architected |
| Failure/chaos testing | ✅ Substantially complete |
| $5K controlled deployment | 🟢 Active |
| Documentation synchronization | ✅ Complete |

## Phase 2: Live Economic Validation & Capacity Discovery 🟡

**Started:** 2026-08-26

### Objective

> Determine whether R4's backtested economic edge survives real execution, how the edge behaves through different regimes, and how much capital the strategy can actually deploy without destroying its economics or risk profile.

### Workstreams

| # | Workstream | Status | Timeline |
|---|---|---|---|
| 1 | Live-vs-research validation | 🟡 Collecting evidence | Ongoing |
| 2 | Entry validation | 🟡 Collecting evidence | Ongoing |
| 3 | Exit economics | 🟡 Collecting evidence | Ongoing |
| 4 | Risk dynamics | 🟡 Collecting evidence | Ongoing |
| 5 | Long-duration survival | 🟡 Collecting evidence | Ongoing |

### Workstream 1: Live-vs-Research Validation

Compare backtest → paper → shadow → $5K live.

| Metric | Source | Status |
|---|---|---|
| Entry price | Live fills | Collecting |
| Exit price | Live fills | Collecting |
| Spread | Broker data | Collecting |
| Slippage | Fill analysis | Collecting |
| Latency | Order timestamps | Collecting |
| Swap | Broker data | Collecting |
| Holding period | Position tracking | Collecting |
| MAE | Price tracking | Collecting |
| MFE | Price tracking | Collecting |
| Win/loss | P&L attribution | Collecting |
| Expectancy | Computed | Pending |
| Turnover | Order count | Collecting |
| Drawdown | Equity tracking | Collecting |

**Key question:** Is reality statistically consistent with the model?

### Workstream 2: Entry Validation

The forensic result was: "real edge, but slow edge."

| Question | Measurement | Status |
|---|---|---|
| Do entries routinely go underwater first? | MAE analysis | Pending |
| Does Q5 really carry the edge? | Quintile analysis | Pending |
| Should weak entries be filtered? | Entry quality ranking | Pending |
| Does volatility expansion damage entries? | Regime analysis | Pending |
| Are late momentum entries worse? | Timing analysis | Pending |
| Does entry quality differ by asset? | Cross-sectional | Pending |
| Does entry quality differ by regime? | Regime analysis | Pending |

**Rule:** First prove the problem exists live. Don't change entry yet.

### Workstream 3: Exit Economics

Validate R4's unconventional exit design:

| Exit Type | Measurement | Status |
|---|---|---|
| Rotation exits | Frequency, P&L impact | Collecting |
| Sign flips | Frequency, timing | Collecting |
| Regime exits | Frequency, P&L impact | Collecting |
| Holding duration | Distribution, edge expression | Collecting |
| Catastrophic SL activation | Frequency, causes | Collecting |

**Key question:** Does R4's lack of conventional TP preserve its convexity in live trading?

### Workstream 4: Risk Dynamics

Build live distribution of:

| Metric | Status |
|---|---|
| MAE distribution | Collecting |
| MFE distribution | Collecting |
| Loss velocity | Collecting |
| Recovery probability | Collecting |
| Portfolio DD | Collecting |
| Daily loss | Collecting |
| Correlation | Collecting |
| Cluster exposure | Collecting |
| Margin utilization | Collecting |
| Loss-at-SL | Collecting |
| Catastrophic-stop frequency | Collecting |

### Workstream 5: Long-duration Survival

The strategy needs 20-40+ days for its economics to express.

| Test | Status |
|---|---|
| Weekend operation | Pending (first weekend) |
| Month boundary | Pending |
| Economic events | Pending |
| Disconnects | Tested (auto-reconnect) |
| Restart recovery | Tested (persisted state) |
| Broker maintenance | Pending |
| Stale data | Tested (watchdog) |
| DST transitions | Pending |
| Prolonged positions | Collecting |
| Multiple rotations | Collecting |
| Large correlated moves | Pending |

## Phase 2 Exit Criteria

### Outcome A: R4 Validates → Phase 3 (Capital Scaling)

- [ ] Positive expectancy over 30+ days
- [ ] Expected holding period (20-40+ days) confirmed
- [ ] Acceptable MAE (within research bounds)
- [ ] Acceptable execution costs
- [ ] Reliable exits
- [ ] Risk controls work
- [ ] No serious operational failures

### Outcome B: R4 Works but Has Weaknesses → Research Campaign

- [ ] Identify specific weakness (e.g., Q1-Q4 entries destroy expectancy)
- [ ] Freeze live system
- [ ] Create offline preregistered experiment
- [ ] Walk-forward validation
- [ ] OOS validation
- [ ] Compare against frozen R4
- [ ] Promotion decision

### Outcome C: Live Evidence Contradicts Research → Investigate

- [ ] Execution costs materially higher
- [ ] Holding-period edge disappears
- [ ] Correlations underestimated
- [ ] Drawdowns materially worse
- [ ] Exits behave differently
- [ ] Catastrophic stops trigger too frequently

## Governance Rules During Phase 2

| Rule | Status |
|---|---|
| R4 strategy frozen | 🔒 LOCKED |
| $5K maximum tier | 🔒 LOCKED |
| No optimization | 🔒 LOCKED |
| No universe expansion | 🔒 LOCKED |
| No cadence changes | 🔒 LOCKED |
| No capital promotion | 🔒 LOCKED |
| Evidence collection active | 🟢 ACTIVE |
| Documentation updates | 🟢 ALLOWED |
| Safety fixes | 🟢 ALLOWED (separately governed) |

## Evidence Collection Schedule

| Frequency | Collection |
|---|---|
| Hourly | Position snapshots, risk gate results |
| Daily | Portfolio state, P&L attribution |
| Weekly | Correlation analysis, stress tests |
| Monthly | Full qualification review |

## Key Documents

| Document | Purpose |
|---|---|
| `PRODUCTION_EVIDENCE_INDEX.md` | All qualification artifacts |
| `RISK_ARCHITECTURE.md` | Risk control documentation |
| `LIVE_TRADING.md` | Operational procedures |
| `CAPITAL_SCALING.md` | Tier definitions and criteria |
| `CAPITAL_SEMANTICS.md` | Capital concept definitions |
