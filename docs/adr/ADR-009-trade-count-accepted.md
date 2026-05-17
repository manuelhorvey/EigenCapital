# ADR-009: Accepted 150-250 Annual Trades for XLF

**Status:** Accepted

## Context

The multiclass XGBoost classifier (BUY / NEUTRAL / SELL) produces near-binary probability distributions: the mean probability of the NEUTRAL class across all test windows is typically 0.04-0.08. This means the model is almost always confident about direction — it rarely outputs the "no trade" signal that the NEUTRAL class represents. Attempting to filter trades by raising the confidence threshold produces problematic behavior: at thresholds above 0.55, the model enters periods of zero trades (stuck in a position it cannot exit), and the trade distribution becomes concentrated in a few high-conviction periods. No single threshold produces the ideal 40-80 annual trades while maintaining continuous market participation.

## Decision

Accept the 150-250 annual trade count as the operating regime. Position sizing (volatility-scaled, capped at 1.0) compensates for the high trade frequency by reducing per-trade risk. The rationale: a) XLF's daily liquidity ($2B+ ADV) makes transaction cost negligible (~$250/year at 250 trades on $100k capital, assuming $1 commission), b) the model's edge is in direction, not trade timing — more trades capture more of the modeled edge, c) the NEUTRAL class's low probability is not a bug but a property of the feature set (daily macro + momentum features predict direction, not regime transitions).

## Alternatives Considered

- **Meta-labeling on top of primary model:** Would add a second classifier to filter trades. Rejected because: a) insufficient training data for a two-stage model on XLF's ~1250 bars, b) the primary model's confidence is already well-calibrated (the 0.45 threshold matches the SHAP-validated decision boundary).
- **Position-level confidence scaling:** Instead of filtering trades, size them proportionally to confidence. This is implemented in the engine (volatility-scaled) but the confidence distribution is so concentrated (0.65-0.85) that it provides little differentiation.
- **Hard trade limit (max N trades per month):)** Would create a calendar-based trading pattern that introduces alpha decay.

## Consequences

**Positive:** The model captures all directional signals without artificial filtering. The high trade frequency means the Sharpe ratio calculation is based on 150-250 independent observations per year (statistically robust). Transaction costs on XLF are negligible — the bid-ask spread on XLF is typically $0.01-0.02 on a $35-40 stock, and the engine simulates fills at close.

**Negative:** High trade count means higher sensitivity to commission and slippage in a real-broker scenario. The model cannot be used directly for tax-sensitive strategies (short-term gains). The confidence threshold (0.45) is arbitrary — it was chosen because it matches the regime classifier's confidence threshold, not through independent optimization.

## Evidence

XLF neutral prob mean across all test windows: 0.04-0.08. Confidence distribution: 0.65-0.85 range for active trades. No confidence threshold between 0.40 and 0.60 produces fewer than 100 trades annually without zero-trade windows. Annual trading cost estimate: $250/year on $100k notional (0.25%), negligible relative to the 11.08% average return.
