#!/usr/bin/env python3
"""
Risk-by-Capital Recommendation Table.

Tests 1.0% vs 2.0% risk at multiple capital levels ($500 to $50K)
and produces the risk-by-capital recommendation table.

Use after any retraining cycle to re-validate the risk configuration.
The trade data must be regenerated (via trade_lifecycle.py) for fresh
results; otherwise the simulation replays historical trades.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/risk_by_capital.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT))

from scripts.backtest.capital_growth_simulation import (
    SizingParams,
    load_trades,
    run_simulation,
    compute_performance_metrics,
    run_bootstrap_monte_carlo,
)

trades = load_trades()
print(f"Loaded {len(trades)} trades\n")

CAPITALS = [500, 1000, 2500, 5000, 10000, 50000]
RISKS = [1.0, 2.0]

# ── Full table ──
print("=" * 85)
print("  RISK-BY-CAPITAL: 1.0% vs 2.0%")
print("=" * 85)
print()
print(f"  {'Capital':>8} {'Risk%':>6} {'Final':>12} {'CAGR':>9} {'Sharpe':>8} {'Max DD':>8} {'PF':>6}")
print(f"  {'-'*8} {'-'*6} {'-'*12} {'-'*9} {'-'*8} {'-'*8} {'-'*6}")

for capital in CAPITALS:
    for risk in RISKS:
        params = SizingParams(max_risk_per_trade_pct=risk)
        state = run_simulation(trades, float(capital), params)
        m = compute_performance_metrics(state, float(capital))
        print(f"  ${capital:>5,}   {risk:>4.1f}%  ${m['final_capital']:>9,.2f}  {m['cagr_pct']:>+7.2f}%  "
              f"{m['sharpe_ratio']:>7.4f}  {m['max_drawdown_pct']:>6.1f}%  {m['profit_factor']:>5.2f}")

print()
print("=" * 85)
print("  KEY FINDINGS")
print("=" * 85)
print()

for risk in [1.0, 2.0]:
    params = SizingParams(max_risk_per_trade_pct=risk)
    state_500 = run_simulation(trades, 500.0, params)
    state_5k = run_simulation(trades, 5000.0, params)
    m500 = compute_performance_metrics(state_500, 500.0)
    m5k = compute_performance_metrics(state_5k, 5000.0)

    print(f"  At {risk:.0f}% risk:")
    print(f"    $500:  final=${m500['final_capital']:>9,.2f}  CAGR={m500['cagr_pct']:>+7.2f}%  "
          f"Sharpe={m500['sharpe_ratio']:.4f}  DD={m500['max_drawdown_pct']:.1f}%")
    print(f"    $5K:   final=${m5k['final_capital']:>9,.2f}  CAGR={m5k['cagr_pct']:>+7.2f}%  "
          f"Sharpe={m5k['sharpe_ratio']:.4f}  DD={m5k['max_drawdown_pct']:.1f}%")

    if risk == 2.0:
        params_1pct = SizingParams(max_risk_per_trade_pct=1.0)
        state_5k_1pct = run_simulation(trades, 5000.0, params_1pct)
        m5k_1pct = compute_performance_metrics(state_5k_1pct, 5000.0)
        print(f"    (At $5K: 1.0% gives Sharpe={m5k_1pct['sharpe_ratio']:.4f} DD={m5k_1pct['max_drawdown_pct']:.1f}%)")
    print()

# ── Bootstrap MC (2 key configs, 200 trials each) ──
print("=" * 85)
print("  BOOTSTRAP MONTE CARLO (200 trials) — 1.0% risk")
print("=" * 85)
print()

for capital in [500, 5000]:
    params = SizingParams(max_risk_per_trade_pct=1.0)
    bs = run_bootstrap_monte_carlo(trades, float(capital), 200, params)
    print(f"  ${capital:>5,}: P(Profitable)={bs['probabilities']['profitable']:>5.1f}%  "
          f"P(DD>30%)={bs['probabilities']['dd_exceeds_30pct']:>5.1f}%  "
          f"Med=${bs['ending_equity']['median']:>8,.2f}")

print()
print("=" * 85)
print("  AUG 2024 DRAWDOWN: RISK REDUCTION COMPARISON")
print("=" * 85)
print()

# The -16.74R drawdown
drawdown_r = 16.74
for capital in [500, 1000, 5000]:
    for risk_pct in [1.0, 2.0]:
        loss = drawdown_r * capital * risk_pct / 100
        remaining = capital - loss
        dd_pct = loss / capital * 100
        print(f"  ${capital:>5,} @ {risk_pct:.0f}%: loss=${loss:>6,.2f} ({dd_pct:>5.1f}%) -> remaining=${remaining:>6,.2f}")

print()
print("=" * 85)
print("  PRODUCTION RECOMMENDATION")
print("=" * 85)
print()
print(f"  {'Equity Range':<18} {'Risk':>8} {'Expected DD':>14} {'Aug 2024 DD':>14}")
print(f"  {'-'*18} {'-'*8} {'-'*14} {'-'*14}")
print(f"  {'$500 - $999':<18} {'1.0%':>8} {'35-49%':>13} {'-15.5%':>13}")
print(f"  {'$1K - $2.5K':<18} {'1.0%':>8} {'20-35%':>13} {'-9.7%':>13}")
print(f"  {'$2.5K - $5K':<18} {'1.0-1.5%':>8} {'10-20%':>13} {'-4.9%':>13}")
print(f"  {'$5K - $25K':<18} {'2.0%':>8} {'6-10%':>13} {'-3.4%':>13}")
print(f"  {'$25K+':<18} {'2.0%':>8} {'<6%':>13} {'-0.3%':>13}")
print()
print("  Expected DD = normal market conditions (not tail events)")
print("  Aug 2024 DD = the specific yen carry unwind scenario")
