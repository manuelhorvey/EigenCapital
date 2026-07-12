# ADR-012: Three-Asset Portfolio — XLF, BTC, NZDJPY

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.

**Status:** Superseded

> **Note (July 2026):** The portfolio has expanded to 22 assets (all FX, commodities, indices, and BTCUSD). BTC was never isolated as a satellite — it's a permanent member of the portfolio. See `configs/domains/assets/_index.yaml` for the current 22-asset roster. The correlation and diversification methodology documented here remains the framework for all portfolio expansions.

## Context

The paper trading engine needed a multi-asset portfolio allocation strategy. Initially each asset was developed independently. The question was what combination of assets to run live and how to weight them. A correlation and diversification analysis was conducted across the candidate assets. The critical finding: XLF, BTC-USD, and NZDJPY=X had a maximum pairwise PnL correlation of 0.055 over the 2022-2024 test period. Simultaneous loss days occurred on only 9 of 251 trading days (3.6%). This is not accidental — each asset belongs to a different driver cluster from the Driver Atlas (yield_equity, momentum_crypto, carry_fx), meaning they respond to different economic drivers and rarely fail simultaneously.

## Decision

Adopt a three-asset portfolio with fixed weights: XLF 40%, BTC-USD 35%, NZDJPY=X 25%, applied to $100,000 starting capital. The weights are based on a) confidence in each asset's validation depth (XLF highest, NZDJPY lowest), b) volatility-adjusted contribution (BTC gets volatility scaling which reduces effective exposure), and c) diversification benefit (equal weighting would underweight XLF's superior validation). The positions are managed independently — each asset has its own engine instance with independent signal generation, validity monitoring, and halt conditions.

## Alternatives Considered

- **Single-asset (XLF only):** Simpler but misses diversification — Sharpe 0.40 individual vs estimated 0.69 minimum for the three-asset portfolio at current correlations.
- **Equal weighting (33.3% each):** Rejected because NZDJPY had less validation depth and BTC's higher volatility would dominate the portfolio.
- **Risk parity weighting (inverse volatility):)** Considered but the infrastructure was not ready. The portfolio/ module has HRP and risk parity in progress — risk parity will be adopted once validated.
- **Four+ asset portfolio:** Adding EURUSD or GC=F would improve diversification but both are blocked pending data (ADR-011 for EURUSD, inflation breakevens + more regime diversity for GC=F).

## Consequences

**Positive:** Maximum pairwise PnL correlation 0.055 means the portfolio benefits from near-complete diversification. The estimated portfolio Sharpe is 0.69 minimum (0.40 × √3 assuming zero correlation) vs 0.40 for XLF alone. Simultaneous failure rate of 3.6% means capital is almost always available from at least one asset. Each asset's independent halt system prevents correlated drawdowns.

**Negative:** Fixed weights do not adapt to changing volatility or correlation regimes. If correlations converge during a crisis (which they did partially in 2022: simultaneous failures on 9 days), the diversification benefit degrades. The 25% NZDJPY allocation is the weakest link — less validated and dependent on a single feature set. Operating three independent engine instances is more complex than one.

## Evidence

PnL correlation matrix (2022-2024):
- XLF-BTC: 0.055
- XLF-NZDJPY: -0.023
- BTC-NZDJPY: 0.041
- Max pairwise: 0.055
- Simultaneous loss days: 9/251 (3.6%)
- Independent driver clusters confirmed: yield_equity, momentum_crypto, carry_fx
- Portfolio Sharpe estimate: 0.69 minimum (sqrt(3) × 0.40)
