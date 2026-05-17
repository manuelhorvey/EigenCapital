# ADR-006: XLF as Primary Equity Asset Over SPY/QQQ

**Status:** Accepted

## Context

The project needed a primary equity asset for the paper trading portfolio. SPY and QQQ were the default candidates (broad market exposure, high liquidity, extensive research literature). SPY was tested first: the XGBoost pipeline produced a long/short signal ratio of 9.82:1 — overwhelmingly long-biased with almost no sell signals. GLD had a ratio of 11.00:1. These instruments do not produce balanced signals from macro+momentum features because a) broad indices absorb macro shocks through sector rotation, b) there is no direct causal mechanism connecting rate expectations to index direction (different sectors respond oppositely), c) the multiclass classifier degenerates to a binary up/down bet.

## Decision

Adopt XLF (Financial Select Sector SPDR ETF) as the primary equity asset. XLF has a direct causal mechanism: financial sector profits are directly impacted by yield curve shape, interest rate policy, and lending spreads. The signal distribution on XLF is balanced: P(short) = 0.52 during 2022-2024 (bearish for financials during tightening) with maximum confidence reaching 0.79. The relationship is causal, not correlational.

## Alternatives Considered

- **SPY:** L/S ratio 9.82:1 effectively binary. Unable to generate sell signals with any threshold.
- **QQQ:** Even more extreme long bias (tech is structurally bullish).
- **GLD:** L/S ratio 11.00:1. Gold's macro drivers (real yields, USD) are captured but produce only long signals because gold has been in a structural bull trend.
- **XLF (chosen):** L/S ratio approximately 1:1 in 2022-2024. The financial sector has clear bull/bear regimes tied to the rate cycle.
- **Sector-rotation approach:** Rejected as too complex for the initial deployment. XLF as single sector is simpler than managing sector timing.

## Consequences

**Positive:** XLF produces genuine sell signals (2022 tightening, regional banking stress March 2023). The causal mechanism means the macro features (rate_diff, 2y_yield_delta_63) have direct explanatory power. The 5-year walk-forward shows consistent performance across rate cycles. The XLF-SPY relative strength feature (xlf_vs_spy_63) also captures financial-sector-specific risk premia.

**Negative:** Single-sector exposure concentration. If financial regulation changes or the sector undergoes structural change, the model must be retrained on a fundamentally different universe. The 2023 regional banking crisis caused a sharp drawdown (-11.4% max DD in 2022). Diversification across the three-asset portfolio (ADR-012) mitigates this but does not eliminate sector risk.

## Evidence

SPY L/S ratio: 9.82:1. GLD L/S ratio: 11.00:1. XLF during 2022-2024: P(short) = 0.52, max confidence 0.79, balanced signal distribution. XLF walk-forward (2019-2024): average annual return 11.08%, Sharpe 0.65, 5/6 positive years. The worst year (2022, -6.25%) occurred during the fastest rate-hiking cycle in 40 years — the model's short signals were correct but the speed of tightening overwhelmed exit timing.
