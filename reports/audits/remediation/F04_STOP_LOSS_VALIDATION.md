# F-04 — Stop-Loss Gate Validation

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `18e254b`
**Severity:** High · **Category:** risk control
**Date:** 2026-11-01

---

## 1. Finding

When `require_sl_on_positions` was enabled, Gate 6 classified only `sl == 0`
as unprotected. `None`, negative, non-numeric, non-finite, boolean,
wrong-side, and unknown-side values were treated as protected. Three strict
`xfail` tests documented the gap.

## 2. Reproduction (before the fix)

```
tests/unit/live/test_stop_loss_policy.py
  14 passed, 3 xfailed
```

The three xfails were `sl=None`, `sl=-1.0`, and `sl="invalid"`. Each returned
`GateResult.PASS` or failed to return `CRITICAL` under the old predicate:

```python
unprotected = [p for p in positions if p.get("sl", 0) == 0]
```

`None != 0`, `-1.0 != 0`, and `"invalid" != 0`, so all three slipped through.

## 3. Correction

A stop-loss now counts as protection only when it is:

- present and not `None` / boolean,
- numeric and finite,
- strictly positive,
- below the entry price for a long (`type == 0`),
- above the entry price for a short (`type == 1`),
- paired with a known, finite entry price and a known side.

Anything else is unprotected and produces the existing Gate 6 `CRITICAL` with
`BlockReason.NO_SL_PROTECTION`. Unknown entry/type fails closed because
protection cannot be proven.

The gate's **advisory semantics are unchanged**: Gate 6 still does not
early-exit the pipeline. Gate enablement remains a separate operator decision.

## 4. Files changed

- `src/eigencapital/live/risk_enforcement.py`
- `tests/unit/live/test_stop_loss_policy.py`

## 5. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/live/test_stop_loss_policy.py -q` | **27 passed** (previously 14 passed, 3 xfailed) |
| `pytest tests/unit/live tests/unit/test_core_and_live_edges.py -q` | **480 passed** |

Added cases: valid short SL, long SL above entry, short SL below entry,
missing entry price, unknown position side, NaN/±inf/boolean/empty SL, plus
the three former xfails.

Not weakened: the xfails were removed only because the behavior they asserted
now passes. No test was skipped or converted to a warning.

## 6. Production impact

None in the current configuration. `configs/production/config.toml` sets
`require_sl_on_positions = false`, and the disabled path still returns `PASS`
with `"SL check disabled"`. The change is dormant until an operator explicitly
enables the gate after its own validation and approval.

The catastrophic stop-loss supervisor continues to operate independently; this
change does not alter it.

## 7. What this does not establish

- The stop-loss gate is **not enabled**.
- No claim is made that every live position is protected; the gate is
  disabled in production and the supervisor remains the backstop.
- Independent review has not occurred.
- This says nothing about capital readiness.

## 8. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`.
