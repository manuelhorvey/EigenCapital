# EC-AUDIT-004 — Test Attestation (Reproducible Evidence)

**Status:** `PARTIALLY VERIFIED — FULL SUITE PASSED VIA SEGMENTED RUNS; MONOLITHIC RUN NOT COMPLETED`
**Tested commit:** `8d0e102bdf41456e0c1c92258f1adbd3368fb548` (parent `40382f8`)
**Branch:** `audit/ec-remediation-001`
**Date:** 2026-10-31
**Scope:** offline test attestation. No live broker, credentials, or production state touched.

---

## 1. Environment

| Item | Value |
|---|---|
| Python | 3.14.8 |
| pytest | 9.1.1 |
| pluggy | 1.6.0 |
| Platform | Linux 7.2.13-100.fc43.x86_64 (glibc 2.42) |
| Hypothesis | 6.152.9 |
| Plugins | hypothesis, cov, xdist, rerunfailures, ordering, metadata, html, seleniumbase, anyio |
| Working tree at test time | Unit 2 changes present; identical to commit `8d0e102` after commit |

---

## 2. Collection

| Stage | Collected |
|---|---|
| Baseline before remediation (`9efb1c9`) | 3603 |
| After Unit 1 (+11) and Unit 2 (+17) | **3631** |

No collection errors were observed.

---

## 3. Safety-critical tests

Command (repo root):

```
python -m pytest -q tests/unit/live/test_p0_safety.py tests/unit/live/test_risk_enforcement.py \
  tests/unit/live/test_stop_loss_policy.py tests/unit/live/test_catastrophic_protection.py \
  tests/unit/live/test_durable_audit.py tests/unit/live/test_disconnect_recovery.py \
  tests/unit/live/test_r4_restart_consistency.py tests/unit/live/test_risk_unification.py \
  tests/unit/test_t0_sizing.py tests/unit/portfolio/test_portfolio.py \
  tests/unit/portfolio/test_portfolio_risk_wiring.py tests/unit/risk/test_eigenrisk.py \
  tests/unit/risk/test_concentration_checks.py tests/unit/reconciliation/test_engine.py \
  tests/unit/test_r4_signal_fidelity.py tests/unit/test_fingerprint_verifier.py \
  tests/unit/test_r4_single_instance.py tests/unit/test_crash_recovery.py \
  tests/unit/test_restart_recovery_certification.py tests/unit/test_execution_reliability.py \
  tests/unit/test_failure_injection.py tests/unit/test_failure_storm.py \
  tests/unit/test_state_machine_verification.py tests/unit/test_supervisor.py \
  tests/unit/test_watchdog.py tests/unit/test_daily_loss.py \
  tests/unit/execution/test_events_durability.py \
  tests/unit/production_qual/test_adversarial_validation.py
```

**Result: 501 passed, 3 xfailed, 6 warnings, exit 0, 128.34s.**

---

## 4. Relevant regression tests

Command:

```
python -m pytest -q tests/unit/test_r4_signal_fidelity.py tests/unit/shadow/portfolio/ \
  tests/unit/fidelity/ tests/unit/live/test_stop_loss_policy.py \
  tests/unit/live/test_risk_enforcement.py tests/unit/production_qual/test_phase2_parity.py \
  tests/unit/research/rebalance/test_replay.py
```

**Result: 308 passed, 1 skipped, 3 xfailed, exit 0, 12.49s.**

---

## 5. Full repository suite (segmented)

A single monolithic `python -m pytest tests/ -q` was attempted twice and
aborted by the operator before completion. It is therefore **NOT RUN to
completion** and is not claimed as a pass. The equivalent coverage was
executed in bounded segments:

| Segment | Command | Result | Duration |
|---|---|---|---|
| Unit | `pytest tests/unit -q --tb=no` | **3587 passed, 2 skipped, 3 xfailed** | 375.03s |
| Integration | `pytest -q tests/integration` | **29 passed** | 2.32s |
| Property | `pytest -q tests/property` | **10 passed** | 22.51s |
| Simulation | `pytest -q tests/simulation` | **no tests collected** | — |
| Failure injection | `pytest -q tests/failure_injection` | **no tests collected** | — |

**Aggregate: 3626 passed, 2 skipped, 3 xfailed = 3631 collected. Exit 0 on every segment that contained tests.**

`tests/simulation/` and `tests/failure_injection/` contain only `__init__.py`;
there is no executable test surface there.

### Known flake

The first combined integration+property+failure-injection run produced one
failure:

```
tests/property/test_invariants.py::TestEventLedgerInvariants::test_correlation_chains_are_complete
hypothesis.errors.DeadlineExceeded: Test took 214.88ms, exceeds 200.00ms deadline
```

This is a Hypothesis wall-clock deadline, not an assertion. The test **passes
in isolation** (2.87s) and the property suite alone **passes 10/10** (22.51s).
It is recorded as a load-sensitive pre-existing flake, not a new failure.

---

## 6. Static checks

| Check | Command | Result |
|---|---|---|
| Lint | `python -m ruff check src/ tests/` | **pass** |
| Format | `python -m ruff format --check src/ tests/` | **pass (540 files)** |
| Types | `python -m mypy src/eigencapital/` | **pass (310 files)** |
| Whitespace | `git diff --check` | **pass (exit 0)** |

---

## 7. Skips, xfails, failures

- **Skipped (2):**
  - `tests/unit/production_qual/test_phase2_parity.py:460` — "Phase 2 baseline lock not yet captured".
  - `tests/unit/data/storage/test_storage_policy.py:137` — "parquet engine installed; unavailable-path not exercisable".
- **xfailed (3, strict):** the EC-AUDIT-002 invalid-SL gap tests in
  `tests/unit/live/test_stop_loss_policy.py` (`None`, negative, non-numeric).
  These document a real residual gap; they are **not** passes.
- **New failures:** none attributable to this remediation.
- **Collection errors:** none.

---

## 8. Unverified / limitations

- The monolithic full-suite command did not complete (operator-aborted); the
  segmented run is the evidence of record.
- No live broker, live credentials, or production account was contacted.
- Coverage (`--cov`, `fail_under=80`) was **not** run in this attestation.
- Timing-sensitive Hypothesis deadlines can flake under concurrent load.

---

## 9. Conclusion

The repository test surface at `8d0e102` passes when executed in segments:
3626 passed, 2 skipped, 3 documented xfails, 0 collection errors. The
monolithic run is explicitly not claimed. Static checks pass.
