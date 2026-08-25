# EigenCapital — Capital Tier Governance

## Purpose

Prevents arbitrary capital changes. Each tier requires explicit approval, evidence gates, and audit trail.

## Tier Definitions

| Tier | Max Equity | Max Position | Max Order | Max Positions | Daily Loss | Stable Days |
|------|-----------|-------------|-----------|--------------|-----------|-------------|
| T1 QUALIFICATION | $5,100 | $1,500 | $1,500 | 8 | $250 | 0 |
| T2 PROVISIONAL | $10,100 | $2,500 | $2,500 | 10 | $500 | 14 |
| T3 CONTROLLED | $25,100 | $5,000 | $5,000 | 12 | $1,000 | 30 |
| T4 SCALED | $50,100 | $8,000 | $8,000 | 15 | $2,000 | 60 |
| T5 INSTITUTIONAL | $100,100 | $15,000 | $15,000 | 20 | $3,000 | 90 |

All tiers are **immutable frozen dataclasses**.

## Promotion Gates

Promotion requires ALL:
- Minimum N stable days (see tier)
- Zero critical incidents
- Zero duplicate orders
- Zero unauthorized orders
- Broker stable
- Historical drawdown within new tier limit
- No tier skipping

## Key Invariants

1. Tier immutability — cannot change after creation
2. No tier skipping — must promote sequentially
3. Evidence required — no promotion without evidence
4. Zero tolerance — critical incidents/duplicates/unauthorized = 0
5. Audit trail — every decision logged
6. Fail closed — unknown tier → BLOCKED
7. Fail closed — no active tier → equity check returns False

## Implementation

- **Source:** `src/eigencapital/production_qual/capital_tier_governance.py`
- **Tests:** `tests/unit/test_capital_tier_governance.py` (26 tests)
