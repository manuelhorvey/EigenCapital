# EC-AUDIT-008 — Unit 7: Capital Readiness Assessment

**Status:** `ASSESSED — CAPITAL INCREASE NOT AUTHORIZED`
**Branch:** `audit/ec-remediation-001`
**Based on:** `b71c5cf` (Unit 6 HEAD)
**Date:** 2026-10-31

> This assessment does **not** authorize a capital increase, a trading change, a
> policy change, or any broker action. It records whether the available evidence
> supports such a decision. The verdict is negative.

---

## 1. Mandate

Determine whether the evidence assembled in Units 1–6, together with the live
artifacts in `reports/`, supports increasing deployed capital. A capital increase
requires more than passing tests: it requires a trustworthy return series, a
current safety attestation, verified exit protection, tamper-evident execution
records, and a documented capital-scaling rule. None of those is fully present.

---

## 2. Evidence reviewed

| Source | Observation |
|---|---|
| `reports/r4_loop/last_equity.json` | `equity = 5117.15` at `2026-09-27T22:15:57Z` |
| `reports/r4_loop/daily_baseline.json` | `equity = 18177.0` at `2026-10-29T13:31:37Z` |
| `reports/r4_loop/runtime_state.json` | `daily_start = 5107.83`, `baseline_equity = 18177.0`, `peak_equity = 18176.81` |
| `reports/r4_loop/portfolio_analytics.jsonl` | equity path `5107.83 → 18176.81`; three step changes |
| `reports/r4_qualification/T0_*.json` | 7 attestations, newest `2026-09-30T05:29:29Z` |
| `reports/r4_loop/risk_gate_audit.jsonl` | `position_protection = PASS ("SL check disabled")` |
| `reports/r4_safety/safety_audit.jsonl` | final tick `DEGRADED`, `authorize_trading = false` |
| `reports/r4_loop/decisions.jsonl` | 65 executions; 45 `intent_discrepancy`; 10 watchdog escalations; 3 `t0_mismatch`; 2 `frozen`; 1 `quarantine` |
| `reports/r4_loop/supervisor_state.json` | still `"status": "running"` for dead PID 2138083 (historical artifact) |
| `configs/production/config.toml` | `require_sl_on_positions = false`; `vol_target_annual = 0.10` |
| Unit 5 report | research provenance gaps G-5-1..G-5-10 |

---

## 3. Findings

### C-7.1 — No capital-event ledger; equity path contains unexplained step changes

Between consecutive analytics snapshots the equity jumps by **+39.0%**
(2026-09-28), **+56.8%** (2026-09-30) and **+34.2%** (2026-10-12). The total path
is `5,107.83 → 18,176.81` (+255.9%) in about 33 days, against a declared
`vol_target_annual = 0.10`. A 10%-vol strategy cannot plausibly produce that path
as trading P&L. The most likely explanation is one or more capital additions, but
the repository contains **no deposit/withdrawal/capital-event record**, so the
equity path cannot be decomposed into capital contributions and returns.

Consequence: risk-adjusted return, drawdown and Sharpe cannot be computed from
the live record. Capital sizing on this basis would be unfounded.

### C-7.2 — No current T=0 attestation

The newest T=0 snapshot is `2026-09-30`. The loop ran through `2026-10-29` and
emitted `t0_validated` 96 times, all against September snapshots; **no T=0
snapshot was captured for the October sessions**. An absent T=0 file only
produces a warning (`scripts/r4_rebalance_loop.py:3056`), while a present-but-
mismatched snapshot aborts startup. Three `t0_mismatch` events are recorded
(`config_match = false`, `account_match = true`).

### C-7.3 — Stop-loss protection is disabled by policy

The production risk gate reports `position_protection = PASS ("SL check
disabled")` because `require_sl_on_positions = false`. R4's design relies on
signal exits plus an asynchronous catastrophic-SL backstop; the safety log shows
`SET_STOP_LOSS` actions with `ok = false` whose meaning (no-op vs failure) is
ambiguous. **R-002-A remains open**: if the policy is ever enabled, the current
`sl == 0` test treats `None`, negative and non-numeric values as protected.

### C-7.4 — Research evidence is not capital-grade

Unit 5 established that the sole persisted trial record (`EXP-000002`) has an
unverifiable completion hash, a missing report artifact, an unresolvable
`git_commit`, an empty `strategy_artifact_hash`, no parent lineage, a trial-count
split (6 vs 14), and a symbol-count mismatch (42/38/37). A capital decision
cannot rest on a research record whose provenance cannot be independently
verified.

### C-7.5 — Execution audit is not tamper-evident

`reports/execution_audit.jsonl` and `reports/campaigns.jsonl` (the `DurableAudit`
SHA-256 chains) are **absent**. `decisions.jsonl` is plain append-only JSONL.
Only `reports/r4_safety/safety_audit.jsonl` and its mirror are hash-chained.

### C-7.6 — Operational state is inconsistent

- `supervisor_state.json` still says `running` for a dead PID (historical
  artifact; Unit 6 fixes this for future releases, not retroactively).
- `runtime_state.json` has `daily_start = 5107.83` while
  `daily_loss.baseline_equity = 18177.0`.
- `decisions.jsonl` execution records show `diag.active_positions = 31–34`
  alongside `positions_before/after = 0–20`; the discrepancy is unexplained.
- The live history contains 45 intent discrepancies, 10 watchdog escalations
  (including a 10-hour `CONTAIN` state), 2 `frozen` events, and 1 `quarantine`.

### C-7.7 — Risk limits are absolute, not capital-scaled

Production uses absolute limits: `max_daily_loss = $250`, `max_position =
$5,000`, `equity_floor = $4,000`. At ~$18.2K equity the daily-loss cap is ~1.4%
and the per-position cap ~27%; at ~$5.1K equity they are ~4.9% and ~100%. There
is no documented rule for rescaling these limits when capital changes.

### C-7.8 — Test evidence is segmented, with timing flakes

Final run: 669 passed, 1 skipped, 3 xfailed, **2 failed** in
`tests/property/test_invariants.py` under combined load; both pass in isolation
and the property-only run is 10/10. The monolithic suite remains operator-aborted
and is not claimed as passing. Two tests are skipped, including the Phase 2
baseline lock (`tests/unit/production_qual/test_phase2_parity.py:460`).

---

## 4. Verdict

**NOT READY FOR A CAPITAL INCREASE.**

**Capital increase is NOT AUTHORIZED by this assessment.** The live record cannot
be decomposed into capital and returns, the safety attestation is stale, stop-
loss protection is policy-disabled, the execution audit is not tamper-evident,
and the research provenance is unverifiable.

---

## 5. Conditions for reconsideration (not an authorization)

1. Add a capital-event ledger (deposits, withdrawals, transfers) and reconcile it
   to the equity path; recompute returns from the reconciled series.
2. Capture T=0 attestation at every startup; make it mandatory or record an
   explicit, time-bounded risk acceptance.
3. Decide the SL policy explicitly: either enable `require_sl_on_positions` and
   close R-002-A, or formally accept signal-based exits plus async catastrophic
   SL with tests and monitoring.
4. Persist execution records in a `DurableAudit` chain; keep `decisions.jsonl`
   as a secondary log.
5. Resolve or formally scope out the Unit 5 provenance gaps.
6. Capture the Phase 2 baseline lock and run the full suite to completion in CI.
7. Define a capital-scaling policy (proportional daily-loss and position limits,
   equity floor, maximum deployment) before any increase.

---

## 6. Explicit non-actions

No broker connection was opened, no order was placed, no configuration was
changed, no capital was moved, and no historical runtime artifact was rewritten.
