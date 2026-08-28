# EigenCapital Phase Alignment

Audit date: 2026-08-27
Last updated: 2026-08-28 (audit resolution pass)

## Phase 0: Research / Strategy Foundation

Status: ✅ COMPLETE.

Evidence: broad research modules, campaign artifacts, R4 frozen manifest, validation tooling, cost models, walk-forward and multiple-testing support. R4 live calculation is inline in `scripts/r4_rebalance_loop.py` — research-production equality depends on tests and parity validation (22/22 parity tests passing).

## Phase 1: Production Hardening / $5K Qualification

Status: ✅ COMPLETE (all conditions met as of 2026-08-28).

Previously blocking conditions — all now resolved:
- ~~Order timeout/idempotency~~ → 30s ThreadPoolExecutor timeout on `order_send()`
- ~~Live reconciliation independence~~ → Order intents persisted before execution, reconciled after
- ~~Duplicate live order path~~ → `r4_live_orders.py` quarantined
- ~~Event-ledger integration~~ → Config fingerprint fixed, correlation IDs standardized
- ~~Config semantics duplication~~ → Startup validation catches inconsistencies
- ~~Process supervision atomicity~~ → Supervisor uses temp + fsync + os.replace
- ~~State machine invariants~~ → Documented on Watchdog + DisconnectRecovery

Evidence: 2,426+ passing tests, risk gates, fingerprint checks, T=0 validation, watchdog, daily loss tracking, position attribution, catastrophic protection, P&L reconciliation, multi-factor foreign detection, pending order capacity, and comprehensive documentation.

## Phase 2: Live Economic Validation

Status: 🟢 ACTIVE — ready with conditions.

R4 should continue running as the control experiment only if changes are limited to non-contaminating safety/evidence infrastructure. Do not alter R4 signal, universe, cadence, sizing, or exit logic. The highest-value Phase 2 output is untouched live evidence over time.

Safety infrastructure changes during Phase 2 (non-contaminating):
- Reconciliation P&L check (audit trail improvement only)
- Foreign position multi-factor detection (more robust, doesn't affect R4)
- Evidence correlation IDs (better traceability)
- Watchdog trail age from JSON (more robust)
- Fingerprint verifier caching (performance only)

## Phase 3: Controlled Capital Scaling

Status: Blocked until Phase 2 evidence (30+ days) confirms R4 edge.

Phase 3A prerequisites (after Phase 2):
- Implement P1-005: Catastrophic SL pre-trade placement (or accept risk buffer)
- Extract main loop into orchestrator class (testability)
- Consolidate error handling patterns
- Build canonical event store and read model

## Phase 4: Production Scale / Capacity

Status: Future.

First likely bottleneck: operational correctness (execution idempotency, reconciliation, event queryability, process supervision). File-based evidence will become limiting for operations dashboards and historical reconstruction.

## Phase 5: Continuous Research & Governance

Status: Partially present, defer expansion.

Hypothesis registry, campaigns, freeze manifests, and validation methods exist. Future ML/research infrastructure should wait for Phase 2 evidence to identify concrete prediction targets and should remain isolated from R4.

## Mandatory Governance

- R4 signal: MUST-FREEZE.
- R4 config/fingerprints: MUST-FREEZE.
- R4 manifest identity: MUST-FREEZE.
- R4 monitoring/reconciliation/dashboard: SAFE only if read-only and unable to alter signal decisions.
- ML/research infrastructure: CONDITIONAL; must be isolated from R4 and promoted only through separate campaigns.
- Alternate live scripts: QUARANTINED (`r4_live_orders.py` cannot submit orders).
