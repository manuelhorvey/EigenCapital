# R4 Exit & Downside-Risk Audit

**Control:** frozen R4 exits (rotation / sign-flip / regime-ride), reconstructed net of 10bps/side.
**Trial governance:** 33 preregistered trials in `trial_ledger.json`; all results reported including failures; Bonferroni-corrected block-bootstrap p-values.

---

## 1. Control economics (2020→2026, daily cadence)

| Metric | Value |
|---|---|
| Sharpe | **0.595** |
| Annual return | +2.80% |
| Ann. volatility | 4.7% |
| Max drawdown | **−12.3%** |
| Calmar | 0.23 |
| Sortino | 0.81 |
| Profit factor (trades) | 2.03 |
| CVaR95 daily | −0.68% |
| Yearly consistency | 71% (2022: −0.31; 2026 partial: −0.12) |

## 2. Counterfactual grid — headline results

| Family | Best/worst result | Verdict |
|---|---|---|
| F1 Fixed % stops 0.25–3% | Tight (0.25–0.5%): Sharpe → **−0.63** (642/744 stopped). Wide (2–3%): Sharpe −0.04…−0.06 vs control, MaxDD improves to −7% | Harmful tight; containment-only at wide |
| F2 ATR stops 0.5–3× | All ΔSharpe negative (−0.02…−0.16). **ATR×1–2: MaxDD −12.3%→−6.7…−7.0% at drag ≤0.05** | Not economic; strong containment profile |
| F4 TP 0.5–5R | **All harmful**: ΔSharpe −0.34…−0.63 | Destroys convexity |
| F5 Trailing (pct/ATR/MFE-giveback) | All harmful: ΔSharpe −0.56…−1.41 | Cuts winners systematically |
| F6 Regime-OFF flatten | ΔSharpe **−0.713** | Riding frozen periods through recovery beats flattening economically |
| F7 Time stops | loser-exit-10bar: Sharpe **+0.068** (0.663), MaxDD −45%, false-stop 22.8%; timecaps on winners: destructive (false-stop 43–58%) | Only control-beater; NOT Bonferroni-significant |

**Zero variants survive family-wise significance against the control.** Trigger-path realism check (H1 vs D1 on AUDUSD/EURUSD/GBPUSD subset): 72–88% trigger-day agreement.

## 3. Does R4's edge depend on letting winners run? — YES

Direct evidence: (a) every TP truncates expectancy; (b) 40d+ episodes hold 84% of positive P&L with +7.35%/trade; (c) sign-flip exits (which occur after full runs) contribute +6.97 total while rotation churn is negative; (d) winner time-caps destroy Sharpe with 43–58% false-stop rates. The strategy IS its tail.

## 4. Economic exit vs catastrophic protection — separate layers

| Layer | Question | Answer |
|---|---|---|
| Economic exits | Does any SL/TP/trail improve risk-adjusted return OOS? | **No.** No-SL/TP is *economically justified* for R4's exit architecture. |
| Catastrophic protection | Can unacceptable loss occur without any economic benefit? | **Yes today.** No layer reduces exposure automatically; worst case bounded by margin only; observed 10.01% DD breach with zero reaction during a 9.5h blind window. |

A ≥2×ATR disaster stop costs ≤0.05 Sharpe while halving MaxDD — acceptable as a **safety-only** layer judged on containment (per preregistered criteria: P99 loss reduction with bounded drag), not as an exit signal. This preserves no-SL economics for normal operation while closing the operational gap.

## 5. Portfolio stress context ($5K envelope)

8 × $1,500 positions = up to $12K gross design cap (~240% equity); simulated gross exposure averages ~1.05× when active. Uniform −5% shock ≈ −$600 (−12% equity) before friction; −10% correlated crash ≈ margin-relevant at 2000:1 leverage. Spread ×10 and gap scenarios are survivable position-wise but **uncontrollable without a reduction path** (P0-1).

## 6. Verdicts

### EXIT QUALITY: **YELLOW**
Rotation/sign-flip/regime-ride preserve the momentum edge better than any tested alternative (all 20+ protective variants fail significance), but rotation churns weak entries at cost and regime-OFF leaves positions unmanaged — economically correct per F6 yet risk-accepting by choice.

### NO-SL/TP DESIGN (economic): **JUSTIFIED**
No variant survives multiple-testing correction; TPs/trails/tight stops are actively destructive.

### CATASTROPHIC PROTECTION: **INSUFFICIENT**
Currently nonexistent at broker level; required independently of economics.

*Artifacts: `counterfactual_results.json`, `trial_ledger.json`, `curve_*.csv`, `loss_dynamics.json`.*
