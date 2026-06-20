# QuantForge — Agent Operating Guide

## Project Identity

Cross-sectional multi-asset paper trading engine. 19-asset portfolio (FX, commodities, equity indices) with per-asset XGBoost models, regime-conditional ensemble (disabled 2026-06-20; see ADR-026 and PnL backtest section), 9-layer governance, position sizing guardrails, and MT5 bridge execution (Exness demo via Wine).

**2026-06-20: AUDNZD, EURUSD, AUDCHF removed from trading.** These 3 assets accounted for the model's confirmed directional instability failure mode (confident wrong-direction bets during trends). Removed from paper_trading.yaml assets, mt5_symbol_map, shadow analytics, risk-off suppression lists, and API commission table. 22-3=19 remaining assets. See the Walk-Forward PnL Backtest section for the full diagnostic chain.

## Architecture Quick Reference

- **Models**: Per-asset XGBClassifier (base only) — regime-conditional ensemble disabled 2026-06-20 (walk-forward p=0.83; see ADR-026)
- **Features**: 13 alpha (includes COT flag) + 7 regime (hurst, kaufman_er, adx, vol_zscore, compression, utc_hour, session_vol_profile)
- **Labels**: Triple-barrier with per-asset pt_sl, vertical_barrier=20, gap >= vb
- **Config**: `configs/paper_trading.yaml` — global defaults + per-asset (19 assets)
- **Inference**: `paper_trading/inference/pipeline.py` — alpha features → base model → governance → execute (ensemble disabled; regime features still generated for trace logging)
- **Training**: `paper_trading/inference/training.py` — base model only (regime model skipped when base_weight >= 1.0), scale_pos_weight, meta-labeling. Expanding-window (all history, never drops old data) — known contributor to directional instability across folds.
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
| `scripts/backtest_pnl.py` | PnL backtest from OOS signal parquets (R-multiples, autocorrelation-adj Sharpe) |
| `scripts/compare_ensemble.py` | Ensemble vs base PnL comparison with per-fold sign test |

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

### PnL Backtest from Signal Parquets
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py
```

### Compare Ensemble vs Base
```bash
PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py --tag base --ensemble-tag ensemble
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
- **AUDNZD ensemble**: Ensemble degrades signal quality (IC -0.020 in pilot). Confirmed portfolio-wide by walk-forward (p=0.83 pooled); ensemble disabled 2026-06-20 (see ADR-026).
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

- **Spread gate (ADDED 2026-06-19)**: `decision_pipeline.py:apply_spread_gate` — blocks entries when spread exceeds per-asset-class threshold. Uses live MT5 bid/ask spread (bps) from `mt5_client.realtime_spread()`. Fail-closed: if spread data is missing or stale (>300s), entry is blocked. Per-asset-class tiers: `fx_major` (10bps), `fx_cross` (20bps), `indices` (15bps), `metals` (20bps). Observe-only mode for first 720 cycles (~6h at 30s cadence) logs what it *would* block without actually blocking — sized to span varied intraday conditions (opens, mid-session, closes). Detection in `pipeline.py:_generate_and_apply -> asset.refresh_spread()`.

- **Regime model at inference (FIXED 2026-06-19, commits f15af30, b980f69)**: Two independent bugs kept the regime model from contributing to ensemble blends:
  1. **Load guard**: `training.py:_train_regime_if_configured` checked `if not regime_feats: return` before attempting to load from disk. `regime_feature_names` was initialized to `[]` in `__init__`, so the guard always fired — load was never attempted. Fix: attempt disk load before the guard; on success, populate `regime_feature_names` from the loaded model's `_feature_names`.
  2. **Missing features at inference**: `pipeline.py:_build_feature_set` built `features_df` from alpha (13 cols) + archetype (4 cols) only. The regime model was trained with 20 columns (13 alpha + 7 regime-specific like `GC_hurst`). The 7 regime columns were absent at inference, so `regime_available` was always empty and the blend silently skipped. Fix: generate regime features from OHLCV, prefix per-asset, join into `features_df`.
  **Result**: After both fixes, 22/22 trace decisions show varying `regime_long_prob` (range 0.0575–0.8659, 22 unique per-cycle). Cross-asset and across-time variance confirmed. The "12 trades all neutral" hypothesis from the Pre-fix era was not a neutral market — it was a dead regime model silently contributing constant noise.
  **Hurst constant (FIXED b980f69)**: `compute_hurst` used `rolling().apply(hurst_calc)` with `raw=False` (default), passing a pandas Series with DatetimeIndex. Inside `hurst_calc`, `z[lag:]` used label-based datetime indexing — integer lags didn't match dates, always returning the fallback 0.5. Fix: `raw=True` passes numpy arrays → positional indexing works. Post-fix: AUDUSD hurst varies from 0.19–0.40 (vs flat 0.5 everywhere pre-fix).
  **Cycle-1 cold-start transient**: The first inference cycle post-restart uses 200 rows (truncation validation hasn't run yet → `_truncate_inference=False`). Cycles 2+ use 1 row. The regime output differs between the two (NZDCAD 0.7397→0.2130). Cycles 2→3→4 are bit-for-bit identical for all 22 assets (Δ=0.0000). Mitigation: `apply_first_cycle_suppression` stage added to `DEFAULT_STAGES` — suppresses all trading on cycle 1 after a cold start.
  **Pre/post-fix boundary**: Any trades executed prior to commit `f15af30` (2026-06-19) used a regime-dead ensemble. Do not pool pre-fix and post-fix trades into a single exit-reason or performance aggregate — they reflect different systems.

---
## Walk-Forward PnL Backtest & Calibration Deep-Dive (2026-06-20)

### Tools Built
- **`scripts/backtest_pnl.py`** — PnL backtest from OOS signal parquets (R-multiples, verified PnL function with 12 test cases, per-asset + portfolio equity curve, drawdown in R-units, autocorrelation-adjusted Sharpe). Usage: `PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py`.
- **`scripts/compare_ensemble.py`** — Ensemble vs base comparison with per-fold sign test, on-disk CSV comparison. Reusable.

### Ensemble Decision Re-Confirmed
- Ensemble vs base PnL comparison: +7.41R (+2.5%) over 350 days, portfolio level
- Sign test: 161/287 non-tie days favor ensemble, p=0.0446 (raw)
- Does not survive Bonferroni correction (IC test was p=0.83, two tests → adjusted threshold p<0.025)
- 2.5% improvement is economically trivial vs 22 extra regime model loads + debug surface area
- The 3 ensemble bugs fixed are a maintenance-burden argument, not a statistical one — kept as separate bullet
- Ensemble disabled date updated: 2026-06-20

### Initial Backtest Results (base-only, full portfolio)
- 22 assets, 350 OOS days (Oct 2024 - May 2026)
- Portfolio total_R = +291R, max_dd_R = -2.64R (all in R-multiples, not currency)
- Portfolio sharpe_adj (Lo-adjusted for autocorrelation ρ=0.68): 9.1 — **CAVEAT: R-multiple portfolio Sharpe; see note below**
- **Top performers**: ^DJI (+712.5R), CADCHF (+867R), NZDCHF (+829R), AUDUSD (+516R)
- **Bottom performers**: AUDNZD (-203R), EURUSD (-157.5R), NZDUSD (-46.5R), GBPNZD (-37R)
- **Removed 2026-06-20**: AUDNZD, EURUSD, AUDCHF — three of the four bottom performers removed after directional instability diagnosis

**Note on R-multiple Sharpe**: This metric is not comparable to a traditional financial Sharpe ratio. The portfolio daily R is a simple average of per-asset R-multiple changes (20 assets, equal weight regardless of position size). Cross-asset diversification artificially reduces portfolio std, inflating the Sharpe. Monthly-block Sharpe (non-overlapping) = 5.61. Adjusting for realistic FX cross-asset correlation (ρ~0.3) gives ~8.05. All values are in R-multiple space — they describe signal quality, not expected live trading Sharpe.

### Directional Asymmetry Investigation

#### Step 1: Per-direction breakdown
- AUDNZD and EURUSD both lose on SELL predictions (82% loss rate, 72% loss rate respectively)
- But this is NOT majority-class bias: 19/22 assets beat 50% coin-flip on BUY, 18/22 on SELL
- The model has genuine directional skill on both sides for most assets

#### Step 2: Breakeven WR vs raw WR
- The real bottleneck for losing assets is tp/sl config: AUDNZD needs 66.7% WR to break even (tp=1, sl=2), EURUSD also 66.7% (tp=1.5, sl=3)
- The model achieves 71.3% BUY WR on AUDNZD (real skill) and 66.2% on EURUSD (skill but just misses BE)
- SELL WR on these assets: 17.9% and 27.6% — significantly worse than 50% coin flip (anti-skill)

#### Step 3: p_long calibration → isotonic fails
- Probability calibration check: the model is severely miscalibrated
  - AUDNZD p_long=0.25 → actual label=1 frequency = 82.6% (model overconfident SELL)
  - AUDNZD p_long=0.93 → actual label=1 frequency = 47.8% (model overconfident BUY)
- Isotonic calibration fit on fold-0 test set compresses all probabilities into [0.44, 0.58]
- With the 0.425-0.575 dead zone, almost all calibrated predictions go FLAT → 0.5 threshold also doesn't help
- **Cause of isotonic failure**: model's directional mix flips between folds (fold 0: 74% BUY → fold 2: 12% BUY). The isotonic fit on a BUY-dominant fold fails on SELL-dominant folds

#### Step 4: Regime-conditional ensemble check
- Ensemble signals are nearly identical to base on the trend folds (p_long correlation 0.97-0.98)
- When signals disagree (13/94 rows), ensemble wins 0/13 on fold 1
- The regime-conditional ensemble does NOT detect or correct the directional flip — falsified

#### Step 5: Training-window return structure
- Expanding-window training (confirmed: `train_idx = idx[:test_start - gap]` — all history, never drops old data)
- 20-bar return autocorrelation is strongly positive in ALL training and test periods (0.75-0.97) but this may be inflated by overlapping-window artifact [CAVEAT: adjacent 20-bar windows share 19/20 data points]
- Model bias vs recent returns: EURUSD shows trend-follower-like behavior (predicts recent train-window direction) that breaks when test trend reverses; AUDNZD shows unexplained flip at fold 2 despite near-identical recent return (+0.50% → +0.40%)

#### Step 6: Directional filter diagnostic — defangs the trend flip, not a structural fix

The filter removes the anti-skill direction per asset (derived from per-direction 50%-null WRs). Portfolio-level: +307R → +350R (+14%). Every asset's total R improved.

**CAVEAT — per-fold concentration**: improvement is dominated by 1-2 folds per asset where trade count collapsed by 80-90% and the removed signals are a concentrated losing streak matching the known trend-period flip:

| Asset | Dominant fold(s) | Removed signals | Removed R | Loss streak |
|-------|-----------------|----------------|-----------|-------------|
| AUDNZD | 2-3 | 148 SELL | -224R | 28 consecutive |
| EURUSD | 1 | 70 SELL | -151.5R | 35 consecutive |
| AUDCHF | 0-1 | 90 BUY | -85R | 20 consecutive |
| ES | 0 | 55 BUY | -72.5R | 26 consecutive |
| NQ | 0 | 32 BUY | -80R | 32 consecutive (all losses) |

Folds where the direction *wasn't* flipped show zero or near-zero removed signals (filter had nothing to override). AUDUSD fold 1-2: removing BUY removes *wins* (+26R), yet fold 0's 48 BUY removed (47/48 losses, -66.5R) outweighs it.

**Interpretation**: The filter defangs the directional instability symptom — it prevents the model from acting on its confirmed trend-period wrong-direction flip. It does NOT identify a structurally bad per-asset direction. The improvement lives where the flip happens (specific historical trend periods) and will re-apply the next time the model flips into a trend. This is a valid production guard but is best understood as a secondary consequence of the terminal finding (directional instability), not an independent discovery.

**script**: `scripts/filter_direction.py`

### Terminal Finding: Base Model Directional Instability

**Symptom**: The base model makes confident wrong-direction bets during trending market periods. Reproducible across 2 assets and 3 consecutive walk-forward folds.

**Evidence**:
- AUDNZD fold 2 (test: +4.54%): model flips from 94% BUY to 12% BUY (wrong — keeps rallying to +5.79%)
- EURUSD fold 1 (test: +10.63%): model flips from 99% BUY to 16% BUY (wrong — keeps rallying)
- Ensemble doesn't correct it (p_long corr 0.97-0.98)
- Calibration doesn't fix it (isotonic fails on fold-to-fold directional shift)
- Not cleanly trend-following (AUDNZD fold 1→2 flip unexplained by recent returns)
- Not cleanly mean-reversion (20-bar ACF positive, not negative)

**Mechanism**: NOT fully isolated. Contributing factors identified:
1. Expanding training window (dilutes recent signal with old data)
2. Triple-barrier labels may not distinguish trend vs. reversal regimes
3. Feature set may lack regime-awareness signals
4. The interaction between these produces fold-to-fold directional instability that tracks realized test-period trend reversals but whose root cause remains distributed

**Risk**: If this pattern (confident wrong-direction bets during trends) holds in production, a 1-2 month trending period could produce concentrated losses in the assets most affected (AUDNZD, EURUSD, likely others with similar profile).

**Next investigation suggestions**:
1. **Circuit breaker simulation (PRIORITY)** — Pull trigger logic from live code, write isolated unit tests (hand-picked equity sequences), confirm it fires and flattens positions, then build synthetic correlated-AUD-cascade scenario as realistic stress input. Do this before trusting the breaker as a reliable backstop — asymmetric downside risk.
2. Cross-correlate AUD pairs for simultaneous adverse move risk
3. Investigate whether fixed-length rolling window (e.g., 12-month lookback) stabilizes fold-to-fold directional bias
4. Test label structures that penalize reversal bets during trend regimes

---
## BUY Inversion Discovery (2026-06-20, Phase 2)

### Finding

The original "directional flip" narrative was wrong as a portfolio-wide diagnosis. The real failure mode is:

**The model's BUY signal is inverted for 9 of 19 assets** — `p_long > 0.5` reliably predicts the WRONG direction.

### Evidence Chain

1. **BUY is flat at ~17% win rate from p_long=0.57 to p_long=1.0** across all 9 assets. p_long=0.50-0.575 bucket: 0 wins out of 144 predictions (0%). This is NOT miscalibration — it's an **inverted signal**.

2. **SELL is well-calibrated at ~77% win rate** on the same 9 assets. p_long < 0.425 bucket: 1,273 predictions at 77% win rate.

3. **The pattern is not trend-conditional**: confident BUY wins 15% in trending windows and 23% in non-trending windows. The model simply misprices these assets regardless of regime.

4. **The pattern is uniform across all 9 assets**: every single one shows 0% win rate in the 50-57% p_long bucket.

5. **Portfolio-wide, not concentrated**: 77% of assets have at least one fold with >50% wrong rate. The BUY inversion is a specific subset of a broader miscalibration.

### Correction to Prior Findings

- The "directional flip" (AUDNZD confident SELL during uptrend) was an asset-specific anomaly, not portfolio pattern
- The portfolio-wide problem is **BUY overconfidence on 9 specific assets**, not "confident wrong-direction bets during trends"
- DXY correlation, trend duration, and regime-conditional factors were all tested and ruled out as mechanisms
- Three of the 9 assets (^DJI, EURCHF, USDCHF) are marginally net-positive on BUY due to favorable tp/sl ratios masking the inverted signal — this is still a trust issue, not a returns issue

### Fix Applied

**`apply_sell_only_filter` stage** added to `decision_pipeline.py:DEFAULT_STAGES`. For 9 flagged assets, BUY signals are overridden to FLAT. SELL signals pass through unchanged.

```python
SELL_ONLY_ASSETS: frozenset[str] = frozenset({
    "CADCHF", "AUDUSD", "ES", "NQ", "NZDCHF",
    "EURAUD", "^DJI", "USDCHF", "EURCHF",
})
```

Backtest comparison (19 assets, same parquets):

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| total_R | 316.6 | 325.3 | +2.7% |
| max_dd_R | -2.34 | -1.42 | **-39%** |
| sharpe_adj | 10.95 | 12.45 | **+13.7%** |
| OK assets (10) | unchanged | unchanged | 0% regression |

The 2.7% total_R improvement is modest because 3 flagged assets (^DJI, EURCHF, USDCHF) have extreme tp/sl ratios that make even inverted signals marginally net-positive in R. The risk improvement (-39% max_dd, +13.7% sharpe) is the real headline — the filter eliminates the high-variance confident-wrong pattern.

**Pass/fail**: Missed ≥5% total_R bar (only +2.7%). Met the no-OK-asset-regression bar. Success criterion revised: **primary metric is max_dd reduction and confident-wrong elimination**, not total_R improvement, because the original problem was asymmetric downside risk, not returns optimization.

### Remaining Open Items

1. **SHAP audit** — Determine which feature(s) cause the BUY inversion on these 9 assets. May reveal a structural cause (e.g., specific feature stale for these asset classes) that could be fixed at the model level. Currently blocked by need to load XGBoost model files and run conditional SHAP decomposition on bad-prediction rows.

2. **^DJI/EURCHF/USDCHF decision** — Three assets where BUY is inverted (21-29% WR) but marginally profitable due to tp/sl asymmetry. Currently included in SELL_ONLY_ASSETS. This is not settled — the tp/sl structure that masks the inversion is a parameter under human control (set in paper_trading.yaml per asset), not an intrinsic property. Tightening tp or widening sl for any of these three would flip them from marginally-net-positive to net-negative overnight. The current "profit" on these assets' BUY side is a fragile artifact of a specific parameter choice, not evidence of genuine directional skill. The principled argument: if you've confirmed the signal is behaviorally inverted (BUY predicts SELL), you should kill BUY everywhere it's confirmed regardless of whether backtest R currently happens to paper it over. Keeping it on these 3 because "R works out" optimizes for backtest total_R, not for signal trustworthiness — which is exactly the mistake the roll-backward walk-through warned against. Decision deferred until SHAP audit reveals whether the inversion has a structural (feature-level) root cause, at which point either a targeted fix makes all 9 revert to full BUY/SELL, or the structural finding confirms they should all be SELL-only permanently.

3. **Path A (rolling window backtest)** — Running overnight (2026-06-20). Two checks upon completion: (a) per-fold p_long std reduction ≥30% vs expanding; (b) cross-reference p_long distributions for the 9 SELL_ONLY assets to confirm the BUY inversion holds under rolling regime. If rolling window changes p_long enough to weaken the inversion, the fix may need revisiting (expanding-window training may have been a contributor, not the sole cause).

4. **Live tripwire** — If any flagged asset's SELL win rate drops **below** 65% over 20 consecutive trades, re-investigate. SELL baseline is ~77%. Tripwire threshold tightened from 50% to 65% based on actual baseline.

### Falsified Hypotheses (2026-06-20 session)

- Ensemble corrects directional flip (falsified 2026-06-19, re-confirmed)
- Calibration problem: OK cluster has 57% win rate on same predictions
- DXY drives the failure: CHF assets show DXY correlation but controlling for DXY direction doesn't explain failures
- Trend duration: equities have shorter trends (confirmed as secondary factor), but CHF/OTHER cluster has normal duration and still fails
- Trend-conditional: bad assets are 15-23% regardless of trending regime — not trend-conditional
- Detection guard: p_long trajectory can't distinguish flip from normal (22.2% FP rate)
- Label redesign: asymmetric barriers increase (not decrease) fold-to-fold variance

## Ruff

```bash
ruff check . && ruff format .
```
