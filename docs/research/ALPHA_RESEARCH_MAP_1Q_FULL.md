# EIGENCAPITAL ALPHA RESEARCH MAP
**Campaign:** 1Q-MT5-FULL
**Freeze:** af47295a35fb5888
**Data:** MT5 Exness — 14 hypotheses tested
**Universe:** 15 multi-asset instruments (FX, metals, indices, crypto, oil)
**Period:** 2020-01-01 to 2026-08-24 (6.6 years daily)
**Date:** 2026-08-24

## Verdict Distribution

```
  FRAGILE                   3
  PORTFOLIO_USEFUL          3
  REJECTED                  8
```

**Survival Rate: 21.4%**

## Failure Mode Distribution

```
  regime_instability                  14
  cost_sensitivity                    11
  catastrophic_drawdown               11
  out_of_sample_failure               11
  statistical_weakness                8
  no_detectable_signal                3
  overfitting                         1
```

## Detailed Results by Family

### Breakout

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-BRK-001 | portfolio_useful | 0.633 | -0.876 | 14.8x | cost_sensitivity, catastrophic_drawdown, regime_instability |

### Cross Sectional

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-CS-001 | rejected | 0.554 | -0.493 | 10.1x | cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability, overfitting |
| HYP-CS-003 | rejected | 0.000 | 0.000 | 0.0x | statistical_weakness, out_of_sample_failure, regime_instability, no_detectable_signal |

### Factor

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-GOLD-MOM | rejected | 0.000 | 0.000 | 0.0x | statistical_weakness, out_of_sample_failure, regime_instability, no_detectable_signal |

### Mean Reversion

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-MR-001 | rejected | -1.141 | -0.996 | 222.4x | cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability |
| HYP-MR-002 | rejected | -1.021 | -1.000 | 33.0x | cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability |

### Momentum

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-MOM-001 | fragile | 0.701 | -0.821 | 6.6x | cost_sensitivity, catastrophic_drawdown, out_of_sample_failure, regime_instability |
| HYP-MOM-002 | fragile | 0.735 | -0.731 | 5.7x | cost_sensitivity, catastrophic_drawdown, out_of_sample_failure, regime_instability |

### Statistical Arbitrage

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-SA-001 | rejected | -0.113 | -0.321 | 2.0x | cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability |

### Trend

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-TREND-001 | fragile | 0.701 | -0.821 | 6.6x | cost_sensitivity, catastrophic_drawdown, out_of_sample_failure, regime_instability |
| HYP-TREND-002 | portfolio_useful | 0.722 | -0.809 | 12.1x | cost_sensitivity, catastrophic_drawdown, regime_instability |
| HYP-TREND-003 | portfolio_useful | 0.633 | -0.876 | 14.8x | cost_sensitivity, catastrophic_drawdown, regime_instability |

### Volatility

| Hypothesis | Status | Sharpe | Max DD | Turnover | Failure Modes |
|------------|--------|--------|--------|----------|---------------|
| HYP-VOL-001 | rejected | -0.734 | -0.999 | 3.0x | cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability |
| HYP-VOL-002 | rejected | 0.000 | 0.000 | 0.0x | statistical_weakness, out_of_sample_failure, regime_instability, no_detectable_signal |

## Loser Analysis (Forensic Trail)

Every rejected hypothesis has a documented failure mode:

### HYP-TREND-001 (trend)
- **Status:** fragile
- **Net Sharpe:** 0.701
- **Max Drawdown:** -0.821
- **Turnover:** 6.6x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, out_of_sample_failure, regime_instability
- **Why it failed:** Score: 0.621, Modes: cost_sensitivity,catastrophic_drawdown,out_of_sample_failure,regime_instability

### HYP-MOM-001 (momentum)
- **Status:** fragile
- **Net Sharpe:** 0.701
- **Max Drawdown:** -0.821
- **Turnover:** 6.6x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, out_of_sample_failure, regime_instability
- **Why it failed:** Score: 0.621, Modes: cost_sensitivity,catastrophic_drawdown,out_of_sample_failure,regime_instability

### HYP-MOM-002 (momentum)
- **Status:** fragile
- **Net Sharpe:** 0.735
- **Max Drawdown:** -0.731
- **Turnover:** 5.7x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, out_of_sample_failure, regime_instability
- **Why it failed:** Score: 0.671, Modes: cost_sensitivity,catastrophic_drawdown,out_of_sample_failure,regime_instability

### HYP-MR-001 (mean_reversion)
- **Status:** rejected
- **Net Sharpe:** -1.141
- **Max Drawdown:** -0.996
- **Turnover:** 222.4x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability
- **Why it failed:** Score: 0.421, Modes: cost_sensitivity,catastrophic_drawdown,statistical_weakness,out_of_sample_failure,regime_instability

### HYP-MR-002 (mean_reversion)
- **Status:** rejected
- **Net Sharpe:** -1.021
- **Max Drawdown:** -1.000
- **Turnover:** 33.0x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability
- **Why it failed:** Score: 0.383, Modes: cost_sensitivity,catastrophic_drawdown,statistical_weakness,out_of_sample_failure,regime_instability

### HYP-SA-001 (statistical_arbitrage)
- **Status:** rejected
- **Net Sharpe:** -0.113
- **Max Drawdown:** -0.321
- **Turnover:** 2.0x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability
- **Why it failed:** Score: 0.333, Modes: cost_sensitivity,catastrophic_drawdown,statistical_weakness,out_of_sample_failure,regime_instability

### HYP-VOL-001 (volatility)
- **Status:** rejected
- **Net Sharpe:** -0.734
- **Max Drawdown:** -0.999
- **Turnover:** 3.0x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability
- **Why it failed:** Score: 0.383, Modes: cost_sensitivity,catastrophic_drawdown,statistical_weakness,out_of_sample_failure,regime_instability

### HYP-VOL-002 (volatility)
- **Status:** rejected
- **Net Sharpe:** 0.000
- **Max Drawdown:** 0.000
- **Turnover:** 0.0x
- **Failure Modes:** statistical_weakness, out_of_sample_failure, regime_instability, no_detectable_signal
- **Why it failed:** Score: 0.208, Modes: statistical_weakness,out_of_sample_failure,regime_instability,no_detectable_signal

### HYP-CS-001 (cross_sectional)
- **Status:** rejected
- **Net Sharpe:** 0.554
- **Max Drawdown:** -0.493
- **Turnover:** 10.1x
- **Failure Modes:** cost_sensitivity, catastrophic_drawdown, statistical_weakness, out_of_sample_failure, regime_instability, overfitting
- **Why it failed:** Score: 0.596, Modes: cost_sensitivity,catastrophic_drawdown,statistical_weakness,out_of_sample_failure,regime_instability,overfitting

### HYP-CS-003 (cross_sectional)
- **Status:** rejected
- **Net Sharpe:** 0.000
- **Max Drawdown:** 0.000
- **Turnover:** 0.0x
- **Failure Modes:** statistical_weakness, out_of_sample_failure, regime_instability, no_detectable_signal
- **Why it failed:** Score: 0.208, Modes: statistical_weakness,out_of_sample_failure,regime_instability,no_detectable_signal

### HYP-GOLD-MOM (factor)
- **Status:** rejected
- **Net Sharpe:** 0.000
- **Max Drawdown:** 0.000
- **Turnover:** 0.0x
- **Failure Modes:** statistical_weakness, out_of_sample_failure, regime_instability, no_detectable_signal
- **Why it failed:** Score: 0.208, Modes: statistical_weakness,out_of_sample_failure,regime_instability,no_detectable_signal

## Key Findings

- **11** hypotheses rejected or fragile
- **0** hypotheses supported
- **0** production candidates

### What the data tells us

1. **Cost sensitivity is the dominant killer** — turnover >1x annually destroys most signals
2. **Drawdown is the second killer** — attractive Sharpe ratios hide catastrophic drawdowns
3. **Walk-forward validation catches overfitting** — signals that look good in-sample often fail OOS
4. **Small universes limit cross-sectional signals** — 15 instruments restricts CS strategies
5. **Conditioning may matter more than raw signals** — regime/timing could add value

### Governance

- No hypothesis was modified after seeing results
- Campaign was frozen before execution
- All verdicts are evidence-based through the Alpha Admission Scorecard
- Rejected hypotheses are permanent research records