# F-23 — Documentation Drift and Absent Governing Specs

**Status:** `IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `55ebb33`
**Severity:** Low · **Category:** documentation
**Date:** 2026-11-01

---

## 1. Finding

Inline comments contradicted code: `scripts/r4_rebalance_loop.py` claimed
`MAX_POSITION_USD = 1500` and `MAX_CONCURRENT = 8`, while the live config
defines `max_position_size = 5000` and `max_concurrent_positions = 20`
(`configs/production/config.toml`, `src/eigencapital/config.py`).

Two governing specs referenced across the repo do not exist:
`SYSTEM_SPECIFICATION.md` and `domain_contracts.md`.

`EC-AUDIT-009` (closure & capital readiness gate) exists only as a draft;
status `DRAFT — AMENDED; NOT ADOPTED; GATE NOT PASSED`.

## 2. Correction

Removed the stale inline value comments (`# 1500`, `# 8`) so comments can no
longer drift from the loaded config values:

```python
MAX_POSITION_USD = _config.capital.max_position_size
MAX_CONCURRENT = _config.capital.max_concurrent_positions
MAX_ORDERS_PER_CYCLE = _config.execution.max_orders_per_cycle
```

## 3. Governing-spec status (explicit)

The repo does not contain `SYSTEM_SPECIFICATION.md` or
`domain_contracts.md`. They are treated as **historical references only**; no
new governing specifications are authored as part of this remediation, to
avoid introducing unverified contracts.

The adopted closure/capital-readiness reference is
`reports/audits/EC_AUDIT_009_CLOSURE_AND_CAPITAL_READINESS_GATE.md`
(`EC-AUDIT-009`). Its status is explicitly:

- `DRAFT — AMENDED FOLLOWING INDEPENDENT REVIEW`
- `NOT ADOPTED`
- `GATE NOT PASSED`
- Capital increase: **NOT AUTHORIZED**

No gate is formally adopted in this remediation; EC-AUDIT-009 is the
reference document, not an approved gate.

## 4. Files changed

- `scripts/r4_rebalance_loop.py` (stale comments removed)

## 5. Verification executed

| Command | Result |
|---|---|
| `git diff scripts/r4_rebalance_loop.py` | Only the three trailing comment lines changed |
| `grep -rn "SYSTEM_SPECIFICATION\|domain_contracts" src scripts` | No source references remain |
| `pytest tests/unit/analytics tests/unit/live -q` | No regressions (see unit suites above) |

No behaviour changed: the code already read values from config; comments were
the only stale artifact.

## 6. What this does not establish

- No new governing specifications are created.
- EC-AUDIT-009 is not adopted; the capital-readiness decision is unchanged.
- Independent review has not occurred.

## 7. Closure decision

`IMPLEMENTED — AWAITING INDEPENDENT VERIFICATION`. Not `CLOSED`.
