# CAMPAIGN 6 — 1H CONFIRMATION OF ST-001

**Mechanism:** Asia→London transition continuation (ST-001)
**Universe:** 8 instruments (Exness MT5, H1)
**Data:** ~50,000 bars/symbol (~8 years, 2018 → 2026)
**Generated:** 2026-08-24 23:21 UTC
**Costs:** base 13bps / adverse 22bps
**Multiple testing:** Bonferroni over 4 primary + 20 sensitivity evaluations

---

## CONFIRMATION VERDICT: **NOT_CONFIRMED**

- No horizon passes all frozen gates at 1H.

---

## PRIMARY RESULTS (b=07, k=2)

| HP | Gross | Net | Adverse | MaxDD | WF | OOS | Perm p | p_adj | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1h | -0.035 | -0.035 | -0.035 | -0.35 | 80% | +0.230 | 0.175 | 1.000 | rejected |
| 2h | -0.109 | -0.109 | -0.109 | -0.41 | 60% | +0.040 | 0.340 | 1.000 | rejected |
| 3h | -0.081 | -0.081 | -0.081 | -0.55 | 40% | +0.040 | 0.365 | 1.000 | rejected |
| 4h | -0.063 | -0.063 | -0.063 | -0.72 | 60% | -0.000 | 1.000 | 1.000 | rejected |

### Best-primary deep dive (HP=1h)

**Year-by-year:**
- 2018: Sharpe +0.63, DD -1.0%
- 2019: Sharpe +0.83, DD -1.1%
- 2020: Sharpe -0.21, DD -2.2%
- 2021: Sharpe +1.13, DD -1.1%
- 2022: Sharpe +0.52, DD -2.1%
- 2023: Sharpe +1.03, DD -1.4%
- 2024: Sharpe +0.16, DD -1.5%
- 2025: Sharpe -0.06, DD -1.0%
- 2026: Sharpe -0.87, DD -1.2%

**Session attribution:**
- london: +0.80

**Per-instrument (net Sharpe | PnL share):**
- AUDUSDm: -0.410 | 0.0%
- EURUSDm: +0.366 | 16.5%
- GBPUSDm: +0.119 | 6.8%
- US500m: -0.318 | 0.0%
- USDJPYm: -0.032 | 0.0%
- USOILm: +0.234 | 65.7%
- USTECm: -0.379 | 0.0%
- XAUUSDm: +0.143 | 11.0%

### Cross-instrument concentration

- Average pairwise correlation of daily strategy returns: +0.124
- Maximum pairwise correlation: +0.804
- Interpretation: high correlation ⇒ concentrated risk factor, not independent edges.

---

## SENSITIVITY GRID (diagnostics only — no selection)

| Boundary | Lookback | HP | Net | WF | p_adj | Verdict |
|---|---|---|---|---|---|---|
| 06:00 | 2h | 1h | +0.066 | 60% | 1.000 | fragile |
| 06:00 | 2h | 2h | +0.067 | 60% | 1.000 | fragile |
| 06:00 | 2h | 3h | -0.020 | 40% | 1.000 | rejected |
| 06:00 | 2h | 4h | -0.034 | 40% | 1.000 | rejected |
| 06:00 | 3h | 1h | +0.243 | 100% | 1.000 | fragile |
| 06:00 | 3h | 2h | +0.166 | 60% | 1.000 | fragile |
| 06:00 | 3h | 3h | +0.048 | 80% | 1.000 | fragile |
| 06:00 | 3h | 4h | +0.054 | 40% | 1.000 | regime_dependent |
| 07:00 | 3h | 1h | -0.024 | 40% | 1.000 | rejected |
| 07:00 | 3h | 2h | -0.091 | 60% | 1.000 | rejected |
| 07:00 | 3h | 3h | -0.052 | 20% | 1.000 | rejected |
| 07:00 | 3h | 4h | -0.098 | 60% | 1.000 | rejected |
| 08:00 | 2h | 1h | -0.048 | 60% | 1.000 | rejected |
| 08:00 | 2h | 2h | -0.029 | 60% | 1.000 | rejected |
| 08:00 | 2h | 3h | -0.016 | 80% | 1.000 | rejected |
| 08:00 | 2h | 4h | +0.111 | 80% | 1.000 | fragile |
| 08:00 | 3h | 1h | -0.148 | 60% | 1.000 | rejected |
| 08:00 | 3h | 2h | -0.057 | 40% | 1.000 | rejected |
| 08:00 | 3h | 3h | -0.068 | 60% | 1.000 | rejected |
| 08:00 | 3h | 4h | +0.006 | 60% | 1.000 | fragile |

Sensitivity robustness: 0/20 variants positive with p_adj ≤ 0.10. Robustness across neighbouring boundaries/lookbacks indicates a stable economic effect rather than a knife-edge fit.

---

## DECISION

ST-001 remains a 30M-supported RESEARCH candidate. It must NOT be promoted toward the fidelity ladder without independent confirmation.
