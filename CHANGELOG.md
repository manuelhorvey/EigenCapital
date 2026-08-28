# Changelog

All notable changes to EigenCapital will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [v0.3.0] - 2026-08-28

### Added
- **Risk observation**: 14 continuous risk dimensions (net exposure, sector breakdown, VaR estimate, slippage monitoring)
- **REDUCED size-scaling**: Shadow-only soft constraint (0.25-1.0) based on drawdown/concentration/daily loss
- **Risk outcome attribution**: `risk_attribution.py` — records risk state at entry, tracks MAE/MFE, computes counterfactual P&L
- **Reconciliation self-healing**: SAFE_AUTOFIX for stale positions, price mismatches, duplicate orders
- **Alerting escalation**: Repetition-based (3+ WARNINGs → CRITICAL) and time-based (10min → CRITICAL) rules
- **Streaming metrics**: Updated dashboard consumption with all 14 observation dimensions
- 25 new tests (REDUCED correctness, shadow mode, attribution, autofix safety)

### Changed
- Risk observer now produces 14 dimensions (was 10)
- Reconciliation `apply_safe_autofixes()` method added to engine
- Structured alerts now support escalation threshold configuration

### Security
- REDUCED is shadow-only during Phase 2 — records but does not apply size reductions
- Reconciliation autofix classified: SAFE/CONDITIONAL/DANGEROUS/NEVER AUTOMATE
- Position count mismatch and foreign positions are NEVER automated

## [v0.2.1] - 2026-08-28

### Fixed
- **P0-4 deployment drift**: Live process restarted, all 5 fingerprint gates pass at startup
- build_manifest.json clarified as historical artifact (not written by live process)

### Changed
- `P0_STATUS_UPDATE.json`: All four Aug 26 P0 findings now resolved or mitigated
- `final_verdict.json`: Phase 2 readiness upgraded from CONDITIONAL to READY

## [v0.2.0] - 2026-08-28

### Added
- **Order timeout**: 30s timeout via `ThreadPoolExecutor` on all `order_send()` calls (EC-AUD-001)
- **Force-regime block**: `--force-regime` in `--loop` mode exits with error (EC-AUD-002)
- **Order intent persistence**: Intents saved to `order_intents.jsonl` before execution (EC-AUD-004)
- **Config validation**: `validate_config_consistency()` at startup (EC-AUD-006)
- **PartialFillManager**: Wired into canonical execution path (EC-AUD-007)
- **P&L reconciliation**: Real check comparing `balance + unrealized_pnl` vs `equity` (P1-003)
- **Multi-factor foreign detection**: Magic number + symbol allowlist (P1-010)
- **Pending order capacity**: `capacity_account()` counts pending orders toward limits (P2-014)
- **FingerprintVerifier caching**: Skip recompute if config unchanged (P2-011)
- **Shared error handler**: `error_handler.py` with `handle_transient()` and `handle_fatal()` (P2-012)
- **Config drift CLI**: `--verify-config` mode shows drift vs T=0 (P1-006)
- **Symbol mapping fingerprint**: `compute_symbol_mapping_fingerprint()` (EC-AUD-009)
- **Evidence correlation IDs**: campaign_id, cycle_counter, correlation_id in snapshots (P2-017)
- **Evidence failure escalation**: WARNING at 3, CRITICAL at 6 consecutive failures (P1-008)
- **Watchdog trail age**: Reads JSONL timestamps instead of file mtime (P1-007)
- **State machine invariants**: Documented in Watchdog and DisconnectRecovery docstrings (ID-008)
- **mypy enforcement**: CI gates mypy on `live/`, `reconciliation/`, `production_qual/` (EC-AUD-010)
- 25 focused audit resolution tests (P&L check, foreign detection, pending order capacity)

### Fixed
- `r4_live_orders.py` quarantined: `--execute` disabled with `sys.exit(1)` (EC-AUD-003)
- `event_ledger.py`: Fixed `_get_config_fingerprint()` to use `load_config("production")` (EC-AUD-005)
- `risk_observation.py`: Hardcoded `min_equity=4000` now matches config (F-003)
- `start_trading.sh`: Interval read from config, `--force-regime` warns in live mode (ID-015)
- All ruff E402 errors resolved in `r4_rebalance_loop.py`
- All mypy type errors resolved across 10 source files
- 15 documentation drift findings resolved
- Runtime audit logs untracked (gitignored)

### Changed
- `COMPREHENSIVE_CODEBASE_AUDIT.md`: Numeric scoring restored (75/100), grade inflation acknowledged
- `DOCUMENTATION_GOVERNANCE.md`: Authority model for all documentation
- Architecture docs updated to reflect post-resolution state

## [v0.1.0] - 2026-08-27

### Added
- Initial tagged release
- R4 frozen momentum strategy (12-1M, cross-sectional ranks, vol scaling)
- 7 risk gates (fingerprint, position count, drawdown, daily loss, equity floor, SL protection, fingerprint)
- Catastrophic stop-loss (2×ATR14 or 1% floor)
- Broker-authoritative reconciliation (8 checks)
- Disconnect recovery state machine (5 states)
- Watchdog with blind-window escalation
- JSONL audit trail with fsync
- Fingerprint verification (startup + every cycle)
- T=0 snapshot and attestation pipeline
- Pre-flight checks (fingerprint, supervisor dry-run, adversarial audit)
- `start_trading.sh` with bridge restart, graceful shutdown
- Dashboard, monitor, qualification monitor
- 2,426+ tests across unit, property, integration, failure injection
- CI: GitHub Actions (3.11-3.12-3.13 matrix, ruff, mypy, codecov)
