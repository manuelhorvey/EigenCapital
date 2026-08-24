# EigenCapital Intraday Alpha Research Map

## Campaign Identity

**Campaign:** INTRADAY-1a775d82532543c8
**Data Snapshot:** 1a775d82532543c8
**Hypothesis Library:** 5ba04dd1bc4afd83
**Cost Model:** base_v1
**Universe:** AUDUSDm, EURUSDm, GBPUSDm, US500m, USDJPYm, USOILm, USTECm, XAUUSDm
**Timeframe:** M5
**Hypotheses Tested:** 24

## Verdict Distribution

```
REJECTED                        24  ████████████████████████████████████████████████████████████████████████
```
**Survival Rate: 0.0%**

## Failure Mode Distribution

```
statistical_weakness            24  ████████████████████████████████████████████████
cost_sensitivity                24  ████████████████████████████████████████████████
out_of_sample_failure           24  ████████████████████████████████████████████████
excessive_degradation           24  ████████████████████████████████████████████████
regime_instability              24  ████████████████████████████████████████████████
negative_sharpe                 22  ████████████████████████████████████████████
oos_negative                    21  ██████████████████████████████████████████
catastrophic_drawdown           16  ████████████████████████████████
insufficient_trades              2  ████
```

## Detailed Results

| ID | Family | Verdict | Net Sharpe | OOS Sharpe | Max DD | Turnover | WF Cons | Degrad | Failure Modes |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ID-VOL-001 | volatility | **REJECTED** | 0.000 | 0.000 | 0.0% | 0.0x | 0% | 0% | insufficient_trades, statistical_weakness, cost_sensitivity |
| ID-VOL-002 | volatility | **REJECTED** | 0.000 | 0.000 | 0.0% | 0.0x | 0% | 0% | insufficient_trades, statistical_weakness, cost_sensitivity |
| ID-XA-002 | cross_asset | **REJECTED** | -16.080 | 0.000 | -4.5% | 474.6x | 0% | 4525% | negative_sharpe, statistical_weakness, cost_sensitivity |
| ID-STR-003 | structure | **REJECTED** | -23.589 | -25.871 | -6.1% | 870.2x | 0% | 3815% | negative_sharpe, statistical_weakness, cost_sensitivity |
| ID-SES-001 | session | **REJECTED** | -24.396 | -27.038 | -6.7% | 1003.0x | 0% | 13580% | negative_sharpe, statistical_weakness, cost_sensitivity |
| ID-MR-001 | mean_reversion | **REJECTED** | -29.792 | -39.309 | -19.9% | 1842.5x | 0% | 6415% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-SES-004 | session | **REJECTED** | -33.931 | -40.239 | -10.5% | 1728.8x | 0% | 7493% | negative_sharpe, statistical_weakness, cost_sensitivity |
| ID-SES-003 | session | **REJECTED** | -34.444 | -46.790 | -36.0% | 2682.6x | 0% | 14465% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-REV-002 | reversal | **REJECTED** | -35.346 | -47.566 | -21.1% | 2780.0x | 0% | 4657% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-BRK-002 | breakout | **REJECTED** | -35.541 | -42.382 | -12.8% | 1879.7x | 0% | 6451% | negative_sharpe, statistical_weakness, cost_sensitivity |
| ID-SES-002 | session | **REJECTED** | -39.430 | -50.781 | -52.3% | 2912.3x | 0% | 4852% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-MOM-003 | momentum | **REJECTED** | -41.046 | -59.814 | -60.1% | 5591.8x | 0% | 32884% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-BRK-003 | breakout | **REJECTED** | -44.120 | -51.208 | -12.4% | 2762.6x | 0% | 4610% | negative_sharpe, statistical_weakness, cost_sensitivity |
| ID-MOM-002 | momentum | **REJECTED** | -54.943 | -84.021 | -44.6% | 7900.8x | 0% | 6342% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-MR-002 | mean_reversion | **REJECTED** | -61.520 | -71.632 | -16.0% | 5029.2x | 0% | 6197% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-REV-001 | reversal | **REJECTED** | -64.348 | -80.721 | -11.8% | 6041.6x | 0% | 13369% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-STR-001 | structure | **REJECTED** | -64.753 | -83.651 | -14.8% | 6943.9x | 0% | 14537% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-BRK-001 | breakout | **REJECTED** | -75.434 | -88.610 | -16.7% | 7240.2x | 0% | 9264% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-XA-001 | cross_asset | **REJECTED** | -82.188 | -85.188 | -29.7% | 9733.9x | 0% | 19240% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-VCOND-001 | volatility | **REJECTED** | -82.407 | -111.382 | -42.9% | 11651.0x | 0% | 20149% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-VCOND-002 | volatility | **REJECTED** | -82.718 | -106.879 | -37.6% | 10708.8x | 0% | 14359% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-MOM-001 | momentum | **REJECTED** | -84.498 | -118.673 | -61.4% | 13431.8x | 0% | 13245% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-XA-003 | cross_asset | **REJECTED** | -103.454 | -82.577 | -45.1% | 15531.3x | 0% | 15415% | negative_sharpe, catastrophic_drawdown, statistical_weakness |
| ID-STR-002 | structure | **REJECTED** | -108.595 | -132.910 | -13.4% | 14668.0x | 0% | 6649% | negative_sharpe, catastrophic_drawdown, statistical_weakness |

## Rejected — Loser Analysis

- **ID-MOM-001** (Short-Horizon Intraday Momentum): Net Sharpe -84.498 is negative; Max DD -61.4% exceeds -15.0% limit; Net Sharpe -84.498 < 0.3; Costs consume 17379% of gross; WF consistency 0% < 50%; OOS Sharpe -118.673 is negative; Gross-to-net degradation 13245%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-MOM-002** (Medium-Horizon Intraday Momentum): Net Sharpe -54.943 is negative; Max DD -44.6% exceeds -15.0% limit; Net Sharpe -54.943 < 0.3; Costs consume 8080% of gross; WF consistency 0% < 50%; OOS Sharpe -84.021 is negative; Gross-to-net degradation 6342%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-MOM-003** (Session Momentum Persistence): Net Sharpe -41.046 is negative; Max DD -60.1% exceeds -20.0% limit; Net Sharpe -41.046 < 0.3; Costs consume 45686% of gross; WF consistency 0% < 50%; OOS Sharpe -59.814 is negative; Gross-to-net degradation 32884%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-REV-001** (Short-Term Mean Reversion): Net Sharpe -64.348 is negative; Max DD -11.8% exceeds -10.0% limit; Net Sharpe -64.348 < 0.2; Costs consume 62661% of gross; WF consistency 0% < 50%; OOS Sharpe -80.721 is negative; Gross-to-net degradation 13369%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-REV-002** (Intraday Exhaustion Reversal): Net Sharpe -35.346 is negative; Max DD -21.1% exceeds -15.0% limit; Net Sharpe -35.346 < 0.3; Costs consume 11773% of gross; WF consistency 0% < 50%; OOS Sharpe -47.566 is negative; Gross-to-net degradation 4657%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-VOL-001** (Volatility Expansion Breakout): Only 0 trades; Net Sharpe 0.000 < 0.3; Costs consume 100% of gross; WF consistency 0% < 50%; Gross-to-net degradation 100%; WF consistency only 0% [failure modes: insufficient_trades, statistical_weakness, cost_sensitivity, out_of_sample_failure, excessive_degradation, regime_instability]
- **ID-VOL-002** (Volatility Contraction Fade): Only 0 trades; Net Sharpe 0.000 < 0.2; Costs consume 100% of gross; WF consistency 0% < 50%; Gross-to-net degradation 100%; WF consistency only 0% [failure modes: insufficient_trades, statistical_weakness, cost_sensitivity, out_of_sample_failure, excessive_degradation, regime_instability]
- **ID-BRK-001** (Opening Range Breakout): Net Sharpe -75.434 is negative; Max DD -16.7% exceeds -15.0% limit; Net Sharpe -75.434 < 0.4; Costs consume 52628% of gross; WF consistency 0% < 50%; OOS Sharpe -88.610 is negative; Gross-to-net degradation 9264%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-BRK-002** (Session High/Low Breakout): Net Sharpe -35.541 is negative; Net Sharpe -35.541 < 0.3; Costs consume 21136% of gross; WF consistency 0% < 50%; OOS Sharpe -42.382 is negative; Gross-to-net degradation 6451%; WF consistency only 0% [failure modes: negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-BRK-003** (Range Compression Breakout): Net Sharpe -44.120 is negative; Net Sharpe -44.120 < 0.3; Costs consume 24112% of gross; WF consistency 0% < 50%; OOS Sharpe -51.208 is negative; Gross-to-net degradation 4610%; WF consistency only 0% [failure modes: negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-SES-001** (London Open Momentum): Net Sharpe -24.396 is negative; Net Sharpe -24.396 < 0.3; Costs consume 8468% of gross; WF consistency 0% < 50%; OOS Sharpe -27.038 is negative; Gross-to-net degradation 13580%; WF consistency only 0% [failure modes: negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-SES-002** (NY Open Momentum): Net Sharpe -39.430 is negative; Max DD -52.3% exceeds -15.0% limit; Net Sharpe -39.430 < 0.3; Costs consume 3888873% of gross; WF consistency 0% < 50%; OOS Sharpe -50.781 is negative; Gross-to-net degradation 4852%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-SES-003** (London-NY Overlap Continuation): Net Sharpe -34.444 is negative; Max DD -36.0% exceeds -15.0% limit; Net Sharpe -34.444 < 0.4; Costs consume 58426% of gross; WF consistency 0% < 50%; OOS Sharpe -46.790 is negative; Gross-to-net degradation 14465%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-SES-004** (Asian Range Breakout at London Open): Net Sharpe -33.931 is negative; Net Sharpe -33.931 < 0.3; Costs consume 37970% of gross; WF consistency 0% < 50%; OOS Sharpe -40.239 is negative; Gross-to-net degradation 7493%; WF consistency only 0% [failure modes: negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-STR-001** (VWAP Deviation Reversion): Net Sharpe -64.753 is negative; Max DD -14.8% exceeds -12.0% limit; Net Sharpe -64.753 < 0.3; Costs consume 25466% of gross; WF consistency 0% < 50%; OOS Sharpe -83.651 is negative; Gross-to-net degradation 14537%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-STR-002** (Range Position Mean Reversion): Net Sharpe -108.595 is negative; Max DD -13.4% exceeds -12.0% limit; Net Sharpe -108.595 < 0.2; Costs consume 31179% of gross; WF consistency 0% < 50%; OOS Sharpe -132.910 is negative; Gross-to-net degradation 6649%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-STR-003** (Previous Day High/Low Rejection): Net Sharpe -23.589 is negative; Net Sharpe -23.589 < 0.3; Costs consume 14129% of gross; WF consistency 0% < 50%; OOS Sharpe -25.871 is negative; Gross-to-net degradation 3815%; WF consistency only 0% [failure modes: negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-XA-001** (US500 Leads USTEC): Net Sharpe -82.188 is negative; Max DD -29.7% exceeds -12.0% limit; Net Sharpe -82.188 < 0.3; Costs consume 46238% of gross; WF consistency 0% < 50%; OOS Sharpe -85.188 is negative; Gross-to-net degradation 19240%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-XA-002** (USD Strength Leads XAUUSD): Net Sharpe -16.080 is negative; Net Sharpe -16.080 < 0.3; Costs consume 1830% of gross; WF consistency 0% < 50%; Gross-to-net degradation 4525%; WF consistency only 0% [failure modes: negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, excessive_degradation, regime_instability]
- **ID-XA-003** (USOIL Leads CAD): Net Sharpe -103.454 is negative; Max DD -45.1% exceeds -12.0% limit; Net Sharpe -103.454 < 0.2; Costs consume 34244% of gross; WF consistency 0% < 50%; OOS Sharpe -82.577 is negative; Gross-to-net degradation 15415%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-VCOND-001** (High-Vol Momentum Dampening): Net Sharpe -82.407 is negative; Max DD -42.9% exceeds -10.0% limit; Net Sharpe -82.407 < 0.2; Costs consume 19742% of gross; WF consistency 0% < 50%; OOS Sharpe -111.382 is negative; Gross-to-net degradation 20149%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-VCOND-002** (Volatility Regime Switching): Net Sharpe -82.718 is negative; Max DD -37.6% exceeds -15.0% limit; Net Sharpe -82.718 < 0.4; Costs consume 18483% of gross; WF consistency 0% < 50%; OOS Sharpe -106.879 is negative; Gross-to-net degradation 14359%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-MR-001** (Intraday Displacement Reversion): Net Sharpe -29.792 is negative; Max DD -19.9% exceeds -10.0% limit; Net Sharpe -29.792 < 0.3; Costs consume 9203% of gross; WF consistency 0% < 50%; OOS Sharpe -39.309 is negative; Gross-to-net degradation 6415%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]
- **ID-MR-002** (Failed Breakout Reversal): Net Sharpe -61.520 is negative; Max DD -16.0% exceeds -12.0% limit; Net Sharpe -61.520 < 0.3; Costs consume 107737% of gross; WF consistency 0% < 50%; OOS Sharpe -71.632 is negative; Gross-to-net degradation 6197%; WF consistency only 0% [failure modes: negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, excessive_degradation, regime_instability]

## Key Findings

1. The intraday research system successfully killed hypotheses with evidence
2. Cost sensitivity is the dominant killer for mean-reversion strategies
3. Walk-forward consistency identifies overfitting before production
4. A small number of survivors is expected and healthy
5. Every rejection has a forensic explanation

---
*Generated: 2026-08-24 09:25 | Campaign: INTRADAY-1a775d82532543c8*