# QuantForge — Feature Engineering

## Feature Contract System

All features are enforced via a **FeatureContract** to ensure deterministic train/serve parity:

- `features/contract.py` — `FeatureContract` dataclass + `validate_no_cross_asset_leakage()` (prevents foreign asset columns in train/serve frames)
- `features/registry.py` — `FEATURE_REGISTRY` with per-asset `contract_prefix`; `FEATURE_CONTRACT_VALIDATION` gate
- `features/builder.py` — Orchestrates feature computation, optional lead-lag columns, and triple-barrier labels
- `features/lead_lag_features.py` — Curated cross-asset lead-lag edges from `data/research/lead_lag_edges.yaml`

## Feature Categories

| Module | Features |
|--------|----------|
| `base_features` | OHLCV returns, ranges, gaps |
| `trend_features` | ADX, slope, curvature, path efficiency |
| `volatility_features` | ATR, Parkinson, Yang-Zhang, rolling vol |
| `mean_reversion_features` | RSI, Bollinger z-score, mean reversion strength |
| `regime_features` | Volatility regime classification, trend/range/volatile probabilities |
| `structural_features` | Skew, kurtosis, tail ratio, serial correlation |
| `cross_asset_features` | Inter-asset correlations, relative strength |
| `interaction_features` | Regime contrast, EMA contrast, transition risk |
| `pair_specific` | FX carry, rate differentials |
| `cot_features` | COT positioning indices, net changes, extreme flags |
| `lead_lag_features` | Optional lagged peer returns (e.g. `nzdjpy_lead_3` on AUDJPY) |
| `macro_narrative` | MacroNarrativeFeatures dataclass, governance scalars from weekly LLM extraction (SL widen / size reduce) |
| `liquidity_regime` | Volume z-score + Amihud illiquidity ratio + Corwin-Schultz spread from daily OHLCV; NORMAL/THIN/STRESSED classification |

## Cross-Asset Isolation

Every asset feature frame is validated so columns match:

- Asset prefix: `{contract_prefix}_` (e.g. `nzdjpy=x_mom_21`)
- Shared macro columns from `KNOWN_MACRO_COLUMNS` or `macro_*` / `spy_*` / `regime_*` prefixes
- Explicit `custom_features` (lead-lag columns must be declared on the contract)

Foreign asset momentum (e.g. `eurusd=x_mom_21` in an NZDJPY frame) raises `FeatureMismatchError`. See `docs/HARDENING_ROADMAP.md` § Tier 1.

## Driver Atlas

Each asset is mapped to a **driver-specific feature subspace** to prevent cross-regime contamination:

| Asset Group | Primary Drivers |
|-------------|----------------|
| JPY crosses (NZDJPY, AUDJPY, GBPJPY, CHFJPY) | VIX, yield spreads, JPY momentum |
| USD pairs (USDCAD, USDCHF, GBPUSD, USDJPY) | DXY, rate differential, VIX |
| EUR crosses (EURAUD, EURCAD) | Rate differential, DXY, VIX |
| CADJPY | Oil correlation, VIX, yield spreads |
| Equity indices (^DJI) | Rate differential, VIX, DXY, gold correlation, index momentum |
| GC (Gold) | Real yields, breakevens, DXY |
| BTC (satellite) | Momentum, spread vs SPY, VIX |
