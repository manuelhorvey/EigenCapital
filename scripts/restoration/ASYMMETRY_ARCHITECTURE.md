# Embrace-Asymmetry Architecture

## Core Finding (2026-06-25)

The system has a **structural directional asymmetry**: SELL predictions achieve 62-90% WR while BUY predictions achieve 0-32% WR for 5 assets (reduced from 8 on 2026-06-26 when ^DJI, USDCHF, EURCHF BuyWR improved above breakeven after trend-exhaustion feature addition). Three independent experiments confirm this is a **feature-space encoding limit**, not a modeling artifact:

| Experiment | Result | What it proves |
|------------|--------|---------------|
| Threshold optimization (0.01-0.99) | No threshold > 50% BUY WR | Not a decision-boundary issue |
| Rolling 252 window | p_long mean shifts 0.4→0.6, BUY worsens | Not a training-window artifact |
| Label inversion (y' = 1-y) | BUY WR 22.7%→31.0%, still < 50% | Signal is not present in the representation |

## System Design Principle

> The system is a **pure SELL alpha engine** for the remaining 5 assets (CADCHF, ES, NQ, NZDCHF, EURAUD). BUY direction is not recoverable under the current feature/label design for these 5; 3 assets (^DJI, USDCHF, EURCHF) were restored to two-way trading on 2026-06-26 after trend-exhaustion features crossed the BuyWR > breakeven WR threshold.

For these assets, the feature space encodes:
- **SELL side**: mean reversion, downside continuation, volatility expansion — structurally learnable (62-90% WR)
- **BUY side**: upward drift, breakout continuation, liquidity-driven expansion — **not reliably encoded** (0-32% WR)

This is consistent with a well-documented financial ML phenomenon: downside moves are sharper, volatility spikes are asymmetric, and crashes are more structured than rallies. The feature set captures "risk events are predictable" but not "growth is predictable."

## Architecture Decision (Path A)

SELL_ONLY filter stays as the permanent production architecture for the remaining 5 flagged assets:

```
For each SELL_ONLY asset:
  Features → XGBoost → p_long = P(UP) → p_short = 1 - P(UP) = P(DOWN)
  
  if p_short > 0.575: SELL  (WR 62-90%)  ← CORRECT, execute
  else:               FLAT                ← BUY not signal, skip
```

No BUY hedge model. No BUY likelihood reconstruction. The diagnostic proves BUY exposure for these assets is noise-dominated — no reliable signal exists in the current feature space.

## What Was Closed

- **SELL_ONLY restoration**: CLOSED. No path to two-way trading under current feature design.
- **BUY signal existence**: FALSIFIED. The signal is not recoverable through any tested transformation.
- **Dual-model approach**: DEFERRED. Would require a fundamentally different feature set (liquidity, order flow, microstructure) before re-evaluation.

## What Remains Open (for future feature changes only)

If a new feature group is added that changes the feature space, the gatekeeper framework must be invoked:
1. Reproduce label inversion + symmetry + sufficiency tests
2. If all three pass (BUY WR > 50%), re-open investigation
3. Shadow mode (30d) before any live restoration

See `GATEKEEPER.md` for the full criteria.

## Portfolio-Level Note

The asymmetry extends beyond the 5 SELL_ONLY assets. Of 16 non-SELL_ONLY assets, several showed severe asymmetry but were mitigated by trend-exhaustion features. A portfolio-wide asymmetry study is deferred — the current system tolerates these within bounds.
