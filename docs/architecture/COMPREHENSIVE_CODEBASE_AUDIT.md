# EigenCapital Comprehensive Codebase Audit

Audit date: 2026-08-27
Audited HEAD: `6d6a3e21eee1a0c9241808a0f9c609f5121f3e3d`

## Executive Verdict

EigenCapital is a credible foundation for Phase 2 live economic validation, but not yet a production-scale trading platform. The strongest parts are the freeze discipline around R4, extensive tests, explicit risk envelopes, broker-authoritative risk checks, daily loss tracking, watchdog logic, and evidence-oriented culture. The weakest parts are live execution idempotency/timeouts, independent reconciliation, duplicated production-capable order paths, configuration semantic duplication, non-enforced type checking, and fragmented evidence storage.

Phase 2 can continue under strict conditions: do not optimize R4, do not change its signal/cadence/universe/sizing/exit behavior, and prioritize only safety/evidence infrastructure that does not contaminate the control experiment.

## Ground Truth

- Branch: `main`.
- HEAD: `6d6a3e21eee1a0c9241808a0f9c609f5121f3e3d`.
- Start status: clean.
- Python: 3.14.7.
- Source modules: 248.
- Tests collected: 2,511.
- Test result: 2,510 passed, 1 skipped, 16 warnings.
- Ruff: passed.
- Mypy: failed with 170 errors in 49 files; CI ignores failure.
- Production config: `configs/production/config.toml`.
- Active campaign in live loop: `R4-5K-20260827`.
- R4 manifest identity: `aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb`.
- Live risk fingerprint: `ee9324293336b827770844ee5e90a371bd6f2d757ba5f0514b3201ea980177ec`.
- Current full config fingerprint observed: `32fbeadcab9a3a14...`.

## What Is Genuinely Production-Grade

- R4 manifest identity is deterministic and guarded by tests.
- Startup and per-cycle fingerprint checks exist in the canonical rebalance loop.
- Risk enforcement is broker-authoritative for account, position count, drawdown, daily loss, equity floor, and fingerprint state.
- Daily loss tracker persists baseline and handles restart/midnight behavior.
- Watchdog state machine has sticky containment semantics.
- Foreign position attribution exists and classifies every position.
- Test suite is broad and includes failure injection, property tests, endurance, crash recovery, parity, and production qualification tests.
- Durable hash-chained audit implementation exists and has mirror support.

## What Is Only Apparently Production-Grade

- Reconciliation: the engine can detect mismatches when given independent states, but the live loop currently constructs internal positions from broker positions, so several checks cannot detect real internal-vs-broker divergence.
- Event ledger: implemented and tested but not the canonical live event stream; config fingerprint currently falls back to `"unknown"`.
- Process supervision: a `ProcessSupervisor` exists and is tested, but the primary live script does not visibly claim it, and deployment is shell-based rather than service-supervised.
- Broker abstraction: `TradingProvider` exists, but the live rebalance loop directly imports and uses `mt5linux.MetaTrader5`.
- Partial fills: components and tests exist, but live `execute_orders()` still treats the immediate `order_send` result as the execution lifecycle.

## Architecture Findings

ID: EC-AUD-001
Severity: P0
Subsystem: Execution
Location: `scripts/r4_rebalance_loop.py::execute_orders`, `docs/production/FAILURE_RECOVERY_MATRIX.md`
Problem: Live order submission has no hard timeout or idempotency key.
Evidence: `execute_orders()` calls `mt5.order_send(request)` synchronously with retry; failure matrix still lists hung `order_send` as an open gap.
Why it matters: A hung broker call freezes the loop while exposure remains unmanaged.
Failure scenario: MT5 bridge accepts the call but never returns; watchdog evidence trail goes stale only after the process stops writing, while the call stack cannot reconcile or flatten.
Current behavior: Retry handles returned failures, not hung calls or duplicate uncertainty after timeout.
Expected behavior: Every order has a client idempotency key, bounded call time, and post-timeout broker reconciliation before further orders.
Recommended action: Implement timeout/idempotency wrapper and halt-to-reconcile on uncertain submission.
Implementation complexity: Medium
Risk of changing it: Medium
Dependencies: Broker provider abstraction, reconciliation, event ledger
Tests required: Hung call, duplicate retry, accepted-after-timeout, reconnect reconciliation
Phase: Phase 2 safety, Phase 3 blocker

ID: EC-AUD-002
Severity: P0
Subsystem: R4 Frozen Boundary
Location: `scripts/r4_rebalance_loop.py`, `scripts/start_trading.sh`
Problem: `--force-regime` can bypass the frozen R4 regime gate.
Evidence: `compute_r4_signal(..., force_regime=True)` sets `regime_on = True`; startup script forwards `--force-regime`.
Why it matters: This can contaminate Phase 2 evidence.
Failure scenario: Operator starts live loop with forced regime during an off-regime period and creates trades not produced by frozen R4.
Current behavior: CLI flag is available in the production script.
Expected behavior: Forced regime is dry-run only or requires explicit governed override artifact.
Recommended action: Disable for live execution or make it fail closed unless dry-run plus change-control marker exists.
Implementation complexity: Low
Risk of changing it: Low
Dependencies: Startup script, runbook
Tests required: live force rejected, dry-run force allowed
Phase: Phase 2

ID: EC-AUD-003
Severity: P0
Subsystem: Execution / Governance
Location: `scripts/r4_live_orders.py`
Problem: Alternate production-capable MT5 order script duplicates R4 signal/execution logic.
Evidence: File imports `mt5linux`, defines `compute_r4_signal`, parses `--force-regime`, and calls `order_send`.
Why it matters: It can bypass the canonical safety/evidence stack.
Failure scenario: Operator runs the older script directly; orders are placed without current T=0 validation, reconciliation, and evidence orchestration.
Current behavior: Script remains tracked and executable.
Expected behavior: One canonical production order path.
Recommended action: Remove, quarantine, or turn into a wrapper that delegates to the canonical loop and safety gates.
Implementation complexity: Low
Risk of changing it: Low
Dependencies: Operator runbooks
Tests required: script cannot submit outside canonical path
Phase: Phase 2

ID: EC-AUD-004
Severity: P1
Subsystem: Reconciliation
Location: `scripts/r4_rebalance_loop.py` and `src/eigencapital/reconciliation/engine.py`
Problem: Live reconciliation is not independent.
Evidence: `BrokerState.positions` and `InternalState.positions` are both built from the same `pos_list` from `mt5.positions_get()`.
Why it matters: Reconciliation can say "RECONCILED" even if intended orders, fills, or strategy state drifted.
Failure scenario: A target order fails or partially fills; on the next cycle internal state is reconstructed from broker state and mismatch disappears.
Current behavior: Broker-vs-broker-derived comparison.
Expected behavior: Broker state compared to independent intended order/fill/event ledger.
Recommended action: Persist intended decisions/orders and reconcile broker tickets/fills against that ledger.
Implementation complexity: Medium
Risk of changing it: Medium
Dependencies: Event ledger, execution lifecycle
Tests required: missing fill, unexpected broker-only R4 position, failed order, partial fill, duplicate fill
Phase: Phase 2 safety, Phase 3 blocker

ID: EC-AUD-005
Severity: P1
Subsystem: Evidence
Location: `src/eigencapital/production_qual/event_ledger.py::_get_config_fingerprint`
Problem: Config fingerprint uses nonexistent `EigenCapitalConfig.load()`.
Evidence: Mypy reports `"type[EigenCapitalConfig]" has no attribute "load"`; code catches the exception and returns `"unknown"`.
Why it matters: Event provenance can silently lose config identity.
Failure scenario: Events are written with `"unknown"` build/config fields and later cannot prove which risk envelope produced a trade.
Current behavior: Fallback to `"unknown"` is accepted.
Expected behavior: Fail loudly or bind to `load_config()` fingerprint.
Recommended action: Replace with `load_config()` and test that event config fingerprint is not `"unknown"` in normal runtime.
Implementation complexity: Low
Risk of changing it: Low
Dependencies: Config loader
Tests required: ledger event has real config fingerprint
Phase: Phase 2

ID: EC-AUD-006
Severity: P1
Subsystem: Configuration
Location: `configs/production/config.toml`, `src/eigencapital/config.py`, tests
Problem: Safety-critical capital/risk semantics are duplicated and inconsistent.
Evidence: `[capital].max_position_size=5000`, `[live_risk].max_position_notional=2500`, `[risk].max_position_notional=500000`, `[risk].min_equity=50000`, live loop uses `[capital]` for sizing caps and `[live_risk]` for enforcement envelope.
Why it matters: A future caller can choose the wrong section and silently trade under a looser envelope.
Failure scenario: New execution service uses `RiskConfig` and permits notional far beyond Phase 2 limit.
Current behavior: Comments say `[live_risk]` is authoritative, but code still consumes `[capital]` for sizing constants.
Expected behavior: Deterministic ownership and validation of every safety-critical parameter.
Recommended action: Define capital semantics hierarchy and enforce cross-section consistency where duplication is intentional.
Implementation complexity: Medium
Risk of changing it: Medium
Dependencies: Config tests, docs, live loop globals
Tests required: precedence, fingerprint, drift, wrong-section consumer checks
Phase: Phase 2/3

ID: EC-AUD-007
Severity: P1
Subsystem: Execution
Location: `scripts/r4_rebalance_loop.py`, `src/eigencapital/live/partial_fills.py`
Problem: Partial-fill lifecycle is not fully wired into canonical live execution.
Evidence: Failure matrix flags this as a P1 gap; `execute_orders()` records only submitted/filled/failed immediate results.
Why it matters: Partial fills are common enough in stressed conditions and must be auditable/recoverable.
Failure scenario: Broker partially fills, retry submits remaining or duplicate volume without a stable lifecycle record.
Current behavior: Immediate retcode summary.
Expected behavior: partial fill -> remainder -> cancel/chase -> reconciliation -> evidence events.
Recommended action: Integrate `PartialFillManager` into canonical execution.
Implementation complexity: Medium
Risk of changing it: Medium
Dependencies: Order IDs, event ledger, broker provider
Tests required: partial fill, chase limit, cancel remainder, restart during partial
Phase: Phase 2/3

ID: EC-AUD-008
Severity: P2
Subsystem: Core Domain
Location: `src/eigencapital/core/models/*`
Problem: Canonical dataclasses use mutable class-level registries for duplicate enforcement.
Evidence: Models assign `_registry = {}` after class definition; tests clear registries in fixtures.
Why it matters: Hidden global state makes object construction order-dependent in long-lived processes.
Failure scenario: Replay or dashboard reconstructs historical objects and later live construction fails due stale registry key.
Current behavior: Process-global duplicate detection.
Expected behavior: Uniqueness enforced by scoped repository/ledger/persistence layer.
Recommended action: Keep during Phase 2 if stable; later move uniqueness out of value objects.
Implementation complexity: Medium
Risk of changing it: Medium
Dependencies: many tests
Tests required: parallel replay, scoped repository duplicate checks
Phase: After Phase 2 unless blocking

ID: EC-AUD-009
Severity: P2
Subsystem: R4 Frozen Boundary
Location: `src/eigencapital/fidelity/r4_manifest.py`, `configs/production/config.toml`
Problem: Frozen manifest universe differs from live production universe.
Evidence: Manifest has 15 `m`-suffixed instruments; production config has 32 bare symbols and 25 eligible symbols.
Why it matters: Broker translation and universe expansion can drift outside the frozen identity.
Failure scenario: Eligible production symbol changes while manifest fingerprint remains unchanged.
Current behavior: Config fingerprint can catch full config change, but manifest identity does not encode production broker mapping.
Expected behavior: Frozen symbol-mapping manifest with deterministic fingerprint and T=0 binding.
Recommended action: Add explicit R4 broker-symbol mapping artifact.
Implementation complexity: Medium
Risk of changing it: Low if read-only
Dependencies: Config, T=0 snapshot, tests
Tests required: mapping drift changes fingerprint
Phase: Phase 2 evidence integrity

ID: EC-AUD-010
Severity: P2
Subsystem: Quality Gate
Location: `pyproject.toml`, `.github/workflows/ci.yml`
Problem: Type checking is non-enforced.
Evidence: Local mypy failed with 170 errors; CI runs `mypy ... || true`.
Why it matters: Safety-critical API drift is harder to catch.
Failure scenario: A provider returns `None` and a live path assumes a valid object; tests miss a rare branch.
Current behavior: Informational mypy only.
Expected behavior: Enforced mypy on critical packages, expanding over time.
Recommended action: Start with `config`, `live`, `reconciliation`, `production_qual`, and `execution`.
Implementation complexity: Medium
Risk of changing it: Low
Dependencies: type cleanup
Tests required: CI gate
Phase: Phase 2/3

## R4 Boundary Classification

- R4 manifest identity: SAFE / MUST-FREEZE.
- R4 signal implementation in live loop: CONDITIONAL / MUST-FREEZE because it is inline rather than package-isolated.
- R4 config parameters in `configs/production/config.toml`: MUST-FREEZE during Phase 2.
- Monitoring dashboards: SAFE if read-only.
- Reconciliation: CONDITIONAL; safe as read-only, but cannot be treated as complete independent reconciliation yet.
- ML/research modules: SAFE only if isolated from R4 production path.
- `--force-regime`: DANGEROUS.
- `scripts/r4_live_orders.py`: DANGEROUS.

## Risk Engine Audit

The system has meaningful periodic risk containment, not complete continuous risk containment. Gates are evaluated at startup and each rebalance cycle. The design is fail-closed for many local uncertainties, but live broker calls can hang, and there is no verified independent process that can flatten while the primary process is blocked inside a broker call. Pre-trade gates are stronger than post-trade lifecycle tracking.

Hard gates verified: broker data validity, position count, account drawdown, daily loss, equity floor, fingerprint. Soft/conditional: SL protection disabled for R4 normal operation, spread/symbol spec gaps, partial fills, margin nuance, correlation/concentration for scaling.

## Execution / Broker Audit

Order creation and ticket-scoped closes exist. Broker confirmation is observed through `order_send` return code and post-cycle positions. Missing or incomplete: client idempotency keys, hard timeouts, robust partial-fill lifecycle, one broker abstraction used everywhere, durable order-intent event before broker submission, and exact recovery for accepted-after-timeout ambiguity.

## Reconciliation Audit

The reconciliation engine can detect missing/extra positions, quantity mismatch, side mismatch, foreign positions, duplicate broker orders, stale positions with `time`, and bad account values. In the live loop, however, independent internal state is NOT VERIFIED because it is generated from broker positions. P&L discrepancy check is explicitly simplified and always passes.

## Evidence Audit

A trade cannot yet be guaranteed reconstructable from one canonical event stream. Evidence exists in multiple files and schemas. `reports/r4_loop/decisions.jsonl` records loop decisions; production qualification evidence records snapshots/closures; durable audit can provide hash chains; event ledger defines a richer schema but is not canonical in the live path and may emit `"unknown"` config fingerprint.

## Research / Backtesting Audit

Research infrastructure is broad and unusually strong for an early codebase: walk-forward, purge/embargo tests, bootstrap, block bootstrap, permutation, PBO, multiple-testing correction, deflated Sharpe, cost stress, regime, and sensitivity modules exist. Equality between research and production R4 is conditional because live R4 signal is inline and must be parity tested rather than imported from a frozen production strategy package.

## ML Readiness

Do not add ML to R4. Current evidence suggests possible future ML targets only after Phase 2 data matures: entry quality prediction, adverse excursion, time-to-profit, regime classification, execution quality, and exit timing. Each must start with a baseline and shadow evaluation, not live promotion.

## Storage / Logging

Operational storage is file-based. At $5K this is acceptable. At $50K-$1M the limiting factor is not bytes alone; it is queryability, atomicity, concurrent readers, corruption handling, retention, and reconstruction. A future read model should consume append-only events and expose read-only operational state.

Projected order-of-magnitude storage: still small at current weekly/hourly cadence, likely MB/month at $5K-$50K and tens to low hundreds of MB/month with richer tick/path evidence. If tick-level MAE/MFE and multi-instrument monitoring are retained at high frequency, storage can grow to GB/month before $1M. NOT VERIFIED with live volume metrics because actual future cadence/instrument count is unknown.

## Observability / Dashboard

Existing terminal dashboards should remain read-only and Phase 2-focused. A future web Operations Console is justified after canonical state exists:

```text
Canonical Event Ledger
      ↓
Read Model / API
      ↓
Read-only Web UI
```

Minimum future views: System Overview, Risk Command Center, Positions, Trade Lifecycle, Execution Quality, Reconciliation, Incidents, Qualification, Evidence, Build/Governance, Research.

## Security Audit

No real credentials were found in `.env.example`; alerts read tokens from environment variables. Realistic risks are local/operator risks: running alternate order scripts, passing `--force-regime`, modifying config before startup, corrupting evidence files, killing processes, or connecting to the local MT5 bridge. Broker credentials and local bridge permissions were NOT VERIFIED because real secret files and host permissions were not inspected.

## Testing Audit

Test volume and breadth are strong. Failures that can still occur despite passing tests: hung broker calls, accepted-after-timeout duplicate ambiguity, live bridge split-brain, real MT5 partial-fill edge cases, disk full during critical evidence append, local operator bypass via alternate script, and config/manifest mapping drift.

## Documentation Audit

Docs are extensive but overstate some current wiring. Authoritative hierarchy should be:

1. Live broker state and T=0 snapshots.
2. `configs/production/config.toml` plus deterministic fingerprints.
3. Frozen R4 manifest and freeze tests.
4. Production scripts actually invoked.
5. Tests and reports.
6. Narrative docs.

Narrative docs must be updated when they reference missing files or aspirational helpers.

## Improvement Plan

IMPLEMENT NOW:

1. Add hard timeout/idempotency around live `order_send`.
2. Disable or govern `--force-regime` for live execution.
3. Remove/quarantine `scripts/r4_live_orders.py` as an alternate order path.
4. Fix event ledger config fingerprint and test non-unknown provenance.
5. Make live reconciliation compare broker state to independent intended order/event state.
6. Wire partial-fill lifecycle into the canonical execution path.
7. Add production startup single-instance/supervisor claim to the live loop or service wrapper.
8. Add safety-critical config consistency checks for `[capital]`, `[risk]`, and `[live_risk]`.

IMPLEMENT AFTER PHASE 2:

1. Package R4 signal as a frozen imported module while preserving identity.
2. Add canonical operational event store and read model.
3. Build read-only web Operations Console.
4. Expand broker provider abstraction and remove direct MT5 calls.
5. Enforce mypy progressively across all packages.
6. Refactor large research scripts only where logic must become reusable.

DO NOT BUILD YET:

1. R4 optimization or parameter tuning.
2. ML inside R4.
3. Portfolio optimization for capital scaling.
4. Advanced execution algorithms.
5. Multi-broker support.
6. Full web dashboard before canonical state/read model.
7. Cosmetic rewrites of research campaign history.

## Final Architectural Verdict

ARCHITECTURAL FOUNDATION: GOOD
PRODUCTION SAFETY: CONDITIONAL
RELIABILITY: CONDITIONAL
OBSERVABILITY: CONDITIONAL
RESEARCH FOUNDATION: GOOD
SCALABILITY: CONDITIONAL
MAINTAINABILITY: CONDITIONAL
DOCUMENTATION: CONDITIONAL
PHASE 2 READINESS: READY WITH CONDITIONS

OVERALL: Continue evolving on the current architecture. Do not rewrite the platform. Refactor the live execution/reconciliation/evidence boundary incrementally and freeze R4 behavior while doing it.

If this were my codebase, the 10 highest-value things I would do next, in exact order:

1. Add broker-call timeout plus idempotency keys.
2. Remove or govern live `--force-regime`.
3. Quarantine `scripts/r4_live_orders.py`.
4. Fix event ledger config fingerprint.
5. Persist order intents before submission.
6. Make reconciliation compare broker state to independent intended state.
7. Wire partial-fill manager into live execution.
8. Add verified supervisor/single-instance startup to the live loop.
9. Add strict safety-config consistency validation.
10. Keep collecting untouched Phase 2 evidence.

I would deliberately not do ML, R4 tuning, capital scaling, advanced execution, multi-broker work, or a web dashboard until the current live evidence and safety boundary are cleaner.
