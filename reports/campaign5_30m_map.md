# CAMPAIGN 5 — 30M MECHANISM-FOCUSED INTRADAY INVESTIGATION

**Universe:** 8 instruments (Exness MT5)
**Timeframe:** 30-minute (M30)
**Bars:** ~50,000 per symbol (~4 years, Apr 2022 – Aug 2026)
**Generated:** 2026-08-24 23:11 UTC
**Hypotheses:** 18 (mechanism-focused, incl. SE-004 continuation)
**Horizons:** 30m / 1h / 2h / 4h
**Costs:** base 13bps, adverse 22bps

---

## VERDICT DISTRIBUTION

| Verdict | Count | Hypotheses |
|---|---|---|
| **REJECTED** | 4 | MH-001, MH-003, XA-102, XA-103 |
| **REGIME_DEPENDENT** | 1 | NR-001 |
| **FRAGILE** | 12 | NC-001, NC-002, NC-003, NR-002, MH-002, MH-004, ST-002, VR-101, VR-102, XA-101, CM-101, CM-102 |
| **SUPPORTED** | 1 | ST-001 |

**Survivors: 1/18**

---

## FAILURE MODE DISTRIBUTION

| Failure Mode | Count |
|---|---|
| catastrophic_dd | 10 |
| negative_gross_alpha | 4 |
| oos_negative | 3 |
| all_gates_passed | 1 |

---

## TOP CANDIDATES

| # | ID | Family | HP | Net Sharpe | Adv Sharpe | MaxDD | WF | Perm p | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | XA-101 | cross_asset | 30m | +0.625 | +0.625 | -0.47 | 80% | 0.100 | fragile |
| 2 | VR-101 | vol_regime | 30m | +0.553 | +0.553 | -0.40 | 80% | 0.120 | fragile |
| 3 | NC-003 | ny_close_rev | 30m | +0.451 | +0.451 | -0.37 | 60% | 0.010 | fragile |
| 4 | NC-001 | ny_close_rev | 30m | +0.433 | +0.433 | -0.38 | 60% | 0.040 | fragile |
| 5 | NC-002 | ny_close_rev | 60m | +0.395 | +0.395 | -0.40 | 60% | 0.080 | fragile |
---

## DETAILED RESULTS

### 🟡 NC-001 — SE-004 continuation: NY-close mean reversion at 30M
**Family:** ny_close_rev | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.433 / +0.433 / +0.433 |
| Max DD | -0.381 |
| Trades | 47034 |
| WF Consistency / OOS Sharpe | 60% / +0.680 |
| Permutation p | 0.040 |
| Primary Failure | catastrophic_dd |

**Sessions:** new_york: +1.47, off_hours: +0.77
**Years:** 2022: +2.30, 2023: +1.67, 2024: +1.50, 2025: -1.09, 2026: +0.05
**Per-instrument:** 7/8 positive

### 🟡 NC-002 — Late-NY fade (UTC 19-21 only)
**Family:** ny_close_rev | **HP:** 60m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.395 / +0.395 / +0.395 |
| Max DD | -0.395 |
| Trades | 27084 |
| WF Consistency / OOS Sharpe | 60% / +0.450 |
| Permutation p | 0.080 |
| Primary Failure | catastrophic_dd |

**Sessions:** new_york: +0.77, off_hours: +1.26
**Years:** 2022: +0.83, 2023: +2.21, 2024: +0.92, 2025: -0.87, 2026: +0.86
**Per-instrument:** 7/8 positive

### 🟡 NC-003 — NY-close reversion x vol regime composite
**Family:** ny_close_rev | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.451 / +0.451 / +0.451 |
| Max DD | -0.371 |
| Trades | 47030 |
| WF Consistency / OOS Sharpe | 60% / +0.803 |
| Permutation p | 0.010 |
| Primary Failure | catastrophic_dd |

**Sessions:** new_york: +1.68, off_hours: +1.23
**Years:** 2022: +2.26, 2023: +1.75, 2024: +1.65, 2025: -0.77, 2026: -0.03
**Per-instrument:** 7/8 positive

### 🟡 NR-001 — NY opening-range breakout (first hour range)
**Family:** ny_range | **HP:** 240m | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.049 / +0.049 / +0.049 |
| Max DD | -0.926 |
| Trades | 30992 |
| WF Consistency / OOS Sharpe | 40% / +0.128 |
| Permutation p | 1.000 |
| Primary Failure | catastrophic_dd |

**Sessions:** new_york: -0.17, off_hours: -0.25
**Years:** 2022: -0.47, 2023: -0.27, 2024: -0.23, 2025: +0.53, 2026: -0.65
**Per-instrument:** 3/8 positive

### 🟡 NR-002 — Intraday closing-range fade during NY
**Family:** ny_range | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.051 / +0.051 / +0.051 |
| Max DD | -0.501 |
| Trades | 27012 |
| WF Consistency / OOS Sharpe | 60% / +0.421 |
| Permutation p | 1.000 |
| Primary Failure | catastrophic_dd |

**Sessions:** new_york: -0.45, off_hours: +0.37
**Years:** 2022: -1.32, 2023: +0.86, 2024: +0.79, 2025: +0.21, 2026: -2.71
**Per-instrument:** 4/8 positive

### 🔴 MH-001 — 2h momentum (4-bar continuation)
**Family:** multihour_mom | **HP:** 240m | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | -0.050 / -0.050 / -0.050 |
| Max DD | -1.000 |
| Trades | 171340 |
| WF Consistency / OOS Sharpe | 60% / -0.002 |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Sessions:** asian: +0.10, london: +0.04, new_york: +0.35, off_hours: -1.75, overlap: -0.13
**Years:** 2022: -0.91, 2023: +0.48, 2024: -0.02, 2025: -0.34, 2026: +0.24
**Per-instrument:** 3/8 positive

### 🟡 MH-002 — 4h momentum vol-adjusted (8-bar)
**Family:** multihour_mom | **HP:** 240m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.038 / +0.038 / +0.038 |
| Max DD | -1.000 |
| Trades | 128443 |
| WF Consistency / OOS Sharpe | 60% / -0.052 |
| Permutation p | 1.000 |
| Primary Failure | oos_negative |

**Sessions:** asian: -0.87, london: +0.32, new_york: +1.19, off_hours: -1.49, overlap: -0.69
**Years:** 2022: -0.98, 2023: +0.34, 2024: -0.33, 2025: -0.56, 2026: +0.47
**Per-instrument:** 4/8 positive

### 🔴 MH-003 — Daily z-score reversal (48-bar lookback)
**Family:** multihour_rev | **HP:** 120m | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | -0.100 / -0.100 / -0.100 |
| Max DD | -0.984 |
| Trades | 58421 |
| WF Consistency / OOS Sharpe | 100% / +0.300 |
| Permutation p | 0.070 |
| Primary Failure | negative_gross_alpha |

**Sessions:** asian: +0.81, london: -0.21, new_york: -0.18, off_hours: +1.44, overlap: +0.27
**Years:** 2022: +1.93, 2023: -0.61, 2024: +1.16, 2025: -0.13, 2026: -0.21
**Per-instrument:** 5/8 positive

### 🟡 MH-004 — Two-day VWAP deviation reversion
**Family:** multihour_rev | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.140 / +0.140 / +0.140 |
| Max DD | -0.503 |
| Trades | 38995 |
| WF Consistency / OOS Sharpe | 80% / +0.465 |
| Permutation p | 0.120 |
| Primary Failure | catastrophic_dd |

**Sessions:** asian: +1.73, london: +0.52, new_york: -1.13, off_hours: +2.04, overlap: +0.16
**Years:** 2022: +2.45, 2023: -0.71, 2024: +1.58, 2025: -0.09, 2026: +0.22
**Per-instrument:** 5/8 positive

### 🟢 ST-001 — Asia→London transition continuation
**Family:** session_transition | **HP:** 30m | **Verdict:** supported

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.304 / +0.304 / +0.304 |
| Max DD | -0.213 |
| Trades | 20514 |
| WF Consistency / OOS Sharpe | 80% / +0.891 |
| Permutation p | 0.020 |
| Primary Failure | all_gates_passed |

**Sessions:** london: +2.00
**Years:** 2022: +1.05, 2023: +0.77, 2024: +1.90, 2025: -0.06, 2026: +1.28
**Per-instrument:** 4/8 positive

### 🟡 ST-002 — London/NY overlap momentum
**Family:** session_transition | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.212 / +0.212 / +0.212 |
| Max DD | -0.379 |
| Trades | 42480 |
| WF Consistency / OOS Sharpe | 60% / -0.129 |
| Permutation p | 0.380 |
| Primary Failure | oos_negative |

**Sessions:** new_york: +0.44, overlap: +0.25
**Years:** 2022: +0.36, 2023: +1.63, 2024: -2.20, 2025: +0.23, 2026: +0.54
**Per-instrument:** 7/8 positive

### 🟡 VR-101 — Vol expansion momentum (20/80 windows)
**Family:** vol_regime | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.553 / +0.553 / +0.553 |
| Max DD | -0.403 |
| Trades | 349969 |
| WF Consistency / OOS Sharpe | 80% / +0.659 |
| Permutation p | 0.120 |
| Primary Failure | catastrophic_dd |

**Sessions:** asian: +1.63, london: +1.26, new_york: -0.64, off_hours: -0.11, overlap: +0.20
**Years:** 2022: +0.63, 2023: +1.95, 2024: +0.36, 2025: -0.81, 2026: +1.08
**Per-instrument:** 7/8 positive

### 🟡 VR-102 — Vol contraction reversal (20/80 windows)
**Family:** vol_regime | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.088 / +0.088 / +0.088 |
| Max DD | -0.419 |
| Trades | 160347 |
| WF Consistency / OOS Sharpe | 60% / -0.400 |
| Permutation p | 1.000 |
| Primary Failure | oos_negative |

**Sessions:** asian: +0.54, london: -0.38, new_york: -0.02, off_hours: -3.10, overlap: -1.75
**Years:** 2022: -1.38, 2023: -0.34, 2024: -1.64, 2025: -0.52, 2026: +0.97
**Per-instrument:** 2/8 positive

### 🟡 XA-101 — US500 leads XAUUSD inverse (C4 XA-003 continuation)
**Family:** cross_asset | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.625 / +0.625 / +0.625 |
| Max DD | -0.472 |
| Trades | 221020 |
| WF Consistency / OOS Sharpe | 80% / +0.653 |
| Permutation p | 0.100 |
| Primary Failure | catastrophic_dd |

**Sessions:** asian: +0.16, london: -0.45, new_york: +0.84, off_hours: -0.69, overlap: +2.36
**Years:** 2022: -0.15, 2023: +1.78, 2024: +1.90, 2025: -0.69, 2026: +0.43
**Per-instrument:** 8/8 positive

### 🔴 XA-102 — USTEC leads EURUSD (C4 XA-002 continuation)
**Family:** cross_asset | **HP:** 240m | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | -0.135 / -0.135 / -0.135 |
| Max DD | -0.999 |
| Trades | 220774 |
| WF Consistency / OOS Sharpe | 20% / -0.656 |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Sessions:** asian: -0.52, london: -0.33, new_york: -0.12, off_hours: -0.46, overlap: -0.75
**Years:** 2022: +0.15, 2023: -0.37, 2024: -1.04, 2025: -0.06, 2026: -1.09
**Per-instrument:** 3/8 positive

### 🔴 XA-103 — USOIL leads USDJPY (C4 XA-004 continuation)
**Family:** cross_asset | **HP:** 120m | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | -0.188 / -0.188 / -0.188 |
| Max DD | -0.989 |
| Trades | 163788 |
| WF Consistency / OOS Sharpe | 40% / -0.151 |
| Permutation p | 1.000 |
| Primary Failure | negative_gross_alpha |

**Sessions:** asian: -0.18, london: -1.08, new_york: +0.63, off_hours: -0.67, overlap: -0.48
**Years:** 2022: -0.92, 2023: -0.54, 2024: +0.51, 2025: -1.22, 2026: +0.96
**Per-instrument:** 2/8 positive

### 🟡 CM-101 — Momentum gated to NY session
**Family:** composite | **HP:** 120m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.097 / +0.097 / +0.097 |
| Max DD | -0.894 |
| Trades | 38014 |
| WF Consistency / OOS Sharpe | 60% / +0.090 |
| Permutation p | 0.120 |
| Primary Failure | catastrophic_dd |

**Sessions:** new_york: +0.43, off_hours: +1.65
**Years:** 2022: +1.27, 2023: +0.00, 2024: -0.10, 2025: -0.47, 2026: +2.01
**Per-instrument:** 4/8 positive

### 🟡 CM-102 — Range breakout x volume confirmation
**Family:** composite | **HP:** 30m | **Verdict:** fragile

| Metric | Value |
|---|---|
| Gross / Net / Adverse Sharpe | +0.296 / +0.296 / +0.296 |
| Max DD | -0.667 |
| Trades | 107188 |
| WF Consistency / OOS Sharpe | 60% / +0.484 |
| Permutation p | 0.160 |
| Primary Failure | catastrophic_dd |

**Sessions:** asian: -1.00, london: +0.81, new_york: +3.07, off_hours: -1.24, overlap: +0.02
**Years:** 2022: -0.67, 2023: +1.26, 2024: -0.38, 2025: +0.14, 2026: +1.74
**Per-instrument:** 5/8 positive

---

## COMBINED INTRADAY RESEARCH (Campaigns 1–5)

| Campaign | Timeframe | Hypotheses | Supported | Fragile+ |
|---|---|---|---|---|
| 1 | M5 price | 24 | 0 | 0 |
| 2 | M5 microstructure | 20 | 0 | 0 |
| 3 | M1 order-flow | 16 | 0 | 1 |
| 4 | 15M multi-family | 31 | 0 | 15 |
| 5 | 30M mechanism-focused | 18 | 1 | 13 |
| **Total** | | **109** | **1** | |

**SURVIVOR(S) FOUND — proceed to independent confirmation (1H) before any fidelity-ladder step.**
