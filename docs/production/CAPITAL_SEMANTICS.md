# Capital Semantics — Explicit Definitions

This document defines the five distinct capital concepts used in EigenCapital's
qualification framework. Confusing these creates governance contradictions.

## Definitions

### 1. Account Equity
```
Current MT5 account equity: $6,981
```
- **Source:** MT5 `account_info().equity`
- **Changes:** Every tick (unrealized P&L)
- **Meaning:** What the broker shows right now
- **NOT used for:** Position sizing decisions

### 2. Authorized Trading Capital
```
MAX_EQUITY = $5,100
```
- **Source:** `configs/production/config.toml` → `[capital].max_equity`
- **Changes:** Only on explicit governance decision
- **Meaning:** The maximum equity the strategy is allowed to trade against
- **Used for:** `capped_equity = min(equity, MAX_EQUITY)` in all sizing
- **Enforced:** In `r4_rebalance_loop.py` line 297, `r4_live_orders.py` line 254

### 3. Maximum Campaign Capital
```
Qualification tier: $5,000
```
- **Source:** Governance decision (this document)
- **Changes:** Only on tier promotion ($5K → $10K → $25K → etc.)
- **Meaning:** The capital tier at which the strategy is being qualified
- **Relationship:** Campaign tier ≤ MAX_EQUITY (buffer for P&L drift)

### 4. Position Notional Limit
```
MAX_POSITION_USD = $5,000
```
- **Source:** `configs/production/config.toml` → `[capital].max_position_size`
- **Changes:** Only on governance decision
- **Meaning:** Maximum notional per single position
- **NOT the same as:** Risk per position (risk = SL distance × notional)
- **Enforced:** In `generate_orders()` — skips positions where min lot > limit

### 5. Risk Capital
```
Effective capital = min(equity, MAX_EQUITY) = $5,100
Risk budget = max_daily_loss = $250
DD limit = 10% = $1,000
Equity floor = $4,000
```
- **Source:** Risk policy configuration
- **Changes:** Only on governance decision
- **Meaning:** The actual risk budget available for trading
- **Used for:** Daily loss tracking, drawdown monitoring, equity floor enforcement

## Current State (2026-08-26)

| Concept | Value | Source |
|---|---|---|
| Account equity | $6,981 | MT5 live |
| Authorized trading capital | $5,100 | Config |
| Campaign tier | $5,000 | Governance |
| Position notional limit | $5,000 | Config |
| Risk capital (daily) | $250 | Config |
| Risk capital (DD) | $1,000 | Config |
| Equity floor | $4,000 | Config |

## The Gap

```
Account equity ($6,981) - Authorized capital ($5,100) = $1,881 buffer
```

This buffer is **governance protection**, not deployable capital.
The strategy must never trade as if $6,981 is available.

## Scaling Rule

When promoting to $10K:
1. Campaign tier: $5,000 → $10,000
2. MAX_EQUITY: $5,100 → $10,200 (tier + 2% buffer)
3. MAX_POSITION_USD: $5,000 → $10,000
4. Re-run qualification evidence at new tier
5. Never skip tiers ($5K → $25K is not allowed)
