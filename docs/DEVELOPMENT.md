# EigenCapital — Development Guide

Key scripts, commands, benchmarks, and contributing information for the EigenCapital paper trading platform.

**Last updated:** 2026-07-11

> **Scripts quick reference:** See the [Key Scripts](#key-scripts) section below
> for categorized script tables (training, backtesting, analysis, optimization,
> operations, diagnostics). This file covers project structure, benchmarks,
> testing, and validation tooling.

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

| Script | Description |
|--------|-------------|
| `scripts/training/retrain_all_fixed.py` | Retrain all assets with current pipeline |
| `scripts/training/train_regime_models.py` | Train regime-conditional models |
| `scripts/training/train_calibration.py` | Fit calibrators from walk-forward signals |
| `scripts/training/retrain_counterfactual.py` | Feature ablation walk-forward (SHAP mechanism test) |

### Backtesting & Analysis

| Script | Description |
|--------|-------------|
| `scripts/backtest/walk_forward_backtest.py [--asset <TICKER>]` | Multi-asset expanding-window validation |
| `scripts/backtest/backtest_pnl.py [--weight-method factor_constrained_v2]` | PnL from signal parquets |
| `scripts/backtest/compare_ensemble.py` | Ensemble vs base with per-fold sign test |
| `scripts/backtest/filter_direction.py` | Directional filter diagnostic |
| `scripts/backtest/crisis_replay.py` | Crisis windows (Dec 2024, tariff, selloffs) |
| `scripts/backtest/monte_carlo_drawdown.py` | Block-bootstrap drawdown (3 horizons, 10K sims) |
| `scripts/analysis/production_audit.py` | 18-phase production audit + scoring |
| `scripts/analysis/trade_lifecycle.py` | 18-phase trade reconstruction |
| `scripts/analysis/trailing_stop_sim.py` | Retracement trailing stop simulation |
| `scripts/analysis/robustness_gatekeeper.py` | 5-test robustness validation suite |
| `scripts/analysis/mfe_stationarity.py` | MFE stationarity + retrace stability |
| `scripts/analysis/shock_simulation.py` | 7-class structural fragility test |

### Optimization

| Script | Description |
|--------|-------------|
| `scripts/optimization/portfolio_sltp_optimizer.py` | TP/SL ratio grid search |
| `scripts/optimization/sl_fragility_test.py` | Intraday SL hit rate validation |
| `scripts/optimization/drift_detector.py [--json]` | Live win-rate drift vs breakeven WR |
| `scripts/optimization/portfolio_balancer.py` | Correlation-aware cluster risk penalty |
| `scripts/optimization/per_asset_quality.py` | Asset quality classification |

### Operations

| Script | Description |
|--------|-------------|
| `./monitor_all` | One-command launch (terminal + bridge + engine + dashboard) |
| `python scripts/ops/monitor_paper_trading.py` | Poll dashboard + CSV logging |
| `python scripts/ops/mt5_bridge_supervisor.py` | Bridge watchdog |
| `scripts/replay/replay_rebalance.py [--verify]` | Historical weight reconstruction |
| `tools/reset_halt.py` | Emergency halt CLI override |

### Replay & Diagnostics

| Script | Description |
|--------|-------------|
| `scripts/replay/replay_rebalance.py --verify` | Reconstruct historical portfolio weights |
| `scripts/diagnostics/check_chf_correlation.py` | CHF cluster independence check |
| `scripts/diagnostics/check_direction_win_rates.py` | Per-direction BUY/SELL win rate audit |
| `benchmarks/microbenchmark.py` | Runtime microbenchmarking |

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

## Dashboard Development

### Quick Start

```bash
cd paper_trading/dashboard
npm ci
npx tsc -b --noEmit  # TypeScript type-check
npx vitest run        # Run frontend tests
npm run build         # Production build
```

The dashboard is a React SPA (Vite + TypeScript + Tailwind CSS) served by the engine's HTTP server on port 5000.

### Key Architecture

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | React 18 | UI components |
| Build | Vite | Dev server + production builds |
| State | React Query | Server-state caching + polling |
| Validation | Zod | API response schema validation |
| Styling | Tailwind CSS | Utility-first styling |
| Charts | Recharts | Equity curves, PnL waterfall |
| Icons | Lucide React | UI icons |

### Route Structure

| Route | Page Component | Primary Job |
|-------|---------------|-------------|
| `/` | `CommandCenter` | Glance: equity curve, open positions, asset list |
| `/trading` | `TradingWorkspace` | Operate: signal queue, admission, trades |
| `/execution` | `ExecutionWorkspace` | Quality: EIS/FQI, attribution, MAE/MFE |
| `/risk` | `RiskWorkspace` | Governance: PEK, metrics, health scores |

### Data Flow

```
Backend (port 5000)                    Frontend (browser)
┌─────────────────────┐               ┌──────────────────────────┐
│ /state-bundle.json   │─────fetch───▶│ React Query              │
│ /state.json          │              │  └─useSystemSnapshot()   │
│ /health.json         │              │     └─sliced selectors   │
│ ...                  │              │        per component     │
└─────────────────────┘              │  Poll: 5s (open)         │
                                     │        30s (closed)      │
                                     └──────────────────────────┘
```

### Component Pattern

```typescript
// ✅ Always use sliced selectors — never subscribe to full state
const drawdown = useSystemSnapshot(s => s.portfolio.drawdown_pct);
const assets = useSystemSnapshot(s => s.assets);
```

### Style Guide

- **Single accent** (lifted emerald `#3dd9ae`) for primary actions and highlights
- **Governance semantic** colors (green/yellow/red) only on values that signal state
- **Mono supremacy** — all data values in monospace
- **Hairline rules** between cells on desktop; no shadow contrast between same-elevation panels
- **Operator voice** — concise, active, domain-specific copy

See [`docs/DASHBOARD.md`](docs/DASHBOARD.md) for the full frontend architecture reference.

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
| `docs/DASHBOARD.md` | Frontend architecture (React, Routing, Components) |
| `docs/DISASTER_RECOVERY.md` | Incident response and recovery playbook |
| `docs/adr/ADR-000-index.md` | Architectural decision record index |
