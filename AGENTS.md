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
- **Ensemble breakdown logger column prefix (FIXED 2026-06-19)**: `_log_ensemble_breakdown` used `f"{asset_name_u}_carry_vol_adj"` but actual feature columns use `CLOSE_` prefix (from `prices.to_frame("close")`). All feature contributions logged as NaN. Fixed in `paper_trading/inference/pipeline.py:302`.
- **Carry feature always zero (FIXED 2026-06-19)**: `rate_diffs` DataFrame in `data_fetch.py:442` used `asset_name` column key, but `build_alpha_features` looks up by `"close"` — so rate_diff lookup always failed and carry was `pd.Series(0.0)`. Affected all assets, both training and inference (same code path), so no training-inference mismatch — carry was simply inert. Fixed column name to `"close"`.
- **Bar-jump suppression (ADDED 2026-06-19)**: `decision_pipeline.py:apply_bar_jump_suppression` — suppresses all trading for 60 minutes when bar count changes >100 (indicating data-source switch). Stage 0 in DEFAULT_STAGES. Detection in `pipeline.py:_detect_bar_jump()`.
- **Risk-off suppression for AUDUSD/AUDCHF (ADDED 2026-06-19)**: `decision_pipeline.py:apply_risk_off_suppression` — holds flat for AUDUSD/AUDCHF when VIX is rising (>0) and SPX is falling (<0). Detection in `pipeline.py:_detect_risk_off()` via `features_df["vix_mom_5d"]` and `features_df["spx_mom_5d"]`. Stage after `resolve_signal` in DEFAULT_STAGES.
- **Risk-off consequence validated (2026-06-19)**: Checked 63 trading days (3 months) — risk-off (VIX>0 & SPX<0) occurred on 12 days vs the 1 live episode. AUDUSD always-long accuracy: 8.3% on risk-off days vs 54.9% on normal days. Mean-reversion (oversold→BUY) accuracy: 14.3% (1/7) on risk-off+oversold vs 100% on normal+oversold (2/2). Consequence generalizes — the suppression rule is not tuned to one episode.
  **Note on methodology:** This finding is *not* based on counting intraday prediction cycles. It was validated using daily-resolution historical price action (63 daily bars × independent forward returns), so it is exempt from the per-cycle-counting artifact that debunked the three-mechanism taxonomy below. The two conclusions came from different evidentiary standards.
- **Prediction taxonomy (CORRECTED 2026-06-19)**: Earlier taxonomy claimed three distinct failure mechanisms across five assets. That taxonomy was based on *per-cycle* accuracy (each ~30s engine cycle counted as an independent prediction), which amplified a 1-2 day directional miss into "hundreds of wrong predictions." A daily-bar XGBoost model updates once per day; ~500 intraday cycles all reproduce the same daily signal. The live window was **3 calendar days (Jun 17-19)**. Honest per-day accuracy:

  | Asset | Daily acc | Days | Actual best description |
  |-------|-----------|------|------------------------|
  | AUDUSD | 0/2 (0%) | 2 | **CONFIRMED** — risk-off degrades mean-reversion (validated across 12 independent risk-off episodes over 3 months of historical data). Risk-off suppression addresses this. |
  | AUDCHF | 2/2 (100%) | 2 | Fine at daily level. Earlier "risk-off failure" was micro-PnL noise, not directional failure. |
  | NZDUSD | 0/2 (0%) | 2 | **Watch**: same direction as AUDUSD's risk-off failure (both wrong on BUY) but unconfirmed. Re-check once more days accumulate. |
  | EURUSD | 1/3 (33%) | 3 | Flipped to SELL on Jun 18 and was correct, but 2/3 wrong overall. Too little data to distinguish real flip-detection from chance. |
  | GBPNZD | 1/2 (50%) | 2 | Coin flip over 2 days. Earlier "opposite pattern" was overinterpretation. |
  | AUDNZD | 2/2 (100%) | 2 | Correct — control asset works. |
  | CADCHF | 1/3 (33%) | 3 | Low accuracy but predicts both directions. Underdetermined. |
  | EURAUD | 1/3 (33%) | 3 | Low accuracy, both directions. Underdetermined. |

  **Only AUDUSD risk-off suppression is a validated claim.** All other "globally wrong" / "confidence-independent" / "risk-off dependent" labels were per-cycle counting artifacts. NZDUSD (0/2, never flipped) is the only remaining genuine concern, but 2 days does not support a mechanism claim.

  **Label barrier-asymmetry hypothesis (2026-06-19) — FALSIFIED**: Testing showed no correlation between TP/SL ratio and prediction accuracy. AUDNZD has the most BUY-biased labels (3.7x ratio of BUY:SELL labels) yet predicts 95% correctly. NZDUSD has nearly balanced labels (1.2x ratio) yet predicts 0% correctly. AUDUSD has SELL-biased labels (0.36x) yet the model predicts BUY — going against the label distribution. The model learns the actual training-period trend, not the barrier geometry.

- **Retrain with carry (2026-06-19)**: All 22 assets retrained after carry bug fix (carry was always zero). Carry is now 8-16% of feature importance across key FX assets. Post-retrain historical replay against 13 risk-off episodes shows:
  - **AUDUSD**: Risk-off accuracy improved from 8.3%→38.5% but still lags normal (54.0%). Suppression still justified.
  - **AUDCHF**: Risk-off accuracy 38.5% vs normal 58.0%. Model more confidently BUY on risk-off (P=0.709 vs 0.652). Suppression still needed.
  - **GBPNZD**: Normal-day accuracy jumped from ~1%→62%. The "opposite pattern" was a carry-deprivation artifact — no longer deferred.
  - **NZDUSD/EURUSD**: No clean historical shortcut — paper-only observation required. Minimum 10 trading days before any directional conclusion.

  **Note on AUDCHF carry entanglement**: Carry being #3 feature (10.7%) made AUDCHF's risk-off failure *more* pronounced (P=0.709 on risk-off vs 0.652 normal), not less. Possible mechanism: carry trade unwinds are a classic feature of real risk-off episodes; a model now using carry more heavily may be doubling down on a carry-trade-direction read that reverses during risk-off. Worth investigating if revisiting the risk-off mechanism.

- **Signal chatter + MT5 orphaned positions (FIXED 2026-06-17)**: fixes applied:
  - (1) `decision_pipeline.py:apply_signal_stability_filter` — margin widened 0.05→0.15, now checks max(prob_long, prob_short). Requires >0.65 conviction on either side to proceed.
  - (2) `decision_pipeline.py:apply_signal_hysteresis` (NEW) — 2-of-3 signal agreement required before a flip is allowed.
  - (3) `decision_pipeline.py:manage_position` — `_can_enter()` checked BEFORE `_close_position()`. If cool-down blocks re-entry, old position is kept open.
  - (4) `engine_state_service.py` — `mt5_ticket` now persisted in snapshot.
   - (5) `position_service.py` — MT5 close failures logged as ERROR with "position may be orphaned".

- **pipeline.py indentation nesting (FIXED 2026-06-19)**: `_detect_bar_jump()` was accidentally defined at module level (0 indent) between `_ensure_ready()` and all remaining class methods. Everything from `_fetch_and_prepare_data` onward (16 methods, lines 119-577) was nested inside `_detect_bar_jump` as local inner functions instead of being class methods. This meant none of those methods were callable from `_generate_and_apply`. Fix: indented `_detect_bar_jump` by 4 spaces (class method) and changed the call site from `_detect_bar_jump(asset, ...)` to `self._detect_bar_jump(asset, ...)`.

- **Spread gate (ADDED 2026-06-19)**: `decision_pipeline.py:apply_spread_gate` — blocks entries when spread exceeds per-asset-class threshold. Uses live MT5 bid/ask spread (bps) from `mt5_client.realtime_spread()`. Fail-closed: if spread data is missing or stale (>300s), entry is blocked. Per-asset-class tiers: `fx_major` (10bps), `fx_cross` (20bps), `indices` (15bps), `metals` (20bps). Observe-only mode for first 10 cycles logs what it *would* block without actually blocking. Detection in `pipeline.py:_generate_and_apply -> asset.refresh_spread()`.

## Ruff

```bash
ruff check . && ruff format .
```
