# ADR-004: EURUSD Daily Rejected as Primary Asset

**Status:** Accepted

## Context

EURUSD was evaluated as a candidate primary asset alongside XLF for the paper trading portfolio. It passed initial feature-engineering benchmarks and had strong intuitive logic (US-EU rate differentials, risk sentiment proxy). An 8-year walk-forward study (2016-2024) was conducted using the same XGBoost multiclass pipeline with macro + momentum features.

## Decision

Reject EURUSD daily as a primary asset. The decision has two components: a) reject daily-frequency FX as a stand-alone alpha source with price-derived features alone, and b) block EURUSD for future deployment until COT (Commitment of Traders) data is integrated.

## Alternatives Considered

- **Weekly EURUSD:** Resampling to weekly improved signal-to-noise ratio but reduced the training sample too much. With 8 years of weekly data (~416 bars), the walk-forward had insufficient test windows for statistical significance.
- **EURUSD with macro-only model:** The macro-only model produced correct directional bias (short in 2022-2024 as USD strengthened) but at 94% short bias — effectively a single-position bet, not a trading system. Maximum confidence of 0.70 showed the model was certain but had no ability to time entries.
- **Increased feature set:** Adding more price-derived features (interaction features, structural features) did not improve results. The bottleneck is not feature count but information type.

## Consequences

**Positive:** Avoided deploying a system with 1.65% CAGR that would have consumed research time and portfolio allocation for near-zero return. The rejection confirmed the asset-specific driver hypothesis: EURUSD's primary drivers (positioning, flows, central bank policy expectations) are not well-captured by daily OHLCV + macro data alone.

**Negative:** EURUSD is the most liquid FX pair and a natural hedge for USD-denominated equity positions. Its absence from the portfolio limits diversification and increases USD exposure risk. The COT data requirement adds data infrastructure complexity (weekly CFTC reports, parsing, alignment).

## Evidence

8-year walk-forward: 1.65% CAGR. Macro-only model: correct short direction but 94% bias, unable to time entries. 28 FX pairs tested with macro + momentum features: zero passed the deployment gate (defined as PF > 1.10 over 5+ consecutive windows with bootstrap p < 0.10). Residual analysis confirmed the missing axis is positioning/liquidity, not additional macro variables.
