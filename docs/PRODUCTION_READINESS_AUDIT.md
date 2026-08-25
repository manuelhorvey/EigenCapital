# Production Readiness Audit — R4 Phase 1U Funding Gate

**Status:** ⚠️ CONDITIONAL GO — hardening required before capital at MINIMAL scale
**Audit Date:** 2026-08-25
**Scope:** data → signal → portfolio → risk → execution → reconciliation → monitoring → kill switch
**Test baseline:** 1729 passed / 1 skipped

---

## 1. Purpose

The R4 fidelity ladder (research → replay → forward paper → shadow →
micro-live) has passed, but fidelity-passing does not by itself make the
system production-ready. This audit assesses each chain stage against the
pre-funding checklist and separates **verified capabilities** from
**gaps that must close before Phase 1U MINIMAL ($5K)**.

---

## 2. Stage-by-stage capability matrix

### Data ✅
| Capability | Status | Evidence |
|---|---|---|
| Snapshot immutability + hashes | ✅ | `data/*/manifest.json`, provider manifests |
| Anomaly detection (zero-vol, halts, missing bars) | ✅ | `data/validation/anomalies.py` |
| Stale/missing-bar operational events | ✅ | `fidelity/forward.py` |

### Signal ✅
| Capability | Status | Evidence |
|---|---|---|
| Frozen configuration identity | ✅ | `fidelity/r4_manifest.py`; drift guard: `tests/unit/fidelity/test_r4_manifest_guard.py` (39 tests) |
| Fingerprint bound to committed artifacts | ✅ | PQ report campaign `PQ-aaab6c00dc05` = identity prefix |
| Strategy cannot bypass risk boundary | ✅ | Architecture contract (`core/models/risk_decision.py`) |

### Portfolio 🟡
| Capability | Status | Evidence |
|---|---|---|
| Target construction with rejection tracking | ✅ | `portfolio/portfolio.py` |
| Correlation-aware sizing | ✅ strategy layer | R4 `correlation_threshold=0.7` |
| Independent portfolio-level exposure monitor | ❌ | See §3 |

### Risk ✅ (hard checks) / 🟡 (aggregate)
Existing hard checks (`risk/checks/account_checks.py`):
`max_drawdown`, `daily_loss`, `weekly_loss`, `gross_leverage`,
`min_equity`, `position_count`, `kill_switch`.
Policy caps exist for asset-class exposure, concentration, per-position
notional/risk (`risk/policy.py`). VaR/CVaR are **diagnostic-only by
documented design** — never a hard trigger (`core/models/risk_decision.py`).
Scaling envelopes define per-level concurrent-position and daily-loss
limits (`production_qual/scaling.py`: MINIMAL = 5 positions / $50 day).

Gaps: asset-class/concentration caps are policy fields but not yet wired
as enforced checks in the account-check pipeline; live path uses its own
simpler limits (`live/risk.py`) that do not consume `RiskPolicy`.

### Execution 🟡
| Capability | Status | Evidence |
|---|---|---|
| Order lifecycle (submit/fill/cancel/reject) | ✅ | `execution/broker.py` (`OrderLifecycleState`) |
| Position accounting from fills | ✅ | `execution/position_manager.py`, `account.py` |
| Fill/slippage/rejection/partial-fill attribution | ✅ measured | `micro_live/campaign.py`, `production/evidence.py` |
| Spread monitoring + rejection on spread breach | ✅ shadow layer | `fidelity/shadow.py` |
| Partial-fill handling in live order path | 🟡 tracked only | counted, not managed |
| Broker disconnect auto-recovery | ❌ | only explicit disconnect (`micro_live/runner.py`) |

### Reconciliation ✅
| Capability | Status | Evidence |
|---|---|---|
| Positions / cash / fill-count vs broker | ✅ fail-closed | `execution/reconciliation.py` ("never silently repair") |
| Periodic cadence | ✅ | forward-paper engine (100-tick cycle), PQ check |
| Package hygiene | ✅ fixed | top-level `reconciliation/` was an empty shell; now a facade over the canonical engine |

### Monitoring ✅ (new) — previously ❌ empty package
| Capability | Status | Evidence |
|---|---|---|
| Portfolio-health state machine | ✅ | `monitoring/health.py` (`HEALTHY/DEGRADED/CRITICAL/FROZEN`) |
| Fail-closed freshness enforcement | ✅ | stale/unparseable/future snapshot ⇒ CRITICAL |
| Structured alerts (severity + stable codes) | ✅ | 14 alert codes; critical dominates warnings; kill-switch dominates all |
| Immutable hash-chained event log | ✅ | append-only, `verify_log_integrity()` detects payload or chain edits |
| Policy integration | ✅ | consumes `RiskPolicy` hard constraints + warn thresholds |
| Tests | ✅ 26 | `tests/unit/monitoring/test_health.py` |

Still open under observability: operator-facing dashboard/alert delivery,
snapshot-freshness wiring into the live loop (the monitor exists; the
live runner does not yet call it).

### Kill Switch ✅
| Capability | Status | Evidence |
|---|---|---|
| Independent switch class | ✅ | `shadow/safety.py::KillSwitch` |
| Policy flag rejects all new positions | ✅ | `risk/checks/account_checks.py::check_kill_switch` |
| Health-state integration | ✅ | `HealthState.FROZEN`, dominant over every other state |
| Activation accounting | ✅ | `production/live_campaign.py` |
| Tested | ✅ | shadow/live/production suites |

---

## 3. Gaps closed by this audit

1. **Monitoring package was empty** — implemented `PortfolioHealthMonitor`
   with fail-closed assessment and tamper-evident event log.
2. **`reconciliation/` dead package** — converted to explicit facade;
   canonical engine remains in `execution/`.
3. **Frozen-R4 manifest guard debt** — closed earlier this session
   (`test_r4_manifest_guard.py`): golden identity pinned to the published
   PQ fingerprint, sensitivity coverage of all governed parameters,
   explicit pinning of identity-exempt fields.

## 4. Pre-funding checklist (must close before MINIMAL $5K)

- [ ] Wire asset-class-exposure and concentration caps into the enforced
      account-check pipeline (currently policy fields without a check fn).
- [ ] Unify live-path limits (`live/risk.py`) with `RiskPolicy` so the
      funded envelope has exactly one source of truth.
- [ ] Call `PortfolioHealthMonitor.assess()` inside the micro-live /
      qualification loops; halt on any non-operational state.
- [ ] Broker disconnect recovery policy for the live runner (detect,
      reconcile-or-flatten, resume criteria).
- [ ] Partial-fill management rule (accept / chase / cancel) rather than
      count-only tracking.
- [ ] Alert delivery path (log + local file minimum; operator-visible).

## 5. Verdict

The system is **structurally sound and fail-closed at every audited
boundary**, but §4 lists concrete engineering items that stand between
"fidelity ladder passed" and "safe to fund." None require research work;
all are execution/observability engineering. Close §4, then begin the
Phase 1U MINIMAL campaign.
