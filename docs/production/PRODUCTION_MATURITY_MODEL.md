# EigenCapital — Production Maturity Model

## Levels

| Level | Name | Capital | Requirements | Status |
|-------|------|---------|-------------|--------|
| 0 | Research | $0 | Backtest/simulation only | ✅ |
| 1 | Paper | $0 | Paper execution, no real orders | ✅ |
| 2 | Shadow | $0 | Real data, simulated execution | ✅ |
| 3 | Micro-live | <$1K | Minimal real execution | ✅ |
| 4 | $5K qualification | $5K | Proven risk/recovery/fingerprint | ✅ CURRENT |
| 5 | $10K | $10K | 14 days stable, zero incidents | ⬜ Requires evidence |
| 6 | $25K | $25K | 30 days stable, capacity review | ⬜ Requires evidence |
| 7 | $50K | $50K | 60 days stable, liquidity review | ⬜ Requires evidence |
| 8 | $100K | $100K | 90 days stable, execution review | ⬜ NOT CERTIFIED |
| 9 | Institutional | $100K+ | Full production hardening | ❌ Not applicable |

## Level 4 → 5 Promotion Requirements

- [ ] 14 days continuous supervised operation
- [ ] Zero critical incidents
- [ ] Zero duplicate orders
- [ ] Zero unauthorized orders
- [ ] All reconciliation checks passing
- [ ] Process supervision verified
- [ ] State persistence verified
- [ ] Emergency flatten verified
- [ ] Fingerprint verification verified
- [ ] Broker execution stable
- [ ] Historical drawdown within T2 limit (15%)
- [ ] All tests passing (excluding 5 pre-existing)

## Level 5 → 6 Promotion Requirements

All Level 4→5 requirements, plus:
- [ ] 30 days continuous operation
- [ ] Capacity review for $25K
- [ ] Instrument liquidity verification
- [ ] Execution quality metrics acceptable

## Level 6 → 7 Promotion Requirements

All Level 5→6 requirements, plus:
- [ ] 60 days continuous operation
- [ ] Order slicing capability (if needed)
- [ ] Spread-aware execution
- [ ] Liquidity stress testing

## Level 7 → 8 Promotion Requirements

**NOT RECOMMENDED** under current R4 instrument universe.
Requires: larger universe, institutional execution, full production hardening.

## Promotion Rules

1. No level may be skipped
2. Promotion requires evidence, not confidence
3. Promotion is an engineering decision, not a profitability decision
4. Any incident resets the observation clock
5. Rollback is automatic on safety violation
