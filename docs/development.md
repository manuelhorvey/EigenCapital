# EigenCapital — Development Scripts Reference

> **This is a supplementary reference.** For the canonical development guide
> (project structure, benchmarks, testing, linting, validation commands), see
> [`docs/DEVELOPMENT.md`](DEVELOPMENT.md).

**Last updated:** 2026-07-07

## Key Scripts

### Training

| Script | Purpose |
|--------|---------|
| `scripts/training/retrain_all_fixed.py` | Retrain all assets with current pipeline |
| `scripts/training/train_regime_models.py` | Train regime-conditional models |
| `scripts/training/train_calibration.py` | Fit calibrators from walk-forward signals |
| `scripts/training/retrain_counterfactual.py` | Feature ablation walk-forward (SHAP mechanism test) |

### Backtesting

| Script | Purpose |
|--------|---------|
| `scripts/backtest/walk_forward_backtest.py` | Multi-asset expanding-window validation |
| `scripts/backtest/backtest_pnl.py` | PnL from signal parquets (`--weight-method factor_constrained_v2`) |
| `scripts/backtest/compare_ensemble.py` | Ensemble vs base with per-fold sign test |
| `scripts/backtest/filter_direction.py` | Directional filter diagnostic |
| `scripts/backtest/crisis_replay.py` | Crisis windows (Dec 2024, tariff, selloffs) |
| `scripts/backtest/monte_carlo_drawdown.py` | Block-bootstrap drawdown (3 horizons, 10K sims) |

### Analysis

| Script | Purpose |
|--------|---------|
| `scripts/analysis/production_audit.py` | 18-phase production audit + scoring |
| `scripts/analysis/trade_lifecycle.py` | 18-phase trade reconstruction |
| `scripts/analysis/trailing_stop_sim.py` | Retracement trailing stop simulation |
| `scripts/analysis/robustness_gatekeeper.py` | 5-test robustness validation suite |
| `scripts/analysis/mfe_stationarity.py` | MFE stationarity + retrace stability |
| `scripts/analysis/shock_simulation.py` | 7-class structural fragility test |

### Optimization

| Script | Purpose |
|--------|---------|
| `scripts/optimization/portfolio_sltp_optimizer.py` | TP/SL ratio grid search |
| `scripts/optimization/sl_fragility_test.py` | Intraday SL hit rate validation |
| `scripts/optimization/drift_detector.py` | Live win-rate drift vs breakeven WR |
| `scripts/optimization/portfolio_balancer.py` | Correlation-aware cluster risk penalty |

### Operations

| Script | Purpose |
|--------|---------|
| `./monitor_all` | One-command launch (terminal + bridge + engine + dashboard) |
| `scripts/ops/monitor_paper_trading.py` | Poll dashboard + CSV logging |
| `scripts/ops/mt5_bridge_supervisor.py` | Bridge watchdog |
| `scripts/replay/replay_rebalance.py` | Historical weight reconstruction |
| `tools/reset_halt.py` | Emergency halt CLI override |

### Diagnostics

| Script | Purpose |
|--------|---------|
| `scripts/diagnostics/check_chf_correlation.py` | CHF cluster independence check |
| `benchmarks/microbenchmark.py` | Runtime microbenchmarking |

---

## Test Suite

```bash
# Full test suite
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -q

# Single file
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/engine/test_engine.py -v

# Dashboard tests (from paper_trading/dashboard/)
cd paper_trading/dashboard && npx vitest run

# Coverage
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ --cov=paper_trading --cov-report=term-missing
```

[Full test docs →](docs/TESTING.md)

---

## Pre-Commit & Validation

```bash
ruff check .                     # Lint
ruff format . --check            # Format check
python tools/check_config_schema.py    # YAML schema validation
python tools/doc_drift_check.py        # Asset/model/config consistency
python tools/check_no_bare_asserts.py  # No bare assert in prod code
python tools/check_no_plaintext_secrets.py  # No plaintext secrets
```

---

## Repository Structure

```text
configs/          # YAML config (paper_trading, MT5 symbol map)
features/         # Feature builders + registry + triple-barrier labels
paper_trading/    # Engine, orchestrator, inference, execution, governance
  engine.py       # Main loop + capital sync
  asset_engine.py # Per-asset lifecycle
  orchestrator/   # Parallel AssetActor execution (5-phase cycle)
  inference/      # Live inference pipeline (base + regime)
  execution/      # PaperBroker, MT5Broker, decision pipeline
  governance/     # Risk engine, health monitor, circuit breaker
  position/       # Position management + adaptive exit
  services/       # Entry, metrics, state services
  attribution/    # Trade attribution
  replay/         # WAL-based deterministic replay
  dashboard/      # React SPA (Vite + TypeScript)
eigencapital/     # DDD application core
scripts/          # CLI tools (training, backtesting, analysis, ops)
models/           # Per-asset XGBoost models (gitignored)
shared/           # P0-P4: portfolio weights, calibration, kelly, factor model
docs/             # Documentation + ADRs
tests/            # Test suite (~2800 tests)
tools/            # Validation and CI tooling
```
