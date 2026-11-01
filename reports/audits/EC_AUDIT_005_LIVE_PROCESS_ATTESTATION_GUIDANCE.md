# EC-AUDIT-005 — Unit 4: Live-Process Attestation Guidance

**Status:** `COMPLETE — GUIDANCE DELIVERED; NO LIVE PROCESS WAS RUNNING OR CHANGED`
**Branch:** `audit/ec-remediation-001`
**Based on:** `4861dc3` (Unit 3 HEAD)
**Date:** 2026-10-31
**Scope:** documentation and read-only inspection only.

---

## 1. Objective

Document how to establish, from evidence:

1. what live process is running and that it is the only one;
2. which code and configuration it loaded;
3. which campaign boundary and broker account it is bound to;
4. whether its evidence chain is intact;
5. when the runtime identity must be treated as **unattested**.

No process was started, stopped, restarted, or reconfigured. No broker order was
submitted. R-002-A remains open.

---

## 2. Deliverables

| Artifact | Change |
|---|---|
| `docs/production/LIVE_PROCESS_ATTESTATION.md` | New guidance: six-question model, artifact map, 8-step procedure, pitfalls, non-goals |
| `docs/production/OPERATIONS_RUNBOOK.md` | Corrected stale `loop.pid` → `supervisor.pid`, `loop.log` → `loop_stdout.log`; added launcher-dependent path note and cross-link |

---

## 3. Method

Static inspection of:

- `scripts/r4_rebalance_loop.py` — startup gates, single-instance claim, `audit()`, T=0 validation;
- `src/eigencapital/live/supervisor.py` — PID/claim/health semantics;
- `src/eigencapital/live/durable_audit.py` — hash-chain verification;
- `src/eigencapital/production_qual/fingerprint_verifier.py` — five-component fingerprint;
- `scripts/start_trading.sh`, `scripts/r4_daily.sh` — launch modes and log destinations;
- read-only inspection of existing `reports/r4_loop/` artifacts.

Current observed state (read-only): **no `r4_rebalance_loop` process running**,
`supervisor.pid` absent, 7 `T0_*.json` files present.

---

## 4. Findings

### F-4-1 — Runtime identity is multi-source, with no single attestation artifact

Identity is distributed across `supervisor.pid`, `supervisor_state.json`,
`loop_health.json`, `decisions.jsonl` startup events, the latest `T0_*.json`,
and the fingerprint verifier. A single file cannot answer all six questions.
The guidance defines the required cross-check.

### F-4-2 — `supervisor_state.json.status` is not authoritative after exit

`ProcessSupervisor.release()` removes `supervisor.pid` and writes
`loop_health.json` with `alive: false`, but does **not** update
`supervisor_state.json`. The current tree demonstrates the hazard:
`supervisor_state.json` records `"status": "running"` for a PID that is not
alive, while `loop_health.json` records `"alive": false`. An operator trusting
the status field alone would wrongly conclude the loop is running.
**Mitigation in guidance:** always confirm with `kill -0` and a fresh
`loop_health.json` timestamp. A code fix is a candidate for Unit 6, not done here.

### F-4-3 — `decisions.jsonl` is append-only, not tamper-evident

`audit()` appends plain JSONL. Only `reports/execution_audit.jsonl` and
`reports/campaigns.jsonl` (plus `.mirror` copies) are SHA-256 hash-chained via
`DurableAudit`. The guidance explicitly forbids claiming tamper evidence for
`decisions.jsonl`.

### F-4-4 — T=0 validation is optional at startup

If no `T0_*.json` exists, the loop logs a warning and proceeds without the
check (`scripts/r4_rebalance_loop.py:3056`). The guidance classifies this as a
material attestation gap, not a pass.

### F-4-5 — Runbook path drift (corrected)

`OPERATIONS_RUNBOOK.md` referenced `reports/r4_loop/loop.pid` and
`reports/r4_loop/loop.log`, neither of which is written by the supported
launchers. Corrected to `supervisor.pid` and `loop_stdout.log`, with an explicit
note that `r4_daily.sh` writes `reports/r4_loop/runs/YYYY-MM-DD.log`.

### F-4-6 — Guard-bypass modes and the daily wrapper

`--flatten` and `--verify-config` intentionally bypass the single-instance
claim; `r4_daily.sh` takes a separate `flock` on `reports/r4_loop/.lock` and
skips (exit 0) when the live loop owns the claim. A skipped daily run is normal
and must not be read as a failed cycle. A duplicate loop exits **75**.

---

## 5. Residual risks / recommendations (not implemented)

| ID | Recommendation | Owner unit |
|---|---|---|
| R-4-A | Make `release()` update `supervisor_state.json.status` atomically so status files agree with `loop_health.json` | Unit 6 candidate |
| R-4-B | Either hash-chain `decisions.jsonl` or label it non-tamper-evident in the evidence index | Unit 6 candidate |
| R-4-C | Decide whether missing T=0 should fail closed (policy decision, not a code default) | governance |
| R-4-D | Provide a single machine-readable attestation command that emits the six-question result | Unit 6 candidate |

These are recommendations only. None were implemented under Unit 4.

---

## 6. Limitations

- No live process was running during this unit, so this report is **guidance
  plus static verification**, not an attestation of a live runtime.
- `/proc/<pid>/environ` readability depends on host permissions; the guidance
  records the consequence (configuration environment becomes unattested).
- Timestamps assume a trusted system clock.

---

## 7. Conclusion

Unit 4 delivers an evidence-based, fail-closed procedure for attesting a live
process, corrects two stale operational paths, and records four follow-up
recommendations. It does not attest any running process and does not authorize
trading or capital changes. R-002-A remains open.
