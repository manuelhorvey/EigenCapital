# R1-B4 Monte Carlo Evidence Report

Report version: 1

## Scope (exact stream consumed)

- Stream: `TS-R4-D1-0001` (experiment `EXP-R1-FIRSTSTREAM`)
- Strategy: R4 v4.0 | Dataset: mt5_d1_local 2026.08 | Cost model: one_way_15bps
- Period: 2020-10-27T00:00:00 → 2026-08-07T00:00:00 | Trades: 1311 | Provenance: `2a801a7aae176230...`
- This report describes exactly the persisted trade stream identified above. It is a persisted historical trade stream and NOT a claim about the strategy's long-run behavior.

## Resampling configuration (as run)

- **B1** (trade_sequence_permutation): n=1000, seed=42
- **B2** (iid_bootstrap_with_replacement): n=1000, seed=42
- **B3** (moving_block_bootstrap): n=1000, seed=42
- **B3 method: moving_block | Block length: 20 (pre-specified) | Blocks per resample: 66**
- Block length was pre-specified, not selected. It is not claimed to be universally optimal; its interaction with the dependence structure is a separate later study.

## OBSERVED HISTORICAL PATH

total_pnl=-0.0756 | trades=1311 | max_drawdown=0.0925 | longest_loss_streak=15
- Percentiles below are the position of the OBSERVED path inside each RESAMPLED DIAGNOSTIC DISTRIBUTION — a statement about the experiment that was run.

## RESAMPLED DIAGNOSTIC DISTRIBUTIONS (comparison per metric)

| Metric | Historical | B1 pct | B2 pct | B3 pct | width B1/B2 | width B3/B2 | dep. Δq95 (B3−B2) |
|--------|-----------:|-------:|-------:|-------:|------------:|------------:|------------------:|
| max_drawdown | +0.0925 | 0.270 | 0.436 | 0.421 | 0.25 | 1.03 | +0.0014 |
| max_drawdown_duration | +1248.0000 | 0.537 | 0.545 | 0.492 | 0.66 | 1.15 | +0.0000 |
| longest_losing_streak | +15.0000 | 0.197 | 0.207 | 0.667 | 0.99 | 1.12 | +4.9500 |
| recovery_time | None | 1.000 | 0.993 | 0.962 | 0.00 | 1.30 | +126.3500 |
| min_equity | +0.9155 | 0.248 | 0.467 | 0.437 | 0.17 | 1.05 | -0.0049 |
| time_under_water | +1303.0000 | 0.622 | 0.576 | 0.464 | 0.80 | 1.48 | +0.0000 |
| total_pnl | -0.0756 | n/a (invariant) | 0.494 | 0.435 | nan | 1.12 | -0.0112 |
| final_equity | +0.9244 | n/a (invariant) | 0.494 | 0.435 | nan | 1.12 | -0.0112 |

## INTERPRETATION

- The observed maximum drawdown lies at the 27% / 44% / 42% percentile of the B1/B2/B3 resampled maximum-drawdown distributions.
- Stable across resampling assumptions (historical percentile spread <= tolerance): max_drawdown, max_drawdown_duration, recovery_time, time_under_water, total_pnl, final_equity.
- Materially changed when serial dependence is retained (B3 vs B2 adverse q95): recovery_time, longest_losing_streak, max_drawdown. This difference itself is evidence: IID resampling understates these tails for this stream.
- All percentiles in this report describe the experiment that was run. None is a probability about future outcomes.

*Note:* B1 percentiles are shown as `n/a (invariant)` for metrics that are identical in every permutation (set-invariant under order-only resampling) — no percentile exists there to report.

**Wording guard (applies to every number in this report):**

> **Correct:** "The observed maximum drawdown lies at the 72nd percentile of the B3 resampled maximum-drawdown distribution."
>
> **Incorrect:** "There is a 72% probability that future maximum drawdown will be worse."
>
> The first describes the experiment that was run. The second would turn the resampling diagnostic into a future forecast, which the frozen methodology explicitly rejects.

**Methodological rule:** Monte Carlo diagnoses robustness of the realized evidence under specified resampling assumptions. It does NOT produce a probability that the strategy will make money in the future.
