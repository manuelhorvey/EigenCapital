# EigenCapital Intraday Campaign 2 — Microstructure Research Map

## Context

**Campaign 1:** 24/24 price-based M5 hypotheses REJECTED (0% survival)
**Campaign 2:** 20 microstructure/volume hypotheses — different information source

## Campaign Identity

**Data Snapshot:** 1a775d82532543c8
**Broker:** Exness (Terminal 168966110)
**Universe:** AUDUSDm, EURUSDm, GBPUSDm, US500m, USDJPYm, USOILm, USTECm, XAUUSDm
**Timeframe:** M5
**Total Bars:** 400000
**Hypotheses Tested:** 20

## Verdict Distribution

```
REJECTED                        20  ████████████████████████████████████████████████████████████
```
**Survival Rate: 0.0%**

## Failure Mode Distribution

```
negative_sharpe                 20  ████████████████████████████████████████
statistical_weakness            20  ████████████████████████████████████████
cost_sensitivity                20  ████████████████████████████████████████
out_of_sample_failure           20  ████████████████████████████████████████
regime_instability              20  ████████████████████████████████████████
oos_negative                    19  ██████████████████████████████████████
catastrophic_drawdown            1  ██
```

## Detailed Results

| ID | Name | Source | Verdict | Net Sharpe | OOS | Max DD | Turnover | WF | Cost% | Failure Modes |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| MIC-SES-002 | NY Open Volume Surge | session | **REJECTED** | -3.238 | 0.000 | -0.4% | 13.4x | 0% | 1901% | negative_sharpe, statistical_weakness |
| MIC-CMP-003 | Spread-Volume-Range Composite | composite | **REJECTED** | -4.310 | -1.391 | -0.8% | 44.1x | 0% | 3944% | negative_sharpe, statistical_weakness |
| MIC-SPR-003 | Spread-Volume Interaction | spread | **REJECTED** | -5.990 | -3.356 | -0.9% | 78.7x | 0% | 6206% | negative_sharpe, statistical_weakness |
| MIC-RNG-002 | Range Compression Breakout | range | **REJECTED** | -9.231 | -8.250 | -0.6% | 112.1x | 0% | 3969% | negative_sharpe, statistical_weakness |
| MIC-SES-001 | London Open Volume Surge | session | **REJECTED** | -14.579 | -22.335 | -1.1% | 319.5x | 0% | 79721% | negative_sharpe, statistical_weakness |
| MIC-CMP-004 | Liquidity Withdrawal Signal | composite | **REJECTED** | -15.053 | -33.438 | -0.2% | 453.8x | 0% | 23658% | negative_sharpe, statistical_weakness |
| MIC-SPR-001 | Spread Expansion Contrarian | spread | **REJECTED** | -15.726 | -29.410 | -0.8% | 523.8x | 0% | 3474% | negative_sharpe, statistical_weakness |
| MIC-CMP-002 | Volume-Range Divergence | composite | **REJECTED** | -16.797 | -19.053 | -1.2% | 418.2x | 0% | 10440% | negative_sharpe, statistical_weakness |
| MIC-SPR-002 | Spread Tightening Continuation | spread | **REJECTED** | -20.313 | -35.949 | -1.9% | 788.9x | 0% | 6541% | negative_sharpe, statistical_weakness |
| MIC-SES-004 | End-of-Session Exhaustion | session | **REJECTED** | -29.822 | -30.895 | -1.6% | 1293.1x | 0% | 15603% | negative_sharpe, statistical_weakness |
| MIC-SES-003 | Session Transition Volatility | session | **REJECTED** | -43.563 | -53.121 | -4.2% | 2669.9x | 0% | 16551% | negative_sharpe, statistical_weakness |
| MIC-VOL-001 | Volume Spike Momentum | volume | **REJECTED** | -58.022 | -69.127 | -7.3% | 5327.6x | 0% | 48463% | negative_sharpe, statistical_weakness |
| MIC-VOL-003 | Volume-Price Divergence | volume | **REJECTED** | -59.225 | -64.956 | -2.4% | 4253.3x | 0% | 56611% | negative_sharpe, statistical_weakness |
| MIC-VOL-002 | Volume Dry-Up Reversal | volume | **REJECTED** | -66.997 | -79.626 | -4.9% | 6334.8x | 0% | 39924% | negative_sharpe, statistical_weakness |
| MIC-CMP-005 | Volume-Session Momentum | composite | **REJECTED** | -73.593 | -92.878 | -9.5% | 8766.1x | 0% | 43950% | negative_sharpe, statistical_weakness |
| MIC-CMP-001 | Volume-Range Momentum | composite | **REJECTED** | -82.406 | -100.574 | -8.1% | 9722.1x | 0% | 46644% | negative_sharpe, statistical_weakness |
| MIC-VOL-004 | Volume-Weighted Momentum | volume | **REJECTED** | -87.957 | -117.944 | -15.6% | 13455.8x | 0% | 39422% | negative_sharpe, catastrophic_drawdown |
| MIC-RNG-001 | Range Expansion Momentum | range | **REJECTED** | -109.936 | -127.394 | -10.4% | 15047.5x | 0% | 81889% | negative_sharpe, statistical_weakness |
| MIC-RNG-003 | Bar Body Ratio Momentum | range | **REJECTED** | -175.203 | -203.379 | -11.3% | 27921.6x | 0% | 163663% | negative_sharpe, statistical_weakness |
| MIC-RNG-004 | Upper/Lower Shadow Rejection | range | **REJECTED** | -189.155 | -219.600 | -8.6% | 31204.6x | 0% | 110984% | negative_sharpe, statistical_weakness |

## Rejected — Loser Analysis

- **MIC-VOL-001** (Volume Spike Momentum): Net Sharpe -58.022; Net Sharpe -58.022 < 0.3; Costs 48463% of gross; WF consistency 0%; OOS Sharpe -69.127 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-VOL-002** (Volume Dry-Up Reversal): Net Sharpe -66.997; Net Sharpe -66.997 < 0.3; Costs 39924% of gross; WF consistency 0%; OOS Sharpe -79.626 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-VOL-003** (Volume-Price Divergence): Net Sharpe -59.225; Net Sharpe -59.225 < 0.3; Costs 56611% of gross; WF consistency 0%; OOS Sharpe -64.956 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-VOL-004** (Volume-Weighted Momentum): Net Sharpe -87.957; Max DD -15.6%; Net Sharpe -87.957 < 0.3; Costs 39422% of gross; WF consistency 0%; OOS Sharpe -117.944 [negative_sharpe, catastrophic_drawdown, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-SPR-001** (Spread Expansion Contrarian): Net Sharpe -15.725; Net Sharpe -15.725 < 0.3; Costs 3474% of gross; WF consistency 0%; OOS Sharpe -29.410 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-SPR-002** (Spread Tightening Continuation): Net Sharpe -20.313; Net Sharpe -20.313 < 0.3; Costs 6541% of gross; WF consistency 0%; OOS Sharpe -35.949 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-SPR-003** (Spread-Volume Interaction): Net Sharpe -5.990; Net Sharpe -5.990 < 0.3; Costs 6206% of gross; WF consistency 0%; OOS Sharpe -3.356 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-RNG-001** (Range Expansion Momentum): Net Sharpe -109.936; Net Sharpe -109.936 < 0.3; Costs 81889% of gross; WF consistency 0%; OOS Sharpe -127.394 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-RNG-002** (Range Compression Breakout): Net Sharpe -9.231; Net Sharpe -9.231 < 0.3; Costs 3969% of gross; WF consistency 0%; OOS Sharpe -8.250 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-RNG-003** (Bar Body Ratio Momentum): Net Sharpe -175.203; Net Sharpe -175.203 < 0.3; Costs 163663% of gross; WF consistency 0%; OOS Sharpe -203.379 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-RNG-004** (Upper/Lower Shadow Rejection): Net Sharpe -189.155; Net Sharpe -189.155 < 0.3; Costs 110984% of gross; WF consistency 0%; OOS Sharpe -219.600 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-SES-001** (London Open Volume Surge): Net Sharpe -14.579; Net Sharpe -14.579 < 0.4; Costs 79721% of gross; WF consistency 0%; OOS Sharpe -22.335 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-SES-002** (NY Open Volume Surge): Net Sharpe -3.238; Net Sharpe -3.238 < 0.4; Costs 1901% of gross; WF consistency 0% [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, regime_instability]
- **MIC-SES-003** (Session Transition Volatility): Net Sharpe -43.563; Net Sharpe -43.563 < 0.3; Costs 16551% of gross; WF consistency 0%; OOS Sharpe -53.121 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-SES-004** (End-of-Session Exhaustion): Net Sharpe -29.822; Net Sharpe -29.822 < 0.3; Costs 15603% of gross; WF consistency 0%; OOS Sharpe -30.895 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-CMP-001** (Volume-Range Momentum): Net Sharpe -82.406; Net Sharpe -82.406 < 0.4; Costs 46644% of gross; WF consistency 0%; OOS Sharpe -100.574 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-CMP-002** (Volume-Range Divergence): Net Sharpe -16.797; Net Sharpe -16.797 < 0.3; Costs 10440% of gross; WF consistency 0%; OOS Sharpe -19.053 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-CMP-003** (Spread-Volume-Range Composite): Net Sharpe -4.310; Net Sharpe -4.310 < 0.4; Costs 3944% of gross; WF consistency 0%; OOS Sharpe -1.391 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-CMP-004** (Liquidity Withdrawal Signal): Net Sharpe -15.053; Net Sharpe -15.053 < 0.3; Costs 23658% of gross; WF consistency 0%; OOS Sharpe -33.438 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]
- **MIC-CMP-005** (Volume-Session Momentum): Net Sharpe -73.593; Net Sharpe -73.593 < 0.3; Costs 43950% of gross; WF consistency 0%; OOS Sharpe -92.878 [negative_sharpe, statistical_weakness, cost_sensitivity, out_of_sample_failure, oos_negative, regime_instability]

## Key Findings

1. Campaign 2 tests a fundamentally different information source than Campaign 1
2. Volume, spread, and range patterns are tested instead of pure price momentum
3. The research system maintains the same forensic discipline
4. A rejection here means: microstructure signals also don't survive at M5
5. If both Campaign 1 and 2 fail, the conclusion is about the M5 frequency/universe, not the research system

---
*Generated: 2026-08-24 09:32 | Data: 400000 bars | Snapshot: 1a775d82532543c8*