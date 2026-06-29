# ADR-027: Portfolio Execution Kernel — Centralized Admission Control

**Status:** Accepted
**Date:** 2026-06-29
**Supersedes:** None (new architecture)

## Context

The original portfolio budget management used a distributed pattern:
- A `budget_ref` list was created in the pre-phase and distributed to every actor engine
- Each actor atomically decremented from this shared mutable reference via `threading.Lock()`
- A secondary backstop multiplier ratcheted down on budget breach and decayed by 0.9×/cycle on clean cycles

This pattern had several problems:

1. **No admission ordering**: First signal to execute got the budget — no prioritization
2. **Race condition surface**: 22 actors competing for the same lock created non-deterministic budget allocation
3. **No portfolio-level view**: Actors had no knowledge of total exposure when making admission decisions
4. **Backstop was reactive, not preventive**: It corrected after the breach had already occurred
5. **No factor exposure awareness**: Budget was a flat notional pool with no understanding of concentrated risk (CHF cluster, etc.)

## Decision

Replace the distributed budget_ref + backstop pattern with a centralized Portfolio Execution Kernel (PEK) consisting of:

### New Components

1. **PortfolioStateSnapshot** (immutable dataclass, `risk/contracts/portfolio_state.py`)
   - Built once per cycle in the PRE phase
   - Contains: all open positions, factor exposures, cluster detection, concurrent position counts, daily loss tracking, drawdown
   - Single source of truth for portfolio-level state

2. **PerformanceState** (immutable dataclass, `risk/contracts/performance_state.py`)
   - OutcomeTracker: rolling 20-trade win rate, R-multiples, streaks, MFE/MAE
   - VelocityProcessor: trend_factor, shock_factor, health_factor → composite scalar ∈ [0.5, 1.5]
   - MarketStateReader + ExecutionQualityTracker: vol, spread, slippage, MT5 health
   - Purely observational — never mutates state

3. **RiskEngineV2** (`risk/engine_v2.py`)
   - Consumes PortfolioStateSnapshot + PerformanceState
   - Produces RiskBudget with adaptive max_risk_per_trade
   - Can only REDUCE risk below config base (never increase)
   - Applies: base_risk × drawdown_scalar × perf_composite × vol_scalar

4. **PortfolioAdmissionController** (`paper_trading/orchestrator/admission/controller.py`)
   - Two-stage design:
     - Stage A: Fast filter — 7 hard constraint checks (concurrent, daily loss, leverage, drawdown, factor exposure, gates, staleness)
     - Stage B: Rank and allocate — composite scoring (calibrated prob, expected value, risk-adjusted reward, regime confidence, correlation penalty, age decay)
   - Collects all intents BEFORE any are admitted (no first-past-the-post)
   - Deterministic: sorted by score, sequential budget allocation

### Engine Cycle Changes

The 4-phase cycle became a 5-phase cycle:

| Phase | Before (removed) | After (PEK) |
|-------|-------------------|-------------|
| PRE | Equity snapshot + budget_ref distribution | PortfolioStateSnapshot + RiskBudget + PerformanceState |
| 1a | Signal generation (with entry execution) | Signal generation (entry execution deferred) |
| 1b | — | PEK admission review: collect intents, filter, rank, enforce budget |
| 3d | Leverage backstop with corrective multiplier | Anomaly-only monitor (log only, no correction) |
| 4 | Persist only | Persist + record outcomes to PerformanceStateBuilder |

### Removed Patterns

- `_leverage_budget_ref` and `_leverage_lock` removed from actor engines
- `_backstop_multiplier` and `_backstop_decay_cycles` removed (backstop → anomaly)
- `SizingInput.leverage_budget_ref`, `leverage_lock`, `leverage_budget_soft` removed
- `SizingResult.leverage_budget_total`, `leverage_decremented` removed

### Configuration

New `mode:` selector + `modes:` section in `configs/paper_trading.yaml`:

```yaml
mode: production
modes:
  production:
    capital: 100000
    defaults:
      max_concurrent_positions: 8
      factor_exposure_limits: {CHF: 0.20, ...}
  challenge_ftmo_10k:
    capital: 10000
    defaults: {max_concurrent_positions: 5, ...}
  live:
    capital: 100000
    defaults: {max_concurrent_positions: 6, ...}
```

## Consequences

### Positive

- Deterministic admission ordering (sorted by composite score, not thread scheduling)
- Portfolio-level awareness of factor exposures, cluster risk, and concentration
- Self-healing budget enforcement (closes lowest-ranked when over budget)
- Removed 22-thread lock contention on budget_ref
- Backstop anomaly detection provides observability without corrective action
- PerformanceState enables anticipatory risk adjustment (velocity layer)

### Negative

- Additional complexity in orchestrator cycle (new Phase 1b)
- PEK admission review runs on orchestrator thread (not parallel) — adds ~1-5ms latency
- PortfolioStateSnapshot construction accesses all actor internals (coupling)
- PerformanceState is observations-only; its velocity scalar is not yet wired as a control input

### Risks

- PEK budget enforcement closes live positions — untested in production with real MT5 positions
- Correlation penalty (0.1 per cluster member, max 0.5) is heuristic — not empirically calibrated
- Mode config overrides could silently change budget limits if misconfigured
