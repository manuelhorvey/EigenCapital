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
| 7 | Broker timeout | ✅ Exception handling | ✅ Log error | ⚠️ Continues | ❌ No change | ⚠️ Next cycle | ❌ No | ✅ |
| 8 | Order timeout | ❌ Not implemented | N/A | ❌ May hang | ⚠️ Unknown | N/A | ❌ No | ❌ No |
| 9 | Duplicate order response | ❌ Not handled | N/A | ⚠️ May double-fill | ⚠️ Incorrect | N/A | ❌ No | ❌ No |
| 10 | Partial fill | ❌ Not handled | N/A | ⚠️ Incomplete | ⚠️ Incorrect | N/A | ❌ No | ❌ No |
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
| 21 | Spread explosion | ❌ Not checked in loop | N/A | ⚠️ May trade bad | ⚠️ Bad fill | N/A | ❌ No | ❌ No |
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
2. **No order timeout** (#8): `mt5.order_send()` can hang indefinitely
3. **No partial fill handling** (#10): Incomplete fills leave incorrect position state
4. **No position reconciliation** (#13-14): Position/equity mismatch undetected
5. **No process crash recovery** (#3-4): Dead system requires manual restart

## Recommended Next Steps

1. Wire `DisconnectRecovery` into live loop → addresses #1-5
2. Add order timeout to `order_send` → addresses #8
3. Wire `PartialFillManager` into live loop → addresses #10
4. Add post-trade reconciliation → addresses #13-14
5. Add auto-restart wrapper → addresses #3-4
