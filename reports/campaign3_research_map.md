# EigenCapital Intraday Alpha Research Map — Campaign 3

## M1/Tick-Level Research

**Date:** 2026-08-24
**Timeframe:** 1-minute (M1)
**Universe:** 8 instruments (EURUSDm, GBPUSDm, USDJPYm, AUDUSDm, XAUUSDm, US500m, USTECm, USOILm)
**Data:** ~100K M1 bars per symbol (~3 months, May-Aug 2026)
**Broker:** Exness MT5 (Terminal 168966110)
**Hypotheses:** 16

---

## Hypothesis Families

| Family | Hypotheses | Information Source |
|---|---|---|
| Order-Flow Proxies | OF-001 to OF-004 | Tick direction, volume imbalance, VWAP, aggressor |
| Liquidity Dynamics | LQ-001 to LQ-003 | Spread shocks, volume bursts, combined |
| Price Structure M1 | PS-001 to PS-004 | Range, momentum, reversal, acceleration |
| Volatility Regime | VR-001 | Realized vol vs average |
| Session Microstructure | SS-001 to SS-002 | Session open, overnight gaps |
| Composite | CP-001 to CP-002 | Order-flow × liquidity, momentum × vol |

---

## Results

### Verdict Distribution

| Verdict | Count | Hypotheses |
|---|---|---|
| **COST_SENSITIVE** | 1 | VR-001 |
| **REJECTED** | 15 | OF-001, OF-002, OF-003, OF-004, LQ-001, LQ-002, LQ-003, PS-001, PS-002, PS-003, PS-004, SS-001, SS-002, CP-001, CP-002 |

**Survival Rate: 0/16 (0.0%)**

---

## Detailed Results

### 🔴 OF-001 — Tick direction persistence: net up/down ticks predict next-bar direction

**Family:** order_flow
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.1223 |
| Net Sharpe | -34.1701 |
| OOS Sharpe | -69.5486 |
| Max Drawdown | -0.9974 |
| Turnover | 19088.6 |
| Trades | 152709 |
| Cost | 198.521700 |
| Gross→Net Degradation | -27846.1% |
| WF Consistency | 0% |
| Pre-registered Hash | 97930718c1733d9e |

**Failure Reasons:** negative_gross_sharpe

### 🔴 OF-002 — Volume-weighted direction: volume-weighted up vs down flow predicts continuation

**Family:** order_flow
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.2853 |
| Net Sharpe | -30.1550 |
| OOS Sharpe | -60.3329 |
| Max Drawdown | -0.9989 |
| Turnover | 17324.8 |
| Trades | 138598 |
| Cost | 180.177400 |
| Gross→Net Degradation | -10469.3% |
| WF Consistency | 0% |
| Pre-registered Hash | ec6a3bfb30851578 |

**Failure Reasons:** negative_gross_sharpe

### 🔴 OF-003 — VWAP deviation: distance from rolling VWAP predicts reversion or continuation

**Family:** order_flow
**Holding Period:** 60 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -1.3661 |
| Net Sharpe | -13.8537 |
| OOS Sharpe | -25.7157 |
| Max Drawdown | -1.0000 |
| Turnover | 14527.5 |
| Trades | 116220 |
| Cost | 151.086000 |
| Gross→Net Degradation | -914.1% |
| WF Consistency | 0% |
| Pre-registered Hash | 565b6c127a345470 |

**Failure Reasons:** negative_gross_sharpe

### 🔴 OF-004 — Aggressor proxy: close vs mid-price direction predicts next-bar movement

**Family:** order_flow
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.2302 |
| Net Sharpe | -32.5287 |
| OOS Sharpe | -64.8501 |
| Max Drawdown | -0.9987 |
| Turnover | 18269.6 |
| Trades | 146157 |
| Cost | 190.004100 |
| Gross→Net Degradation | -14029.5% |
| WF Consistency | 0% |
| Pre-registered Hash | 608eb7e30b873246 |

**Failure Reasons:** negative_gross_sharpe

### 🔴 LQ-001 — Spread shock: spread widening predicts volatility expansion or reversal

**Family:** liquidity
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | 0.1832 |
| Net Sharpe | 0.0357 |
| OOS Sharpe | 1.0508 |
| Max Drawdown | -1.0000 |
| Turnover | 55.5 |
| Trades | 444 |
| Cost | 0.577200 |
| Gross→Net Degradation | 80.5% |
| WF Consistency | 75% |
| Pre-registered Hash | 4365ac6b371f66c8 |

**Failure Reasons:** catastrophic_drawdown, excessive_cost_degradation

### 🔴 LQ-002 — Volume burst: sudden volume increase predicts directional move or exhaustion

**Family:** liquidity
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | 0.2095 |
| Net Sharpe | -2.5377 |
| OOS Sharpe | -4.6615 |
| Max Drawdown | -1.0000 |
| Turnover | 1312.0 |
| Trades | 10496 |
| Cost | 13.644800 |
| Gross→Net Degradation | 1311.2% |
| WF Consistency | 0% |
| Pre-registered Hash | a0ba12bbda9f16e2 |

**Failure Reasons:** negative_net_sharpe, catastrophic_drawdown, excessive_cost_degradation, wf_inconsistent, oos_negative

### 🔴 LQ-003 — Combined liquidity signal: spread shock + volume burst interaction

**Family:** liquidity
**Holding Period:** 20 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | 0.1952 |
| Net Sharpe | -4.1160 |
| OOS Sharpe | -8.0066 |
| Max Drawdown | -0.9998 |
| Turnover | 1356.2 |
| Trades | 10850 |
| Cost | 14.105000 |
| Gross→Net Degradation | 2209.0% |
| WF Consistency | 0% |
| Pre-registered Hash | 909666e4ab894c36 |

**Failure Reasons:** negative_net_sharpe, catastrophic_drawdown, excessive_cost_degradation, wf_inconsistent, oos_negative

### 🔴 PS-001 — Range position: where price sits within recent range predicts breakout or reversion

**Family:** price_structure
**Holding Period:** 60 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | 0.0825 |
| Net Sharpe | -5.6006 |
| OOS Sharpe | -10.8624 |
| Max Drawdown | -1.0000 |
| Turnover | 6494.8 |
| Trades | 51958 |
| Cost | 67.545400 |
| Gross→Net Degradation | 6891.8% |
| WF Consistency | 0% |
| Pre-registered Hash | 38a2eeb803147f05 |

**Failure Reasons:** negative_net_sharpe, catastrophic_drawdown, excessive_cost_degradation, wf_inconsistent, oos_negative

### 🔴 PS-002 — Intraday momentum: short-horizon M1 momentum — micro-momentum different from M5

**Family:** price_structure
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.4837 |
| Net Sharpe | -52.4620 |
| OOS Sharpe | -102.4075 |
| Max Drawdown | -0.9985 |
| Turnover | 29114.0 |
| Trades | 232912 |
| Cost | 302.785600 |
| Gross→Net Degradation | -10745.7% |
| WF Consistency | 0% |
| Pre-registered Hash | 57f0e0e12c56a54c |

**Failure Reasons:** negative_gross_sharpe

### 🔴 PS-003 — Reversal extreme: standardized displacement from mean predicts reversion

**Family:** price_structure
**Holding Period:** 60 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | 0.9729 |
| Net Sharpe | -16.6924 |
| OOS Sharpe | -34.2968 |
| Max Drawdown | -0.9982 |
| Turnover | 20244.2 |
| Trades | 161954 |
| Cost | 210.540200 |
| Gross→Net Degradation | 1815.7% |
| WF Consistency | 0% |
| Pre-registered Hash | d82435d8be6251d5 |

**Failure Reasons:** negative_net_sharpe, catastrophic_drawdown, excessive_cost_degradation, wf_inconsistent, oos_negative

### 🔴 PS-004 — Price acceleration: second derivative of price predicts continuation or exhaustion

**Family:** price_structure
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.2075 |
| Net Sharpe | -178.0223 |
| OOS Sharpe | -350.5796 |
| Max Drawdown | -0.8549 |
| Turnover | 88662.0 |
| Trades | 709296 |
| Cost | 922.084800 |
| Gross→Net Degradation | -85689.6% |
| WF Consistency | 0% |
| Pre-registered Hash | f5fd0299d098e77e |

**Failure Reasons:** negative_gross_sharpe

### 🟡 VR-001 — Realized vol regime: current vol vs average predicts expansion or contraction

**Family:** volatility_regime
**Holding Period:** 60 M1 bars
**Verdict:** cost_sensitive

| Metric | Value |
|---|---|
| Gross Sharpe | 0.1992 |
| Net Sharpe | 0.1974 |
| OOS Sharpe | 1.5477 |
| Max Drawdown | -1.0000 |
| Turnover | 3.8 |
| Trades | 30 |
| Cost | 0.039000 |
| Gross→Net Degradation | 0.9% |
| WF Consistency | 75% |
| Pre-registered Hash | 3f47f6a5a6cd4cde |

**Failure Reasons:** catastrophic_drawdown

### 🔴 SS-001 — Session open momentum: first-bar direction predicts session continuation

**Family:** session_structure
**Holding Period:** 60 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -1.2280 |
| Net Sharpe | -16.0219 |
| OOS Sharpe | -30.3578 |
| Max Drawdown | -1.0000 |
| Turnover | 17102.5 |
| Trades | 136820 |
| Cost | 177.866000 |
| Gross→Net Degradation | -1204.7% |
| WF Consistency | 0% |
| Pre-registered Hash | 6ed1267a82676e2b |

**Failure Reasons:** negative_gross_sharpe

### 🔴 SS-002 — Overnight gap behavior: gap size/direction predicts intraday fill or continuation

**Family:** session_structure
**Holding Period:** 120 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.1605 |
| Net Sharpe | -4.4239 |
| OOS Sharpe | -7.3997 |
| Max Drawdown | -1.0000 |
| Turnover | 10059.2 |
| Trades | 80474 |
| Cost | 104.616200 |
| Gross→Net Degradation | -2656.4% |
| WF Consistency | 0% |
| Pre-registered Hash | b5fadd441b948f5d |

**Failure Reasons:** negative_gross_sharpe

### 🔴 CP-001 — Order-flow + liquidity composite: tick direction conditioned on volume burst

**Family:** composite
**Holding Period:** 20 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.0678 |
| Net Sharpe | -58.5509 |
| OOS Sharpe | -119.4330 |
| Max Drawdown | -0.9724 |
| Turnover | 21126.1 |
| Trades | 169009 |
| Cost | 219.711700 |
| Gross→Net Degradation | -86196.8% |
| WF Consistency | 0% |
| Pre-registered Hash | 217b35587b897cf6 |

**Failure Reasons:** negative_gross_sharpe

### 🔴 CP-002 — Momentum + volatility regime: momentum signal conditioned on vol state

**Family:** composite
**Holding Period:** 30 M1 bars
**Verdict:** rejected

| Metric | Value |
|---|---|
| Gross Sharpe | -0.4948 |
| Net Sharpe | -52.4366 |
| OOS Sharpe | -102.6174 |
| Max Drawdown | -0.9986 |
| Turnover | 29049.8 |
| Trades | 232398 |
| Cost | 302.117400 |
| Gross→Net Degradation | -10497.5% |
| WF Consistency | 0% |
| Pre-registered Hash | e660c72e0bc04d38 |

**Failure Reasons:** negative_gross_sharpe

---

## Conclusions

**No robust M1 intraday alpha found** in this universe and sample.

Combined with Campaigns 1-2 (M5 → 44/44 rejected), the total M5+M1 research:

- **Campaign 1:** M5 price-based → 24/24 rejected
- **Campaign 2:** M5 microstructure → 20/20 rejected
- **Campaign 3:** M1 order-flow/liquidity → 16/16 rejected or fragile

**Total: 44+ M5 hypotheses rejected, M1 hypotheses rejected/fragile.**

This is a **successful research outcome** — the system correctly identified
that conventional intraday information at these resolutions does not contain
robust exploitable alpha in this universe.

---

## Research Integrity

- All hypotheses pre-registered before evaluation
- Walk-forward OOS validation
- Realistic transaction costs (13 bps per trade)
- Multiple-holding-period testing
- Cross-asset validation across 8 instruments
- No post-result tuning
- Rejection treated as successful research
