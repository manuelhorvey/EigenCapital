# EigenCapital

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Status](https://img.shields.io/badge/status-paper%20trading-green)
![Portfolio](https://img.shields.io/badge/portfolio-22%20assets-blue)
[![codecov](https://codecov.io/gh/manuelhorvey/EigenCapital/graph/badge.svg)](https://codecov.io/gh/manuelhorvey/EigenCapital)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

Cross-sectional multi-asset paper trading engine with per-asset XGBoost models, 16-layer governance framework, adaptive exit trailing, MetaTrader 5 bridge execution (Exness demo), and a React SPA dashboard. Every asset must survive expanding-window walk-forward validation before entering the live portfolio.

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

[MT5 bridge →](docs/OPERATIONS.md#mt5-bridge-supervision) · [Security →](docs/SECURITY.md)

---

## Design Philosophy

- **Alpha is fragile; infrastructure robustness matters more.**
- Every decision is validated by expanding-window walk-forward before touching live capital.
- Runtime execution is a systems-engineering problem, not a signal-generation problem.
- Determinism, replayability, train/serve symmetry, and per-asset isolation are non-negotiable.

---

## System Overview

The engine runs a continuous 5-phase orchestrator cycle (every 60s) across 22 assets:

```text
PRE: state snapshot → REFRESH: parallel inference → ADMIT: PEK gate →
VALIDITY: state updates → PORTFOLIO HEALTH: circuit breaker, VaR, orphan recon → PERSIST: WAL
```

Each asset runs an independent `binary:logistic` XGBoost model. Raw probabilities pass through P1 calibration (ECE 0.36→0.02), a 22-stage decision pipeline, 16 governance layers, and a multiplicative sizing chain before reaching the broker.

[Full architecture →](docs/SYSTEM_OVERVIEW.md) · [Governance detail →](docs/GOVERNANCE.md) · [Feature reference →](docs/FEATURES.md)

---

## Current Portfolio

22 assets promoted from a 36-asset research universe via walk-forward. Weights use `factor_constrained_v2` (hard-linear factor constraints). Exits use trail_33pct retracement trailing (3-stage: breakeven lock → retracement trail → time decay).

**Portfolio timeline:**

| Date | Change |
|------|--------|
| 2026-07-04 | BTCUSD (weekend-eligible, 24/7), AUDJPY, NZDJPY, GBPJPY, USDJPY added → 22 assets |
| 2026-06-30 | 11 assets bumped to ratio=3.0 via optimizer; all models retrained |
| 2026-06-26 | Trend-exhaustion features (6 new alpha) improved BuyWR; SELL_ONLY reduced 10→3 |
| 2026-06-22 | GBPUSD promoted (walk-forward IC 0.186); ES/NQ/^DJI removed for portfolio remediation |
| 2026-06-20 | AUDNZD, EURUSD, AUDCHF, GBPNZD removed for directional instability |

Per-asset config (SL/TP, allocation, max_depth) in per-asset YAML files under [`configs/domains/assets/`](configs/domains/assets/).

[Full portfolio detail →](configs/domains/assets/) · [Mode reference →](docs/MODES.md)

---

## Key Results

| Metric | Value |
|--------|-------|
| Walk-forward portfolio R | +288.4R (ratio=3.0 retrain) |
| trail_33pct improvement | 6.9× over fixed-barrier baseline |
| Assets profitable | 16/16 under adaptive exit |
| Max drawdown (trail_33pct) | -23.5R (6.9× reduction vs fixed) |
| Sharpe (R-space, adj) | ~15-20 |
| Robustness gatekeeper | 5/5 PASS |
| Shock simulation | 21/21 scenarios PASS (0 catastrophic) |

[Backtest scripts →](scripts/backtest/) · [Robustness validation →](scripts/analysis/robustness_gatekeeper.py)

---

## Dashboard

React SPA (TypeScript, Vite, Tailwind CSS) served on port 5000. 4 routes with single-primary-job surfaces:

| Route | Purpose |
|-------|---------|
| `/` | Glance — status row, equity curve, open positions, sortable asset list |
| `/trading` | Operate — signal queue, admissions, recent trades, execution feed |
| `/execution` | Quality — equity curve, EIS/FQI scores, trade attribution |
| `/risk` | Governance — PEK telemetry, risk metrics, health scores |

[API reference →](docs/API.md) · [Monitoring →](docs/MONITORING.md) · [Security →](docs/SECURITY.md)

---

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `PYTHONPATH` | Yes | Set to `.` |
| `MT5_ACCOUNT` | No* | Exness MT5 account number |
| `MT5_PASSWORD` | No* | Exness MT5 account password |
| `MT5_SERVER` | No* | Exness MT5 server |
| `EIGENCAPITAL_REFRESH_INTERVAL` | No | Engine loop interval (default 60s) |
| `EIGENCAPITAL_API_TOKEN` | No | Dashboard bearer auth token |
| `WINE_PREFIX` | No | Wine prefix path (default ~/.wine_mt5) |
| `MT5_BRIDGE_PORT` | No | Bridge TCP port (default 9879) |

\* Required when `mt5.enabled: true` in config.

---

## Documentation

| Guide | Contents |
|-------|----------|
| [Architecture](docs/SYSTEM_OVERVIEW.md) | Full system design, orchestrator lifecycle, data flow |
| [Governance](docs/GOVERNANCE.md) | 16-layer framework, decision pipeline, sizing guardrails |
| [Features](docs/FEATURES.md) | Alpha, regime, and archetype feature reference |
| [Operations](docs/OPERATIONS.md) | Runbook, monitoring commands, troubleshooting |
| [API Reference](docs/API.md) | All dashboard JSON endpoints |
| [Security](docs/SECURITY.md) | Auth model, bridge security, secret management |
| [Testing](docs/TESTING.md) | Test suite structure and commands |
| [Monitoring](docs/MONITORING.md) | Prometheus metrics reference |
| [Development](docs/DEVELOPMENT.md) | Key scripts, benchmarks, contributing |
| [Modes](docs/MODES.md) | Operating mode presets (production/FTMO/live) |
| [Architecture Decisions](docs/adr/ADR-000-index.md) | ADR index (23 records) |
| [Changelog](CHANGELOG.md) | Release history |
| [Agent Guide](AGENTS.md) | Full operational context for LLM agents |

---

## Active Constraints

- Paper trading only (MT5 Exness demo — no live capital)
- 3 permanent SELL_ONLY assets (CADCHF, NZDCHF, EURAUD) — BUY signal inversion confirmed permanent
- MT5 bridge requires Wine on Linux; single-threaded (RLock-serialized)
- Small MT5 demo ($107) → positions quantize to 0.01 lot minimum; desired-vs-actual diverges
- Circuit breaker at -15% DD or 7 consecutive losses; emergency halt auto-clears on recovery
- Spread gate in observe-only for first 720 cycles; enforcement activates automatically thereafter

[Full known issues →](docs/known-issues.md)

---

## License

MIT License. Research and paper-trading system only. Not financial advice.
