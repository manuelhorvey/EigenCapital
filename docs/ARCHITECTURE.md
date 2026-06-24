# Architecture — Backtesting & Model Assessment (`backtests/`)

> **Note:** This file documents the `backtests/` module (recreated 2026-06-24).
> The main system architecture is documented in [`docs/SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md).

---

## `backtests/` — Model Comparison & Promotion Framework

The `backtests/` package provides model evaluation utilities used by research scripts (`scripts/research/`) for walk-forward model comparison, adversarial stress-testing, and promotion decisions. It is a standalone module with minimal dependencies (numpy, pandas, scikit-learn).

### Module Overview

| Module | Purpose | Key Exports |
|--------|---------|-------------|
| `__init__` | Package entry point | `compute_per_fold_labels` (placeholder) |
| `trade_analysis.py` | Trade aggregation & statistics | `aggregate`, `flip_quality`, `paper_stats` |
| `forward_test.py` | Walk-forward metrics | `_forward_metrics`, `_regime_metrics`, `_classify_vol_regime` |
| `mas.py` | Model Assessment Scoring | `compute_mas`, `score_model`, `score_signal`, `score_portfolio`, `score_shadow`, `score_forward`, `score_stress`, `hard_gates` |
| `model_comparator.py` | Model comparison | `compare_models`, `compare_signals`, `compare_portfolio`, `compare_shadow_intel`, `build_summary` |
| `model_evolution.py` | Trajectory management | `compute_mas_velocity`, `compute_mas_acceleration`, `compute_subaxis_drift`, `compute_convergence`, `estimate_equilibrium_band` |
| `model_promotion_engine.py` | Promotion decisions | `evaluate_promotion`, `_check_performance`, `_check_stability`, `_check_consistency`, `_check_safety` |
| `adversarial_manifold.py` | Adversarial stability testing | `evaluate_adversarial_manifold`, `PERTURBATIONS` (12 perturbation configs) |
| `performance_metrics.py` | Regime-stratified metrics | `calculate_regime_performance` |
| `expectancy_audit.py` | Trade expectancy analysis | `calculate_expectancy`, `run_expectancy_audit` |

### Data Flow

```
Research scripts (scripts/research/)
    │
    ├── compare_models()          → model_result
    ├── compare_signals()         → signal_result
    ├── compare_portfolio()       → portfolio_result
    ├── compare_shadow_intel()    → shadow_result
    │
    ├── _forward_metrics()        → forward_result  (via forward_test.py)
    ├── _regime_metrics()         → forward_result  (regime breakdown)
    │
    ├── score_*()                 → 6 sub-scores    (via mas.py)
    ├── hard_gates()              → pass/fail
    ├── compute_mas()             → MAS score       [0–100] + decision
    │
    ├── evaluate_adversarial_manifold() → CMSS      (via adversarial_manifold.py)
    ├── evaluate_promotion()      → promotion decision
    │
    ├── append_trajectory()       → persistence     (via model_evolution.py)
    └── load_trajectory()         → replay          (via model_evolution.py)
```

### Model Assessment Score (MAS)

The MAS framework combines six sub-scores into a composite [0–100] score:

| Component | Weight | Source | Evaluation Dimension |
|-----------|--------|--------|---------------------|
| model | 0.20 | `compare_models` | AUC, logloss |
| signal | 0.20 | `compare_signals` | Agreement, flip rate, confidence shift |
| portfolio | 0.20 | `compare_portfolio` | Return, return delta, drawdown |
| shadow | 0.15 | `compare_shadow_intel` | Entropy, agreement, regime stability |
| forward | 0.15 | `_forward_metrics` | Sharpe, hit rate, stability |
| stress | 0.10 | `_regime_metrics` | Regime-conditional Sharpe delta |

**Hard gates** (all must pass before MAS is valid):
- A: Signal agreement ≥ 0.95, flip rate ≤ 0.10
- B: Forward Sharpe ≥ 80% of baseline, drawdown ≤ 150%
- C: Drift score < 0.7
- D: Shadow entropy ratio ∈ [0.8, 1.2]

**Decision tiers** (based on MAS + check met-count in promotion engine):
- LIVE_CANDIDATE: MAS ≥ 88, all 4 checks pass
- PAPER_TRADING_ONLY: MAS ≥ 70, ≥ 3 checks pass
- SHADOW_ONLY: MAS ≥ 50, all 4 checks pass
- REJECT: Otherwise

### Adversarial Manifold

The `evaluate_adversarial_manifold` function applies 12 synthetic perturbations across 4 categories:

| Category | Perturbations | Effect |
|----------|--------------|--------|
| Volatility | shock, compression, noise | Amplify/reduce/add noise to feature variance |
| Correlation | decouple, inversion, break | Shuffle, invert, or add orthogonal noise |
| Trend | flip, burst, decay | Reverse, amplify, or dampen momentum features |
| Noise | inject, spike, dropout | Uniform noise, random spikes, random zero-out |

Each perturbation is scored by comparing the model's prediction distribution to the unperturbed baseline. The Composite Model Stability Score (CMSS) is the mean across all perturbations. Classification: ROBUST (≥ 0.7), MODERATE (≥ 0.5), BRITTLE (< 0.5).

### Trajectory Persistence

Model evolution trajectories are stored as JSON arrays in `data/sandbox/evolution/{asset}.json`. Each entry contains timestamp, MAS score, delta, decision, sub-scores, and forward result. This enables replay-based analysis and convergence monitoring across the portfolio.

### Test Coverage

The module has 211 unit tests in `tests/backtests/` covering all public functions, perturbation types, edge cases (empty trades, single-row DataFrames, error states), and promotion decision logic.
