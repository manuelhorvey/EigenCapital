# EigenCapital — Capital Capacity Report

## Capacity Model

The production capacity limit is:

```
MIN(strategy capacity, execution capacity, broker capacity, infrastructure capacity, risk capacity)
```

## Per-Tier Analysis

| Capital | Position Cap | Max Orders | Margin | Liquidity | Status |
|---------|-------------|-----------|--------|-----------|--------|
| $5K | $1,500 | 1,500 | OK | OK | ✅ CERTIFIED |
| $10K | $2,500 | 2,500 | OK | OK | ⬜ Requires evidence |
| $25K | $5,000 | $5,000 | OK | ⚠️ Monitor | ⬜ Requires evidence |
| $50K | $8,000 | $8,000 | ⚠️ Monitor | ⚠️ Capacity limits | ⬜ Requires evidence |
| $100K | $15,000 | $15,000 | ⚠️ High | ❌ Likely capacity-constrained | ⬜ NOT CERTIFIED |

## Constraint Analysis

### Strategy Capacity (R4)
- Expected turnover: moderate
- Instrument universe: 11 instruments
- Signal frequency: intraday
- **Estimated practical capacity: ~$50K–$100K** (limited by instrument liquidity)

### Execution Capacity (MT5)
- Single-threaded order submission
- MT5 throughput: ~10 orders/second max
- Partial fill probability increases with order size
- **Estimated practical capacity: ~$100K** (broker throughput sufficient)

### Broker Capacity
- Minimum lot: varies by symbol (typically 0.01)
- Maximum lot: varies by symbol (typically 100)
- Volume step: 0.01
- Leverage: account-dependent
- **Estimated practical capacity: ~$100K** (account leverage dependent)

### Infrastructure Capacity
- Memory: stable over 50K cycles ✅
- File descriptors: stable ✅
- Latency: sub-millisecond risk checks ✅
- **Estimated practical capacity: unlimited** (no infrastructure bottleneck)

### Risk Capacity
- Position limits enforced ✅
- Drawdown limits enforced ✅
- Equity floor enforced ✅
- SL protection enforced ✅
- **Estimated practical capacity: unlimited** (risk scales linearly)

## Capacity Curve

```
Capital:    $5K   $10K   $25K   $50K   $100K  $250K  $500K  $1M
Strategy:    ✅    ✅     ✅     ✅     ⚠️     ❌     ❌     ❌
Execution:   ✅    ✅     ✅     ✅     ✅     ⚠️     ⚠️     ⚠️
Broker:      ✅    ✅     ✅     ✅     ✅     ⚠️     ⚠️     ⚠️
Infra:       ✅    ✅     ✅     ✅     ✅     ✅     ✅     ✅
Risk:        ✅    ✅     ✅     ✅     ✅     ✅     ✅     ✅
OVERALL:     ✅    ⬜     ⬜     ⬜     ❌     ❌     ❌     ❌
```

Legend: ✅ Certified, ⬜ Requires evidence, ❌ Not certified

## Limiting Factor: Strategy Capacity

R4's practical capacity is constrained by instrument liquidity, not infrastructure.
The strategy trades 11 instruments with moderate expected turnover. At capital levels
above ~$50K, order sizes begin to represent a material fraction of expected daily
volume, increasing slippage and market impact.

**This is an economic limit, not a technical limit.** The system could technically
execute larger orders, but expected alpha would be degraded by execution costs.

## Recommendation

**$5K → $10K → $25K:** Evidence-based progression, each requiring proven stability.
**$25K → $50K:** Capacity review required — verify instrument liquidity.
**$50K+:** NOT RECOMMENDED under current instrument universe without:
- Larger instrument universe
- Order slicing capability
- Spread-aware execution
- Participation rate limits
