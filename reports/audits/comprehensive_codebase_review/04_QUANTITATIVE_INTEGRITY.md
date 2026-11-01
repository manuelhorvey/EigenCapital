# Quantitative Integrity Assessment

## Summary

The R4 *signal definition* is disciplined and frozen. The research *inference layer* is not trustworthy in its current form: two validation statistics are objectively wrong, provenance does not reproduce, and the cited research artifacts are absent. Reported research confidence should be treated as **unverified** until corrected and re-run.

## 1. R4 signal identity — sound

Per `reports/audits/EC_AUDIT_001_R4_IDENTITY_DECISION_RECORD.md` (Alternative A, approved):

- `signal_vol_scale_reference = 0.50` is the divisor actually consumed by the live signal/sizing path.
- `vol_target_annual = 0.10` is declared but **not** consumed by the live signal.
- `tests/unit/test_r4_signal_fidelity.py` guards the identity.

This is a documented, approved resolution — not drift. No action required in this review.

Minor: inline comments in `scripts/r4_rebalance_loop.py:163-168` still say `# 1500` and `# 8` while the actual configured values are `5000` and `20`. Cosmetic but misleading during incident response.

## 2. Multiple-testing correction — **wrong (confirmed at runtime)**

File: `src/eigencapital/analytics/validation/multiple_testing.py:63-129`.

The implementation computes adjusted p-values per rank, then **sorts the adjusted values and maps them back by rank position**. That destroys the rank↔adjusted correspondence and does not implement the required step-down/step-up monotonicity.

Runtime evidence (executed in this review):

```
input                       [0.001, 0.04, 0.03]
holm()                      [0.003, 0.06, 0.04]
correct Holm                [0.003, 0.06, 0.06]
benjamini_hochberg()        [0.003, 0.045, 0.04]
correct BH                  [0.003, 0.04,  0.04]
```

Impact:

- **Holm is anti-conservative.** In the example, the test with `p=0.03` is reported as `0.04` instead of `0.06`; at `α=0.05` it is **rejected when correct Holm would not reject it**. Family-wise error control is no longer guaranteed.
- **BH is non-monotone in raw-p order** (0.045 for a smaller raw p than one reported at 0.04), so FDR control is not guaranteed either. In this example it is not anti-conservative, but it is invalid.

Blast radius: any R3/R4-B2 gate or report that calls these functions and claims multiplicity-controlled significance. Verdicts must be re-derived after the fix.

Fix shape: sort `(orig_index, p)` ascending; compute `adj = p * (n - rank)` for Holm (`rank` 0-based) or `p * n / (rank+1)` for BH; apply a **cumulative max** forward (Holm) or **cumulative min** backward (BH) over the rank-ordered array; scatter back by `orig_index`. Never sort the adjusted values.

## 3. Probability of Backtest Overfitting — **structurally constant 1.0 (confirmed)**

File: `src/eigencapital/analytics/validation/pbo.py:53-126`.

The implementation:

1. splits candidate indices into `train = indices[:n//2]`, `test = indices[n//2:]` — a **single deterministic disjoint split**, repeated identically `n_partitions` times (the loop body does not vary the split);
2. picks `best_is_idx` from **train**;
3. asks whether `best_is_idx` appears in **test**.

Because train and test are disjoint, the best-in-train index can **never** appear in test. Therefore `overfit_count == total_partitions` for every input with `n >= min_candidates`.

Runtime evidence:

```
12 candidates, monotonically degrading OOS Sharpe
compute_pbo(...) -> pbo=1.0, overfit_count=6, total_partitions=6
```

`reports/research_program/*` state "PBO 1.000 (16/16)" — that value is an artifact of this bug, not evidence of overfitting. It equally means the metric carries no information.

Fix shape: use combinatorial symmetric cross-validation (CSCV). Enumerate combinations `C(S, S/2)` of the performance matrix, rank configurations in-sample, take the top configuration, and compute its out-of-sample rank / logit; PBO = frequency the selected configuration lands in the bottom half OOS. Report the number of combinations actually evaluated.

## 4. Correctness-preserving components (strengths)

- Purged/embargoed walk-forward splitting.
- Deflated Sharpe Ratio (DSR) implementation present.
- Block bootstrap present.
- Deterministic provenance hashing helpers.
- `LookAheadViolationError` guard in `backtest/clock.py`; signal at `t` cannot fill before `t + execution_delay`.

These are genuine, but they do not compensate for the two broken statistics above.

## 5. Research provenance and evidence

| Claim | Status |
|---|---|
| `EXP-000002.provenance_hash` reproduces from stored inputs | **No.** Stored `1b81…` does not match recomputation (`e549…` blanked, `fbb4…` included). `repository.load()` never re-verifies. |
| `dataset_hash` matches the experiment universe | **No.** Hash is SHA-256 of `data/mt5/R5_data_manifest.json` (38 instruments); EXP-000002 declares 42 symbols; production config allows 37 (30 tradeable). |
| `program_status.json` R1–R6 artifacts exist | **No.** All six cited directories are absent from the tree. |
| `git_commit fda2468` resolvable | **No.** Unresolvable in this repo. |
| Promotion path to production is enforced | **No.** No code path promotes research to live; production uses the frozen R4 constants directly. Registry is mutable (`save()` overwrites, `delete()` available, `_MODIFIABLE_BEFORE_FREEZE` is dead code). |
| Simulated executors are test-only | **Currently yes**, but they are importable production modules (`SIMULATED_EVIDENCE`). Latent fabrication risk if ever wired into a report path. |

## 6. Backtest realism

`backtest/engine.py` is better than a naive vectorized backtest (explicit clock, execution delay, cost model, accounting), but its fill model is **not suitable as capital-scaling evidence**:

- fixed `tick_size = 0.25` for every instrument;
- fixed `quantity = 1.0` contract per signal;
- fill at bar close plus a static spread/slippage in ticks;
- no symbol-specific contract size, margin, swap, financing, or liquidation;
- `trade_count = len(fill_events) // 2` — an approximation, not real round-trip accounting;
- no partial fills, no rejections, no gaps-through-stop handling.

Conclusion: useful for relative strategy comparisons and look-ahead testing; **not** a basis for capacity, slippage, or drawdown claims.

## 7. Live signal input integrity

`fetch_d1_data` (`scripts/r4_rebalance_loop.py:509-520`) calls `copy_rates_from_pos(sym, TIMEFRAME_D1, 0, bars)`, which includes the **currently forming** D1 bar. The loop wakes hourly and recomputes the signal on an evolving daily bar. Consequences:

- intraday signal churn and unnecessary turnover;
- weights can differ between the signal that produced an order and the signal reported at end of day;
- the "daily" signal is not reproducible from a fixed bar-close timestamp.

No incomplete-bar filter was found. This is a correctness/consistency defect, not look-ahead (the forming bar is legitimately available), but it undermines reproducibility and interacts badly with the 10 bps band and execution costs.

## 8. Findings relevant to this document

| ID | Severity | Finding |
|---|---|---|
| F-08 | High | PBO structurally constant 1.0 |
| F-09 | High | Holm/BH correction invalid (anti-conservative Holm) |
| F-10 | High | Research provenance unverifiable; artifacts absent |
| F-11 | High | Live D1 signal includes the forming bar |
| F-18 | Medium | Backtest fill model unsuitable for scaling evidence |
| F-20 | Medium | Experiment registry mutable, no enforced promotion path |

## 9. Quantitative integrity rating

| Area | Rating |
|---|---|
| Signal definition discipline | Good |
| Statistical validation | **Unsound** (two broken statistics) |
| Provenance reproducibility | **Unsound** |
| Backtest look-ahead control | Good |
| Backtest execution realism | Weak |
| Research→production governance | Weak (absent path) |

Research-derived confidence should be restated as **provisional** until F-08 and F-09 are fixed and affected experiments re-run.
