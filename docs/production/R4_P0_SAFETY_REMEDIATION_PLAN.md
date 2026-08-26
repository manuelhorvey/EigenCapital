# R4 P0 Safety Remediation & Controlled Resume — Campaign Plan (Preregistered)

**Status:** ACTIVE · **Baseline:** git `d16148e`, frozen identity `aaab6c00dc05…b2beb` (44/44 freeze tests)
**Predecessor evidence:** `reports/r4_economics_audit/` (forensic audit; PAUSE_REQUIRED verdict)
**Scope rule:** remediation implements **safety and operational-integrity infrastructure only**. R4 entry/exit economics remain frozen. Entry-quality research (Q5 concentration, cadence) is explicitly OUT OF SCOPE for this campaign.

---

## Architectural principle

> R4 keeps its economic exit logic (rotation / sign-flip / regime-ride, no economic SL/TP).
> An **independent catastrophic-loss layer** is added whose sole purpose is containment of
> abnormal loss. It is judged on containment criteria, never on expectancy.

## Components (all NEW files; frozen paths untouched)

| # | Component | File | Purpose |
|---|---|---|---|
| C1 | Build pinning | `src/eigencapital/live/build_pinning.py` | Guarantee the running code is the audited commit/config; stamp build-id into every audit record |
| C2 | Attribution & quarantine | `src/eigencapital/live/position_attribution.py` | Magic-based classification; foreign positions can never consume R4 capacity or be misattested; attestation derived from data (never asserted zero) |
| C3 | Catastrophic protection | `src/eigencapital/live/catastrophic_protection.py` | ≥2×ATR14 disaster stops on R4-owned positions + flatten-with-retry; kill-switch-by-default |
| C4 | Watchdog | `src/eigencapital/live/watchdog.py` | Independent blind-window detection (dead process, stale audit trail, failed equity reads, bridge down) with escalation ladder ending in containment |
| C5 | Durable audit | `src/eigencapital/live/durable_audit.py` | Hash-chained JSONL records + mirror copy; tamper-evident |
| C6 | Supervisor | `scripts/r4_safety_supervisor.py` | Orchestrates C1–C5 around the frozen loop; dry-run by default; live actions gated behind flag file |

## Acceptance criteria → verification map (preregistered before implementation)

| # | Hard criterion (from campaign directive) | Verified by |
|---|---|---|
| A1 | Zero foreign-position contamination | `test_capacity_counts_only_r4` · `test_foreign_positions_cannot_consume_capacity` · `test_contamination_blocks_new_entries` |
| A2 | Zero unverified build execution | `test_build_pin_passes_on_baseline` · `test_build_pin_fails_on_head_drift` · `test_build_pin_fails_on_manifest_drift` · supervisor refuses to start (integration) |
| A3 | No position unprotected beyond safety boundary | `test_disaster_stop_at_least_2atr` · `test_disaster_stop_direction_aware` · `test_plan_sets_missing_sl` · `test_plan_skips_already_protected` |
| A4 | No trading after stale/disconnected/untrusted state | `test_stale_trail_beyond_threshold_is_blind` · `test_failed_equity_read_is_untrusted` · `test_blind_state_blocks_authorization` |
| A5 | Independent watchdog detects & contains dead/hung process | `test_dead_process_escalates_to_contain` · `test_contain_issues_flatten_with_retry` · `test_retry_until_flat_or_halt` |
| A6 | Every position has unambiguous owner/classification | `test_every_position_receives_a_class` · `test_unknown_magic_is_quarantined_not_silently_owned` |
| A7 | Every risk decision carries broker-state evidence | `test_decision_records_broker_snapshot_hash` |
| A8 | Restart cannot duplicate orders | `test_idempotent_protection_plan` (SL set on ticket = single logical action; re-run yields zero new actions) |
| A9 | Reconnect requires reconciliation before resume | `test_reconnect_without_reconciliation_stays_halted` · `test_reconciliation_clears_halt_only_when_clean` |
| A10 | Audit artifacts durable & hash-verifiable | `test_chain_verifies` · `test_tamper_detected` · `test_mirror_written` |
| A11 | P0 failure injections produce BLOCK/HALT/FLATTEN | injection matrix in `test_failure_injection_matrix` |
| A12 | $5K resume only after all above pass | Resume checklist section in remediation report; not automatable here |

## Kill-switch discipline

Live broker mutations (SL placement, flatten) require flag file `configs/r4_safety.enabled`.
Default mode is DRY-RUN: full decision pipeline executes, actions are logged, nothing is sent.

## Out of scope (explicitly deferred)

Entry filters, cadence change, TP/trailing research, capital promotion — all remain
research-only per `improvement_ranking.json` until this campaign completes an adversarial
re-audit.
