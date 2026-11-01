# Independent Verification Report — Phase 1 Remediation

**Branch:** `audit/comprehensive-remediation-001` (23 commits, on `origin/main` ancestry)
**Branch pushed:** Yes (`git push origin audit/comprehensive-remediation-001`)
**CI status:** `main` green — run `41277592309` (success)
**Draft PR:** Not opened (no GitHub auth/token available)
**Draft PR compare URL:** https://github.com/manuelhorvey/EigenCapital/compare/main...audit/comprehensive-remediation-001?expand=1
**Full test suite:** `pytest tests/unit tests/property tests/integration tests/failure_injection` → **3739 passed, 2 skipped** (0 failures)
**Date:** 2026-11-01

---

## Scope

Independent verification of the 11 implemented Phase-1 findings:

| Finding | Commit | Severity |
|---|---|---|
| F-04 | `18e254b` | High |
| F-08 | `6e707ca` | High |
| F-09 | `174b5a1` | High |
| F-11 | `c91a8d9` | High |
| F-14 | `dfb99ea` | Medium |
| F-15 | `e0fec4c` | Medium |
| F-19 | `678433b` | Medium |
| F-20 | `63c2cbe` | Medium |
| F-21 | `7db75db` | Medium |
| F-22 | `7998201` | Medium |
| F-23 | `55ebb33` | Low |

Each finding has a supporting evidence doc under `reports/audits/remediation/`.

---

## Verification Decisions

| Finding | Decision | Rationale |
|---|---|---|
| F-04 | VERIFIED WITH LIMITATIONS | `p.get('sl',0)==0` replaced with `_has_valid_stop_loss()` fail-closed classification (None/negative/non-numeric/wrong-side/unknown → unprotected). Three strict xfails removed and replaced with passing tests. **Limitation:** gate remains **disabled** (`require_sl_on_positions=false`) by design — validation semantics fixed only, gate enablement is a separate operator decision. No production/risk/broker change. |
| F-08 | VERIFIED WITH LIMITATIONS | Fixed-split PBO (structurally constant 1.0) replaced with CSCV over a performance time-series matrix. Summary-only IS/OOS input returns `UNSUPPORTED_INPUT` (no fabricated value). Hand-calculation cases (0.0 no-overfit, 1.0 full-reversal) verified. **Limitation:** affected research verdicts (R3 PBO 1.000) not yet re-derived — blocked on raw per-period return matrix (F-10); no historical report edited. |
| F-09 | VERIFIED WITH LIMITATIONS | Holm (forward cumulative max in rank order) and BH (backward cumulative min) corrected. Rank↔index mapping restored. Invalid/non-finite/out-of-range p-values fail closed. Hand-calculated values + FWER/FDR bound properties + Hypothesis property tests added. **Limitation:** affected research verdicts not yet re-run. |
| F-11 | VERIFIED WITH LIMITATIONS | `copy_rates_from_pos(..., 0, bars)` → `(..., 1, bars)` in loop and live-orders script, so the forming D1 bar is excluded. R4 maths/lookbacks/sizing/caps unchanged. **Limitation:** no backtest/live signal comparison performed; staleness TTL may cause late-Monday/holiday cycle skips (conservative, documented). |
| F-14 | VERIFIED WITH LIMITATIONS | MT5 `positions_get()` moved before `shutdown()` (unrealized_pnl real, was always 0). `daily_loss_remaining` decrements from baseline (`max(0, max_daily_loss - |daily_pnl|)`). Health staleness TTL (300s): stale `alive=true` → HALTED. Reconciliation missing engine record → `UNKNOWN`, never `CLEAN` from SL presence. **Limitation:** reconciliation-record portion blocked pending F-06 (loop doesn't yet write engine record). |
| F-15 | VERIFIED WITH LIMITATIONS | Missing/default API key → 503 fail-closed; `DASHBOARD_ALLOW_INSECURE_DEV=1` explicit dev opt-in (warned once); startup warns on `DASHBOARD_DISABLE_AUTH=1`; `?token=` WebSocket transport removed (H-11); subprotocol + Bearer remain. **Limitation:** `VITE_API_KEY` still embeds key in frontend bundle — frontend architecture decision pending. |
| F-19 | VERIFIED WITH LIMITATIONS | Actions SHA-pinned (checkout/setup-python/setup-node/codecov), `permissions: contents: read`, pip-audit step added, Python 3.14 added to matrix + trove classifier. **Limitation:** cannot execute GitHub Actions offline; lockfile/hashes for operational installs tracked as follow-up (not fabricated). |
| F-20 | VERIFIED WITH LIMITATIONS | `ExperimentRecord` is now a frozen dataclass with defensively-copied nested dicts; transitions return new records replacing stored record; `save()`/`delete()` refuse frozen/finalized records (append-only). Dead `_MODIFIABLE_BEFORE_FREEZE` removed. **Limitation:** hash verification on `repository.load()` is part of F-10 (blocked on missing artifacts); promotion checklist documented as out of scope. |
| F-21 | VERIFIED WITH LIMITATIONS | `executor.py` raises `RuntimeError` on import unless `EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS=1`; tests set the flag. Build-time exclusion of `eigencapital.research*` already present in pyproject. **Limitation:** remaining research executors (r2/r3/r4) are research tooling consumed by research campaigns/scripts, not the live loop — moving them wholesale deferred to avoid scope creep. |
| F-22 | VERIFIED WITH LIMITATIONS | New `eigencapital.core.state_schema` framework: explicit `schema_version`, required-field validation, fail-closed on unknown version, legacy passthrough/migration with no data loss, atomic writes. Wired into `daily_baseline.json` and `supervisor_state.json`. **Limitation:** remaining `r4_loop/*` files not yet versioned — framework ready for follow-up. |
| F-23 | VERIFIED WITH LIMITATIONS | Stale loop comments (`# 1500`, `# 8`) removed; absent governing specs (`SYSTEM_SPECIFICATION.md`, `domain_contracts.md`) labelled historical references only; EC-AUDIT-009 stated as draft/not adopted/gate not passed. **Limitation:** no new governing specs authored (avoid unverified contracts); EC-AUDIT-009 not adopted. |

---

## Test Results Summary

| Suite | Result |
|---|---|
| Full CI-equivalent (`tests/unit tests/property tests/integration tests/failure_injection`) | **3739 passed, 2 skipped** |
| Dashboard suite | 168 passed |
| Live suite | 404 passed |
| Analytics suite | 191 passed |
| Research suite | 791 passed |
| Core suite | included in full suite |
| Security audit suite | 14 passed |

The 2 pre-existing skips and any xfails (Gate-6 under F-04) are unchanged and unrelated to this remediation. Two test pollution bugs introduced during remediation (direct `os.environ` mutation in dashboard auth tests; stale `_DEFAULT_API_KEY` reference) were found and fixed during verification.

---

## Unintended Behaviour Changes Check

None found:
- R4 strategy mathematics, lookbacks, thresholds, sizing, caps, universe, regime, rebalance frequency — unchanged (F-11 only changes which bar index is consumed; `MAX_POSITION_USD`/`MAX_CONCURRENT` comments only, values unchanged).
- Production risk limits — unchanged.
- Stop-loss gate enablement — unchanged (still `false`).
- Broker behaviour — unchanged (F-11 only affects bar selection, not execution).
- Capital/leverage — unchanged.
- Dashboard read-only guarantee — preserved (all GET/HEAD only).

---

## Remaining Limitations (findings not CLOSED)

| Finding | Remaining |
|---|---|
| F-04 | Independent review; gate enablement is separate operator decision |
| F-08 | Research verdict re-derivation blocked on raw return matrix (F-10) |
| F-09 | Research verdict re-run pending |
| F-11 | Independent review; staleness nuance production re-check |
| F-14 | Reconciliation-record portion blocked pending F-06 (loop must write `reconciliation_state.json`) |
| F-15 | Frontend `VITE_API_KEY` embedding — separate frontend architecture decision |
| F-19 | Cannot execute GitHub Actions offline; lockfile/hashes follow-up |
| F-20 | Hash verification on load (F-10); promotion checklist out of scope |
| F-21 | Remaining research executors not moved (scope-limited) |
| F-22 | Remaining `r4_loop/*` files not yet versioned |
| F-23 | EC-AUDIT-009 not adopted; no new governing specs |

No finding is marked `CLOSED`. All are `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION` → now `VERIFIED WITH LIMITATIONS` where verified.

---

## Next Safe Implementation Units

The following units can proceed without broker behaviour changes, live-path integration, capital changes, risk-limit changes, or R4 changes, and without formal decisions:

| Priority | Unit | Findings | Rationale |
|---|---|---|---|
| 1 | Research repository hash verification on load | F-10 (verification part) | High severity P1; isolated research change; artifact restoration remains blocked |
| 2 | Dashboard snapshot cache / single-worker docs | F-24 | Now unblocked (depends on F-14 which is done); read-only consumer fix |
| 3 | EventLedger fixture implementation (no live wiring) | F-02 (fixture part) | Safe with synthetic fixtures; live wiring remains unauthorized |
| 4 | Remaining `r4_loop/*` schema versioning | F-22 (extension) | Uses existing `state_schema.py` framework |

**Recommended next unit: F-10 hash verification on load** — it is high severity, isolated to the research repository, touches no live path, and has a clear acceptance criterion (load rejects tampered hash).

---

## Restrictions Preserved

- F-01: **blocked** pending broker statement (no inference from snapshots).
- F-02/F-03/F-05/F-06/F-16: **not wired** into live path (unauthorized).
- F-07/F-10/F-12/F-13/F-17/F-18: **pending formal decisions** (not implemented).
- R4 strategy invariants, broker behaviour, production risk limits, capital, leverage — **unchanged**.
- Capital readiness: **NOT READY — CAPITAL INCREASE NOT AUTHORIZED.**

---

## PR Status

The branch `audit/comprehensive-remediation-001` is pushed and ready for a Draft PR (base `main`, head `audit/comprehensive-remediation-001`, title "Comprehensive audit remediation — Phase 1"). It cannot be opened or merged in this environment (no GitHub auth/token). Do not merge.
