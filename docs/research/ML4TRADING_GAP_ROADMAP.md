# ML4Trading Gap Analysis — Phased Implementation Roadmap

Based on: *Machine Learning for Algorithmic Trading* (Stefan Jansen, 2020)

## Current State Assessment

### What EigenCapital Does Well

| Area | Status | Evidence |
|------|--------|----------|
| Factor-based signal construction | ✅ Strong | R4 momentum with multi-timeframe features |
| Walk-forward validation | ✅ Strong | Embargo-aware walk-forward with out-of-sample testing |
| Multiple-testing correction | ✅ Strong | Bonferroni, BH/FDR, deflated Sharpe ratio |
| Falsification culture | ✅ Strong | R5 (16/16 rejected), M1-1H frozen, tick campaigns frozen |
| Risk enforcement | ✅ Strong | 7-gate broker-authoritative enforcement |
| Production infrastructure | ✅ Strong | Reconciliation, health states, event ledger |
| Backtesting framework | ✅ Moderate | Cost-aware with basic execution modeling |
| Alternative data hypothesis testing | ✅ Moderate | R5 breadth factor, sentiment hypotheses |

### What EigenCapital Is Missing

| Area | Gap | Impact |
|------|-----|--------|
| ML signal generation | No ML models in signal pipeline | High — potential alpha |
| Portfolio optimization | Weight clipping only | Medium — risk-adjusted returns |
| Transaction cost modeling | Basic spread/commission | Medium — needed at scale |
| Covariance-aware sizing | AUD cluster not used in sizing | Medium — tail risk |
| Bar aggregation | No tick → volume/dollar bars | Low — not needed for daily |
| NLP/Alternative data pipelines | No NLP, sentiment, satellite | Low — Phase 5 |
| Execution algorithms | No TWAP/VWAP/IS | Low — not needed at $5K |

---

## Phase A: ML Signal Generation (Post-Phase 2)

**Trigger:** Phase 2 evidence confirms R4 has a live edge.

**Objective:** Add a machine-learning signal layer that can be combined with R4's rules-based signal.

### A1. Feature Engineering Pipeline

```python
# Target: Generate ML-ready features from existing R4 data

Feature Categories:
├── Momentum (existing R4 features)
│   ├── ROC_1, ROC_5, ROC_20, ROC_60
│   ├── Moving average crossover signals
│   └── Volatility regime indicators
├── Cross-sectional
│   ├── Relative strength vs universe
│   ├── Sector/factor exposure
│   └── Correlation regime
├── Microstructure
│   ├── Spread dynamics
│   ├── Volume profile
│   └── Order flow imbalance (if available)
├── Macro
│   ├── VIX regime
│   ├── Yield curve slope
│   ├── Dollar index momentum
│   └── Commodity correlation
└── Calendar
    ├── Day of week
    ├── Month effect
    ├── Turn-of-month
    └── Holiday proximity
```

**Implementation:**
- `src/eigencapital/features/ml_features.py` — ML feature computation
- `src/eigencapital/features/purged_cross_validator.py` — Purged K-fold with embargo
- `tests/unit/features/test_ml_features.py` — Feature validation tests

### A2. Model Training Pipeline

```python
# Target: Train LightGBM/XGBoost models with proper cross-validation

Models:
├── LightGBM (primary)
│   ├── Binary classification (up/down)
│   ├── Regression (forward return magnitude)
│   └── Ranking (cross-sectional sort)
├── XGBoost (secondary)
│   └── Same as LightGBM for comparison
└── Simple ensemble
    └── Average of LightGBM + XGBoost predictions
```

**Implementation:**
- `src/eigencapital/models/trainer.py` — Model training with purged CV
- `src/eigencapital/models/predictor.py` — Inference pipeline
- `src/eigencapital/models/validator.py` — Model validation metrics
- `tests/unit/models/test_trainer.py` — Training tests

### A3. Signal Combination

```python
# Target: Combine ML signal with R4 rules-based signal

Combination Strategies:
├── Additive: signal = α * R4 + (1-α) * ML
├── Regime-conditional: ML in low-vol, R4 in high-vol
├── Confidence-weighted: ML confidence gates R4
└── Stacking: meta-learner on top of R4 + ML
```

**Implementation:**
- `src/eigencapital/strategies/ensemble.py` — Signal combination logic
- `src/eigencapital/strategies/ml_strategy.py` — ML-based strategy wrapper
- Tests for each combination method

### A4. Validation & Evidence

```
Validation Requirements:
├── Purged walk-forward (no leakage)
├── Multiple-testing correction applied
├── Parameter stability check
├── Drawdown requirement met
├── Live shadow mode (feature-flagged)
└── Parity tests confirm R4 unchanged
```

**Shadow Mode:**
```python
# During Phase 2, ML signal runs in shadow only
ML_SIGNAL_ENABLED = False  # Feature flag
ml_decision = model.predict(features)
# Record what ML would have done, but don't execute
log_shadow_decision(ml_decision, actual_r4_decision)
```

---

## Phase B: Portfolio Optimization (Post-Phase 2)

**Trigger:** Phase 2 evidence confirms R4 has a live edge.

**Objective:** Replace crude weight clipping with principled portfolio optimization.

### B1. Covariance Estimation

```python
# Target: Robust covariance estimation for 24-asset universe

Methods:
├── Sample covariance (baseline)
├── Shrinkage (Ledoit-Wolf)
├── Exponential weighting (recent data weighted more)
├── DCC-GARCH (dynamic conditional correlation)
└── Factor model covariance (PCA-based)
```

**Implementation:**
- `src/eigencapital/portfolio/covariance.py` — Covariance estimators
- `tests/unit/portfolio/test_covariance.py` — Estimator validation

### B2. Portfolio Optimization

```python
# Target: Risk-aware position sizing

Methods:
├── Hierarchical Risk Parity (HRP)
│   ├── Hierarchical clustering of assets
│   ├── Recursive bisection
│   └── Inverse variance allocation
├── Mean-Variance (Markowitz)
│   ├── Maximum Sharpe
│   ├── Minimum variance
│   └── Risk parity
├── Black-Litterman
│   ├── Market equilibrium returns
│   ├── Investor views (R4 signals)
│   └── Posterior returns
└── Risk budgeting
    ├── Equal risk contribution
    └── Custom risk budgets
```

**Implementation:**
- `src/eigencapital/portfolio/optimizer.py` — Portfolio optimizer
- `src/eigencapital/portfolio/hrp.py` — HRP implementation
- `src/eigencapital/portfolio/black_litterman.py` — BL implementation
- `tests/unit/portfolio/test_optimizer.py` — Optimizer tests

### B3. Integration with R4

```python
# Target: Use optimizer output as weight constraints

R4 Signal → Weight Clipping → Optimizer → Final Weights
                ↓                    ↓
         ±20% per asset    Risk-aware allocation
```

**Implementation:**
- Modify `scripts/r4_rebalance_loop.py` to use optimizer
- Add optimizer as optional step before order generation
- Feature-flag: `PORTFOLIO_OPTIMIZER_ENABLED = False`

---

## Phase C: Transaction Cost Modeling (Post-Phase 2)

**Trigger:** Planning for $25K+ capital scaling.

**Objective:** Model market impact and optimize execution.

### C1. Cost Model

```python
# Target: Estimate total transaction costs

Cost Components:
├── Spread cost (observable)
├── Commission (known)
├── Slippage (measured)
├── Market impact (modeled)
│   ├── Linear impact: impact = a * (order_size / ADV)
│   ├── Square-root impact: impact = a * sqrt(order_size / ADV)
│   └── Almgren-Chriss optimal execution
├── Opportunity cost (estimated)
└── Financing/swap (measured)
```

**Implementation:**
- `src/eigencapital/execution/cost_model.py` — Transaction cost model
- `src/eigencapital/execution/impact_model.py` — Market impact estimation
- `tests/unit/execution/test_cost_model.py` — Cost model tests

### C2. Execution Algorithms

```python
# Target: Optimize order execution

Algorithms:
├── TWAP (Time-Weighted Average Price)
│   └── Split order evenly over time window
├── VWAP (Volume-Weighted Average Price)
│   └── Match historical volume profile
├── Implementation Shortfall (IS)
│   └── Minimize deviation from decision price
└── Adaptive
    └── Adjust urgency based on market conditions
```

**Implementation:**
- `src/eigencapital/execution/algorithms.py` — Execution algorithms
- `src/eigencapital/execution/twap.py` — TWAP implementation
- `src/eigencapital/execution/vwap.py` — VWAP implementation

### C3. Cost-Aware Sizing

```python
# Target: Include costs in position sizing

current: size = risk_budget / stop_distance
proposed: size = risk_budget / (stop_distance + expected_cost)
```

---

## Phase D: Covariance-Aware Bet Sizing (Post-Phase 2)

**Trigger:** Phase 2 evidence confirms portfolio-level risk is acceptable.

**Objective:** Use portfolio covariance to adjust position sizes.

### D1. Portfolio Risk Metrics

```python
# Target: Compute portfolio-level risk metrics

Metrics:
├── Portfolio VaR (Historical, Parametric, Monte Carlo)
├── Portfolio CVaR (Expected Shortfall)
├── Marginal VaR (contribution of each position)
├── Component VaR
├── Incremental VaR
└── Diversification ratio
```

**Implementation:**
- `src/eigencapital/portfolio/risk_metrics.py` — Portfolio risk computation
- `tests/unit/portfolio/test_risk_metrics.py` — Risk metric tests

### D2. Risk-Budget Sizing

```python
# Target: Size positions based on portfolio risk contribution

Current: equal risk per position (implicit)
Proposed: equal risk contribution per position

if correlation(cluster_AUD) > 0.7:
    reduce AUDCAD, AUDUSD, NZDCAD, NZDUSD sizes
    until portfolio risk contribution is balanced
```

**Implementation:**
- `src/eigencapital/portfolio/risk_budget.py` — Risk budget allocation
- `tests/unit/portfolio/test_risk_budget.py` — Risk budget tests

---

## Implementation Order

```
Phase 2 Evidence Collection (NOW)
        │
        ▼
Phase 2 Verdict
        │
   ┌────┴────┐
   │         │
 PASS      FAIL
   │         │
   ▼         ▼
Phase A    Investigate
(ML Signal)    │
   │         └──→ Fix R4 or accept
   ▼
Phase B
(Portfolio Opt)
   │
   ▼
Phase C
(Cost Model)
   │
   ▼
Phase D
(Risk-Budget Sizing)
   │
   ▼
Phase 3
(Capital Scaling)
```

## Estimated Effort

| Phase | Component | Effort | Dependencies |
|-------|-----------|--------|--------------|
| A1 | Feature engineering | 2-3 weeks | None |
| A2 | Model training | 2-3 weeks | A1 |
| A3 | Signal combination | 1-2 weeks | A2 |
| A4 | Shadow validation | 2-4 weeks | A3 |
| B1 | Covariance estimation | 1-2 weeks | None |
| B2 | Portfolio optimizer | 2-3 weeks | B1 |
| B3 | R4 integration | 1-2 weeks | B2 |
| C1 | Cost model | 1-2 weeks | None |
| C2 | Execution algorithms | 2-3 weeks | C1 |
| C3 | Cost-aware sizing | 1 week | C2 |
| D1 | Portfolio risk metrics | 1-2 weeks | B1 |
| D2 | Risk-budget sizing | 1-2 weeks | D1, B2 |

**Total estimated:** 16-24 weeks of focused development

## Critical Constraint

> **All of this is deferred until Phase 2 evidence confirms R4 has a live edge.**

Adding ML models, portfolio optimization, or execution algorithms before proving the base strategy works would be premature optimization. The current priority is:

1. Let R4 run frozen
2. Collect live economic evidence
3. Prove or disprove the R4 hypothesis
4. Then build on top of a proven foundation

---

*This roadmap is derived from the ML4Trading book's structure and adapted to EigenCapital's current architecture and Phase 2 governance constraints.*
