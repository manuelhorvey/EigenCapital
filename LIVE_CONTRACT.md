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
| 2 | GC, ES, NQ, GBPCAD, NZDCAD, NZDCHF, CADCHF, AUDUSD, GBPCHF, EURAUD |
| 3 | GBPAUD, EURCAD, EURNZD |
| 4 | USDCHF, ^DJI, EURCHF |
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

### Ensemble (Disabled 2026-06-20)
**Weight:** `base_weight = 1.0` (regime model not loaded at inference)
**Status:** Disabled portfolio-wide after walk-forward PnL comparison (+2.5% / p=0.0446 raw, fails Bonferroni correction). Regime model training path still active for future re-enable; see `docs/adr/ADR-026-ensemble-disabled.md`.
**Re-enable criteria:** Pooled sign test p < 0.10 across 25+ assets AND ≥3 assets with per-asset sign-p < 0.10 on ≥6 months fresh OOS data.

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

13 features total (9 per-asset + 4 cross-asset), all with per-asset prefix (`{ASSET}_`):

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

### Sell-Only Filter (Decision Pipeline Stage)

Applied at decision pipeline stage `g`. Overrides BUY signals to FLAT for assets where the model's BUY calibration is inverted (p_long > 0.5 → ~17% win rate). SELL signals pass through unchanged. See `2026-06-20 diagnostic chain` for full evidence.

**SELL_ONLY_ASSETS** (`paper_trading/execution/decision_pipeline.py:415`):
```
CADCHF, AUDUSD, ES, NQ, NZDCHF, EURAUD, ^DJI, USDCHF, EURCHF, NZDUSD, EURNZD
```

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
| `MT5` / `yfinance` | Daily OHLCV for all assets + macro (DXY=DX-Y.NYB, VIX=^VIX, SPX=^GSPC, WTI=CL=F, TNX=^TNX) | Daily bars |

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

**Halt parameters** (from `configs/paper_trading.yaml`, global defaults overridable per asset):

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
**Data window:** 5y history from yfinance (`_FETCH_PERIOD = "5y"`, `_FETCH_WARMUP_BUFFER = 1250`), train on last `retrain_window` years (default 5)
**Feature builder:** `build_alpha_features()` — 13 alpha feature columns (9 per-asset + 4 cross-asset)
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
- Loaded at engine startup by `_train_regime_if_configured()` — skipped when `base_weight >= 1.0`
- Ensemble disabled portfolio-wide (base_weight=1.0) — regime models not loaded at inference

**Post-training:**
- Persist PSI baseline from training feature distribution
- Train optional meta-label model (XGBoost)
- Log feature importances + stability (Jaccard + Spearman)

---

## 7. INFERENCE PIPELINE CONTRACT

**Pipeline:** `paper_trading/inference/pipeline.py:AssetInferencePipeline._generate_and_apply()`
**Per-cycle (every 30s):**

1. `fetch_live(ticker)` — 5y OHLCV, deduplicate index
2. Normalize index to UTC TZ-naive
3. `refresh_price()` — patch last close with real-time or 5d fallback
4. `ffill()` close column
5. `fetch_asset_data()` + `build_alpha_features()` — 13 alpha feature cols
6. Compute regime features from OHLCV (7 cols via `generate_regime_features`)
7. Compute archetype features (ema_spread, adx, rsi, bb_zscore)
8. PSI drift check (rolling 21d vs baseline; skipped on first cycle)
9. Inference truncation validation — if proven safe, predict only last row
10. XGBoost predict → 3-column proba expansion `[p_short, 0, p_long]`
11. Ensemble blend skipped (regime model not loaded — disabled portfolio-wide)
12. Optional meta-label inference
13. `FixedThresholdStrategy(0.45)` → BUY/SELL/FLAT
14. Archetype classification → `TradeDecision`
15. Refresh MT5 spread for spread gate
16. Decision pipeline stages (applied sequentially):
    a. First-cycle suppression — suppress trading on cold-start cycle 1
    b. Bar-jump suppression — suppress 60min if bar count changed >100
    c. Store prediction metadata — record pre-decision signal state
    d. Update MAE/MFE — update max adverse/favorable excursion
    e. Resolve signal — map proba to BUY/SELL/FLAT
    f. Risk-off suppression — flat AUDUSD when VIX>0 & SPX<0 (AUDCHF removed from trading)
    g. Sell-only filter — override BUY→FLAT for 11 SELL_ONLY assets (inverted BUY calibration)
    h. Spread gate — block entry if spread > per-class threshold (observe 720 cycles first)
    i. Confidence gate — abort if net confidence below threshold
    j. Signal stability filter — require >0.65 max(prob_long, prob_short)
    k. Signal hysteresis — 2-of-3 agreement before flip
    l. Meta-label advisory — record meta-label recommendation without enforcement
    m. Update regime bar counter — track bars since last regime shift
    n. Conviction gate — flip gate based on regime conviction
    o. Profit lock gate — block flip if unrealized PnL > threshold
    p. Manage position — close/re-open with entry gate check
    q. Build entry artifacts — construct TradeDecision for execution
    r. Route execution policy — direct to PaperBroker or MT5Broker
    s. Poll deferred entries — execute previously deferred pending orders
17. Route through governance layers (9 layers)
18. Position sizing chain (drawdown taper → cap → risk cap → leverage budget → backstop)
19. Independent MT5 sizing (`_compute_mt5_qty` with broker equity)
20. Execute position lifecycle:
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

### Current assets (18 promoted)
| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|---|---|---|
| GC | GC=F | 7.0% | 1.00 | 4.00 | 2 |
| USDCHF | USDCHF=X | 4.0% | 0.85 | 3.00 | 4 |
| USDCAD | USDCAD=X | 2.5% | 2.50 | 2.03 | 5 |
| ES | ES=F | 7.0% | 2.00 | 5.50 | 2 |
| NQ | NQ=F | 7.0% | 2.50 | 5.00 | 2 |
| GBPCAD | GBPCAD=X | 5.0% | 2.50 | 2.50 | 2 |
| NZDCAD | NZDCAD=X | 5.0% | 2.50 | 4.00 | 2 |
| ^DJI | ^DJI | 4.0% | 0.50 | 4.00 | 4 |
| NZDUSD | NZDUSD=X | 2.5% | 2.50 | 1.50 | 5 |
| GBPAUD | GBPAUD=X | 5.0% | 1.00 | 2.00 | 3 |
| NZDCHF | NZDCHF=X | 7.0% | 1.00 | 4.00 | 2 |
| CADCHF | CADCHF=X | 5.0% | 1.00 | 4.00 | 2 |
| AUDUSD | AUDUSD=X | 4.0% | 1.50 | 4.00 | 2 |
| EURCHF | EURCHF=X | 5.0% | 1.00 | 3.00 | 4 |
| EURCAD | EURCAD=X | 2.0% | 1.00 | 1.00 | 3 |
| EURNZD | EURNZD=X | 3.0% | 1.50 | 2.50 | 3 |
| GBPCHF | GBPCHF=X | 3.0% | 1.00 | 2.00 | 2 |
| EURAUD | EURAUD=X | 1.0% | 0.54 | 1.77 | 2 |

**Total allocation: ~0.95** (remaining capacity held as cash buffer).

### Removed from trading (2026-06-20)
AUDCHF, EURUSD, AUDNZD — removed after walk-forward diagnostic confirmed base model directional instability (confident wrong-direction bets during trend periods).

**2026-06-20 (late): GBPNZD** removed — tp/sl=1.0/3.0 (ratio 0.33), breakeven WR 75%, achieved 72.3%. Net-negative — lost -37R total with -71R max drawdown.

**USDCAD/NZDUSD allocation halved** from 5% → 2.5% to limit drawdown impact while keeping diversification.

### Previously removed (post walk-forward, insufficient edge)
CHFJPY, CADJPY, CL, USDJPY, BTCUSD, EURGBP, EURJPY, GBPUSD, GBPJPY, AUDCAD, NZDJPY, ^VIX, IWM

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

11 layered governance mechanisms plus position sizing guardrails, decision pipeline suppression stages, circuit breaker, and HealthMonitor, each independently configurable:

| Layer | Frequency | Effect | Config key |
|---|---|---|---|---|---|
| Validity state machine | Per tick | Exposure 0–100% | `halt.*` |
| Feature stability | Per retrain | Validity penalty | — |
| Meta-labeling (XGBoost) | Per signal | Size scalar [0–1] | `meta_labeling` |
| Macro narrative | Weekly | SL +10%, size −20% | `narrative_config` |
| Liquidity regime | Per signal | THIN: SL +15%, size −15% (soft) | `liquidity_config` |
| | | STRESSED: SL +30%, size −30%, hard halt | |
| PSI drift | Per cycle | Validity penalty, halt at 3+ SEVERE | — |
| Sell-only filter | Per decision | Override BUY→FLAT for 11 inverted-BUY assets | `SELL_ONLY_ASSETS` (hardcoded) |
| Equity cluster alarm | Per cycle | Flags ES/NQ/^DJI all on same side (recommendation) | (hardcoded, 60s throttle) |
| Portfolio drawdown | Per cycle | Circuit breaker at −15% | `portfolio_drawdown_limit` |
| Circuit breaker | Per cycle | Multi-condition: dd, vol spike, halt ratio, consecutive losses (threshold=7) | (hardcoded in `CircuitBreaker`) |
| Entry price deviation | Per entry | Skips entry if price moved > `max_entry_slippage_pct` (def 2%) | `max_entry_slippage_pct` |
| Profit lock | Per flip | Blocks flip if unrealized PnL > `profit_lock_threshold_pct` (def 15%) | `profit_lock_threshold_pct` |

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
| Risk-off suppression | Flat AUDUSD when VIX>0 & SPX<0 (AUDCHF removed) | (hardcoded, per-asset pair) |
| Sell-only filter | Override BUY→FLAT for `SELL_ONLY_ASSETS` | (hardcoded frozenset, 11 assets) |
| Spread gate | Block entry if spread > per-class tier (observe 720 cycles first) | `spread_gate_tiers` (fx_major=10bps, fx_cross=20bps, indices=15bps, metals=20bps) |
| Confidence gate | Abort if net confidence below threshold | `min_confidence` (default 50) |
| Signal stability filter | Require >0.65 max(prob_long, prob_short) | `stability_margin` (default 0.15) |
| Signal hysteresis | 2-of-3 agreement before flip allowed | HYSTERESIS_WINDOW=3, HYSTERESIS_MIN_AGREE=2 |
| Meta-label advisory | Record meta-label recommendation (no enforcement) | — |
| Update regime bar counter | Track bars since last regime shift | — |
| Conviction gate | Flip gate based on regime conviction | `_evaluate_flip_gate()` |
| Profit lock gate | Block flip if unrealized PnL > `profit_lock_threshold_pct` | `profit_lock_threshold_pct` (default 15%) |
| Manage position | Close/re-open with entry gate check | `_can_enter()` |
| Build entry artifacts | Construct `TradeDecision` for execution | — |
| Route execution policy | Direct to PaperBroker or MT5Broker | — |
| Poll deferred entries | Execute pending deferred orders | — |

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
12. Exit reason canonicalization — all exit reasons are UPPERCASE (FLIP, SL, TP, BREAKEVEN, EXPIRY, GATE_CLOSED, PORTFOLIO_CIRCUIT_BREAKER, SELL_ONLY_FILTER)
13. **MT5 order lifecycle symmetry** — Every paper position open has a corresponding MT5 `place_order`; every paper close has a corresponding MT5 `close_position`; every SL/TP adjustment has a corresponding MT5 `modify_position`.
14. **Paper engine is source of truth** — If an MT5 bridge operation fails (close, modify), the paper engine state is NOT rolled back. The next open cycle will detect the orphaned MT5 position and skip the duplicate order.
15. **Independent paper/MT5 sizing** — Paper positions are sized from paper mtm_value ($100K capital) with paper-specific drawdown and leverage budget. MT5 positions are sized from the real broker account balance with MT5-specific drawdown. The two sizing paths never interfere.
16. **No MT5 equity fetch in orchestrator** — The `EngineOrchestrator` does not fetch broker equity. MT5 sizing occurs at submission time (`_submit_mt5_order`) via `_compute_mt5_qty()`. Paper sizing uses the pre-Phase 1 equity snapshot from `sum(asset.mtm_value)`.
17. **HealthMonitor runs in Phase 3g** — `HealthMonitor.observe()` computes portfolio vol, VaR(95), CVaR, halt ratio, equity cluster alarm, and circuit breaker checks. `RecoveryScheduler.probe()` checks halted actors with exponential backoff for re-enablement.
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
- `trailing_activation_mult` and `trailing_distance_mult` are per-asset from `configs/paper_trading.yaml` (ranges: activation 0.3–1.0, distance 0.5–1.5)

---

## 15. DISCLAIMER

Paper trading system only. No live capital execution. Not financial advice.
Past walk-forward performance is not indicative of future results.
