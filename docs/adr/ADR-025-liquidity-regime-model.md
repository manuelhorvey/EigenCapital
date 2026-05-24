# ADR-025 — Liquidity Regime Model (Volume/Amihud Proxy Governance)

**Status:** Accepted  
**Date:** 2026-05  
**Tags:** governance, risk, liquidity, execution

## Context

The system has no liquidity awareness. Execution configs hardcode `base_spread_bps` and `avg_daily_volume` per asset, but these are static — they don't adapt to real-time liquidity conditions. During thin trading periods (holidays, Friday afternoons, crisis dislocations), static spreads and impact estimates understate true execution cost. The system cannot detect when it should widen SL barriers or reduce size due to adverse liquidity.

Tick/order book data is not available — only daily OHLCV from yfinance. Liquidity must be proxied from available data.

## Decision

Add a per-tick liquidity regime model that computes proxy liquidity metrics from daily OHLCV and classifies market conditions into NORMAL / THIN / STRESSED.

### Design

- **Features** (`compute_liquidity_features()`):
  - **Volume z-score**: rolling 21d z-score of volume. Negative values indicate abnormally thin trading.
  - **Amihud illiquidity ratio z-score**: `|return| / (volume × close)`, rolling 21d z-score. Positive values indicate abnormally high price impact per unit volume (illiquid).
  - **Corwin-Schultz spread estimate**: bid-ask spread proxy derived from daily high/low prices.
- **Regime classification** (`classify_liquidity_regime()`):
  - NORMAL: volume_z > -1.5 AND amihud_z < 1.5
  - THIN: volume_z ≤ -1.5 OR amihud_z ≥ 1.5
  - STRESSED: volume_z ≤ -2.5 OR amihud_z ≥ 3.0
- **Governance rules** (`liquidity_governance_scalars()`):
  - THIN: SL +15%, size -15%
  - STRESSED: SL +30%, size -30%, halted
- **Integration**: Same pattern as narrative governance — `_liquidity_sl_mult` in SL chain, `_liquidity_size_scalar` in sizing notional, `liquidity_ok` halt flag with -0.10 validity penalty
- **Refresh**: Every signal cycle (per tick), computed from latest OHLCV data

### Rationale for OHLCV-only approach

- No tick/order book data available in the data layer
- Volume z-score and Amihud ratio are well-established liquidity proxies in academic finance
- Corwin-Schultz spread provides a daily bid-ask estimate without requiring tick data
- Conservative thresholds prevent over-sensitivity

## Consequences

**Positive:**
- System gains liquidity awareness without new data sources
- Automatically adapts to holiday/weekend thin conditions
- STRESSED regime provides a new halt dimension (liquidity crisis detection)
- Configurable thresholds allow tuning per asset class

**Negative:**
- OHLCV proxies are noisy — volume can spike for non-liquidity reasons (news events)
- Daily data limits sensitivity — intraday liquidity dry-ups are invisible
- Corwin-Schultz spread estimate can produce unreliable values in certain market conditions
- Adds computational cost per signal cycle (rolling window computations)

## Threshold Selection

Thresholds are set conservatively to avoid false positives:
- volume_z ≤ -1.5 (bottom ~7% of volume distribution) for THIN
- volume_z ≤ -2.5 (bottom ~0.6%) for STRESSED
- These will be tuned empirically after 30 days of live data
