# ADR-011: EURUSD Blocked Pending COT Data Integration

**Status:** Accepted

## Context

ADR-004 rejected EURUSD daily as a primary asset, but the deeper question remained: is EURUSD systematically untradeable with this feature set, or is there a specific missing data axis? A cross-asset scan was conducted across 28 FX pairs using the standard macro + momentum feature template. Result: zero pairs passed the deployment gate (PF > 1.10 over 5+ consecutive windows with bootstrap p < 0.10). This is not an asset-specific failure — it is a feature-class failure for FX. Residual analysis was performed: the model predictions were regressed against actual returns, and the residuals showed clear non-random structure correlated with CFTC positioning data (commercial vs speculative net positions) and liquidity regime indicators. The missing axis is positioning and liquidity, not additional macro variables.

## Decision

Block EURUSD (and all FX pairs) from the trading universe until COT (Commitment of Traders) data is integrated. This is a hard gate: no FX asset can be deployed without COT-based features. The COT data source (CFTC weekly reports) requires infrastructure for parsing, alignment to daily price data, and feature engineering (net commercial positioning, speculative/managed money ratios, positioning extremes). The feature module for FX will include: COT net positioning (z-score), positioning extreme indicator (top/bottom 10th percentile), change in speculative positioning (1-week and 4-week delta), and commercial-to-speculative ratio.

## Alternatives Considered

- **Deploying EURUSD with current features despite marginal results:** Rejected — 1.65% CAGR is not sufficient compensation for the operational cost of running a live FX position.
- **Switching to EURUSD weekly:** Fewer test windows, lower statistical significance.
- **Adding more macro features (more yield curves, more rate differentials):** Residual analysis confirmed the residuals are not correlated with any additional macro variable. The missing signal is positioning (who holds what), not environment (what rates are).
- **Using proxy for positioning (spot volume, volatility skew):)** Tested but the signal-to-noise ratio was too low — CFTC data is the only reliable source.

## Consequences

**Positive:** Prevents deployment of a system with no verified edge. The COT requirement forces the data infrastructure to exist before FX trading, which prevents the "let's just try it and see" pattern that would produce unreliable results. COT data also has value for the existing XLF model (financial sector positioning) and for regime classification.

**Negative:** Eliminates the largest and most liquid asset class from the portfolio. No FX hedging for USD-denominated equity positions. Requires ongoing weekly data ingestion (CFTC reports release Friday afternoons). COT data is reported with a 3-day lag (Tuesday positions reported Friday) — the feature will be stale by 3-5 days, which may limit its predictive value for intra-week trading.

## Evidence

28 FX pairs tested with macro + momentum features: zero passed deployment gate. Residual analysis: residuals show significant correlation with CFTC net commercial positioning (r²=0.31 for EURUSD, p<0.01). Adding COT features to the residual model explains 31% of the residual variance — the largest single factor identified. Liquidity regime (measured by bid-ask spread percentile) explains an additional 8%.
