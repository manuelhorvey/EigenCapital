# Risk Architecture

This document describes the actual risk architecture of EigenCapital's live trading system.

Last updated: 2026-08-26

## Overview

Risk management operates at three levels:

1. **Strategy risk** — R4's own signal clipping and regime gating
2. **Execution safety** — Pre-trade gates that block unauthorized orders
3. **Catastrophic protection** — Disaster boundary that limits maximum loss

These are independent layers. Failure of one does not compromise the others.

## Layer 1: Strategy Risk (R4 Signal)

R4's signal is inherently conservative:

| Control | Value | Purpose |
|---|---|---|
| Weight clip | ±20% (BTC ±10%) | Limits single-position concentration |
| Volatility scaling | 60-day vol, 50% target | Reduces sizing in volatile markets |
| Regime gate | Vol < median | No trade when market is stressed |
| Cross-sectional rank | Percentile-based | Relative strength, not absolute |

**What this means:** R4 never assigns a large weight to any single instrument, and it stops trading entirely when volatility is elevated.

## Layer 2: Execution Safety (Pre-trade Gates)

Seven gates enforce limits before any order reaches the broker:

| # | Gate | Limit | Enforcement | Fail Mode |
|---|---|---|---|---|
| 1 | Broker connectivity | equity > 0 | `check_all()` | CRITICAL — short-circuit |
| 2 | Position count | ≤ 19 | `check_all()` | BLOCK — no new entries |
| 3 | Account drawdown | ≤ 10% from peak | `check_all()` | BLOCK |
| 4 | Daily loss | ≤ $250 | `check_all()` | BLOCK |
| 5 | Equity floor | ≥ $4,000 | `check_all()` | CRITICAL |
| 6 | Position protection | SL on all R4 positions | `check_all()` | CRITICAL |
| 7 | Fingerprint | Config matches T=0 | `check_all()` | BLOCK |

### Gate Behavior

- **Short-circuit:** Earlier gates are more critical; failure stops evaluation
- **Fail-closed:** Missing data defaults to safest outcome
- **Broker-authoritative:** All checks use actual MT5 state, not internal state
- **Auditable:** Every gate result recorded to JSONL

### Additional Loop-level Gates

The rebalance loop adds:

| Gate | Purpose |
|---|---|
| Watchdog state | NORMAL required for trading |
| T=0 validation | Campaign boundary must match config |
| Position attribution | Foreign positions block new entries |
| Quarantine logic | Self-rotation allowed, new entries blocked |

## Layer 3: Catastrophic Protection

Disaster stop-loss boundary for every R4 position:

| Parameter | Value | Source |
|---|---|---|
| Stop distance | max(2× ATR14, 1% floor) | `catastrophic_protection.py` |
| ATR period | 14 days | Config |
| Minimum distance | 1% | Floor for low-vol instruments |
| Maximum distance | 2× ATR | Cap for high-vol instruments |

### Current Portfolio Risk

| Metric | Value |
|---|---|
| Positions | 19 |
| Total loss-at-SL (nominal) | ~$450 (6.4% of equity) |
| Equity floor | $4,000 |
| Buffer to floor | ~$3,000 (43%) |
| Worst single loss-at-SL | ~$177 (XAUUSD) |

### Stress Test Results

| Scenario | Loss | Equity After | vs Floor |
|---|---|---|---|
| All stops nominal | $450 | $6,531 | ✅ SAFE |
| All stops + 50% gap | $675 | $6,307 | ✅ SAFE |
| XAUUSD gap 3x | $804 | $6,177 | ✅ SAFE |
| AUD cluster 2x | $520 | $6,461 | ✅ SAFE |

**Important:** Stop-loss stress tests are not equivalent to guaranteed liquidation prices. Gaps, slippage, and rejection can produce larger losses.

## Layer 4: Operational Safety

| Control | Purpose | Implementation |
|---|---|---|
| Auto-reconnect | Stale MT5 detection | `r4_rebalance_loop.py` |
| Watchdog | Blind-window escalation | `watchdog.py` |
| Process supervision | Duplicate instance prevention | `supervisor.py` |
| Durable audit | Crash-resistant JSONL trail | `durable_audit.py` |
| Emergency flatten | Close all positions | `--flatten` flag |

### Watchdog State Machine

```
NORMAL → DEGRADED → BLIND → CONTAIN → RECONCILING → RESUMED
                                    → HALTED (reconciliation failed)
```

| State | Meaning | Trading |
|---|---|---|
| NORMAL | All probes healthy | Authorized |
| DEGRADED | Process/trail/equity unhealthy | Blocked |
| BLIND | Evidence untrustworthy | Blocked |
| CONTAIN | Prolonged abnormal condition | Flatten on reconnect |
| HALTED | Reconciliation failed | Permanently blocked |

## Risk Budget Summary

| Budget | Limit | Current | Status |
|---|---|---|---|
| Daily loss | $250 | $0 | ✅ |
| Drawdown from peak | 10% ($698) | 0% | ✅ |
| Equity floor | $4,000 | $6,981 | ✅ |
| Max position | $5,000 | 0.01 lots | ✅ |
| Max concurrent | 19 | 19 | ✅ |
| Portfolio loss-at-SL | ~$450 | ~$450 | ✅ |

## Capital Semantics

| Concept | Value | Meaning |
|---|---|---|
| Account equity | ~$6,980 | What broker shows |
| Authorized capital | $5,100 | What strategy trades against |
| Campaign tier | $5,000 | Qualification level |
| Position limit | $5,000 | Max notional per position |
| Risk budget (daily) | $250 | Daily loss limit |
| Risk budget (DD) | $1,000 | Max drawdown |

**The gap between account equity and authorized capital is governance protection, not deployable capital.**

## What Is NOT Risk Management

- **Take-profit orders:** R4 deliberately does not use TP. The research evidence shows TP truncates momentum continuation without improving risk-adjusted returns.
- **Trailing stops:** Not used. R4's exit is signal-based, not price-based.
- **Hedging:** The system uses ticket-scoped closes, not opposing positions.
- **Position scaling:** R4 does not pyramid into winners.

## Monitoring

| Metric | Frequency | Source |
|---|---|---|
| Position evidence | Hourly | `r4_qualification_monitor.py` |
| Loop decisions | Per cycle | `reports/r4_loop/decisions.jsonl` |
| Risk gate results | Per cycle | `reports/r4_loop/decisions.jsonl` |
| Watchdog state | Per probe | `reports/r4_loop/loop_health.json` |
| Daily loss | Per cycle | `DailyLossTracker` |
| Drawdown | Per cycle | `RiskEnforcer` |
