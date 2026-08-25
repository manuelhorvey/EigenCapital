# Production SLOs (Service Level Objectives)

## Availability SLOs

| Objective | Target | Measurement | Current Status |
|-----------|--------|-------------|----------------|
| Application uptime | ≥ 99.5% | Process alive + loop cycling | ✅ Measured |
| Broker connectivity | ≥ 99.0% | MT5 connection active | ⚠️ Depends on MT5 bridge |
| Trading authorization | ≥ 99.5% | Fingerprint + risk + health OK | ✅ Enforced |
| Risk gate availability | 100% | All 7 gates execute | ✅ Enforced |

**Note:** Availability targets assume a stable MT5 bridge/connection. External dependencies (MT5, network) are excluded from application SLOs but tracked separately.

## Safety SLOs

| Objective | Target | Measurement | Current Status |
|-----------|--------|-------------|----------------|
| Unauthorized orders | 0 | RiskEnforcementEngine blocks | ✅ Tested |
| Fingerprint bypasses | 0 | FingerprintVerifier rejects | ✅ Tested |
| Risk-gate bypasses | 0 | All gates execute before order | ✅ Tested |
| Duplicate orders (from recovery) | 0 | Idempotency + reconciliation | ⚠️ Partial (no idempotency keys yet) |
| Trading after disconnect | 0 | DisconnectRecovery blocks | ✅ Tested |
| Trading in FROZEN state | 0 | HealthGate blocks | ✅ Tested |
| Oversized positions | 0 | RiskPolicy enforced | ✅ Tested |

## Recovery SLOs

| Objective | Target | Measurement | Current Status |
|-----------|--------|-------------|----------------|
| Broker reconnection | < 30 seconds | Time from disconnect to reconnect | ⚠️ Depends on MT5 bridge |
| State reconciliation | < 5 seconds | Time from reconnect to RESUME | ✅ Tested |
| Process restart recovery | < 10 seconds | Time from start to RESUME | ✅ Tested |
| Emergency flatten | < 60 seconds | Time to close all positions | ⚠️ Not benchmarked |
| Duplicate instance detection | < 5 seconds | PID file check on start | ✅ Tested |

## Observability SLOs

| Objective | Target | Measurement | Current Status |
|-----------|--------|-------------|----------------|
| Critical state transitions logged | 100% | Audit trail entries | ✅ Implemented |
| Risk decisions auditable | 100% | RiskEnforcementEngine audit | ✅ Implemented |
| Fingerprint verification logged | 100% | FingerprintVerifier log | ✅ Implemented |
| Health state transitions logged | 100% | Health gate audit | ⚠️ Partial |
| Alert delivery | 100% | AlertDispatcher.on_event | ✅ Implemented |

## Performance SLOs

| Objective | Target | Measurement | Current Status |
|-----------|--------|-------------|----------------|
| Cycle latency (p50) | < 2 seconds | Signal → risk → order → reconcile | ⚠️ Not benchmarked |
| Cycle latency (p99) | < 10 seconds | Including broker round-trip | ⚠️ Not benchmarked |
| Memory stability | < 15 MB RSS | Over 10,000 cycles | ✅ Verified (tracemalloc) |
| Memory growth rate | 0 MB/hour | Bounded retention | ✅ Verified |

## Capital Scaling SLOs

| Objective | Target | Measurement | Current Status |
|-----------|--------|-------------|----------------|
| Max capital (certified) | $5K | Current qualification | ✅ |
| Max capital (estimated safe) | $50K-$100K | Capacity analysis | ⚠️ Not live-tested |
| Max positions | 8 | RiskPolicy | ✅ Configured |
| Max concurrent orders | 3 | RiskPolicy | ✅ Configured |

## Failure Mode SLOs

| Scenario | Expected Behavior | Target Recovery | Verified |
|----------|-------------------|-----------------|----------|
| MT5 disconnect | HALT → reconnect → reconcile → resume | < 30s | ✅ |
| Process crash | Start → HALT → load state → reconcile → resume | < 10s | ✅ |
| Daily loss breach | HALT trading for day | Immediate | ✅ |
| Fingerprint mismatch | HALT immediately | Immediate | ✅ |
| Health degradation | DEGRADED → FROZEN if persistent | 3 cycles | ✅ |
| Duplicate process | Second instance blocked | Immediate | ✅ |
| Memory leak | Bounded retention prevents growth | N/A (preventive) | ✅ |

## SLO Violation Response

| Severity | Response | Example |
|----------|----------|---------|
| P0 (Safety) | HALT trading immediately | Fingerprint bypass, unauthorized order |
| P1 (Reliability) | HALT trading, alert operator | Disconnect > 30s, reconciliation failure |
| P2 (Performance) | Log, monitor, alert if persistent | Slow cycle, high memory |
| P3 (Observability) | Log for review | Missing audit entry, stale metric |

## Current Production Certification

| Tier | Capital | Status | Evidence |
|------|---------|--------|----------|
| Level 0 (Research) | — | ✅ Certified | Backtests, paper |
| Level 1 (Paper) | — | ✅ Certified | Paper execution |
| Level 2 (Shadow) | — | ✅ Certified | Real data, simulated execution |
| Level 3 (Micro-live) | $5K | ✅ Certified | Live qualification |
| Level 4 (Controlled) | $10K-$25K | ⚠️ Not Certified | Requires 30+ days stable at $5K |
| Level 5 (Scaled) | $50K+ | ❌ Not Certified | Requires Level 4 evidence |

## Monitoring Checklist

For a production operator, the following must be observable at all times:

- [ ] Process alive (PID file exists and matches running process)
- [ ] Loop cycling (last cycle timestamp < 5 minutes old)
- [ ] Broker connected (MT5 connection active)
- [ ] Fingerprint valid (startup verification passed)
- [ ] Risk policy active (RiskPolicy loaded and valid)
- [ ] Health gate operational (not FROZEN)
- [ ] Daily loss within limits
- [ ] Drawdown within limits
- [ ] Position count within limits
- [ ] No stale broker data
- [ ] Alerts operational
