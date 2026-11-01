# Remediation Roadmap (Planning Only)

This roadmap is **not executed**. It is a proposed sequence for a separate, approved remediation phase. It deliberately does not change R4, risk limits, broker behaviour, capital, or the stop-loss gate enablement decision.

Estimates assume one engineer familiar with the codebase; they are planning ranges, not commitments.

## Guiding constraints

- Freeze the live path's behaviour while adding observability. Do not combine refactors with behaviour changes.
- Every safety fix lands with a regression test that fails before and passes after.
- No fix may silently relax a limit; if a limit is wrong, change it explicitly in config with a recorded decision.
- Keep `configs/production/config.toml` and code claims in lockstep; delete claims that cannot be enforced.

---

## P0 — Accounting and audit spine (blocks capital increase)

| Order | Work | Findings | Est. |
|---|---|---|---|
| 1 | **Introduce a cycle/decision ID** at the top of `run_cycle`; thread it through signal, intents, orders, fills, reconciliation. Persist it in every state record. | F-03, F-06, F-22 | 2–3 d |
| 2 | **Wire `EventLedger`** into the loop. Emit signal/computed, intent, submitted, fill, rejected, reconciled, health-change events. Assert `get_trade_chain(correlation_id)` returns the full chain. | F-02, F-03 | 3–4 d |
| 3 | **Persist intents before submission** and resolve open intents against the broker on startup before any new order. Add durable client order IDs. | F-03, F-12 | 3–4 d |
| 4 | **Build the internal position ledger from confirmed fills** and use it as `InternalState` in reconciliation. Add tests for broker-only, missing, and quantity-mismatch cases. | F-05 | 3–4 d |
| 5 | **Fix reconciliation persistence**: real monotonic cycle ID, write once per cycle, unify the filename/schema with the dashboard. | F-06 | 1 d |
| 6 | **Equity/capital ledger**: append-only entries; per-cycle broker-vs-ledger delta; daily baseline derived from it; unexplained-delta alert + entry block. | F-01 | 3–5 d |
| 7 | **Make the dashboard read engine truth** for account, risk, health, reconciliation; add staleness TTL and explicit UNKNOWN. | F-14 | 2–3 d |

**Exit criteria:** a restart during an ambiguous send is resolved without duplication; a manual broker position change produces a recorded MISMATCH and HALT; the dashboard shows the same reconciliation record the loop wrote; the equity ledger explains the current baseline.

---

## P1 — Enforce or remove claims; fix statistics

| Order | Work | Findings | Est. |
|---|---|---|---|
| 8 | Enforce `max_absolute_weight_error` as a veto (or delete the config/doc claim with written acceptance). | F-07 | 1 d |
| 9 | Correct stop-loss validation: `None`, non-positive, wrong-side, non-numeric → unprotected/BLOCK; un-xfail tests. Do **not** enable the gate as part of this work. | F-04 | 1–2 d |
| 10 | Call risk gates with the actual planned order count; remove the permissive daily-loss baseline initialization (require RESTORED or refuse). | F-16 | 1–2 d |
| 11 | Correct Holm (forward cumulative max) and BH (backward cumulative min); property tests for monotonicity and bounds. | F-09 | 1 d |
| 12 | Replace PBO with CSCV; unit test with a known matrix. | F-08 | 2–3 d |
| 13 | Re-run affected research verdicts and withdraw/restate claims that depended on F-08/F-09. | F-08, F-09, F-10 | 2–5 d |
| 14 | Fix the forming-bar input: pin to the last closed bar or document/test intraday semantics. | F-11 | 1–2 d |
| 15 | Execution hardening: capability-based filling mode, config-driven deviation, resolve ambiguous sends, partial-fill repair, chase policy. | F-12, F-13 | 3–5 d |
| 16 | Enforce or delete the remaining unconsumed config fields; add a config-consumption test. | F-13 | 1–2 d |
| 17 | Provenance: verify hash on load; align dataset manifest/universe; restore artifacts or withdraw claims. | F-10 | 2–4 d |
| 18 | Dashboard credentials: fail closed in production on missing/default key; remove `?token=`. | F-15 | 1 d |

**Exit criteria:** every documented safety limit has a test proving enforcement; corrected statistics reproduce reference values; research claims match artifacts present in the repo.

---

## P2 — Integrity hardening and governance

| Work | Findings | Est. |
|---|---|---|
| HMAC the audit chain with an externally held key; allocate sequence under the file lock; export head digests off-host. | F-17 | 2–3 d |
| Schema-version every operational state file; readers reject unknown versions. | F-22 | 2 d |
| Make experiment records immutable (content-addressed IDs, append-only supersession). | F-20 | 2–3 d |
| Move simulation executors under tests or gate them at import. | F-21 | 1 d |
| CI hardening: SHA-pin actions, read-only permissions, lockfile/hashes, `pip-audit`, explicit 3.14 decision. | F-19 | 1–2 d |
| Extract the orchestrator from `scripts/r4_rebalance_loop.py`; delete the duplicate rebalance implementation. | TD-01, TD-03 | 5–8 d |
| Improve backtest realism (instrument metadata, risk sizing, intrabar stops, broker costs) or explicitly scope it as relative-only. | F-18 | 5–8 d |

---

## P3 — Hygiene

- Fix stale comments and reconcile documentation with code (F-23).
- Dashboard snapshot cache; document single-worker or use an external limiter (F-24).
- Remove deprecated shims; consolidate alerts for "safety disabled" and "reconciliation not persisted".
- Complete or withdraw the referenced specification documents.

---

## Suggested gates

| Gate | Prerequisite | Decision enabled |
|---|---|---|
| G-A: Audit spine | P0 items 1–7 | Capital increase remains blocked, but the system can *prove* state |
| G-B: Enforcement parity | P1 items 8–18 | `SOUND WITH MATERIAL REMEDIATION REQUIRED` |
| G-C: External validation | G-B + 30 days of clean reconciliation + DR drill + independent review | Capital increase decision |

## What not to do

- Do not merge P0 work with a refactor of the signal or sizing.
- Do not "fix" the weight-error finding by raising the threshold.
- Do not enable the stop-loss gate as a shortcut to closing F-04.
- Do not re-run research and adopt new findings before F-08/F-09 are fixed.
- Do not treat the safety supervisor as a substitute for correct Gate-6 semantics.
