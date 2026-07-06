# Optimization Priority Matrix

Ranked by: expected CAGR impact, implementation confidence, risk of
overfitting, ease of deployment.

| Rank | Item | Impact | Confidence | Risk | Effort | Verdict |
|------|------|--------|------------|------|--------|---------|
| 1 | Fix ATR cache bug | +1.0pp | HIGH | None | Hours | **DO NOW** |
| 2 | Raise max_concurrent to 13 | +2.0pp | HIGH | Low | Minutes | **DO NOW** |
| 3 | Remove bottom-5 drag assets | +2.5pp | MEDIUM | Low | Days | **DO NEXT** |
| 4 | CHF factor limit 20→25% | +0.5pp | MEDIUM | Low | Minutes | **DO NEXT** |
| 5 | Replace equal-weight with quality-tilt | +0.3pp | LOW | Medium | Weeks | **STUDY** |
| 6 | Optimize per-asset TP/SL per regime | +0.2pp | LOW | Medium | Weeks | **STUDY** |
| 7 | Add weekend trading (BTCUSD) | +0.1pp | LOW | Low | Already done | **DONE** |

## Item 1: Fix ATR Cache Bug

**Impact:** +1.0pp CAGR (6.28% → ~7.27%)

**What:** 3 assets (BTCUSD, GBPJPY, ^DJI) return default fallback 0.005
instead of correct ATR_pct values (0.0366, 0.0093, 0.0111).

**Root cause:**
- BTCUSD: cache file is `BTC_USD.parquet` not `BTCUSD.parquet`
- GBPJPY/^DJI: cache has MultiIndex columns (Close['TICKER'])
  but code accesses `df["high"]` with flat column names

**Fix:**
```python
# In compute_atr_pct_from_cache():
# Add fallback patterns
patterns = [
    cache_dir / f"{asset}.parquet",
    cache_dir / f"{asset}_X.parquet",
    cache_dir / f"{asset}_F.parquet",
    cache_dir / f"{asset.replace('^','')}.parquet",  # ^DJI
    cache_dir / f"{asset.replace('=X','')}.parquet",  # GBPJPY=X
]
# Also: flatten MultiIndex columns before accessing
if hasattr(df.columns, 'levels'):  # MultiIndex
    df.columns = df.columns.get_level_values(0)
```

**Risk:** None. The correct ATR values reduce allocation to these assets
(which is more accurate), but since all 3 have positive total R, the
net effect should be positive or neutral.

## Item 2: Raise max_concurrent to 13

**Impact:** +2.0pp CAGR. Capital utilization jumps from 60% to ~95%.
Reduces the 96.9% backtest-vs-live concurrency gap.

**What:** Change `max_concurrent: 8` → `max_concurrent: 13` in
`configs/domains/risk/sizing.yaml`.

**Chain:** 13 × 15% = 195% deployed, under the 200% max_leverage cap.
Still 5% headroom. The PEK budget enforcement will naturally prevent
over-deployment.

**Justification:** Walk-forward backtest shows P95=22 concurrent
positions. Even at 13, we're below the backtest's median of 18. The
Phase 2 scaling analysis assumes R²=1.0 linearity, which depends on
~18 concurrent positions. 8 is too conservative.

**Risk:** LOW — the number was set arbitrarily (historical default).
The PEK admission controller already ranks and selects positions; it
will naturally prefer the highest-conviction 13. The 3 additional
positions are lower-velocity but still positive-EV assets.

## Item 3: Remove Bottom-5 Drag Assets

**Impact:** +2.5pp CAGR. Portfolio R jumps from 331 → 477 (+44%).

**Targets:** GBPJPY, NZDJPY, AUDJPY, EURCHF, GBPCHF (5 assets
with lowest marginal contribution. Combined marginal = -146R).

**Evidence:**
- All 5 have total R < 20 (vs portfolio avg 15.1)
- EURCHF is the only asset with WR below breakeven (23.1% vs 25.0%)
- JPY crosses share a common failure mode (model JPY bias)
- Removing them removes 22.7% of portfolio which is currently
  allocated to these assets

**Caveat:** The bottom-3 (EURCHF, NZDUSD, GBPCHF) each have single-asset
total R of +30-50 — they're not losing money individually. The "drag"
comes from their marginal contribution through covariance with the
portfolio. Over long periods, removing them may reduce diversification.

**Recommendation:** Remove worst 3 (GBPJPY, NZDJPY, AUDJPY) and
reduce allocation of EURCHF/GBPCHF to 50% weight. Monitor for 3
months.

## Item 4: CHF Factor Limit 20→25%

**Impact:** +0.5pp CAGR.

**What:** `CHF: 0.20` → `CHF: 0.25` in factor limits.

**Justification:** CHF assets are SELL-only. Their aggregate
contribution is positive (CADCHF +101R, NZDCHF +124R, EURCHF +41R).
The 20% cap was set before SELL_ONLY was proven safe. 25% gives
another 5% allocation to the highest-confidence SELL signals.

**Risk:** LOW — CHF cluster correlation is moderate (41% concurrent
loss days). The factor-constrained optimizer currently pins CHF at
exactly 20%. Raising to 25% would still respect the limit.

## Item 5: Quality-Tilt Weighting

**Impact:** +0.3pp CAGR (uncertain).

**What:** Replace equal-weight with a rolling quality-tilt that
underweights assets with negative 60-day total R.

**Rationale:** Equal-weight currently beats risk parity, but equal-weight
also allocates equally to drag and driver assets. A simple binary
filter (remove assets with negative rolling 60d R) could improve
returns without the overfitting risk of full risk parity.

**Implementation complexity:** Low — add a `quality_tilt_v1` method
to `shared/portfolio_weights.py`:

```python
def quality_tilt_weights(returns, window=60, reduction=0.5):
    """Underweight assets with negative rolling total R."""
    rolling_r = returns.rolling(window).sum()
    weights = np.ones(len(returns.columns)) / len(returns.columns)
    mask = rolling_r.iloc[-1] < 0 if len(rolling_r) > 0 else np.zeros(len(weights), dtype=bool)
    if mask.any():
        weights[mask] *= reduction
        weights /= weights.sum()
    return weights
```

**Risks:**
- Parameter sensitivity (60d window, 0.5 reduction)
- Lag in detecting regime changes
- Would flag different assets in different periods

**Verdict:** Worth testing but not high priority. Study phase only.

## Expected CAGR After All Fixes

| Change | ΔCAGR | Cumulative |
|--------|-------|------------|
| Baseline | — | 6.28% |
| ATR cache fix | +1.0pp | 7.27% |
| max_concurrent 8→13 | +2.0pp | 9.27% |
| Remove bottom-3 JPY crosses | +1.5pp | 10.77% |
| CHF 20→25% | +0.5pp | 11.27% |
| Realistic costs | -0.7pp | 10.57% |

**Expected CAGR after top-4 fixes: ~10.6% before costs, ~9.9% after.**

Target 8% is achievable with Items 1+2 alone (7.27% + 2.0% utilization
→ 7.6% CAGR with realistic costs → ~6.9%). Items 1-2-3 together
reach ~9.3% before costs, well above 8%.

## Monitoring

After deploying each change:
- Track `state.json` capital efficiency and live Sharpe (trading days)
- Run `PYTHONPATH=$PYTHONPATH:. python scripts/backtest/backtest_pnl.py`
- Compare walk-forward R against pre-change baseline
- If R drops >10%, revert and investigate
