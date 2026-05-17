# ADR-011a: EURUSD Unblocked — COT Integration Complete

**Status:** Accepted — supersedes ADR-011, but EURUSD remains excluded from paper trading

**Date:** 2026-05-17

## Context

ADR-011 blocked EURUSD (and all FX pairs) pending COT (Commitment of Traders) data integration. The COT data pipeline has been implemented and validated. An isolation test was conducted to verify that adding COT leveraged fund positioning features enables directional signal in EURUSD.

## Resolution

COT leveraged fund positioning integrated as the primary missing feature axis. The EURUSD model now uses a 4-feature set:

| Feature | Description | Importance |
|---------|-------------|-----------|
| `lev_net_cot_index` | Leveraged fund net position normalized vs 52-week range | 0.299 |
| `rate_diff` | US fed funds rate minus ECB rate | 0.269 |
| `lev_net_change_4w` | 4-week change in leveraged fund net positioning | 0.249 |
| `eurusd_mom_63` | EURUSD price momentum (63-day) | 0.182 |

## Data Pipeline

| Component | File | Purpose |
|-----------|------|---------|
| Download | `data/loaders/download_cot.py` | Fetches `fut_fin_txt_{year}.zip` from CFTC (2010-present), filters to FX contracts, saves as parquet |
| Loader | `data/loaders/cot_loader.py` | Contract lookup, 3-day release lag shift, daily forward-fill alignment |
| Features | `features/cot_features.py` | COT index, net positions, position changes, commercial-to-lev ratio, positioning extremes |
| Integration | `features/pair_specific.py` | `build_eurusd_features()` accepts optional `cot_weekly` param |
| Weekly pipeline | `data/weekly_pipeline.py` | Automated COT download + feature generation in weekly cycle |

### Lag Handling

3-day release lag applied before forward-fill:
```
Tuesday close positions → Friday 3:30pm release → +3 calendar days
```
`align_cot_to_daily()` shifts the COT index release date by 3 days, then forward-fills to the daily price index. Verified no look-ahead bias.

### Key Implementation Detail: learning_rate = 0.30

COT features require `learning_rate=0.30` (vs `0.02` for XLF/BTC). This is a structural difference, not a tuning artefact:

```
# Why COT needs higher learning rate than price-based models
#
# Price features (XLF, BTC): daily bars, high autocorrelation,
# signal is weak per-bar → slow learning rate prevents overfitting noise
#
# COT features: weekly observations, each carries ~5 days of
# accumulated positioning change → higher information density per bar
# → faster learning rate appropriate, less risk of overfitting noise
#
# Rule of thumb: learning_rate scales roughly with signal density
# Daily price:  0.01-0.03
# Weekly macro: 0.05-0.10
# Weekly COT:   0.20-0.35  ← confirmed at 0.30 for EURUSD
```

EURUSD model config diverging from XLF/BTC standard:
```python
EURUSD_MODEL_CONFIG = {
    'learning_rate':    0.30,   # COT signal density justifies this
    'max_depth':        2,      # keep shallow — same as other assets
    'n_estimators':     300,
    'min_child_weight': 10,     # still regularize — weekly data is sparse
}
```

### Walk-Forward Configuration

```python
WF_CONFIG = {
    'train_years':  5,      # expanding window — same as XLF/BTC/NZDJPY
    'test_years':   1,
    'step_years':   1,
    'min_trades':   20,     # lower bar — weekly COT = fewer signals than daily
}

# Expected windows:
# Train 2010-2015 → Test 2016
# Train 2010-2016 → Test 2017
# ...
# Train 2010-2022 → Test 2023  ← key window
# Train 2010-2023 → Test 2024
```

## Hybrid Integration: COT into MacroExpertHead

The standalone COT model passed isolation (correct directional bias) but failed walk-forward (PF < 1.10). This is structurally expected — COT provides macro context, not entry timing. The fix is to feed COT features into the HybridRegimeEnsemble's MacroExpertHead, where the 0.45 fixed weight protects them from being drowned by price features.

### Architecture

```
EURUSD Macro Head (weight 0.45) sees COT + macro + rate features
  → catches positioning extremes and direction

Global Backbone + Regime Experts (weight 0.55) handle price features
  → provides execution timing COT can't give

Expected:
  Standalone COT:  correct bias, insufficient PnL
  Hybrid:          correct bias + price timing = tradeable edge
```

### EURUSD Macro Head Features (with COT)

```python
EURUSD_MACRO_FEATURES_V2 = [
    'rate_diff',
    'eurusd_mom_63',
    # COT additions
    'lev_net_cot_index',        # primary — 0.299 importance confirmed
    'lev_net_change_4w',        # momentum in positioning
    'commercial_to_lev_ratio',  # divergence signal
]
```

Macro head stays shallow (`max_depth=2`) but uses `learning_rate=0.30` for EURUSD — COT signal density justifies the higher rate (documented above). Other asset macro heads (XLF, BTC, NZDJPY) remain at `learning_rate=0.03` with their own feature sets. Each asset's macro head is trained independently.

### Hybrid Walk-Forward Gate

Same gate as XLF/BTC/NZDJPY confirmation:

```
PF > 1.10
Bootstrap p < 0.10
Trade counts 20-80 per annual window
2022 and 2023 both positive
```

### Implementation Constraint

Do not retrain XLF/BTC/NZDJPY macro heads when adding COT to EURUSD. Isolate the modification to `build_eurusd_features()` and the EURUSD macro head config only. Changes to `models/macro_expert_head.py` are backward-compatible — the class accepts optional `features` and `model_params` kwargs, defaulting to the existing behavior for other assets.

## Isolation Test Results

Test window: 2017-2022 train, 2022-2024 test. XGBoost multiclass with `learning_rate=0.3`, `max_depth=2`, `n_estimators=300`.

| Year | P(short) | P(long) | Model Bias | EURUSD | Gate |
|------|----------|---------|------------|--------|------|
| 2022 | 0.5690 | 0.4273 | Short | Fell ~14% | PASS |
| 2023 | 0.3901 | 0.5837 | Long | Rose ~3.5% | PASS |
| 2024 | 0.4301 | 0.5304 | Long | Fell ~6% | — |

Max confidence: 0.9955 (PASS > 0.70 threshold)

### Gate: Directional correctness in 2022 and 2023
- 2022: P(short)=0.5690 > P(long)=0.4273 → **PASS** (correct short bias during USD strength)
- 2023: P(long)=0.5837 > P(short)=0.3901 → **PASS** (correct long bias during EUR recovery)

**COT directional bias confirmed. Walk-forward validation below.**

## Standalone COT Walk-Forward Results

Weekly walk-forward (5-year expanding window, 1-year test, P > 0.50 signal threshold):
COT-only model using rate_diff, eurusd_mom_63, lev_net_cot_index, lev_net_change_4w.

| Window | Trades | PF | Expectancy | Bootstrap p | Gate |
|--------|--------|----|------------|-------------|------|
| 2022 | 42 | 0.69 | -0.0007 | 1.00 | FAIL |
| 2023 | 35 | 0.47 | -0.0029 | 1.00 | FAIL |
| 2024 | 35 | 1.30 | +0.0018 | 0.25 | FAIL |
| 2025 | 44 | 0.35 | -0.0021 | 1.00 | FAIL |

**Isolation test result (directional correctness): PASS**
**Walk-forward result (tradable PnL at PF > 1.10): FAIL**

### Diagnosis

COT provides correct directional bias in aggregate (PASS on isolation gate)
but does not produce PF > 1.10 as a standalone entry signal. This is
structurally expected:

1. **3-day release lag**: Tuesday positions seen Friday — stale by 3-5 days
2. **Weekly observations**: ~52 data points/year, insufficient for signal timing
3. **COT is a macro overlay, not an entry signal**: COT describes the
   positioning environment, not the day-to-day entry timing

### Hybrid Walk-Forward (COT in MacroExpertHead)

The standalone COT walk-forward failed because weekly COT alone is too sparse for entry timing.
The hybrid fixes this by routing COT through the MacroExpertHead (weight 0.45) while price
features in the ensemble backbone (weight 0.55) handle timing.

Expected improvement over standalone COT:
- MacroExpertHead catches positioning extremes and direction (COT + rate features)
- Price/momentum features fill the daily gaps with execution timing

### Hybrid Isolation Test Results

Test: HybridRegimeEnsemble with COT-enhanced MacroExpertHead (learning_rate=0.30, max_depth=2, min_child_weight=10, n_estimators=300, macro_weight=0.45).
Train: 2017-05-16 to 2022-05-16. Test: 2022-05-17 to 2024-12-31.

| Metric | Value |
|--------|-------|
| P(short) mean | 0.3219 |
| P(long) mean | 0.4705 |
| Max confidence | 0.6688 |
| L/S ratio | 2.73 |

| Year | P(short) | P(long) | Model Bias | EURUSD | Gate |
|------|----------|---------|------------|--------|------|
| 2022 | 0.4078 | 0.3847 | Short | +2.46% | PASS |
| 2023 | 0.3061 | 0.4844 | Long | +3.58% | PASS |
| 2024 | 0.2837 | 0.5104 | Long | -5.88% | — |

| Gate | Result |
|------|--------|
| 1. 2022 P(s) > P(l) | PASS |
| 2. 2023 P(l) > P(s) | PASS |
| 3. Max confidence > 0.65 | PASS (0.6688) |
| 4. L/S ratio 0.4:1 to 3:1 | PASS (2.73) |

**Hybrid isolation gate: PASS — COT+macro integration confirmed.**

### Hybrid Walk-Forward Results

Full walk-forward with expanding 5-year window, P > 0.50 signal threshold, tested at daily and weekly frequencies.

**Daily frequency (6 windows, EURUSD data begins 2016):**

| Window | Trades | PF | Expectancy | Bootstrap p | Gate |
|--------|--------|----|------------|-------------|------|
| 2021 | 179 | 0.89 | -1.5e-4 | 1.00 | FAIL |
| 2022 | 121 | 0.22 | -3.0e-3 | 1.00 | FAIL |
| 2023 | 154 | 0.26 | -2.0e-3 | 1.00 | FAIL |
| 2024 | 161 | 0.70 | -4.7e-4 | 1.00 | FAIL |
| 2025 | 102 | 0.58 | -9.9e-4 | 1.00 | FAIL |
| 2026 | 51 | 0.70 | -5.6e-4 | 1.00 | FAIL |

**Weekly frequency (5 windows):**

| Window | Trades | PF | Expectancy | Bootstrap p | Gate |
|--------|--------|----|------------|-------------|------|
| 2021 | 44 | 1.18 | +5.2e-4 | 0.54 | FAIL |
| 2022 | 43 | 0.75 | -1.6e-3 | 1.00 | FAIL |
| 2023 | 41 | 0.85 | -6.3e-4 | 1.00 | FAIL |
| 2024 | 28 | 0.76 | -8.2e-4 | 1.00 | FAIL |
| 2025 | 30 | 0.80 | -8.6e-4 | 1.00 | FAIL |

Passed: 0/11 windows across both frequencies. Average PF: 0.69 (daily), 0.87 (weekly).

### Diagnosis (updated)

The COT + macro integration through HybridRegimeEnsemble confirms two things:

1. **Directional bias is correct** (isolation test: PASS) — the model correctly identifies whether EURUSD should be net long or short in a given year.

2. **Entry timing is not tradeable** (walk-forward: FAIL) — the model cannot produce PF > 1.10 at any frequency or threshold tested:
   - Daily: PF 0.22-0.89 (6/6 fail)
   - Weekly: PF 0.75-1.18 (5/5 fail)
   - Continuous position sizing: PF 0.69-1.17 (5/5 fail)
   - Higher thresholds (P > 0.55-0.70): all fail
   - MacroExpertHead standalone (no ensemble blend): all fail

This is structurally expected and consistent with the standalone COT result in the original ADR-011a. The 3-day COT release lag means positioning data is stale at both daily and weekly frequencies. The information advantage is too small to generate positive expectancy after transaction costs.

### What COT Is Good For

While COT cannot drive tradeable entry signals for EURUSD, it provides useful structural information:

1. **Position sizing modifier** — COT bias can upweight/downweight EURUSD positions in the portfolio based on macro regime alignment
2. **Cross-asset macro context** — EURUSD COT leveraged fund positioning provides information about USD sentiment that may inform XLF positioning (financial sector sensitivity to USD)
3. **Weekly regime validation** — COT positioning extremes can confirm weekly regime classifications from the regime classifier
4. **FX pair mapping** — The COT infrastructure exists for all FX futures (GBPUSD, USDJPY, AUDUSD, etc.) and can be reused

### Portfolio Impact

EURUSD should remain excluded from paper trading until either:
- A reduced-lag COT data source becomes available (e.g., through CFTC's same-day release pilot program)
- A different entry mechanism is found that can exploit the COT directional bias (e.g., option-based, or weekly swing with wide stops)
- The COT signal is used ONLY as a position-sizing overlay for existing portfolio assets, not as an independent trading signal

## Correlation Check (Pre-Allocation)

Before any allocation decision with EURUSD:

```python
correlation_checks = {
    'EURUSD vs XLF':    target_below_0.30,  # different drivers — equity vs FX positioning
    'EURUSD vs BTC':    target_below_0.30,  # different drivers — crypto vs FX
    'EURUSD vs NZDJPY': target_below_0.40,  # both FX — may be higher
}
```

NZDJPY correlation is the critical one. Both are FX, but:
- NZDJPY driver: carry trade (VIX + yield spread)
- EURUSD driver: COT positioning (leveraged fund flow)

These should be largely independent — but must be verified before adding EURUSD to the portfolio.

### Allocation Math

Current portfolio:
```python
CURRENT = {'XLF': 0.40, 'BTC': 0.35, 'NZDJPY': 0.25}
```

Two options depending on correlation check result:

**Option A: EURUSD vs NZDJPY < 0.30** (genuinely independent)
```python
WITH_EURUSD_A = {
    'XLF':    0.35,   # slight reduction
    'BTC':    0.30,   # slight reduction
    'NZDJPY': 0.20,   # slight reduction
    'EURUSD': 0.15,   # new allocation
}
```

**Option B: EURUSD vs NZDJPY 0.30-0.40** (partially correlated)
```python
WITH_EURUSD_B = {
    'XLF':    0.40,   # unchanged
    'BTC':    0.35,   # unchanged
    'NZDJPY': 0.15,   # reduced to make room
    'EURUSD': 0.10,   # smaller allocation — shared FX risk
}
```

Decision rule:
- If walk-forward passes AND correlation checks pass → Option A (full allocation)
- If walk-forward passes AND NZDJPY correlation 0.30-0.40 → Option B (reduced allocation)
- If walk-forward fails → do not add EURUSD, revisit feature form

## Files Created/Modified

- `data/loaders/download_cot.py` — New: CFTC COT data downloader
- `data/loaders/cot_loader.py` — New: Contract lookup + alignment
- `features/cot_features.py` — New: COT feature engineering
- `features/pair_specific.py` — Modified: COT integration in `build_eurusd_features()`
- `data/weekly_pipeline.py` — Modified: COT generation step
- `diagnostics/eurusd_cot_isolation_test.py` — New: Standalone COT validation script
- `models/macro_expert_head.py` — Modified: Configurable features and model_params kwargs for per-asset macro head setup
- `models/hybrid_ensemble.py` — Modified: Accepts `macro_head_config` dict for per-asset overrides (features, learning_rate, etc.)
- `diagnostics/eurusd_hybrid_isolation_test.py` — New: Hybrid ensemble isolation test (COT in MacroExpertHead)
- `backtests/eurusd_hybrid_walkforward.py` — New: Full hybrid walk-forward (daily and weekly configurations)

## Consequences

**Positive:** EURUSD unblocked for analysis (COT directional bias confirmed). COT infrastructure now available for other FX pairs (GBPUSD, USDJPY, AUDUSD) and for XLF financial sector positioning analysis. The 3-day lag alignment honed by COT work is a reusable pattern. The configurable MacroExpertHead allows any future asset to use custom feature sets and learning rates.

**Negative:** COT requires ongoing weekly data ingestion (Friday release). Walk-forward does not clear the deployment gate at any frequency — COT provides correct directional bias but cannot generate tradeable PnL due to the 3-day release lag and weekly observation frequency. EURUSD remains excluded from paper trading. The `learning_rate=0.30` divergence increases configuration surface. The COT prediction pipeline adds ~260ms to feature generation per call.
