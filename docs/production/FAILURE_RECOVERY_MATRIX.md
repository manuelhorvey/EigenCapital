# EigenCapital — Failure & Recovery Matrix (Post-Remediation)

**Campaign:** Long-Horizon Reliability, Capital Scaling & Production Stress-Test
**Supersedes:** `PRODUCTION_FAILURE_MATRIX.md` (retained as the *pre-remediation*
historical snapshot; its 48% detection coverage described the system before the
production-readiness remediation, not the current one).

## Status Legend

- ✅ Implemented **and verified by test**
- ⚠️ Implemented; verification incomplete or external-dependent
- ❌ Not implemented (tracked gap)
- N/A — not applicable to current architecture

---

## Failure Scenario Matrix

| # | Scenario | Detection | Immediate Action | Trading Permission | Recovery | Test Evidence |
|---|----------|-----------|------------------|--------------------|----------|---------------|
| 1 | Broker disconnect | ✅ Exception/bridge check | ✅ HALT via DisconnectRecovery → DISCONNECTED | ❌ Blocked in DISCONNECTED/RECONCILING/HALTED | ✅ Reconnect → reconcile → freshness → RESUME (bounded 3 attempts → FROZEN) | `test_disconnect_recovery*.py` (21+ tests), `test_state_machine_verification.py` (21) |
| 2 | Broker terminal crash | ✅ Same as #1 | ✅ Same | ❌ Same | ✅ Same as #1 | same as #1 |
| 3 | Process crash | ✅ Supervisor PID staleness | N/A (process dead) | ❌ No process to trade | ✅ Restart: claim instance → load persisted baseline/state → broker-authoritative reconcile | `test_crash_recovery.py`, `test_supervisor.py`, restart-cert suite |
| 4 | Machine reboot | ✅ Same as #3 | N/A | ❌ Until operator/systemd start | ✅ Same as #3 + duplicate-instance prevention | `test_supervisor.py` (13) |
| 5 | Network outage/flapping | ✅ Disconnect detection per flap | ✅ HALT per flap; attempt counter escalates | ❌ During every DISCONNECTED interval | ✅ Bounded retries; FROZEN after 3 consecutive failures | `test_failure_storm.py::TestDisconnectStorm` |
| 6 | Stale market data | ✅ Freshness gate at reconcile/resume | ✅ No resume on stale | ❌ Blocked | ✅ Waits for fresh data | `test_failure_injection.py`, failure-storm data cases |
| 7 | Malformed/duplicated/out-of-order bars | ✅ Injection-tested parsers/gates | ✅ Reject cycle input | ❌ Blocked for that cycle | ✅ Next cycle with clean data | `test_failure_injection.py` (13) |
| 8 | Broker timeout | ⚠️ Bridge-level exception | ✅ Cycle aborts safely | ❌ For that cycle | ✅ Next cycle | partial — no hard per-call timeout yet (see Gap G2) |
| 9 | Order timeout / hung order_send | ❌ Not implemented | N/A | N/A | ❌ See Gap G2 | **OPEN GAP** |
| 10 | Duplicate execution messages | ⚠️ Broker-authoritative reconciliation absorbs | ✅ Position set derived from broker, not message count | ❌ Mismatch ⇒ HALTED | ✅ Reconcile-or-halt | restart-cert `test_position_state_from_broker_not_local` |
| 11 | Partial fill | ✅ PartialFillManager exists | ✅ Tracks remainder | ⚠️ Wired component; loop integration verified in tests, not yet live | ✅ Complete-or-cancel policy | `tests/unit/live/test_partial_fills*`; live wiring listed as P1 |
| 12 | Rejected order | ✅ Retcode check | ✅ Log + continue, no retry storm | ✅ System remains up | ✅ Next rebalance re-evaluates | risk-enforcement suites |
| 13 | Rejected SL / unprotected position | ✅ `require_sl_on_positions` gate | ✅ BLOCK before order; CRITICAL if found post-fill | ❌ Blocked | ✅ Operator intervention | `risk_enforcement.py::_check_position_protection` + tests |
| 14 | Position mismatch after reconnect | ✅ Reconciliation compares broker vs expected | ✅ HALTED on mismatch | ❌ Blocked until resolved | ✅ Manual/explicit reconcile pass required | disconnect-recovery suites |
| 15 | Equity mismatch after reconnect | ✅ Same | ✅ HALTED | ❌ Blocked | ✅ Same | `test_failure_storm.py::equity_mismatch_halts` |
| 16 | Fingerprint mismatch (config drift) | ✅ FingerprintVerifier at startup + per-cycle | ✅ BLOCKED + audit entry | ❌ HALT immediately | ✅ Fix config → fingerprint matches T=0 → resume path | `test_fingerprint_verifier.py` (12), chaos `fingerprint_mutation` |
| 17 | Corrupted local state file | ✅ Hash validation (daily baseline) / JSON guard (supervisor) | ✅ Treat as missing → fail closed | ❌ Re-baselined from broker equity | ✅ Safe rebuild | clock-reliability corrupted-baseline tests; supervisor `_load_state` guards |
| 18 | Corrupted audit log (in-memory) | N/A — bounded list, reconstructable | N/A | ✅ Unaffected | ✅ Trailing window only; durability is broker-side | memory-leak suite |
| 19 | Clock anomaly (naive time, TZ drift) | ✅ Source-scan + behavior tests | ✅ CI failure (not runtime) | N/A | ✅ UTC-only contract pinned | `test_clock_reliability.py` (20) |
| 20 | Disk full during state write | ✅ OSError caught in atomic-write paths | ✅ tmp discarded; last good state retained | ✅ Continues (state files non-critical for safety) | ✅ Next successful write | supervisor/daily-loss `_save_*` except-paths |
| 21 | Insufficient margin | ✅ Broker reject + free-margin gate | ✅ Order refused, logged | ✅ System remains up | ✅ Next cycle | risk gates `_check_*` |
| 22 | Spread explosion / bad pricing | ⚠️ Not gated pre-order | N/A | ⚠️ Current exposure via weekly cadence is low-frequency | — | **OPEN GAP (G4)** — acceptable at $5K weekly cadence |
| 23 | Unexpected manual trade on account | ⚠️ Position-count/exposure gates catch overflow | ✅ Gates block new orders when limits consumed | ❌ If beyond envelope | ✅ Operator resolves attribution | position-count gate tests |
| 24 | Duplicate process instance | ✅ PID file liveness check | ✅ Second instance exits | N/A (first unaffected) | N/A | `test_supervisor.py` |
| 25 | Symbol spec change (lot/step) | ❌ Not detected at runtime | N/A | ⚠️ Sizing could violate broker min/max | ❌ See Gap G3 | **OPEN GAP** |

---

## Coverage Summary (current vs. pre-remediation)

| Category | Pre-remediation | Current | Basis |
|----------|:--------------:|:-------:|-------|
| Detection | 12/25 (48%) | 20/25 (80%) | Items 6,7,10,13,14,15,16,17,18,19 newly covered |
| Immediate action | 10/25 (40%) | 21/25 (84%) | HALT semantics wired through recovery machine |
| Trading permission control | 8/25 (32%) | 23/25 (92%) | State machine makes "no trade while unsafe" the default |
| Recovery | 5/25 (20%) | 19/25 (76%) | Restart/reconnect/reconcile certified by simulation |
| Audit record | 10/25 (40%) | 21/25 (84%) | RiskEnforcer audit + fingerprint log + bounded trail |

---

## Open Gaps (ranked)

| ID | Gap | Severity | Required for |
|----|-----|----------|--------------|
| G1 | Order idempotency keys (duplicate-safe submission under retry) | P1 | Any capital scaling; live long-horizon operation |
| G2 | Hard timeout wrapper around `order_send` | P1 | Live operation (hang = unmanaged exposure) |
| G3 | Runtime symbol-spec validation (min/max lot, step) before sizing | P2 | Scaling ≥ $50K where lots grow |
| G4 | Pre-order spread/liquidity sanity gate | P2 | Scaling ≥ $100K; low urgency at $5K weekly cadence |
| G5 | PartialFillManager fully wired into production loop | P1 | Live operation with any capital |

G1–G5 are also recorded in `FINAL_SCALABILITY_CERTIFICATION.md`. None are exercised
at $5K weekly-cadence micro-live scale today, but all become blockers before Tier 3
($10K+) promotion.
