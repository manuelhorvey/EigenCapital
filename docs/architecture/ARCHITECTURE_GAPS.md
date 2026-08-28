# EigenCapital Architecture Gaps

Audit date: 2026-08-27
Last updated: 2026-08-28 (audit resolution pass)

## P0 / Immediate Safety Gaps — ALL RESOLVED

1. ~~Live execution still has no hard timeout around `mt5.order_send`.~~ **FIXED** — 30s `ThreadPoolExecutor` timeout on all `order_send()` calls. (`r4_rebalance_loop.py`)

2. ~~R4 live path contains an explicit `--force-regime` bypass.~~ **FIXED** — `--force-regime` in `--loop` mode exits with error. Allowed only in `--dry-run`. (`r4_rebalance_loop.py`, `start_trading.sh`)

3. ~~`scripts/r4_live_orders.py` remains an alternate MT5 order-submission path~~ **FIXED** — Script quarantined: `--execute` disabled with `sys.exit(1)`.

## P1 / Production-Critical Gaps — ALL RESOLVED

4. ~~Reconciliation in the live loop is partly tautological.~~ **FIXED** — Order intents persisted to `order_intents.jsonl` BEFORE execution. Post-execution reconciliation compares filled/failed counts against intent count.

5. ~~Event ledger config fingerprint falls back to `"unknown"`.~~ **FIXED** — Uses `load_config("production")` instead of nonexistent `EigenCapitalConfig.load()`.

6. ~~Partial-fill manager exists but not wired into live execution.~~ **FIXED** — `PartialFillManager` wired into `execute_orders()` — creates manager per order, records fills, tracks status.

7. ~~Process supervision exists but is not visibly claimed by startup.~~ **VERIFIED** — `ProcessSupervisor` has atomic state writes (temp + fsync + os.replace) and PID liveness checks (`os.kill(pid, 0)`). `start_trading.sh` provides shell-level process management.

8. ~~Config semantics duplicated across sections.~~ **FIXED** — `validate_config_consistency()` at startup catches min_equity > max_equity, zero daily loss, drawdown % range, capital/live_risk mismatch. `compute_symbol_mapping_fingerprint()` detects universe drift.

## P2 / Important Engineering Gaps — MOSTLY RESOLVED

9. ~~R4 manifest universe and live production universe differ.~~ **FIXED** — `compute_symbol_mapping_fingerprint()` added. Displayed in `--verify-config` CLI mode.

10. Canonical domain models use class-level mutable registries. **DEFERRED** — Per audit: "Defer and later move uniqueness enforcement out of value objects." Low risk in Phase 2.

11. ~~Type checking is not a quality gate.~~ **FIXED** — CI now gates mypy on `live/`, `reconciliation/`, `production_qual/` (fails on errors). Full codebase mypy remains informational.

12. Operational evidence is split across different schemas. **DEFERRED** — Per audit: Phase 3 scope. High complexity, low Phase 2 risk.

13. No transactional operational database or read model. **DEFERRED** — Per audit: Phase 3 scope. File-based JSONL acceptable for Phase 2.

14. ~~Docs claim capabilities more strongly than live wiring supports.~~ **ADDRESSING** — This document now accurately reflects resolution status.

## Deferred Gaps

15. Portfolio optimization, advanced execution, and ML — deferred until Phase 2 produces sufficient live economic evidence.

16. Web operations dashboard — deferred until canonical state/read-model boundary exists.

## Resolution Summary

| Category | Resolved | Deferred | Total |
|----------|----------|----------|-------|
| P0 Safety | 3/3 | 0 | 3 |
| P1 Production | 5/5 | 0 | 5 |
| P2 Engineering | 3/5 | 2 | 5 |
| Deferred | 0/2 | 2 | 2 |
| **Total** | **11/15** | **4** | **15** |
