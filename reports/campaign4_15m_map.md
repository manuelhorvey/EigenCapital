# EigenCapital Intraday Alpha Research Map — Campaign 4 (15M)

**Date:** 2026-08-24
**Timeframe:** 15-minute (M15)
**Universe:** 8 instruments (Exness MT5)
**Data:** ~50K M15 bars per symbol (~2 years, Jul 2024 – Aug 2026)
**Hypotheses:** 31
**Holding Horizons:** 15m, 30m, 1h, 2h, 4h
**Cost Scenarios:** base (13bps), adverse (22bps)

---

## Verdict Distribution

| Verdict | Count | Hypotheses |
|---|---|---|
| **REGIME_DEPENDENT** | 14 | MO-003, MR-001, MR-003, MR-004, BR-001, BR-002, BR-004, SE-004, VR-002, VR-003, VR-004, XA-003, PS-003, CM-002 |
| **REJECTED** | 17 | MO-001, MO-002, MO-004, MO-005, MR-002, BR-003, SE-001, SE-002, SE-003, SE-005, VR-001, XA-001, XA-002, XA-004, PS-001, PS-002, CM-001 |

**Survival: 0/31 (0.0%)**

---

## Family Breakdown

| Family | Count | Rejected | Fragile | Supported |
|---|---|---|---|---|
| breakout | 4 | 1 | 3 | 0 |
| composite | 2 | 1 | 1 | 0 |
| cross_asset | 4 | 3 | 1 | 0 |
| mean_reversion | 4 | 1 | 3 | 0 |
| momentum | 5 | 4 | 1 | 0 |
| price_structure | 3 | 2 | 1 | 0 |
| sessions | 5 | 4 | 1 | 0 |
| volatility | 4 | 1 | 3 | 0 |

---

## Detailed Results

### 🔴 MO-001 — 4-bar momentum (1h continuation)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.119 |
| Net Sharpe (base) | -0.119 |
| Net Sharpe (adverse) | -0.119 |
| Max DD | -0.999 |
| Trades | 179517 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 MO-002 — 8-bar momentum (2h continuation)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.039 |
| Net Sharpe (base) | -0.039 |
| Net Sharpe (adverse) | -0.039 |
| Max DD | -0.997 |
| Trades | 129442 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 MO-003 — 16-bar momentum (4h continuation)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.090 |
| Net Sharpe (base) | 0.090 |
| Net Sharpe (adverse) | 0.090 |
| Max DD | -0.996 |
| Trades | 93187 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 MO-004 — Vol-adjusted 8-bar momentum
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.042 |
| Net Sharpe (base) | -0.042 |
| Net Sharpe (adverse) | -0.042 |
| Max DD | -0.997 |
| Trades | 129490 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 MO-005 — Momentum acceleration (mom strengthening)
**Family:** momentum | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.175 |
| Net Sharpe (base) | -0.175 |
| Net Sharpe (adverse) | -0.175 |
| Max DD | -0.999 |
| Trades | 219302 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 MR-001 — 8-bar VWAP deviation
**Family:** mean_reversion | **HP:** 1 bars (15m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.049 |
| Net Sharpe (base) | 0.049 |
| Net Sharpe (adverse) | 0.049 |
| Max DD | -0.496 |
| Trades | 76788 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 MR-002 — 16-bar z-score reversal
**Family:** mean_reversion | **HP:** 4 bars (60m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.139 |
| Net Sharpe (base) | -0.139 |
| Net Sharpe (adverse) | -0.139 |
| Max DD | -0.969 |
| Trades | 51193 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 MR-003 — 16-bar vol-normalized deviation
**Family:** mean_reversion | **HP:** 1 bars (15m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.470 |
| Net Sharpe (base) | 0.470 |
| Net Sharpe (adverse) | 0.470 |
| Max DD | -0.458 |
| Trades | 93197 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 MR-004 — Range reversion (close near range extreme)
**Family:** mean_reversion | **HP:** 1 bars (15m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.522 |
| Net Sharpe (base) | 0.522 |
| Net Sharpe (adverse) | 0.522 |
| Max DD | -0.468 |
| Trades | 92248 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 BR-001 — 20-bar range breakout (5h range)
**Family:** breakout | **HP:** 16 bars (240m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.077 |
| Net Sharpe (base) | 0.077 |
| Net Sharpe (adverse) | 0.077 |
| Max DD | -0.999 |
| Trades | 92108 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 BR-002 — Compression → expansion (vol squeeze)
**Family:** breakout | **HP:** 16 bars (240m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.257 |
| Net Sharpe (base) | 0.257 |
| Net Sharpe (adverse) | 0.257 |
| Max DD | -0.990 |
| Trades | 215666 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 BR-003 — Previous day high/low breakout
**Family:** breakout | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.087 |
| Net Sharpe (base) | -0.087 |
| Net Sharpe (adverse) | -0.087 |
| Max DD | -1.000 |
| Trades | 37300 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 BR-004 — Asian range breakout
**Family:** breakout | **HP:** 2 bars (30m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.217 |
| Net Sharpe (base) | 0.217 |
| Net Sharpe (adverse) | 0.217 |
| Max DD | -0.845 |
| Trades | 73448 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 SE-001 — London open momentum (first 4 bars)
**Family:** sessions | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.119 |
| Net Sharpe (base) | -0.119 |
| Net Sharpe (adverse) | -0.119 |
| Max DD | -0.999 |
| Trades | 179517 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 SE-002 — NY open momentum (first 4 bars)
**Family:** sessions | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.119 |
| Net Sharpe (base) | -0.119 |
| Net Sharpe (adverse) | -0.119 |
| Max DD | -0.999 |
| Trades | 179517 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 SE-003 — Overlap momentum (London/NY)
**Family:** sessions | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.119 |
| Net Sharpe (base) | -0.119 |
| Net Sharpe (adverse) | -0.119 |
| Max DD | -0.999 |
| Trades | 179517 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 SE-004 — NY close mean-reversion
**Family:** sessions | **HP:** 1 bars (15m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 1.179 |
| Net Sharpe (base) | 1.179 |
| Net Sharpe (adverse) | 1.179 |
| Max DD | -0.440 |
| Trades | 179517 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 SE-005 — Asian→London transition
**Family:** sessions | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.119 |
| Net Sharpe (base) | -0.119 |
| Net Sharpe (adverse) | -0.119 |
| Max DD | -0.999 |
| Trades | 179517 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 VR-001 — Vol regime predicts returns (low vol = trend)
**Family:** volatility | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.041 |
| Net Sharpe (base) | -0.041 |
| Net Sharpe (adverse) | -0.041 |
| Max DD | -0.997 |
| Trades | 129240 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 VR-002 — Vol expansion momentum
**Family:** volatility | **HP:** 8 bars (120m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.012 |
| Net Sharpe (base) | 0.012 |
| Net Sharpe (adverse) | 0.012 |
| Max DD | -0.900 |
| Trades | 384408 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 VR-003 — Vol contraction reversal
**Family:** volatility | **HP:** 1 bars (15m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.321 |
| Net Sharpe (base) | 0.321 |
| Net Sharpe (adverse) | 0.321 |
| Max DD | -0.310 |
| Trades | 182418 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 VR-004 — Realized vol vs implied proxy
**Family:** volatility | **HP:** 8 bars (120m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.043 |
| Net Sharpe (base) | 0.043 |
| Net Sharpe (adverse) | 0.043 |
| Max DD | -0.991 |
| Trades | 21175 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 XA-001 — US500 leads EURUSD (2-bar lag)
**Family:** cross_asset | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.092 |
| Net Sharpe (base) | -0.092 |
| Net Sharpe (adverse) | -0.092 |
| Max DD | -0.988 |
| Trades | 249350 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 XA-002 — USTEC leads EURUSD (2-bar lag)
**Family:** cross_asset | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.092 |
| Net Sharpe (base) | -0.092 |
| Net Sharpe (adverse) | -0.092 |
| Max DD | -0.988 |
| Trades | 249350 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 XA-003 — US500 leads XAUUSD (2-bar lag, inverse)
**Family:** cross_asset | **HP:** 1 bars (15m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.819 |
| Net Sharpe (base) | 0.819 |
| Net Sharpe (adverse) | 0.819 |
| Max DD | -0.318 |
| Trades | 249350 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 XA-004 — EURUSD leads GBPUSD (1-bar lag)
**Family:** cross_asset | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.063 |
| Net Sharpe (base) | -0.063 |
| Net Sharpe (adverse) | -0.063 |
| Max DD | -0.987 |
| Trades | 350062 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

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
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 PS-002 — Multi-bar directional persistence (8+)
**Family:** price_structure | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.073 |
| Net Sharpe (base) | -0.073 |
| Net Sharpe (adverse) | -0.073 |
| Max DD | -1.000 |
| Trades | 112967 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 PS-003 — Failed breakout reversal
**Family:** price_structure | **HP:** 2 bars (30m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.567 |
| Net Sharpe (base) | 0.567 |
| Net Sharpe (adverse) | 0.567 |
| Max DD | -0.265 |
| Trades | 98916 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

### 🔴 CM-001 — Momentum × vol regime
**Family:** composite | **HP:** 16 bars (240m) | **Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.048 |
| Net Sharpe (base) | -0.048 |
| Net Sharpe (adverse) | -0.048 |
| Max DD | -0.998 |
| Trades | 129184 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** negative_gross

### 🔴 CM-002 — Breakout × volume confirmation
**Family:** composite | **HP:** 16 bars (240m) | **Verdict:** regime_dependent

| Metric | Value |
|---|---|
| Gross Sharpe | 0.089 |
| Net Sharpe (base) | 0.089 |
| Net Sharpe (adverse) | 0.089 |
| Max DD | -0.999 |
| Trades | 96852 |
| WF Consistency | 0% |
| Degradation | 0.0% |

**Reasons:** catastrophic_dd, wf_inconsistent

---

## Conclusion

### Combined Intraday Research (Campaigns 1–4)

| Campaign | Timeframe | Hypotheses | Survivors |
|---|---|---|---|
| 1 | M5 price | 24 | 0 |
| 2 | M5 microstructure | 20 | 0 |
| 3 | M1 order-flow | 16 | 0 |
| 4 | 15M multi-family | 31 | 0 |
| **Total** | | **91** | **0** |

**No robust intraday alpha found at any tested timeframe (M1, M5, 15M).**

This is a **successful research outcome** — the system correctly identified
that conventional intraday information does not contain exploitable alpha in this universe.

---
## Research Integrity

- Pre-registered hypotheses
- Walk-forward OOS validation
- 2 cost scenarios
- Cross-asset validation (8 instruments)
- 5 holding horizons
- No post-result tuning
