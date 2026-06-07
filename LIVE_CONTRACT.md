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
| 2 | GC, AUDCHF, ES, NQ, GBPCAD, NZDCAD |
| 3 | GBPNZD, EURUSD |
| 4 | USDCHF, ^DJI |
| 5 | USDCAD, NZDUSD |

**Signature:** `model.predict(X: pd.DataFrame) -> np.ndarray`
**Output shape:** `(N, 1)` — raw probability of LONG class
**Pipeline expansion:** Raw output is expanded to 3-column proba `[p_short, 0, p_long]` in
`paper_trading/inference/pipeline.py:_generate_and_apply()`
**Serialization:** `model.save_model(path)` / `model.load_model(path)` — `.json` format
**Path:** `paper_trading/models/{asset_name}_model.json`

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

**Primary builder:** `features/builder.py:build_features()`
**Per-asset contract:** Defined in `features/registry.py:FEATURE_REGISTRY` (36 tickers).
**Input:** Per-asset features from `contract.features` — macro filters + price momentum + custom features.

### Per-asset features (dashboard assets):

| Asset | Features |
|-------|----------|
| GC | `real_yield_delta_63`, `breakeven_delta_63`, `dxy_mom_63`, `gc=f_mom_63` |
| USDCHF | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `usdchf=x_mom_21`, `usdchf=x_mom_63`, `gc_lead_1` |
| AUDCHF | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `audchf=x_mom_21`, `audchf=x_mom_63` |
| USDCAD | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `usdcad=x_mom_21`, `usdcad=x_mom_63`, `dji_lead_1` |
| ES | `rate_diff`, `vix_ma21`, `dxy_mom_21`, `breakeven_delta_63`, `es=f_mom_21`, `es=f_mom_63` |
| NQ | `rate_diff`, `vix_ma21`, `dxy_mom_21`, `nq=f_mom_21`, `nq=f_mom_63` |
| GBPCAD | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `gbpcad=x_mom_21`, `gbpcad=x_mom_63` |
| GBPNZD | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `gbpnzd=x_mom_21`, `gbpnzd=x_mom_63` |
| NZDCAD | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `nzdcad=x_mom_21`, `nzdcad=x_mom_63` |
| ^DJI | `rate_diff`, `vix_ma21`, `dxy_mom_21`, `breakeven_delta_63`, `^dji_mom_21`, `^dji_mom_63` |
| EURUSD | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `eurusd=x_mom_21`, `eurusd=x_mom_63` |
| NZDUSD | `rate_diff`, `dxy_mom_21`, `vix_ma21`, `vix_delta_5`, `nzdusd=x_mom_21`, `nzdusd=x_mom_63` |

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
- `fetch_live(ticker)` — 500 days, truncated to 250d for XGBoost (TZ-aware → normalized to UTC date via `pipeline.py:51-56`)
- All date indices are `datetime64[ns]` at daily resolution (no intraday)
- No FRED data — all macro derived from yfinance tickers

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
**Data window:** 10y history from yfinance, train on last `retrain_window` years (default 5)
**Minimum samples:** 100 binary labels; 2+ unique classes
**Train/val split:** 80/20 chronological, stratified by label if minimum class count ≥ 2
**Per-asset max_depth** from `yaml` config (default 2).
**Post-training:**
- Persist PSI baseline from training feature distribution
- Train optional meta-label model (XGBoost)
- Log feature importances + stability (Jaccard + Spearman)

---

## 7. INFERENCE PIPELINE CONTRACT

**Pipeline:** `paper_trading/inference/pipeline.py:AssetInferencePipeline._generate_and_apply()`
**Per-cycle (every 300s / 5 min):**

1. `fetch_live(ticker)` — 250 days OHLCV
2. Normalize index to UTC TZ-naive
3. `refresh_price()` — patch last close with real-time or 5d fallback
4. `ffill()` close column
5. `build_features()` — per-asset feature set from FEATURE_REGISTRY
6. Compute archetype features (ema_spread, adx, rsi, bb_zscore)
7. PSI drift check (rolling 21d vs baseline; skipped on first cycle)
8. XGBoost predict → 3-column proba expansion
9. Optional meta-label inference
10. `FixedThresholdStrategy.compute()` → signal + decision
11. Archetype classification → `TradeDecision`
12. Route through governance layers
13. Execute position lifecycle

---

## 8. PORTFOLIO CONTRACT

**Builder:** `paper_trading/portfolio_builder.py:build_paper_portfolio()`
**Source:** `configs/paper_trading.yaml`

### Current assets (12 promoted)
| Asset | Ticker | Allocation | sl_mult | tp_mult | max_depth |
|---|---|---|---|---|---|---|
| GC | GC=F | 11.0% | 1.00 | 4.00 | 2 |
| USDCHF | USDCHF=X | 5.0% | 0.85 | 3.00 | 4 |
| AUDCHF | AUDCHF=X | 7.0% | 2.75 | 3.50 | 2 |
| USDCAD | USDCAD=X | 7.0% | 2.50 | 2.03 | 5 |
| ES | ES=F | 12.0% | 2.00 | 5.50 | 2 |
| NQ | NQ=F | 10.0% | 2.50 | 5.00 | 2 |
| GBPCAD | GBPCAD=X | 7.0% | 2.50 | 2.50 | 2 |
| GBPNZD | GBPNZD=X | 7.0% | 3.00 | 1.00 | 3 |
| NZDCAD | NZDCAD=X | 7.0% | 2.50 | 4.00 | 2 |
| ^DJI | ^DJI | 5.0% | 0.50 | 4.00 | 4 |
| EURUSD | EURUSD=X | 5.0% | 3.00 | 1.50 | 3 |
| NZDUSD | NZDUSD=X | 7.0% | 2.50 | 1.50 | 5 |

**Total allocation: 0.90 (10% cash).**

### Removed (post walk-forward, insufficient edge)
CHFJPY, AUDNZD, CADCHF, CADJPY, CL, EURCAD, GBPCHF, USDJPY, BTCUSD, EURGBP, EURJPY, NZDCHF, GBPUSD, GBPJPY, GBPAUD, AUDCAD, EURCHF, NZDJPY, ^VIX, IWM

---

## 9. POSITION SIZING CONTRACT

**Strategy:** Risk-parity weights via `configs/paper_trading.yaml`
**Capital utilization cap:** `position_size` (default 0.95)
**Size scalar chain:**
```
final_size = base × governance_scalar × meta_confidence_scalar
```
- Governance scalar: validity state machine (GREEN=1.0, YELLOW=0.5, RED=0.0)
- Meta-confidence scalar: `_meta_size_multiplier()` maps [threshold, 1.0] → [min_size, 1.0]

---

## 10. ASSET SCREENING & PROMOTION CONTRACT

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

## 11. GOVERNANCE CONTRACT

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

## 12. SYSTEM INVARIANTS

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

## 13. DISCLAIMER

Paper trading system only. No live capital execution. Not financial advice.
Past walk-forward performance is not indicative of future results.
