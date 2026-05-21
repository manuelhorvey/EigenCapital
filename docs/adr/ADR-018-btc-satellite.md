# ADR-018: BTC Satellite Isolation With Regime Gate

**Date:** 2026-05-18
**Status:** Accepted

## Context

BTC exhibited persistent structural instability as a portfolio asset. Marginal contribution analysis showed that BTC added disproportionate volatility (annualised vol 60-80% vs 15-25% for core assets) while contributing minimal Sharpe improvement. During the 2022 bear market, BTC's 77% drawdown dominated portfolio P&L despite being 20% of capital — the correlation spike during stress periods defeated the diversification intent.

Two options were considered: a) remove BTC entirely, losing its upside convexity, or b) isolate it with independent risk controls that prevent it from corrupting core portfolio metrics.

## Decision

Create `HighVolSatellite` — an isolated bucket with five independent controls:

1. **Hard capital cap** at 5% of AUM — cannot be exceeded by any path
2. **Separate vol target** at 40% annualised (vs 15-20% for core)
3. **Separate drawdown limit** at -25% (core limit is -15%)
4. **Five-condition regime gate** (AND logic) — all must be true to trade BTC:
   - BTC-to-portfolio rolling correlation < 0.30
   - BTC-specific vol z-score ≤ 2.0
   - VIX < 25 (risk-on macro regime)
   - DXY 21d momentum within ±2% (no USD strength shock)
   - At least 5 days since last CRISIS regime flag
5. **Marginal contribution monitoring** — 63-day rolling ΔSharpe with alert (-0.5) and auto-reduce (-1.0) thresholds

Satellite P&L is reported separately and never blends into core portfolio metrics. BTC was removed from `PAPER_PORTFOLIO` in engine, config, and shadow analytics.

## Alternatives Considered

- **Remove BTC entirely:** Simpler but forfeits upside convexity. BTC has 0.3-0.4 correlation to global liquidity conditions, providing non-zero diversification during liquidity-driven rallies.
- **Reduce allocation only:** Still allows tail events (2022-style 77% drawdown) to dominate portfolio P&L at any positive allocation.
- **Soft gate (OR logic):** Would allow BTC trading during any single favourable condition, increasing tail risk.

## Consequences

- BTC can no longer corrupt core Sharpe or drawdown metrics
- Upside participation is preserved but capped at 5% and conditioned on benign regime state
- Five simultaneous conditions mean the gate is rarely open during turbulent periods — this is intentional, not a bug
- Marginal contribution auto-reduce provides a second line of defence if the gate fails

## Affected code

- `paper_trading/satellite.py` — HighVolSatellite, SatelliteConfig, GateDecision, marginal contribution logic
- `paper_trading/engine.py:25-26,893-955,1084-1148` — satellite wiring, _run_satellite, portfolio aggregation
- `paper_trading/serve.py` — BTC removed from fallback allocations
- `paper_trading/shadow_analytics.py` — BTC removed from PAPER_PORTFOLIO
- `configs/paper_trading.yaml` — BTC moved from assets to satellite section
- `tests/test_satellite.py` — 14 tests
