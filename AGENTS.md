# QuantForge — Agent Operating Guide

## Project Identity

Cross-sectional multi-asset paper trading engine. 21-asset portfolio (FX, commodities, equity indices) with per-asset XGBoost models, regime-conditional ensemble, 7-layer governance, and MT5 bridge execution (Exness demo via Wine).

## Architecture Quick Reference

- **Models**: Per-asset XGBClassifier (base) + RegimeConditionalModel (regime) — 60/40 ensemble blend
- **Features**: 13 alpha (includes COT flag) + 7 regime (hurst, kaufman_er, adx, vol_zscore, compression, utc_hour, session_vol_profile)
- **Labels**: Triple-barrier with per-asset pt_sl, vertical_barrier=20, gap >= vb
- **Config**: `configs/paper_trading.yaml` — global + per-asset (21 assets)
- **Inference**: `paper_trading/inference/pipeline.py` — alpha → regime → base model → regime model → ensemble → governance → execute
- **Training**: `paper_trading/inference/training.py` — base + regime models, scale_pos_weight, meta-labeling
- **MT5 Bridge**: `paper_trading/ops/mt5_client.py` — TCP frame protocol to Wine-hosted MT5 (port 9879)
- **Dashboard**: React SPA on port 5000, state via `state.json`

## Key Files

| File | Purpose |
|------|---------|
| `configs/paper_trading.yaml` | All config (capital, assets, SL/TP, depth, regime_geometry) |
| `paper_trading/engine.py` | `PaperTradingEngine` — main loop, capital sync, parallel orchestrator |
| `paper_trading/asset_engine.py` | `AssetEngine` — per-asset lifecycle, train(), generate_signal() |
| `paper_trading/inference/training.py` | `AssetTrainingPipeline` — base + regime model training |
| `paper_trading/inference/pipeline.py` | `AssetInferencePipeline` — live inference with ensemble |
| `paper_trading/inference/regime_model.py` | `RegimeConditionalModel` — per-asset regime classifier |
| `paper_trading/inference/ensemble.py` | `EnsembleSignal` — 60/40 blend logic |
| `paper_trading/ops/monitor.py` | Main entry point — loads models, runs engine, serves dashboard |
| `features/alpha_features.py` | Alpha feature builder (13 cols) |
| `features/regime_features.py` | Regime feature builder (7 cols) |
| `features/data_fetch.py` | Data fetching with MT5/yfinance fallback |
| `features/labels.py` | Triple-barrier labeling + PurgedWalkForwardFolds |
| `LIVE_CONTRACT.md` | Immutable system contract (update when architecture changes) |

## Common Tasks

### Run Paper Trading
```bash
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/monitor.py
```

### Retrain All Assets
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/retrain_all_fixed.py
```

### Train Regime Models
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/train_regime_models.py
```

### Walk-Forward Backtest (diagnostic)
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/walk_forward_backtest.py --asset EURUSD
```

### Daily Monitoring
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/monitor_paper_trading.py
```

### Check Dashboard
```bash
curl http://127.0.0.1:5000/state.json | python3 -m json.tool
```

## Go/No-Go Checklist (Paper Trading → Live)

| Check | Target | Source |
|-------|--------|--------|
| Gate override rate | <40% all assets | monitor csv |
| Mean confidence | >0.52 for ≥18/21 | monitor csv |
| Signal flips | ≤3/day for ≥18/21 | monitor csv |
| Cross-asset correlation | no unexplained >0.7 | monitor csv |
| MT5 errors | zero | engine logs |
| Trades executed | ≥10 across portfolio | MT5 terminal |

6/7 pass → go live at 50% position size for 2 weeks, then full size if live Sharpe tracks within 0.2 of backtest Sharpe.

## Known Issues

- **GBPNZD**: `DX-Y.NYB` (DXY) data not available on some MT5 brokers. Options: fix DXY source (A), zero-fill DXY features (B), exclude from go-live (C — recommended).
- **AUDNZD ensemble**: Ensemble degrades signal quality (IC -0.020 in pilot). Monitor during paper trading; disable per-asset if confirmed.
- **Futures (ES, NQ, GC, ^DJI)**: OHLCV-dependent features (regime) require `fetch_asset_ohlcv()` which works on all assets.
- **SL/TP triple bug (FIXED 2026-06-16)**: Three independent issues (deactivated `atr_mult_tp`, uncalibrated `atr_mult_sl`, TP compiler convexity applied to inflated SL distance) produced TP distances up to 44%. Fixes: (1) `_atr_barriers()` now uses `atr_mult_tp` for TP vol basis, (2) `tp_compiler.py` caps R:R at `MAX_RR=5.0`. Restarted engine post-fix.

## Ruff

```bash
ruff check . && ruff format .
```
