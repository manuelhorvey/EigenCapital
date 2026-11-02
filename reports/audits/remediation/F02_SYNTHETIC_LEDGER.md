# F-02 — Capital-Event Ledger (Synthetic Fixture Remediation)

**Status:** `VERIFIED WITH LIMITATIONS`
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** pending
**Severity:** Critical · **Phase:** P0
**Date:** 2026-11-01

---

## 1. Finding

`src/eigencapital/production_qual/event_ledger.py` defines an `EventLedger`
(typed, append-only, hash-chained trade lifecycle ledger) but it is not
instantiated or used anywhere in `src/` or `scripts/` outside
`production_qual`. There is no capital-event ledger wired into the live path,
so capital movements cannot be reconstructed for external audit.

## 2. Constraint and approach

Per the mandated safety constraints:

- The ledger is **not wired into any live or paper-trading runtime path**.
- No broker APIs, account snapshots, credentials, or production state are
  used.
- All fixtures are synthetic and test-only.
- No historical evidence is fabricated; no claim is made that synthetic
  results reconcile actual broker equity.
- R4 strategy invariants, broker behaviour, production risk limits, capital,
  and leverage are unchanged.

Because live-path wiring is prohibited, this remediation unit implements and
verifies **only** the synthetic fixture-ledger plumbing against the existing
`EventLedger` class. The live-path wiring portion of F-02 remains
**BLOCKED — NOT AUTHORIZED**.

## 3. Files changed

- `tests/unit/live/test_f02_ledger_fixture.py` (new) — synthetic fixture tests
  exercising `EventLedger` append, hash computation, correlation-chain
  reconstruction (`get_trade_chain`), duplicate handling, fail-closed input
  validation, flush/persistence, and deterministic replay.

## 4. Verification executed

| Command | Result |
|---|---|
| `pytest tests/unit/live/test_f02_ledger_fixture.py -q` | **14 passed** |
| `pytest tests/unit/live tests/unit/dashboard tests/unit/live/test_durable_audit.py -q` | **189 passed** |
| Full suite `tests/unit tests/property tests/integration tests/failure_injection` | **3762 passed, 2 skipped** |

New coverage (14 tests):

- `TestSyntheticLedgerAppendAndHash` — appended event has deterministic,
  self-consistent `event_hash`; hash changes when payload changes.
- `TestSyntheticLedgerCorrelationChain` — `get_trade_chain(correlation_id)`
  returns the full 4-event cycle, ordered by timestamp, all sharing the
  correlation ID.
- `TestSyntheticLedgerDuplicateHandling` — duplicate event appends produce
  distinct event IDs with the same correlation ID (caller is responsible for
  deduplication).
- `TestSyntheticLedgerFailClosed` — invalid `event_type`, empty `account_id`,
  empty `tier`, empty `campaign_id` all raise `ValueError`.
- `TestSyntheticLedgerPersistenceAndReplay` — flush persists events to JSONL;
  re-reading yields the same events in order; subsequent flushes append to new
  batch files without overwriting.
- `TestSyntheticLedgerNoLivePathMutation` — no `mt5`/`MetaTrader` imports or
  API usage in `event_ledger.py`; ledger writes only under the test temp
  directory; pure Python + file I/O.
- `TestSyntheticLedgerDeterministicReplay` — appending the same fixture twice
  produces persisted records with matching correlation_id/payload (event_id and
  timestamp differ per-append as expected).

## 5. Limitations (noted, not hidden)

- **Live-path wiring is not implemented.** `EventLedger` is not instantiated
  in the live loop. F-02 acceptance criteria that require live-cycle
  integration (per-cycle expected equity comparison, unexplained-delta
  BLOCKED, startup baseline restore, CORRUPTED fail-closed) remain blocked.
- **Schema versioning, currency/signed-amount/balance fields, prev_hash
  chaining, and sequential event IDs under file lock are not present in
  `EventLedger`.** These are financial-accounting / ledger-design decisions
  that are explicitly **not made here**; they remain pending formal decision.
- The hash chain used by `EventLedger` is a per-event `event_hash` (SHA-256
  over event data), not a `prev_hash`-chained ledger. Converting to a
  hash-chained ledger is a formal decision, not made here.
- No synthetic result is claimed to reconcile actual broker equity.

## 6. What this does not establish

- Independent review has not occurred.
- No live trading, broker integration, or production state was touched.
- Capital readiness remains **NOT READY — CAPITAL INCREASE NOT AUTHORIZED**.
- The ledger is not wired into any live or paper-trading runtime path.

## 7. Closure decision

`VERIFIED WITH LIMITATIONS`. Not `CLOSED`. Remaining: independent review;
live-path wiring remains blocked pending formal authorization; schema
versioning / hash-chaining / currency-amount fields remain pending formal
decision.
