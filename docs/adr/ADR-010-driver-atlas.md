# ADR-010: Driver Atlas Framework — Asset-Specific Feature Sets

**Status:** Accepted

## Context

Early experiments applied a generic feature template to all assets: DXY momentum + asset momentum + macro features (rate_diff, yield curves). This approach produced acceptable results for XLF but failed on NZDJPY — 0 out of 7 walk-forward test windows were positive. The generic template did not fail due to poor feature engineering but due to incorrect driver selection: NZDJPY is driven by risk sentiment (VIX), bilateral yield spreads (US-JP 10-year), and carry trade dynamics, not by DXY or general momentum. The same analysis on other asset classes showed that each asset type responds to different macro drivers.

## Decision

Adopt the Driver Atlas framework: each asset is mapped to a driver cluster that determines which features are engineered. The confirmed clusters are:

- **yield_equity** (XLF): rate_diff, yield curve delta, sector momentum, relative strength vs SPY
- **momentum_crypto** (BTC): rate_diff, BTC momentum, BTC vs SPY relative strength, volatility scaling
- **carry_fx** (NZDJPY): VIX (level and delta), bilateral yield spread, carry-adj momentum
- **usd_macro** (EURUSD, blocked): DXY, COT positioning (blocked), bilateral rate differential
- **real_asset** (GC=F, blocked): real yields, inflation breakevens, USD, momentum

Asset-specific features are defined in YAML configs (`configs/paper_trading.yaml`, `configs/forex.yaml`, etc.) and the feature engineering pipeline selects the appropriate module based on the asset's driver cluster.

## Alternatives Considered

- **Generic feature set for all assets:** 0/7 positive NZDJPY windows. The failure is catastrophic, not marginal.
- **Single comprehensive feature set (all features for all assets):)** Would work but produces overfitting risk, higher computational cost, and degraded interpretability. The 32-feature model (ADR-005) already showed that irrelevant features introduce noise.
- **Auto feature selection (PCA, LASSO):)** Tested but the resulting features are not asset-class-portable and lose the causal interpretability needed for the driver atlas.

## Consequences

**Positive:** NZDJPY improved from 0/7 to 5/7 positive windows after switching to VIX + bilateral yield spread + momentum features. The driver atlas provides a clear research roadmap for adding new assets: identify the driver cluster, build the feature module, validate. The framework also enables rapid testing — a new asset's driver cluster can be hypothesized from its fundamentals without running full walk-forward.

**Negative:** The driver atlas requires asset-specific feature engineering, which increases the cost of adding new assets. Each new asset class needs a feature module. The five identified clusters are based on the current asset universe and may not generalize — a new asset may require a new cluster. The config files must be kept in sync with the feature modules.

## Evidence

NZDJPY generic features (DXY + momentum): 0/7 positive windows.
NZDJPY specific features (VIX + bilateral yield spread + carry-adj momentum): 5/7 positive windows.
Cross-asset scan confirmed the five driver clusters by analyzing feature importance across 28 FX pairs and 10 equity sectors.
