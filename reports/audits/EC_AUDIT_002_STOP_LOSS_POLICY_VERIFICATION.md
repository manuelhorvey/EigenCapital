# EC-AUDIT-002 — Stop-Loss Policy and Risk-Gate Semantics Verification

**Status:** `VERIFIED — POLICY ESTABLISHED; INVALID-DATA GAP RETAINED AS RESIDUAL RISK`
**Date:** 2026-10-31
**Branch / HEAD at verification:** `audit/ec-remediation-001` (Unit 2 working tree)
**Scope:** verification + tests + documentation only. No production behavior changed.

---

## 1. Authoritative policy (verified, not assumed)

The historical claim that R4 uses signal-driven exits rather than a mandatory
fixed stop-loss is **VERIFIED**:

- `configs/production/config.toml` → `[live_risk] require_sl_on_positions = false  # R4 uses signal-based exits`
- `src/eigencapital/config.py` → `LiveRiskConfig.require_sl_on_positions: bool = False`
- `docs/production/RISK_ARCHITECTURE.md` → Gate 6: "SL required **only if** `require_sl_on_positions=true` (production: **false** — signal-based exits)"
- `src/eigencapital/live/catastrophic_protection.py` → asynchronous disaster-stop backstop; "R4's own exits remain rotation/sign-flip/regime-ride"

The actual policy flag is `require_sl_on_positions`. The directive's label
`stop_loss_required` does not exist in the codebase; no field was renamed.

---

## 2. Policy-to-implementation mapping

| Concern | Implementation | Source |
|---|---|---|
| Policy flag | `LiveRiskConfig.require_sl_on_positions` | `src/eigencapital/config.py:256` |
| Envelope derivation | `RiskEnvelope.from_config()` reads the flag | `src/eigencapital/live/risk_enforcement.py:111` |
| Gate 6 | `_check_position_protection()` | `src/eigencapital/live/risk_enforcement.py:414` |
| Gate-6 outcome | `CRITICAL` + `BlockReason.NO_SL_PROTECTION` | `risk_enforcement.py:443` |
| Loop consequence | Any `CRITICAL` → `status: BLOCKED`, no new entries | `scripts/r4_rebalance_loop.py:1839` |
| SL placement | `plan_protection()` → `SET_STOP_LOSS` → `broker.set_sl()` → `ok` recorded | `catastrophic_protection.py:84`, `scripts/r4_safety_supervisor.py:214` |
| Dry-run | intended action recorded with `dry_run=True`, no `ok` | `scripts/r4_safety_supervisor.py:217` |
| Foreign positions | never managed (R4_BOT only) | `catastrophic_protection.py:92-96` |
| Audit trail | `risk_gate_audit.jsonl`, safety `safety_tick` records | loop + supervisor |

---

## 3. Required behavior distinctions

| # | State | Current behavior | Evidence |
|---|---|---|---|
| 1 | SL required by policy | `require_sl_on_positions=True` enables Gate 6 | `test_zero_sl_is_critical` |
| 2 | SL not required by policy | production flag `false`; Gate 6 PASS "SL check disabled" | `test_production_policy_is_not_required`, `test_position_without_sl_is_allowed` |
| 3 | Position with valid SL | PASS | `test_valid_sl_passes` |
| 4 | Position without SL, policy permits | PASS | `test_position_without_sl_is_allowed` |
| 5 | Position without SL, policy requires | CRITICAL `no_stop_loss_protection`; loop blocks entries | `test_zero_sl_is_critical` |
| 6 | Missing SL key | treated as unprotected (CRITICAL when required) | `test_missing_sl_key_is_critical` |
| 7 | Invalid SL value (`None`, negative, non-numeric) | **treated as protected** — unsafe; see residual gap | xfail tests in `TestInvalidDataGap` |
| 8 | SL placement pending | not modeled as a distinct state; position remains `sl=0` until broker confirms | `test_successful_placement_then_idempotent` |
| 9 | SL placement rejected | `set_sl` returns `False`; recorded `ok=False`; not reported as protected | `test_failed_placement_is_not_reported_as_protected` |
| 10 | SL placement failure | same as rejected; no false success claim | `test_failed_placement_is_not_reported_as_protected` |
| 11 | Broker SL differs from expected | `plan_protection` repairs wider stops; already-tighter stops skipped | existing `tests/unit/live/test_p0_safety.py::TestA3DisasterStops` |

States 8–10 are collapsed into a boolean `ok` by the current architecture.
This is acceptable only because placement success is confirmed against broker
state on the next tick (idempotent plan); it does not lose the distinction
between "confirmed protected" and "not confirmed protected".

---

## 4. Blocking vs advisory classification

- **Blocking gates:** position count, drawdown, daily loss, equity floor, fingerprint, connectivity (any BLOCK/CRITICAL halts new entries in the loop).
- **Advisory-with-loop-consequence:** Gate 6. It does **not** early-exit the gate pipeline (later gates still run), but the loop treats its `CRITICAL` as `NO ENTRIES` when the policy is enabled.
- **Production:** policy disabled → Gate 6 PASS; catastrophic SL is the asynchronous backstop.

---

## 5. Tests

New file `tests/unit/live/test_stop_loss_policy.py`: **14 passed, 3 xfailed**.

The three `xfail(strict=True)` cases document the invalid-SL residual gap
(§6). If the gap is fixed, strict xfail turns into a failure, forcing the test
to be updated deliberately.

Regression suites to be recorded in the Unit 3 attestation.

---

## 6. Residual risk (retained, not silently fixed)

**R-002-A — Invalid SL values treated as protected.**
`_check_position_protection` uses `p.get("sl", 0) == 0`, so `None`, negative,
or non-numeric values are treated as protected when the policy requires SL.
Production runs with `require_sl_on_positions=false`, so the path is dormant.
Fixing it is a risk-control behavior change and requires separate
authorization. Do not fix it under a test-hardening label.

**R-002-B — Placement states not first-class.**
Pending / rejected / failed are represented by a single `ok` boolean plus
broker-state re-read on the next tick. Adequate for current idempotent
planning; a richer state machine would require an architecture change.

---

## 7. Conclusion

The stop-loss policy is correctly represented in production: R4 exits are
signal-driven, fixed SL is not mandatory, and catastrophic SL is a backstop.
Gate 6 semantics are documented and tested for both policy states. The
invalid-SL handling gap is explicit and retained as residual risk.
