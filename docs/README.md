# QuantForge Documentation

Project documentation for the QuantForge cross-sectional factor ranking and paper trading system.

## Guides

| Guide | Description |
|-------|-------------|
| [`PAPER_TRADING_RUNBOOK.md`](PAPER_TRADING_RUNBOOK.md) | Daily/weekly ops, halt responses, troubleshooting |
| [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) | Architecture, components, data flow |
| [`GOVERNANCE_LAYER.md`](GOVERNANCE_LAYER.md) | 7-layer governance: validity, narrative, liquidity, PSI, halt chain |
| [`FEATURES.md`](FEATURES.md) | Alpha features, data ingestion, archetype features, labeling |
| [`LIVE_CONTRACT.md`](../LIVE_CONTRACT.md) | Immutable production system contract |

## Quick Reference

| Command | Description |
|---------|-------------|
| `./monitor_all` | One-command launch: MT5 terminal + bridge + engine + dashboard |
| `mt5-terminal` | Launch MT5 terminal in Wine |
| `mt5-bridge` | Launch MT5 TCP bridge server on :9876 |
| `python -m paper_trading.ops.monitor` | Run engine + dashboard only |
| `python backtests/trade_analysis.py` | Walk-forward style backtest + per-asset optimization |
| `python scripts/walk_forward_backtest.py` | Multi-ticker walk-forward validation |
| `python scripts/score_tickers.py` | Asset scoring and promotion classification |
| `python scripts/train_all_assets.py` | Full retraining of all asset models |

## Core Pipeline

| Stage | Module | Purpose |
|-------|--------|---------|
| Screening | `backtests/trade_analysis.py`, `scripts/walk_forward_backtest.py` | Multi-ticker walk-forward backtest, promotion scoring |
| Training | `paper_trading/inference/training.py` | XGBoost training with per-asset features |
| Inference | `paper_trading/inference/pipeline.py` | Live pipeline: OHLCV → features → XGBoost → decision |
| Async diagnostics | `paper_trading/inference/async_diagnostics.py` | DiagnosticsSnapshot + daemon consumer thread |
| Data fetching | `paper_trading/ops/data_fetcher.py` | MT5 bridge with yfinance fallback |
| MT5 bridge | `paper_trading/ops/mt5_bridge.py` | Wine-side TCP server for MT5 operations |
| MT5 client | `paper_trading/ops/mt5_client.py` | Host-side client with frame protocol + RLock |
| Broker | `paper_trading/execution/` | PaperBroker (simulated) or MT5Broker (live Exness) |
| State store | `paper_trading/state_store.py` | SQLite WAL-mode persistent state |
| Portfolio | `paper_trading/portfolio_builder.py` | 12-asset risk-parity portfolio from YAML config |
| Engine | `paper_trading/engine.py` | PaperTradingEngine with capital sync, parallel orchestrator |
| Dashboard | `paper_trading/dashboard/` | React SPA (Vite + TypeScript + Tailwind) on port 5000 |

## Current Portfolio

12 assets across FX, commodities, and equity indices. See `configs/paper_trading.yaml` for full configuration and allocations.

### Active
GC, USDCHF, AUDCHF, USDCAD, ES, NQ, GBPCAD, GBPNZD, NZDCAD, ^DJI, EURUSD, NZDUSD

### Removed (post walk-forward, insufficient edge)
AUDNZD, CADCHF, CADJPY, CL, EURCAD, GBPCHF, USDJPY, BTCUSD, EURGBP, EURJPY, NZDCHF, GBPUSD, GBPJPY, GBPAUD, AUDCAD, EURCHF, NZDJPY, ^VIX, IWM

## Services / Processes

| Service | Port | Purpose |
|---------|------|---------|
| Engine | — | Main trading loop (300s cycle) |
| Dashboard | 5000 | React SPA + JSON API endpoints |
| MT5 bridge | 9876 | Wine-hosted TCP bridge to MetaTrader 5 terminal |
| MT5 terminal | — | MetaTrader 5 under Wine + xvfb-run |

## ADRs

Architecture Decision Records in [`adr/`](adr/) — see [`adr/ADR-000-index.md`](adr/ADR-000-index.md) for the full list.

## Conventions

- ADRs follow the standard [Michael Nygard template](https://github.com/joelparkerhenderson/architecture-decision-record)
- All docs are written in Markdown
- `LIVE_CONTRACT.md` at the project root is the immutable system contract
