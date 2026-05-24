# ADR-018: BTC Satellite Isolation With Regime Gate and Position Management

**Date:** 2026-05-18 (updated 2026-05-24)
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

The satellite is **not a passive bucket** — it actively manages positions:

- **Position entry**: When the gate opens (all 5 conditions met) and no position is active, the engine calls `open_position(entry_price, vol)` which:
  - Deploys 5% of AUM (`current_value = max_capital`)
  - Computes vol-adjusted SL/TP: `stop = entry × (1 − vol × sl_mult)`, `target = entry × (1 + vol × tp_mult)`
  - Vol (`v`) is the EWMA(span=100) of BTC daily log returns (mirrors `AssetEngine._tb_vol`)
  - `sl_mult` / `tp_mult` (0.58 / 1.51 from config) are multipliers on volatility, not on entry price — producing sane levels (~±2-5% for typical BTC vol)

- **SL/TP exit**: Each cycle, `check_exit(current_price)` checks whether price has breached the stop or target. If so, the position is closed with reason `"SL_HIT"` or `"TP_HIT"`.

- **Gate exit**: When the gate closes (any condition fails) and a position is active, the engine calls `close_position(reason="GATE_CLOSED")`.

- **Logging**: Every cycle produces a structured log line: `"BTC satellite: gate=OPEN|CLOSED, position=ACTIVE|FLAT, value=XXXX, exit=SL_HIT/TP_HIT"`.

- **Capital lifecycle**: `deploy_capital(max_capital)` runs once on the first engine tick. After that, `record_return(daily_btc_return)` compounds `current_value` when `position_active=True`. On re-entry, `current_value` resets to `max_capital` (each entry starts fresh at full allocation).

Satellite P&L is reported separately and never blends into core portfolio metrics. BTC was removed from `PAPER_PORTFOLIO` in engine, config, and shadow analytics.

## Alternatives Considered

- **Remove BTC entirely:** Simpler but forfeits upside convexity. BTC has 0.3-0.4 correlation to global liquidity conditions, providing non-zero diversification during liquidity-driven rallies.
- **Reduce allocation only:** Still allows tail events (2022-style 77% drawdown) to dominate portfolio P&L at any positive allocation.
- **Soft gate (OR logic):** Would allow BTC trading during any single favourable condition, increasing tail risk.
- **Read-only gate (original design):** Evaluated the gate but never acted on the decision — no positions were opened or closed. This was replaced by active position management (this ADR update).

## Consequences

- BTC can no longer corrupt core Sharpe or drawdown metrics
- Upside participation is preserved but capped at 5% and conditioned on benign regime state
- Five simultaneous conditions mean the gate is rarely open during turbulent periods — this is intentional, not a bug
- Vol-adjusted SL/TP prevent unrealistically wide stop/target levels (original bug: applied `sl_mult`/`tp_mult` as raw percentages of entry, producing -58%/+151% ranges)
- Dashboard exposes entry price, stop price, target price, and exit reason for full visibility
- Marginal contribution auto-reduce provides a second line of defence if the gate fails
- Every engine cycle logs satellite state (gate, position, value) so it stays visible even when excluded from core metrics

## Affected code

- `paper_trading/satellite.py` — HighVolSatellite, SatelliteConfig (added sl_mult/tp_mult), SatelliteSnapshot (added entry_price, stop_price, target_price, exit_reason), `open_position()` (vol-adjusted SL/TP), `close_position()` (exit price + reason), `check_exit()` (SL/TP breach detection), `get_state()` (new fields)
- `paper_trading/satellite_runner.py` — `compute_btc_context()`, `fetch_macro_context()`, `fetch_btc_price()`
- `paper_trading/engine.py` — `_run_satellite()` (record_return → check_exit → gate open/close loop), `_init_satellite()` (passes sl_mult/tp_mult), `_satellite_snapshot()` (new fields)
- `paper_trading/dashboard/src/types/portfolio.ts` — SatelliteState interface (entry_price, stop_price, target_price, exit_reason)
- `paper_trading/dashboard/src/components/SatelliteCard.tsx` — displays entry/SL/TP prices when position active, last exit reason when flat
- `paper_trading/serve.py` — BTC removed from fallback allocations
- `paper_trading/shadow_analytics.py` — BTC removed from PAPER_PORTFOLIO
- `configs/paper_trading.yaml` — BTC moved from assets to satellite section
- `tests/test_satellite.py` — 14 tests
