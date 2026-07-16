# Analysis Scripts — Methodology Reference

## Production Audit

### `scripts/analysis/production_audit.py`
Comprehensive 18-phase forensic audit of the entire trade lifecycle. Runs all phases sequentially from `scripts/analysis/audit_phases/`. Produces structured JSON (`--output`) and terminal report.

**Methodology**: Reads pre-computed trade lifecycle data (`data/processed/trade_data/trade_lifecycle_results.json`), passes through 15 forensic phases (Phase 0 augments temporal data, Phases 1-17 are independent, Phase 18 aggregates + scores). Outputs scored recommendations (Alpha/Sigma/Info) with impact estimates.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/production_audit.py [--phases 4,7] [--output path.json]`

### Audit Phase Modules (`scripts/analysis/audit_phases/`)

| Phase | Module | Methodology |
|-------|--------|-------------|
| 0 | `scripts/analysis/audit_phases/phase_data.py` | Temporal metadata augmentation (session, hour, DOW, month from entry/exit dates). Defines shared constants (portfolio assets, tp/sl, sell-only set). |
| 1 | `scripts/analysis/audit_phases/phase1_lifecycle.py` | Enhanced lifecycle metrics: time-to-TP/SL, time-to-peak-MFE, time-from-peak-MFE-to-exit, portfolio-level percentiles. |
| 2 | `scripts/analysis/audit_phases/phase2_path_dependency.py` | Path quality from MAE/MFE/underwater/profitable fields: zero-crossings, underwater/profitable streaks, largest intra-reversal, MAE recovery rate. |
| 4-5 | `scripts/analysis/audit_phases/phase4_time_profitability.py` | Time-based profitability by hour, session (Sydney/Tokyo/London/NY + overlaps), DOW, week-of-month, month (seasonality). Uses scipy stats for significance. |
| 6 | `scripts/analysis/audit_phases/phase6_holding_period.py` | Force-close trades after N candles (sweep 1-500), measure impact on total_R, Sharpe, profit factor, max_dd, WR, expectancy. |
| 7 | `scripts/analysis/audit_phases/phase7_exit_strategies.py` | Compares 9 exit strategies: fixed barriers, adaptive exit (retracement trail), breakeven lock, hard trailing (33/50/67%), ATR trail, chandelier, time stop, vol-adjusted stop, hybrid. |
| 8 | `scripts/analysis/audit_phases/phase8_entry_quality.py` | Entry quality: distance from 10-bar HL, ATR position percentile, trend alignment (vs 20-bar MA), first-candle MAE, entry timing relative to signal. |
| 9 | `scripts/analysis/audit_phases/phase9_opportunity_cost.py` | Evaluates rejected (FLAT) signals: reconstructs counterfactual outcome, computes net filter contribution (PnL saved vs missed). |
| 11 | `scripts/analysis/audit_phases/phase11_overlap.py` | Trade overlap: simultaneous positions, correlated entries/exits, drawdown concentration, sector clustering. |
| 12 | `scripts/analysis/audit_phases/phase12_risk_of_ruin.py` | Monte Carlo simulation on trade sequence: DD breach probability, worst losing streak, 95/99% capital survival, cumulative return CIs. |
| 13 | `scripts/analysis/audit_phases/phase13_sensitivity.py` | Parameter perturbation: SL/TP multiplier (0.5-1.5x), confidence threshold (±0.05/0.10), position size (±20/50%), exit strategy gates, session filter. |
| 14 | `scripts/analysis/audit_phases/phase14_regime_transition.py` | Performance around regime transitions: trend↔range, vol regime shifts, bull↔bear. Tests whether exits should adapt to transitions. |
| 15 | `scripts/analysis/audit_phases/phase15_edge_decay.py` | Rolling WR/expectancy across trade sequence. Finds point where rolling expectancy turns negative. Tests force-close at edge decay. |
| 16 | `scripts/analysis/audit_phases/phase16_clustering.py` | K-means clustering on trade quality: duration, MAE, MFE, ATR%, session, confidence, efficiency, holding period. Identifies profitable signatures. |
| 17 | `scripts/analysis/audit_phases/phase17_portfolio_timing.py` | Per-asset session/hour/DOW profitability. Produces trading calendar recommendations. |
| 18 | `scripts/analysis/audit_phases/phase18_recommendations.py` | Aggregates all phases: classifies recommendations, estimates impact (Sharpe, max_dd, total_R, capital efficiency), assigns confidence, prioritizes. |

## Trade Lifecycle & Exit Analysis

### `scripts/analysis/trade_lifecycle.py`
Reconstructs every trade from walk-forward signal parquets + OHLCV data. Computes full lifecycle metrics across 18 phases. Core data source for all downstream analysis scripts.

**Methodology**: Maps each unresolved signal to an executed trade using barrier prices and OHLCV. Computes MFE, MAE, path efficiency, reversal rates, TP/SL outcomes per asset.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/trade_lifecycle.py --all [--phase 3-5]`

### `scripts/analysis/trailing_stop_sim.py`
Tests multiple trailing stop rules against reconstructed trades. Core simulation: for trades where MFE >= `require_min_mfe`, exit at `(1 - retrace_pct) * peak_MFE` instead of fixed SL.

**Methodology**: Conservative simulation — never clips winners (passes through unchanged). Only modifies loser exits. Returns (improvement_R, new_total_R, n_saved).

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/trailing_stop_sim.py`

### `scripts/analysis/robustness_gatekeeper.py`
5-test validation suite for the adaptive exit improvement:

1. **Regime robustness**: Split trades by ATR at entry (low/high vol), verify both regimes positive.
2. **Bootstrap**: 500 resamples, 95% CI on total_R for trailing vs fixed.
3. **Slippage sensitivity**: Adverse slippage of 0.5-4.0R, verify trailing still beats fixed baseline.
4. **Ablation comparison**: All trailing variants vs fixed on Sharpe.
5. **Benefit concentration**: Gini coefficient + top-N share of trailing benefit.

**Methodology**: Each test is a pure function operating on the trade lifecycle dataset. Tests are independent. Verdict derived from threshold comparisons.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/robustness_gatekeeper.py`

### `scripts/analysis/mfe_stationarity.py`
Validates trailing stop robustness to distribution drift:

1. **MFE stationarity**: KS test on MFE distributions between early/late halves of trade history.
2. **Walk-forward retrace stability**: Find optimal retrace% on period A, verify same optimum on period B.
3. **Reversal rate trend**: Quartile-by-quartile reversal rate (losers with MFE >= 1R).

**Methodology**: Split trade history chronologically, compare distributions via KS statistic (p > 0.05 = stationary). Retrace stability verified by rank correlation of retrace-level rankings across periods.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/mfe_stationarity.py`

### `scripts/analysis/shock_simulation.py`
Structural failure discovery. Applies 7 shock classes to realized MFE distribution and measures adaptive exit edge retention:

| Shock | Method |
|-------|--------|
| MFE compression | Scale MFE by 0.3-0.7 (vol decay) |
| Retrace acceleration | Increase effective retrace_pct by 10-35pp (spiky action) |
| Gap | Zero MFE on 5-20% of losers (black swan) |
| Multi-peak decoy | 10-25% of trades lose 30-70% MFE (false peaks) |
| Execution lag | 20-50% of trades lose 0.2-0.5R (delayed fills) |
| Correlated crash | 1-4R loss on 20-50% of overlapping (contagion) |
| Trend fragmentation | Progressive MFE tail compression |

**Severity**: PASS (>80% edge retention), MODERATE (50-80%), SEVERE (<50%), CATASTROPHIC (<0%).

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/shock_simulation.py [--scenario mfe_compression,correlated_crash]`

### `scripts/analysis/deep_dive_trail33.py`
6-test deep-dive for the `trail_33pct` exit strategy: per-asset breakdown, parameter sensitivity sweep (10-80%), bootstrap CI (5000 resamples), time stability, benefit concentration (Gini), worst-case drawdown scenario.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/deep_dive_trail33.py`

### `scripts/analysis/enhance_trailing.py`
Simulates enhanced trailing and scale-out exit strategies. Tests combinations of partial profit-taking (scale-out at N×R) with retracement trailing on remainder.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/enhance_trailing.py`

### `scripts/analysis/equity_curve_7025.py`
Generates equity curve chart for the 70%@2.5R + 15% retrace production config.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/equity_curve_7025.py`

### `scripts/analysis/robustness_7025.py`
Robustness gatekeeper specifically for 70%@2.5R + 15% retrace config. Same methodology as `scripts/analysis/robustness_gatekeeper.py` but parameterized for this specific exit strategy.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/robustness_7025.py`

### `scripts/analysis/robustness_6020.py`
Robustness gatekeeper for 60%@2.0R + 20% retrace exit strategy.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/robustness_6020.py`

## Comprehensive Profitability

### `scripts/analysis/comprehensive_profitability.py`
10-phase profitability report using current live config on walk-forward trade data: global performance, timeline, sessions, time-of-day, holding periods, profit accumulation, asset ranking, regime timing, portfolio concentration, recommendations.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/comprehensive_profitability.py`

## Re-Entry Policy Analysis

### `scripts/analysis/reentry_simulation.py`
Simulates 4 position-entry policies on reconstructed trade timelines:

| Policy | Max positions | Same-side re-entry |
|--------|--------------|-------------------|
| A (baseline) | 1 | No |
| B | 2 | Guarded (min_confidence=0.55, min_reentry_r=0.5) |
| C | 3 | Guarded |
| D | 2 | Unguarded (matches live engine) |

All enforce cross-side flipping. No production code is modified.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_simulation.py [--all] [--assets GC,USDCHF]`

### `scripts/analysis/reentry_metrics.py`
Computes performance, risk, and trade statistics from reentry simulation output.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_metrics.py --input /tmp/reentry_full_results.json`

### `scripts/analysis/reentry_statistics.py`
Bootstrap resampling, Monte Carlo simulation, regime analysis, and sensitivity sweeps for re-entry policy comparison.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_statistics.py`

### `scripts/analysis/reentry_report.py`
Per-asset deep dive, policy recommendation matrix, and production deployment recommendation.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/reentry_report.py`

## Threshold Validation

### `scripts/analysis/threshold_validation.py`
Walk-forward threshold comparison: trains ONCE per fold, caches raw probabilities, applies 0.45 and 0.40 thresholds post-hoc to the same predictions. Ensures apples-to-apples comparison.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/threshold_validation.py`

### `scripts/analysis/run_threshold_040.py`
Proper threshold comparison using the canonical `walk_forward_one()` pipeline. Runs both 0.45 and 0.40 with the same code path for apples-to-apples comparison.

**Usage**: `PYTHONPATH=$PYTHONPATH:. python scripts/analysis/run_threshold_040.py`

---

**Last updated:** 2026-07-07
