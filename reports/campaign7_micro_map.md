# CAMPAIGN 7 — BROKER-SPECIFIC MICROSTRUCTURE (REAL TICK QUOTES)

> **[SUPERSEDED]** This report was generated under the pre-hardening
> accounting engine and is retained as raw forensic evidence only.
> The authoritative Campaign 7 verdict is
> [campaign7_rerun_hardened.md](campaign7_rerun_hardened.md):
> **18/18 REJECTED** under corrected per-bar cost accounting with
> family-wise + cumulative multiple-testing correction.

**Information source:** Exness MT5 quote ticks → M5 micro bars (broker-specific microstructure, NOT institutional order flow)
**Universe:** 8 instruments
**Generated:** 2026-08-25 01:13 UTC
**Hypotheses:** 18 pre-registered across 7 families
**Costs:** base 13bps / adverse 22bps
**Multiple testing:** all hypothesis × horizon evaluations form one Bonferroni family; SUPPORTED requires p_adj ≤ 0.05. Cumulative intraday trials incl. frozen branch: 133 prior + current campaign.

---

## VERDICT DISTRIBUTION

| Verdict | Count | IDs |
|---|---|---|
| **REJECTED** | 11 | TF-001, TF-002, AI-002, SD-002, PI-001, PE-001, PE-002, LL-002, LL-003, CO-001, CO-002 |
| **REGIME_DEPENDENT** | 1 | AI-001 |
| **FRAGILE** | 6 | TF-003, AI-003, SD-001, SD-003, PI-002, LL-001 |

**Survivors: 0/18**

---

## TOP CANDIDATES

| ID | Family | HP | Net | Adv | DD | WF | Perm p | p_adj | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| TF-003 | tick_flow | 5m | +1.647 | +1.647 | -0.34 | 100% | 0.010 | 0.720 | fragile |
| AI-003 | intensity | 5m | +1.371 | +1.371 | -0.21 | 50% | 0.180 | 1.000 | fragile |
| AI-001 | intensity | 5m | +0.934 | +0.934 | -0.46 | 25% | 1.000 | 1.000 | regime_dependent |
| PI-002 | impact | 5m | +0.778 | +0.778 | -0.26 | 50% | 1.000 | 1.000 | fragile |
| SD-003 | spread | 5m | +0.727 | +0.727 | -0.31 | 100% | 0.000 | 0.000 | fragile |
| LL-001 | lead_lag | 30m | +0.502 | +0.502 | -0.80 | 75% | 0.360 | 1.000 | fragile |
---

## DETAILED RESULTS

### 🟡 TF-003 — Flow-extreme reversal (5m, fragile)
- gross/net/adverse: +1.647 / +1.647 / +1.647
- maxDD -0.34 · trades 322149 · WF 100% (OOS +2.307) · perm p 0.010 (adj 0.720, family 72)
- instruments positive: 8/8
- primary failure: catastrophic_dd

### 🟡 AI-003 — Quiet-market reversion (5m, fragile)
- gross/net/adverse: +1.371 / +1.371 / +1.371
- maxDD -0.21 · trades 134766 · WF 50% (OOS +0.679) · perm p 0.180 (adj 1.000, family 72)
- instruments positive: 7/8
- primary failure: permutation_insignificant

### 🟡 AI-001 — Tick-intensity anomaly + direction (5m, regime_dependent)
- gross/net/adverse: +0.934 / +0.934 / +0.934
- maxDD -0.46 · trades 308268 · WF 25% (OOS -1.518) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 6/8
- primary failure: oos_negative

### 🟡 PI-002 — Low-impact move fade (5m, fragile)
- gross/net/adverse: +0.778 / +0.778 / +0.778
- maxDD -0.26 · trades 268384 · WF 50% (OOS -1.007) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 6/8
- primary failure: oos_negative

### 🟡 SD-003 — Spread-spike fade (5m, fragile)
- gross/net/adverse: +0.727 / +0.727 / +0.727
- maxDD -0.31 · trades 298508 · WF 100% (OOS +2.344) · perm p 0.000 (adj 0.000, family 72)
- instruments positive: 6/8
- primary failure: catastrophic_dd

### 🟡 LL-001 — EURUSD flow leads GBPUSD (1-bar lag) (30m, fragile)
- gross/net/adverse: +0.502 / +0.502 / +0.502
- maxDD -0.80 · trades 332546 · WF 75% (OOS +0.016) · perm p 0.360 (adj 1.000, family 72)
- instruments positive: 6/8
- primary failure: catastrophic_dd

### 🟡 SD-001 — Spread expansion reversal (5m, fragile)
- gross/net/adverse: +0.414 / +0.414 / +0.414
- maxDD -0.21 · trades 78313 · WF 75% (OOS +1.099) · perm p 0.180 (adj 1.000, family 72)
- instruments positive: 6/8
- primary failure: permutation_insignificant

### 🔴 AI-002 — Intensity spike x flow composite (30m, rejected)
- gross/net/adverse: -0.031 / -0.031 / -0.031
- maxDD -0.54 · trades 124914 · WF 0% (OOS -0.754) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 2/8
- primary failure: negative_gross_alpha

### 🔴 CO-001 — Flow x spread-regime composite (30m, rejected)
- gross/net/adverse: -0.033 / -0.033 / -0.033
- maxDD -0.55 · trades 199378 · WF 25% (OOS -0.385) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 3/8
- primary failure: negative_gross_alpha

### 🔴 LL-003 — XAUUSD flow leads AUDUSD (1-bar lag) (10m, rejected)
- gross/net/adverse: -0.035 / -0.035 / -0.035
- maxDD -0.24 · trades 151672 · WF 25% (OOS +0.339) · perm p 0.300 (adj 1.000, family 72)
- instruments positive: 6/8
- primary failure: negative_gross_alpha

### 🔴 PE-001 — Multi-bar directional persistence (10m, rejected)
- gross/net/adverse: -0.062 / -0.062 / -0.062
- maxDD -0.52 · trades 122328 · WF 25% (OOS -1.326) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 5/8
- primary failure: negative_gross_alpha

### 🔴 PI-001 — High impact-per-tick continuation (15m, rejected)
- gross/net/adverse: -0.272 / -0.272 / -0.272
- maxDD -0.44 · trades 188056 · WF 25% (OOS -1.210) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 3/8
- primary failure: negative_gross_alpha

### 🔴 SD-002 — Spread contraction continuation (15m, rejected)
- gross/net/adverse: -0.311 / -0.311 / -0.311
- maxDD -0.55 · trades 235652 · WF 50% (OOS +0.156) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 2/8
- primary failure: negative_gross_alpha

### 🔴 LL-002 — US500 flow leads USTEC (1-bar lag) (15m, rejected)
- gross/net/adverse: -0.345 / -0.345 / -0.345
- maxDD -0.52 · trades 282824 · WF 50% (OOS +0.172) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 2/8
- primary failure: negative_gross_alpha

### 🔴 TF-001 — Signed quote-flow continuation (1-bar) (30m, rejected)
- gross/net/adverse: -0.492 / -0.492 / -0.492
- maxDD -0.59 · trades 321905 · WF 25% (OOS -0.467) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 1/8
- primary failure: negative_gross_alpha

### 🔴 CO-002 — Intensity spike x micro-breakout (5m, rejected)
- gross/net/adverse: -0.519 / -0.519 / -0.519
- maxDD -0.41 · trades 84176 · WF 25% (OOS -0.913) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 2/8
- primary failure: negative_gross_alpha

### 🔴 TF-002 — Signed quote-flow continuation (3-bar) (30m, rejected)
- gross/net/adverse: -0.571 / -0.571 / -0.571
- maxDD -0.76 · trades 180564 · WF 25% (OOS -0.956) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 2/8
- primary failure: negative_gross_alpha

### 🔴 PE-002 — Quote-run persistence (30m, rejected)
- gross/net/adverse: -0.673 / -0.673 / -0.673
- maxDD -0.87 · trades 169984 · WF 25% (OOS -0.994) · perm p 1.000 (adj 1.000, family 72)
- instruments positive: 1/8
- primary failure: negative_gross_alpha

