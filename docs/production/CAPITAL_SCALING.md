# Capital Scaling

This document describes the capital tier system and promotion criteria.

Last updated: 2026-08-26

## Current Tier

**$5K — CONTROLLED QUALIFICATION (LIVE)**

| Parameter | Value |
|---|---|
| Campaign tier | $5,000 |
| Authorized capital | $5,100 |
| Max position | $5,000 |
| Max concurrent | 19 |
| Universe | 24 symbols |
| Status | 🟢 Live, collecting evidence |

## Tier Definitions

| Tier | Max Position | Max Concurrent | Universe | Status |
|---|---|---|---|---|
| $5K | $5,000 | 19 | 24 | 🟢 Live |
| $10K | $10,000 | TBD | TBD | 🔴 Not qualified |
| $25K | $25,000 | TBD | TBD | 🔴 Not qualified |
| $50K | $50,000 | TBD | TBD | 🔴 Not qualified |
| $100K | $100,000 | TBD | TBD | 🔴 Not qualified |

## Promotion Criteria

### $5K → $10K

Before promoting, ALL of the following must be demonstrated:

| # | Criterion | Evidence Required |
|---|---|---|
| 1 | No unresolved P0/P1 safety defects | Safety audit, adversarial tests |
| 2 | Live execution consistent with reconstruction | Entry/exit comparison |
| 3 | No unexplained reconciliation mismatches | Reconciliation logs |
| 4 | Catastrophic protection functional | SL execution evidence |
| 5 | Daily-loss and DD controls intact | Risk gate logs |
| 6 | Correlated stress within envelope | Portfolio stress tests |
| 7 | Sufficient live trades/holding periods | 30+ days, 50+ trades |
| 8 | No material cost degradation | Spread/slippage analysis |
| 9 | Fresh capital-tier risk calculation | Updated stress tests |
| 10 | Strategy remains frozen | No parameter changes |

### $10K → $25K

Same criteria, plus:

- Demonstrate $10K tier stability over 60+ days
- Portfolio correlation analysis at scale
- Liquidity impact assessment
- Broker capacity verification

### $25K → $50K+

- Formal strategy capacity analysis
- Multi-broker readiness
- Institutional-grade risk controls
- Regulatory compliance review

## What Changes at Each Tier

| Aspect | $5K | $10K | $25K+ |
|---|---|---|---|
| Position size | $5,000 | $10,000 | $25,000 |
| Notional exposure | ~$95K | ~$190K | ~$475K |
| Margin usage | ~15% | ~30% | ~75% |
| Liquidity impact | Minimal | Low | Moderate |
| Slippage risk | Low | Low-Medium | Medium |

## Liquidity Constraints

| Symbol | Avg Daily Volume | $5K Notional | $10K Notional | Impact |
|---|---|---|---|---|
| EURUSD | Very High | 0.01 lots | 0.01 lots | Negligible |
| GBPUSD | Very High | 0.01 lots | 0.01 lots | Negligible |
| USDJPY | Very High | Excluded | Excluded | N/A |
| XAUUSD | High | 0.01 lots | 0.02 lots | Low |
| US30 | Medium | 0.05 lots | 0.10 lots | Low |
| BTCUSD | Medium | 0.01 lots | 0.02 lots | Low |

## Risk Budget by Tier

| Budget | $5K | $10K | $25K |
|---|---|---|---|
| Daily loss | $250 | $500 | $1,250 |
| Max DD (10%) | $510 | $1,020 | $2,550 |
| Equity floor | $4,000 | $8,000 | $20,000 |
| Loss-at-SL | ~$450 | ~$900 | ~$2,250 |

## Rollback Criteria

If any of the following occur, revert to previous tier:

- Unexplained reconciliation mismatch
- Catastrophic protection failure
- Daily-loss limit breached
- Drawdown exceeds tier limit
- Foreign position detected (unexplained)
- Fingerprint mismatch
- Safety defect discovered

## Governance

### Who Can Approve Promotion

- Evidence gate must pass (automated)
- Manual review required
- Documentation must be updated
- T=0 snapshot must be regenerated

### What Cannot Be Changed During Promotion

- R4 strategy parameters
- Signal computation
- Regime gate logic
- Risk gate logic
- Safety architecture

### What CAN Be Changed

- Position limits (within tier bounds)
- Concurrent position count (within tier bounds)
- Universe (within tier constraints)
- Monitoring frequency

## Evidence Requirements

### For $10K Promotion

| Evidence | Minimum | Ideal |
|---|---|---|
| Live trading days | 30 | 60+ |
| Trades executed | 50 | 100+ |
| Holding periods | 20+ days avg | 30+ days avg |
| Max drawdown | < 5% | < 3% |
| Daily loss events | 0 breaches | 0 breaches |
| Reconciliation mismatches | 0 | 0 |
| SL triggers | < 5% of trades | < 2% of trades |
| Execution fill rate | > 95% | > 99% |

### For $25K Promotion

| Evidence | Minimum | Ideal |
|---|---|---|
| Live trading days | 60 | 120+ |
| Trades executed | 100 | 200+ |
| Max drawdown | < 5% | < 3% |
| Correlation stability | Confirmed | Stable 60+ days |
| Liquidity impact | Minimal | Confirmed |
| Broker capacity | Verified | Multi-broker tested |

## Important Principle

> **Capital scaling is earned through evidence, not enabled by changing a configuration value.**

The $5K tier exists to prove the system works under real conditions. Promotion to $10K requires evidence that the system is ready — not just that the configuration allows it.
