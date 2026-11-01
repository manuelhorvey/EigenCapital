# F-09 — Holm / Benjamini-Hochberg Correction

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION` (not closed)
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `174b5a1`
**Severity:** High · **Category:** statistics
**Date:** 2026-11-01

---

## 1. Finding

`src/eigencapital/analytics/validation/multiple_testing.py` produced invalid
Holm and Benjamini-Hochberg adjusted p-values. Holm was anti-conservative for
the largest raw p-value, so a hypothesis with `p=0.03` was rejected at
`alpha=0.05` when correct Holm retains it. The FWER/FDR guarantees did not
hold.

## 2. Reproduction (before the fix)

```
holm([0.001, 0.04, 0.03])              -> [0.003, 0.06, 0.04]   expected [0.003, 0.06, 0.06]
benjamini_hochberg([0.001,0.04,0.03])  -> [0.003, 0.045, 0.04]  expected [0.003, 0.04, 0.04]
holm([0.01,0.02,0.03,0.04,0.05])       -> [0.05, 0.05, 0.08, 0.08, 0.09]
                                                                expected [0.05, 0.08, 0.09, 0.09, 0.09]
```

## 3. Root cause

The implementation adjusted each p-value by rank, then **sorted the multiset of
adjusted values** and remapped them to indices using the rank order:

```python
sorted_adj = sorted(adjusted)
for i in range(1, n):
    sorted_adj[i] = max(sorted_adj[i], sorted_adj[i - 1])
for i, (orig_idx, _) in enumerate(indexed):
    result[orig_idx] = sorted_adj[i]
```

Sorting discards the association between an adjusted value and the hypothesis
it belongs to. Enforcing monotonicity on the sorted list therefore does not
enforce it on the rank-ordered sequence, and the remap assigns another
hypothesis's adjusted value to the index. BH had the symmetric defect.

## 4. Correction

The cumulative maximum (Holm) and cumulative minimum (BH) are now applied
**in rank order**, and each value is written directly to its own index:

```
adj_Holm(k)  = max_{j <= k} min(1, (n - j + 1) * p_(j))
adj_BH(k)    = min_{j >= k} min(1, n * p_(j) / j)
```

Inputs are validated once: non-numeric, non-finite, or out-of-range values
raise `ValueError` rather than being silently corrected. The caller's list is
not mutated.

No method was substituted: Holm remains Holm, BH remains BH.

## 5. Files changed

- `src/eigencapital/analytics/validation/multiple_testing.py`
- `tests/unit/analytics/test_multiple_testing.py`
- `tests/property/test_multiple_testing_properties.py` (new)

## 6. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/analytics/test_multiple_testing.py tests/property/test_multiple_testing_properties.py -q` | **32 passed** |
| `pytest tests/unit/analytics -q` | **176 passed** |
| `pytest tests/unit/research/factor_lab/test_factor_lab.py tests/unit/research/parameter_stability/test_grid.py tests/unit/research/volatility/test_hypotheses_evidence.py tests/unit/research/test_alpha_freeze.py -q` | **88 passed** |
| `pytest tests/unit tests/property tests/integration tests/failure_injection -q` | **3662 passed, 2 skipped, 3 xfailed** in 424.61 s |

Environment: Python 3.14.8, pytest 9.1.1, hypothesis 6.152.9. The 2 skips and
3 xfails are pre-existing and unrelated to this change; the xfails are the
documented Gate-6 cases under F-04.

Test coverage added:

- Hand-calculated Holm and BH values.
- Caller-order preservation for unsorted input.
- Cumulative max/min in rank order.
- Rejection decisions for the `[0.001, 0.04, 0.03]` example.
- Holm FWER bound (no rejection when the smallest p exceeds `alpha/n`).
- BH FDR bound (no rejection when every `p_(k) > k*alpha/n`).
- BH is pointwise no more conservative than Holm.
- Ties remain tied; input is not mutated.
- Non-numeric / NaN / ±inf / out-of-range inputs fail closed.
- Hypothesis properties over arbitrary p-value lists: bounds, monotonicity,
  order preservation, BH <= Holm, Bonferroni bounds.

## 7. What this does not establish

- No independent reviewer has verified the correction yet.
- Research verdicts that consumed the old adjusted p-values have **not** been
  re-derived. Callers are `research/factor_lab/evaluation.py`,
  `research/parameter_stability/grid.py`, and
  `scripts/run_r4_b2_pairs.py`. Their reports must be re-run and any verdict
  that depended on a wrong adjusted p-value restated. This is tracked as part
  of the F-08/F-10 re-derivation unit.
- The corrected functions are not evidence that any research claim is valid;
  they only restore the stated statistical procedure.

## 8. Closure decision

`IMPLEMENTED — AWAITING VERIFICATION`. Not `CLOSED`. Remaining acceptance
evidence: independent review plus re-run/restatement of affected research
verdicts.
