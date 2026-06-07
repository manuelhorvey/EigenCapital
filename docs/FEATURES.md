# QuantForge — Feature Engineering

## Alpha Features

The primary feature builder is `features/builder.py:build_features()`. It produces per-asset feature sets defined by `features/registry.py:FEATURE_REGISTRY`, using a combination of macro filters, price momentum, and custom features.

### Input Data

Data ingested from MT5 bridge (primary) or yfinance (fallback):

| Source | Symbol | Data |
|---|---|---|
| Asset ticker | e.g. `GC=F` | Daily OHLCV close |
| Dollar index | `DX-Y.NYB` | DXY close |
| VIX | `^VIX` | VIX close |
| SPX | `^GSPC` | S&P 500 close |
| Crude oil | `CL=F` | WTI close |
| 10Y Treasury | `^TNX` | TNX yield |

### Feature Categories

#### Macro Filters
| Feature | Source | Description |
|---|---|---|
| `rate_diff` | yfinance | Interest rate differential proxy |
| `dxy_mom_21` / `dxy_mom_63` | DX-Y.NYB | Dollar momentum |
| `vix_ma21` | ^VIX | VIX 21-day moving average |
| `vix_delta_5` | ^VIX | VIX 5-day change |
| `breakeven_delta_63` | ^TNX | 10Y breakeven inflation change |
| `real_yield_delta_63` | ^TNX | Real yield change |
| `us_jp_10y_spread` | ^TNX | US-JP 10-year yield spread |

#### Price Momentum
| Feature | Window | Description |
|---|---|---|
| `{asset}_mom_21` | 21d | 1-month momentum |
| `{asset}_mom_63` | 63d | 3-month momentum |

#### Custom Features
| Feature | Description |
|---|---|
| `gc_lead_1` | Gold 1-day lead |
| `dji_lead_1` | Dow 1-day lead |

### Per-Asset Feature Sets

Each dashboard asset has a tailored feature set from `features/registry.py`:

| Asset | Features |
|---|---|
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

`features/labels.py:triple_barrier_labels()`:

1. Compute ATR-based barrier distances from `pt_sl = (tp_mult, sl_mult)` per asset
2. Apply triple-barrier touch: first touch of TP (+1), SL (-1), or vertical barrier → {-1, 0, 1}
3. Training pipeline drops HOLD (0) labels and maps {-1, 1} → {0, 1} for binary XGBoost

Per-asset `pt_sl` from `configs/paper_trading.yaml`.

## Feature Contract Validation

`features/contract.py` provides `FeatureContract` dataclass and `validate_no_cross_asset_leakage()`.

## Lead-Lag Features

`features/lead_lag_features.py` — not used in production. Exists for research experiments.

## Pair-Specific Features

`features/pair_specific.py` — not used in production. Historical per-pair feature builders.

## COT Features

`features/cot_features.py` — not used in production. Commitments of Traders features pending data integration.

## Architecture Note

Feature sets are defined per-asset in `FEATURE_REGISTRY` and built by `features/builder.py`. Each asset has an independent set of features — no shared feature manifold across all assets.
