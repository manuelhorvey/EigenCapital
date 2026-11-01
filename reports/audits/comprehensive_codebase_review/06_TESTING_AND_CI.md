# Testing and CI Assessment

## Evidence executed in this review

| Command | Result |
|---|---|
| `pytest --collect-only -q` | `3644 tests collected in 5.04s` |
| `pytest tests/unit/execution tests/unit/live tests/unit/risk tests/unit/portfolio tests/unit/reconciliation -q` | Passed (3 xfailed) |
| `pytest tests/property -q` (3 consecutive runs) | `10 passed` each run, ~22–23 s; **no flake reproduced** |
| `pytest tests/unit/live/test_stop_loss_policy.py -q -rxX` | `14 passed, 3 xfailed` |
| `ruff check src scripts tests` | `All checks passed!` |
| `mypy src/eigencapital` | `Success: no issues found in 310 source files` |

Environment: Python 3.14.8, pytest 9.1.1, hypothesis 6.152.9.

## CI pipeline (`.github/workflows/ci.yml`)

Two jobs:

1. **test** — matrix Python 3.11/3.12/3.13; repo-hygiene check (no tracked gitignored files); `pip install -e ".[research]"` + `.[dev]`; `ruff`; `mypy` on critical safety packages and then full package; `pytest tests/unit --cov --fail-under=80`; then property + integration + failure_injection + simulation + dashboard tests; Codecov upload on 3.12.
2. **frontend** — Node 24, `npm ci`, `oxlint`, `npm run build` (tsc + vite).

Strengths:

- type-checking of safety packages is gated, then the full package is gated;
- integration/property/failure-injection suites run on **all** matrix versions (not just one);
- repo-hygiene step prevents silently ignored tracked files;
- frontend typecheck is part of build, not optional.

Gaps:

- **No test asserts the live loop uses the durable audit ledger.** Tests for `DurableAudit`, `EventLedger`, and `execute_orders` exist in isolation; none asserts the wiring, which is precisely the missing piece (P0-2/P0-3).
- **No test asserts `max_absolute_weight_error` blocks an order.** The only reference is diagnostic persistence.
- **3 xfailed stop-loss tests** encode the known Gate-6 gap. Xfail is honest, but CI is green while the condition remains.
- Reconciliation tests exercise the engine, not the loop's caller; the tautological construction is not covered.
- Dashboard truth defects (unrealized P&L, daily-loss remaining, staleness-gated health) have no failing test.
- Coverage excludes `**/research/**` and the research package is excluded from the installed distribution, so research tests run but research coverage is not measured. Reasonable, but it means the broken statistics are not caught by coverage.
- No mutation testing, no property test for statistical invariants (e.g., "adjusted p-values are monotone in raw p"), which is why F-08/F-09 survived.
- CI does not test Python 3.14, which is the local interpreter used for this review.
- `fail_ci_if_error: false` for Codecov; coverage threshold itself is enforced by pytest-cov, so this is minor.
- No dependency vulnerability scan and no lockfile/hash pinning.

## Test-suite composition (observed)

- Unit tests dominate and are the strongest layer.
- Property tests cover invariants and passed repeatedly.
- Failure-injection and simulation suites exist — a genuine maturity signal.
- Integration tests exist and run in CI.
- Live-loop tests are limited by the god-script structure: logic embedded in `run_cycle` is hard to test without a broker.

## Test-evidence quality rating

| Dimension | Rating |
|---|---|
| Breadth | Good (3,644 tests) |
| Determinism observed | Good (property suite stable 3×) |
| Static gates | Good (ruff + mypy clean) |
| Safety-wiring coverage | **Weak** (the critical gaps are untested) |
| Statistical correctness coverage | **Weak** |
| CI reproducibility | Medium (unpinned deps/actions) |
| Frontend CI | Good |

## Recommended test additions (planning only)

1. A test that runs one synthetic cycle with a fake broker and asserts an `EventLedger` trade chain exists with `decision_id → intent_id → order_id → fill_id`.
2. A test that persists an internal ledger, mutates broker positions, and asserts reconciliation reports a mismatch and HALTs.
3. A test that a weight error above `max_absolute_weight_error` prevents order submission (or delete the config claim).
4. Property test: Holm adjusted p-values are non-decreasing in raw-p rank and ≥ raw p; BH likewise monotone with the step-up bound.
5. PBO test: random performance matrices do not yield constant 1.0; known CSCV fixture yields the expected value.
6. Dashboard tests: `unrealized_pnl` non-zero when positions exist; `daily_loss_remaining` decreases with loss; stale `alive=true` reads as STALE.
7. Regression test that the reconciliation file written by the loop is the file the dashboard reads.
