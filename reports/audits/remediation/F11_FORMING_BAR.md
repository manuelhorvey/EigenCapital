# F-11 — Forming-Bar Live Signal

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `c91a8d9`
**Severity:** High · **Category:** signal correctness
**Date:** 2026-11-01

---

## 1. Finding

`scripts/r4_rebalance_loop.py:515` called
`copy_rates_from_pos(symbol, TIMEFRAME_D1, 0, bars)`. `start_pos=0` includes
the current, still-forming daily bar. R4's lookbacks then operated on a bar
whose close, volume, and high/low changed on every hourly cycle, so the
signal and the computed weights were not reproducible within a day.

## 2. Reproduction

The defect is a call-site parameter, not a numerical function. The new test
records the arguments passed to the broker double:

```
before: ("EURUSD", 0, 10)
after:  ("EURUSD", 1, 10)
```

A second path, `scripts/r4_live_orders.py`, had the same `start_pos=0` call
and computes the same frozen signal for manual order submission.

## 3. Correction

Request `start_pos=1`, which returns the most recent `bars` **completed** D1
bars and excludes the forming bar. Applied to:

- `scripts/r4_rebalance_loop.py::fetch_d1_data` (production loop path)
- `scripts/r4_live_orders.py::fetch_d1_data` (manual live-order path)

No signal mathematics changed: lookback (`252`), skip (`21`), regime
conditioning, rank/centering, volatility scaling, clip bounds, BTC cap,
universe, sizing, and rebalance policy are untouched. The only change is
which rows enter the existing calculation.

## 4. Files changed

- `scripts/r4_rebalance_loop.py`
- `scripts/r4_live_orders.py`
- `tests/unit/test_forming_bar.py` (new)

`scripts/r4_monitor.py` and `scripts/r4_supervisor_dryrun.py` also read D1
with `start_pos=0`, but they are observability/dry-run tools and do not
produce the order-generating signal. They were left unchanged to keep this
unit scoped; they should be migrated if they are ever used to derive trading
decisions.

## 5. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/test_forming_bar.py -q` | **3 passed** |
| `pytest tests/unit/test_forming_bar.py tests/unit/test_t0_sizing.py -q` | **35 passed** |
| `pytest tests/unit/shadow/portfolio/test_r4_immutability.py tests/unit/live/test_r4_restart_consistency.py tests/unit/live/test_rebalance_policy_loop_integration.py tests/unit/test_r4_loop_reconnect.py tests/unit/test_r4_single_instance.py tests/unit/test_r4_signal_fidelity.py -q` | **69 passed** |

The R4 fidelity and immutability guards pass unchanged, confirming the frozen
signal constants and formulas were not altered.

## 6. Operational consequence

The staleness check (`_MAX_D1_DATA_AGE_SECONDS = 3 days`) now measures the
age of the last **closed** bar, which is up to one day older than the forming
bar. Late-Monday or long-holiday cycles may therefore skip as stale where
they previously did not. That is the conservative direction and was not
adjusted; changing the threshold would be a separate safety decision.

## 7. What this does not establish

- No backtest/live comparison was performed; the change removes a known
  input-timing defect, it does not prove performance.
- Intraday-update semantics were not adopted; R4 remains a completed-bar
  strategy.
- Independent review has not occurred.

## 8. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`.
