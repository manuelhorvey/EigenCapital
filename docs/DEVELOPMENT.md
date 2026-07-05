# EigenCapital — Development Guide

Key scripts, commands, benchmarks, and contributing information for the EigenCapital paper trading platform.

**Last updated:** 2026-07-05

---

## Quick Start

```bash
git clone https://github.com/manuelhorvey/EigenCapital.git
cd EigenCapital
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m paper_trading.ops.monitor    # yfinance-only mode
```

Dashboard: [http://localhost:5000](http://localhost:5000)

---

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `eigencapital/` | Core domain package (DDD structure) |
| `paper_trading/` | Paper trading engine, inference, execution |
| `features/` | Alpha feature engineering, labels, regime detection |
| `shared/` | Shared utilities (calibration, kelly, factor model, sizing) |
| `configs/` | Configuration — domain YAML tree + `PaperConfigRegistry` |
| `scripts/` | Analysis, backtest, optimization, training, ops |
| `tools/` | Validation, migration, security utilities |
| `tests/` | Test suite (pytest, vitest) |
| `portfolio/` | HRP allocator (P4) |
| `models/` | Trained models |
| `data/` | Runtime state, processed data, cache |

---

## Key Scripts

### Training

| Command | Description |
|---------|-------------|
| `python scripts/training/retrain_all_fixed.py` | Retrain all assets with pipeline fixes |
| `python scripts/training/train_regime_models.py` | Train regime-conditional models |
| `python scripts/training/train_calibration.py` | Train calibrators from walk-forward signal parquets |
| `python scripts/training/retrain_counterfactual.py` | Feature ablation walk-forward test |

### Backtesting & Analysis

| Command | Description |
|---------|-------------|
| `python scripts/backtest/walk_forward_backtest.py --asset <TICKER>` | Walk-forward validation per asset |
| `python scripts/backtest/backtest_pnl.py --weight-method factor_constrained_v2` | PnL backtest from OOS signal parquets |
| `python scripts/backtest/backtest_pnl.py --tag base --ensemble-tag ensemble` | Compare ensemble vs base |
| `python scripts/analysis/production_audit.py` | 18-phase production audit |
| `python scripts/analysis/trade_lifecycle.py` | Reconstruct + analyze trade lifecycle |
| `python scripts/analysis/trailing_stop_sim.py` | Retracement trailing stop simulation |
| `python scripts/analysis/robustness_gatekeeper.py` | 5-test robustness validation |
| `python scripts/analysis/mfe_stationarity.py` | MFE stationarity analysis |
| `python scripts/analysis/shock_simulation.py` | Structural fragility simulation |

### Optimization

| Command | Description |
|---------|-------------|
| `python scripts/optimization/portfolio_sltp_optimizer.py` | Grid search TP/SL ratio space |
| `python scripts/optimization/sl_fragility_test.py` | Intraday SL hit rate test |
| `python scripts/optimization/drift_detector.py --json > data/live/optimization.json` | Live win-rate drift check |
| `python scripts/optimization/per_asset_quality.py` | Asset quality classification |

### Operations

| Command | Description |
|---------|-------------|
| `python -m paper_trading.ops.monitor` | Run engine + dashboard |
| `./monitor_all` | One-command launch: MT5 + bridge + engine + dashboard |
| `python scripts/ops/monitor_paper_trading.py` | Poll dashboard + CSV logging |
| `python scripts/ops/mt5_bridge_supervisor.py` | MT5 bridge watchdog |

### Replay & Diagnostics

| Command | Description |
|---------|-------------|
| `python scripts/replay/replay_rebalance.py --verify` | Reconstruct historical portfolio weights |
| `python scripts/diagnostics/check_chf_correlation.py` | CHF cluster independence verification |

---

## Benchmarks

```bash
PYTHONPATH=$PYTHONPATH:. python benchmarks/microbenchmark.py
```

Reference: 1.63s warm p50 for 15 assets, 8 workers (see `benchmarks/README.md`).

---

## Testing

```bash
# Full Python test suite
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -v --tb=short -x

# Specific test file
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/engine/test_engine_weekend.py -v --tb=short

# Dashboard tests
cd paper_trading/dashboard && npx vitest run --reporter verbose

# Chaos tests
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/chaos/ -v --tb=short

# Documentation drift check
PYTHONPATH=$PYTHONPATH:. python tools/doc_drift_check.py

# With coverage
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ \
  --cov=. --cov-report=term-missing --cov-fail-under=70 -v --tb=short -x
```

## Linting

```bash
ruff check .
ruff format . --check
```

## Validation Commands

```bash
python tools/check_config_schema.py
python tools/check_import_firewall.py
python tools/check_no_bare_asserts.py
python tools/check_no_plaintext_secrets.py
```

---

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for:

- Code standards (Python + TypeScript)
- Git workflow and branch naming
- Pre-commit hooks
- Pull request process

---

## Key Documents

| Document | What it covers |
|----------|---------------|
| `AGENTS.md` | Day-to-day operational guide, architecture, common tasks |
| `LIVE_CONTRACT.md` | Immutable system invariants |
| `docs/ARCHITECTURE.md` | Backtesting framework architecture |
| `docs/SYSTEM_OVERVIEW.md` | Full system design, orchestrator lifecycle, data flow |
| `docs/OPERATIONS.md` | Operational procedures and runbook |
| `docs/FEATURES.md` | Feature engineering details |
| `docs/GOVERNANCE.md` | Governance layer reference |
| `docs/SECURITY.md` | Security model |
| `docs/adr/ADR-000-index.md` | Architectural decision record index |
