# ADR-022: Macro Expert Head Adaptive Weighting

## Status
Accepted

## Context
The Hybrid Regime Ensemble uses a Macro Expert Head to provide a "fundamental" or "regime-based" overlay that is less susceptible to price-action noise. Currently, this head has a fixed blend weight (default 0.45). However, the relative predictive power of macro factors vs. price-based features fluctuates across different market regimes. A fixed weight may be sub-optimal during periods where macro drivers are either dominant or decoupled from price action.

## Decision
We will implement an adaptive weighting mechanism for the Macro Expert Head. This mechanism will:
1.  **Track Performance**: Maintain a rolling history of performance (returns) for both the Macro Expert Head and the blended model.
2.  **Relative Sharpe Update**: Periodically (or on every trade close) compare the 63-day rolling Sharpe ratio of the macro-only signals vs. the blended signals.
3.  **Soft Update Logic**: Adjust the blend weight `w` using a soft update: `w += 0.01 * (macro_sharpe - blend_sharpe)`.
4.  **Guardrails**: Constrain the weight within a strictly defined interval `[0.25, 0.65]` to prevent the model from becoming entirely dependent on macro or entirely ignoring it.

## Implementation

- `MacroExpertHead.online_weight` — soft update `w += 0.01 * (macro_sharpe - blend_sharpe)`, clipped to [0.25, 0.65].
- `paper_trading/asset_engine.py` — enables on hybrid models; attributes trade PnL to macro vs blend by directional agreement; exposes `macro_weight` on decision JSON.
- `configs/paper_trading.yaml` — `adaptive_macro: true` on NZDJPY (requires `HybridRegimeEnsemble` pickle with `macro_head`).

## Consequences

- **Improved adaptivity**: The model can increase macro reliance during fundamental-driven regimes and decrease it when macro signal-to-noise is low.
- **Complexity**: Adds statefulness to the inference engine; plain XGBoost pickles ignore the flag.
- **Inertia**: The soft update and rolling window provide stability, preventing erratic weight swings.
- **Monitoring**: `macro_weight` on live decisions and `/volatility.json` vol ratios support ops dashboards.

See also: [HARDENING_ROADMAP.md](../HARDENING_ROADMAP.md) § Tier 3C.
