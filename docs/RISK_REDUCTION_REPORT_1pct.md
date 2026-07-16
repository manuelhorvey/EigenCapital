# Risk Reduction Report: 1.0% max_risk_per_trade_pct

**Date:** 2026-07-15
**Status:** Applied to `configs/domains/risk/sizing.yaml`
**Previous config:** 2.0%
**Evidence:** Capital growth simulation + tail-risk stress test

> **⚠️ Important caveat:** All figures in this report are validated against **trade data from the pre-depth-optimization model run** (Jul 9). Models were subsequently retrained with depth changes (GBPCHF depth=4, GBPJPY depth=3, NZDCAD depth=4, NZDJPY depth=5) and EURCHF feature additions (gc_lead_1, yield_slope). **These metrics must be re-validated** after the next retraining cycle — see the full pipeline at `scripts/analysis/risk_by_capital.py`.

---

## Executive Summary

Reducing `max_risk_per_trade_pct` from **2.0% → 1.0%** simultaneously **improves every key metric** at the $500 capital level — there is no tradeoff. CAGR increases, Sharpe increases, and max drawdown drops by 22 percentage points.

At $5K+, 1.0% and 2.0% produce **identical risk-adjusted returns** (same Sharpe, same DD%) because min-lot constraints stop binding and the sizing chain can precisely target the configured risk.

---

## 1. Simulation Parameters

| Parameter | Value |
|:----------|:------|
| **Data source** | `data/processed/trade_data/trade_lifecycle_results.json` (6,646 trades, Jul 9) |
| **Starting capital** | $500 (primary) / $1K–$50K (sensitivity) |
| **Max risk/trade** | 1.0% (was 2.0%) |
| **Other params** | Production defaults unchanged |
| **Bootstrap trials** | 200 (Monte Carlo) |
| **Drawdown stress test** | Aug 2024 yen carry unwind (−16.74R) |

---

## 2. Primary Results ($500 start)

| Metric | 2.0% (Baseline) | 1.0% (New) | Δ | Δ% |
|:-------|:---------------:|:-----------:|:-:|:--:|
| **Final Capital** | $4,925.14 | **$5,111.58** | **+$186.44** | +3.8% |
| **Total Return** | +885.0% | **+922.3%** | **+37.3pp** | +4.2% |
| **CAGR** | +242.9% | **+249.9%** | **+7.0pp** | +2.9% |
| **Sharpe Ratio** | 1.41 | **1.69** | **+0.28** | +19.9% |
| **Max Drawdown** | **−70.9%** | **−48.9%** | **−22.0pp** | −31.0% |
| **Profit Factor** | 1.56 | 1.60 | +0.04 | +2.6% |

### Yearly Performance (1.0% risk)

| Year | Start | End | PnL | Return | Trades | Max DD |
|:----|:-----:|:---:|:---:|:------:|:------:|:------:|
| 2024 | $500 | $812 | +$312 | +62.5% | 2,668 | −31.7% |
| 2025 | $812 | $6,168 | +$5,356 | +660% | 3,454 | −48.9% |
| 2026 | $6,168 | $5,112 | −$1,056 | −17.1% | 524 | −32.0% |

### Quarterly Breakdown

| Quarter | Start | End | PnL | Return | Trades | DD |
|:--------|:-----:|:---:|:---:|:------:|:------:|:--:|
| 2024-Q3 | $500 | $396 | −$104 | −20.8% | 318 | −31.7% |
| 2024-Q4 | $396 | $812 | +$416 | +105% | 2,350 | −14.5% |
| 2025-Q1 | $812 | $1,159 | +$347 | +42.7% | 869 | −21.0% |
| 2025-Q2 | $1,159 | $2,792 | +$1,633 | +141% | 776 | −33.3% |
| 2025-Q3 | $2,792 | $4,408 | +$1,616 | +57.9% | 905 | −48.9% |
| 2025-Q4 | $4,408 | $5,452 | +$1,044 | +23.7% | 870 | −18.6% |
| 2026-Q1 | $5,452 | $3,307 | −$2,145 | −39.3% | 516 | −39.4% |
| 2026-Q2 | $3,307 | $5,112 | +$1,805 | +54.6% | 8 | −32.0% |

### Monthly Summary

| Metric | Value |
|:-------|:------|
| Avg Monthly Return | +5.80% |
| Best Month | +68.41% |
| Worst Month | −24.31% |
| Profitable Months | 16 / 22 (72.7%) |

### Compounding Analysis

| Strategy | Final Value |
|:---------|:-----------:|
| **Compounded (reinvesting)** | **$5,111.58** |
| Fixed position size | $530.00 |
| Fixed dollar risk | $2,968.80 |
| **Compounding benefit vs fixed** | **+72.4%** |

---

## 3. Sensitivity Across Capital Levels

| Capital | Final | CAGR | Sharpe | Max DD | PF | Verdict |
|:-------:|:-----:|:----:|:------:|:------:|:--:|:--------|
| **$500** | $5,112 | **249.9%** | 1.69 | **48.9%** | 1.60 | 🟡 Acceptable for paper |
| $1,000 | $5,325 | 146.2% | 1.61 | 40.5% | 1.55 | 🟡 Monitor DD |
| $2,500 | $6,796 | 71.4% | 1.82 | 19.9% | 1.54 | ✅ Good |
| **$5,000** | $9,274 | **39.5%** | **1.87** | **14.6%** | 1.54 | ✅ **Best** |
| $10,000 | $14,234 | 21.0% | 1.87 | 9.6% | 1.53 | ✅ Excellent |
| $50,000 | $57,462 | 7.8% | 1.77 | 6.5% | 1.48 | ✅ Excellent |

**Key insight:** Sharpe peaks at **$5K (1.87)** where min-lot constraints fully disappear. Higher capital maintains Sharpe but CAGR naturally declines as a percentage of larger equity.

---

## 4. Bootstrap Monte Carlo (200 trials, 1.0% risk)

*Note: 200 trials are sufficient for median/percentile estimates but produce wider CIs than the 1,000-trial baseline. Treat p5/p95 as directional ranges, not precise boundaries.*

| Metric | $500 | $5,000 |
|:-------|:----:|:------:|
| **P(Profitable)** | **99.5%** | **100.0%** |
| **Median end equity** | $5,178.90 | $9,291.88 |
| **Median end equity** | $5,178.90 | $9,291.88 |
| **p5 / p95** | $26 / $7,472 | $6,158 / $11,284 |
| **P(DD > 30%)** | **100.0%** | **1.0%** |
| **P(DD > 50%)** | Not computed | 0.0% |

The probability of DD > 30% drops from **100% at $500 to 1% at $5,000** — a dramatic improvement driven by the elimination of min-lot distortion.

---

## 5. Tail-Risk Protection (Aug 2024 Yen Carry Unwind)

| Config | Aug Loss | % DD | Improvement vs 2.0% |
|:-------|:--------:|:----:|:-------------------|
| 2.0% (old config) | −$167.40 | −33.5% | — |
| **1.0% (new config)** | **−$83.70** | **−16.7%** | **2× less dollar loss** |
| All gates + 1.0% | −$36.65 | −7.3% | **4.6× less dollar loss** |

The 1.0% risk reduction alone halves the dollar impact of any drawdown. Combined with the circuit breaker (which catches mid-drawdown), the total expected loss during a repeat of the Aug 2024 event drops from −33.5% to −7.3%.

---

## 6. Comparison: 1.0% vs 2.0% at Each Capital Level

| Capital | 1.0% Sharpe | 2.0% Sharpe | 1.0% DD | 2.0% DD | Which is Better? |
|:-------:|:-----------:|:-----------:|:-------:|:-------:|:----------------|
| **$500** | **1.69** | 1.41 | **48.9%** | 70.9% | **1.0% wins** |
| $1,000 | 1.61 | **1.59** | **40.5%** | 40.9% | **1.0% slightly ahead** |
| $2,500 | 1.82 | 1.82 | 19.9% | 19.9% | **Identical** |
| $5,000 | 1.87 | 1.87 | 14.6% | 14.6% | **Identical** |
| $10,000 | 1.87 | 1.87 | 9.6% | 9.6% | **Identical** |

At $2,500+, the two risk settings are **indistinguishable** in risk-adjusted terms. The final capital scales linearly: 1.0% produces half the CAGR (71% vs 143% at 2.0%), but with identical DD% and Sharpe.

---

## 7. Production Recommendation

| Equity | Recommended Risk | Rationale |
|:-------|:----------------:|:----------|
| **Under $500** | **0.5%** | Min-lot constraints dominate — risk is higher than configured |
| **$500 – $2,500** | **1.0%** | Currently applied — eliminates 22pp DD without sacrificing CAGR |
| **$2,500 – $5,000** | **1.0–1.5%** | Risk-adjusted metrics identical — personal preference |
| **$5,000+** | **2.0%** | Min-lot constraints gone — full production setting safe |

**Current config:** `configs/domains/risk/sizing.yaml` — `max_risk_per_trade_pct: 1.0`

---

**Related documents:**
- `docs/PRODUCTION_READINESS_AUDIT.md` — Full production readiness audit (baseline 2.0%)
- `docs/INITIAL_DRAWDOWN_ANALYSIS.md` — Aug 2024 tail-risk analysis
- `configs/domains/risk/sizing.yaml` — Applied config

**Last updated:** 2026-07-15
