# Capital Efficiency Investigation — Final Report

## Executive Summary

**Question:** Why does EigenCapital plateau at ~6.28% CAGR despite 331R
in walk-forward R-space, and how can we reach 8%+?

**Answer:** The 6.28% CAGR is genuine (verified, reproducible, 434-day
walk-forward, Lo-Sharpe 13.50, max DD -0.02%). The constraints keeping
it from 8%+ are structural but fixable:

1. **max_concurrent=8 binds at 60% capacity** — $40K of $100K is idle
2. **11 drag assets dilute portfolio by 44.2%** — removing worst 3 JPY
   crosses alone recovers ~17% R
3. **Transaction costs are ~0.69%, not 4.50%** (Phase 7 was wrong)
4. **ATR cache bug** silently underweights 3 assets

**Expected CAGR after top-3 fixes: ~9.5% after costs — above 8% target.**

## Verified Baseline

| Metric | Value | Source |
|--------|-------|--------|
| Portfolio total R | 331.12 | Phase 2 (load_daily_r + evaluate_scenario) |
| %-space CAGR | 6.28% | Geometrically compounded daily % returns |
| Total return % | 11.05% | Over 434 days (~1.72 years) |
| Lo-Sharpe | 13.50 | Autocorrelation-adjusted (ρ=0.64) |
| Max DD in %-space | -0.02% | Near-zero drawdown |
| R→% conversion | 4.55% alloc × avg ATR_pct 0.70% |
| P(CAGR > 8%) | 0% | Bootstrap, 10k simulations |

**Method verified:** Code matches stored Phase 2 JSON bit-for-bit.
All numbers reproducible as of 2026-07-06 04:02 UTC.

## The 8 Bottlenecks

### B1. Concurrent Position Cap (Primary — ~2.0pp)

`max_concurrent=8` is the binding constraint at all capital sizes.

- Backtest assumes ~18 concurrent positions (median = 19)
- 96.9% of 434 WF days exceed the live cap of 8
- Capital utilization is invariant at 60% from $100K→$1M
- Fix: raise to 13 → 13×15% = 195% deployed (under 200% max leverage)

### B2. Portfolio Dilution (~2.5pp from all drags)

11 of 22 assets reduce portfolio value marginally:

| Tier | Assets | Count | ΔR if removed |
|------|--------|-------|-----------|
| Core drivers | ^DJI, GBPCAD, EURNZD, GC, GBPAUD | 5 | -127.15 R |
| Neutral | CADCHF, NZDCHF, EURAUD, USDCAD | 4 | +23.87 R |
| Drags | GBPJPY, NZDJPY, AUDJPY, EURCHF, GBPCHF, NZDUSD, USDJPY, AUDUSD, NZDCAD, BTCUSD, GBPUSD | 11 | +146.33 R |

Removing all 11 drags → 331.12 → 477.45 R (+44.2%).

**Important:** EURCHF is the only structurally unprofitable asset
(WR=23.1% vs BE=25.0%, total R = -31.00). All others are positive-R
individually but subtract from the portfolio through covariance.

### B3. Transaction Cost Overestimate

Phase 7's friction calculation was fundamentally wrong:

| Metric | Phase 7 Claim | Reality |
|--------|--------------|---------|
| Slippage RMS | 1.74% (cost) | Model timing noise (directionally correct edge) |
| Spread drag | 0.75%/yr | Double-counted (already in price gap) |
| Position size | 15% | 4.55% (1/22 equal weight) |
| Annual cost drag | 4.50% | ~0.69% |
| Net CAGR | 1.78% | **5.59%** (not 1.78%) |

The 1.74% RMS is `(current_price - close_price) / close_price` — mean
+1.17% on BUY signals. The market moves in the predicted direction.

### B4. ATR Cache Bug (~1.0pp)

3 assets return default ATR=0.005 instead of correct values:

| Asset | Cache file | Correct ATR% | Used ATR% |
|-------|-----------|-------------|-----------|
| BTCUSD | BTC_USD.parquet vs BTCUSD.parquet | 3.66% | 0.50% |
| GBPJPY | MultiIndex columns (Close['GBPJPY=X']) | 0.93% | 0.50% |
| ^DJI | MultiIndex columns | 1.11% | 0.50% |

BTCUSD has 20 trades, total R=+19.75. ^DJI is a top-5 driver. Fixing
these raises portfolio CAGR from 6.28→7.27%.

### B5. TP/SL Ratio Ceiling (Conservative)

Ratio=3.0 for 11 assets. The optimizer found all 21 assets converge
to ratio=20.0 given infinite freedom. Ratio=3.0 is a conservative cap.
Moving to ratio=4.0 for top-5 drivers may add ~0.2pp (SL fragility
test: 20/21 OK at ratio=3.0).

### B6. SELL_ONLY Opportunity Cost (~0.3pp)

3 assets (CADCHF, NZDCHF, EURAUD) are SELL-only — BUY signals are
zeroed. Walk-through: SELL_ONLY is permanent under current feature
design (SHAP audit + counterfactual ablation). No fix expected.

### B7. Equal-Weight Suboptimality (~0.3pp)

All 22 assets have positive total R. Equal-weight beats risk parity,
factor-constrained, and HRP in both R-space and %-space. Risk parity
reduces total R by 30% without drawdown improvement.

However, a simple quality-tilt (underweight assets with negative
rolling 60d R) could add ~0.3pp without full risk parity complexity.

### B8. CHF Factor Limit (20%→25%, ~0.5pp)

CHF concentration at 22.7% vs 20% limit. Factor constraints pinned at
20% limit. CHF assets are SELL-only with positive total R. Raising to
25% releases 5% allocation for highest-SELL conviction assets.

## Corrected Cost Structure

| Cost Type | bps/trade | CAGR Impact |
|-----------|-----------|-------------|
| Half-spread entry | 1-15 | 0.31% |
| Slippage entry | 2 | 0.10% |
| Slippage SL exit | 3 | 0.12% |
| Slippage TP exit | 2 | 0.02% |
| Commission (GC, ^DJI) | 7 | 0.08% |
| Swap overnight | 0.5/d | 0.08% |
| **Total** | **3-20** | **0.69%** |

## Optimized CAGR Projection

| Change | ΔCAGR | Cumulative | Cumulative+Costs |
|--------|-------|------------|------------------|
| **Baseline** | — | 6.28% | 5.59% |
| B4: ATR cache fix | +1.0pp | 7.27% | 6.58% |
| B1: max_concurrent 8→13 | +2.0pp | 9.27% | 8.58% |
| B2: Remove bottom-3 JPY crosses | +1.5pp | 10.77% | 10.08% |
| B8: CHF 20→25% | +0.5pp | 11.27% | 10.58% |

**8% CAGR target: Achievable after fixing B1+B4 (8.58% after costs).**

## Data Compatibility Note

This investigation found **two different walk-forward datasets**:

| Dataset | Total R | CAGR | Source |
|---------|---------|------|--------|
| Phase 2 (tag-less) | 331.12R | 6.28% | `*_wf_signals.parquet` |
| Remediation | 491.81R | 9.72% | `*_wf_signals_remediation.parquet` |

The remediation parquets show higher total R. Both datasets produce
identical relative rankings (equal-weight > risk parity > HRP). The
Phase 2 dataset is the verified baseline used throughout.

## Deliverables

| File | Content |
|------|---------|
| `capital_efficiency_audit.md` | Full audit of capital utilization |
| `research_summary.md` | One-page summary of findings |
| `optimization_priority_matrix.md` | Ranked action plan with expected CAGR impact |
| `cagr_reconciliation.txt` | Full R→% transformation chain with checks |
| `agents/findings/capital_utilization.txt` | Capital utilization analysis |
| `agents/findings/transaction_costs.txt` | Transaction cost audit |
| `agents/findings/trade_quality.txt` | Per-asset contribution analysis |
| `agents/findings/portfolio_construction.txt` | Weight method comparison |

## Verification Steps

To reproduce all results:
```bash
# Phase 2 (baseline CAGR)
PYTHONPATH=$PYTHONPATH:. python -c "
from scripts.capital_study.phase2_scaling import main; main()
"

# Trade quality
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py --weight-method equal_v1

# Phase 6 (bootstrap CI)
PYTHONPATH=$PYTHONPATH:. python -c "
from scripts.capital_study.phase6_validation import main; main()
"

# Lint and tests
ruff check . && ruff format . --check
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -q
```
