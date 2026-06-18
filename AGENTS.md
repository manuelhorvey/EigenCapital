# QuantForge — Agent Operating Guide

## Project Identity

Cross-sectional multi-asset paper trading engine. 21-asset portfolio (FX, commodities, equity indices) with per-asset XGBoost models, regime-conditional ensemble, 9-layer governance, position sizing guardrails, and MT5 bridge execution (Exness demo via Wine).

## Architecture Quick Reference

- **Models**: Per-asset XGBClassifier (base) + RegimeConditionalModel (regime) — 60/40 ensemble blend
- **Features**: 13 alpha (includes COT flag) + 7 regime (hurst, kaufman_er, adx, vol_zscore, compression, utc_hour, session_vol_profile)
- **Labels**: Triple-barrier with per-asset pt_sl, vertical_barrier=20, gap >= vb
- **Config**: `configs/paper_trading.yaml` — global defaults + per-asset (21 assets)
- **Inference**: `paper_trading/inference/pipeline.py` — alpha → regime → base model → regime model → ensemble → governance → execute
- **Training**: `paper_trading/inference/training.py` — base + regime models, scale_pos_weight, meta-labeling
- **Entry gates**: `entry_service.py` price deviation check (skips if price deviated > max_entry_slippage_pct); `decision_pipeline.py` profit lock (blocks flips when unrealized PnL > profit_lock_threshold_pct)
- **Position sizing guardrails**: Drawdown taper, per-position equity cap, risk-per-trade cap, portfolio leverage budget (atomic lock), backstop decay multiplier
- **Independent MT5 sizing**: Paper sized from paper equity ($100K mtm_value); MT5 sized from real broker account balance via `_compute_mt5_qty()` with its own drawdown taper + risk cap
- **Orchestrator**: `EngineOrchestrator` (ThreadPoolExecutor, 8 workers), 3-phase cycle (signal → entry → backstop)
- **MT5 Bridge**: `paper_trading/ops/mt5_client.py` — TCP frame protocol to Wine-hosted MT5 (port 9879)
- **Dashboard**: React SPA on port 5000, state via `state.json`

## Key Files

| File | Purpose |
|------|---------|
| `configs/paper_trading.yaml` | All config (capital, assets, SL/TP, depth, regime_geometry, sizing guardrail defaults) |
| `paper_trading/engine.py` | `PaperTradingEngine` — main loop, capital sync, parallel orchestrator |
| `paper_trading/asset_engine.py` | `AssetEngine` — per-asset lifecycle, train(), generate_signal() |
| `paper_trading/inference/training.py` | `AssetTrainingPipeline` — base + regime model training |
| `paper_trading/inference/pipeline.py` | `AssetInferencePipeline` — live inference with ensemble |
| `paper_trading/inference/regime_model.py` | `RegimeConditionalModel` — per-asset regime classifier |
| `paper_trading/inference/ensemble.py` | `EnsembleSignal` — 60/40 blend logic |
| `paper_trading/ops/monitor.py` | Main entry point — loads models, runs engine, serves dashboard |
| `paper_trading/execution/decision_pipeline.py` | Decision pipeline stages — includes profit lock gate |
| `paper_trading/services/entry_service.py` | Entry validation, full sizing chain (drawdown taper → position cap → risk cap → leverage budget), price deviation gate |
| `paper_trading/orchestrator/engine.py` | `EngineOrchestrator` — phases 1-3 (parallel signal, atomic entry, portfolio backstop) |
| `paper_trading/execution/mt5_broker.py` | `MT5Broker` — MT5 execution with `current_mt5_drawdown_pct()` |
| `features/alpha_features.py` | Alpha feature builder (13 cols) |
| `features/regime_features.py` | Regime feature builder (7 cols) |
| `features/data_fetch.py` | Data fetching with MT5/yfinance fallback |
| `features/labels.py` | Triple-barrier labeling + PurgedWalkForwardFolds |
| `LIVE_CONTRACT.md` | Immutable system contract (update when architecture changes) |

## Position Sizing Chain

Paper positions are sized through multiplicative guardrails:

```
effective_cap = capital_base × min(mtm / initial_capital, 3.0)
size_scalar = base × exposure × governance × meta × drawdown_taper
notional = effective_cap × size_scalar
→ cap by max_position_pct_of_equity
→ cap by risk_per_trade_pct (skip if below min_viable_position_pct)
→ atomic decrement from shared leverage_budget (lock-protected)
```

MT5 positions are sized independently:

```
mt5_equity = broker.get_account_summary().portfolio_value
notional = mt5_equity × max_position_pct_of_equity × drawdown_taper
→ cap by risk_per_trade_pct (skip if below min_viable)
→ validate min volume via _quantity_to_lots()
```

Log lines: `SIZING` (paper) and `MT5_SIZING` (MT5) with all decomposed factors.

## Common Tasks

### Run Paper Trading
```bash
PYTHONPATH=$PYTHONPATH:. python paper_trading/ops/monitor.py
```

### Full Launcher (MT5 + Dashboard)
```bash
./monitor_all
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
- **Small MT5 equity ($107 demo)**: 0.01 lot minimum for forex (≈$1,150 notional on EURUSD) far exceeds the MT5 position budget (≈$15.67 at 15% of $104). MT5 positions quantize to 0.01 lots regardless of computed size. Leverage budget is deferred for MT5 — revisit when equity > $10K.
- **Leverage budget deferred for MT5**: 0.01 lot granularity makes desired-vs-actual notional diverge wildly for small accounts. No leverage cap check on MT5 side until equity supports meaningful multi-position sizing.
- **SL/TP triple bug (FIXED 2026-06-16)**: Three independent issues (deactivated `atr_mult_tp`, uncalibrated `atr_mult_sl`, TP compiler convexity applied to inflated SL distance) produced TP distances up to 44%. Fixes: (1) `_atr_barriers()` now uses `atr_mult_tp` for TP vol basis, (2) `tp_compiler.py` caps R:R at `MAX_RR=5.0`.
- **THIN liquidity (FIXED 2026-06-17)**: THIN regime was routing to hard_reasons (halted all assets). Fixed: only STRESSED halts; THIN → soft_warnings (SL/size adjust, no halt).
- **Prob drift min samples (FIXED 2026-06-17)**: Raised from 3 to 10 for stable mean estimate before confidence drift halt check activates.
- **Entry price deviation gate (ADDED 2026-06-17)**: `entry_service.py` compares `asset.current_price` to signal `entry_price` before submitting. Skips if deviation > `max_entry_slippage_pct` (default 2%).
- **Profit lock gate (ADDED 2026-06-17)**: `decision_pipeline.py` checks unrealized PnL before flipping. Blocks flip if PnL > `profit_lock_threshold_pct` (default 15%).
- **Position sizing guardrails (ADDED 2026-06-17)**: drawdown taper (linear between start_dd/end_dd), per-position equity cap, risk-per-trade cap, portfolio leverage budget (atomic lock decrement), backstop decay (penalty × 0.9/cycle on breach-free cycles).
- **Independent MT5 sizing (ADDED 2026-06-17)**: MT5 computes own qty from broker equity with separate drawdown taper and risk cap. Paper sizing unchanged at $100K equity.
- **Signal chatter + MT5 orphaned positions (FIXED 2026-06-17)**: fixes applied:
  - (1) `decision_pipeline.py:apply_signal_stability_filter` — margin widened 0.05→0.15, now checks max(prob_long, prob_short). Requires >0.65 conviction on either side to proceed.
  - (2) `decision_pipeline.py:apply_signal_hysteresis` (NEW) — 2-of-3 signal agreement required before a flip is allowed.
  - (3) `decision_pipeline.py:manage_position` — `_can_enter()` checked BEFORE `_close_position()`. If cool-down blocks re-entry, old position is kept open.
  - (4) `engine_state_service.py` — `mt5_ticket` now persisted in snapshot.
  - (5) `position_service.py` — MT5 close failures logged as ERROR with "position may be orphaned".


## Ruff

```bash
ruff check . && ruff format .
```
