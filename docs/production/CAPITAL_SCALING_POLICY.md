# EigenCapital — Capital Scaling Policy

## Principle

> Capital scaling must be evidence-driven, not confidence-driven.

Every capital increase requires demonstrated stability at the previous tier.

---

## Capital Tiers and Gates

### Tier 0: Research ($0)
**Status:** COMPLETE

### Tier 1: Paper ($0 simulated)
**Status:** COMPLETE

### Tier 2: Micro-Live ($5K)
**Status:** IN PROGRESS — supervised qualification

**Entry requirements (all met):**
- [x] Frozen R4 identity
- [x] RiskPolicy as authority
- [x] 7 broker-authoritative risk gates
- [x] Fingerprint verification at runtime
- [x] Daily loss tracking with persistence
- [x] Process supervision (PID file)
- [x] Disconnect recovery state machine
- [x] Configuration single source of truth
- [x] Platform-agnostic provider abstraction
- [x] 2063 tests passing

**Current limits:**
| Limit | Value | Rationale |
|-------|-------|-----------|
| Max equity | $5,100 | $5K + 2% buffer |
| Max position | $1,500 | 30% of equity |
| Max order | $1,500 | Single order can fill any position |
| Max concurrent | 8 | Margin constraint at $5K |
| Max daily loss | $250 | 5% of equity |
| Max drawdown | 10% ($500) | Risk limit |
| Campaign duration | 30 days | Qualification window |

### Tier 3: Controlled Production ($10K)
**Entry requirements (from Tier 2):**
- [ ] 30 days stable operation at $5K
- [ ] Zero critical incidents (position breach, risk bypass, fingerprint drift)
- [ ] Zero reconciliation failures
- [ ] Zero duplicate orders
- [ ] Zero unauthorized orders
- [ ] All risk controls verified by test
- [ ] Broker execution stable (no requotes, no rejects)
- [ ] Disconnect recovery verified in production
- [ ] Process crash recovery verified

**Proposed limits:**
| Limit | Value | Scaling |
|-------|-------|---------|
| Max equity | $10,200 | Linear (2×) |
| Max position | $2,000 | Linear (but capped by liquidity) |
| Max order | $2,000 | Linear |
| Max concurrent | 12 | Partially linear |
| Max daily loss | $500 | Linear (5% of equity) |
| Max drawdown | $1,000 | Linear (10%) |

### Tier 4: Scaled Production ($25K)
**Entry requirements (from Tier 3):**
- [ ] 60 days stable operation at $10K
- [ ] Same criteria as Tier 3
- [ ] Capacity analysis completed
- [ ] Liquidity impact assessment

**Proposed limits:**
| Limit | Value | Scaling |
|-------|-------|---------|
| Max equity | $25,500 | Linear |
| Max position | $3,750 | Liquidity-constrained |
| Max order | $3,750 | Liquidity-constrained |
| Max concurrent | 15 | Partially linear |
| Max daily loss | $1,250 | Linear (5%) |
| Max drawdown | $2,500 | Linear (10%) |

### Tier 5: Material Capital ($50K)
**Entry requirements (from Tier 4):**
- [ ] 90 days stable operation at $25K
- [ ] Same criteria as Tier 3
- [ ] Market impact analysis completed
- [ ] Execution quality metrics established

**Proposed limits:**
| Limit | Value | Scaling |
|-------|-------|---------|
| Max equity | $51,000 | Linear |
| Max position | $5,000 | Liquidity-constrained |
| Max order | $5,000 | Liquidity-constrained |
| Max concurrent | 15 | Strategy-constrained |
| Max daily loss | $2,500 | Linear (5%) |
| Max drawdown | $5,000 | Linear (10%) |

### Tier 6: Large Capital ($100K+)
**Entry requirements (from Tier 5):**
- [ ] 180 days stable operation at $50K
- [ ] Full capacity analysis
- [ ] Multi-broker evaluation
- [ ] Institutional-grade operational procedures

---

## Scaling Classification

| Parameter | Scaling Type | Notes |
|-----------|-------------|-------|
| Max equity | Linear | Directly proportional to capital |
| Max position | Liquidity-constrained | Capped by market depth |
| Max order | Liquidity-constrained | Same as position |
| Max concurrent | Strategy-constrained | R4 signal limits active positions |
| Max daily loss | Linear (% of equity) | 5% of equity |
| Max drawdown | Linear (% of equity) | 10% of equity |
| Order rate | Operationally constrained | MT5 throughput limits |
| Slippage budget | Non-linear | Worsens with size |
| Spread cost | Non-linear | Worsens with size |

## Key Insight

R4 strategy is **capacity-constrained** at approximately:
- 16 eligible instruments
- 8 concurrent positions maximum
- $1,500 per position (current lot constraints)
- Weekly rebalance frequency

**Maximum defensible capital for R4 under current constraints: ~$50K-$100K**

Beyond this, the strategy needs:
- Additional instruments
- Larger lot sizes (higher account tier)
- Potentially different brokers
- Or accept lower capacity utilization

## Escalation Criteria

Each tier upgrade requires a **Capital Scaling Review** documenting:
1. Days of stable operation at current tier
2. Incident count (critical, warning, info)
3. Test suite status
4. Risk control verification
5. Execution quality metrics
6. Disconnect recovery verification
7. Operator sign-off
