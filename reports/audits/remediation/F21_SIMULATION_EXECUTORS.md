# F-21 — Simulation Executors Importable in Production Package

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `7db75db`
**Severity:** Medium · **Phase:** P2
**Date:** 2026-11-01

---

## 1. Finding

`SIMULATED_EVIDENCE` (hard-coded, "realistic OOS metrics" for the frozen
campaign) and the research executors live in `src/eigencapital/research/alpha/`,
a namespace importable from the source tree and referenced by tests. Simulated
evidence must not be selectable in production.

## 2. Mitigations

**Build-time (already present):** `pyproject.toml` excludes
`eigencapital.research*` from the built packages
(`[tool.setuptools.packages.find] exclude`), so research modules — including
`SIMULATED_EVIDENCE` — are not installed into production deployments and cannot
be imported from an installed wheel.

**Source-tree guard (this change):** `executor.py` now raises `RuntimeError` at
import time unless `EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS=1`:

```python
if os.environ.get("EIGENCAPITAL_RESEARCH_ALLOW_IMPORTS") != "1":
    raise RuntimeError(
        "eigencapital.research.alpha.executor is research-only tooling: it "
        "ships SIMULATED_EVIDENCE and must not be imported outside tests. ..."
    )
```

Tests that need the module set the flag before importing
(`tests/unit/research/test_alpha_executor.py`).

## 3. Files changed

- `src/eigencapital/research/alpha/executor.py` (import guard)
- `tests/unit/research/test_alpha_executor.py` (set test flag before import)
- `tests/unit/research/test_research_import_guard.py` (new: import raises
  without the flag, loads with the flag)

## 4. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/research/test_research_import_guard.py tests/unit/research/test_alpha_executor.py -q` | **22 passed** |
| `pytest tests/unit/research -q` | **785 passed** |

No production (non-research, non-test) code imports `eigencapital.research.alpha.executor`, so the guard has no production impact.

## 5. What this does not establish

- The remaining research executors (`r2_executor`, `r3_executor`, `r4_executor`,
  etc.) are research tooling consumed by research campaigns and scripts, not by
  the live loop; moving them wholesale under `tests/` is a larger refactor and
  was deferred to avoid scope creep. The build-time exclusion plus the
  `executor.py` import guard cover the simulated-evidence surface named in the
  finding.
- Independent review has not occurred.

## 6. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`.
