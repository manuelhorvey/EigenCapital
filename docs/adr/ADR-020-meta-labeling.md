# ADR-020: Meta-Labeling Layer as Confidence Filter

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.
>
> **OBSOLETE 2026-07-11** — The LogisticRegression meta-label implementation described here was superseded by an XGBoost-based MetaLabelModel (labels/meta_labels.py) after AUC 0.49-0.55 validation proved the LR approach effectively random. The XGBoost replacement uses richer features and continuous sizing. The legacy shared/meta_labeling.py file remains on disk but is not used in production.

**Date:** 2026-05-18
**Status:** Accepted

## Context

The primary XGBoost model produces multiclass probabilities (BUY/NEUTRAL/SELL) and a confidence score. These outputs are well-calibrated in aggregate but contain individual signals that lose money. The system needed a secondary filter that learns from historical trade outcomes to distinguish "signals that look good but fail" from "signals that succeed."

Key requirements: a) lightweight architecture (not another XGBoost), b) must not reduce trade frequency below minimum viability, c) must work with limited training data (50-300 trades), d) must be class-imbalance aware.

## Decision

Create `MetaModel` in `shared/meta_labeling.py` — a logistic regression binary classifier with:

1. **Five features** extracted at signal time:
   - `primary_confidence` — XGBoost confidence at entry
   - `regime_state_encoded` — GREEN (2), YELLOW (1), RED (0)
   - `feature_stability_penalty` — from ImportanceStore, -0.25 to 0
   - `vol_zscore` — recent vol relative to trailing 252d hist vol
   - `days_since_regime_change` — how long the current regime has persisted
2. **Class weighting** (`class_weight='balanced'`) over resampling — avoids information loss
3. **Minimum 50 trades** before training — prevents degenerate models on small samples
4. **Decision thresholds:**
   - Confidence ≥ 0.55: FULL (scale=1.0)
   - Confidence ≥ 0.40: REDUCED (scale=0.5)
   - Confidence < 0.40: SKIP (scale=0.0)
5. **StandardScaler** for feature normalisation; **lbfgs solver** for stability

## Alternatives Considered

- **Another XGBoost:** Overkill for a secondary model. Logistic regression is interpretable, fast, and less prone to overfitting on small trade samples.
- **Resampling (SMOTE/undersample):** Discards information (undersample) or creates synthetic data (SMOTE) that may not reflect actual trade dynamics. Class weighting preserves the real distribution.
- **Fixed threshold on primary confidence:** Does not incorporate regime context, vol regime, or feature stability — exactly the information the meta-model needs.

## Consequences

- Approximately 30-40% of signals are SKIP'd (scale 0), 20-30% are REDUCED (scale 0.5), and 30-40% are FULL (scale 1.0)
- The meta-model adapts over time as more trades accumulate, potentially becoming more selective
- The 50-trade minimum means no meta-filtering for the first 5-10 weeks of paper trading
- Logistic regression coefficients can be inspected post-hoc to understand what drives signal rejection

## Affected code

- `shared/meta_labeling.py` — MetaModel, build_meta_features_from_trade, build_meta_training_data, build_inference_features, decision_from_confidence
- `paper_trading/engine.py:207,343-360,640-710` — meta-model lifecycle, training trigger, inference injection
- `shared/sizing.py` — VolTargetSizing, meta-scale multiplies pos_size
- `tests/test_meta_labeling.py` — 31 tests
