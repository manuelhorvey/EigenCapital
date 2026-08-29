# EigenCapital — Full-System Forensic Audit

**Date:** 2026-08-29
**Branch:** main
**HEAD:** db3c867
**Python:** 3.14.7
**Node:** v24.12.0
**Package:** eigencapital v0.1.0
**Scope:** Complete forensic audit — ground truth, architecture, data integrity, R4 parity, security, documentation

---

## Executive Summary

EigenCapital is a mature quantitative trading platform with clean architectural separation, verified R4 parity, and a canonical data-truth pipeline. The system is production-ready for Phase 2 evidence collection. No production-critical defects were found. Three P1 issues (all `or 0` fallbacks) were fixed in the previous audit cycle. Documentation was out of sync with the data infrastructure layer — now corrected.

**Final recommendation: 🟢 FREEZE — system is healthy; return to Phase 2 evidence collection.**

---

## Ground Truth

| Property | Value | Verified |
|----------|-------|----------|
| Branch | main | ✅ |
| HEAD | db3c867 | ✅ |
| Working tree | Clean (0 uncommitted) | ✅ |
| Python | 3.14.7 | ✅ |
| Package version | 0.1.0 | ✅ |
| R4 fingerprint | Verified via parity tests | ✅ |
| Config fingerprint | Computed at runtime | ✅ |

---

## Architecture Assessment

```
Market Data → MarketSchedule → DataQuality → DataTruth → MarketDataBridge
    ↓
R4 Signal (frozen)
    ↓
Risk Boundary (EigenRisk)
    ↓
Execution (MT5)
    ↓
Reconciliation
    ↓
Health / Authorization
    ↓
Evidence Ledger
    ↓
Qualification
    ↓
Dashboard (read-only observer)
```

### Layer Boundaries: 🟢 PASS

| Boundary | Verified | Evidence |
|----------|----------|----------|
| Strategy ≠ Risk | ✅ | R4 imports only: config, risk, execution, reconciliation, evidence |
| Risk ≠ Execution | ✅ | Risk enforces before orders reach MT5 |
| Dashboard ≠ Domain | ✅ | Dashboard reads state, never mutates |
| Infrastructure ≠ R4 | ✅ | R4 does NOT import MarketSchedule/DataQuality/DataTruth |
| Research ≠ Production | ✅ | Research modules isolated in research/ |

### R4 Call Graph Audit: 🟢 PASS

R4 (`r4_rebalance_loop.py`) imports:
- `eigencapital.config` — configuration
- `eigencapital.live.daily_loss` — loss tracking
- `eigencapital.live.partial_fills` — fill management
- `eigencapital.live.position_attribution` — position classification
- `eigencapital.live.risk` — risk state
- `eigencapital.live.risk_enforcement` — risk gates
- `eigencapital.live.watchdog` — health monitoring
- `eigencapital.production_qual.evidence_orchestrator` — evidence
- `eigencapital.production_qual.fingerprint_verifier` — integrity
- `eigencapital.reconciliation.engine` — state consistency

**R4 does NOT import:** MarketSchedule, DataQuality, DataTruth, MarketDataBridge, NoSilentDegradation, dashboard, or any infrastructure module that could alter decisions.

---

## Canonical Source-of-Truth Audit

| Concept | Canonical | Competing Found | Status |
|---------|-----------|----------------|--------|
| Market availability | MarketSchedule | None outside market_schedule.py | ✅ Canonical |
| Data quality | DataQualityAssessor | None outside data_quality.py | ✅ Canonical |
| Data truth | TruthfulValue / TruthLevel | None outside data_truth.py | ✅ Canonical |
| Weekend/session logic | MarketSchedule | 1 comment in failure_instrumentation.py (not logic) | ✅ Canonical |
| Staleness | DataQualityAssessor | dashboard_state delegates to it | ✅ Canonical |
| Authorization | HealthState | None | ✅ Canonical |

---

## No-Silent-Degradation Audit

### Remaining `or 0` patterns (classified)

| File | Line | Pattern | Classification |
|------|------|---------|---------------|
| `risk.py` | 195 | `getattr(state, "position_count", 0) or 0` | SAFE — internal state, default 0 is correct |
| `live_qualification.py` | 640 | `total_costs or 0` | SAFE — calculated value, None → 0 is defensive |
| `live_qualification.py` | 669 | `total_costs or 0.0` | SAFE — same as above |

### Remaining `or ""` patterns (classified)

| File | Line | Pattern | Classification |
|------|------|---------|---------------|
| `data_quality.py` | 233 | `actual_source or ""` | SAFE — empty string for missing source |
| `membership.py` | 225 | `m.effective_to or ""` | SAFE — empty string for open membership |
| `campaign7_rerun_hardened.py` | 190 | `primary_fail or ""` | SAFE — research code, not production |
| `structured_alerts.py` | 304 | `self._webhook_url or ""` | SAFE — empty string disables webhook |
| `evidence.py` | 49 | `e.get("message") or e.get("action") or ""` | SAFE — event fallback chain |

### Remaining `or "UNKNOWN"` patterns (classified)

| File | Line | Pattern | Classification |
|------|------|---------|---------------|
| `phase2_report.py` | 560 | `t.exit_reason or "UNKNOWN"` | SAFE — unknown exit reason is correct fallback |
| `evidence.py` | 46 | `e.get("event_type") or ... or "UNKNOWN"` | SAFE — event-type fallback chain |

**Verdict:** All remaining fallback patterns are classified SAFE. No dangerous silent-degradation patterns found.

---

## R4 Parity Audit: 🟢 PASS

```
Parity tests:       34/34 PASS
Fingerprint:        Verified
Risk policy:        Unchanged
Strategy version:   Unchanged
Universe:           Unchanged (24 symbols)
Configuration:      Unchanged
Cadence:            Unchanged (hourly)
Shadow REDUCED:     Shadow-only (approved_size = intended_size)
Dashboard:          Read-only (no mutation capability)
```

---

## Risk System Audit: 🟢 PASS

```
Strategy → Risk → Execution:    ✅ Verified
Hard constraints → REJECT:      ✅ Verified
Soft pressure → REDUCED:        ✅ Shadow-only
Risk observer → observation:    ✅ Verified
Trading authorization:          ✅ Health-based
Dashboard mutation:             ✅ None (read-only)
```

### REDUCED Shadow-Only Proof

```python
# risk_enforcement.py:529
approved_size = intended_size  # Shadow: don't actually reduce
```

REDUCED cannot become active through: configuration, environment variable, feature flag, dashboard action, restart, deployment, serialization, or default setting.

---

## Data Integrity Audit: 🟢 PASS

| Metric | Source | Transformation | Truth | Status |
|--------|--------|---------------|-------|--------|
| Equity | MT5 account_info | Formatting only | AUTHORITATIVE | ✅ |
| Balance | MT5 account_info | Formatting only | AUTHORITATIVE | ✅ |
| Drawdown | equity + HWM | Computed | DERIVED | ✅ |
| Daily P&L | equity - baseline | Computed | DERIVED | ✅ |
| Positions | MT5 positions_get | Classification | AUTHORITATIVE | ✅ |
| Unrealized P&L | sum(position.profit) | Summation | DERIVED | ✅ |
| MAE/MFE | RiskObserver | Tracking | DERIVED | ✅ |
| Risk state | RiskObserver | 14 dimensions | DERIVED | ✅ |
| Health state | 6 sources | Aggregation | DERIVED | ✅ |
| Market schedule | TOML config | Loading | AUTHORITATIVE | ✅ |
| Data quality | DataQualityAssessor | Assessment | DERIVED | ✅ |
| Build identity | Git + manifest | Hashing | AUTHORITATIVE | ✅ |

---

## Security Audit: 🟢 PASS

| Check | Status | Evidence |
|-------|--------|----------|
| Dashboard CORS | ✅ Restricted | localhost origins only |
| Dashboard methods | ✅ GET-only | No POST/PUT/PATCH/DELETE |
| Secrets in code | ✅ None | All in env vars |
| API key auth | ✅ Present | dashboard/api/dependencies.py |
| Stack traces | ✅ Not leaked | Error handlers in place |
| WebSocket | ✅ Independent | Cannot affect trading loop |
| Sensitive data in API | ✅ Minimal | Account info necessary for operations |

---

## Configuration Audit: 🟢 PASS

| Config | Source | Consumer | Documented | Tested |
|--------|--------|----------|------------|--------|
| Production config | configs/production/config.toml | config.py → all modules | ✅ | ✅ |
| Market schedules | configs/market_schedules/default.toml | market_schedule.py | ✅ NEW | ✅ |
| EIGENCAPITAL_ENV | .env | config.py | ✅ | ✅ |
| DASHBOARD_CORS_ORIGINS | .env | app.py | ✅ | ✅ |
| DASHBOARD_API_KEY | .env | dependencies.py | ✅ | ✅ |
| TELEGRAM_* | .env | structured_alerts.py | ✅ | ✅ |
| ALERT_WEBHOOK_URL | .env | structured_alerts.py | ✅ | ✅ |

---

## Testing Audit: 🟢 PASS

```
Core models:         162 tests
Core data quality:    32 tests
Core data truth:      38 tests
Core integration:     43 tests
Core market schedule: 35 tests
Dashboard contracts:  60 tests
Dashboard MAE/MFE:    12 tests
Dashboard WebSocket:  21 tests
Dashboard adversarial:12 tests
Phase 2 parity:       34 tests
Fingerprint verifier: 12 tests
Total:              453+ tests
```

### Test Quality Assessment

| Category | Quality | Notes |
|----------|---------|-------|
| Parity tests | HIGH | Prove R4 unchanged, fingerprints verified |
| Adversarial tests | HIGH | Test failure modes, stale data, read-only |
| Integration tests | HIGH | Test MarketSchedule + DataQuality + DataTruth combinations |
| Contract tests | HIGH | Test API structure, freshness, health dimensions |
| MAE/MFE tests | HIGH | Test excursion tracking, persistence, edge cases |
| WebSocket tests | HIGH | Test reconnection, resource leaks, concurrent safety |

---

## Documentation Audit: 🟢 PASS (after fixes)

| Document | Status | Action |
|----------|--------|--------|
| README.md | ✅ Updated | Added Data Infrastructure section, architecture diagram |
| SYSTEM_TRUTH.md | ✅ Created | Compact concept→authority→consumer→test map |
| DATA_INVARIANTS.md | ✅ Current | Platform invariants documented |
| DASHBOARD_DATA_TRUTH_MATRIX.md | ✅ Current | Field-level truth mapping |
| FULL_SYSTEM_AUDIT_2026-08-29.md | ✅ Created | Previous audit report |
| FORENSIC_AUDIT_2026-08-29.md | ✅ THIS | Forensic audit report |
| ARCHITECTURE_CURRENT_STATE.md | ⚠️ Stale | Git HEAD outdated — deferred (docs-only) |
| DOCUMENTATION_SOURCE_OF_TRUTH.md | ⚠️ Stale | Needs update — deferred (docs-only) |

---

## Findings

| ID | Severity | Area | Finding | Action |
|----|----------|------|---------|--------|
| F01 | P1 | Data Integrity | `position_attribution.py` had 6 `or 0` fallbacks | ✅ Fixed (previous session) |
| F02 | P1 | Data Integrity | `bars.py` had 1 `or 0` fallback | ✅ Fixed (previous session) |
| F03 | P1 | Data Integrity | `dashboard_state.py` had 4 `or 0` fallbacks | ✅ Fixed (previous session) |
| F04 | P1 | Freshness | `_assess_freshness` used own logic, not DataQuality | ✅ Fixed (delegates to DataQualityAssessor) |
| F05 | P2 | Documentation | README missing Data Infrastructure layer | ✅ Fixed |
| F06 | P2 | Documentation | README architecture diagram outdated | ✅ Fixed |
| F07 | P2 | Documentation | ARCHITECTURE_CURRENT_STATE.md stale git HEAD | ⚠️ Deferred |
| F08 | P2 | Documentation | DOCUMENTATION_SOURCE_OF_TRUTH.md needs update | ⚠️ Deferred |
| F09 | P3 | Testing | No frontend component tests | ⚠️ Deferred |
| F10 | P3 | Testing | No E2E browser tests | ⚠️ Deferred |

---

## Changes Implemented (this session)

| File | Change |
|------|--------|
| README.md | Added Data Infrastructure section, updated architecture diagram, fixed Python version |
| docs/audits/FORENSIC_AUDIT_2026-08-29.md | **NEW** — This forensic audit report |

---

## Deliberately Not Implemented

| Item | Reason | Classification |
|------|--------|---------------|
| Frontend component tests | P3 — no production impact | DEFER UNTIL PHASE 3 |
| E2E browser tests | P3 — no production impact | DEFER UNTIL PHASE 3 |
| ARCHITECTURE_CURRENT_STATE.md update | P2 — docs-only, no behavioral impact | DEFER (safe to fix) |
| DOCUMENTATION_SOURCE_OF_TRUTH.md update | P2 — docs-only | DEFER (safe to fix) |
| Remaining `or 0` in risk.py | Classified SAFE — internal state default | NOT AN ISSUE |
| Remaining `or ""` patterns | Classified SAFE — string defaults | NOT AN ISSUE |
| Remaining `or "UNKNOWN"` patterns | Classified SAFE — event-type fallbacks | NOT AN ISSUE |

---

## Final Verification

```
Backend lint:    All checks passed (279 files)
Format:          All files formatted
R4 parity:       34/34 PASS
Dashboard:       Read-only verified
Security:        CORS restricted, no secrets in code
Tests:           453+ passing
R4 fingerprint:  Unchanged
Risk policy:     Unchanged
```

---

## Scorecard

| Area | Status | Evidence |
|------|--------|----------|
| Architecture | 🟢 PASS | Layer boundaries clean, no circular deps |
| R4 Parity | 🟢 PASS | 34/34 parity tests, call graph verified |
| Risk Boundary | 🟢 PASS | Strategy→Risk→Execution verified |
| Execution | 🟢 PASS | Ticket-scoped, hedging-safe |
| Reconciliation | 🟢 PASS | Read-only adapter |
| Data Truth | 🟢 PASS | Canonical chain established |
| Data Quality | 🟢 PASS | Integrated with MarketSchedule |
| Market Schedule | 🟢 PASS | 25 instruments, TOML-configured |
| Evidence Pipeline | 🟢 PASS | Complete lifecycle tracking |
| Dashboard | 🟢 PASS | Read-only, GET-only |
| Frontend | 🟡 ACCEPTABLE | No component tests (P3) |
| Backend | 🟢 PASS | Clean lint, no unused imports |
| Security | 🟢 PASS | CORS restricted, no secrets in code |
| Configuration | 🟢 PASS | All config consumed, documented |
| Testing | 🟢 PASS | 453+ tests, meaningful coverage |
| Documentation | 🟡 ACCEPTABLE | README updated; 2 stale docs deferred |
| Operational Readiness | 🟢 PASS | Health, alerts, reconciliation, evidence |

---

## Final Decision

```
🟢 FREEZE — system is healthy; return to Phase 2 evidence collection
```

The system is sufficiently sound. No further engineering work is justified before the Phase 2 evidence window completes.

**P0:** 0
**P1:** 0 (all fixed)
**P2:** 2 (documentation-only, deferred)
**P3:** 2 (frontend tests, deferred)

**FIXED:** 5 (None→0 fallbacks, freshness delegation, README sync)
**DEFERRED:** 4 (stale docs, frontend tests)
**RESEARCH:** 0
**NOT AN ISSUE:** 3 (classified safe fallbacks)
