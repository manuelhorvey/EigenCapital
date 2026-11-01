# P0 F-01 / F-02 — Investigation and Acceptance Criteria

**Status:** `INVESTIGATION COMPLETE — ACCEPTANCE CRITERIA PROPOSED; NOT IMPLEMENTED`
**Branch:** `audit/p0-remediation-001`
**Base:** `250f3cb` (merge of PR #1; contains `6a7e77f` and `b8ef53c`)
**Findings:** F-01 (no independent equity reconciliation), F-02 (capital-event ledger not wired)
**Date:** 2026-11-01

This commit contains **investigation and proposed criteria only**. No source, configuration, risk limit, broker behaviour, R4 constant, or capital state was changed. P0-1 remains `BLOCKED — BROKER STATEMENT REQUIRED`.

---

## 1. Purpose

Define what must be true before F-01 and F-02 can be implemented and accepted, and record what the current evidence does and does not establish.

The deposit hypothesis for the 2026-09-26 → 2026-10-29 equity path is **not confirmed**. It is recorded as a hypothesis to be tested against broker evidence, not as a finding.

## 2. Evidence base

| Source | Contents | Limitation |
|---|---|---|
| `reports/r4_loop/portfolio_analytics.jsonl` | 65 equity/position snapshots, 2026-09-26T23:34:56Z → 2026-10-29T13:31:40Z | Sparse, no unrealized P&L, no transaction references; gitignored |
| `reports/r4_loop/runtime_state.json` | `daily_start=5107.83`, `daily_loss.baseline_equity=18177.0`, `peak_equity=18176.81` | Same file carries two starting-equity notions |
| `reports/r4_loop/last_equity.json` | `equity=5117.15` at 2026-09-27T22:15:57Z | Stale relative to the closing window |
| `reports/audits/EC_AUDIT_009_P0_1_EQUITY_RECONCILIATION.md` | P0-1 attempt: `EXIT 2`, statement absent | No broker statement/deal history in the repository |
| `scripts/audit/equity_reconciliation.py` | Read-only reconciliation tool, 9 passing tests | Diagnostic only; not wired to the live loop |

Repository search found no broker statement, deal-history export, deposit/withdrawal record, capital ledger, or transaction log. `reports/r4_loop/` is gitignored, so these artefacts have no git history. The pre-existing stash `stash@{0}` was left untouched.

## 3. Confirmed observations

### 3.1 Series

- 65 snapshots, 64 consecutive steps.
- Opening: **$5,107.83** at `2026-09-26T23:34:56Z`.
- Closing: **$18,176.81** at `2026-10-29T13:31:40Z`.
- Net change: **+$13,068.98**.

### 3.2 Material jumps at the 10% threshold

| # | Interval | Equity | Change | Positions | Gross notional | Leverage |
|---|---|---|---|---|---|---|
| 1 | 09-28 06:27:56 → 09-28 22:16:25 | 5,348.58 → 7,432.04 | **+$2,083.46 (+38.95%)** | 20 → 18 | 0.00 → 27,811.16 | 0.00 → 3.74 |
| 2 | 09-30 12:26:21 → 09-30 22:00:40 | 7,234.28 → 11,343.81 | **+$4,109.53 (+56.81%)** | 18 → 18 | 28,033.78 → 27,874.63 | 3.88 → 2.46 |
| 3 | 10-07 23:26:57 → 10-12 02:50:46 | 11,416.14 → 15,325.00 | **+$3,908.86 (+34.24%)** | 19 → 0 | 29,724.05 → 0.00 | 2.60 → 0.00 |
| 4 | 10-27 00:09:14 → 10-29 13:31:40 | 16,153.52 → 18,176.81 | **+$2,023.29 (+12.53%)** | 20 → 20 | 33,403.34 → 32,598.37 | 2.07 → 1.79 |

Sum of the four jumps: **$12,125.14**. The remaining `$943.84` is spread across the other 60 steps.

Jumps 1, 2 and 3 exceed 15%; jump 4 does not. The frozen gate's "three jumps" screen therefore misses a material fourth event, consistent with `EC_AUDIT_009_P0_1_EQUITY_RECONCILIATION.md` §4.1.

### 3.3 What the series suggests — and does not establish

- In jumps 2 and 4, gross notional is approximately unchanged while equity rises, so leverage falls (`3.88 → 2.46`, `2.07 → 1.79`). This is **consistent with** a cash inflow followed by no immediate rebalance, but not diagnostic: P&L also leaves notional unchanged.
- Jump 3 ends with zero positions and zero gross exposure. It is consistent with a profitable flattening, a stop-out, a withdrawal, or a combination; the snapshot cannot distinguish these.
- Jump 1's "before" record reports 20 positions and `gross_exposure = 0.0`, an internally inconsistent snapshot. That record cannot be used as a leverage baseline.
- Snapshot spacing reaches ~4.2 days (2026-10-07 → 2026-10-12), so an intra-interval sequence of flows and trades could be hidden inside a single step.

**Conclusion:** the snapshots are not cash evidence. No classification (deposit, withdrawal, P&L, correction) is asserted until a broker statement supports it.

### 3.4 Instrumentation state

- `EventLedger` (`src/eigencapital/production_qual/event_ledger.py`) has no caller in `scripts/` or the live loop.
- `DurableAudit` is used only by `campaign.py`.
- No capital-event or equity-history artifact exists in `reports/r4_loop/`.
- `runtime_state.json` simultaneously carries `daily_start = 5107.83` and `daily_loss.baseline_equity = 18177.0`.

## 4. Hypothesis register

| Hypothesis | Status | Evidence needed to confirm | Evidence needed to refute |
|---|---|---|---|
| H1: one or more deposits explain the jumps | **UNCONFIRMED** | Broker statement rows with type `deposit`, timestamps inside the intervals, matching amounts/balances | Statement covering full window with no matching deposit |
| H2: realized trading P&L explains the jumps | **UNCONFIRMED** | Deal history with realized P&L and fees/swaps for the intervals | P&L totals materially below the jumps |
| H3: withdrawals or corrections offset part of the change | **UNCONFIRMED** | Withdrawal/adjustment/credit rows | Statement with no such rows |
| H4: snapshot or accounting error contributes | **POSSIBLE** | Reconciliation of statement balances to snapshot equity at matched timestamps | Snapshot equity matches statement at every anchor |

Multiple hypotheses may hold simultaneously. Acceptance requires every step to be classified, not a single explanation for the total.

## 5. F-01 acceptance criteria (proposed)

### Evidence criteria (blocking)

1. A broker statement / deal-history export covering `2026-09-26T00:00:00Z` through `2026-10-29T23:59:59Z`, in USD, with unique broker references and timezone-aware timestamps.
2. The statement is stored outside the repository or at a documented gitignored path; its SHA-256 is recorded in the acceptance report.
3. Required fields per transaction: `timestamp`, `type`, `amount`, `reference`, `currency`; `balance_after` and `equity_after` where available. Types: `deposit`, `withdrawal`, `credit`, `adjustment`, `realized_pnl`, `floating_pnl`, `fee`, `swap`.
4. The statement is not synthesized, transformed, or normalized except for documented column mapping; the raw file hash is preserved.

### Reconciliation criteria (blocking)

5. The exact command exits `0`:
   `python scripts/audit/equity_reconciliation.py --start 2026-09-26 --end 2026-10-29 --statement <path>`
6. `unexplained_steps == 0` and `unexplained_jumps == 0`.
7. `abs(closing - (opening + statement_delta)) < 0.01` USD.
8. Every consecutive step is classified, not only the four >10% jumps; all three >15% jumps and the 12.53% jump carry a classification and an evidence reference.
9. Classification is stored with the report (JSON) and includes the evidence reference and source hash.

### Implementation criteria (after evidence acceptance)

10. The live loop writes a per-cycle equity record and compares broker equity to the ledger's expected equity.
11. An unexplained delta above tolerance blocks new entries and raises an alert; it does not silently update the baseline.
12. The daily-loss baseline is derived from the ledger and is immutable within a trading day; restart cannot re-initialise it from current equity.
13. `portfolio_analytics.jsonl` is explicitly treated as analytics, never as a cash ledger.

## 6. F-02 acceptance criteria (proposed)

### Ledger

1. One typed, append-only, schema-versioned capital ledger; event types match §5.3.
2. Each entry carries: UTC timestamp, currency, signed amount, broker reference, post-event balance/equity (when available), source hash, and a correlation ID.
3. Hash-chained with `prev_hash`; mirror copy written atomically; `fsync` on append. A keyed MAC is required, or the unkeyed-chain limitation is explicitly accepted in writing (see F-17).
4. Unknown event types, non-USD currency, malformed rows, and missing references fail closed.
5. Sequence/event IDs are allocated under the existing file lock; replay is deterministic.

### Wiring and control

6. The live loop instantiates the ledger and emits capital events; `get_trade_chain(correlation_id)` returns the full chain for a cycle.
7. Per-cycle expected equity = previous expected equity + classified flows + realized P&L; broker equity is compared to it each cycle.
8. Unexplained per-cycle delta above tolerance → `BLOCKED`/alert, not a baseline update.
9. Startup replays the ledger to restore the daily baseline; `CORRUPTED` fails closed and refuses to trade.
10. No automatic baseline initialisation from current equity on a clean-start path once a ledger exists.

### Backfill

11. The 2026-09-26 → 2026-10-29 window is backfilled **only** from the accepted broker statement, with an immutable import record (source hash, row count, import timestamp).
12. Backfilled entries are marked as imported (not live-captured) and are not counted as new capital events.
13. The backfill result reproduces the F-01 acceptance residual within `$0.01`.

### Tests

14. Append/replay determinism; tamper detection; duplicate/restart idempotency; unknown-type rejection; currency mismatch; unexplained-delta block; corrupted-ledger fail-closed.
15. A regression test asserts the live loop constructs and appends to the ledger (wiring, not just the class).

## 7. Dependencies and decision required

**Hard dependency:** the broker statement. Without it, F-01 cannot pass and F-02 backfill cannot be accepted. Snapshot-derived inference is explicitly rejected as evidence.

Decision needed before implementation:

- Provide the MT5 statement/deal-history export (preferred), **or**
- Authorise a documented alternative source and state its evidentiary weight, **or**
- Defer F-01/F-02 acceptance and implement only the F-02 plumbing against fixtures, with acceptance still blocked.

## 8. Explicit non-actions

- No deposit, withdrawal, or P&L classification was assumed.
- No baseline, risk limit, config, R4, broker, or capital state was changed.
- No live loop, broker, or dashboard process was started or modified.
- The pre-existing stash was preserved.

## 9. Reproduction

```bash
# Material jumps in the snapshot series
python - <<'PY'
import json
rows=[json.loads(l) for l in open('reports/r4_loop/portfolio_analytics.jsonl') if l.strip()]
rows.sort(key=lambda r: r['timestamp'])
for a,b in zip(rows,rows[1:]):
    pct=(b['equity']/a['equity']-1)*100
    if abs(pct)>=10:
        print(a['timestamp'], '->', b['timestamp'], f"{a['equity']:.2f} -> {b['equity']:.2f}", f"{pct:+.2f}%",
              f"pos {a['position_count']}->{b['position_count']}",
              f"gross {a['gross_exposure']:.2f}->{b['gross_exposure']:.2f}")
PY

# P0-1 acceptance attempt (blocked until a statement exists)
python scripts/audit/equity_reconciliation.py \
  --start 2026-09-26 --end 2026-10-29 \
  --statement <broker_statement.csv>
```

## 10. Status after this commit

| Item | Status |
|---|---|
| F-01 | Open; P0-1 `BLOCKED — BROKER STATEMENT REQUIRED` |
| F-02 | Open; ledger design and criteria proposed, not implemented |
| Capital increase | **NOT AUTHORIZED** |
| Code/config/R4/risk changes | None |
