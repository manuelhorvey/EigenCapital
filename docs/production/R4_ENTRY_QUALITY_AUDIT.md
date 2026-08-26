# R4 Entry Quality Audit

**Evidence base:** 744 parity-verified reconstructed episodes (`trades_enriched.parquet`); forward returns measured on traded symbols' close series in trade direction, independent of exits. R := ATR14% at entry.

---

## 1. Forward performance after entry

| Horizon | Mean fwd return | Win rate |
|---|---|---|
| +1 bar | +0.013% | 54.0% |
| +3 bars | +0.029% | 50.2% |
| +5 bars | −0.029% | 49.4% |
| +10 bars | −0.006% | 51.6% |
| +20 bars | **+0.138%** | 52.5% |
| +60 bars | +0.111% | 50.5% |

Immediate edge is ≈0; the first statistically meaningful drift appears only around +20 bars. Median time-to-profit = median time-to-loss = 2 bars — entries are coin-flips short-term.

## 2. Excursion structure

| Metric | Value |
|---|---|
| MFE median | 0.283R |
| MAE median | 0.200R |
| MFE/MAE ratio (median) | 0.66 |
| Immediate adverse move share | **55.8%** of trades go negative at some point |
| Adverse-first (−0.25R before +0.25R) | 10.8% |
| Early failure rate (≤ −0.5R within 5 bars) | **19.8%** |
| P(reach +1R) / P(reach −1R) | 23.5% / 25.3% |
| P(reach +2R) / P(reach −2R) | 11.3% / 12.2% |

MFE/MAE < 1 means typical adverse excursion exceeds typical favorable excursion early in the trade — entries are NOT at favorable micro-locations; the strategy tolerates adverse excursion waiting for slow drift.

## 3. Signal strength — is stronger better?

By absolute signal-weight quintiles:

| Quintile | mean \|w\| | Expectancy | Win rate | P(+1R) |
|---|---|---|---|---|
| Q1 (weakest) | 0.017 | −0.22% | 33.6% | 0.0% |
| Q2 | 0.023 | −0.16% | 36.9% | 0.0% |
| Q3 | 0.027 | −0.51% | 29.1% | 0.0% |
| Q4 | 0.033 | −0.45% | 37.6% | 0.0% |
| **Q5 (strongest)** | 0.052 | **+5.03%** | 44.3% | **6.7%** |

Not smoothly monotone (Spearman ρ=0.20, p=0.75 across quintile means) but strongly **threshold-shaped**: only the strongest weight quintile earns; the weakest four are cost-dragged churn with zero probability of reaching +1R.

By cross-sectional rank at entry (top-8 selection): rank-1/2 entries carry expectancy +3.6%/trade and P(+1R)=37%; weaker ranks ≈ −0.2%. The edge concentrates in the strongest-selected names.

**Major finding (flagged per governance §4/§5):** smooth monotonicity does NOT exist; a threshold effect does. Weak-signal entries dilute and cost-drag the book.

## 4. Entry classification

- Regime ON at entry: 100% by construction (gate). 23% of episodes subsequently span regime-OFF freezes.
- Volatility expansion at entry and post-extension behavior: diagnostics recorded in `entry_quality.json`; no production filter is proposed from subgroups without walk-forward validation.

## 5. Verdict

### ENTRY QUALITY: **YELLOW**

Entries have a real but slow, tail-concentrated edge (+20 bar drift; 40d+ holding bucket carries 84% of positive P&L; rank/strongest-quintile concentration), while short-horizon behavior is indistinguishable from noise with adverse-first tendencies (55.8% immediate adverse; MFE/MAE 0.66) and ~20% early-failure rate. Entries are *tolerable for a patient momentum system*, not good timing. Avoidable inefficiency exists: weak-signal churn and the daily-vs-weekly cadence gap destroy measurable value.

*Artifacts: `entry_quality.json`, `signal_strength.json`, `holding_period.json`.*
