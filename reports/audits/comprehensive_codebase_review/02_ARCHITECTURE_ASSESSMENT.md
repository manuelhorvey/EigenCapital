# Architecture Assessment

## System shape

Python package under `src/eigencapital` plus operational `scripts/`, a FastAPI + React dashboard, and research code shipped separately from the installed package.

```
configs/                     production + environment TOML
scripts/                     OPERATIONAL ENTRY POINTS (live loop, supervisor, dashboard, monitor)
src/eigencapital/
  core/                      contracts, data_quality, data_truth, rebalance policy, events
  data/                      catalogue, loaders, normalization, storage, validation
  features/                  feature engineering
  strategies/                strategy interfaces
  backtest/                  clock (look-ahead guard), engine, accounting
  execution/                 broker abstraction, events, trading_provider
  live/                      risk, enforcement, supervisor, watchdog, durable_audit,
                             catastrophic_protection, campaign, daily_loss, reconciliation glue
  reconciliation/            deterministic broker↔internal comparison engine
  analytics/validation/      DSR, PBO, multiple testing, walk-forward
  research/                  alpha, intraday campaigns, monte carlo (not installed with package)
  production_qual/           qualification, prefunding audit, event_ledger, capital boundaries
  fidelity/ micro_live/ shadow/   promotion-path simulation layers
  dashboard/                 api, schemas, services, streaming
tests/                       unit, property, integration, failure_injection, simulation
```

## Strengths

- **Explicit layering intent.** Core contracts are separated from research; `live/rebalance_policy` was split into `core/rebalance.py` specifically so research does not cross the live boundary.
- **Frozen-signal discipline.** R4 constants are centralized and guarded by a dedicated fidelity test rather than by convention.
- **Operational scripts are thin-ish entry points** relative to library code, and the live loop refuses to start twice.
- **Deterministic, hashable artifacts.** Config fingerprinting, build identity, provenance helpers exist and are used by dashboard/qualification.
- **Failure semantics are mostly fail-closed**: corrupted risk audit → block; HALT reconciliation → stop trading; unknown regime → no trade.

## Structural weaknesses

### 1. The live loop is a 3,329-line god module
`scripts/r4_rebalance_loop.py` contains signal computation, sizing, order generation, execution, reconciliation, persistence, safety-supervisor interaction, and CLI. Consequences observed:

- duplicated order-request builders with **different hard-coded deviations** (`10` at line 995, `20` at line 2564);
- stale inline comments contradicting the code (`# 1500` vs `$5,000`; `# 8` vs `20`);
- business logic that cannot be unit-tested without importing the script;
- config fields that exist but are consumed nowhere.

`src/eigencapital/core/rebalance.py` duplicates rebalance logic in a testable form, so two implementations of the same policy now exist.

### 2. Three parallel audit/state mechanisms, none authoritative
| Mechanism | Location | Wired to live loop? |
|---|---|---|
| `AuditLog` (JSONL events) | `execution/events.py` | **No** |
| `DurableAudit` (hash chain + mirror) | `live/durable_audit.py` | **Only `live/campaign.py`** |
| `EventLedger` (typed, hash-chained, correlation IDs) | `production_qual/event_ledger.py` | **No callers outside package** |

The loop instead writes ad-hoc `decisions.jsonl` dictionaries and attempts a reconciliation JSONL that is never emitted. This is the root cause of P0-2/P0-3.

### 3. State is file-sprawl, not a state machine
`reports/r4_loop/` holds at least `runtime_state.json`, `risk_state.json`, `loop_health.json`, `supervisor_state.json`, `decisions.jsonl`, `weight_deviation.jsonl`, `reconciliation_state.jsonl`, `reconciliation_state.json` (dashboard), plus baselines. Ownership is partly documented (single-writer rule) but naming is inconsistent (`.json` vs `.jsonl`, singular vs plural), and no file carries an explicit schema version. Two consumers already disagree on filenames.

### 4. No persistence abstraction
Every component reads/writes JSON with its own `open()`/`json.load` and its own error handling. There is no repository layer, no schema validation on read, no atomicity contract except where individually implemented (`DurableAudit`, `supervisor`). Corruption handling is therefore per-call-site and inconsistent.

### 5. Dashboard service is a 60 KB procedural module
`dashboard/services/dashboard_state.py` reads ~15 files per request, contains business semantics (health, reconciliation, daily loss), and mixes freshness policy with presentation. It is the single largest file in the package and the main correctness risk on the observability side.

### 6. Documentation claims overstate implementation
- `configs/production/config.toml` documents `max_absolute_weight_error` as an execution veto; the code only records it.
- `ExecutionConfig` fields (`max_chase_attempts`, `max_age_seconds`, `max_cumulative_slippage_bps`, `max_order_frequency`) have no consumer in the live loop.
- `rebalance_frequency` is documented as intent, not enforced.
- No `SYSTEM_SPECIFICATION.md` or `domain_contracts.md` exists, despite being referenced as governing documents.

## Architecture risk rating

| Dimension | Rating | Note |
|---|---|---|
| Modularity | Medium | Good directory intent, undermined by god script |
| Testability | Medium | Library code is testable; live path largely is not |
| State integrity | Low–Medium | No schemas/versioning; three audit mechanisms |
| Observability truth | Low | See `05_EXECUTION_OPERATIONAL_SAFETY.md` |
| Change safety | Medium | Lint/type/tests strong; frozen constants guarded |

## Recommended target shape (planning only)

1. `core/` — pure domain (signal, policy, sizing, risk rules).
2. `live/engine.py` — orchestration with injected broker, ledger, clock, and state store.
3. `persistence/` — one owner per state file, schema-versioned, atomic writes, read validation.
4. `audit/` — a single append-only, hash-chained, keyed event log used by every live decision.
5. `scripts/r4_rebalance_loop.py` — CLI only (<300 lines).
