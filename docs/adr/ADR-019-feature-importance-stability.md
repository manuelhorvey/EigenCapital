# ADR-019: Feature Importance Stability Tracking as Governance Signal

**Date:** 2026-05-18
**Status:** Accepted

## Context

The system retrains XGBoost models on expanding windows. As new data arrives, the model's feature importance rankings can shift. Large shifts indicate that the model's decision boundary is changing — the model is "chasing" new patterns rather than reinforcing stable ones. Without monitoring, a model could silently become reliant on entirely different features than it was validated on, violating the walk-forward contract.

Two monitoring dimensions were needed: a) which features are in the top N (set-level stability via Jaccard), and b) whether the rank ordering of shared features is preserved (ordinal stability via Spearman).

## Decision

Create `ImportanceStore` in `monitoring/importance_tracker.py` with:

1. **Snapshot persistence** — logs feature importances per asset per training window to `data/live/importance_history.parquet`
2. **Jaccard top-10 similarity** — measures overlap between consecutive windows' top-10 feature sets. Range [0, 1].
3. **Spearman rank correlation** — measures rank-order preservation on features common to both windows
4. **Stability penalties** that feed into `ValidityStateMachine`:
   - Jaccard < 0.6: -0.10 penalty
   - Jaccard < 0.4: -0.25 penalty
   - Spearman < 0.7: -0.08 penalty
   - Spearman < 0.5: -0.20 penalty
5. **Worst-wins aggregation** — the most negative penalty is applied, not the average, to avoid masking degradation signals

## Alternatives Considered

- **KL divergence on full importance distribution:** More sensitive but harder to threshold and interpret. Jaccard + Spearman maps directly to "are we using the same features" and "in the same order."
- **Averaging penalties:** Would dilute the signal — a single catastrophic metric collapse could be hidden by stable metrics.
- **Threshold-only (no penalty):** Would alert but not act. The penalty mechanism ties degradation directly to position sizing.

## Consequences

- Feature stability is now a governance signal, not just a monitoring metric
- A model that suddenly switches features (e.g., after a regime shift) sees reduced position sizes until stability recovers
- Worst-wins means a single low Jaccard or Spearman score triggers the full penalty, which is intentionally conservative
- The parquet file enables post-hoc analysis of which features gained/lost importance over time

## Affected code

- `monitoring/importance_tracker.py` — ImportanceStore, compute_jaccard_top_n, compute_spearman_rank_corr, compute_stability_penalty, StabilityResult
- `monitoring/validity_state_machine.py:140-155` — stability penalties consumed via update_validity()
- `paper_trading/engine.py:202-207,294-304` — importance logging and penalty injection
- `tests/test_importance_tracker.py` — 27 tests
