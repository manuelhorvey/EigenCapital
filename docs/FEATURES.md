# EigenCapital — Feature Engineering

## Alpha Features

The primary feature builder is `features/alpha_features.py:build_alpha_features()`. Every asset uses base alpha features (9 core per-asset + 6 trend-exhaustion + 4 cross-asset + 10 directional momentum/carry splits + 15 FXStreet narrative cross-asset features) with per-asset prefix, including trend-exhaustion indicators, directional splits, and narrative overlays. During training, additional feature groups are appended: Group 1 (cross-sectional momentum), Group 2 (positioning/volume momentum), Group 3 (rates & carry), and Group 4 (event/calendar features), expanding the total feature count significantly beyond the base set. COT features were deprecated 2026-07-09 after walk-forward validation showed zero gain across all 22 assets. The per-asset contracts in `features/registry.py` are used by the backtest pipeline for custom feature variants.

> **See also:** [`docs/INSTITUTIONAL_AUDIT_REPORT.md`](INSTITUTIONAL_AUDIT_REPORT.md) — full 9-phase forensic audit covering feature integrity (no look-ahead bias), feature stability (PSI/drift analysis), and feature-directional capability analysis across all 22 assets.

### Input Data

Data ingested from MT5 bridge (primary) or yfinance (fallback):

| Source | Symbol | Data |
|---|---|---|
| Asset ticker | e.g. `GC=F` | Daily OHLCV close |
| Dollar index | `DX-Y.NYB` | DXY close |
| VIX | `^VIX` | VIX close |
| SPX | `^GSPC` | S&P 500 close |
| Crude oil | `CL=F` | WTI close |

### Feature Categories

#### Per-Asset Core Features (9 cols via `build_alpha_features()`)

| Feature | Description |
|---|---|
| `{ASSET}_carry_vol_adj` | Volatility-adjusted carry |
| `{ASSET}_mom_21d` | 21-day momentum |
| `{ASSET}_mom_63d` | 63-day momentum |
| `{ASSET}_mom_126d` | 126-day momentum |
| `{ASSET}_mom_252d` | 252-day momentum |
| `{ASSET}_zscore_20` | 20-day z-score vs SMA |
| `{ASSET}_vol_ratio` | Short/long-term vol ratio |
| `{ASSET}_dow_signal` | Day-of-week encoding |
| `{ASSET}_has_cot` | COT data availability flag (zero-filled for pairs not in CFTC data) |

#### Per-Asset Directional Split Features (10 cols, added 2026-07-11)

Directional momentum and carry splits decompose features into positive/negative components.
Mathematically redundant with the base feature (XGBoost handles direction via splits), but
kept for interpretability. Walk-forward validation confirmed **0 splits** across all 22 models
— the splits carry no incremental information.

| Feature | Description |
|---|---|
| `{ASSET}_mom_21d_up` | Positive component of 21d momentum (0 if negative) |
| `{ASSET}_mom_21d_dn` | Negative component of 21d momentum (0 if positive) |
| `{ASSET}_mom_63d_up` | Positive component of 63d momentum |
| `{ASSET}_mom_63d_dn` | Negative component of 63d momentum |
| `{ASSET}_carry_up` | Positive carry component |
| `{ASSET}_carry_dn` | Negative carry component |

#### Per-Asset COT Features (2 cols, added per covered pair)

| Feature | Description |
|---|---|
| `{ASSET}_cot_z` | COT speculative positioning z-score |
| `{ASSET}_cot_change_4w` | 4-week change in COT net positioning |

> **COT features — DEPRECATED 2026-07-09:** Walk-forward validation showed zero gain across all 22 assets. The function `fetch_cot_features()` now returns an empty DataFrame. No COT columns are produced in training or inference. Kept as placeholder columns for backward compatibility.

#### Training-Only Feature Groups (Groups 1-4)

During training via `AssetTrainingPipeline.train()`, four additional feature groups are appended to the base alpha set. These are NOT reproduced in the live inference pipeline (which uses the base alpha set from `build_alpha_features()` plus regime + archetype features):

**Group 1 — Cross-Sectional Features** (`features/cross_sectional.py`): Momentum-based features computed across the full asset panel. Requires `full_panel` DataFrame passed to `train()`. Added in `training.py:131-141`.

**Group 2 — Positioning & Volume Features** (`features/positioning_features.py`): Volume momentum and open interest indicators from OHLCV volume. See `training.py:144-152`.

**Group 3 — Rates & Carry Features** (`features/rates_features.py`): Government bond yield curves, rate differentials, and carry proxies via FRED/yfinance. See `training.py:155-169`.

**Group 4 — Event & Calendar Features** (`features/event_features.py`): Calendar-based features (month-end, FOMC, NFP, etc.) from the date index. See `training.py:172-178`.

#### Per-Asset Trend-Exhaustion Features (6 cols, added 2026-06-26)

Require OHLCV data passed to `build_alpha_features()`. Computed via the `ta` library. See `features/divergence.py` for RSI divergence detection logic.

| Feature | Description |
|---|---|
| `{ASSET}_macd_hist` | MACD histogram normalized by close (±5% clip) |
| `{ASSET}_stoch_k` | Stochastic %K normalized to [0, 1] |
| `{ASSET}_stoch_d` | Stochastic %D (signal line) |
| `{ASSET}_bb_pct_b` | Bollinger Band %B: (close - lower) / (upper - lower) |
| `{ASSET}_adx_slope` | ADX rate of change over 5 days |
| `{ASSET}_rsi_divergence` | RSI divergence (-1 bearish / 0 none / +1 bullish) |

#### Cross-Asset Features (4 cols)

| Feature | Source | Description |
|---|---|---|
| `dxy_mom_21d` | DX-Y.NYB | Dollar 21-day return |
| `vix_mom_5d` | ^VIX | VIX 5-day return |
| `spx_mom_5d` | ^GSPC | S&P 500 5-day return |
| `WTI_mom_21d` | CL=F | WTI crude 21-day return |

#### FXStreet Narrative Features (15 cols, added 2026-07-11)

Weekly-frequency macro sentiment features extracted via LLM from FXStreet weekly forecasts.
Loaded from `data/live/narrative_active.json` by `features/alpha_features.py:_compute_narrative_features()`.
Broadcast as constant values across all rows in the same week (same frequency as DXY/VIX/SPX features).

| Feature | Description |
|---|---|
| `usd_strength_narr` | USD strength score (0-1) |
| `geopol_risk` | Geopolitical risk score (0-1) |
| `fed_hawk` | Fed hawkishness score (0-1) |
| `rbnz_hawk` | RBNZ hawkishness score (0-1) |
| `rba_hawk` | RBA hawkishness score (0-1) |
| `boj_intervene_risk` | BOJ intervention risk score (0-1) |
| `energy_pressure` | Energy price pressure score (0-1) |
| `usd_bias_num` | USD directional bias (-1/0/+1) |
| `nzd_bias_num` | NZD directional bias (-1/0/+1) |
| `aud_bias_num` | AUD directional bias (-1/0/+1) |
| `jpy_bias_num` | JPY directional bias (-1/0/+1) |
| `cad_bias_num` | CAD directional bias (-1/0/+1) |
| `eur_bias_num` | EUR directional bias (-1/0/+1) |
| `regime_risk_on` | Risk-on regime indicator (0/1) |
| `regime_geopol` | Geopolitical regime indicator (0/1) |

**Empirical impact:** Walk-forward validation showed zero change in BUY/SELL information gap
compared to pre-narrative baseline. Weekly-frequency macro sentiment is already partially captured
by existing DXY/VIX/SPX features. Narrative pipeline remains valuable for **governance** (SL widening,
position sizing during risk-off regimes) but contributes no incremental predictive signal as a model feature.

### Custom Feature Variants

Some assets have additional or replacement features beyond the base set.
Custom features are defined in `features/registry.py` via `custom_features` tuples
and `price_mom_windows` overrides.

| Asset | Custom features | Notes |
|-------|----------------|-------|
| EURCHF | `mom126` (+126d momentum, replaces base mom), `gc_lead_1` | Added 2026-07-16 |
| NZDUSD | `mom126` (+126d momentum, replaces base mom), `gc_lead_1`, `dji_lead_1` | Variance compressed since 10y retrain |
| GBPAUD | `yield_slope` (US yield curve slope) | |
| CADCHF | `yield_slope`, `gc_lead_1` | |
| EURNZD | `yield_slope` | |
| GBPCHF | `yield_slope`, `gc_lead_1`, `mom126` (+126d momentum) | 126d window fixed collapse at depth=4 |
| AUDUSD | `gc_lead_1` | Added 2026-07-16; did not restore edge |
| NZDJPY | `dji_lead_1`, `gc_lead_1` | |
| AUDJPY | `nzdjpy_lead_3`, `dji_lead_1` | |
| USDJPY | `gc_lead_1` | |
| USDCHF | `gc_lead_1` | |
| NZDCHF | `gc_lead_1` | |
| USDCAD | `dji_lead_1` | |
| EURAUD | `dji_lead_1` | |
| GBPJPY | `dji_lead_1`, `gc_lead_1` | |
| NZDCAD | (none) | Depth=4 compensates for generic features |

## Archetype Features

Computed inline in `paper_trading/inference/pipeline.py:_generate_and_apply()` from full-history OHLCV:

| Feature | Formula | Window |
|---|---|---|
| `ema_spread` | (EMA20 − EMA50) / EMA50 | 20/50 |
| `adx` | ADX(high, low, close) | 14 |
| `rsi` | RSI(close) | 14 |
| `bb_zscore` | (close − BB_mavg) / (BB_std / 2) | 20 |

These are inference-only — used by `ArchetypeClassifier` but never passed to XGBoost.

## Labeling

`features/labels.py:triple_barrier_labels()` (uses Per-barrier ATR method):


1. Compute ATR-based barrier distances from `pt_sl = (tp_mult, sl_mult)` per asset
2. Apply triple-barrier touch: first touch of TP (+1), SL (-1), or vertical barrier → {-1, 0, 1}
3. Training pipeline drops HOLD (0) labels and maps {-1, 1} → {0, 1} for binary XGBoost

Per-asset `pt_sl` from per-asset YAML files in `configs/domains/assets/` (e.g., `configs/domains/assets/GBPUSD.yaml`).

## Feature Contract Validation

`features/contract.py` provides `FeatureContract` dataclass and `validate_no_cross_asset_leakage()`.

## Lead-Lag Features

`features/lead_lag_features.py` — not used in production. Exists for research experiments.

## Pair-Specific Features

`features/pair_specific.py` — not used in production. Historical per-pair feature builders.

## Architecture Note

All 22 promoted assets use the same alpha feature pipeline from `features/alpha_features.py:build_alpha_features()`. During training, Groups 1-4 are appended (cross-sectional, positioning, rates, events). During live inference, only base alpha features (9 core + 6 trend-exhaustion + 4 cross-asset + 15 FXStreet narrative) are used, plus regime features (7 cols) and archetype features (4 cols). Several assets additionally use custom feature variants (`gc_lead_1`, `dji_lead_1`, `nzdjpy_lead_3`, `yield_slope`, or `mom126` overrides) defined in `features/registry.py`. Each asset has an independent XGBoost model — no shared feature manifold across all assets.

### COT Features — Deprecated

COT features (`{ASSET}_cot_z`, `{ASSET}_cot_change_4w`, `{ASSET}_has_cot`) were deprecated 2026-07-09 after walk-forward validation showed zero gain across all 22 assets. `fetch_cot_features()` returns an empty DataFrame. These placeholder columns are kept for backward compatibility but always zero-filled.

### Directional Splits — Zero Impact

Directional momentum and carry split features (`mom_{h}d_up`, `mom_{h}d_dn`, `carry_up`, `carry_dn`) were added 2026-07-11 but walk-forward validation confirmed **zero splits across all 22 assets** — they carry no incremental information beyond the base features. XGBoost handles directional asymmetry natively via tree splits. Kept in the codebase for backward compatibility.

### Per-Asset Model Depth

Each asset has an independent `max_depth` for its XGBoost model, configured in `configs/domains/assets/<TICKER>.yaml`. See the depth reference table in [`docs/CONFIGURATION.md`](CONFIGURATION.md) for the full per-asset depth map.

### BTCUSD Note

BTCUSD uses the standard `build_alpha_features()` pipeline. COT features (`cot_z`, `cot_change_4w`) are zero-filled (deprecated). Session features (dow_signal) use UTC timestamps for 24/7 session consistency. All trend-exhaustion features (MACD, stoch, BB, ADX, RSI divergence) apply unchanged.

---

**Last updated:** 2026-07-16
