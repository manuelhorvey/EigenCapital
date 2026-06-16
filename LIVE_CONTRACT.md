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
random_state=42, n_jobs=1, tree_method='hist', verbosity=0
```
**Per-asset max_depth:**
| Depth | Assets |
|-------|--------|
| 2 | GC, ES, NQ, GBPCAD, NZDCAD, NZDCHF, CADCHF, AUDUSD, GBPCHF |
| 3 | AUDCHF, GBPNZD, GBPAUD, AUDNZD, EURCAD, EURNZD |
| 4 | USDCHF, ^DJI, EURUSD, EURCHF |
| 5 | USDCAD, NZDUSD |

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

### Ensemble
**Weight:** `base_weight = 0.6` (regime weight = 0.4)
**Threshold:** `0.15` — LONG when `P(LONG) > 0.575`, SHORT when `P(LONG) < 0.425`
**Formula:** `P(LONG)_final = base_weight * P(LONG)_base + (1-base_weight) * P(LONG)_regime`

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
**Input:** 13 standard alpha features + 7 regime features per asset.

### Alpha features (all 21 dashboard assets use these 13 base features):

All assets receive the same 13 alpha features with per-asset prefix (`{ASSET}_`):

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
| `dxy_mom_21d` | DXY 21-day return |
| `vix_mom_5d` | VIX 5-day return |
| `spx_mom_5d` | SPX 5-day return |
| `WTI_mom_21d` | WTI crude 21-day return |

### Custom feature variants:

| Asset | Additional features |
|-------|--------------------|
| EURCHF | `mom126` (+126d momentum, replaces base mom) |
| NZDUSD | `mom126` (+126d momentum, replaces base mom) |
| GBPAUD | `yield_slope` (US yield curve slope) |
| CADCHF | `yield_slope` |
| AUDNZD | `yield_slope` |
| EURNZD | `yield_slope` |
| GBPCHF | `yield_slope` |

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

20 total features enter the regime model (13 alpha + 7 regime).
The base model sees only the 13 alpha features.

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
| `yfinance` / `MT5` | Daily OHLCV for all assets + macro (DXY=DX-Y.NYB, VIX=^VIX, SPX=^GSPC, WTI=CL=F, TNX=^TNX) | Daily bars |

### Ingestion rules
- `fetch_live(ticker)` — 5 years OHLCV (`_FETCH_PERIOD = "5y"`, `_FETCH_WARMUP_BUFFER = 1250`), truncated to `_MAX_INDICATOR_LOOKBACK + 50` rows when inference truncation is validated
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
**Input parameters** (per-asset, from `configs/paper_trading.yaml`):
- `pt_sl`: `(tp_mult, sl_mult)` — barrier multiples of ATR
- `vertical_barrier`: configurable per-asset (default config)

**Label pipeline:**
1. Triple-barrier touch → {-1 (SELL), 0 (HOLD), 1 (BUY)}
2. Binary reduction: drop HOLD (0), map {-1, 1} → {0, 1}
3. Binary XGBoost trains on {0, 1} labels only

**Per-asset pt_sl** from `configs/paper_trading.yaml`.

---

## 6. MODEL TRAINING CONTRACT

**Pipeline:** `paper_trading/inference/training.py:AssetTrainingPipeline.train()`
**Data window:** 5y history from yfinance (`_FETCH_PERIOD = "5y"`, `_FETCH_WARMUP_BUFFER = 1250`), train on last `retrain_window` years (default 5)
**Feature builder:** `build_alpha_features()` — 13 alpha feature columns
**Minimum samples:** 100 binary labels; 2+ unique classes
**Train/val split:** 80/20 chronological, stratified by label if minimum class count ≥ 2
**Per-asset max_depth** from `yaml` config (default 2).
**scale_pos_weight:** Set to `imbalance_ratio` (n_neg / n_pos) per asset.
**Vertical barrier:** Configurable per-asset via `contract.label_params["vertical_barrier"]` (default 20).
**Gap (embargo):** `max(gap, vertical_barrier)` — enforced to prevent leakage.

#### Regime Model Training
- Second XGBoost trained on alpha features + 7 regime features (generated from OHLCV via `fetch_asset_ohlcv()`)
- 20 total features (13 alpha + 7 regime, all prefixed by asset name)
- Saved to `models/regime/{ASSET}_regime.json`
- Loaded at engine startup by `_train_regime_if_configured()`
- Ensemble configured (60/20) only when regime model exists

**Post-training:**
- Persist PSI baseline from training feature distribution
- Train optional meta-label model (XGBoost)
- Log feature importances + stability (Jaccard + Spearman)

---

## 7. INFERENCE PIPELINE CONTRACT

**Pipeline:** `paper_trading/inference/pipeline.py:AssetInferencePipeline._generate_and_apply()`
**Per-cycle (every 300s / 5 min):**

1. `fetch_live(ticker)` — 5y OHLCV, deduplicate index
2. Normalize index to UTC TZ-naive
3. `refresh_price()` — patch last close with real-time or 5d fallback
4. `ffill()` close column
5. `fetch_asset_data()` + `build_alpha_features()` — 12 alpha feature cols
6. Compute archetype features (ema_spread, adx, rsi, bb_zscore)
7. PSI drift check (rolling 21d vs baseline; skipped on first cycle)
8. Inference truncation validation — if proven safe, predict only last row
9. XGBoost predict → 3-column proba expansion `[p_short, 0, p_long]`
10. Optional ensemble blend (regime model, disabled by default)
11. Optional meta-label inference
12. `FixedThresholdStrategy(0.45)` → BUY/SELL/FLAT
13. Archetype classification → `TradeDecision`
14. Route through governance layers
15. Execute position lifecycle:
    - **Open**: `pos_mgr.open(intent)` + MT5 `place_order` (SL/TP attached)
    - **SL/TP hit**: `pos_mgr.close()` + MT5 `close_position(ticket)`
    - **Flip**: close + re-open in same cycle (MT5 close + place_order)
    - **Trailing stop**: `pos_mgr.update_stop_loss()` + MT5 `modify_position(ticket, sl)`
    - **Post-entry adjust**: `pos_mgr.update_stop_loss/tp()` + MT5 `modify_position()`

---

## 8. MT5 BRIDGE CONTRACT

**Bridge server:** `paper_trading/ops/mt5_bridge.py` — runs under Wine Python
**Client:** `paper_trading/ops/mt5_client.py` — host-side TCP client
**Broker:** `paper_trading/execution/mt5_broker.py` — implements `BrokerInterface`
**Port:** `9879` (configurable via `MT5_BRIDGE_PORT` env var, default in `configs/paper_trading.yaml`)
**Symbol map:** `configs/mt5_symbol_map.yaml` — maps QuantForge tickers to MT5 symbols

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
**Source:** `configs/paper_trading.yaml`

### Current assets (21 promoted)
| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|---|
| GC | GC=F | 7.0% | 1.00 | 4.00 | 2 |
| USDCHF | USDCHF=X | 4.0% | 0.85 | 3.00 | 4 |
| AUDCHF | AUDCHF=X | 5.0% | 2.75 | 3.50 | 2 |
| USDCAD | USDCAD=X | 5.0% | 2.50 | 2.03 | 5 |
| ES | ES=F | 7.0% | 2.00 | 5.50 | 2 |
| NQ | NQ=F | 7.0% | 2.50 | 5.00 | 2 |
| GBPCAD | GBPCAD=X | 5.0% | 2.50 | 2.50 | 2 |
| GBPNZD | GBPNZD=X | 5.0% | 3.00 | 1.00 | 3 |
| NZDCAD | NZDCAD=X | 5.0% | 2.50 | 4.00 | 2 |
| ^DJI | ^DJI | 4.0% | 0.50 | 4.00 | 4 |
| EURUSD | EURUSD=X | 4.0% | 3.00 | 1.50 | 3 |
| NZDUSD | NZDUSD=X | 5.0% | 2.50 | 1.50 | 5 |
| GBPAUD | GBPAUD=X | 5.0% | 1.00 | 2.00 | 2 |
| NZDCHF | NZDCHF=X | 7.0% | 1.00 | 4.00 | 2 |
| CADCHF | CADCHF=X | 5.0% | 1.00 | 4.00 | 2 |
| AUDUSD | AUDUSD=X | 4.0% | 1.50 | 4.00 | 2 |
| AUDNZD | AUDNZD=X | 3.0% | 2.00 | 1.00 | 2 |
| EURCHF | EURCHF=X | 5.0% | 1.00 | 3.00 | 4 |
| EURCAD | EURCAD=X | 2.0% | 1.00 | 1.00 | 3 |
| EURNZD | EURNZD=X | 3.0% | 1.50 | 2.50 | 3 |
| GBPCHF | GBPCHF=X | 3.0% | 1.00 | 2.00 | 2 |

**Total allocation: ~1.00.**

### Removed (post walk-forward, insufficient edge)
CHFJPY, CADJPY, CL, USDJPY, BTCUSD, EURGBP, EURJPY, GBPUSD, GBPJPY, AUDCAD, NZDJPY, ^VIX, IWM

---

## 10. POSITION SIZING CONTRACT

**Strategy:** Risk-parity weights via `configs/paper_trading.yaml`
**Capital utilization cap:** `position_size` (default 0.95)
**Size scalar chain:**
```
final_size = base × governance_scalar × meta_confidence_scalar
```
- Governance scalar: validity state machine (GREEN=1.0, YELLOW=0.5, RED=0.0)
- Meta-confidence scalar: `_meta_size_multiplier()` maps [threshold, 1.0] → [min_size, 1.0]

---

## 11. ASSET SCREENING & PROMOTION CONTRACT

**Screening pipeline:**
1. `backtests/trade_analysis.py` — walk-forward style backtest with per-asset SL/TP/depth
2. `scripts/walk_forward_backtest.py` — multi-ticker validation
3. `scripts/score_tickers.py` — composite score (IC + hit rate + consistency + bidirectionality)

**Promotion criteria:**
| Condition | Threshold |
|---|---|
| 5-year profit factor | > 1.0 |
| Avg R | > 0.0 |
| All 5-fold windows positive | Preferred |

---

## 12. GOVERNANCE CONTRACT

Seven layered governance mechanisms, each independently configurable:

| Layer | Frequency | Effect | Config key |
|---|---|---|---|
| Validity state machine | Per tick | Exposure 0–100% | `halt.*` |
| Feature stability | Per retrain | Validity penalty | — |
| Meta-labeling (XGBoost) | Per signal | Size scalar [0–1] | `meta_labeling` |
| Macro narrative | Weekly | SL +10%, size −20% | `narrative_config` |
| Liquidity regime | Per signal | SL +15/30%, size −15/30%, halt | `liquidity_config` |
| PSI drift | Per cycle | Validity penalty, halt at 3+ SEVERE | — |
| Portfolio drawdown | Per cycle | Circuit breaker at −15% | `portfolio_drawdown_limit` |

See `docs/GOVERNANCE_LAYER.md` for full detail.

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

---

### Additional invariants:

11. **MT5 order lifecycle symmetry** — Every paper position open has a corresponding MT5 `place_order`; every paper close has a corresponding MT5 `close_position`; every SL/TP adjustment has a corresponding MT5 `modify_position`.
12. **Paper engine is source of truth** — If an MT5 bridge operation fails (close, modify), the paper engine state is NOT rolled back. The next open cycle will detect the orphaned MT5 position and skip the duplicate order.

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
- `trailing_activation_mult = 2.0` — trailing activates at 2× SL distance from entry

---

## 15. DISCLAIMER

Paper trading system only. No live capital execution. Not financial advice.
Past walk-forward performance is not indicative of future results.
