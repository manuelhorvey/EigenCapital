# R4 P0 Safety Remediation — Implementation & Evidence Report

**Campaign:** R4 P0 Safety Remediation & Controlled Resume
**Plan (preregistered):** `R4_P0_SAFETY_REMEDIATION_PLAN.md` · **Baseline:** `d16148e`, identity `aaab6c00dc05…b2beb`
**Machine-readable evidence:** `reports/r4_safety/p0_remediation_evidence.json`

---

## Result summary

| Gate | Result |
|---|---|
| Full unit regression | **2300 passed**, 1 skipped (pre-existing skip) |
| P0 acceptance tests (A1–A11) | **44/44 passed** (`tests/unit/live/test_p0_safety.py`) |
| Freeze guard | 44/44 passed |
| Frozen-path diff | empty (`r4_manifest.py`, strategy/risk sections of `config.py`, `r4_rebalance_loop.py`, production `config.toml`) |
| Lint / types on new code | ruff clean · mypy clean |

## Components delivered (all NEW files)

| Component | File | Notes |
|---|---|---|
| Build pinning | `src/eigencapital/live/build_pinning.py` | build-id = sha256(head‖manifest‖config-fp‖loop-script); fail-closed |
| Attribution/quarantine | `src/eigencapital/live/position_attribution.py` | every position classified; only magic=20260825 counts toward capacity; foreign presence ⇒ quarantine (no new entries, self-rotation allowed); attestation derived from deals, never asserted zero |
| Catastrophic protection | `src/eigencapital/live/catastrophic_protection.py` | ≥2×ATR14 disaster stops with 1% floor; idempotent plan (restart-safe); flatten-with-retry → FAILED_HALT escalation; scoped to R4 tickets only; kill-switch flag file |
| Watchdog | `src/eigencapital/live/watchdog.py` | severity-tiered ladder NORMAL→DEGRADED→BLIND→CONTAIN (sticky)→RECONCILING→RESUMED/HALTED; reconnect requires reconciliation before resume |
| Durable audit | `src/eigencapital/live/durable_audit.py` | hash-chained JSONL + mirror copy; tamper detection verified by test |
| Supervisor | `scripts/r4_safety_supervisor.py` | orchestrates all layers; DRY-RUN default; live mutations need `--live` AND flag file `configs/r4_safety.enabled`; refuses to start on build-pin failure |

## Acceptance criteria evidence

| # | Criterion | Evidence |
|---|---|---|
| A1 | Zero foreign contamination | capacity counts R4-only; 8 foreign positions cannot block the bot's own rotation; contamination blocks new entries (`TestA1*`, 5 tests) |
| A2 | Zero unverified builds | pin passes on baseline; fails on head drift / manifest drift / fingerprint drift; supervisor exits(2) on failure |
| A3 | No unprotected positions | boundary = max(2×ATR14%, 1%); direction-aware; missing/wider SLs repaired; tighter SLs left alone |
| A4 | No trading on untrusted state | dead process / stale trail / failed equity read / unreachable broker ⇒ trading authorization false (parametrized injection matrix) |
| A5 | Independent watchdog containment | persistent abnormality ⇒ CONTAIN (sticky); flatten retried across passes; exhausted retries ⇒ FAILED_HALT |
| A6 | Unambiguous ownership | three-class taxonomy; unknown magics quarantined and invalidate attestation |
| A7 | Broker-state evidence per decision | snapshot hash bound into watchdog decisions and supervisor ticks |
| A8 | Restart cannot duplicate | protection plan is idempotent: applied SLs yield zero further actions |
| A9 | Reconnect needs reconciliation | resume only via explicit `complete_reconciliation(clean=True)`; failed reconciliation ⇒ HALTED (manual review) |
| A10 | Durable, verifiable artifacts | chain verify/tamper/mirror/reopen tests green |
| A11 | Injections produce BLOCK/HALT/FLATTEN | matrix covers process-death, staleness, equity-read failure, disconnect, contaminated book, unknown owner |
| A12 | Resume gate | checklist below — deliberately manual |

## Live-broker evidence at report time (read-only exports)

- Foreign book **closed by operator** since triage: 0 magic≠20260825 positions remain; balance realized $6,741.77 (attribution ledger: UNATTRIBUTED_MAGIC_0 realized +$4,529.35 across 47 deals vs R4_BOT −$3.67 across 90 — attestation honestly flags these as unattributable rather than asserting zero).
- Remaining live exposure: 9 bot positions, **all sl=0**, and 9 > 8 is an active capacity breach.
- Dry-run supervisor tick against this state correctly produced: BLIND (stale loop trail), authorize_trading=false, breach detected, and an idempotent 9-action disaster-stop plan (e.g., AUDNZD SL 1.18683 = 2×ATR below entry).

## Controlled-resume checklist (A12 — manual gate)

1. Operator closes or formally accepts the 9>8 breach down to ≤8 bot positions.
2. Deployed runtime switched to a launcher that runs `verify_pinned_build` before the frozen loop starts; build-id stamped into cycle records.
3. Supervisor running alongside (`--loop --interval 60`), dry-run first for one full session, then flag-file enabled for protection actions only.
4. Fresh T0 snapshot taken after reconciliation; PQ attribution regenerated from deal history via `ledger_from_deals` (attestation_valid must be true).
5. Adversarial re-audit of this layer (failure injections re-run against live wiring).
6. Only then does the $5K qualification clock restart.

## Explicitly deferred

Entry-quality research (rank/Q5 concentration), cadence correction, any TP/trail/time-cap economics — unchanged research-only status per `improvement_ranking.json`. The economic exit architecture of frozen R4 remains untouched.
