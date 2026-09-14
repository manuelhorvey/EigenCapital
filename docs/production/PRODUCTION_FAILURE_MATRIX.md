# EigenCapital — Production Failure Matrix

## Status Legend
- ✅ Implemented and tested
- ⚠️ Implemented but not fully tested
- ❌ Not implemented
- 🔧 Partially implemented

---

## Failure Scenario Matrix

| # | Scenario | Detection | Immediate Action | Trading | Position | Recovery | Notification | Audit |
|---|----------|-----------|-----------------|---------|----------|----------|-------------|-------|
| 1 | MT5 disconnect | ✅ Exception handling | ✅ Log error | ⚠️ May continue | ❌ No flatten | ⚠️ Next cycle retry | ❌ No alert | ✅ Logged |
| 2 | MT5 terminal crash | ✅ Same as disconnect | ✅ Same | ⚠️ May continue | ❌ No flatten | ❌ Manual restart | ❌ No | ✅ |
| 3 | Python process crash | ❌ Dead | N/A | ❌ Dead | ❌ No change | ❌ Manual restart | ❌ No | ⚠️ Last JSONL |
| 4 | Machine reboot | ❌ Dead | N/A | ❌ Dead | ❌ No change | ❌ Manual restart | ❌ No | ⚠️ |
| 5 | Network outage | ✅ Same as disconnect | ✅ Same | ⚠️ Same | ❌ No change | ⚠️ Same | ❌ No | ✅ |
| 6 | Stale market data | ❌ Not detected | N/A | ⚠️ May trade stale | ⚠️ Bad fills | N/A | ❌ No | ❌ No |
| 7 | Broker timeout | ✅ Exception handling | ✅ Log error | ⚠️ Cycle may stop | ⚠️ Broker outcome checked next cycle | ⚠️ Next cycle | ❌ No | ✅ |
| 8 | Order timeout | ✅ 30s bound | ✅ Abort remaining cycle orders | ✅ No automatic retry | ⚠️ Outcome reconciled next cycle | ⚠️ Reconnect next cycle | ❌ No | ✅ Ambiguous result logged |
| 9 | Duplicate order response | 🔧 Per-cycle idempotency | ✅ Suppress same-cycle retry | ⚠️ Cross-cycle broker reconciliation required | ⚠️ Broker authoritative | ⚠️ Next cycle | ❌ No | ✅ |
| 10 | Partial fill | ✅ Broker volume captured | 🔧 Remainder recorded | ⚠️ No automatic chase | ⚠️ Remainder requires reconciliation | ⚠️ Next cycle | ❌ No | ✅ Fill quantity logged |
| 11 | Rejected order | ✅ Retcode check | ✅ Log error | ✅ Continues | ❌ No change | ✅ Next cycle | ❌ No | ✅ |
| 12 | Rejected SL | N/A (SL not submitted) | N/A | N/A | ⚠️ Unprotected | N/A | ❌ No | N/A |
| 13 | Position mismatch | ❌ Not detected | N/A | ⚠️ Unknown | ⚠️ Incorrect | N/A | ❌ No | ❌ No |
| 14 | Equity mismatch | ❌ Not detected | N/A | ⚠️ Unknown | ⚠️ Incorrect | N/A | ❌ No | ❌ No |
| 15 | Fingerprint mismatch | ✅ FingerprintVerifier | ✅ BLOCKED | ✅ Halts | ❌ No change | ✅ Fix config | ✅ Audit entry | ✅ |
| 16 | Corrupted snapshot | ❌ Not detected | N/A | ⚠️ Unknown | ⚠️ Unknown | N/A | ❌ No | ❌ No |
| 17 | Corrupted audit log | ❌ Not detected | N/A | ⚠️ Continues | ❌ No change | N/A | ❌ No | ❌ No |
| 18 | Clock drift | ❌ Not detected | N/A | ⚠️ Affects daily loss | ⚠️ Incorrect P&L | N/A | ❌ No | ❌ No |
| 19 | Disk full | ✅ IO error | ⚠️ Exception caught | ⚠️ Audit fails | ❌ No change | N/A | ❌ No | ❌ No |
| 20 | Insufficient margin | ✅ MT5 rejects | ✅ Log error | ✅ Continues | ❌ No change | ✅ Next cycle | ❌ No | ✅ |
| 21 | Spread explosion | ✅ Entry spread guard | ✅ Skip new entry | ✅ Existing positions unaffected | ✅ Close remains allowed | ✅ Next cycle | ❌ No | ✅ Logged |
| 22 | Unexpected manual trade | ❌ Not detected | N/A | ⚠️ May conflict | ⚠️ Wrong attribution | N/A | ❌ No | ❌ No |
| 23 | Duplicate process | ✅ PID file | ✅ Second rejected | ✅ Single instance | ❌ No change | N/A | ❌ No | ✅ |
| 24 | Config drift | ✅ FingerprintVerifier | ✅ BLOCKED | ✅ Halts | ❌ No change | ✅ Fix config | ✅ Audit entry | ✅ |
| 25 | Symbol spec change | ❌ Not detected | N/A | ⚠️ Wrong sizing | ⚠️ Incorrect | N/A | ❌ No | ❌ No |

## Coverage Summary

| Category | Implemented | Not Implemented | Coverage |
|----------|:-----------:|:---------------:|:--------:|
| Detection | 12/25 | 13/25 | 48% |
| Immediate Action | 10/25 | 15/25 | 40% |
| Trading Permission | 8/25 | 17/25 | 32% |
| Position Handling | 1/25 | 24/25 | 4% |
| Recovery | 5/25 | 20/25 | 20% |
| Notification | 2/25 | 23/25 | 8% |
| Audit Record | 10/25 | 15/25 | 40% |

## Critical Gaps

1. **No disconnect → flatten** (#1-5): Positions remain unprotected during MT5 disconnect
2. **Cross-cycle duplicate protection** (#9): Per-cycle idempotency cannot identify an order accepted by the broker after a timeout
3. **Partial-fill completion policy** (#10): Fill quantities are recorded, but automatic remainder chase/cancel requires provider order identifiers
4. **No process crash recovery** (#3-4): Dead system requires manual restart

## Recommended Next Steps

1. Wire `DisconnectRecovery` into live loop → addresses #1-5
2. Add broker-side idempotency keys and cross-cycle intent reconciliation → addresses #9
3. Expose provider order identifiers/cancel API for partial remainder management → addresses #10
4. Add auto-restart wrapper → addresses #3-4
