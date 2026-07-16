# LIVE SYSTEM CONTRACT — IMMUTABLE SOURCE OF TRUTH

This file defines the exact behavior of the production paper trading system.
Any deviation from this contract is a trading bug.
Changes require full regression validation.

## 1. MODEL CONTRACT

**Type:** `xgboost.XGBClassifier`
**Objective:** `binary:logistic`
**Architecture:** Binary classifier (HOLD dropped, {-1, 1} mapped to {0, 1})
**Constructor:**
```
n_estimators=300, max_depth=<per-asset>, learning_rate=0.02,
objective='binary:logistic', scale_pos_weight=imbalance_ratio,
random_state=42, n_jobs=1, tree_method='hist', verbosity=0,
early_stopping_rounds=50
```
**Per-asset max_depth:**
| Depth | Assets |
|-------|--------|
| 2 | GC (rolled back from 4), NZDCAD, NZDUSD, NZDCHF, GBPCHF (rolled back from 4), AUDJPY, NZDJPY, GBPJPY, USDJPY |
| 3 | USDCAD, GBPAUD, CADCHF, EURCAD, BTCUSD |
| 4 | USDCHF, EURCHF, GBPUSD, ^DJI |
| 5 | GBPCAD, AUDUSD, EURNZD, EURAUD |

**Signature:** `model.predict(X: pd.DataFrame) -> np.ndarray`
**Output shape:** `(N, 1)` — raw probability of LONG class
**Pipeline expansion:** Raw output is expanded to 3-column proba `[p_short, 0, p_long]` in
`paper_trading/inference/pipeline.py:_generate_and_apply()`
**Serialization:** `model.save_model(path)` / `model.load_model(path)` — `.json` format
**Path:** `paper_trading/models/{asset_name}_model.json`

---

### Regime-Conditional Model
**Type:** `xgboost.XGBClassifier`
**Objective:** `binary:logistic`
**Architecture:** Binary classifier trained on alpha features + 7 regime features
**Constructor:**
```
n_estimators=200, max_depth=2, learning_rate=0.03,
random_state=42, n_jobs=1, tree_method='hist', verbosity=0
```
**Per-asset:** One per asset, stored at `models/regime/{asset_name}_regime.json`
**Feature names:** Persisted in a sidecar `{asset_name}_regime_features.txt` file.

### Ensemble (Disabled 2026-06-20)
**Weight:** `base_weight = 1.0` (regime model not loaded at inference)
**Status:** Disabled portfolio-wide after walk-forward PnL comparison (+2.5% / p=0.0446 raw, fails Bonferroni correction). Regime model training path still active for future re-enable; see `docs/adr/ADR-026-ensemble-disabled.md`.
**Re-enable criteria:** Pooled sign test p < 0.10 across the live portfolio AND ≥3 assets with per-asset sign-p < 0.10 on ≥6 months fresh OOS data.

---

## 2. SIGNAL THRESHOLD CONTRACT

**Strategy:** `FixedThresholdStrategy` (`shared/signal.py`)
**Threshold:** `0.45` (float, default param of `generate_signal()`)

| Condition | Signal | Label |
|---|---|---|
| `proba[:,2] > 0.45` AND `proba[:,0] <= 0.45` | BUY | 2 |
| `proba[:,0] > 0.45` AND `proba[:,2] <= 0.45` | SELL | 0 |
| BOTH `> 0.45` | BUY (long wins — order-dependent) | 2 |
| NEITHER `> 0.45` | FLAT | 1 |

**Confidence:** `confidence = max(proba[:,2], proba[:,0])`
**Confidence output:** `round(confidence * 100, 2)` (percent, 0-100 scale)

---

## 3. FEATURE CONTRACT

**Primary builder:** `features/alpha_features.py:build_alpha_features()`
**Regime builder:** `features/regime_features.py:generate_regime_features()`
**Per-asset contract:** Defined in `features/registry.py:FEATURE_REGISTRY` (36 tickers) — used for training custom features.
**Input:** 15–35 alpha features per asset (15 per-asset + 4 cross-asset + up to 16 COT features from all covered pairs) + 7 regime features per asset.

**Feature naming:** Per-asset features use the asset ticker prefix (e.g. `EURUSD_carry_vol_adj`).

15 per-asset features (9 core + 6 trend-exhaustion) + 4 cross-asset features + up to 16 COT features from all covered pairs (variable count, injected from `cot_data`):

| Feature | Description |
|---------|-------------|
| `{ASSET}_carry_vol_adj` | Volatility-adjusted carry |
| `{ASSET}_mom_21d` | 21-day momentum |
| `{ASSET}_mom_63d` | 63-day momentum |
| `{ASSET}_mom_126d` | 126-day momentum |
| `{ASSET}_mom_252d` | 252-day momentum |
| `{ASSET}_zscore_20` | 20-day z-score vs SMA |
| `{ASSET}_vol_ratio` | Short/long-term vol ratio |
| `{ASSET}_dow_signal` | Day-of-week encoding |
| `{ASSET}_has_cot` | COT data availability flag (zero-filled for pairs not in COT data) |
| `{COVERED}_cot_z` | COT speculative positioning z-score (all COT-covered pairs, not per-asset) |
| `{COVERED}_cot_change_4w` | 4-week change in COT net positioning (all COT-covered pairs) |
| `{ASSET}_macd_hist` | MACD histogram / close (normalized) — trend exhaustion |
| `{ASSET}_stoch_k` | Stochastic %K — overbought/oversold |
| `{ASSET}_stoch_d` | Stochastic %D — signal line confirmation |
| `{ASSET}_bb_pct_b` | Bollinger Band %B — extreme range detection |
| `{ASSET}_adx_slope` | ADX rate of change — trend acceleration/deceleration |
| `{ASSET}_rsi_divergence` | RSI divergence (-1/0/+1) — bullish/bearish exhaustion |
| `dxy_mom_21d` | DXY 21-day return |
| `vix_mom_5d` | VIX 5-day return |
| `spx_mom_5d` | SPX 5-day return |
| `WTI_mom_21d` | WTI crude 21-day return |

> **COT features — DEPRECATED 2026-07-09:** Walk-forward validation showed zero gain across all 22 assets. `fetch_cot_features()` now returns an empty DataFrame. No COT columns are produced in training or inference. The COT placeholder columns (`has_cot`, `cot_z`, `cot_change_4w`) are kept for backward compatibility but always zero-filled.
>
> The following **historical** description is preserved for reference only — it no longer applies to current production:
> "COT features were injected via a per-column join that matched `cot_data` columns against `_COT_COVERED_NAMES`. However, the initialization loop never fired because the DataFrame column is named `"close"`. Instead, ALL columns from `cot_data` were joined into every asset's feature vector. Assets not in COT data (GC, ES, NQ) received unrelated COT positioning data."

**Trend-exhaustion features** (added 2026-06-26) require OHLCV data passed to `build_alpha_features()`. Computed via the `ta` library. See `features/divergence.py` for RSI divergence detection logic (local extrema within 20-bar lookback window).

### Custom feature variants:

| Asset | Additional features |
|-------|--------------------|
| EURCHF | `mom126` (+126d momentum, replaces base mom), `gc_lead_1` (added 2026-07-16) |
| NZDUSD | `mom126` (+126d momentum, replaces base mom), `gc_lead_1`, `dji_lead_1` |
| GBPAUD | `yield_slope` (US yield curve slope) |
| CADCHF | `yield_slope`, `gc_lead_1` |
| EURNZD | `yield_slope` |
| GBPCHF | `yield_slope`, `gc_lead_1`, `mom126` (+126d momentum, added 2026-07-16) |
| AUDUSD | `gc_lead_1` (added 2026-07-16) |
| NZDJPY | `dji_lead_1`, `gc_lead_1` |
| AUDJPY | `nzdjpy_lead_3`, `dji_lead_1` |
| USDJPY | `gc_lead_1` |
| USDCHF | `gc_lead_1` |
| NZDCHF | `gc_lead_1` |
| USDCAD | `dji_lead_1` |
| EURAUD | `dji_lead_1` |
| GBPJPY | `dji_lead_1`, `gc_lead_1` |
| NZDCAD | (none) |

### Sell-Only Filter (Decision Pipeline Stage)

Applied at decision pipeline stage `g`. Overrides BUY signals to FLAT for assets where the model's BUY calibration is inverted (p_long > 0.5 → ~17% win rate). SELL signals pass through unchanged. See `2026-06-20 diagnostic chain` for full evidence.

**SELL_ONLY_ASSETS** (config-driven, resolved by `paper_trading/execution/gate_constants.py:get_sell_only_assets()`, sourced from `SellOnlyConfig` default in `configs/domain_models/risk.py:154-164`; no `sell_only_assets` key exists in domain YAML):

```
CADCHF, EURAUD, EURCHF, GBPCHF, GBPJPY, NZDCHF
```

**Expanded to 6 assets on 2026-07-11.** CADCHF, NZDCHF, EURAUD remain from the original 3 permanent SELL_ONLY set. EURCHF, GBPCHF, and GBPJPY were promoted to permanent SELL_ONLY after additional walk-forward analysis confirmed their BUY inversion is irrecoverable under current feature design.

**Epistemic status:** Empirically-grounded — two leading causal hypotheses (carry for CHF+OTHER, DXY for equities) tested via walk-forward counterfactual ablation and **falsified**. Removing SELL_ONLY requires discovering a causal mechanism that does not currently exist in any tested hypothesis.

**Deferred-entry bypass fix (2026-06-20):** `entry_service.py:poll_pending_entries()` cancels deferred BUY entries for SELL_ONLY assets with reason `sell_only_filter`.

### Regime features (used by regime-conditional model, generated from OHLCV)

Built in `features/regime_features.py:generate_regime_features()`.
7 features per asset, prefixed with `{ASSET}_` when fed to the regime model:

| Feature | Description |
|---------|-------------|
| `hurst` | Hurst exponent (window=21) — trending vs mean-reverting |
| `kaufman_er` | Kaufman efficiency ratio (window=10) |
| `adx` | ADX(14) — trend strength |
| `vol_zscore` | Volatility shock detection (vol_10 / vol_21) |
| `compression` | Vol compression ratio (ATR_5 / ATR_20) |
| `utc_hour` | UTC hour of bar timestamp |
| `session_vol_profile` | Hourly vol relative to 20-day norm |

21 alpha features (9 core + 6 trend-exhaustion + has_cot + cot_z + cot_change_4w + 4 cross-asset) enter the base model. Up to 16 additional COT features are injected when COT data is available.
28 total features enter the regime model (21 alpha + 7 regime) — but regime model is not loaded at inference (ensemble disabled).

### Archetype features (inference-only, from full-history OHLCV)

Computed inline in `paper_trading/inference/pipeline.py:_generate_and_apply()` via `ta` library:

| Feature | Formula | Window |
|---|---|---|
| `ema_spread` | (EMA20 − EMA50) / EMA50 | 20/50 |
| `adx` | ADX(high, low, close) | 14 |
| `rsi` | RSI(close) | 14 |
| `bb_zscore` | (close − BB_mavg) / (BB_std / 2) | 20 |

---

## 4. DATA CONTRACT

### Sources
| Source | Data | Frequency |
|---|---|---|
| `MT5` / `yfinance` | Daily OHLCV for all assets + macro (DXY=DX-Y.NYB, VIX=^VIX, SPX=^GSPC, WTI=CL=F, TNX=^TNX) | Daily bars |

### Ingestion rules
- `fetch_live(ticker)` — OHLCV via MT5 bridge (primary) or yfinance fallback (`_FETCH_PERIOD = "5y"`, `_FETCH_WARMUP_BUFFER = 1250`), truncated to `_MAX_INDICATOR_LOOKBACK + 50` rows when inference truncation is validated. Training uses the expanded data cache (`data/yfinance_10yr/`) providing 10y+ history.
- All date indices are `datetime64[ns]` at daily resolution (no intraday)
- No FRED data — all macro derived from yfinance tickers
- Deduplication: `df = df[~df.index.duplicated(keep="last")]` applied after ffill to handle duplicate dates from UTC normalization

### Index normalization
All downloads produce TZ-naive DatetimeIndex at daily resolution.
The pipeline normalizes output by converting to UTC before stripping TZ:
```python
df.index = pd.to_datetime(df.index.tz_convert("UTC").date)
```

---

## 5. LABEL CONTRACT

**Label function:** `features/labels.py:triple_barrier_labels()`
**Input parameters** (per-asset, from per-asset YAML files in `configs/domains/assets/`):
- `pt_sl`: `(tp_mult, sl_mult)` — barrier multiples of ATR
- `vertical_barrier`: configurable per-asset (default config)

**Label pipeline:**
1. Triple-barrier touch → {-1 (SELL), 0 (HOLD), 1 (BUY)}
2. Binary reduction: drop HOLD (0), map {-1, 1} → {0, 1}
3. Binary XGBoost trains on {0, 1} labels only

**Per-asset pt_sl** from per-asset YAML files in `configs/domains/assets/`.

**Halt parameters** (from `configs/domains/risk/halt.yaml`, global defaults overridable per asset):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `drawdown` | -0.08 | Per-asset drawdown limit |
| `monthly_pf` | 0.70 | Minimum trailing monthly profit factor |
| `signal_drought` | 30 | Max days without a signal before penalty |
| `prob_drift` | 0.25 | Max confidence drift from expected baseline |
| `prob_drift_min_samples` | 10 | Minimum signals required before drift check activates |
| `expected_prob_conf` | 0.65 | Expected probability confidence baseline |

---

## 6. MODEL TRAINING CONTRACT

**Pipeline:** `paper_trading/inference/training.py:AssetTrainingPipeline.train()`
**Data window:** 10y+ history from expanded data cache (`data/yfinance_10yr/`), train on last `retrain_window` years (default 10)
**Feature builder:** `build_alpha_features()` — when OHLCV is provided, emits 15 per-asset columns (9 base `carry_vol_adj, mom_21d, mom_63d, mom_126d, mom_252d, zscore_20, vol_ratio, dow_signal, has_cot` + 6 trend-exhaustion `macd_hist, stoch_k, stoch_d, bb_pct_b, adx_slope, rsi_divergence`) + 4 cross-asset (`dxy_mom_21d, vix_mom_5d, spx_mom_5d, WTI_mom_21d`) + 2 × N COT-covered pairs (`cot_z, cot_change_4w`) joined into every asset's vector.
Without OHLCV: 9 per-asset + 4 cross-asset + per-pair COT.
See Section 3 for the canonical taxonomy.
**Minimum samples:** 100 binary labels; 2+ unique classes
**Train/val split:** 80/20 chronological, stratified by label if minimum class count ≥ 2
**Per-asset max_depth** from `yaml` config (default 2).
**scale_pos_weight:** Set to `imbalance_ratio` (n_neg / n_pos) per asset.
**Vertical barrier:** Configurable per-asset via `contract.label_params["vertical_barrier"]` (default 20).
**Gap (embargo):** `max(gap, vertical_barrier)` — enforced to prevent leakage.

#### Regime Model Training
- Second XGBoost trained on alpha features + 7 regime features (generated from OHLCV via `fetch_asset_ohlcv()`)
- 28 total features (21 alpha + 7 regime, all prefixed by asset name)
- Saved to `models/regime/{ASSET}_regime.json`
- Loaded at engine startup by `_train_regime_if_configured()` — skipped when `base_weight >= 1.0`
- Ensemble disabled portfolio-wide (base_weight=1.0) — regime models not loaded at inference

**Post-training:**
- Persist PSI baseline from training feature distribution
- Train optional meta-label model (XGBoost)
- Log feature importances + stability (Jaccard + Spearman)

---

## 7. INFERENCE PIPELINE CONTRACT

**Pipeline:** `paper_trading/inference/pipeline.py:AssetInferencePipeline._generate_and_apply()`
**Per-cycle (every ~60s):**

1. `fetch_live(ticker)` — OHLCV via MT5 bridge (primary) or yfinance fallback (`_FETCH_PERIOD = "5y"`), deduplicate index
2. Normalize index to UTC TZ-naive
3. `refresh_price()` — patch last close with real-time or 5d fallback
4. `ffill()` close column
5. `fetch_asset_data()` + `build_alpha_features()` — 21 alpha feature cols (9 core + 6 trend-exhaustion + 3 COT + 4 cross-asset)
6. Compute regime features from OHLCV (7 cols via `generate_regime_features`)
7. Compute archetype features (ema_spread, adx, rsi, bb_zscore)
8. PSI drift check (rolling 21d vs baseline; skipped on first cycle)
9. Inference truncation validation — if proven safe, predict only last row
10. XGBoost predict → 3-column proba expansion `[p_short, 0, p_long]`
11. Calibrate probabilities — apply per-asset `DirectionalCalibrator` (Platt base) to raw `p_long` (config-gated via `calibration.enabled`; default `true`). See Section 16.1 (P1).
12. Ensemble blend skipped (regime model not loaded — disabled portfolio-wide)
13. Optional meta-label inference
14. `FixedThresholdStrategy(0.45)` → BUY/SELL/FLAT
15. Archetype classification → `TradeDecision`
16. Refresh MT5 spread for spread gate
17. Decision pipeline stages (applied sequentially, 25 stages):
    a. First-cycle suppression — suppress trading on cold-start cycle 1
    b. Weekend gate — suppress entries during weekend (0.5× allocation, filtered cycles)
    c. Bar-jump suppression — suppress 60min if bar count changed >100
    d. Store prediction metadata — record pre-decision signal state
    e. Update MAE/MFE — update max adverse/favorable excursion
    f. Resolve signal — map proba to BUY/SELL/FLAT
    g. Risk-off suppression — flat AUDUSD when VIX>0 & SPX<0
    h. VIX gate — suppress CL=F when VIX > 30; fail-open if VIX data missing or stale
    i. Sell-only filter — override BUY→FLAT for 6 SELL_ONLY assets (inverted BUY calibration)
    j. Confidence gate — abort if net confidence below threshold (direction-conditional buy/sell thresholds)
    k. Spread gate — block entry if spread > per-class threshold (observe 720 cycles first)
    l. Session gate — block entry outside market session hours per asset-class tier (observe 720 cycles first)
    m. Regime transition gate — suppress entries for 30 days after bull↔bear transition (close crossing MA50)
    n. ADX entry gate — block entry if ADX below threshold (observe-only, disabled by default)
    o. Calibration drift gate — suppress entry if mean confidence exceeds mean WR by >20pp (30-trade window)
    p. Signal hysteresis — 2-of-3 agreement before flip
    q. Meta-label advisory — record meta-label recommendation without enforcement
    r. Update regime bar counter — track bars since last regime shift
    s. Conviction gate — flip gate based on regime conviction
    t. Kelly sizing — scale position by Kelly criterion (config-gated via `kelly.enabled`; default `false`). See Section 15.3 (P2).
    u. Manage position — close/re-open with entry gate check (includes embedded profit lock — blocks flip if unrealized PnL > `profit_lock_threshold_pct`, default 15%)
    v. Build entry artifacts — construct TradeDecision for execution
    w. Route execution policy — direct to PaperBroker or MT5Broker
    x. Poll deferred entries — execute previously deferred pending orders
    y. Update prob history — record probability history for drift monitoring
18. Route through governance layers (15 mechanisms)
19. Position sizing chain: Kelly multiplier → drawdown taper → cap → risk cap → leverage budget → backstop
20. Independent MT5 sizing (`_compute_mt5_qty` with broker equity)
21. Execute position lifecycle:
      - **Open**: `pos_mgr.open(intent)` + MT5 `place_order` (SL/TP attached); entry skipped if current price deviated > `max_entry_slippage_pct` from signal price (entry service gate)
      - **SL/TP hit**: `pos_mgr.close()` + MT5 `close_position(ticket)`
      - **Flip**: profit-lock check first — if unrealized PnL > `profit_lock_threshold_pct`, flip is blocked and position holds; else close + re-open in same cycle (MT5 close + place_order)
      - **Trailing stop**: `pos_mgr.update_stop_loss()` + MT5 `modify_position(ticket, sl)`
      - **Post-entry adjust**: `pos_mgr.update_stop_loss/tp()` + MT5 `modify_position()`

---

## 8. MT5 BRIDGE CONTRACT

**Bridge server:** `paper_trading/ops/mt5_bridge.py` — runs under Wine Python
**Client:** `paper_trading/ops/mt5_client.py` — host-side TCP client
**Broker:** `paper_trading/execution/mt5_broker.py` — implements `BrokerInterface`
**Port:** `9879` (configurable via `MT5_BRIDGE_PORT` env var, default in `configs/domains/broker/mt5.yaml`)
**Symbol map:** `configs/mt5_symbol_map.yaml` — maps EigenCapital tickers to MT5 symbols

### Operations actively routed to MT5

| Operation | Method | When |
|-----------|--------|------|
| Place market order | `MT5Broker.place_order()` → bridge `place_order` | On every new position open (SL/TP attached) |
| Close position | `MT5Broker.close_position()` → bridge `close_position` | On SL hit, TP hit, flip, or time-stop |
| Modify SL/TP | `MT5Broker.modify_position()` → bridge `modify_position` | On trailing stop advance, post-entry SL/TP adjustment |
| Get positions | `MT5Broker.get_positions()` → bridge `get_positions` | Every open cycle (to check for duplicate orders) |
| Real-time price | `MT5Broker.get_current_price()` → bridge `realtime_price` | Every refresh cycle |
| Account info | `MT5Broker.get_account_summary()` → bridge `get_account` | Capital sync cycle |

### Guard against duplicate orders
Before placing an MT5 order, the engine checks if a position already exists for that symbol in the broker. If yes, the MT5 order is skipped (paper engine state may have diverged — next close will resync).

---

## 9. PORTFOLIO CONTRACT

**Builder:** `paper_trading/portfolio_builder.py:build_paper_portfolio()`
**Source:** `configs/domains/` directory tree — loaded by `PaperConfigRegistry` from per-asset YAML files (`configs/domains/assets/<TICKER>.yaml`) and domain files

> **2026-06-30 update:** 11 assets adjusted to ratio=3.0 via geometric mean constraint.
> Methodology: `scripts/optimization/portfolio_sltp_optimizer.py`. See AGENTS.md for full chronology.
> All 22 assets retrained with new labels. Backtest (base): total_R=367.84 (Sharpe 34.57), max_dd_R=-0.9. Calibrated + direction-conditional thresholds: total_R=732.73 (Sharpe 56.45).

### Current assets (22 promoted)
| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|
| GC | GC=F | 7.0% | 1.00 | 4.00 | 2 (rolled back from 4) |
| USDCHF | USDCHF=X | 2.0% | 0.85 | 3.00 | 4 |
| USDCAD | USDCAD=X | 2.5% | 1.30 | 3.90 | 3 |
| GBPCAD | GBPCAD=X | 5.0% | 1.45 | 4.34 | 5 |
| NZDCAD | NZDCAD=X | 5.0% | 1.83 | 5.48 | 2 |
| NZDUSD | NZDUSD=X | 2.5% | 1.29 | 3.87 | 2 |
| GBPAUD | GBPAUD=X | 5.0% | 1.00 | 3.00 | 3 |
| NZDCHF | NZDCHF=X | 7.0% | 1.00 | 4.00 | 2 |
| CADCHF | CADCHF=X | 5.0% | 1.00 | 4.00 | 3 |
| AUDUSD | AUDUSD=X | 4.0% | 1.41 | 4.24 | 5 |
| EURCHF | EURCHF=X | 5.0% | 1.00 | 3.00 | 4 |
| EURCAD | EURCAD=X | 2.0% | 0.71 | 2.12 | 3 |
| EURNZD | EURNZD=X | 3.0% | 1.12 | 3.36 | 5 |
| GBPCHF | GBPCHF=X | 3.0% | 0.82 | 2.45 | 2 (rolled back from 4) |
| GBPUSD | GBPUSD=X | 4.0% | 0.52 | 1.97 | 4 |
| EURAUD | EURAUD=X | 1.0% | 0.54 | 1.77 | 5 |
| ^DJI | ^DJI | 2.0% | 0.50 | 4.00 | 4 |
| BTCUSD | BTC-USD | 2.0% | 0.58 | 1.51 | 3 |
| AUDJPY | AUDJPY=X | 2.0% | 0.52 | 2.01 | 2 |
| NZDJPY | NZDJPY=X | 2.0% | 0.51 | 2.02 | 2 |
| GBPJPY | GBPJPY=X | 2.0% | 0.50 | 2.22 | 2 |
| USDJPY | USDJPY=X | 2.0% | 0.52 | 1.97 | 2 |

**Total allocation: varies** (factor_constrained_v2 adjusts weights dynamically; remaining capacity held as cash buffer).

### Removed from trading (2026-06-20)
AUDCHF, EURUSD, AUDNZD — removed after walk-forward diagnostic confirmed base model directional instability (confident wrong-direction bets during trend periods).

**2026-06-20 (late): GBPNZD** removed — tp/sl=1.0/3.0 (ratio 0.33), breakeven WR 75%, achieved 72.3%. Net-negative — lost -37R total with -71R max drawdown.

**USDCAD/NZDUSD allocation halved** from 5% → 2.5% to limit drawdown impact while keeping diversification.

**2026-06-22: GBPUSD promoted** to portfolio after walk-forward showed IC 0.186 (4/4 folds positive), HR 0.371, pt_sl=(1.97, 0.52) giving R:R=3.79.

**2026-06-26: USDJPY, GBPJPY re-promoted** after Step 3 trend-exhaustion features improved BuyWR above breakeven WR thresholds, enabling two-way trading.

**2026-06-30: 11 assets bumped to ratio=3.0** via geometric mean constraint (USDCAD, GBPCAD, NZDCAD, NZDUSD, GBPAUD, AUDUSD, EURCAD, EURNZD, GBPCHF). Full optimizer suite in `scripts/optimization/`. All 16 models retrained with new labels. Dashboard endpoint `/optimization.json` added.

**2026-07-03/04: 6 assets promoted** — AUDJPY, NZDJPY, GBPJPY, USDJPY (JPY crosses — walk-forward positive) and BTCUSD (crypto — 24/7 trading, no COT features). ^DJI re-promoted from SELL_ONLY after trend-exhaustion features.

### Previously removed (post walk-forward, insufficient edge)
CHFJPY, CADJPY, CL, EURGBP, EURJPY, AUDCAD, ^VIX, IWM

---

## 10. POSITION SIZING CONTRACT (PAPER EQUITY)

Paper positions are sized independently from MT5 positions. Paper sizing uses the
simulation's mtm_value ($100K capital) and its own drawdown peak.

**Size scalar chain:**
```
effective_cap = capital_base × min(current_value / initial_capital, 3.0)
size_scalar = position_size × exposure_multiplier × governance_size_scalar
              × meta_size_multiplier × drawdown_taper
notional = effective_cap × size_scalar

1. Per-position equity cap: notional = min(notional, max_position_pct_of_equity × total_equity)
2. Risk-per-trade cap:     risk = |entry - stop_loss| × (notional / entry_price)
                            if risk > max_risk_per_trade_pct × total_equity:
                              cap notional; skip if capped below min_viable_position_pct × total_equity
3. Leverage budget:        atomic decrement from shared pool (lock-protected)
                            if remaining budget < 0: skip
                            notional = min(notional, remaining)
```

**Drawdown taper:**
```
if dd_pct >= start_dd:  taper = 1.0
if dd_pct <= end_dd:    taper = min_size
else:                   linear interpolation between start_dd and end_dd
```
Config keys: `size_taper_start_dd` (default -0.05), `size_taper_end_dd` (default -0.15),
`size_taper_min` (default 0.50).

**Leverage budget (portfolio-level):**
```
leverage_budget = portfolio_max_leverage × total_equity × backstop_multiplier
```
Allocated per-cycle via atomic lock decrement per asset. Backstop multiplier is tracked
by `EngineOrchestrator`: decays ×0.9 toward 1.0 on breach-free cycles; ratchets down
when Phase 3 detects breach against `fair_budget = max_leverage × equity`.

**Backstop Phase 3:**
```
total_entered = sum(asset._last_entry_notional) across all actors
fair_budget = max_leverage × peak_equity
if total_entered > fair_budget × (1 + tolerance):
    backstop_multiplier = min(backstop_multiplier, fair_budget / total_entered)
```
Correction uses `fair_budget` (unmodified by backstop_multiplier) to prevent
feedback-loop decay toward zero.

**Weekend allocation multiplier:** When `is_weekend()` returns true and the asset has `weekend_eligible: true`, a `weekend_allocation_multiplier` (default 0.5) is applied to `size_scalar` before the SizingInput is constructed. Config keys: `weekend_eligible` (default false), `weekend_allocation_multiplier` (default 0.5).

### 10a. MT5 INDEPENDENT SIZING CONTRACT

MT5 positions are sized independently from paper, using the real broker account equity.

**MT5 sizing chain (per entry, in `_compute_mt5_qty()`):**
```
1. broker.get_account_summary().portfolio_value → mt5_equity
2. current_mt5_drawdown_pct() → taper via drawdown_taper()
3. notional = mt5_equity × max_position_pct_of_equity × drawdown_taper
4. risk cap: similar to paper, capped at max_risk_per_trade_pct × mt5_equity
5. min viable: skip if capped notional < min_viable_position_pct × mt5_equity
6. min volume: _quantity_to_lots() validates against broker min_volume; skip if 0
```

MT5 does NOT share the paper leverage budget (deferred — 0.01 lot minimum makes
desired-vs-actual notional diverge wildly for small accounts).

**MT5 drawdown tracking:**
- `MT5Broker._peak_equity` updated on every `get_account_summary()` call
- `MT5Broker.current_mt5_drawdown_pct()` returns negative fraction from peak

### 10b. STACKING CONTRACT (Pyramiding)

**Status:** Disabled by default (`defaults.stacking.enabled: false`), dry_run mode (`dry_run: true`).

**Purpose:** Add incremental layers to existing winning positions (pyramiding), tracked via `PositionIntent.layers` (StackLayer dataclass) with avg_price invariant enforcement.

**Entry gate:** `manage_position` evaluates `_should_stack(ctx)` when already in same-side position. Stacking is bypassed for `OrderType.STACK` in MT5 orphan detection.

**Sizing:** Volatility-adjusted diminishing schedule anchored to `base_entry_size`:
```
layer_multipliers: [0.8, 0.5, 0.3]  # fraction of base size per layer
max_layers: 3
```

**Layer conditions (all must pass):**
- `stacking.enabled: true`
- Position has unrealized PnL > 0
- Confidence >= `min_confidence` (default 0.60)
- ADX >= `adx_threshold` (default 25, ensures trending regime)
- Not at `max_layers` capacity
- Stack size >= `min_stack_size_factor` of base entry
- Not in risk-off/STRESSED liquidity regime
- Net leverage after stack stays within `stack_max_risk_growth` (default 1.0x)

**Layer protection:** Each layer gets a tightened SL (`stack_sl_tighten: 0.5`). Breakeven SL activates after `breakeven_threshold_r: 0.4`. Trailing stop activates after `trail_activate_r: 0.8`.

**Config keys:** See `configs/domains/risk/sizing.yaml` for stacking-related parameters (e.g., `defaults.stacking.*`).

---

## 11. ASSET SCREENING & PROMOTION CONTRACT

**Screening pipeline:**
1. `scripts/backtest/walk_forward_backtest.py` — multi-ticker walk-forward validation
2. `scripts/analysis/production_audit.py` — 18-phase production audit
3. `scripts/optimization/per_asset_quality.py` — asset quality classification (EV/breakeven/MFE/MAE)

**Promotion criteria:**
| Condition | Threshold |
|---|---|
| 5-year profit factor | > 1.0 |
| Avg R | > 0.0 |
| All 5-fold windows positive | Preferred |

---

## 12. GOVERNANCE CONTRACT

17 layered governance mechanisms plus RiskEngineV2, PEK admission, and PerformanceState velocity, each independently configurable. See `docs/GOVERNANCE.md` for the canonical taxonomy.

| Layer | Frequency | Effect | Config key |
|---|---|---|---|---|
| Validity state machine | Per tick | Exposure 0–100% | `halt.*` |
| Feature stability | Per retrain | Validity penalty | — |
| Meta-labeling (XGBoost) | Per signal | Size scalar [0–1] | `meta_labeling` |
| Macro narrative | Weekly | SL +10%, size −20% | `narrative_config` |
| Liquidity regime | Per signal | THIN: SL +15%, size −15% (soft) | `liquidity_config` |
| | | STRESSED: SL +30%, size −30%, hard halt | |
| PSI drift | Per cycle | Validity penalty, halt at 3+ SEVERE | — |
| Sell-only filter | Per decision | Override BUY→FLAT for 6 inverted-BUY assets | `get_sell_only_assets()` (config-driven from per-asset files in `configs/domains/assets/`) |
| Sell tripwire | Per exit | 20-trade sliding window, 65% SELL win-rate WARNING threshold | (hardcoded in `RiskRegistry`) |
| Calibration (P1) | Per inference | Remap raw p_long via DirectionalCalibrator (Platt base), ECE ↓ from 0.2207→0.0178 | `calibration.*` (config-gated) |
| Kelly sizing (P2) | Per decision | Scale position by Kelly criterion (disabled pending live data) | `kelly.*` (config-gated, default disabled) |
| Factor model (P3) | Per cycle | Factor exposures via 10 groups in state.json (monitoring only) | `portfolio.factor_constraints.*` |
| Position concentration | Per cycle | Flags >75% net-short skew | `net_short_concentration_threshold` |
| Circuit breaker | Per cycle | Multi-condition: dd, vol spike, halt ratio, consecutive losses (threshold=7) | (hardcoded in `CircuitBreaker`) |
| Portfolio drawdown | Per cycle | Circuit breaker at −15% | `portfolio_drawdown_limit` |
| Entry price deviation | Per entry | Skips entry if price moved > `max_entry_slippage_pct` (def 2%) | `max_entry_slippage_pct` |
| Profit lock | Per flip (embedded in manage_position) | Blocks flip if unrealized PnL > `profit_lock_threshold_pct` (def 15%) | `profit_lock_threshold_pct` |
| Weekend trading governance | Per cycle (weekend/holiday) | Filtered cycle for `weekend_eligible` assets; 0.5× allocation multiplier; `crypto: [0,24]` session tier | `weekend_eligible`, `weekend_allocation_multiplier` |

**Position sizing guardrails (multiply into final notional):**

| Guardrail | Scope | Effect | Config keys |
|-----------|-------|--------|-------------|
| Drawdown taper | Per asset | Linear taper from 1.0 to min_size between start_dd and end_dd | `size_taper_start_dd`, `size_taper_end_dd`, `size_taper_min` |
| Per-position equity cap | Per entry | Clip notional to `max_position_pct_of_equity` of total equity | `max_position_pct_of_equity` |
| Risk-per-trade cap | Per entry | Clip or skip if SL risk > `max_risk_per_trade_pct` of equity | `max_risk_per_trade_pct`, `min_viable_position_pct` |
| Portfolio leverage budget | Global | Atomic decrement from `max_leverage × equity` pool | `portfolio_max_leverage`, `portfolio_leverage_tolerance` |
| Backstop multiplier | Global | Ratchets down on breach, decays 0.9/cycle otherwise | (no config — fixed 0.9 decay) |

**Decision pipeline suppression stages (applied in order `DEFAULT_STAGES`):**

| Stage | Effect | Config |
|-------|--------|--------|
| First-cycle suppression | Suppress trading on cold-start cycle 1 | (hardcoded, `_cycle_counter <= 1`) |
| Bar-jump suppression | Suppress 60min if bar count changed >100 (data-source switch) | `bar_jump_suppression_cycles` (default 120) |
| Store prediction metadata | Record pre-decision signal state | — |
| Update MAE/MFE | Update max adverse/favorable excursion | — |
| Resolve signal | Map proba to BUY/SELL/FLAT via `FixedThresholdStrategy(0.45)` | `threshold` (default 0.45) |
| Risk-off suppression | Flat AUDUSD when VIX>0 & SPX<0 | (hardcoded, per-asset pair) |
| Sell-only filter | Override BUY→FLAT for `get_sell_only_assets()` | (config-driven from per-asset files in `configs/domains/assets/`, 6 assets) |
| Spread gate | Block entry if spread > per-class tier (observe 720 cycles first) | `spread_gate_tiers` (fx_major=10bps, fx_cross=20bps, indices=15bps, metals=20bps) |
| Session gate | Block entry outside market session hours per asset-class tier (observe 720 cycles first) | `session_gate.tiers` (fx_major=[7,17], fx_cross=[7,17], indices=[13,20], metals=[8,18], crypto=[0,24]) |
| ADX entry gate | Block entry if ADX below threshold (observe-only, disabled by default) | `adx_entry_gate` (adx_threshold=18) |
| Confidence gate | Abort if net confidence below threshold | `min_confidence` (default 55.0) |
| Signal stability filter | Require >0.65 max(prob_long, prob_short) | `stability_margin` (default 0.15) |
| Signal hysteresis | 2-of-3 agreement before flip allowed | HYSTERESIS_WINDOW=3, HYSTERESIS_MIN_AGREE=2 |
| Meta-label advisory | Record meta-label recommendation (no enforcement) | — |
| Update regime bar counter | Track bars since last regime shift | — |
| Conviction gate | Flip gate based on regime conviction | `_evaluate_flip_gate()` |
| Kelly sizing (P2) | Scale position by Kelly criterion (config-gated, disabled by default) | `kelly.*` |
| Profit lock gate | Block flip if unrealized PnL > `profit_lock_threshold_pct` | `profit_lock_threshold_pct` (default 15%) |
| Manage position | Close/re-open with entry gate check | `_can_enter()` |
| Build entry artifacts | Construct `TradeDecision` for execution | — |
| Route execution policy | Direct to PaperBroker or MT5Broker | — |
| Poll deferred entries | Execute pending deferred orders | — |
| Update prob history | Record probability history for drift monitoring | — |

See `docs/GOVERNANCE.md` for full detail.

---

## 13. SYSTEM INVARIANTS

1. No train/serve skew — same feature builder in training and inference
2. No look-ahead — labels computed from future data only in training, never in inference
3. TZ-naive date alignment — all pipeline indices normalized to UTC date
4. Per-asset model independence — each asset has its own XGBoost model
5. Strict signal/execution separation — model produces probabilities only; execution resolved by policy layer
6. Worst-wins penalty aggregation — most negative governance penalty applied, not averaged
7. Frozen execution contract — PolicyDecision → FillResult → AttributionRecord is immutable causal chain
8. Single entry authority — `_can_enter()` is the sole gate for all entry sources
9. Binary signal — model trains on {-1, 1} labels only; HOLD dropped
10. Walk-forward validated — every promoted asset passes expanding-window backtest
11. Per-asset model depth — `max_depth` configured per-asset, not global
12. Exit reason canonicalization — all exit reasons are UPPERCASE (FLIP, SL, TP, BREAKEVEN, EXPIRY, GATE_CLOSED, MANUAL, PORTFOLIO_CIRCUIT_BREAKER, PEK_BUDGET_OVERRUN, SELL_ONLY_FILTER)
13. **MT5 order lifecycle symmetry** — Every paper position open has a corresponding MT5 `place_order`; every paper close has a corresponding MT5 `close_position`; every SL/TP adjustment has a corresponding MT5 `modify_position`.
14. **Paper engine is source of truth** — If an MT5 bridge operation fails (close, modify), the paper engine state is NOT rolled back. The next open cycle will detect the orphaned MT5 position and skip the duplicate order.
15. **Independent paper/MT5 sizing** — Paper positions are sized from paper mtm_value ($100K capital) with paper-specific drawdown and leverage budget. MT5 positions are sized from the real broker account balance with MT5-specific drawdown. The two sizing paths never interfere.
16. **No MT5 equity fetch in orchestrator** — The `EngineOrchestrator` does not fetch broker equity. MT5 sizing occurs at submission time (`_submit_mt5_order`) via `_compute_mt5_qty()`. Paper sizing uses the pre-Phase 1 equity snapshot from `sum(asset.mtm_value)`.
17. **HealthMonitor runs in Phase 3g** — `HealthMonitor.observe()` computes portfolio vol, VaR(95), CVaR, halt ratio, and circuit breaker checks. `RecoveryScheduler.probe()` checks halted actors with exponential backoff for re-enablement. Equity cluster alarm was removed 2026-07-01 when ES/NQ/^DJI left the portfolio (see `paper_trading/orchestrator/health.py:105`).
18. **Live VaR/CVaR** — Rolling 60-period portfolio returns feed VaR (5th percentile) and CVaR (mean of tail) computed in `EngineOrchestrator.run_once()` Phase 3g. Stored in `results["var_95"]` and `results["cvar_95"]`.
19. **Schema migration** — SQLite state store uses `DB_SCHEMA_VERSION = "2.0.0"` (up from implicit v1). Migrations run at connect time via `_run_migrations()`. Current migration (v1→v2.0.0) adds `cycle_id` to trades, `vol_spike`/`var_95` to equity_history, and indexes.
20. **SELL_ONLY_FILTER exit reason** — Deferred BUY entries canceled by sell-only filter record `sell_only_filter` as exit reason in trade history.

---

## 14. SL/TP BARRIER COMPUTATION CONTRACT

**Engine:** `paper_trading/position/dynamic_sltp.py:DynamicSLTPEngine`

### Barrier computation chain

1. **Primary method:** `_atr_barriers()` — ATR-based vol, used for most asset/regime combinations
2. **Vol basis:** `atr_pct = ATR_mean / close` (20-day ATR)
3. **Effective vol per side:**
   ```
   vol_used_sl = atr_pct * atr_mult_sl   # SL multiplier calibration
   vol_used_tp = atr_pct * atr_mult_tp   # TP multiplier calibration (separate from SL)
   sl_dist = entry_price * vol_used_sl * sl_mult
   tp_dist = entry_price * vol_used_tp * tp_mult
   ```
4. `atr_mult_sl` and `atr_mult_tp` are config-level defaults (currently 2.0 and 3.0) — per-asset override possible via YAML
5. The `_atr_barriers()` TP distance is discarded for live orders — the TP compiler overrides it

**SL/TP overrides (applied after ATR barriers):**

### TP Compiler: `paper_trading/entry/tp_compiler.py:compute_take_profit()`

This function ALWAYS overrides the TP from `_atr_barriers()`:
```
tp_distance = sl_distance × convexity × reg_mult × tp_mult_override
```

Where:
- `convexity` = archetype convexity (MOMENTUM_IGNITION=6.0, BREAKOUT=5.0, etc.)
- `reg_mult` = regime multiplier (trend=2.0, range_bound=1.5, volatile=1.1, crisis=0.6)
- `tp_mult_override` = config-level `tp_mult` from YAML per-asset

**Safety cap:** `MAX_RR = 5.0` — TP distance capped at 5× SL distance regardless of stacked multipliers.

### Post-entry adjustments
- Trailing stop: `_trailing_initial_barriers()` delegates to `_atr_barriers()` for SL, then adjusts
- `trailing_activation_mult` and `trailing_distance_mult` are per-asset from YAML files in `configs/domains/assets/` (ranges: activation 0.3–1.0, distance 0.5–1.5)

---

## 15. PORTFOLIO MATURITY FRAMEWORK — P0–P4

The system implements a 5-layer portfolio maturity framework (P0–P4). Each layer is
config-gated — no behavior change until explicitly enabled.

### 15.1 P0 — Portfolio Truth Layer (live: enabled)

**File:** `shared/portfolio_weights.py` — canonical weight computation, SINGLE source of truth.

**Contract:**
- `compute_weights()` is PURE — same returns → same weights.
- Covariance computed from RAW historical returns only (no governance scaling).
- Governance multipliers affect per-position sizing at trade time, NOT the portfolio weight matrix.
- WeightMethod strings are versioned (e.g. `"risk_parity_v1"`). Old versions remain callable for reproducible backtests.

**Registered strategies (8):**

| Method | Strategy | Description |
|--------|----------|-------------|
| `equal_v1` | Equal weight | Simple 1/N allocation |
| `risk_parity_v1` | Risk parity | Equal risk contribution via scipy SLSQP |
| `hrp_v1` | Hierarchical Risk Parity | Lopez de Prado HRP with `optimal_leaf_ordering` for deterministic quasi-diagonalization |
| `factor_constrained_v1` | Factor-constrained risk parity (legacy) | Risk parity with penalty term for factor exposure limits; falls back to base risk parity on optimizer failure |
| `factor_constrained_v2` | Factor-constrained risk parity (hard constraints) | Risk parity with direct linear inequality constraints (SLSQP). Guarantees factor limits bind (CHF ≤ 0.20). Best total_R/sharpe tradeoff — 124.45R / 15.40 / -0.62 max_dd. |
| `conviction_weighted_v1` | Conviction-tilted risk parity | Risk parity tilted by model conviction scores |

**Active config:** `portfolio.weight_method: factor_constrained_v2` (enabled 2026-06-25).

**Supporting tools:**
- `scripts/replay/replay_rebalance.py` — reconstruct historical weights via `rolling_weight_matrix()` and compare with live.
- `scripts/backtest/backtest_pnl.py --weight-method <method>` — backtest with any registered strategy.
- `engine_rebalance_service.py` — reads `weight_method` from config, calls `compute_weights()` on schedule.

### 15.2 P1 — Calibration Layer (live: enabled)

**Files:** `shared/calibration/` — `calibrator.py`, `registry.py`, `ece_tracker.py`

**Calibrators:**
- `DirectionalCalibrator` (Platt base) — trains separate Platt calibrators (LogisticRegression on logit(p_long)) for BUY and SELL directions. Handles p_long compression naturally (2-parameter fit). Default: `calibration.method: platt`.
- `BinnedCalibrator` (legacy) — divides `[0, 1]` into `n_bins` equal-width bins, maps raw p_long → empirical P(label=1) per bin. Linear interpolation between bin centers. Superseded by DirectionalCalibrator in 2026-07-11.
- `BetaCalibrator` — parametric beta regression (used as alternative).

**CalibrationRegistry:**
- Loads/saves calibrator models per asset from `paper_trading/models/calibration/`.
- Called at AssetEngine init (`asset_engine.py:121`).
- Applied in `pipeline.py:_generate_and_apply()` after `_run_inference()` (step 11 of the inference pipeline).

**Integration:**
- Config key: `calibration.enabled: true` (default), `calibration.method: platt`.
- `ECETracker` — rolling ECE tracked per asset; drift detection via configurable threshold.
- Calibration operator in `state.json`: each asset reports `calibration_applied: true/false`.

**Known performance:** ECE reduced from 0.2207 → 0.0178 (DirectionalCalibrator Platt base).

**Training:** `scripts/training/train_calibration.py` — fits calibrators from walk-forward signal parquets. Run when walk-forward parquets are regenerated.

### 15.3 P2 — Fractional Kelly Sizing (live: disabled)

**File:** `shared/kelly.py` — 143 lines, P2 in the portfolio maturity framework.

**Formula (standard Kelly for binary bets with asymmetric payoffs):**
```
f* = p - q × sl_mult / tp_mult
edge = p × tp_mult - q × sl_mult
```
Where `p` = calibrated P(TP hit), `q = 1-p`.

**Fractional Kelly:** `f = f* × fraction` (default fraction=0.25 for quarter-Kelly).

**Functions:**
| Function | Purpose |
|----------|---------|
| `compute_kelly_fraction(prob, tp_mult, sl_mult)` | Full Kelly fraction f*; 0.0 if no edge |
| `compute_kelly_multiplier(prob, tp_mult, sl_mult, fraction, max_cap, min_edge)` | Multiplier applied to base size |
| `compute_kelly_size(base_size, ...)` | Returns `base_size × multiplier`; 0.0 if no edge |
| `compute_edge(prob, tp_mult, sl_mult)` | Expected return in R units |
| `edge_description(prob, tp_mult, sl_mult)` | Human-readable edge summary |

**Integration:**
- Decision pipeline stage `apply_kelly_sizing` (stage o in DEFAULT_STAGES — after conviction gate, before manage_position).
- Config key: `kelly.enabled: false` (disabled by default).
- Kelly multiplier stored in `asset._kelly_multiplier`, consumed by `_composite_size_scalar()` before position cap/risk cap.
- **Requires calibrated probabilities.** Kelly reads probabilities AFTER calibration (P1) — if calibration is off, Kelly operates on raw model probabilities.

**Status:** Disabled pending 2+ weeks of live data to validate calibration-vs-win-rate alignment across all 22 assets.

### 15.4 P3 — Factor Model (live: enabled for monitoring)

**File:** `shared/factor_model.py` — 325 lines, P3 in the portfolio maturity framework.

**Factor groups (10):**

| Group | Assets |
|-------|--------|
| USD | AUDUSD, NZDUSD, USDCHF, USDCAD, GBPUSD, GBPCHF, CADCHF, NZDCHF, EURCAD |
| EUR | EURAUD, EURCHF, EURNZD, EURCAD |
| AUD | AUDUSD, EURAUD, AUDJPY |
| NZD | NZDUSD, NZDCHF, EURNZD, NZDJPY |
| CHF | EURCHF, USDCHF, NZDCHF, CADCHF, GBPCHF |
| CAD | USDCAD, CADCHF, EURCAD |
| GBP | GBPUSD, GBPCHF, GBPAUD, GBPCAD, GBPJPY |
| JPY | USDJPY, GBPJPY, AUDJPY, NZDJPY |
| US_EQUITY | ^DJI (ES, NQ removed 2026-07-01) |
| COMMODITY | GC |

**Functions:**
| Function | Purpose |
|----------|---------|
| `compute_factor_exposures(returns, dates)` | Factor exposure matrix for a given date range |
| `exposure_violations(exposures, limits, tolerance)` | Returns list of violations against per-factor limits |
| `factor_exposure_penalty(exposures, limits, scale)` | Penalty term for constrained optimization |
| `factor_constrained_weights(cov, limits, scale, ...)` | Penalized SLSQP risk parity with factor constraints |
| `compute_factor_returns(returns, simple=True)` | Simple equal-weight or regression factor returns |
| `summary(weight_vector)` | One-call summary: exposures, violations, n_violations, within_limits |

**Integration:**
- Factor exposures computed per-cycle in `engine_state_service.py:_compute_factor_exposures()`.
- Exposed in `state.json` portfolio summary as `factor_exposures`.
- `factor_constrained_v2` weight strategy uses `factor_constrained_weights_v2()` with hard linear inequality constraints.
- Active config: `portfolio.weight_method: factor_constrained_v2` (enabled — binds CHF to ≤0.20, all 10 factor groups constrained).

### 15.5 P4 — HRP Fix (2026-06-24)

**File:** `portfolio/hrp_allocator.py` — 102 lines.

**Fix applied:** `_get_quasi_diag()` now accepts optional `dist` parameter. When provided, `optimal_leaf_ordering` is applied to the linkage matrix before leaf-order traversal, guaranteeing a consistent dendrogram leaf order even when the distance matrix violates the metric triangle inequality.

**Root cause:** `scipy.cluster.hierarchy.linkage` with `method='single'` can produce SERIAL-index-ordered dendrograms when the distance matrix is near-singular (common with highly correlated financial returns). The leaf order becomes arbitrary, producing volatile HRP weights across rebalance periods.

**Verification:** 17 tests pass (was 14 + 1 skipped before fix). `optimal_leaf_ordering` is deterministic for any input — confirmed by bit-for-bit identical output across repeated calls.

---

## 16. DISCLAIMER

Paper trading system only. No live capital execution. Not financial advice.
Past walk-forward performance is not indicative of future results.
