# LIVE SYSTEM CONTRACT — IMMUTABLE SOURCE OF TRUTH

This file defines the exact behavior of the production trading system.
Any deviation from this contract is a trading bug.
Changes require full regression validation.

---

## 1. MODEL CONTRACT

**Type:** `xgboost.XGBClassifier`
**Signature:** `model.predict_proba(X: pd.DataFrame) -> np.ndarray`
**Output shape:** `(N, 3)` — columns: `[short_prob, neutral_prob, long_prob]`
**Constructor:**
```
n_estimators=300, max_depth=2, learning_rate=0.02,
objective='multi:softprob', num_class=3,
random_state=42, n_jobs=1, tree_method='hist', verbosity=0
```
**Serialization:** `pickle.dump` / `pickle.load` to `paper_trading/models/{name}_model.pkl`

---

## 2. SIGNAL THRESHOLD CONTRACT

**Threshold value:** `0.45` (float)
**Mapping (engine.py:290-294, 310):**

| Condition | `signal` value | String label | Class label |
|---|---|---|---|
| `proba[:,2] > 0.45` (long, last check) | `2` | `BUY` | 2 |
| `proba[:,0] > 0.45` (short, first check) | `0` | `SELL` | 0 |
| Both > 0.45 | `2` (long wins — overwrites) | `BUY` | 2 |
| Neither > 0.45 | `0` (default) | `FLAT` | 1 |

**Confidence:** `confidence = max(proba[:,2], proba[:,0])`
**Confidence output:** `round(confidence * 100, 2)` (percent, 0-100 scale)

---

## 3. FEATURE CONTRACT (PER ASSET)

| Asset | Ticker | Features | Label type | Label params |
|---|---|---|---|---|---|
| BTC (satellite) | BTC-USD | `rate_diff, 2y_yield_delta_63, vix_delta_5, dxy_mom_21, vix_ma21, btc_mom_10, btc_mom_21, btc_vs_spy_21, btc_mom_63, btc_vs_spy_63` | tb20 | pt_sl=[2,2], vbar=20 |
| GC | GC=F | `real_yield_delta_63, breakeven_delta_63, dxy_mom_63, gc_mom_63` | fwd60 | window=60, threshold=0.02 |
| EURAUD | EURAUD=X | `rate_diff, dxy_mom_21, vix_ma21, vix_delta_5, euraud=x_mom_21, euraud=x_mom_63, dji_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| NZDJPY | NZDJPY=X | `vix_ma21, vix_delta_5, us_jp_10y_spread, nzdjpy=x_mom_21, dji_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| CADJPY | CADJPY=X | `vix_ma21, ca_jp_spread_mom_21, us_jp_10y_spread, vix_delta_5, ca_jp_10y_spread, dxy_mom_21, cadjpy=x_mom_10, cadjpy=x_mom_21, cadjpy=x_mom_63, dji_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| AUDJPY | AUDJPY=X | `vix_ma21, vix_delta_5, us_jp_10y_spread, audjpy=x_mom_21, audjpy=x_mom_63, nzdjpy_lead_3, dji_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| USDCAD | USDCAD=X | `rate_diff, dxy_mom_21, vix_ma21, vix_delta_5, usdcad=x_mom_21, usdcad=x_mom_63, dji_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| GBPJPY | GBPJPY=X | `vix_ma21, vix_delta_5, us_jp_10y_spread, gbpjpy=x_mom_21, gbpjpy=x_mom_63, dji_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| USDJPY | USDJPY=X | `vix_ma21, vix_delta_5, us_jp_10y_spread, dxy_mom_21, usdjpy=x_mom_21, usdjpy=x_mom_63, gc_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| USDCHF | USDCHF=X | `rate_diff, dxy_mom_21, vix_ma21, vix_delta_5, usdchf=x_mom_21, usdchf=x_mom_63, gc_lead_1` | tb20 | pt_sl=[2,2], vbar=20 |
| GBPUSD | GBPUSD=X | `rate_diff, dxy_mom_21, vix_ma21, vix_delta_5, gbpusd=x_mom_21, gbpusd=x_mom_63` | tb20 | pt_sl=[2,2], vbar=20 |
| CHFJPY | CHFJPY=X | `vix_ma21, vix_delta_5, us_jp_10y_spread, chfjpy=x_mom_21, chfjpy=x_mom_63` | tb20 | pt_sl=[2,2], vbar=20 |
| EURCAD | EURCAD=X | `rate_diff, dxy_mom_21, vix_ma21, vix_delta_5, eurcad=x_mom_21, eurcad=x_mom_63` | tb20 | pt_sl=[2,2], vbar=20 |
| ^DJI | ^DJI | `rate_diff, vix_ma21, dxy_mom_21, breakeven_delta_63, dji_mom_21, dji_mom_63, dji_vs_spy_21, dji_vs_spy_63` | tb20 | pt_sl=[2,2], vbar=20 |

**Momentum features** use `{contract_prefix}_mom_{window}` naming (e.g. `euraud=x_mom_21`), derived from the `contract_prefix` field in `features/registry.py`. **Lead-lag features** (`dji_lead_1`, `gc_lead_1`, `nzdjpy_lead_3`) are declared in `custom_features` on each asset's FeatureContract and computed from normalized leader returns shifted by the specified lag.

**tb20 label:** `apply_triple_barrier(df, pt_sl=[2,2], vertical_barrier=20)` → `{-1,0,1}` → `+1` → `{0,1,2}`
**fwd60 label:** `ret = close.pct_change(60).shift(-60)` → `2 if ret>0.02, 0 if ret<-0.02, 1 else`

---

## 4. POSITION SIZING CONTRACT

**Default:** `pos_size = 1.0` (all assets except BTC)
**BTC only:** `pos_size = _vol_scalar(df)` where:
```
rets = close.pct_change().dropna()
if len(rets) < 30: return 1.0
rv = rets.iloc[-30:].std() * sqrt(252)
if isnan(rv) or isinf(rv): return 1.0
scalar = 0.30 / (rv + 1e-9)
pos_size = min(scalar, 1.0)
```

**Position sizing multiplier:** `CONFIG['position_size'] = 0.95`
Applied in: `PositionManager.close()` → `pnl = current_value * ret * 0.95`
Applied in: `PositionManager.compute_daily_pnl()` → `current_value * direction * ret * 0.95 * pos_size`

---

## 5. SL/TP CONTRACT

**Volatility:** `returns = log(close / close.shift(1)); vol = ewm(span=100).std(); floor = 0.01`
**Multiplier:** Per-asset from `configs/paper_trading.yaml` `sl_mult`/`tp_mult`, adjusted by model-validity state machine multipliers.
**Base values (research-optimized via per-regime sweep):**

| Asset | sl_mult | tp_mult | Regime-tuned |
|-------|---------|---------|--------------|
| EURAUD | 0.30 | 1.00 | yes |
| GC | 0.30 | 1.50 | yes |
| NZDJPY | 0.30 | 1.75 | yes |
| CADJPY | 0.30 | 1.25 | yes |
| AUDJPY | 0.30 | 1.75 | yes |
| USDCAD | 0.30 | 1.50 | yes |
| GBPJPY | 0.30 | 1.25 | yes |
| USDJPY | 0.30 | 1.00 | yes |
| USDCHF | 0.30 | 1.75 | yes |
| CHFJPY | 0.30 | 1.00 | yes |
| EURCAD | 0.30 | 1.75 | yes |
| ^DJI | 0.30 | 1.50 | yes |
| GBPUSD | 0.52 | 1.97 | no (plateau default) |
| BTC (satellite) | 0.58 | 1.51 | no (plateau default) |

**Regime-validity adjustment:** When model validity state is YELLOW, TP is multiplied by 0.85; when RED, TP × 0.70. SL stays at base multiplier across all states.

**Formulas:**
```
sl_mult_effective = base_sl_mult × validity_sl_mult
tp_mult_effective = base_tp_mult × validity_tp_mult

long:  sl = entry × (1 - vol × sl_mult_effective)
       tp = entry × (1 + vol × tp_mult_effective)
short: sl = entry × (1 + vol × sl_mult_effective)
       tp = entry × (1 - vol × tp_mult_effective)
```

---

## 6. PnL CONTRACT

**Close trade:**
```
ret = (exit/entry - 1) if long else (entry/exit - 1)
pnl = current_value * ret * 0.95
current_value += pnl
```

**Daily mark-to-market (no open position):**
```
direction = 1 if signal==2 else -1 if signal==0 else 0
ret = today_close / prev_close - 1
pnl = current_value * direction * ret * 0.95 * pos_size
```

**SL/TP check (position held):**
```
long:  price <= sl → ("sl", sl);  price >= tp → ("tp", tp)
short: price >= sl → ("sl", sl);  price <= tp → ("tp", tp)
```

**Additional exit reasons:**
```
time_stop:                force-closed after max_holding_days (default 30) calendar days
portfolio_circuit_breaker: force-closed by portfolio-level drawdown limit (-15%)
```

---

## 7. PORTFOLIO ALLOCATION CONTRACT

**Core portfolio (13 assets, cash buffer ~3%):**

| Asset | Ticker | Allocation | Driver cluster |
|---|---|---|---|
| EURAUD | EURAUD=X | 0.12 | eur_cross |
| GC | GC=F | 0.13 | real_asset |
| NZDJPY | NZDJPY=X | 0.11 | carry_fx |
| CADJPY | CADJPY=X | 0.09 | oil_carry |
| CHFJPY | CHFJPY=X | 0.07 | carry_fx |
| AUDJPY | AUDJPY=X | 0.06 | carry_fx |
| USDCAD | USDCAD=X | 0.08 | usd_macro |
| GBPJPY | GBPJPY=X | 0.08 | carry_fx |
| EURCAD | EURCAD=X | 0.05 | eur_cross |
| ^DJI | ^DJI | 0.05 | equity_index |
| GBPUSD | GBPUSD=X | 0.05 | usd_macro |
| USDJPY | USDJPY=X | 0.04 | usd_macro |
| USDCHF | USDCHF=X | 0.04 | usd_macro |

**BTC satellite bucket:**
| Property | Value |
|---|---|
| Allocation | 5% AUM cap |
| Vol target | 40% annualised |
| Drawdown limit | 25% |
| Regime gate | 5-condition AND logic (correlation, BTC vol, VIX, DXY momentum, CRISIS) |

**Capital:** $100,000
**Sum constraint:** `sum(core_allocations) ≈ 0.97` (cash buffer of ~3%)

---

## 8. HALT CONDITIONS CONTRACT

**Default thresholds:**
```
drawdown: -0.08               # halt if drawdown <= -8%
monthly_pf: 0.70              # halt if monthly profit factor < 0.70
signal_drought: 30            # halt if no signal in 30 days
prob_drift: 0.15              # halt if |mean_conf - 0.45| > 0.15
```

**Portfolio-level circuit breaker:**
```
portfolio_drawdown_limit: -0.15   # force-close ALL positions when total equity drawdown <= -15%
```
Triggered at the start of each `run_once()` cycle, before signal generation. Closes positions with reason `portfolio_circuit_breaker`. Tracks portfolio peak value across engine ticks.

**Per-asset trade quality config (all assets):**
```
min_confidence: 50          # skip trade if model confidence < 50%
max_holding_days: 30        # force-close after N calendar days, reason `time_stop`
```
Applied in `asset_engine._apply_decision()` (min_confidence) and `asset_engine.update_pnl()` (max_holding_days).

**Per-asset override:** BTC drawdown = -0.15, NZDJPY drawdown = -0.06

**Validity scoring:**
```
score = 0.80
score -= 0.25 if drawdown_not_ok
score -= 0.20 if monthly_pf_not_ok
score -= 0.15 if drought_not_ok
score -= 0.15 if drift_not_ok
score = clip(0.0, 1.0, score)
→ ValidityStateMachine.transition(score)
```

**ValidityStateMachine parameters:**
```
green_entry: 0.70, green_exit: 0.60
yellow_entry: 0.45, yellow_exit: 0.40
red_entry: 0.40, red_exit: 0.50
inertia_alpha: 0.7, inertia_beta: 0.3
regime_lock_periods: 5, regime_lock_window: 10
exposure: GREEN=1.0, YELLOW=0.5, RED=0.0
```

**Execution state derived from validity:**
```
HALTED if any asset halted OR portfolio circuit breaker triggered
PAUSED if average_validity_exposure < 0.5
ACTIVE otherwise
```

---

## 9. MACRO DERIVED FEATURES CONTRACT

Derived from `data/processed/macro_factors.parquet`:
```
rate_diff = fed_funds - ecb_rate
2y_yield_delta_63 = us_2y.diff(63)
dxy_mom_63 = dxy.pct_change(63)
dxy_mom_21 = dxy.pct_change(21)
vix_ma21 = vix.rolling(21).mean()
vix_delta_5 = vix.diff(5)
us_jp_10y_spread = us_10y - jp_10y
ca_jp_10y_spread = ca_10y - jp_10y
ca_jp_spread_mom_21 = ca_jp_10y_spread.diff(21)
ca_jp_spread_mom_5 = ca_jp_10y_spread.diff(5)
real_yield_delta_63 = real_yield_10y.diff(63)
breakeven_delta_63 = breakeven_10y.diff(63)
```
Warmup: first 90 days dropped after derivation.

---

## 10. ALLOWED IMPORTS

Live system (`paper_trading/`) may only import:
```
standard library: os, sys, json, pickle, math, copy, time, threading,
                  signal, logging, dataclasses, http.server, socketserver,
                  abc, enum, fcntl
third-party: pandas, numpy, xgboost, yfinance, yaml, pytz
intra-project:
  features.builder, features.contract, features.registry
  labels.triple_barrier
  monitoring.validity_state_machine
  paper_trading.* (own package)
  execution.paper_broker
  paper_trading.execution_bridge
  shared.execution_config
  shared.registry
  quantforge (setup_logging)
```

**SAFE shared interfaces:** shared.model, shared.signal, shared.sizing, shared.pnl, shared.features, shared.registry

**FORBIDDEN at runtime:** execution.*, portfolio.*, risk.*, signals.*,
models.*, diagnostics.*, equity.*, backtests.*, scripts.*,
data.weekly_pipeline, data.loaders.*, features.{base,regime,structural,
interaction,cot,pair_specific,mean_reversion,trend,volatility,cross_asset},
archive.*, configs.driver_atlas

---

## 11. DATA SOURCES CONTRACT

| Data | Source | Path | Format |
|---|---|---|---|
| Asset prices | yfinance | live fetch | OHLCV DataFrame |
| Macro factors | `data/processed/macro_factors.parquet` | `compute_macro_derived()` | Parquet → derived columns |
| SPY reference | yfinance | `fetch_ref('SPY')` | OHLCV DataFrame |
| Cached models | disk | `paper_trading/models/{name}_model.pkl` | pickle |
| Engine state | disk | `data/live/state.json` | JSON |
| Trade journal | disk | `data/live/trade_journal.parquet` | Parquet |
| Equity curve | disk | `data/live/equity_history.json` | JSON |

---

## 12. REFRESH CONTRACT

**Interval:** 300 seconds (5 minutes, configurable via `QUANTFORGE_REFRESH_INTERVAL` env var)
**On each refresh:** run_once() → save_state()
**On startup:** Load cached models or train, initialize broker+execution configs, run_once(), save_state(), start HTTP server
**HTTP server:** port 5000, daemon thread, endpoints:
  `/` → index.html (static)
  `/state.json` → EngineSnapshot JSON
  `/trades.json` → recent trades (Parquet or snapshot)
  `/equity_history.json` → equity curve
  `/logs` → tail of engine.log
