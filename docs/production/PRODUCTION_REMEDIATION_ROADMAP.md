# Production Remediation Roadmap

**Based on:** Codebase Forensic Audit (2026-08-27)
**Audit Score:** 74/100
**Verdict:** Production Ready with Minor Changes

---

## P0 — Immediate (Must fix before continued production)

### F-001: Import error in research/__init__.py

**Severity:** CRITICAL
**Finding:** `ProvenanceManifest` should be `ResearchManifest`
**Impact:** 20 tests fail to collect; any import of eigencapital.research fails
**Fix:** Change import in `src/eigencapital/research/__init__.py`
**Effort:** 1 minute
**Regression Risk:** None
**Test:** Verify all 20 tests collect after fix

```python
# Before:
from eigencapital.research.provenance.manifest import ProvenanceManifest

# After:
from eigencapital.research.provenance.manifest import ResearchManifest
```

### F-002: ReconciliationEngine not in main loop

**Severity:** HIGH
**Finding:** Full reconciliation engine exists but is not called in r4_rebalance_loop.py
**Impact:** Broker/internal divergence may go undetected
**Fix:** Import and call `ReconciliationEngine.reconcile()` in `run_cycle()`
**Effort:** 2-4 hours
**Regression Risk:** Low — additive change
**Test:** Integration test: reconciliation blocks trading on mismatch

---

## P1 — Required (Fix before meaningful scale)

### F-003: Hardcoded min_equity in risk_observation.py

**Severity:** MEDIUM
**Finding:** `min_equity = 4000.0` hardcoded instead of reading from config
**Impact:** Risk observation ignores config changes
**Fix:** Accept `LiveRiskConfig` in `RiskObserver.__init__`; use `self._config.min_equity`
**Effort:** 15 minutes
**Regression Risk:** Low — parameter injection
**Test:** Unit test: RiskObserver respects config value

### F-004: Consolidate duplicate module names

**Severity:** MEDIUM
**Finding:** 18 duplicate module names across packages
**Impact:** Import confusion; maintenance burden
**Fix:** Rename ambiguous modules (e.g., `live/broker.py` → `live/mt5_broker.py`)
**Effort:** 2-3 days
**Regression Risk:** Medium — import path changes
**Test:** Verify all imports still resolve

### F-005/F-006: Consolidate duplicate systems

**Severity:** MEDIUM
**Finding:** Two alert systems; two reconciliation engines
**Impact:** Confusion about which to use
**Fix:** Remove deprecated modules or add deprecation warnings
**Effort:** 1 day
**Regression Risk:** Low
**Test:** Verify no production imports of deprecated modules

---

## P2 — Planned (Important improvements)

### F-007: Atomic writes for supervisor state

**Severity:** LOW
**Finding:** Supervisor state written without tmp+rename pattern
**Impact:** Corrupted state on crash during write
**Fix:** Use tmp+rename pattern like `_persist_state()` in r4_rebalance_loop.py
**Effort:** 30 minutes
**Regression Risk:** None
**Test:** Verify state survives simulated crash

### F-008: Research campaign cleanup

**Severity:** LOW
**Finding:** 10+ campaign files with near-identical structure
**Impact:** Maintenance burden; code duplication
**Fix:** Extract common patterns into shared utilities (post-Phase 2)
**Effort:** 3-5 days
**Regression Risk:** Medium — refactoring research code
**Test:** All campaign tests pass after refactor

### F-009: Add retry logic to order submission

**Severity:** LOW
**Finding:** No retry logic or idempotency keys on order submission
**Impact:** Transient errors cause permanent failure
**Fix:** Add retry wrapper with idempotency key generation
**Effort:** 2-4 hours
**Regression Risk:** Low — additive change
**Test:** Unit test: retry on transient failure

### F-010: Add PID liveness check to supervisor

**Severity:** LOW
**Finding:** PID file checked but no liveness verification
**Impact:** Stale PID prevents new instance
**Fix:** Add `os.kill(pid, 0)` check before rejecting duplicate
**Effort:** 30 minutes
**Regression Risk:** None
**Test:** Unit test: stale PID allows new instance

---

## Implementation Sequence

### Phase A: Critical fixes (1-2 hours)
1. Fix F-001 (import error) — 1 min
2. Fix F-003 (hardcoded min_equity) — 15 min
3. Fix F-007 (atomic supervisor state) — 30 min
4. Fix F-010 (PID liveness check) — 30 min

### Phase B: Integration (4-8 hours)
1. Fix F-002 (integrate reconciliation) — 4 hours
2. Fix F-009 (retry logic) — 4 hours

### Phase C: Cleanup (2-3 days)
1. Fix F-005/F-006 (remove deprecated modules) — 1 day
2. Fix F-004 (rename duplicate modules) — 2 days

### Phase D: Research cleanup (3-5 days, post-Phase 2)
1. Fix F-008 (extract common patterns) — 3-5 days

---

## Verification Plan

After each fix:
1. Run `python -m pytest tests/unit/production_qual/ tests/integration/ tests/property/ -q`
2. Run `python -m pytest tests/ --co -q` to verify test collection
3. Verify no new import errors
4. Verify no regressions in existing tests

---

## Risk Assessment

| Phase | Risk | Mitigation |
|-------|------|------------|
| A | Very Low | Minimal changes, well-isolated |
| B | Low | Additive changes, existing behavior preserved |
| C | Medium | Import path changes require careful testing |
| D | Medium | Research code refactoring, frozen during Phase 2 |

---

## Decision: When to Implement

**Recommended:** Implement Phase A immediately (1-2 hours). Phase B can wait until after Phase 2 evidence window. Phase C and D should wait until after Phase 2 qualification completes.

**Rationale:** The critical blocker (F-001) prevents 20 tests from running. The other P0 item (F-002) is important but not blocking current $5K operation. The P1/P2 items are improvements that can safely follow.
