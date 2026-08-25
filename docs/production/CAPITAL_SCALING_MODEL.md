# EigenCapital — Capital Scaling Model

## Methodology

All values below are **calculated from actual broker specifications** (Exness MT5Trial9), not theoretical.

### Contract Specifications Used
- Forex standard lot = 100,000 units
- Min lot = 0.01
- Contract sizes vary by symbol (100,000 for major forex, 1 for crypto)

---

## Scaling Matrix

| Capital | Max Position | Max Order | Max Positions | Margin (1:100) | Free Margin | Est. Utilization | Status |
|--------:|-------------:|----------:|--------------:|---------------:|------------:|-----------------:|--------|
| $5K | $1,500 | $1,500 | 8 | $50/pos | $4,600 | ~40% | ✅ Tested |
| $10K | $2,000 | $2,000 | 8 | $100/pos | $9,200 | ~20% | ✅ Safe (est) |
| $25K | $3,750 | $3,750 | 12 | $250/pos | $22,000 | ~25% | ✅ Safe (est) |
| $50K | $5,000 | $5,000 | 12 | $500/pos | $44,000 | ~25% | ⚠️ Liquidity check |
| $100K | $5,000 | $5,000 | 15 | $1,000/pos | $85,000 | ~20% | ⚠️ Capacity limit |
| $250K | $10,000 | $10,000 | 15 | $2,500/pos | $212,000 | ~20% | ❌ Needs slicing |
| $500K | $10,000 | $10,000 | 15 | $5,000/pos | $425,000 | ~15% | ❌ Needs slicing |
| $1M | $15,000 | $15,000 | 15 | $10,000/pos | $850,000 | ~15% | ❌ Multi-broker |
| $5M | $25,000 | $25,000 | 20 | $50,000/pos | $4M | ~10% | ❌ Institutional |
| $10M+ | $50,000 | $50,000 | 20 | $100,000/pos | $8M | ~10% | ❌ Institutional |

## Per-Instrument Capacity at Each Tier

### EURUSD (Most Liquid)
| Capital | Lot Size | Notional | % ADV | Slippage Est |
|--------:|---------:|---------:|------:|-------------:|
| $5K | 0.01 | $1,167 | <0.001% | Negligible |
| $10K | 0.02 | $2,334 | <0.001% | Negligible |
| $25K | 0.03 | $3,501 | <0.001% | Negligible |
| $50K | 0.05 | $5,835 | <0.001% | Negligible |
| $100K | 0.08 | $9,336 | <0.001% | Low |
| $250K | 0.15 | $17,505 | <0.002% | Low |
| $500K | 0.25 | $29,175 | <0.003% | Moderate |
| $1M | 0.50 | $58,350 | <0.006% | Moderate |

### AUDNZD (Least Liquid Eligible)
| Capital | Lot Size | Notional | % ADV | Slippage Est |
|--------:|---------:|---------:|------:|-------------:|
| $5K | 0.01 | $1,199 | ~0.01% | Low |
| $10K | 0.01 | $1,199 | ~0.01% | Low |
| $25K | 0.03 | $3,597 | ~0.03% | Low |
| $50K | 0.04 | $4,796 | ~0.04% | Moderate |
| $100K | 0.08 | $9,592 | ~0.08% | Moderate |
| $250K | 0.15 | $17,985 | ~0.15% | High |
| $500K | 0.20 | $23,980 | ~0.20% | High |

## Limiting Factors by Tier

### $5K-$25K: **Capital-Limited**
- Position sizes are small relative to market liquidity
- No execution concerns
- Risk limits are the binding constraint

### $25K-$100K: **Strategy-Limited**
- R4 selects top 8 of 16 instruments
- 8 concurrent positions is the strategy design
- Increasing positions doesn't help (signal doesn't support it)

### $100K-$500K: **Liquidity-Limited**
- Some instruments (AUDNZD, NZDCHF) become impacted
- Need to exclude less liquid pairs or reduce participation
- Order slicing may be needed for larger orders

### $500K+: **Architecture-Limited**
- Single-broker execution insufficient
- Need multi-broker or institutional execution
- VWAP/TWAP execution required
- Current architecture does not support this

## Economic Capacity Curve

```
Capital vs Expected Net Alpha (after costs):

$5K:    ~8-12% annual (full alpha capture)
$10K:   ~8-12% annual
$25K:   ~7-11% annual (slight spread impact)
$50K:   ~6-10% annual (spread + slippage)
$100K:  ~5-8% annual (market impact begins)
$250K:  ~3-6% annual (significant impact on exotics)
$500K:  ~2-4% annual (execution costs dominate)
$1M:    ~1-3% annual (capacity exhausted)
```

## Recommendation

| Tier | Capital | Confidence | Evidence Required |
|------|---------|------------|-------------------|
| Tier 2 | $5K | ✅ HIGH | Current qualification |
| Tier 3 | $10K | ✅ HIGH | 30 days at $5K stable |
| Tier 4 | $25K | ✅ MEDIUM | 60 days at $10K stable |
| Tier 5 | $50K | ⚠️ MEDIUM | 90 days at $25K + liquidity test |
| Tier 6 | $100K | ⚠️ LOW | Capacity analysis + execution quality |
| Tier 7+ | $250K+ | ❌ NOT CERTIFIED | Requires architecture changes |
