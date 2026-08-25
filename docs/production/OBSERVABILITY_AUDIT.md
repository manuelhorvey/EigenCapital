# EigenCapital — Observability Audit

## Operator Questions

| Question | Answerable | Source |
|----------|-----------|--------|
| Is the system running? | ✅ | ProcessSupervisor.get_health_status() |
| Is it connected? | ✅ | TradingProvider.is_connected() |
| Is trading authorized? | ✅ | check_all() returns (passed, results) |
| Why is it not trading? | ⚠️ Partially | Gate results show which gate blocked |
| What is the current regime? | ❌ Not directly exposed | Requires reading regime logic |
| What positions exist? | ✅ | positions_get() from broker |
| What orders exist? | ⚠️ | Order history from broker |
| Today's P&L? | ⚠️ | equity - daily_baseline.equity |
| Drawdown? | ✅ | peak_equity tracking |
| Risk gates active? | ✅ | RiskEnforcer.get_audit_log() |
| Last successful cycle? | ⚠️ | Logged in rebalance loop |
| Last reconciliation? | ⚠️ | Logged in rebalance loop |
| Process restarted? | ✅ | ProcessSupervisor state timestamps |
| Configuration active? | ⚠️ | FingerprintVerifier state |
| Why was last order rejected? | ⚠️ | Gate results with reason |
| Current fingerprint? | ✅ | FingerprintVerifier.log |

## Status

| Dimension | Coverage |
|-----------|---------|
| Health status | ✅ Complete |
| Risk gate audit | ✅ Complete |
| Fingerprint verification | ✅ Complete |
| Daily loss tracking | ✅ Complete |
| Process supervision | ✅ Complete |
| Disconnect recovery | ✅ Complete |
| Order-level audit | ⚠️ Partial |
| P&L calculation | ⚠️ Partial |
| Regime visibility | ❌ Missing |
| Alert delivery | ✅ AlertDispatcher exists |

## Gap: No Single Status View

The system has all the data but no unified operator status endpoint.
A production operator would need to:
1. Check process health via ProcessSupervisor
2. Check risk state via RiskEnforcer audit log
3. Check fingerprint via FingerprintVerifier log
4. Check daily loss via DailyLossTracker persistence
5. Check positions via broker query

**Recommendation:** Build a unified `get_system_status()` method that
aggregates all critical state into a single response.

## Gap: No Durable Audit Trail

Audit logs are in-memory and bounded. After process restart, the audit
trail is lost. Critical state transitions (health changes, risk blocks,
disconnect events) should be persisted to disk for post-incident analysis.

**Recommendation:** Persist critical audit events to a JSONL file with
hash-chain integrity.
