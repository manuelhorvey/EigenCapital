# QuantForge — Feature Engineering

## Alpha Features

The primary feature builder is `features/alpha_features.py:build_alpha_features()`. Every asset uses the same 13 alpha features (9 per-asset + 4 cross-asset) with per-asset prefix. The per-asset contracts in `features/registry.py` are used by the backtest pipeline for custom feature variants.

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

#### Per-Asset Alpha Features (9 cols via `build_alpha_features()`)

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

#### Cross-Asset Features (4 cols)

| Feature | Source | Description |
|---|---|---|
| `dxy_mom_21d` | DX-Y.NYB | Dollar 21-day return |
| `vix_mom_5d` | ^VIX | VIX 5-day return |
| `spx_mom_5d` | ^GSPC | S&P 500 5-day return |
| `WTI_mom_21d` | CL=F | WTI crude 21-day return |

### Custom Feature Variants

Some assets have additional or replacement features beyond the 13-base set:

| Asset | Variant |
|---|---|
| EURCHF | `mom126` replaces base momentum (126d momentum) |
| NZDUSD | `mom126` replaces base momentum |
| GBPAUD | `yield_slope` (US yield curve slope) |
| CADCHF | `yield_slope` |
| EURNZD | `yield_slope` |
| GBPCHF | `yield_slope` |

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

Per-asset `pt_sl` from `configs/paper_trading.yaml`.

## Feature Contract Validation

`features/contract.py` provides `FeatureContract` dataclass and `validate_no_cross_asset_leakage()`.

## Lead-Lag Features

`features/lead_lag_features.py` — not used in production. Exists for research experiments.

## Pair-Specific Features

`features/pair_specific.py` — not used in production. Historical per-pair feature builders.

## Architecture Note

All 18 dashboard assets use the same 13 alpha features from `features/alpha_features.py:build_alpha_features()`. A few assets additionally use `yield_slope` or `mom126` variants defined in `features/registry.py`. Each asset has an independent XGBoost model — no shared feature manifold across all assets.
