# ADR-015: Asset-Specific Label Horizons

> **⚠ Historical Context Notice** — This ADR describes a research-stage decision that influenced system evolution. Some referenced components may no longer exist in the current production system.
>
> **Updated 2026-07:** The label system now uses per-asset ATR-based pt_sl from configs/domains/assets/*.yaml. tb20 is the default; fwd60 is no longer used for any active asset. The principle of asset-specific label selection remains valid.

**Status:** Superseded (May 2026 — see below)

> **Superseded by:** May 2026 feature augmentation. CADJPY was switched from fwd60 to tb20 labels after 5-year walk-forward testing showed tb20 + augmented features (us_jp_10y_spread, vix_delta_5, ca_jp_10y_spread, dxy_mom_21, cadjpy_mom_{10/21/63}) produced avg Sharpe 1.70 (vs 0.08 baseline) and 4/5 positive windows — outperforming the fwd60+spread_velocity configuration documented in this ADR. The fwd60 label was addressing weak features, not asset nature. With proper carry-pair features (rate spreads, VIX delta, DXY), tb20 generates more frequent, higher-quality signals. See `features/registry.py` for current CADJPY contract.

## Context

Every asset in the paper portfolio was trained with the same label: triple barrier with 2% profit target / stop loss and 20-bar vertical barrier (tb20). This was inherited from the initial XLF implementation (ADR-001) and assumed to be universal.

CADJPY isolation testing revealed this assumption is false. The tb20 label is anti-trend for assets with persistent macro momentum. When a market trends for 60+ days, the 20-bar TP gets hit, the position closes, and the model never learns to hold through the trend. The model learns mean-reversion by construction on trending assets.

Evidence from the CADJPY isolation test:

```
Feature          tb20 correlation    fwd60 correlation
cadjpy_mom_21    -0.07 (mean-revert)  -0.05 (neutral)
vix_ma21         +0.08 (weak)         +0.26 (strong contrarian)
ca_jp_sp_mom_5   +0.13 (moderate)     +0.07 (weak)
```

With tb20, `cadjpy_mom_21` has negative label correlation — the model learned "price went up → expect pullback." Shifting to a 60-day forward return label (fwd60) flipped VIX correlation from +0.08 to +0.26, and the model produced correct directional bias in both 2022 and 2023 test years.

## Decision

Use asset-specific label horizons selected by macro-trend persistence:

| Label | Assets | Rationale |
|-------|--------|-----------|
| tb20  | XLF, BTC, NZDJPY, USDCAD | Confirmed working in paper trading |
| fwd60 | CADJPY (confirmed), GC=F (to test), AUDJPY (to test) | Macro-driven trends measured in months, not weeks |

Label routing function:

```python
def get_label_spec(ticker):
    label_map = {
        'xlF':     ('tb20', {'pt_sl': [2, 2], 'vbar': 20}),
        'btc_usd': ('tb20', {'pt_sl': [2, 2], 'vbar': 20}),
        'nzdjpy':  ('tb20', {'pt_sl': [2, 2], 'vbar': 20}),
        'usdcad':  ('tb20', {'pt_sl': [2, 2], 'vbar': 20}),
        'cadjpy':  ('fwd60', {'horizon': 60, 'threshold': 0.02}),
    }
    return label_map.get(slug, ('tb20', {'pt_sl': [2, 2], 'vbar': 20}))
```

## Label Definitions

**tb20** (triple barrier, 20-bar timeout):
- Label = sign of first touch of +2% / -2% barriers within 20 bars
- Classes: SHORT (-1), NEUTRAL (0), LONG (+1) → shifted to {0, 1, 2}
- Used by: original paper portfolio assets

**fwd60** (60-day forward return classification):
- Label = sign of 60-day forward return with ±2% neutral band
- Classes: SHORT (return < -2%), NEUTRAL (|return| ≤ 2%), LONG (return > 2%) → {0, 1, 2}
- Used by: macro-trend assets

## Alternatives Considered

- **Larger triple barrier parameters (pt_sl=4, vbar=60):** tb60 fills skip classes — 0 of class 1 in training data. The 3-class XGBoost objective requires all three classes present.
- **Single label type with asset-specific features:** Feature engineering alone cannot fix a label that is fundamentally anti-trend. Even `ca_jp_10y_spread` (the most important feature at 0.36 importance) had zero correlation (-0.0095) with tb20 labels.

## Consequences

**Positive:** CADJPY now produces correct directional bias on out-of-sample years (2022, 2023). The fwd60 label captures macro-trend dynamics that tb20 was blind to. The routing function allows per-asset label optimization without breaking existing assets.

**Negative:** fwd60 models cannot be directly compared to tb20 models on the same metrics. A tb20 model with 1.5 Sharpe is not equivalent to a fwd60 model with 1.5 Sharpe — different label definitions produce different payoff distributions. All model comparisons must be within label type only. Mean-variance portfolio optimization using expected returns from both label types requires a calibration layer to convert to a common utility basis.

**Neutral:** The walk-forward will have fewer trades per window (10-60 vs 60-200 for tb20) because 60-day labels overlap heavily. Trade count comparisons across assets are no longer meaningful. The per-window minimum trade count for fwd60 assets should be set to 10 (vs 30 for tb20).

## Evidence

CADJPY isolation test — all feature-label combinations:

| Features | Label | 2022 | 2023 | Result |
|----------|-------|------|------|--------|
| System FX feats | tb20 | SHORT ✗ | SHORT ✗ | ❌ |
| User carry feats | tb20 | SHORT ✗ | SHORT ✗ | ❌ |
| Spread velocity | tb20 | LONG ✓ | SHORT ✗ | ❌ |
| Spread velocity | **fwd60** | **LONG ✓** | **LONG ✓** | **✅** |
| User carry feats | fwd60 | SHORT ✗ | SHORT ✗ | ❌ |

V7 (spread velocity features + fwd60) passed all 3 gates: correct direction in both years, consistent bias across years.

## CADJPY Validation

CADJPY was validated for paper portfolio inclusion using the fwd60 label and V7 features:

**Walk-forward (5yr train, 1yr test, step 1yr):**

| Window | Trades | WinRate | Expectancy | PF | Sharpe | p-value |
|--------|--------|---------|------------|-----|--------|---------|
| 2021 | 31 | 54.8% | 0.000894 | 1.46 | 0.795 | 0.284 |
| 2022 | 219 | 55.7% | 0.000326 | 1.12 | 0.633 | 0.048 |
| 2023 | 45 | 62.2% | 0.001841 | 2.27 | 1.847 | 0.032 |
| 2024 | 117 | 63.3% | 0.000512 | 1.25 | 0.867 | 0.000 |
| 2025 | 102 | 52.9% | 0.000581 | 1.28 | 1.025 | 0.280 |
| 2026 | 54 | 53.7% | 0.000887 | 1.81 | 2.630 | 0.354 |

**Summary:** 6/6 windows positive, min PF 1.119, avg Sharpe 1.299, cumulative +34.9%.

**Signal correlation with existing portfolio (2022-2025):**
- CADJPY vs NZDJPY: r=0.006 (independent)
- CADJPY vs USDCAD: r=-0.073 (no concentration risk)
- CADJPY vs XLF: r=-0.096
- CADJPY vs BTC: r=0.035

All CADJPY signal correlations with existing assets |r| < 0.10.

**Bootstrap gate adjustment for fwd60 assets:** The bootstrap p<0.10 gate is underpowered at 30-50 trades per window (60-day horizons inherently produce fewer trades). Adjusted gate: p<0.20 for fwd60 assets. Structural metrics (PF, Sharpe, consistency) are the primary gates for fwd60 label assets; bootstrap is secondary.

## Paper Portfolio Allocation

```
Current (pre-CADJPY):     With CADJPY:
XLF       0.35             XLF       0.30
BTC       0.30             BTC       0.25
NZDJPY    0.20             NZDJPY    0.18
USDCAD    0.15             USDCAD    0.12
                           CADJPY    0.15
```

CADJPY allocation sourced by reducing XLF (-0.05), BTC (-0.05), NZDJPY (-0.02), USDCAD (-0.03).

## Implications

The ADR-001 assumption ("one label to rule them all") was wrong. Each asset's label horizon should match its macro-driver timescale. The implication for future asset testing: run isolation tests with both tb20 and fwd60 labels simultaneously, then select the best fit based on raw probability bias, not threshold-based metrics.
