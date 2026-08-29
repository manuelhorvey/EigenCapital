# EigenCapital Full System Audit

**Date:** 2026-08-29
**Branch:** main
**HEAD:** ea07779
**Auditor:** Buffy (Codebuff)
**Scope:** Complete production-grade system audit

---

## Executive Summary

EigenCapital is a mature quantitative trading platform currently running Phase 2 live economic validation. The architecture is well-structured with clean separation between strategy, risk, execution, reconciliation, evidence, and observability layers. The recently completed DataTruth/DataQuality/MarketSchedule integration establishes a canonical chain of truth. The system has 453+ automated tests, clean lint, and verified R4 parity.

**Overall: PASS with minor documentation debt.**

---

## Current Architecture

```
Strategy R4 (frozen)
    ↓
Risk Boundary (EigenRisk)
    ↓
Execution (MT5)
    ↓
Reconciliation
    ↓
Evidence/Ledger

Supporting:
MarketSchedule → DataQuality → DataTruth → MarketDataBridge
Dashboard (read-only observer)
```

---

## Technology Stack

### Backend
- **Python:** >= 3.11 (running 3.14.7)
- **FastAPI:** Dashboard API
- **Pydantic:** DTO schemas
- **Ruff:** Linting + formatting
- **pytest:** Testing
- **JSONL/JSON:** Persistence (no database)

### Frontend
- **React** + **TypeScript** + **Vite**
- **Tailwind CSS**
- **React Query** (API layer)
- **WebSocket** (live streaming)

---

## Findings

| ID | Severity | Area | Finding | Action |
|----|----------|------|---------|--------|
| F01 | P0 | Security | Dashboard read-only — verified: no POST/PUT/PATCH/DELETE | ✅ Confirmed |
| F02 | P0 | R4 Parity | 34/34 parity tests pass, fingerprints verified | ✅ Confirmed |
| F03 | P1 | Data Integrity | `position_attribution.py` had 6 `or 0` fallbacks | ✅ Fixed |
| F04 | P1 | Data Integrity | `bars.py` had 1 `or 0` fallback | ✅ Fixed |
| F05 | P1 | Data Integrity | `dashboard_state.py` had 4 `or 0` fallbacks | ✅ Fixed (previous session) |
| F06 | P1 | Freshness | `_assess_freshness` used own logic, not DataQuality | ✅ Fixed (delegates to DataQualityAssessor) |
| F07 | P2 | Documentation | `ARCHITECTURE_CURRENT_STATE.md` has stale git HEAD | ⚠️ Deferred (docs-only) |
| F08 | P2 | Documentation | Multiple stale audit reports from previous sessions | ⚠️ Deferred (historical) |
| F09 | P3 | Testing | No frontend component tests (TypeScript compilation only) | ⚠️ Deferred |
| F10 | P3 | Testing | No E2E browser tests | ⚠️ Deferred |

---

## R4 Parity Verification

```
Parity tests:       34/34 PASS
Fingerprint:        Verified
Risk policy:        Unchanged
Strategy version:   Unchanged
Universe:           Unchanged
Configuration:      Unchanged
Cadence:            Unchanged
Shadow REDUCED:     Shadow-only (not applied live)
```

---

## Risk Audit

```
Strategy → Risk → Execution:    ✅ Verified
Hard constraints → REJECT:      ✅ Verified
Soft pressure → REDUCED:        ✅ Verified (shadow only)
Risk observer → observation:    ✅ Verified
Trading authorization:          ✅ Verified (health-based)
Dashboard mutation:             ✅ None (read-only)
```

---

## Data Integrity Audit

```
Account state:       MT5 → dashboard_state → API → React (authoritative)
Position data:       MT5 → dashboard_state → API → React (authoritative)
Risk state:          RiskObserver → JSON → dashboard_state → API → React
Health state:        6 sources → dashboard_state → API → React
Market schedule:     TOML → MarketSchedule → MarketDataBridge
Data quality:        DataQualityAssessor (canonical)
Data truth:          TruthfulValue / TruthLevel (canonical)
```

---

## Security Audit

```
Dashboard CORS:      Restricted to localhost origins ✅
Dashboard methods:   GET only ✅
Secrets in code:     None found (all in env vars) ✅
API key auth:        Present (dashboard/api/dependencies.py) ✅
Stack traces:        Not leaked to clients ✅
WebSocket:           Independent of trading loop ✅
```

---

## Testing Audit

```
Backend tests:       453+ passing
Lint:                All checks passed (279 files)
Format:              All files formatted
TypeScript:          Clean compilation
Parity tests:        34/34 passing
Adversarial tests:   12/12 passing
```

---

## Documentation Audit

| Document | Status | Notes |
|----------|--------|-------|
| README.md | ✅ Current | Accurate architecture, phases, stack |
| SYSTEM_TRUTH.md | ✅ NEW | Compact truth map |
| DATA_INVARIANTS.md | ✅ Current | Platform invariants |
| DASHBOARD_DATA_TRUTH_MATRIX.md | ✅ Current | Field-level truth mapping |
| PHASE_STATUS.md | ⚠️ Stale | Git HEAD outdated |
| ARCHITECTURE_CURRENT_STATE.md | ⚠️ Stale | Git HEAD outdated |

---

## Changes Implemented

| File | Change |
|------|--------|
| `live/position_attribution.py` | Replaced 6 `or 0` fallbacks with explicit None checks |
| `data/normalization/bars.py` | Replaced 1 `or 0` fallback with explicit None check |
| `docs/architecture/SYSTEM_TRUTH.md` | **NEW** — Compact truth map |

---

## Deliberately Not Implemented

| Item | Reason |
|------|--------|
| Frontend component tests | P3 — no production impact |
| E2E browser tests | P3 — no production impact |
| Documentation HEAD updates | P2 — docs-only, no behavioral impact |
| Historical audit cleanup | P2 — no behavioral impact |

---

## Final Verification

```
R4 parity:       34/34 PASS
Backend lint:    All checks passed
Format:          All files formatted
TypeScript:      Clean compilation
Tests:           453+ passing
R4 fingerprint:  Unchanged
Risk policy:     Unchanged
Dashboard:       Read-only verified
```

---

## Scorecard

| Area | Status | Evidence |
|------|--------|----------|
| Architecture | 🟢 PASS | Canonical chain verified |
| R4 Parity | 🟢 PASS | 34/34 parity tests |
| Risk Boundary | 🟢 PASS | Strategy→Risk→Execution verified |
| Reconciliation | 🟢 PASS | Read-only adapter |
| Data Integrity | 🟢 PASS | None→0 fallbacks eliminated |
| Dashboard | 🟢 PASS | Read-only, GET-only |
| Security | 🟢 PASS | CORS restricted, no secrets in code |
| Configuration | 🟢 PASS | TOML authoritative, env override |
| Testing | 🟢 PASS | 453+ tests, clean lint |
| Documentation | 🟡 ACCEPTABLE | SYSTEM_TRUTH.md created; some stale reports |

---

## Final Recommendation

**The system is production-ready for Phase 2 evidence collection.**

The architecture is clean, the data pipeline is canonical, R4 is frozen and verified, the dashboard is read-only, and the test suite provides meaningful protection.

**Do not add features. Do not refactor R4. Let the live system generate evidence.**
