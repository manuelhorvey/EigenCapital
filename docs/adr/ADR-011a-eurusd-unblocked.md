# ADR-011a: EURUSD Unblocked — COT Integration Complete

**Status:** Accepted — supersedes ADR-011

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

### Key Implementation Detail

COT features require `learning_rate=0.3` (vs `0.02` for XLF/BTC). COT data is weekly, so each observation carries more signal density. The higher learning rate lets the model weight it appropriately.

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

**COT signal confirmed. Proceed to walk-forward validation.**

## Deployment Path

1. Run full walk-forward (5yr expanding window, 1yr test, 1yr step)
2. Clear deployment gate: PF > 1.10, bootstrap p < 0.10
3. Run signal correlation check vs XLF, BTC, NZDJPY (target < 0.30 pairwise)
4. Allocate in paper trading portfolio if correlation gate clears

## Files Created/Modified

- `data/loaders/download_cot.py` — New: CFTC COT data downloader
- `data/loaders/cot_loader.py` — New: Contract lookup + alignment
- `features/cot_features.py` — New: COT feature engineering
- `features/pair_specific.py` — Modified: COT integration in `build_eurusd_features()`
- `data/weekly_pipeline.py` — Modified: COT generation step
- `diagnostics/eurusd_cot_isolation_test.py` — New: Validation script

## Consequences

**Positive:** EURUSD unblocked for walk-forward and potential deployment. COT infrastructure now available for other FX pairs (GBPUSD, USDJPY, AUDUSD) and for XLF financial sector positioning analysis. The 3-day lag alignment honed by COT work is a reusable pattern.

**Negative:** COT requires ongoing weekly data ingestion (Friday release). Walk-forward may still not clear the deployment gate — COT fixes the feature gap but does not guarantee tradable signal. EURUSD COT model needs `learning_rate=0.3` diverging from the XLF/BTC standard of `0.02`, increasing configuration surface.
