# ADR-002: Regime Classifier as Router, Not Alpha Source

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.
>
> **OBSOLETE 2026-06-20** — Ensemble disabled per ADR-026. The regime classifier is no longer used as a model router. Regime features remain in the alpha pipeline for trace logging only.

**Status:** Accepted

## Context

The initial design treated regime classification (TREND / RANGE / VOLATILE / NEUTRAL) as an additional feature set to feed into the main XGBoost model. The hypothesis was that regime state would be among the most important features for the classifier. Regime ablation studies showed a different picture: including regime probabilities as features produced a profit factor of 1.061 vs 0.231 without regime — a massive improvement — but SHAP analysis showed the raw regime probability columns (P_trend, P_range, etc.) were not among the top 10 features in the XGBoost model. The regime signal was being used indirectly, not as a direct predictor.

## Decision

Refactor regime classification from a feature provider to a model router. The `RegimeClassifier` (KER + ADX + volatility compression, with structural VOLATILE priority gate) determines the current regime at inference time. The `HybridRegimeEnsemble` then routes to regime-specific expert XGBoost models (max_depth=3) rather than feeding regime probabilities into a global model. The global backbone (max_depth=2) still trains on all data as a baseline, but the expert heads are regime-conditional. Regime routing happens once inside the ensemble; downstream signal logic is intentionally stateless to avoid compounding regime decisions.

## Alternatives Considered

- **Regime probabilities as features in a single XGBoost:** SHAP confirmed the model did not use them directly — it found more predictive patterns elsewhere. The benefit of regime was architectural (different models for different conditions), not parametric.
- **Hard regime switch (single model per regime):** Produced instability at regime boundaries; the soft blend (global + expert + macro) smooths transitions.
- **No regime classification at all:** Profit factor dropped from 1.061 to 0.231 — regime is essential but for risk management, not prediction.

## Consequences

**Positive:** The regime classifier acts as a gearbox — selecting the right tool for current market conditions without the model needing to learn regime transitions internally. The 0.231 → 1.061 PF improvement is the single largest performance jump measured. The router architecture also enables independent validation of each expert head.

**Negative:** Regime misclassification propagates — if the regime classifier calls TREND during a RANGE market, the wrong expert fires. The 10-bar smoothing window and confidence threshold (0.45) mitigate this but cannot eliminate it. The structural VOLATILITY override gate (vol_zscore > 1.35 or compression > 1.45) prevents shocks from being misclassified but introduces a hard-code threshold that requires monitoring.

## Evidence

Regime ablation experiment: PF with regime routing = 1.061, PF without regime = 0.231. SHAP verification on the TREND expert confirmed that P_trend appears in the top 10 features for the TREND-specific model, confirming the routing architecture is working as designed.
