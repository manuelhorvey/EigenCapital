# QuantForge Documentation

Project documentation for the QuantForge cross-sectional factor ranking and paper trading system.

## Guides

| Guide | Description |
|-------|-------------|
| [`PAPER_TRADING_RUNBOOK.md`](PAPER_TRADING_RUNBOOK.md) | Daily/weekly ops, halt responses, troubleshooting |
| [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) | Architecture, components, data flow, governance |
| [`GOVERNANCE_LAYER.md`](GOVERNANCE_LAYER.md) | 9-layer governance + decision pipeline stages + position sizing guardrails |
| [`FEATURES.md`](FEATURES.md) | Alpha features (13 cols), regime features (7 cols), archetype, labeling |
| [`LIVE_CONTRACT.md`](../LIVE_CONTRACT.md) | Immutable production system contract |

## Quick Reference

| Command | Description |
|---------|-------------|
| `./monitor_all` | One-command launch: MT5 terminal + bridge + engine + dashboard |
| `mt5-terminal` | Launch MT5 terminal in Wine |
| `mt5-bridge` | Launch MT5 TCP bridge server on :9879 |
| `python -m paper_trading.ops.monitor` | Run engine + dashboard only |
| `python scripts/research/trade_analysis.py` | Walk-forward style backtest + per-asset optimization |
| `python scripts/backtest/walk_forward_backtest.py` | Multi-ticker walk-forward validation |
| `python scripts/research/score_tickers.py` | Asset scoring and promotion classification |
| `python scripts/training/train_all_assets.py` | Full retraining (legacy) |
| `python scripts/training/retrain_all_fixed.py` | Retrain with all pipeline fixes |
| `python scripts/training/train_regime_models.py` | Train regime-conditional models |
| `python scripts/backtest/ensemble_pilot_backtest.py` | 3-asset ensemble pilot backtest |
| `python scripts/ops/monitor_paper_trading.py` | Poll dashboard + CSV logging |

## Core Pipeline

| Stage | Module | Purpose |
|-------|--------|---------|
| Screening | `scripts/research/trade_analysis.py`, `scripts/backtest/walk_forward_backtest.py` | Multi-ticker walk-forward backtest, promotion scoring |
| Training | `paper_trading/inference/training.py` | XGBoost training with per-asset features |
| Inference | `paper_trading/inference/pipeline.py` | Live pipeline: OHLCV → features → XGBoost → decision |
| Async diagnostics | `paper_trading/inference/async_diagnostics.py` | DiagnosticsSnapshot + daemon consumer thread |
| Data fetching | `paper_trading/ops/data_fetcher.py` | MT5 bridge with yfinance fallback |
| MT5 bridge | `paper_trading/ops/mt5_bridge.py` | Wine-side TCP server for MT5 operations |
| MT5 client | `paper_trading/ops/mt5_client.py` | Host-side client with frame protocol + RLock |
| Broker | `paper_trading/execution/` | PaperBroker (simulated) or MT5Broker (live Exness) |
| State store | `paper_trading/state_store.py` | SQLite WAL-mode persistent state |
| Portfolio | `paper_trading/portfolio_builder.py` | 21-asset risk-parity portfolio from YAML config |
| Engine | `paper_trading/engine.py` | PaperTradingEngine with capital sync, parallel orchestrator (HealthMonitor + VaR/CVaR in Phase 3g) |
| Portfolio weights | `shared/portfolio_weights.py` | P0 portfolio weight computation |
| Calibration | `shared/calibration/` | P1 calibration layer |
| Kelly sizing | `shared/kelly.py` | P2 fractional Kelly sizing |
| Factor model | `shared/factor_model.py` | P3 factor model monitoring |
| HRP fix | `portfolio/hrp_allocator.py` | P4 HRP fix |
| Dashboard | `paper_trading/dashboard/` | React SPA (Vite + TypeScript + Tailwind) on port 5000 |

## Current Portfolio

19 assets across FX, commodities, and equity indices. See `configs/paper_trading.yaml` for full configuration and allocations.

**Added 2026-06-22:** GBPUSD promoted (walk-forward IC 0.186, HR 0.371, pt_sl=(1.97, 0.52) → R:R=3.79).

**Removed 2026-06-20:** AUDNZD, EURUSD, AUDCHF, GBPNZD (directional instability). USDCAD/NZDUSD halved 5%→2.5%.

### Active
GC, USDCHF, USDCAD, ES, NQ, GBPCAD, NZDCAD, ^DJI, NZDUSD, GBPAUD, NZDCHF, CADCHF, AUDUSD, EURCHF, EURCAD, EURNZD, GBPCHF, GBPUSD, EURAUD

### Removed (post walk-forward, insufficient edge)
AUDCHF, AUDNZD, EURUSD, GBPNZD, CADJPY, CHFJPY, CL, USDJPY, BTCUSD, EURGBP, EURJPY, GBPJPY, AUDCAD, NZDJPY, ^VIX, IWM

## Services / Processes

| Service | Port | Purpose |
|---------|------|---------|
| Engine | — | Main trading loop (300s cycle) |
| Dashboard | 5000 | React SPA + JSON API endpoints |
| MT5 bridge | 9879 | Wine-hosted TCP bridge to MetaTrader 5 terminal |
| MT5 terminal | — | MetaTrader 5 under Wine + xvfb-run |

## ADRs

Architecture Decision Records in [`adr/`](adr/) — see [`adr/ADR-000-index.md`](adr/ADR-000-index.md) for the full list.

## Conventions

- ADRs follow the standard [Michael Nygard template](https://github.com/joelparkerhenderson/architecture-decision-record)
- All docs are written in Markdown
- `LIVE_CONTRACT.md` at the project root is the immutable system contract
