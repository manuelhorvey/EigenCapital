# EigenCapital — R4 Strategy Capacity Analysis

## Strategy Characteristics

| Property | Value |
|----------|-------|
| Signal | 12-1 month momentum |
| Rebalance | Weekly |
| Universe | 16 eligible instruments |
| Max concurrent | 8 positions |
| Position sizing | Equal-weight top-N by signal strength |
| Vol target | 10% annual |
| Asset classes | Forex (14), Crypto (1) |

## Instrument Liquidity Analysis

### Current Eligible Instruments (Exness MT5)

| Instrument | Avg Daily Volume | Min Lot | Min Lot Notional | Max Position at $1,500 |
|-----------|-----------------|---------|-----------------|----------------------|
| EURUSD | High | 0.01 | $1,167 | 1.28 lots |
| GBPUSD | High | 0.01 | $1,363 | 1.10 lots |
| AUDUSD | Medium | 0.01 | $716 | 2.09 lots |
| USDCHF | Medium | 0.01 | $803 | 1.87 lots |
| USDCAD | Medium | 0.01 | $1,384 | 1.08 lots |
| NZDUSD | Medium | 0.01 | $597 | 2.51 lots |
| AUDNZD | Low-Medium | 0.01 | $1,199 | 1.25 lots |
| AUDCHF | Low-Medium | 0.01 | $574 | 2.61 lots |
| AUDCAD | Low-Medium | 0.01 | $990 | 1.52 lots |
| NZDCHF | Low-Medium | 0.01 | $479 | 3.13 lots |
| NZDCAD | Low-Medium | 0.01 | $826 | 1.82 lots |
| GBPCHF | Low-Medium | 0.01 | $1,094 | 1.37 lots |
| EURCHF | Low-Medium | 0.01 | $937 | 1.60 lots |
| EURGBP | Low-Medium | 0.01 | $856 | 1.75 lots |
| BTCUSD | Medium | 0.01 | $792 | 1.89 lots |

## Capacity Constraints

### 1. Instrument Count (Hard Constraint)
- **16 eligible instruments** out of 31 total
- R4 selects top-8 by signal strength
- **Maximum positions:** 8 concurrent
- This is a **strategy constraint**, not a capital constraint

### 2. Minimum Lot Size (Hard Constraint)
- Minimum lot = 0.01 for all forex instruments
- At current prices, min lot costs $479-$1,384
- **Minimum capital to trade all 8 positions:** ~$4,000-$11,000
- At $5K, some instruments can only trade 1 min lot

### 3. Position Size Scaling

| Capital | Max Position | Max Order | Positions at Min Lot | Effective Utilization |
|---------|-------------|-----------|---------------------|---------------------|
| $5K | $1,500 | $1,500 | 8 × 0.01 = 8 | ~40% of equity used |
| $10K | $2,000 | $2,000 | 8 × 0.01 = 8 | ~20% of equity used |
| $25K | $3,750 | $3,750 | 8 × 0.02-0.03 | ~30% of equity used |
| $50K | $5,000 | $5,000 | 8 × 0.04-0.05 | ~40% of equity used |
| $100K | $5,000 | $5,000 | 8 × 0.08-0.10 | ~25% of equity used |

### 4. Market Impact
- At $5K-$50K: Negligible market impact on major forex pairs
- At $100K+: Potential spread widening on less liquid pairs
- **Estimated capacity limit for negligible impact:** ~$100K

### 5. Execution Capacity
- MT5 handles orders sequentially
- Weekly rebalance = ~8 orders per week maximum
- **No execution bottleneck at any capital tier**

## Maximum Defensible Capital

### Conservative Estimate: $50K
- All 8 positions can be appropriately sized
- Market impact negligible
- Risk limits proportional
- Broker constraints satisfied

### Aggressive Estimate: $100K
- Requires larger lot sizes (0.08-0.10)
- Some spread impact on less liquid pairs
- Still within broker margin requirements
- Risk limits need review

### Capacity Ceiling: ~$200K-$500K
- Limited by instrument count (16 eligible)
- Limited by position concentration
- Limited by market depth on exotic crosses
- Would need universe expansion or multi-broker

## Recommendation

For the current $5K qualification:
- **Safe to scale to $25K** after 60 days stable operation
- **Safe to scale to $50K** after 90 days stable operation
- **Requires capacity analysis before scaling beyond $50K**
- **Cannot scale beyond ~$100K without universe expansion**

The strategy is **capacity-constrained** at the instrument level, not the execution level.
