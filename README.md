# QuantForge

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Status](https://img.shields.io/badge/status-paper%20trading-green)
![WalkForward](https://img.shields.io/badge/walk--forward-36%20assets%20screened-success)
![Portfolio](https://img.shields.io/badge/portfolio-21%20dashboard%20assets-blue)
[![codecov](https://codecov.io/gh/manuelhorvey/QuantForge/graph/badge.svg)](https://codecov.io/gh/manuelhorvey/QuantForge)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

Cross-sectional multi-asset research and paper trading engine with walk-forward asset selection, per-asset XGBoost models, seven-layer governance, MetaTrader 5 bridge execution (with full order lifecycle support), and a React dashboard.

---

# Design Philosophy

> alpha is fragile; infrastructure robustness matters more.

The system prioritizes:

* walk-forward validation,
* deterministic execution,
* train/serve symmetry,
* replayability,
* governance layering,
* per-asset isolation,
* and operational observability

over maximizing in-sample returns.

Every promoted asset must survive expanding-window validation before entering the live paper portfolio. Runtime execution is treated as a systems-engineering problem rather than purely a signal-generation problem.

---

# System Lifecycle

```
Research Universe (36 assets screened)
        ↓
Walk-Forward Screening (expanding window)
        ↓
Asset Selection (GREEN / YELLOW / RED)
        ↓
Per-Asset Model Training (XGBoost, per-asset depth)
        ↓
Live Inference (every 300s)
        ↓
Governance Filters (7 layers)
        ↓
Execution & Positioning (MT5 or PaperBroker)
        ↓
State Persistence + Replay
```

---

# Current Portfolio

21 assets promoted from the research universe via expanding-window walk-forward. Per-asset SL/TP/max_depth calibrated via grid sweep.

| Asset      | Ticker       | sl_mult | tp_mult | Allocation | max_depth |
| ---------- | ------------ | ------- | ------- | ---------- | --------- |
| GC         | GC=F         | 1.00    | 4.00    | 7.0%       | 2         |
| USDCHF     | USDCHF=X     | 0.85    | 3.00    | 4.0%       | 4         |
| AUDCHF     | AUDCHF=X     | 2.75    | 3.50    | 5.0%       | 2         |
| USDCAD     | USDCAD=X     | 2.50    | 2.03    | 5.0%       | 5         |
| ES         | ES=F         | 2.00    | 5.50    | 7.0%       | 2         |
| NQ         | NQ=F         | 2.50    | 5.00    | 7.0%       | 2         |
| GBPCAD     | GBPCAD=X     | 2.50    | 2.50    | 5.0%       | 2         |
| GBPNZD     | GBPNZD=X     | 3.00    | 1.00    | 5.0%       | 3         |
| NZDCAD     | NZDCAD=X     | 2.50    | 4.00    | 5.0%       | 2         |
| ^DJI       | ^DJI         | 0.50    | 4.00    | 4.0%       | 4         |
| EURUSD     | EURUSD=X     | 3.00    | 1.50    | 4.0%       | 3         |
| NZDUSD     | NZDUSD=X     | 2.50    | 1.50    | 5.0%       | 5         |
| GBPAUD     | GBPAUD=X     | 1.00    | 2.00    | 5.0%       | 2         |
| NZDCHF     | NZDCHF=X     | 1.00    | 4.00    | 7.0%       | 2         |
| CADCHF     | CADCHF=X     | 1.00    | 4.00    | 5.0%       | 2         |
| AUDUSD     | AUDUSD=X     | 1.50    | 4.00    | 4.0%       | 2         |
| AUDNZD     | AUDNZD=X     | 2.00    | 1.00    | 3.0%       | 2         |
| EURCHF     | EURCHF=X     | 1.00    | 3.00    | 5.0%       | 4         |
| EURCAD     | EURCAD=X     | 1.00    | 1.00    | 2.0%       | 3         |
| EURNZD     | EURNZD=X     | 1.50    | 2.50    | 3.0%       | 3         |
| GBPCHF     | GBPCHF=X     | 1.00    | 2.00    | 3.0%       | 2         |

Allocation sums to ~1.00. Daily risk-parity rebalancing redistributes capital proportionally.

### Backtest Performance (5-Year 2021–2025, 21-asset portfolio)

| Metric | Value |
|--------|-------|
| Profit factor | 1.908 |
| Avg R | +0.268 |
| All assets positive | 21/21 |
| Total trades | 2383 |

---

# MT5 Bridge Integration

QuantForge can route data fetching and order execution through a live MetaTrader 5 terminal (Exness demo) running under Wine.

## Architecture

```
Linux Host                          Wine Prefix
┌─────────────┐                ┌──────────────────────┐
│ Engine      │── TCP :9879 ──▶│ mt5_bridge.py        │
│ mt5_client  │◀───────────────│ (Python 3.12 via      │
│ (Python)    │                │  Wine → MetaTrader5)  │
└─────────────┘                ├──────────────────────┤
                               │ MetaTrader 5 terminal │
                               │ terminal64.exe        │
                               │ (Exness demo account) │
                               └──────────────────────┘
```

## Capabilities

* Real-time price streaming (bid/ask)
* Historical OHLCV and tick data
* Account info and position management
* Market order placement with SL/TP
* Trailing stop and post-entry SL/TP modification
* Position closing on flip, SL, TP, and time-stop

## Symbol Mapping

QuantForge tickers (e.g. `GC=F`) are mapped to MT5 symbols (e.g. `XAUUSD`) via `configs/mt5_symbol_map.yaml`.

## Capital Sync

When MT5 is enabled, each engine cycle syncs internal capital bases to the live Exness account equity. Position sizing uses the real account balance.

---

# Model Architecture

Each asset runs an independent XGBoost model with per-asset configuration.

**Training** (backtest): `multi:softprob` — 3-class (SELL/HOLD/BUY), HOLD dropped for training.
**Live inference**: `binary:logistic` — trained on {-1, 1} labels after dropping HOLD.

```text
Objective: binary:logistic (live), multi:softprob (backtest)
Trees:     300
LR:        0.02
Depth:     per-asset (2–5)
```

No shared multi-asset model exists.

---

# Feature Engineering

Built in `features/alpha_features.py:build_alpha_features()`.

Every asset uses the same 12 alpha features (per-asset prefix):

| Feature | Description |
|---------|-------------|
| `{ASSET}_carry_vol_adj` | Volatility-adjusted carry |
| `{ASSET}_mom_21d` | 21-day momentum |
| `{ASSET}_mom_63d` | 63-day momentum |
| `{ASSET}_mom_126d` | 126-day momentum |
| `{ASSET}_mom_252d` | 252-day momentum |
| `{ASSET}_zscore_20` | 20-day z-score |
| `{ASSET}_vol_ratio` | Short/long-term vol ratio |
| `{ASSET}_dow_signal` | Day-of-week encoding |
| `dxy_mom_21d` | DXY 21-day return |
| `vix_mom_5d` | VIX 5-day return |
| `spx_mom_5d` | SPX 5-day return |
| `WTI_mom_21d` | WTI crude 21-day return |

Some assets additionally include `yield_slope` (GBPAUD, CADCHF, AUDNZD, EURNZD, GBPCHF) or `mom126` (EURCHF, NZDUSD).

## Archetype Features (inference-only)

Derived from OHLCV for execution conditioning:
- EMA spread, ADX(14), RSI(14), Bollinger z-score

---

# Inference Pipeline

```text
1. Fetch live OHLCV (MT5 or yfinance, 5y window)
2. Refresh latest price
3. Fetch macro data
4. Build alpha features (build_alpha_features, 12 cols)
5. Build archetype features (ema_spread, adx, rsi, bb_zscore)
6. Optional truncation validation (predict last row only)
7. PSI drift check (rolling 21d vs baseline)
8. XGBoost inference (binary:logistic → 3-col proba expansion)
9. Optional meta-label inference
10. FixedThresholdStrategy(0.45) → BUY/SELL/FLAT
11. Archetype classification
12. Route through 7 governance layers
13. Execute or defer (MT5 bridge for real broker)
```

---

# Execution Architecture

```
TradeDecision
      ↓
EntryOptimizer
      ↓
ExecutionPolicyLayer
      ↓
_can_enter()  (single entry authority)
      ↓
PositionManager
      ↓
Attribution Engine
```

Orders route through either:
- **PaperBroker** — simulated fills with slippage and market impact
- **MT5Broker** — live Exness demo via Wine bridge

## Key Invariants

### Single Entry Authority
All entry paths route through `_can_enter()`. No component may bypass centralized admission control.

### Immutable Execution Contract
```
PolicyDecision → FillResult → AttributionRecord
```
Execution artifacts are append-only and replay-safe.

### Train/Serve Symmetry
The same feature builder is used in both training and live inference.

### Replay-Oriented Persistence
Persistent state is stored in SQLite WAL mode with append-oriented semantics.

---

# Governance Framework

QuantForge uses independently configurable governance layers with worst-wins aggregation.

| Layer                  | Frequency   | Scope     | Effect                    |
| ---------------------- | ----------- | --------- | ------------------------- |
| Exposure state machine | Per tick    | Per asset | Exposure scaling          |
| Feature stability      | Per retrain | Per asset | Validity penalty          |
| Meta-labeling          | Per signal  | Per asset | Position scalar           |
| Macro regime overlay   | Weekly      | Global    | Exposure + SL adjustments |
| Liquidity regime       | Per signal  | Per asset | Exposure + halt logic     |
| PSI drift              | Per cycle   | Per asset | Penalty + halt            |
| Portfolio drawdown     | Global      | Portfolio | Global throttling         |

---

# Failure Isolation

Each `AssetEngine` executes independently via parallel orchestration (`EngineOrchestrator` with `ThreadPoolExecutor`). Failures in data ingestion, diagnostics, governance, execution, or model inference cannot halt the global engine.

---

# Dashboard

A React SPA (TypeScript, Vite, Tailwind CSS) served on port 5000.

## Features

* 6-layer execution dashboard (FilterBar → ExecutionQualityStrip → Attribution Breakdown → MAE/MFE Scatter → Execution Friction → Trade Table)
* Governance overlays (narrative status, liquidity badges, PSI drift panel, connection status)
* Risk-parity rebalancing visualization
* Historical trade log with attribution decomposition
* Zod-validated API responses

### API Endpoints

| Endpoint            | Format | Purpose                     |
| ------------------- | ------ | --------------------------- |
| `state.json`        | JSON   | Engine snapshot             |
| `trades.json`       | JSON   | Trade history               |
| `attribution.json`  | JSON   | Execution decomposition     |
| `narrative.json`    | JSON   | Macro narrative status      |
| `liquidity.json`    | JSON   | Liquidity regime per asset  |
| `psi.json`          | JSON   | PSI drift monitoring        |
| `governance.json`   | JSON   | Governance layer state      |
| `risk_parity.json`  | JSON   | Risk-parity weights         |
| `execution.json`    | JSON   | Execution quality metrics   |
| `shadow.json`       | JSON   | Shadow trade comparison     |
| `analytics.json`    | JSON   | Portfolio analytics         |

---

# Getting Started

## Prerequisites

- Python 3.12+
- Wine 11+ (for MT5 bridge — skip if using yfinance only)
- `xvfb-run` (for headless MT5 terminal)
- Node.js + Yarn (for dashboard build)

## Install

```bash
git clone https://github.com/manuelhorvey/QuantForge.git
cd QuantForge

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

## MT5 Setup (optional)

Only needed if you want to use the MetaTrader 5 bridge for live demo execution:

```bash
# Install MT5 terminal in Wine prefix
./scripts/setup_mt5_wine.sh

# Configure credentials in .env
cp .env.example .env
# Edit .env: set MT5_ACCOUNT, MT5_PASSWORD, MT5_SERVER
```

## Run

```bash
# One-command launcher: builds dashboard, starts MT5 terminal, bridge, and engine
./monitor_all

# Or for yfinance-only mode (no MT5):
# Set data_source: yfinance in configs/paper_trading.yaml
python -m paper_trading.ops.monitor
```

Dashboard: [http://localhost:5000](http://localhost:5000)

---

# Environment Variables

| Variable                      | Required | Purpose                                |
| ----------------------------- | -------- | -------------------------------------- |
| `PYTHONPATH`                  | Yes      | Set to `.`                             |
| `QUANTFORGE_REFRESH_INTERVAL` | No       | Engine loop interval (default 300s)     |
| `MT5_ACCOUNT`                 | No*      | Exness MT5 account number              |
| `MT5_PASSWORD`                | No*      | Exness MT5 account password            |
| `MT5_SERVER`                  | No*      | Exness MT5 server (e.g. Exness-MT5Trial2) |
| `OPENCODE_ZEN_API_KEY`        | No       | Weekly narrative extraction            |
| `WINE_PREFIX`                 | No       | Wine prefix path (default ~/.wine_mt5) |
| `MT5_BRIDGE_PORT`             | No       | Bridge TCP port (default 9879)          |

\* Required when `mt5.enabled: true` in config.

---

# Key Scripts

| Script                                         | Purpose                         |
| ---------------------------------------------- | ------------------------------- |
| `./monitor_all`                                | One-command launch (terminal + bridge + engine + dashboard) |
| `~/.local/bin/mt5-terminal`                    | Launch MT5 terminal via Wine    |
| `~/.local/bin/mt5-bridge`                      | Launch MT5 bridge server        |
| `backtests/trade_analysis.py`                  | Walk-forward backtest + optimization |
| `scripts/walk_forward_backtest.py`             | Multi-ticker validation         |
| `scripts/score_tickers.py`                     | Asset scoring                   |
| `scripts/generate_promotion_report.py`         | Portfolio report generation     |
| `scripts/train_all_assets.py`                  | Full retraining                 |
| `scripts/setup_mt5_wine.sh`                    | MT5 Wine environment setup      |
| `benchmarks/microbenchmark.py`                 | Runtime benchmarking            |

---

# Repository Structure

```text
configs/
    paper_trading.yaml        # Primary engine config
    mt5_symbol_map.yaml       # MT5 symbol mapping
backtests/                   # Backtest + optimization scripts
    trade_analysis.py         # Main backtest engine
features/
    builder.py                # Per-asset feature construction
    registry.py               # Feature contracts (36 assets)
    labels.py                 # Triple-barrier labeling
paper_trading/
    engine.py                 # Main engine + capital sync
    asset_engine.py           # Per-asset lifecycle
    orchestrator/             # Parallel AssetActor execution
    inference/                # Live inference pipeline
    execution/
        paper_broker.py       # Simulated fills
        mt5_broker.py         # MT5 live execution
        bridge.py             # Broker abstraction
    ops/
        monitor.py            # Main loop + dashboard server
        data_fetcher.py       # Data with MT5 fallback
        mt5_bridge.py         # Wine-side TCP bridge server
        mt5_client.py         # Host-side bridge client
    governance/               # 7-layer governance
    position/                 # Position management
    services/                 # Engine services (narrative, rebalance, state)
    dashboard/                # React SPA (Vite + TypeScript)
scripts/                      # CLI tools
docs/                         # Documentation + ADRs
shared/                       # Strategy registry, sizing, execution config
monitoring/                   # PSI drift, validity, importance tracking
benchmarks/                   # Performance benchmarks
tests/                        # Test suite
```

---

# Known Constraints

* Paper trading only (no live capital)
* Yahoo Finance primary data source (with MT5 as optional supplement)
* MT5 bridge requires Wine on Linux
* Some FX crosses may produce incomplete first-cycle bars
* Macro data sourced entirely from Yahoo Finance
* Dashboard requires `yarn build` after asset list changes
* MT5 bridge is single-threaded — concurrent requests are serialized via RLock

---

# Roadmap

* Deterministic full-day replay reconstruction
* Event-sequence validation tooling
* Extended execution quality analytics
* Multi-engine distributed orchestration
* Portfolio-level regime optimization
* Shadow execution comparison tooling
* Async MT5 bridge for concurrent symbol queries

---

# License

MIT License.

Research and paper-trading system only.

Not financial advice.
