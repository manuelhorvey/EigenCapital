# EigenCapital — Capital Scaling

**Last Updated:** 2026-08-27  
**Current Tier:** T1 — $5K Controlled Qualification (Live)

---

## Current Tier

| Parameter | Value |
|---|---|
| Campaign tier | $5,000 |
| Authorized capital | $5,100 |
| Max position | $1,500 |
| Max concurrent | 19 |
| Max order | $1,500 |
| Daily loss limit | $250 |
| Universe | 24 symbols |
| Status | 🟢 Live, collecting evidence |

---

## Tier Definitions

| Tier | Max Equity | Max Position | Max Order | Max Positions | Daily Loss | Stable Days |
|------|-----------|-------------|-----------|--------------|-----------|-------------|
| T1 QUALIFICATION | $5,100 | $1,500 | $1,500 | 19 | $250 | 0 |
| T2 PROVISIONAL | $10,100 | $2,500 | $2,500 | 10 | $500 | 14 |
| T3 CONTROLLED | $25,100 | $5,000 | $5,000 | 12 | $1,000 | 30 |
| T4 SCALED | $50,100 | $8,000 | $8,000 | 15 | $2,000 | 60 |
| T5 INSTITUTIONAL | $100,100 | $15,000 | $15,000 | 20 | $3,000 | 90 |

All tiers are **immutable frozen dataclasses**.

---

## Promotion Gates

### T1 → T2 Requirements

| Gate | Requirement | Evidence |
|------|-------------|----------|
| Minimum days | 14 days live | Campaign timestamp |
| Completed trades | 10+ closed trades | Trade log |
| Win rate | > 50% | P&L analysis |
| Max drawdown | < 10% | Equity curve |
| Risk gates | 100% pass rate | Audit log |
| Fingerprint | Verified at T=0 | Fingerprint log |

### T2 → T3 Requirements

| Gate | Requirement | Evidence |
|------|-------------|----------|
| Minimum days | 30 days live | Campaign timestamp |
| Completed trades | 20+ closed trades | Trade log |
| Sharpe ratio | > 0.5 | Risk metrics |
| Max drawdown | < 15% | Equity curve |
| Independent episodes | 3+ | Rebalancing log |
| Max holding | 10+ days achieved | Holding metrics |

### T3 → T4 Requirements

| Gate | Requirement | Evidence |
|------|-------------|----------|
| Minimum days | 60 days live | Campaign timestamp |
| Completed trades | 30+ closed trades | Trade log |
| Sharpe ratio | > 1.0 | Risk metrics |
| Max drawdown | < 20% | Equity curve |
| Profit factor | > 1.5 | P&L analysis |
| Independent episodes | 5+ | Rebalancing log |

### T4 → T5 Requirements

| Gate | Requirement | Evidence |
|------|-------------|----------|
| Minimum days | 90 days live | Campaign timestamp |
| Completed trades | 50+ closed trades | Trade log |
| Sharpe ratio | > 1.5 | Risk metrics |
| Max drawdown | < 25% | Equity curve |
| Profit factor | > 2.0 | P&L analysis |
| Independent episodes | 10+ | Rebalancing log |

---

## Capacity Analysis

### $5K Tier Capacity

| Metric | Value | Source |
|--------|-------|--------|
| Account equity | ~$7,000 | MT5 live |
| Max position notional | $1,500 | Config |
| Max concurrent | 19 | Config |
| Total capacity | $28,500 | 19 × $1,500 |
| Leverage utilized | ~4x | $28,500 / $7,000 |

### Scalability Notes

- System tested at $5K tier only
- Higher tiers require live validation at each level
- Position sizing scales linearly with equity
- Risk gates enforce per-tier limits automatically

---

## Semantics

- **Equity**: Account balance + floating P&L
- **Max position**: Maximum notional value per position
- **Max concurrent**: Maximum number of open positions
- **Daily loss**: Maximum loss from start-of-day equity
- **Stable days**: Days of positive returns required for promotion
- **Independent episodes**: Distinct rebalancing events (not correlated)

---

## Risk Controls

| Control | Implementation | Test Coverage |
|---------|---------------|---------------|
| Position size limit | `RiskEnforcer` gate | 15 tests |
| Concurrent limit | `PositionAttribution` | 8 tests |
| Daily loss limit | `DailyLossTracker` | 12 tests |
| Drawdown protection | `RiskEnforcer` gate | 10 tests |
| Tier promotion | `CapitalTierGovernance` | 26 tests |

---

*This document consolidates: CAPITAL_SCALING.md, CAPITAL_SCALING_MODEL.md, CAPITAL_SCALING_POLICY.md, CAPITAL_CAPACITY_REPORT.md, CAPITAL_SEMANTICS.md, CAPITAL_TIER_GOVERNANCE.md, CAPITAL_TIER_PROMOTION_POLICY.md*
