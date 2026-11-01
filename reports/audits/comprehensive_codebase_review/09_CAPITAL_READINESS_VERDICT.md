# Capital Readiness Verdict

Commit reviewed: `6a7e77f`. This document answers the 12 decision questions for the capital-readiness gate.

---

## Q1. Is the architecture sound enough to operate and evolve?

**Partially.** Directory boundaries are sensible and the frozen-signal split is deliberate. But the live path is a 3,329-line script containing business logic, and three separate audit/state mechanisms coexist with no authoritative one. Operable today; not safely evolvable without extraction. → **TD-01/TD-02/TD-04; F-03, F-22.**

## Q2. Is the R4 strategy implemented faithfully to its approved specification?

**Yes.** `signal_vol_scale_reference=0.50` is the consumed divisor; `vol_target_annual=0.10` is decorative, exactly as approved in `EC-AUDIT-001` Alternative A. A fidelity guard test protects the identity. The defect is not the math but its input: the live signal includes the forming D1 bar. → **F-11.**

## Q3. Is risk control correct and enforced?

**No, with two exceptions.** Position count, notional envelope, drawdown, and daily loss are enforced and fail closed on corrupted state. But the advertised `max_absolute_weight_error` veto does not exist (record-only by design while config still claims a veto), the stop-loss gate treats invalid SL as protected, and the per-order gate is invoked with `target_orders=0`. → **F-04, F-07, F-16.**

## Q4. Is execution safe and auditable?

**Not auditable; partially safe.** Containment is good (single instance, HALT on reconciliation, supervisor backstop). Execution robustness is weak (FOK always, hard-coded deviation 10/20, ambiguous sends unresolved, partial fills treated as failures, per-cycle in-memory idempotency), and no durable decision→fill chain exists. → **F-03, F-12.**

## Q5. Can state be reconciled and reconstructed after a restart or intervention?

**No.** Reconciliation compares the broker snapshot to itself, and its result is never written; the dashboard reads a differently named file anyway. Two different starting-equity values coexist in `reports/r4_loop`. → **F-01, F-05, F-06, F-14.**

## Q6. Is the research evidence valid and reproducible?

**No.** PBO is structurally 1.0 for any input with ≥10 candidates; Holm/BH are implemented incorrectly and Holm is anti-conservative; provenance does not reproduce; the dataset universe does not match the experiment; all six cited R1–R6 artifact directories are absent. → **F-08, F-09, F-10, F-18, F-20.**

## Q7. Is the dashboard operationally truthful and secure?

**Secure enough for a loopback single-operator tool; not truthful enough to rely on.** Auth/transport design is solid, but unrealized P&L is always zero, daily-loss remaining never decreases, health is not staleness-gated, and reconciliation "CLEAN" is inferred from SL presence rather than the engine. → **F-14, F-15, F-24.**

## Q8. Is the system secure against credential and supply-chain threats?

**Adequately for local operation, not hardened.** No committed secrets; loopback bind; constant-time auth. Weaknesses: predictable default key, auth-disable env, query-token legacy, unpinned actions/dependencies, no CVE scan, unkeyed audit chain. → **F-15, F-17, F-19.**

## Q9. Is the test suite sufficient to trust changes?

**Strong breadth, weak safety-wiring coverage.** 3,644 tests, property suite stable over three runs, ruff/mypy clean, integration/failure-injection suites in CI. But no test asserts the durable audit wiring, the weight-error veto, the reconciliation caller, or the statistical invariants — which is why the critical defects are green in CI. → **Q9 evidence in `06_TESTING_AND_CI.md`; F-07, F-08, F-09.**

## Q10. Is documentation adequate for operations and handover?

**Not fully.** Useful operational docs exist (`SYSTEM_TRUTH`, dashboard/broker contracts, audit reports), but two referenced governing specs are absent, `EC-AUDIT-009` is draft/not adopted, inline comments contradict code, and multiple config claims overstate enforcement. → **F-13, F-23.**

## Q11. Are failure modes contained?

**Mostly yes.** Single-instance claim, fail-closed risk recovery, reconnect-requires-live-read, reconciliation HALT, catastrophic-SL supervisor default-on, refusal not written to the watchdog trail. Gaps: no alert for "safety disabled", ambiguous sends unresolved until the next cycle, and no durable reconciliation history. → **F-03, F-05, F-06, F-12.**

## Q12. Is the system ready for a capital increase?

**No.**

---

## Verdict

# MAJOR ARCHITECTURAL OR SAFETY WORK REQUIRED

**Capital increase: NOT AUTHORIZED.**
**Leverage increase: NOT AUTHORIZED.**
**Stop-loss gate relaxation: NOT AUTHORIZED.**
**R4 modification: NOT AUTHORIZED.**
**Research promotion to production: NOT AUTHORIZED.**

### Basis

Three capabilities required to account for capital are absent from the live path:

1. an independent equity/capital reconciliation (F-01),
2. a capital-event ledger (F-02),
3. a durable execution audit chain (F-03).

Two of the components exist in the repository but are unwired; the third (reconciliation) is structurally incapable of detecting divergence (F-05) and produces no durable record (F-06). The research layer used to justify the strategy contains two objectively invalid statistics (F-08, F-09) and non-reproducible provenance (F-10).

`reports/audits/EC_AUDIT_009_P0_1_EQUITY_RECONCILIATION.md` reaches the same conclusion independently for P0-1: `BLOCKED — BROKER STATEMENT REQUIRED`, because the available artifacts contain no capital transactions.

This is **not** a finding that EigenCapital is currently trading dangerously at its present size. Confirmed failures would have shown up as position drift, which the current comparison cannot see; the correct conclusion is that the system cannot prove agreement, not that disagreement is proven.

### Conditions for continued operation at current size

All must hold:

1. `configs/r4_safety.enabled` present and the safety supervisor running with `--live` (`scripts/start_trading.sh` default).
2. Production risk limits and `require_sl_on_positions` unchanged.
3. Frozen R4 constants unchanged.
4. Single-instance guard active; no `--force-regime` in loop mode.
5. Operator verifies reconciliation manually against the broker at least daily until F-05/F-06 are fixed.

### Conditions to lift the verdict

Minimum bar for `SOUND WITH MATERIAL REMEDIATION REQUIRED`:

- F-01, F-02, F-03, F-05, F-06 closed with tests.
- F-04 and F-07 closed or explicitly accepted in writing with a compensating control.
- F-08 and F-09 corrected and affected research verdicts re-derived; F-10 artifacts restored or claims withdrawn.
- F-14 corrected so the dashboard cannot display a false-healthy state.

Minimum bar for `READY WITH MINOR REMEDIATION` (capital increase):

- All of the above, plus an independent external review of the live cycle, a 30-day reconciliation record with zero unexplained deltas, and an exercised disaster-recovery drill with evidence.
