# Stress Test Contract — Phase 1H

## Purpose

Phase 1H answers: "Does EigenCapital remain correct, controlled, and fail-safe when reality is materially worse than the assumptions used in the research environment?"

## Terminology

| Term | Definition |
|------|-----------|
| **Scenario** | A controlled perturbation applied to a baseline system state |
| **Baseline** | The nominal system state before perturbation |
| **Perturbation** | The adverse condition injected into the system |
| **Expected Behavior** | What the system must do under the scenario |
| **Forbidden Behavior** | What the system must NOT do under the scenario |
| **Invariant** | A property that must hold under all conditions |
| **Fail-Closed** | System stops or rejects new exposure rather than operating incorrectly |

## Scenario Taxonomy

1. Market-data failures (missing, stale, invalid, corrupted)
2. Execution degradation (slippage, delay, partial fill)
3. Transaction-cost shocks (spread widening, fee increases)
4. Liquidity deterioration (reduced volume, limited depth)
5. Order/fill failures (rejection, invalid price, margin)
6. Portfolio stress (drawdown cascades, correlated losses)
7. Risk-control activation (leverage, loss limits, kill switch)
8. State/reconciliation failures (divergence, restart)
9. Extreme market events (gaps, crashes, volatility spikes)
10. Simultaneous subsystem failures (multi-component breakdown)

## Severity Classification

- **CRITICAL**: Risk bypass, duplicate exposure, drawdown breaker bypass, accounting phantom equity
- **HIGH**: Incorrect partial-fill, incorrect slippage, stop-gap error, state recovery inconsistency
- **MEDIUM**: Degraded observability, incomplete diagnostics
- **LOW**: Non-critical reporting issues

## Status Semantics

- **PASS**: Expected behavior observed, no forbidden behavior
- **FAIL**: Forbidden behavior observed or expected behavior violated
- **INCONCLUSIVE**: Scenario cannot be executed or result is ambiguous

## Deterministic Execution

Every scenario must be reproducible:
- Same seed + same inputs = same result
- Deterministic perturbation
- Deterministic system state

## Interaction with EigenRisk

- Stress scenarios must not bypass EigenRisk
- Risk controls must remain active under all scenarios
- A triggered risk breaker must halt new exposure

## Failure Semantics

A stress failure is a **research result**, not something to "make green."
- Do not modify risk limits to pass tests
- Do not optimize strategy to survive scenarios
- Do not convert FAIL into PASS without correcting the underlying issue

## Evidence Requirements

Every scenario must produce:
- scenario_id
- baseline_result
- stressed_result
- perturbation applied
- expected vs actual behavior
- violated_invariants (if any)
- risk_controls_triggered
- maximum_loss
- reconciliation_status
