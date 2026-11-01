# EC-AUDIT-009-P0-1 — Equity Reconciliation

**Status:** `BLOCKED — BROKER STATEMENT REQUIRED; P0-1 NOT PASSED`
**Branch:** `audit/ec-remediation-001`
**Gate:** `6a7e77f` (`EC_AUDIT_009_CLOSURE_AND_CAPITAL_READINESS_GATE.md`, frozen)
**Tool commit:** `bed32f1`
**Date:** 2026-11-01

---

## 1. Scope

P0-1 of the frozen closure gate requires the equity path from
2026-09-26 to 2026-10-29 to be reconciled against a broker statement, with
every material step classified and every residual within USD 0.01:

```bash
python scripts/audit/equity_reconciliation.py \
  --start 2026-09-26 \
  --end 2026-10-29 \
  --statement <broker.csv>
```

Acceptance requires exit `0`, `unexplained_steps == 0`, a classification and
evidence reference for each jump, and `abs(delta) < 0.01` USD.

This record covers only P0-1. No trading behavior, configuration, risk
envelope, broker state, or historical evidence was modified.

---

## 2. Deliverable

### 2.1 Tool

`scripts/audit/equity_reconciliation.py` (commit `bed32f1`) implements:

- snapshot loading from `reports/r4_loop/portfolio_analytics.jsonl`;
- broker statement loading from CSV;
- classification of **every** consecutive equity step, not only material jumps;
- jump detection at a configurable threshold (default 10%);
- per-step reconciliation against statement transactions;
- a total reconciliation equation:

  ```text
  closing_equity - (opening_equity + total_statement_delta) <= 0.01 USD
  ```

- fail-closed behavior for missing, malformed, unknown-type, or non-USD
  statements;
- JSON output with per-step classifications, evidence references, residuals,
  statement hash, and `unexplained_steps` / `unexplained_jumps`.

Exit codes: `0` = PASS, `1` = FAIL, `2` = input error.

Statement schema:

```csv
timestamp,type,amount,reference,currency,balance_after,equity_after
```

Allowed `type` values: `deposit`, `withdrawal`, `credit`, `adjustment`,
`realized_pnl`, `floating_pnl`, `fee`, `swap`. `currency` must be USD when
present. `reference` must be non-empty.

### 2.2 Tests

`tests/unit/audit/test_equity_reconciliation.py` — 9 tests covering:

- deposit explains a material jump (PASS);
- missing explanation fails (FAIL, one unexplained jump);
- realized P&L explains a jump (PASS);
- missing statement exits `2`;
- unknown statement type exits `2`;
- non-USD statement exits `2`;
- the 10% threshold detects a 12% jump; a 15% threshold does not;
- a jump-level explanation cannot hide a total-equation failure;
- output schema and statement hash.

Result: **9 passed**.

---

## 3. Acceptance attempt

Exact acceptance command with the documented repository path:

```bash
python scripts/audit/equity_reconciliation.py \
  --start 2026-09-26 \
  --end 2026-10-29 \
  --statement reports/audits/broker_statement.csv
```

Observed:

```text
ERROR: broker statement not found: reports/audits/broker_statement.csv
EXIT:2
```

No report is written on input failure. The gate cannot be satisfied because
the required source data is absent.

---

## 4. Available equity evidence

`reports/r4_loop/portfolio_analytics.jsonl` contains 65 snapshots in the
window:

| Field | Value |
|---|---|
| Opening equity | `5107.83` at `2026-09-26T23:34:56Z` |
| Closing equity | `18176.81` at `2026-10-29T13:31:40Z` |
| Net change | `+13068.98` |

A diagnostic run using the real snapshot series and an **empty statement**
(header only; not acceptance evidence) produced:

```text
Verdict: FAIL
Snapshots: 65 | Steps: 64 | Jumps: 4 | Unexplained steps: 63 | Unexplained jumps: 4
Opening: $5,107.83 | Closing: $18,176.81 | Statement delta: $0.00 | Residual: $13,068.98
  2026-09-28T06:27:56Z -> 2026-09-28T22:16:25Z: +38.95% | UNEXPLAINED | residual $2,083.46
  2026-09-30T12:26:21Z -> 2026-09-30T22:00:40Z: +56.81% | UNEXPLAINED | residual $4,109.53
  2026-10-07T23:26:57Z -> 2026-10-12T02:50:46Z: +34.24% | UNEXPLAINED | residual $3,908.86
  2026-10-27T00:09:14Z -> 2026-10-29T13:31:40Z: +12.53% | UNEXPLAINED | residual $2,023.29
```

The diagnostic confirms the tool operates on the real series. It is not a
reconciliation: with no statement rows, every material step is correctly
classified `UNEXPLAINED`.

### 4.1 Jump-count discrepancy

The frozen gate refers to three equity jumps (the >15% screen). At the tool's
10% materiality threshold there are **four**:

| # | From | To | Change | Residual |
|---|---|---|---|---|
| 1 | 2026-09-28T06:27:56Z | 2026-09-28T22:16:25Z | +38.95% | $2,083.46 |
| 2 | 2026-09-30T12:26:21Z | 2026-09-30T22:00:40Z | +56.81% | $4,109.53 |
| 3 | 2026-10-07T23:26:57Z | 2026-10-12T02:50:46Z | +34.24% | $3,908.86 |
| 4 | 2026-10-27T00:09:14Z | 2026-10-29T13:31:40Z | +12.53% | $2,023.29 |

The fourth jump is material and must also be classified. The gate's
acceptance condition applies to every jump, so P0-1 cannot pass on the three
>15% jumps alone.

---

## 5. Why P0-1 is blocked

Repository search found only market-data CSVs (under `data/`) and skill data;
there is **no broker account statement or deal-history export**. The available
artifacts do not contain deposits, withdrawals, credits, adjustments, realized
P&L, fees, or swaps. In particular:

- `portfolio_analytics.jsonl` has no unrealized P&L field and no transaction
  references;
- T=0 snapshots contain balances/equity but not transaction history, and the
  newest is `2026-09-30T05:29:29Z` (stale for the full window);
- `reports/execution_audit.jsonl` and `reports/campaigns.jsonl` are absent,
  and `AuditLog` is not wired into the R4 loop;
- no statement hash or evidence reference can be produced.

Therefore:

- `unexplained_steps` is not zero (`63` in the diagnostic);
- no jump has a broker evidence reference;
- the total equation cannot be evaluated;
- the gate's `abs(delta) < 0.01` condition cannot be met.

**P0-1 is `BLOCKED`, not `PASSED`.** The four jumps remain unexplained and are
not to be treated as trading profit.

---

## 6. Required input to unblock

Provide an MT5 account statement / deal-history export covering
**2026-09-26 through 2026-10-29**, in USD, including:

- deposits and withdrawals;
- credits and adjustments;
- realized P&L;
- floating P&L snapshots sufficient to explain each interval;
- fees and swaps;
- unique broker references and timestamps with timezone.

Normalize it to the schema in Section 2.1, place it outside the repository or
at a documented path, record its SHA-256, and run the exact acceptance command
in Section 1. Expected PASS requires:

```text
exit 0
unexplained_steps == 0
abs(delta) < 0.01 USD
```

Until then, the gate remains unpassed and capital remains unauthorized.

---

## 7. Verification

| Check | Result |
|---|---|
| `pytest tests/unit/audit/test_equity_reconciliation.py` | 9 passed |
| `ruff check scripts/audit/equity_reconciliation.py tests/unit/audit/test_equity_reconciliation.py` | pass |
| `ruff format --check` on changed Python files | pass |
| `mypy scripts/audit/equity_reconciliation.py` | pass |
| `git diff --check` | pass |

No live broker action, capital movement, configuration change, or destructive
git operation was performed. The pre-existing stash
`stash@{0}: WIP on fix/findings-resolution: d77d5ef` was preserved.
