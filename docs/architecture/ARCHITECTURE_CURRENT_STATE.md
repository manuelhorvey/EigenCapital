# EigenCapital Current Architecture

Audit date: 2026-08-27
Git branch: `main`
Git HEAD: `ea223e2c28148883ba38f6411423d6af41882383`
Working tree at audit start: clean
Runtime used for verification: Python 3.14.7 on Linux

## Inventory

- Source modules: 248 Python files under `src/eigencapital`.
- Test files: 119 `test_*.py` files.
- Test collection: 2,511 tests collected.
- Test execution: 2,510 passed, 1 skipped, 16 warnings.
- Lint: `ruff check src/eigencapital scripts` passed.
- Type check: `mypy` passes on critical packages (live/, reconciliation/, production_qual/) — CI enforced, fails on errors.
- Application database: NOT VERIFIED as present. Current operational state is primarily CSV, JSON, JSONL, and logs.
- Current production config: `configs/production/config.toml`.
- Active R4 campaign from live loop and T=0 artifacts: `R4-5K-20260827`.
- Frozen R4 manifest identity: `aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb`.
- Current full production config fingerprint observed by `FingerprintVerifier(config=load_config("production"))`: `32fbeadcab9a3a14...`.
- Live risk fingerprint: `ee9324293336b827770844ee5e90a371bd6f2d757ba5f0514b3201ea980177ec`.

## Architecture Diagram

```text
Data
  src/eigencapital/data, MT5 D1 fetch in scripts/r4_rebalance_loop.py
  ↓
Feature Engineering
  src/eigencapital/features, R4 inline momentum/vol features in r4_rebalance_loop.py
  ↓
Research
  src/eigencapital/research, reports/r4_economics_audit, docs/research
  ↓
Strategy
  R4 manifest: src/eigencapital/fidelity/r4_manifest.py
  Live R4 signal implementation: scripts/r4_rebalance_loop.py::compute_r4_signal
  ↓
Signal
  pandas weight series plus diagnostics
  ↓
Portfolio Construction
  scripts/r4_rebalance_loop.py::generate_orders
  ↓
Sizing
  equity cap, min lot, contract size, max position cap
  ↓
Risk
  src/eigencapital/live/risk_enforcement.py
  src/eigencapital/live/daily_loss.py
  src/eigencapital/live/position_attribution.py
  ↓
Safety / Authorization
  fingerprint verifier, watchdog, T=0 validation, position assertion
  ↓
Execution
  scripts/r4_rebalance_loop.py::execute_orders
  ↓
Broker
  mt5linux MetaTrader5 RPyC bridge on 127.0.0.1:8001
  ↓
Reconciliation
  src/eigencapital/reconciliation/engine.py
  ↓
Evidence / Ledger
  reports/r4_loop/decisions.jsonl
  reports/r4_qualification/evidence/*.jsonl
  src/eigencapital/live/durable_audit.py
  src/eigencapital/production_qual/event_ledger.py
  ↓
Monitoring / Dashboard
  scripts/r4_monitor.py
  scripts/r4_dashboard.py
  scripts/r4_qualification_dashboard.py
```

```text
Research
  src/eigencapital/research/*
  ↓
Backtest
  src/eigencapital/backtest/*
  ↓
Validation
  src/eigencapital/analytics/validation/*
  ↓
Qualification
  src/eigencapital/production_qual/*
  ↓
Shadow / Fidelity
  src/eigencapital/fidelity/*
  src/eigencapital/shadow/*
  ↓
Live
  scripts/r4_rebalance_loop.py
  scripts/start_trading.sh
```

## Module Responsibilities

- `core.models`: canonical-ish dataclasses for bars, instruments, orders, fills, positions, decisions, targets, and experiment metadata.
- `data`: CSV loaders, normalization, validation, catalogues, and storage policy.
- `features`: base and alpha feature functions plus registry and pipeline.
- `strategies`: generic strategy base and a trend strategy baseline; the current R4 live signal is not packaged here.
- `research`: campaign and alpha research code, including large intraday campaign scripts.
- `analytics.validation`: walk-forward, bootstrap, PBO, multiple testing, cost stress, regime, and evidence gates.
- `backtest`: clock, accounting, and engine.
- `risk`: policy and account checks.
- `portfolio`: portfolio target and order-plan construction.
- `live`: live operational safety helpers, watchdog, risk overlay, alerts, supervisor, broker placeholder, and catastrophic protection.
- `execution`: paper broker and platform-agnostic MT5 provider abstraction.
- `reconciliation`: broker/internal comparison engine.
- `production_qual`: campaign gates, fingerprint verification, event/evidence ledger, live qualification dataset, and Phase 2 reports.
- `scripts`: actual production entry points and research/audit utilities.

## Dependency Direction

Static import graph found 310 internal import edges and no module-level cycles in the analyzed source tree. Top-level direction is mostly acceptable: data/features/strategies depend on core, live depends on risk/config/fidelity, production_qual depends on fidelity/risk/config. The largest architecture exception is the production live loop: it imports almost every critical subsystem directly and owns signal, portfolio, sizing, execution, reconciliation wiring, evidence capture, bridge restart, and CLI parsing in one script.

## Production Entry Points

- `scripts/r4_rebalance_loop.py`: primary live rebalance and order submission path.
- `scripts/start_trading.sh`: starts MT5 bridge, rebalance loop, optional monitor, and status/stop actions.
- `scripts/r4_monitor.py`: operational monitor.
- `scripts/r4_dashboard.py` and `scripts/r4_qualification_dashboard.py`: terminal dashboards.
- `scripts/r4_safety_supervisor.py`: safety supervisor for catastrophic protection, gated by `configs/r4_safety.enabled`.
- `scripts/r4_supervisor_dryrun.py`: dry-run supervisor report.
- `scripts/r4_live_orders.py`: **QUARANTINED** — `--execute` flag disabled with `sys.exit(1)`. All trading must go through `r4_rebalance_loop.py`.

No systemd service, container spec, migration system, or CI deployment artifact was verified.

## Persistence Paths

- `reports/r4_loop/decisions.jsonl`, `runtime_state.json`, logs, and monitor output.
- `reports/r4_qualification/T0_*.json`, attestations, supervisor dry-runs, and evidence JSONL files.
- `reports/r4_safety/safety_audit.jsonl` and `.mirror.jsonl`.
- `reports/r4_economics_audit/*.json`, CSVs, and reconstructed evidence.
- `data/mt5`, `data/intraday*`, and `data/tick_micro_m5` CSV datasets.

## Current Runtime Contradictions

- README references `docs/production/CAPITAL_SEMANTICS.md`, which is not present.
- Deployment docs reference `config/production.toml` and `config/development.toml`, but actual files are under `configs/{environment}/config.toml`.
- Deployment docs reference an `mt5-bridge` helper; no such tracked script was found.
- README says production Linux is certified and Python 3.12 recommended; deployment docs claim 3.14 tested; pyproject classifiers stop at 3.12; CI runs 3.11, 3.12, 3.13; local audit ran on 3.14.7.
- Older `reports/codebase_audit/provenance.json` is for a different HEAD and reported test collection errors; current collection succeeds.
