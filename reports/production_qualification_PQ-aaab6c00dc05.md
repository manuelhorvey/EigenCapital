# Production Qualification Report

**Campaign:** PQ-aaab6c00dc05
**Scale Level:** minimal
**Verdict:** qualified_with_restrictions
**Manifest:** aaab6c00dc05a09a

## Account State

| Metric | Value |
|---|---|
| Balance | $0.00 |
| Equity | $0.00 |
| Free Margin | $0.00 |
| Unrealized P&L | $0.00 |
| Leverage | 2000000000 |

## Scale Envelope (MINIMAL)

| Parameter | Value |
|---|---|
| Max Equity | $5,000 |
| Max Position | $500 |
| Max Order | $250 |
| Max DD | $1,000 (20%) |

## Position Classification

| Symbol | Origin | Side | Volume | P&L |
|---|---|---|---|---|

## Qualification Checks

- ✅ **no_manual_trades**: Manual trades: 0
- ❌ **r4_attribution**: R4 trades: 0, open: 0
- ✅ **reconciliation**: 100% broker/internal agreement
- ✅ **fingerprint_frozen**: Fingerprint unchanged
- ✅ **slippage_scaling**: Slippage deterioration: 0.00x
- ✅ **spread_scaling**: Spread deterioration: 1.00x
- ✅ **fill_rate**: Fill rate: 100.0%
- ✅ **margin_pressure**: Margin usage: 0.0%
- ✅ **risk_proportional**: Position risk ratio: 0.00

## Scaling Evaluation

- ✅ **slippage**: {"deterioration": 0.0, "threshold": 2.0}
- ✅ **spread**: {"deterioration": 1.0, "threshold": 2.0}
- ✅ **fill_rate**: {"rate": 1.0, "threshold": 0.9}
- ✅ **margin**: {"usage": 0.0, "threshold": 0.5}
- ✅ **risk_proportional**: {"ratio": 0.0}

## P&L Attribution

- R4 P&L: $0.00
- Pre-existing P&L: $0.00
- Manual P&L: $0.00
- Total P&L: $0.00

## Summary

- Passed: 8/9
- Failed: 1/9
- Report Hash: 63a76aacc33ebc8c

**QUALIFIED WITH RESTRICTIONS** — Safe, but specific constraints remain.