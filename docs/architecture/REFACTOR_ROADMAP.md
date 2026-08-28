# EigenCapital Refactor Roadmap

Audit date: 2026-08-27

## Keep

- Frozen R4 manifest identity and freeze tests: KEEP / MUST-FREEZE.
- `RiskEnforcer` broker-authoritative gates: KEEP, with targeted additions for order-level notional, spread, and symbol spec gates.
- `DailyLossTracker`, `Watchdog`, `PositionAttribution`, and catastrophic protection decision logic: KEEP.
- Research validation primitives such as walk-forward, bootstrap, PBO, multiple-testing correction, and deflated Sharpe: KEEP.
- Current terminal qualification dashboard: KEEP AS READ-ONLY during Phase 2.

## Refactor

- `scripts/r4_rebalance_loop.py`: REFACTOR INCREMENTALLY after safety gaps are closed. Extract canonical live application service boundaries for signal, portfolio plan, execution, reconciliation, and evidence, while preserving frozen R4 calculations.
- Configuration: REFACTOR into explicit owned semantics. Keep environment profiles, but validate safety-critical duplication across `[capital]`, `[risk]`, and `[live_risk]`.
- Reconciliation: REFACTOR to compare broker state against an independent intended-order/event ledger, not against broker-derived internal state.
- Evidence: REFACTOR toward one canonical event schema plus append-only storage; keep legacy JSONL/report readers as adapters.
- Process startup: REFACTOR from shell-backgrounded processes to a verified supervisor/service model.

## Merge

- `execution.trading_provider`, `live.broker`, and direct MT5 calls in scripts should converge on one broker provider boundary.
- `live.alerts` and `live.structured_alerts` should converge on the structured implementation.
- `execution.reconciliation` compatibility should remain deprecated and be removed after consumers migrate to `reconciliation.engine`.

## Remove

- ~~Remove or quarantine `scripts/r4_live_orders.py`~~ **DONE** — quarantined (EC-AUD-003).
- ~~Remove stale references to `CAPITAL_SEMANTICS.md`~~ **DONE** — consolidated into `CAPITAL_SCALING.md`.

## Defer

- Do not refactor historical research campaign files for style alone.
- Do not build ML inside R4.
- Do not build a web dashboard until canonical state and read-model boundaries exist.
- Do not optimize R4 parameters, universe, cadence, sizing, or exits while Phase 2 evidence collection is active.

## Rewrite

No subsystem currently warrants a full rewrite. The exception would become the live execution/reconciliation path if idempotency, timeout, and independent evidence-ledger integration cannot be added incrementally.
