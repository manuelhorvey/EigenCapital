# EigenCapital Phase Status

Last updated: 2026-08-27

## Official Status

| Phase | Status | Description |
|---|---|---|
| Phase 0 | ✅ COMPLETE | Research/Strategy Foundation |
| Phase 1 | 🟢 COMPLETE | Production Hardening & Safety Qualification |
| Phase 2 | 🟡 ACTIVE | Live Economic Validation & Capacity Discovery |
| Phase 3 | 🔒 LOCKED | Capital Scaling (requires Phase 2 evidence gates) |
| Phase 4 | ⏳ FUTURE | Production Scale / Capacity |
| Phase 5 | ⏳ FUTURE | Continuous Research & Governance |

## Infrastructure Track: COMPLETE ✅

**Completed:** 2026-08-27

The following infrastructure has been validated and is now COMPLETE:

| Component | Status | Validation |
|---|---|---|
| Event/evidence ledger | ✅ Complete | Immutability, correlation chains |
| Reconciliation engine | ✅ Complete | 11 hostile-condition tests |
| Health-state model | ✅ Complete | 8 transition tests |
| Risk observation | ✅ Complete | 5K observation test |
| Structured alerting | ✅ Complete | Flood deduplication test |
| Failure instrumentation | ✅ Complete | Comprehensive tracking |
| Phase 2 qualification dataset | ✅ Complete | Per-trade evidence |
| Phase 2 report generator | ✅ Complete | Structured verdict |
| Evidence maturity framework | ✅ Complete | E0-E6 levels |
| Parity tests | ✅ Complete | 22/22 passing |
| Adversarial validation | ✅ Complete | 40 hostile-condition tests |
| Long-duration tests | ✅ Complete | Memory, performance |

**The next valuable commit is a qualification report from another week/month of untouched live data, not another feature.**

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

## Phase 2: Live Economic Validation 🟡

**Started:** 2026-08-26

### Objective

> Does R4, exactly as frozen and deployed, produce a statistically credible positive net edge in live conditions while remaining inside its risk envelope?

### Sub-phases

| # | Sub-phase | Purpose | Status |
|---|---|---|---|
| 2A | Execution Fidelity | Research → Paper → Live comparison | 🟡 Collecting |
| 2B | Entry Quality | Slow edge validation | 🟡 Collecting |
| 2C | Holding Period | Edge expression timeline | 🟡 Collecting |
| 2D | Downside/SL Validation | Catastrophic protection behavior | 🟡 Collecting |
| 2E | Portfolio Risk | Correlation, clusters, VaR/CVaR | 🟡 Collecting |
| 2F | Operational Survival | Failure → detection → recovery | 🟡 Collecting |
| 2G | Profitability | Net expectancy, Sharpe, drawdown | 🟡 Collecting |

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

### Minimum Evidence Gate

- [ ] Meaningful number of completed trades
- [ ] Sufficient exposure across regimes
- [ ] Sufficient holding-period observations
- [ ] Multiple weekly/monthly cycles
- [ ] At least one meaningful volatility transition
- [ ] Weekend/open-gap observations
- [ ] Execution statistics
- [ ] Zero unresolved P0 safety incidents
- [ ] Complete trade-level attribution

### Economic Gate

- [ ] Live net expectancy > 0
- [ ] Confidence intervals don't contradict research expectation
- [ ] Expectancy/trade, expectancy/day, expectancy/month positive
- [ ] Sharpe, Sortino, profit factor acceptable
- [ ] Maximum drawdown within bounds
- [ ] CVaR acceptable
- [ ] Losing streaks within research bounds

### Risk Gate

- [ ] No uncontrolled DD breach
- [ ] Daily loss controls behave correctly
- [ ] Catastrophic protection works (rare activation)
- [ ] No unexplained position creation
- [ ] No foreign-position contamination
- [ ] No reconciliation failures
- [ ] No persistent execution anomaly

### Fidelity Gate

- [ ] Research and live behavior sufficiently consistent
- [ ] Entry prices match signal expectations
- [ ] Exit behavior matches research model
- [ ] Holding period distribution matches research

### Outcomes

| Outcome | Result | Next Phase |
|---|---|---|
| A: R4 validates | Positive expectancy, all gates pass | Phase 3: Capital Scaling |
| B: R4 has weaknesses | Specific issues identified | Research Improvement Campaign |
| C: Evidence contradicts research | Major discrepancies | Investigation, no scaling |

## Governance Rules During Phase 2

| Rule | Status |
|---|---|
| R4 signal frozen | 🔒 LOCKED |
| R4 universe frozen | 🔒 LOCKED |
| R4 cadence frozen | 🔒 LOCKED |
| R4 sizing frozen | 🔒 LOCKED |
| R4 exit logic frozen | 🔒 LOCKED |
| R4 risk envelope frozen | 🔒 LOCKED |
| $5K maximum tier | 🔒 LOCKED |
| No optimization | 🔒 LOCKED |
| No universe expansion | 🔒 LOCKED |
| No cadence changes | 🔒 LOCKED |
| No capital promotion | 🔒 LOCKED |
| Evidence collection active | 🟢 ACTIVE |
| Documentation updates | 🟢 ALLOWED |
| Safety fixes | 🟢 ALLOWED (separately governed) |

### Why Freeze Everything

> Do not optimize R4 while collecting this evidence.
> Otherwise you'll never know whether the live results came from R4 or from constant intervention.

Every live trade is evidence. Create a separate **R4 Live Qualification Dataset** and treat every trade as data.

## Evidence Collection Schedule

| Frequency | Collection |
|---|---|
| Per trade | Signal, fill, spread, slippage, latency, swap |
| Hourly | Position snapshots, risk gate results |
| Daily | Portfolio state, P&L attribution, MAE/MFE |
| Weekly | Correlation analysis, stress tests, holding period |
| Monthly | Full qualification review, expectancy calculation |

## Key Metrics to Track

### Per-Trade
- Signal timestamp, intended symbol/direction/weight
- Requested price, fill price, spread, slippage
- Execution latency, rejection/partial-fill status
- Swap/financing, commissions
- Actual exit, exit reason, realized P&L
- MAE, MFE, holding period

### Entry Quality
- Forward return at 1h/1d/3d/5d/10d/20d
- Time to first profit
- Time to first -0.25R / -0.5R / -1R
- Eventual winner/loser
- Signal-strength percentile, regime, volatility state

### Holding Period Distribution
- <1d: Immediate edge?
- 1-5d: Early adverse movement normal?
- 5-10d: Position beginning to work?
- 10-20d: Expectancy improving?
- 20-40d: Predicted edge emerging?
- 40d+: Majority of P&L from here?

### Portfolio Risk
- Gross/net/long/short exposure
- FX/commodity/index exposure
- Currency-factor exposure
- Correlation clusters
- Portfolio VaR/CVaR
- Simultaneous MAE/SL losses
- Drawdown, daily loss, margin utilization

### SL Validation
- SL hit frequency
- Loss per SL
- MAE before recovery
- How many trades would have recovered
- Portfolio-level simultaneous SLs
- Gap-through-SL losses
- SL contribution to total P&L

## Key Documents

| Document | Purpose |
|---|---|
| `PRODUCTION_EVIDENCE_INDEX.md` | All qualification artifacts |
| `RISK_ARCHITECTURE.md` | Risk control documentation |
| `LIVE_TRADING.md` | Operational procedures |
| `CAPITAL_SCALING.md` | Tier definitions and criteria |
| `CAPITAL_SCALING.md` | Capital semantics & scaling (consolidated) |
| `PHASE2_INFRASTRUCTURE_PLAN.md` | Phase-2-safe infrastructure implementation plan |
| `PHASE2_GOVERNANCE.md` | Phase 2 governance rules |
| `PHASE2_CHANGE_CONTROL.md` | Change control and exit gate definitions |

## Repository Freeze

**As of 2026-08-27, the repository is in measurement mode.**

The next valuable commit is a qualification report from untouched live data, not another feature.

See `PHASE2_CHANGE_CONTROL.md` for allowed/not-allowed changes.
