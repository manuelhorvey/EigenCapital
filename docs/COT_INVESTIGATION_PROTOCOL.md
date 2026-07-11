**Last updated:** 2026-07-10

# COT Investigation Protocol — 15 Phases

## Research Principles

> This investigation must be **hypothesis-driven rather than confirmation-driven**. The objective is **not** to prove that COT should return or remain removed. The objective is to determine, using **reproducible experiments** and **statistically rigorous analysis**, whether COT creates measurable value in any role within the system. Every hypothesis must be tested against empirical evidence, and **negative results should be documented with the same rigor as positive findings**.

> Every conclusion must be supported by:
> 1. **Counterfactual experiments** — not just observational analysis
> 2. **Economic rationale** — not just statistical significance
> 3. **Point-in-time data** — strict look-ahead prevention
> 4. **Cross-validation** — against both backtest and forward-test results
> 5. **Clearly documented negative results** — with the same detail as positive findings

---

## Phase 1 — Audit the Previous COT Implementation

Determine whether the previous implementation was ever capable of producing a non-zero COT feature.

**Counterfactual experiment**: Reconstruct the exact data pipeline state at the time of the last model training. Check the parquet file timestamps, the cot_raw_parquet existence, and whether try/except blocks silently caught all COT loading.

**Test**: Can we reproduce a non-zero COT feature vector by running the original pipeline on any date?

**Deliverable**: A definitive answer to: "Was the COT feature ever actually computed, or was it always zero?"

---

## Phase 2 — Was COT Being Used for the Wrong Purpose?

Determine whether COT was incorrectly treated as a short-term predictive feature.

**Economic rationale required**: For each COT trader category (commercial, leveraged money, asset manager, non-reportable), document:
- What economic function do they serve?
- What is their expected positioning during trends, reversals, and range-bound markets?
- Is net long/short positioning economically meaningful for FX (vs. commodities where commercial hedging has a clear directional bias)?
- Does the existing feature engineering (z-score, change_4w) align with the economic meaning, or does it measure something else entirely?

**Counterfactual**: If COT were the correct type of feature (slow, structural), what would a properly-designed version look like?

---

## Phase 3 — Predictive Value Analysis

Run counterfactual walk-forward backtests with strictly point-in-time COT data (3-day release lag enforced).

| Experiment | Feature Set | Hypothesis |
|------------|-------------|------------|
| A — Baseline | Current (no COT) | Current production state |
| B — Placeholder COT | Current + old zero-valued COT columns | Zero-value columns → zero contribution |
| C — Proper COT (direct) | Current + cot_features outputs as ML features | Proper COT features improve IC |
| D — Proper COT (regime) | Current (COT as non-ML overlay) | COT improves trading metrics without entering the model |

**Metrics**: Gain importance, SHAP values, permutation importance, mutual information, conditional permutation importance.

**Thresholds**: Non-zero gain importance in ≥3/22 assets, or statistically significant Sharpe improvement (bootstrap p < 0.10).

---

## Phase 4 — Horizon Compatibility

**Counterfactual experiment**: Train a model using only weekly data (Tuesday close) with COT features. Compare against daily model.

**Test**: Plot IC(COT_feature, forward_return) as a function of days-since-measurement. Determine the half-life of COT's predictive content.

---

## Phase 5 — Regime Filter Evaluation

Implement `apply_cot_regime_gate` as a decision pipeline stage. Walk-forward replay with gate ON vs OFF.

**Regimes to test**:
1. Normal positioning → no modification
2. Extreme speculator long (cot_index > 0.90) → reduce confidence by 20%
3. Extreme speculator short (cot_index < 0.10) → reduce confidence by 20%
4. Commercial/leveraged divergence → increase confidence for contrarian signals
5. Multi-asset crowding → portfolio-level position size reduction

---

## Phase 6 — Portfolio Overlay Simulation

| Variant | Description | Expected effect |
|---------|-------------|-----------------|
| V1 — Confidence adj | COT modifies model confidence by ±10-20% | Improved calibration, unchanged trade frequency |
| V2 — Position sizing | COT scales position size 25-100% | Reduced DD, unchanged WR |
| V3 — Trade suppression | COT blocks trades at extreme positioning | Higher WR, lower frequency |

**Metrics**: Sharpe, max DD, Win Rate, Profit Factor, Calmar, Trade frequency.

---

## Phase 7 — Trend Confirmation Analysis

Stratify trades by trend strength (mom_21d quartiles). Within each quartile, compare COT-confirmed vs COT-contradicted trades.

**Test**: Trend breakout + increasing speculator participation vs Trend breakout + commercial hedging against move.

---

## Phase 8 — Extreme Positioning Analysis

Define extreme positioning as cot_index < 0.10 or > 0.90. Bootstrap extreme-event returns against random sampling (10,000 resamples, 95% CI).

**Economic rationale**: Extreme positioning is a structural condition, not a timing signal.

---

## Phase 9 — Asset-Level Evaluation

Run 3 walk-forward backtests per asset (22 assets × 3 variants = 66 backtests):
1. No COT (current baseline)
2. COT as ML feature
3. COT as overlay

Per-asset delta table.

---

## Phase 10 — Production Cost vs Benefit

Cost dimensions: data acquisition, storage, compute, pipeline latency, external dependency, failure mode, maintenance.

Benefit only quantifiable after Phases 3-9.

---

## Phase 11 — Alternative Architectures

| Architecture | Integration Point | File | Function |
|-------------|-------------------|------|----------|
| Decision pipeline stage | After `apply_confidence_gate` | `paper_trading/execution/decision_pipeline.py` | New `apply_cot_sentiment_gate()` |
| Position sizing modifier | In sizing chain | `shared/sizing_chain.py` | New `apply_cot_sizing_modifier()` |
| Portfolio health | Correlation monitor | `paper_trading/orchestrator/correlation.py` | Extend `CorrelationMonitor` |
| Confidence calibration | Calibration layer | `shared/calibration/calibrator.py` | Conditional calibration split |
| Daily regime cache | Data fetch layer | `features/data_fetch.py` | Weekly COT fetch + daily reindex |

---

## Phase 12 — Interaction Effects & Synergy Analysis

**Hypotheses**:

| Interaction | Hypothesis |
|-------------|------------|
| COT × Trend | COT confirms momentum signals only during established trends |
| COT × Volatility | COT adds value only during low-vol regimes |
| COT × Regime | COT is valuable in RANGE regimes (positioning extreme = potential breakout) |
| COT × Macro | COT + DXY momentum together predict FX reversals better than either alone |
| COT × Confidence | COT improves calibration by adjusting overconfident wrong-way predictions |
| COT × Asset class | COT works for major FX but not for crosses or commodities |

**Methods**: SHAP interaction values, Friedman H-statistics, partial dependence plots, conditional permutation importance.

---

## Phase 13 — Forward-Test Replay

Three versions: A (No COT), B (COT as ML feature), C (COT as overlay).

14 metrics: Net Profit, Sharpe, Sortino, Calmar, Max DD, Win Rate, Expectancy, Profit Factor, Trade Frequency, Avg Holding Time, VaR(95) DD, Recovery Time, Capital Efficiency, P(positive return).

Bootstrap 10,000 resamples. Report 95% CI for Δ values.

---

## Phase 14 — Decision Matrix

| Architecture | Predictive Benefit | Trading Benefit | Complexity | Op Cost | Recommendation |
|-------------|:---:|:---:|:---:|:---:|:---:|
| Remove completely | — | — | None | None | Default |
| ML feature (old impl) | Zero | Zero | Medium | Low | Reject if zero gain |
| ML feature (proper impl) | Phase 3 | Phase 3 | Medium | Low | Tentative |
| Regime filter | N/A | Phases 5-7 | Low | Low | Strong candidate |
| Risk overlay | N/A | Phase 6 | Low | Low | Strong candidate |
| Position sizing | N/A | Phase 6 | Low | Low | Strong candidate |
| Confidence adjustment | N/A | Phase 6 | Low | Low | Moderate |
| Hybrid | N/A | Combined | Medium | Low | Best candidate |
| Portfolio allocation | N/A | Phase 11 | Medium | Low | Secondary |

**Decision rule**: ΔSharpe ≥ 0.10 AND ΔDD ≥ -0.10 → PROMOTE. ΔSharpe ≥ 0.05 AND ΔDD ≥ -0.05 → CONSIDER. All others → REJECT.

---

## Phase 15 — Implementation Blueprint

**Only produced if Phases 3-14 justify reintroduction.**

Sections: System architecture, Integration points, Data pipeline, Feature engineering, Decision engine, Position sizing, Configuration, Failure handling, Monitoring, Testing (unit/integration/stress), Rollout plan, Rollback plan.

---

*Last updated: 2026-07-11*
