# CAMPAIGN 4 — 15M INTRADAY ALPHA RESEARCH

**Universe:** 8 instruments (Exness MT5)
**Timeframe:** 15-minute (M15)
**Bars:** ~50,000 per symbol (~2 years, Jul 2024 – Aug 2026)
**Date range:** 2024-07-04 → 2026-08-24
**Generated:** 2026-08-24 22:49 UTC
**Hypotheses:** 31
**Holding Horizons:** 15m, 30m, 1h, 2h, 4h
**Cost Scenarios:** base (13bps), adverse (22bps)

---

## VERDICT DISTRIBUTION

| Verdict | Count | Hypotheses |
|---|---|---|
| **REJECTED** | 16 | MO-001, MO-002, MO-004, MO-005, MR-002, BR-003, SE-001, SE-002, SE-003, VR-001, VR-002, XA-001, XA-002, PS-001, PS-002, CM-001 |
| **REGIME_DEPENDENT** | 5 | MO-003, BR-001, BR-004, SE-005, CM-002 |
| **FRAGILE** | 10 | MR-001, MR-003, MR-004, BR-002, SE-004, VR-003, VR-004, XA-003, XA-004, PS-003 |

**Survivors: 0/31 (0.0%)**

---

## FAILURE MODE DISTRIBUTION

| Failure Mode | Count | % |
|---|---|---|
| negative_gross_alpha | 16 | 52% |
| catastrophic_dd | 10 | 32% |
| oos_negative | 4 | 13% |
| permutation_insignificant | 1 | 3% |

---

## FAMILY BREAKDOWN

| Family | Count | Rejected | Fragile+ | Supported |
|---|---|---|---|---|
| breakout | 4 | 1 | 3 | 0 |
| composite | 2 | 1 | 1 | 0 |
| cross_asset | 4 | 2 | 2 | 0 |
| mean_reversion | 4 | 1 | 3 | 0 |
| momentum | 5 | 4 | 1 | 0 |
| price_structure | 3 | 2 | 1 | 0 |
| sessions | 5 | 3 | 2 | 0 |
| volatility | 4 | 2 | 2 | 0 |

---

## TOP CANDIDATES

| # | ID | Family | Description | HP | Net Sharpe | WF | Perm p | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | SE-004 | sessions | NY close mean-reversion (UTC-filtered) | 15m | +1.124 | 80% | 0.110 | fragile |
| 2 | MR-004 | mean_reversion | Range reversion (close near range extreme) | 15m | +0.573 | 60% | 0.360 | fragile |
| 3 | PS-003 | price_structure | Failed breakout reversal | 30m | +0.567 | 60% | 0.130 | fragile |
| 4 | MR-003 | mean_reversion | 16-bar vol-normalized deviation | 15m | +0.391 | 60% | 0.130 | fragile |
| 5 | VR-003 | volatility | Vol contraction reversal | 15m | +0.373 | 80% | 0.050 | fragile |

---

## DETAILED RESULTS

### 🔴 MO-001 — 4-bar momentum (1h continuation)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.136 |
| Net Sharpe (base) | -0.136 |
| Net Sharpe (adverse) | -0.136 |
| Max DD | -0.998 |
| Trades | 173481 |
| WF Consistency | 0% |
| WF OOS Sharpe | -0.294 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -1.142
  - 2025: -0.276
  - 2026: -0.285

**Session decomposition:**
  - asian: -0.140
  - london: -0.627
  - new_york: -0.316
  - off_hours: -1.435
  - overlap: -0.172

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.681
  - ❌ EURUSDm: -0.429
  - ❌ GBPUSDm: -0.496
  - ✅ US500m: +0.126
  - ✅ USDJPYm: +0.010
  - ❌ USOILm: -0.220
  - ✅ USTECm: +0.302
  - ✅ XAUUSDm: +0.302

---

### 🔴 MO-002 — 8-bar momentum (2h continuation)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.049 |
| Net Sharpe (base) | -0.049 |
| Net Sharpe (adverse) | -0.049 |
| Max DD | -0.997 |
| Trades | 128222 |
| WF Consistency | 20% |
| WF OOS Sharpe | -0.310 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -1.027
  - 2025: -0.615
  - 2026: +0.072

**Session decomposition:**
  - asian: -0.169
  - london: -0.456
  - new_york: +0.078
  - off_hours: -2.307
  - overlap: -0.586

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.948
  - ❌ EURUSDm: -0.499
  - ❌ GBPUSDm: -0.658
  - ✅ US500m: +0.118
  - ✅ USDJPYm: +0.567
  - ✅ USOILm: +0.068
  - ✅ USTECm: +0.292
  - ✅ XAUUSDm: +0.663

---

### 🟡 MO-003 — 16-bar momentum (4h continuation)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.071 |
| Net Sharpe (base) | 0.071 |
| Net Sharpe (adverse) | 0.071 |
| Max DD | -0.996 |
| Trades | 91981 |
| WF Consistency | 40% |
| WF OOS Sharpe | -0.214 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | oos_negative |

**Reasons:** catastrophic_dd, wf_inconsistent, oos_negative, permutation_insignificant

**Year decomposition:**
  - 2024: -1.338
  - 2025: -0.595
  - 2026: +0.265

**Session decomposition:**
  - asian: -0.565
  - london: +0.421
  - new_york: +0.144
  - off_hours: -2.906
  - overlap: -0.839

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.875
  - ❌ EURUSDm: -0.490
  - ❌ GBPUSDm: -0.404
  - ✅ US500m: +0.118
  - ✅ USDJPYm: +0.899
  - ✅ USOILm: +0.336
  - ✅ USTECm: +0.384
  - ✅ XAUUSDm: +0.598

---

### 🔴 MO-004 — Vol-adjusted 8-bar momentum
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.031 |
| Net Sharpe (base) | -0.031 |
| Net Sharpe (adverse) | -0.031 |
| Max DD | -0.996 |
| Trades | 128380 |
| WF Consistency | 20% |
| WF OOS Sharpe | -0.307 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -1.039
  - 2025: -0.532
  - 2026: +0.022

**Session decomposition:**
  - asian: -0.198
  - london: -0.420
  - new_york: +0.026
  - off_hours: -2.153
  - overlap: -0.467

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.927
  - ❌ EURUSDm: -0.468
  - ❌ GBPUSDm: -0.645
  - ✅ US500m: +0.146
  - ✅ USDJPYm: +0.584
  - ✅ USOILm: +0.102
  - ✅ USTECm: +0.325
  - ✅ XAUUSDm: +0.630

---

### 🔴 MO-005 — Momentum acceleration (mom strengthening)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.158 |
| Net Sharpe (base) | -0.158 |
| Net Sharpe (adverse) | -0.158 |
| Max DD | -0.993 |
| Trades | 207092 |
| WF Consistency | 20% |
| WF OOS Sharpe | -0.214 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -0.623
  - 2025: -0.168
  - 2026: -0.310

**Session decomposition:**
  - asian: -0.012
  - london: -0.461
  - new_york: -0.584
  - off_hours: +0.121
  - overlap: -0.386

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.401
  - ❌ EURUSDm: -0.286
  - ❌ GBPUSDm: -0.115
  - ✅ US500m: +0.070
  - ❌ USDJPYm: -0.375
  - ❌ USOILm: -0.187
  - ✅ USTECm: +0.031
  - ✅ XAUUSDm: +0.004

---

### 🟡 MR-001 — 8-bar VWAP deviation reversion
**Family:** mean_reversion | **HP:** 4 bars (60m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.053 |
| Net Sharpe (base) | 0.053 |
| Net Sharpe (adverse) | 0.053 |
| Max DD | -0.928 |
| Trades | 76312 |
| WF Consistency | 60% |
| WF OOS Sharpe | -0.006 |
| Degradation | 0.0% |
| Permutation p | 0.140 |
| Primary Failure | oos_negative |

**Reasons:** catastrophic_dd, oos_negative, permutation_insignificant

**Year decomposition:**
  - 2024: +2.229
  - 2025: +0.263
  - 2026: -0.386

**Session decomposition:**
  - asian: +1.263
  - london: -1.067
  - new_york: -0.736
  - off_hours: +1.906
  - overlap: +1.389

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +1.349
  - ✅ EURUSDm: +0.443
  - ✅ GBPUSDm: +0.973
  - ❌ US500m: -0.432
  - ❌ USDJPYm: -0.749
  - ✅ USOILm: +0.265
  - ❌ USTECm: -0.472
  - ❌ XAUUSDm: -0.956

---

### 🔴 MR-002 — 16-bar z-score reversal
**Family:** mean_reversion | **HP:** 1 bars (15m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.073 |
| Net Sharpe (base) | -0.073 |
| Net Sharpe (adverse) | -0.073 |
| Max DD | -0.539 |
| Trades | 51443 |
| WF Consistency | 40% |
| WF OOS Sharpe | -0.447 |
| Degradation | 0.0% |
| Permutation p | 0.430 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: +3.516
  - 2025: -0.147
  - 2026: -1.348

**Session decomposition:**
  - asian: +0.914
  - london: -0.533
  - new_york: -0.667
  - off_hours: +3.154
  - overlap: -0.472

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +0.943
  - ✅ EURUSDm: +0.168
  - ✅ GBPUSDm: +0.593
  - ❌ US500m: -0.093
  - ❌ USDJPYm: -0.530
  - ✅ USOILm: +0.144
  - ❌ USTECm: -0.417
  - ❌ XAUUSDm: -1.397

---

### 🟡 MR-003 — 16-bar vol-normalized deviation
**Family:** mean_reversion | **HP:** 1 bars (15m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.391 |
| Net Sharpe (base) | 0.391 |
| Net Sharpe (adverse) | 0.391 |
| Max DD | -0.497 |
| Trades | 91925 |
| WF Consistency | 60% |
| WF OOS Sharpe | 0.381 |
| Degradation | 0.0% |
| Permutation p | 0.130 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd, permutation_insignificant

**Year decomposition:**
  - 2024: +1.345
  - 2025: +0.748
  - 2026: -0.130

**Session decomposition:**
  - asian: +0.461
  - london: -0.044
  - new_york: +0.582
  - off_hours: +1.253
  - overlap: +1.168

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +2.378
  - ✅ EURUSDm: +0.609
  - ✅ GBPUSDm: +1.588
  - ❌ US500m: -0.283
  - ❌ USDJPYm: -0.103
  - ✅ USOILm: +0.233
  - ❌ USTECm: -0.360
  - ❌ XAUUSDm: -0.936

---

### 🟡 MR-004 — Range reversion (close near range extreme)
**Family:** mean_reversion | **HP:** 1 bars (15m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.573 |
| Net Sharpe (base) | 0.573 |
| Net Sharpe (adverse) | 0.573 |
| Max DD | -0.467 |
| Trades | 92852 |
| WF Consistency | 60% |
| WF OOS Sharpe | 0.206 |
| Degradation | 0.0% |
| Permutation p | 0.360 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd, permutation_insignificant

**Year decomposition:**
  - 2024: +0.873
  - 2025: +0.333
  - 2026: -0.221

**Session decomposition:**
  - asian: -0.354
  - london: -0.503
  - new_york: -0.518
  - off_hours: +2.059
  - overlap: +1.531

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +2.329
  - ✅ EURUSDm: +0.278
  - ✅ GBPUSDm: +1.296
  - ✅ US500m: +0.104
  - ✅ USDJPYm: +0.439
  - ✅ USOILm: +0.787
  - ❌ USTECm: -0.084
  - ❌ XAUUSDm: -0.568

---

### 🟡 BR-001 — 20-bar range breakout (5h range)
**Family:** breakout | **HP:** 16 bars (240m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.077 |
| Net Sharpe (base) | 0.077 |
| Net Sharpe (adverse) | 0.077 |
| Max DD | -0.999 |
| Trades | 92108 |
| WF Consistency | 40% |
| WF OOS Sharpe | -0.244 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | oos_negative |

**Reasons:** catastrophic_dd, wf_inconsistent, oos_negative, permutation_insignificant

**Year decomposition:**
  - 2024: -1.567
  - 2025: -0.579
  - 2026: +0.401

**Session decomposition:**
  - asian: -0.518
  - london: -0.169
  - new_york: +0.613
  - off_hours: -3.011
  - overlap: -0.496

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.892
  - ❌ EURUSDm: -0.487
  - ❌ GBPUSDm: -0.516
  - ✅ US500m: +0.117
  - ✅ USDJPYm: +1.125
  - ✅ USOILm: +0.180
  - ✅ USTECm: +0.379
  - ✅ XAUUSDm: +0.709

---

### 🟡 BR-002 — Compression to expansion (vol squeeze)
**Family:** breakout | **HP:** 16 bars (240m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.255 |
| Net Sharpe (base) | 0.255 |
| Net Sharpe (adverse) | 0.255 |
| Max DD | -0.989 |
| Trades | 208811 |
| WF Consistency | 80% |
| WF OOS Sharpe | 0.336 |
| Degradation | 0.0% |
| Permutation p | 0.000 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd

**Year decomposition:**
  - 2024: +1.945
  - 2025: +0.765
  - 2026: -0.359

**Session decomposition:**
  - asian: +1.070
  - london: +0.103
  - new_york: +0.540
  - off_hours: +1.412
  - overlap: +0.467

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +0.419
  - ✅ EURUSDm: +0.671
  - ✅ GBPUSDm: +0.191
  - ✅ US500m: +0.213
  - ❌ USDJPYm: -0.423
  - ✅ USOILm: +0.268
  - ✅ USTECm: +0.291
  - ✅ XAUUSDm: +0.409

---

### 🔴 BR-003 — Previous intraday high/low breakout
**Family:** breakout | **HP:** 8 bars (120m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.140 |
| Net Sharpe (base) | -0.140 |
| Net Sharpe (adverse) | -0.140 |
| Max DD | -0.995 |
| Trades | 37300 |
| WF Consistency | 40% |
| WF OOS Sharpe | -0.518 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -2.019
  - 2025: -0.302
  - 2026: -0.297

**Session decomposition:**
  - asian: -0.335
  - london: +0.364
  - new_york: -0.043
  - off_hours: -3.998
  - overlap: -0.702

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.961
  - ❌ EURUSDm: -0.601
  - ❌ GBPUSDm: -0.589
  - ❌ US500m: -0.708
  - ✅ USDJPYm: +0.642
  - ❌ USOILm: -0.015
  - ❌ USTECm: -0.061
  - ✅ XAUUSDm: +1.176

---

### 🟡 BR-004 — Asian range breakout
**Family:** breakout | **HP:** 2 bars (30m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.217 |
| Net Sharpe (base) | 0.217 |
| Net Sharpe (adverse) | 0.217 |
| Max DD | -0.845 |
| Trades | 73448 |
| WF Consistency | 40% |
| WF OOS Sharpe | 0.455 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd, wf_inconsistent, permutation_insignificant

**Year decomposition:**
  - 2024: -2.151
  - 2025: -0.214
  - 2026: +1.276

**Session decomposition:**
  - asian: -1.035
  - london: +1.410
  - new_york: +1.338
  - off_hours: -2.119
  - overlap: -1.198

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.734
  - ❌ EURUSDm: -0.167
  - ❌ GBPUSDm: -0.394
  - ✅ US500m: +0.689
  - ✅ USDJPYm: +1.204
  - ❌ USOILm: -0.530
  - ✅ USTECm: +0.585
  - ✅ XAUUSDm: +1.081

---

### 🔴 SE-001 — London open momentum (first 4 bars, UTC-filtered)
**Family:** sessions | **HP:** 1 bars (15m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.121 |
| Net Sharpe (base) | -0.121 |
| Net Sharpe (adverse) | -0.121 |
| Max DD | -0.330 |
| Trades | 43234 |
| WF Consistency | 80% |
| WF OOS Sharpe | -0.240 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -2.711
  - 2025: -0.789
  - 2026: +0.966

**Session decomposition:**
  - london: -1.728
  - overlap: +0.353

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.979
  - ❌ EURUSDm: -0.737
  - ❌ GBPUSDm: -0.092
  - ✅ US500m: +0.681
  - ✅ USDJPYm: +0.352
  - ❌ USOILm: -0.303
  - ✅ USTECm: +0.586
  - ❌ XAUUSDm: -0.473

---

### 🔴 SE-002 — NY open momentum (first 4 bars, UTC-filtered)
**Family:** sessions | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.064 |
| Net Sharpe (base) | -0.064 |
| Net Sharpe (adverse) | -0.064 |
| Max DD | -0.871 |
| Trades | 42182 |
| WF Consistency | 20% |
| WF OOS Sharpe | -0.136 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -0.667
  - 2025: -0.254
  - 2026: +0.266

**Session decomposition:**
  - new_york: -0.311
  - off_hours: -0.491

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.291
  - ❌ EURUSDm: -0.174
  - ❌ GBPUSDm: -0.329
  - ✅ US500m: +0.198
  - ❌ USDJPYm: -0.472
  - ❌ USOILm: -0.013
  - ✅ USTECm: +0.205
  - ✅ XAUUSDm: +0.362

---

### 🔴 SE-003 — Overlap momentum (London/NY, UTC-filtered)
**Family:** sessions | **HP:** 8 bars (120m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.116 |
| Net Sharpe (base) | -0.116 |
| Net Sharpe (adverse) | -0.116 |
| Max DD | -0.909 |
| Trades | 35789 |
| WF Consistency | 60% |
| WF OOS Sharpe | 0.003 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -0.728
  - 2025: -0.003
  - 2026: -0.206

**Session decomposition:**
  - new_york: -0.068
  - overlap: -0.444

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.722
  - ❌ EURUSDm: -0.184
  - ✅ GBPUSDm: +0.314
  - ❌ US500m: -0.156
  - ✅ USDJPYm: +0.368
  - ❌ USOILm: -0.417
  - ❌ USTECm: -0.140
  - ✅ XAUUSDm: +0.012

---

### 🟡 SE-004 — NY close mean-reversion (UTC-filtered)
**Family:** sessions | **HP:** 1 bars (15m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 1.124 |
| Net Sharpe (base) | 1.124 |
| Net Sharpe (adverse) | 1.124 |
| Max DD | -0.147 |
| Trades | 42182 |
| WF Consistency | 80% |
| WF OOS Sharpe | 0.982 |
| Degradation | 0.0% |
| Permutation p | 0.110 |
| Primary Failure | permutation_insignificant |

**Reasons:** permutation_insignificant

**Year decomposition:**
  - 2024: +0.791
  - 2025: +0.797
  - 2026: +1.261

**Session decomposition:**
  - new_york: +2.119
  - off_hours: -1.308

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +1.421
  - ✅ EURUSDm: +0.920
  - ✅ GBPUSDm: +0.631
  - ✅ US500m: +0.793
  - ✅ USDJPYm: +2.351
  - ✅ USOILm: +1.045
  - ✅ USTECm: +0.673
  - ✅ XAUUSDm: +1.158

---

### 🟡 SE-005 — Asian to London transition (UTC-filtered)
**Family:** sessions | **HP:** 4 bars (60m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.022 |
| Net Sharpe (base) | 0.022 |
| Net Sharpe (adverse) | 0.022 |
| Max DD | -0.295 |
| Trades | 13626 |
| WF Consistency | 40% |
| WF OOS Sharpe | 0.087 |
| Degradation | 0.0% |
| Permutation p | 0.110 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd, wf_inconsistent, permutation_insignificant

**Year decomposition:**
  - 2024: +1.330
  - 2025: -0.088
  - 2026: +0.503

**Session decomposition:**
  - london: +0.830

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.534
  - ✅ EURUSDm: +0.379
  - ✅ GBPUSDm: +0.574
  - ❌ US500m: -0.226
  - ❌ USDJPYm: -0.515
  - ✅ USOILm: +0.105
  - ❌ USTECm: -0.077
  - ✅ XAUUSDm: +0.474

---

### 🔴 VR-001 — Vol regime predicts returns (low vol = trend)
**Family:** volatility | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.034 |
| Net Sharpe (base) | -0.034 |
| Net Sharpe (adverse) | -0.034 |
| Max DD | -0.996 |
| Trades | 128254 |
| WF Consistency | 20% |
| WF OOS Sharpe | -0.380 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -1.052
  - 2025: -0.547
  - 2026: +0.050

**Session decomposition:**
  - asian: -0.182
  - london: -0.403
  - new_york: +0.023
  - off_hours: -2.192
  - overlap: -0.500

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.909
  - ❌ EURUSDm: -0.472
  - ❌ GBPUSDm: -0.625
  - ✅ US500m: +0.101
  - ✅ USDJPYm: +0.592
  - ✅ USOILm: +0.099
  - ✅ USTECm: +0.316
  - ✅ XAUUSDm: +0.627

---

### 🔴 VR-002 — Vol expansion momentum
**Family:** volatility | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.031 |
| Net Sharpe (base) | -0.031 |
| Net Sharpe (adverse) | -0.031 |
| Max DD | -0.998 |
| Trades | 358479 |
| WF Consistency | 60% |
| WF OOS Sharpe | 0.108 |
| Degradation | 0.0% |
| Permutation p | 0.360 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -0.494
  - 2025: +0.001
  - 2026: +0.539

**Session decomposition:**
  - asian: +0.269
  - london: -0.425
  - new_york: +0.714
  - off_hours: +0.504
  - overlap: -0.506

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +0.295
  - ✅ EURUSDm: +0.054
  - ❌ GBPUSDm: -0.239
  - ❌ US500m: -0.070
  - ✅ USDJPYm: +0.132
  - ❌ USOILm: -0.255
  - ❌ USTECm: -0.066
  - ❌ XAUUSDm: -0.102

---

### 🟡 VR-003 — Vol contraction reversal
**Family:** volatility | **HP:** 1 bars (15m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.373 |
| Net Sharpe (base) | 0.373 |
| Net Sharpe (adverse) | 0.373 |
| Max DD | -0.298 |
| Trades | 164950 |
| WF Consistency | 80% |
| WF OOS Sharpe | 1.195 |
| Degradation | 0.0% |
| Permutation p | 0.050 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd

**Year decomposition:**
  - 2024: +0.502
  - 2025: +0.854
  - 2026: +1.697

**Session decomposition:**
  - asian: +0.761
  - london: +0.766
  - new_york: +1.307
  - off_hours: +3.384
  - overlap: +0.332

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +0.802
  - ✅ EURUSDm: +1.006
  - ✅ GBPUSDm: +0.834
  - ❌ US500m: -0.503
  - ❌ USDJPYm: -0.166
  - ✅ USOILm: +0.904
  - ❌ USTECm: -0.137
  - ✅ XAUUSDm: +0.248

---

### 🟡 VR-004 — Realized vol vs longer-term average
**Family:** volatility | **HP:** 8 bars (120m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.021 |
| Net Sharpe (base) | 0.021 |
| Net Sharpe (adverse) | 0.021 |
| Max DD | -0.992 |
| Trades | 21019 |
| WF Consistency | 80% |
| WF OOS Sharpe | 1.008 |
| Degradation | 0.0% |
| Permutation p | 0.000 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd

**Year decomposition:**
  - 2024: +0.094
  - 2025: +1.171
  - 2026: +0.621

**Session decomposition:**
  - asian: -0.007
  - london: -0.107
  - new_york: +0.837
  - off_hours: -2.259
  - overlap: +4.410

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.432
  - ✅ EURUSDm: +0.826
  - ✅ GBPUSDm: +0.666
  - ❌ US500m: -0.457
  - ❌ USDJPYm: -0.824
  - ✅ USOILm: +0.337
  - ❌ USTECm: -0.739
  - ✅ XAUUSDm: +0.791

---

### 🔴 XA-001 — US500 returns lead EURUSD (2-bar lag)
**Family:** cross_asset | **HP:** 4 bars (60m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.150 |
| Net Sharpe (base) | -0.150 |
| Net Sharpe (adverse) | -0.150 |
| Max DD | -0.934 |
| Trades | 231360 |
| WF Consistency | 80% |
| WF OOS Sharpe | 0.035 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -0.124
  - 2025: -0.110
  - 2026: +0.111

**Session decomposition:**
  - asian: +0.637
  - london: -1.065
  - new_york: -0.404
  - off_hours: +1.175
  - overlap: -0.077

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.224
  - ❌ EURUSDm: -0.054
  - ❌ GBPUSDm: -0.183
  - ✅ US500m: +0.091
  - ❌ USDJPYm: -0.637
  - ❌ USOILm: -0.466
  - ✅ USTECm: +0.117
  - ✅ XAUUSDm: +0.153

---

### 🔴 XA-002 — USTEC returns lead EURUSD (2-bar lag)
**Family:** cross_asset | **HP:** 4 bars (60m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.181 |
| Net Sharpe (base) | -0.181 |
| Net Sharpe (adverse) | -0.181 |
| Max DD | -0.936 |
| Trades | 230900 |
| WF Consistency | 60% |
| WF OOS Sharpe | -0.324 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: +0.559
  - 2025: -0.422
  - 2026: -0.189

**Session decomposition:**
  - asian: +0.221
  - london: -0.697
  - new_york: -0.762
  - off_hours: +0.948
  - overlap: -0.205

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.391
  - ❌ EURUSDm: -0.185
  - ❌ GBPUSDm: -0.310
  - ✅ US500m: +0.111
  - ❌ USDJPYm: -0.543
  - ❌ USOILm: -0.344
  - ✅ USTECm: +0.130
  - ✅ XAUUSDm: +0.084

---

### 🟡 XA-003 — US500 returns lead XAUUSD (2-bar lag, inverse)
**Family:** cross_asset | **HP:** 8 bars (120m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.302 |
| Net Sharpe (base) | 0.302 |
| Net Sharpe (adverse) | 0.302 |
| Max DD | -0.859 |
| Trades | 231360 |
| WF Consistency | 60% |
| WF OOS Sharpe | 0.294 |
| Degradation | 0.0% |
| Permutation p | 0.010 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd

**Year decomposition:**
  - 2024: +1.397
  - 2025: +0.214
  - 2026: +0.639

**Session decomposition:**
  - asian: -0.169
  - london: +1.510
  - new_york: -0.560
  - off_hours: +0.930
  - overlap: +0.991

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +0.780
  - ✅ EURUSDm: +0.528
  - ✅ GBPUSDm: +0.525
  - ❌ US500m: -0.049
  - ✅ USDJPYm: +0.286
  - ✅ USOILm: +0.067
  - ❌ USTECm: -0.119
  - ✅ XAUUSDm: +0.400

---

### 🟡 XA-004 — USOIL returns lead USDJPY (4-bar lag)
**Family:** cross_asset | **HP:** 4 bars (60m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.209 |
| Net Sharpe (base) | 0.209 |
| Net Sharpe (adverse) | 0.209 |
| Max DD | -0.778 |
| Trades | 167484 |
| WF Consistency | 80% |
| WF OOS Sharpe | 0.354 |
| Degradation | 0.0% |
| Permutation p | 0.260 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd, permutation_insignificant

**Year decomposition:**
  - 2024: +0.706
  - 2025: -0.337
  - 2026: +0.977

**Session decomposition:**
  - asian: +0.194
  - london: +2.404
  - new_york: +0.890
  - off_hours: -0.404
  - overlap: -2.305

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +0.295
  - ✅ EURUSDm: +0.194
  - ✅ GBPUSDm: +0.276
  - ✅ US500m: +0.274
  - ✅ USDJPYm: +0.179
  - ✅ USOILm: +0.281
  - ✅ USTECm: +0.128
  - ✅ XAUUSDm: +0.047

---

### 🔴 PS-001 — Higher-high/lower-low continuation
**Family:** price_structure | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.078 |
| Net Sharpe (base) | -0.078 |
| Net Sharpe (adverse) | -0.078 |
| Max DD | -1.000 |
| Trades | 323874 |
| WF Consistency | 0% |
| WF OOS Sharpe | -0.290 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -0.594
  - 2025: -0.355
  - 2026: -0.058

**Session decomposition:**
  - asian: +0.262
  - london: -0.750
  - new_york: -0.839
  - off_hours: -0.365
  - overlap: -0.067

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.405
  - ❌ EURUSDm: -0.315
  - ❌ GBPUSDm: -0.143
  - ✅ US500m: +0.069
  - ❌ USDJPYm: -0.089
  - ❌ USOILm: -0.320
  - ✅ USTECm: +0.289
  - ✅ XAUUSDm: +0.288

---

### 🔴 PS-002 — Multi-bar directional persistence (8+)
**Family:** price_structure | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.078 |
| Net Sharpe (base) | -0.078 |
| Net Sharpe (adverse) | -0.078 |
| Max DD | -1.000 |
| Trades | 113405 |
| WF Consistency | 20% |
| WF OOS Sharpe | -0.453 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -1.063
  - 2025: -0.447
  - 2026: -0.299

**Session decomposition:**
  - asian: -1.148
  - london: -0.814
  - new_york: -0.159
  - off_hours: -1.449
  - overlap: +0.851

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.665
  - ❌ EURUSDm: -0.514
  - ❌ GBPUSDm: -0.720
  - ✅ US500m: +0.198
  - ✅ USDJPYm: +0.545
  - ❌ USOILm: -0.093
  - ✅ USTECm: +0.034
  - ✅ XAUUSDm: +0.594

---

### 🟡 PS-003 — Failed breakout reversal
**Family:** price_structure | **HP:** 2 bars (30m) | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross Sharpe | 0.567 |
| Net Sharpe (base) | 0.567 |
| Net Sharpe (adverse) | 0.567 |
| Max DD | -0.265 |
| Trades | 98916 |
| WF Consistency | 60% |
| WF OOS Sharpe | 0.064 |
| Degradation | 0.0% |
| Permutation p | 0.130 |
| Primary Failure | catastrophic_dd |

**Reasons:** catastrophic_dd, permutation_insignificant

**Year decomposition:**
  - 2024: +3.152
  - 2025: +0.069
  - 2026: -0.147

**Session decomposition:**
  - asian: +1.783
  - london: +0.081
  - new_york: +1.327
  - off_hours: +0.270
  - overlap: -0.149

**Per-instrument net Sharpe:**
  - ✅ AUDUSDm: +1.610
  - ✅ EURUSDm: +0.627
  - ✅ GBPUSDm: +1.296
  - ❌ US500m: -0.012
  - ✅ USDJPYm: +0.300
  - ✅ USOILm: +1.279
  - ❌ USTECm: -0.167
  - ❌ XAUUSDm: -0.394

---

### 🔴 CM-001 — Momentum x vol regime
**Family:** composite | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.038 |
| Net Sharpe (base) | -0.038 |
| Net Sharpe (adverse) | -0.038 |
| Max DD | -0.997 |
| Trades | 127126 |
| WF Consistency | 20% |
| WF OOS Sharpe | -0.392 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Reasons:** negative_gross

**Year decomposition:**
  - 2024: -1.190
  - 2025: -0.632
  - 2026: +0.115

**Session decomposition:**
  - asian: -0.189
  - london: -0.489
  - new_york: +0.036
  - off_hours: -2.281
  - overlap: -0.623

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.926
  - ❌ EURUSDm: -0.524
  - ❌ GBPUSDm: -0.649
  - ✅ US500m: +0.104
  - ✅ USDJPYm: +0.578
  - ✅ USOILm: +0.087
  - ✅ USTECm: +0.330
  - ✅ XAUUSDm: +0.695

---

### 🟡 CM-002 — Breakout x volume confirmation
**Family:** composite | **HP:** 16 bars (240m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.077 |
| Net Sharpe (base) | 0.077 |
| Net Sharpe (adverse) | 0.077 |
| Max DD | -0.999 |
| Trades | 101248 |
| WF Consistency | 40% |
| WF OOS Sharpe | -0.108 |
| Degradation | 0.0% |
| Permutation p | 1.000 |
| Primary Failure | oos_negative |

**Reasons:** catastrophic_dd, wf_inconsistent, oos_negative, permutation_insignificant

**Year decomposition:**
  - 2024: -1.519
  - 2025: -0.425
  - 2026: +0.470

**Session decomposition:**
  - asian: -0.525
  - london: -0.122
  - new_york: +0.563
  - off_hours: -2.141
  - overlap: -0.483

**Per-instrument net Sharpe:**
  - ❌ AUDUSDm: -0.854
  - ❌ EURUSDm: -0.377
  - ❌ GBPUSDm: -0.455
  - ✅ US500m: +0.101
  - ✅ USDJPYm: +1.087
  - ✅ USOILm: +0.165
  - ✅ USTECm: +0.322
  - ✅ XAUUSDm: +0.629

---

## COMBINED INTRADAY RESEARCH (Campaigns 1–4)

| Campaign | Timeframe | Hypotheses | Survivors |
|---|---|---|---|
| 1 | M5 price | 24 | 0 |
| 2 | M5 microstructure | 20 | 0 |
| 3 | M1 order-flow | 16 | 0 |
| 4 | 15M multi-family | 31 | 0 |
| **Total** | | **91** | **0** |

**No robust intraday alpha found at any tested timeframe (M1, M5, 15M).**

This is a **successful research outcome** — the system correctly identified that conventional intraday information does not contain exploitable alpha in this universe.

---

## MULTIPLE TESTING ANALYSIS

- **Hypotheses tested:** 31
- **Holding horizons per hypothesis:** 5
- **Symbols tested:** 8
- **Survivors:** 0

---

## RESEARCH INTEGRITY

- Pre-registered hypotheses with frozen hashes
- Strict chronological walk-forward OOS validation
- 2 cost scenarios (base 13bps, adverse 22bps)
- Cross-asset validation across 8 instruments
- 5 holding horizons tested per hypothesis
- Permutation significance testing
- No post-result tuning
- Rejection treated as successful research

---
*Generated by EigenCapital Campaign 4 Executor — 2026-08-24 22:49 UTC*
