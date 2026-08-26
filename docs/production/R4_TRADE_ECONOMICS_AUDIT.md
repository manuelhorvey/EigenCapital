# R4 Trade Economics Audit

**Scope:** frozen R4 (`risk_conditioned_continuation` vR4.0, identity `aaab6c00dc05…b2beb`, git `d16148e`)
**Evidence base:** simulation-based reconstruction (744 episodes, D1 2020-01→2026-08, parity-verified against the live loop's own `compute_r4_signal`) + live broker exports. Reconstruction is NOT fills; conventions preregistered in `reports/r4_economics_audit/trades.schema.json`.
**Safety status:** 🔴 PAUSE_REQUIRED (see `PRELIMINARY_SAFETY_TRIAGE.md`). This document addresses economics only.

---

## 1. Holding period — where the edge lives

| Bucket (trading days) | n | Expectancy (net) | Win rate | Share of all positive P&L |
|---|---|---|---|---|
| 1–2d | 210 | −0.21% | 25.7% | 1.3% |
| 3–5d | 210 | −0.23% | 37.1% | 3.0% |
| 6–10d | 108 | −0.16% | 48.1% | 2.6% |
| 11–20d | 68 | +0.28% | 44.1% | 5.2% |
| 21–40d | 57 | −0.49% | 31.6% | 3.9% |
| **40d+** | **91** | **+7.35%** | 41.8% | **84.0%** |

Holding-period percentiles (trading days): P25=1, P50=3, P75=12, P90=52, P95=108, P99=236.

**Answer:** R4's edge emerges beyond ~20 days and concentrates overwhelmingly at 40+ days. Everything shorter is cost-dragged churn. Time caps destroy convexity (60d cap: Sharpe 0.595→−0.03; false-stop 43%).

**Cadence finding:** the manifest declares *weekly* rebalance; operations run *hourly/daily*. Reconstructed weekly cadence: expectancy **+2.17%/trade, win 45.2%**, median hold 17d vs daily **+0.74%, 36.3%**, median 3d. The operational cadence materially degrades the declared design. (Artifact: `trades_weekly.csv`.)

## 2. Loss dynamics and recovery curves

Recovery curves (R := ATR14% at entry):

| Reached depth | n | Eventually profitable | Avg final return | Deteriorated further ≥0.25R |
|---|---|---|---|---|
| −0.25R | 360 | 33.3% | −0.31R | 81.4% |
| −0.50R | 293 | 29.0% | −0.82R | 77.1% |
| −0.75R | 226 | 21.7% | −1.10R | 83.2% |
| **−1.0R** | 188 | 18.6% | −1.30R | 85.1% |
| −1.5R | 127 | 15.0% | −1.77R | 89.0% |
| −2.0R | 91 | 12.1% | −2.04R | 87.9% |
| −3.0R | 53 | 9.4% | −2.81R | 90.6% |

Monotone deterioration with **no natural bounce zone**: deeper losers keep getting worse; there is no evidence-backed recovery threshold. Median underwater share of episode life: 6.3%. Loss clustering: up to 16 losing exits in a single month; 53 months had ≥3 losses.

## 3. Exit attribution

| Exit reason | n | Avg net | Median | % profitable | Total contribution |
|---|---|---|---|---|---|
| rotated_out_top8 | 713 | −0.23% | −0.20% | 35.3% | −1.62 |
| sign_flip | 23 | +30.3% (skewed by BTC tails) | +0.09% | 52.2% | **+6.97** |
| end_of_data | 8 | +1.82% | +0.22% | 75.0% | +0.15 |

Sign-flip exits harvest the tails; rotation carries the churn. Post-exit 20-bar direction resumption averages just +0.07% — rotation does not systematically miss large moves on average, but the 40d+ concentration shows it truncates future winners early (they re-enter later).

## 4. Costs

Gross-vs-net drag on the exact-weight portfolio path: **+2.59%/yr**, versus +1.43%/yr net (+4.02% gross) — costs consume ~64% of gross edge at 10bps/side on the daily-cadence path. On weekly cadence the drag shrinks proportionally to turnover. Live trial account charged zero swap/commission; true production cost is spread-crossing (t0 snapshot spreads ≈0.6–1.5 pips majors).

## 5. What this means

- R4 is a **slow tail-harvester**: positive expectancy exists only through multi-week/40d+ holds; short-cycle behavior is a cost sink.
- The declared weekly cadence outperforms the operational daily cadence on every metric.
- Losses do not mean-revert: no natural stop threshold exists; protection must be justified on containment grounds only (see Exit-Risk audit).

*All figures traceable to: `holding_period.json`, `loss_dynamics.json`, `exit_attribution.json`, `trades.parquet`, `counterfactual_results.json`, `portfolio_curve_daily.csv`.*
