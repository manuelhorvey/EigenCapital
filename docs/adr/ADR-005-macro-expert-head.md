# ADR-005: Macro Expert Head With Protected Weight in Ensemble

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.
>
> **OBSOLETE 2026-06-20** — Ensemble disabled per ADR-026. The Macro Expert Head no longer participates in signal generation.

**Status:** Superseded (by ADR-026)

## Context

The `HybridRegimeEnsemble` architecture blends a global XGBoost backbone, regime-specific expert heads, and a macro-expert head. Initial experiments trained a single model on all 32 features (price-derived + macro). Feature importance analysis produced a troubling result: the full 32-feature model achieved maximum confidence of only 0.54 (near-random) and showed a 4:1 long bias — it was overwhelmingly bullish regardless of market conditions. Training the macro features in isolation produced both higher confidence (0.70 max) and correct bearish bias (0.4:1 short) during the 2022-2024 tightening cycle. The joint model was destroying the macro signal through feature interference.

## Decision

Implement a protected macro expert head with a fixed blend weight of 0.45, applied after the regime blend: `final = 0.45 * macro_probs + 0.55 * regime_blend`. The macro head is a separate XGBoost trained exclusively on macro features (rate_diff, dxy_mom, yield curves, spreads) with heavier regularization (min_child_weight=5, reg_alpha=0.1, reg_lambda=1.0) because macro data has strong autocorrelation. The global backbone (weight=0.4) and regime experts (weight=0.6) are blended first, then macro is blended on top.

## Alternatives Considered

- **Single model with all features:** Produced confidence 0.54, 4:1 long bias — macro signal drowned by 20+ price features.
- **Macro features only (no price features):** Correct bias but no timing ability — 94% short bias in 2022-2024, effectively a static position.
- **Learnable macro weight:** Considered using a meta-model to dynamically weight macro contribution based on recent performance. Rejected because: a) sample size of regime transitions is too small for reliable meta-learning, b) the macro head's value is context (rate regime), not timing.
- **Soft attention on macro features within the global model:** SHAP would be less interpretable and the feature interference issue likely persists.

## Consequences

**Positive:** The macro head cannot be outvoted by price features. With 0.45 fixed weight, macro signal contributes to every decision even when price features disagree. The separate training with heavier regularization handles macro data's auto-correlation. SHAP analysis on the macro head is clean and interpretable — it consistently ranks rate_diff and yield curves as top features.

**Negative:** Fixed 0.45 weight means the macro head contributes even when macro is uninformative (e.g., during rate-pause periods when all macro indicators are flat). The macro head cannot be dynamically downweighted. The regularization penalties (min_child_weight=5) were chosen heuristically and have not been systematically optimized.

## Evidence

Full 32-feature model: max confidence 0.54, 4:1 long/bull bias (wrong during 2022 tightening).
Macro-only isolation: max confidence 0.70, 0.4:1 short/bear bias (correct for 2022-2024).
The gap confirms feature interference — not feature absence. The protected macro head has since been validated in live paper trading.
