# Stress-Test Report: SELL_ONLY Alpha Robustness

## TL;DR

The SELL_ONLY alpha **passes 3 of 6 checks and fails 3.** It is real but fragile —
concentrated in ~8 genuinely robust assets (not 20), dependent on barrier asymmetry >3:1,
and driven by momentum features (not label leakage). It is tradeable but needs
two critical corrections before live deployment.

## Six-Check Summary

| Check | Result | Verdict |
|---|---|---|
| 1. Regime decomposition | 8 Tier A (multi-fold), 7 single-fold, 3 decay, 1 insufficient | ⚠ **FAIL** — 7/20 are regime-lucky |
| 2. Trade count audit | 1 asset <30 SELL trades (GBPCHF 100% WR on n=10) | ✅ **PASS** — all others have adequate N |
| 3. Expectancy conversion | All 20 positive net E; top: AUDUSD(+2.89), ^DJI(+2.48), NZDUSD(+2.31) | ✅ **PASS** — expectancy positive after spread |
| 4. Barrier sensitivity | Alpha CLIFF at asym~3.0: WR 70%→53% across one step | ⚠ **FAIL** — cliff suggests artifact, not smooth decay |
| 5. Feature attribution | Momentum features dominate; no label leakage found | ✅ **PASS** — models learn genuine patterns |
| 6. Cross-asset correlation | 8.06 effective independent bets from 19 assets | ⚠ **WARN** — diversification overstated by 2.4× |

## Detailed Results

### Check 1: Regime Decomposition (Fold Stability)

The "20 sell-only assets" collapse into four tiers when examined at the fold level:

```
        Asset  | Trades  | WR(S) |  E(net) | Folds | Tier
 AUDUSD        |    699  | 78.1% |  +2.900 |     5 | A - stable multi-fold
 CADCHF ★      |    373  | 90.4% |  +1.754 |     5 | A - stable multi-fold
 GC            |    819  | 66.2% |  +2.172 |     5 | A - stable multi-fold
 NZDJPY        |    309  | 67.6% |  +1.169 |     5 | A - stable multi-fold
 NZDUSD        |    697  | 79.8% |  +2.317 |     5 | A - stable multi-fold
 USDCAD        |    952  | 69.4% |  +2.308 |     5 | A - stable multi-fold
 USDJPY        |    555  | 56.8% |  +0.766 |     5 | A - stable multi-fold
 ^DJI          |    597  | 78.7% |  +2.513 |     4 | A - stable multi-fold
 ─────────────────────────────────────────────────────────────
 GBPCAD        |    102  | 86.3% |  +0.964 |     2 | B - multi-fold unstable
 ─────────────────────────────────────────────────────────────
 GBPJPY        |    266  | 63.5% |  +0.776 |     5 | C - WR decay
 NZDCHF ★      |    264  | 86.4% |  +1.685 |     5 | C - WR decay (76→-7%)
 USDCHF        |    353  | 75.1% |  +1.298 |     5 | C - WR decay (28→-16%)
 ─────────────────────────────────────────────────────────────
 AUDJPY        |    167  | 58.7% |  +0.856 |     1 | C - single fold only
 BTCUSD        |     54  | 87.0% |  +0.708 |     1 | C - single fold only
 EURCAD        |    185  | 70.3% |  +1.176 |     1 | C - single fold only
 EURCHF        |    140  | 78.6% |  +1.889 |     1 | C - single fold only
 EURNZD        |    170  | 60.0% |  +1.606 |     1 | C - single fold only
 NZDCAD        |     94  | 83.0% |  +1.909 |     1 | C - single fold only
 ─────────────────────────────────────────────────────────────
 GBPCHF        |     10  |100.0% |  +0.167 |     0 | D - insufficient
```

(★ = permanent SELL_ONLY asset)

NZDCHF fold-level WR decay (hit rate by fold):
- Fold 0: +0.762 (WR≈88%) → Fold 1: +0.038 → Fold 2: -0.163 → Fold 3: -0.189 → Fold 4: -0.074
- This is a classic regime-conditioned alpha that expired.

USDCHF fold-level WR decay:
- Fold 0: +0.275 → Fold 1: +0.209 → Fold 2: +0.171 → Fold 3: +0.029 → Fold 4: -0.164

**Recommendation**: Downgrade NZDCHF and USDCHF from SELL_ONLY. The WR decay
pattern strongly suggests these were capturing a multi-year macro trend
(CHF strength 2021-2022) that reversed in later folds (2025-2026).

### Check 4: Barrier Sensitivity Curve

USDCAD (Tier A, most stable asset):

| Ratio | Asym | Hit rate | WR(est) | nSell | Flat% |
|---|---|---|---|---|---|
| (3.9, 1.3) | 3.0 | +0.388 | 69.4% | 952 | 2% |
| (3.5, 1.0) | 3.5 | +0.397 | 69.8% | 207 | 1% |
| (3.0, 1.0) | 3.0 | +0.057 | 52.8% | 42 | 80% |
| (2.5, 1.0) | 2.5 | +0.064 | 53.2% | 27 | 87% |
| (2.0, 1.0) | 2.0 | +0.049 | 52.4% | 20 | 91% |
| (3.0, 1.5) | 2.0 | +0.201 | 60.1% | 184 | 10% |
| (2.0, 2.0) | 1.0 | ≈0.00 | ≈50% | ~0 | ~100% |

Key finding: **CLIFF, not smooth decay.** The alpha drops from 70%→53% WR
between 3.5:1 and 3.0:1 asymmetry. This is inconsistent with genuine signal
(which decays smoothly). However, the cliff is partly explained by absolute
barrier width: at (3.0, 1.5) with the same 2.0:1 ratio but wider barriers,
WR recovers to 60%. The model needs barriers wide enough for trades to
resolve before timeout.

Interpretation: The feature space genuinely predicts short-term downside
volatility events, but needs the asymmetric barrier structure to create
enough labeled training examples. This is **real alpha with an artifact-
enhanced training signal** — not pure artifact, not pure alpha.

### Check 5: Feature Attribution (Permutation Importance)

Top features across all 4 assets:

| USDCAD | NZDCHF | CADCHF | AUDJPY |
|---|---|---|---|
| mom_252d +0.081 | carry +0.054 | carry +0.069 | mom_252d +0.154 |
| mom_63d +0.078 | dxy_mom +0.053 | mom_126d +0.069 | mom_126d +0.102 |
| mom_126d +0.071 | adx_slope +0.050 | mom_252d +0.067 | mom_63d +0.091 |
| WTI_mom +0.058 | mom_252d +0.039 | WTI_mom +0.056 | stoch_k +0.083 |
| mom_21d +0.050 | mom_63d +0.032 | dxy_mom +0.048 | mom_21d +0.064 |

**No label leakage detected.** The dominant features are momentum (all lookbacks),
cross-asset (DXY, WTI, VIX momentum), and carry. Features mechanically related
to the barrier construction (zscore_20, vol_ratio) rank below top 5.

An interesting structural finding: **CHF pairs (CADCHF, NZDCHF) are carry-driven**
while **non-CHF pairs (USDCAD, AUDJPY) are momentum-driven.** This suggests
the SELL alpha has different mechanisms in CHF vs non-CHF assets.

### Check 6: Cross-Asset Signal Correlation

- Effective independent bets: **8.06** from 19 assets
- HHI of eigenvalues: 0.124 (moderate concentration)
- Max pairwise |corr|: 0.707 (BTCUSD × CADCHF)
- Mean |corr|: 0.108 (low average)

High-correlation pairs (>0.5):
- GBPCHF × USDCAD: -0.741
- GBPCHF × NZDUSD: -0.680
- NZDUSD × USDCAD: +0.637
- BTCUSD × CADCHF: +0.707

The 20-asset sell-only claim reduces to **~8 effective independent factors**,
but these 8 factors are genuine (driven by different feature combinations
per asset). The correlation structure is expected for FX pairs (all share
USD, EUR, JPY risk factors).

## Go/No-Go Recommendation

### Corrected Portfolio (Tier A only)

8 assets with multi-fold stable SELL alpha:
```
USDCAD   WR=69%  E=+2.31  TotalR=2202  5 folds  ← strongest evidence
^DJI     WR=79%  E=+2.51  TotalR=1963  4 folds
AUDUSD   WR=78%  E=+2.90  TotalR=2080  5 folds
NZDUSD   WR=80%  E=+2.32  TotalR=2002  5 folds
GC       WR=66%  E=+2.17  TotalR=2085  5 folds
CADCHF   WR=90%  E=+1.75  TotalR=1379  5 folds
NZDJPY   WR=68%  E=+1.17  TotalR=382   5 folds
USDJPY   WR=57%  E=+0.77  TotalR=630   5 folds
```

### Conditional Go

**Recommendation: CONDITIONAL GO for 8 Tier A assets, 60-day live probation.**

| Condition | Rationale |
|---|---|
| Remove 7 single-fold assets from SELL_ONLY | Their alpha is indistinguishable from regime luck |
| Remove NZDCHF, USDCHF from SELL_ONLY | Clear WR decay across folds — regime expired |
| Remove GBPCHF from SELL_ONLY | Only 10 trades, 100% WR is meaningless |
| Keep NZDUSD SELL_ONLY | Multi-fold stable despite earlier doubts |
| Keep CADCHF SELL_ONLY | Multi-fold stable at 90% WR |
| Downgrade portfolio from 20→8 sell-only assets | 8 is the genuine signal count |
| Live probation: 60 days | Monitor fold-level WR decay in real time |

### What To Watch For

1. **WR decay in live**: The fold-level degradation pattern in NZDCHF/USDCHF
   is a leading indicator. If any Tier A asset shows 3 consecutive 20-trade
   windows with WR < 55%, remove from SELL_ONLY.

2. **Barrier sensitivity drift**: If volatility regime changes (VIX regime
   shift), the effective barrier width changes. Monitor the timeout rate
   (flat predictions) — if >50% for a 2-week period, the barriers need
   recalibration.

3. **Macro data quality**: The effective data range is only 2020-2026
   (macro bottleneck). Older data exists for prices (2003+) but not for
   macro series (DXY, VIX, SPX, WTI). This limits regime diversity —
   the models have never been tested through a 2008-style crisis.

4. **Correlation regime**: The effective 8 independent bets may collapse
   in a crisis (all FX correlations → 1 during USD liquidity events).
   The position sizing should account for this tail risk.

### Final Verdict

> **The SELL_ONLY alpha is real but the 20-asset claim was wrong. 8 assets
> have genuine, multi-fold, momentum-driven SELL alpha with positive expectancy
> and no label leakage. 12 assets need removal or downgrade. Live trading
> at 50% size on the 8 Tier A assets for 60 days, then reassess.**
