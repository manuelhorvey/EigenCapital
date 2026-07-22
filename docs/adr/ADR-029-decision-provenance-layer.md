# ADR-029: Decision Provenance Layer — Immutable Audit Record

**Status:** Accepted
**Date:** 2026-07-22
**Supersedes:** None (new architecture)

## Context

EigenCapital executes trading decisions through a 17-layer governance pipeline (PEK admission, gates, factor constraints, adaptive exit engine, etc.). Each decision depends on a specific combination of market state, model output, portfolio context, and runtime conditions. When investigating unexpected outcomes — a blocked trade, an unusual signal, a drawdown event — operators had no way to reconstruct what the system saw at decision time.

The system also lacks an audit trail for compliance, backtesting comparison, and drift detection. The state store records *what* happened (positions, trades, PnL) but not *why* a particular decision was made.

### Requirements

1. **Immutable** — once captured, provenance records must never be modified
2. **Decision-boundary capture** — records are created at the exact point where a decision is made (after governance, before execution), not retrospectively
3. **Six-context snapshot** — each record captures MarketContext, FeatureContext, ModelContext, PortfolioContext, ExecutionContext (runtime), and DecisionTrace
4. **Passive observer** — provenance capture must never affect trading decisions; failures are logged non-fatally
5. **Versioned** — every record pins the exact config version (git hash + runtime config SHA-256) that produced it
6. **Counterfactual analysis** — operators must be able to simulate "what if" scenarios on captured decisions
7. **Independent of pipeline** — the provenance store, domain models, validator, and counterfactual engine must be usable outside the main trading pipeline

## Decision

Create a **Decision Provenance Layer (DPL)** at `eigencapital/domain/provenance/` with the following components:

### Architecture

```
eigencapital/domain/provenance/
├── __init__.py               # Package init, re-exports
├── decision_id.py             # UUID4 decision ID with lineage tracking
├── market_context.py          # MarketContext (prices, volatility, spreads)
├── feature_context.py         # FeatureContext (feature vector hash, n_features)
├── model_context.py           # ModelContext (probabilities, model hash, calibration)
├── portfolio_context.py       # PortfolioContext (exposure, positions, PEK budget)
├── execution_context.py       # ExecutionContext → renamed runtime (runtime/engine state)
├── decision_trace.py          # DecisionTrace (signal, SL/TP, gates, entry action)
├── decision_provenance.py     # DecisionProvenance (aggregate root with all 6 contexts)
├── provenance_store.py        # SqliteProvenanceStore (SQLite persistence)
├── validator.py               # ProvenanceValidator (8 validation categories)
└── counterfactual.py          # CounterfactualEngine (4 override types)
```

### Design Decisions

#### 1. Domain Model Shape

Each provenance record is a **flat aggregate root** (`DecisionProvenance`) containing six optional context objects:

- **MarketContext** — snapshot prices, spreads, ATR, volatility
- **FeatureContext** — feature vector hash, count, regime label
- **ModelContext** — model probabilities, confidence, hash, calibration
- **PortfolioContext** — gross/net exposure, open positions, PEK budget
- **RuntimeContext** (execution) — total equity, drawdown, halt state, circuit breaker
- **DecisionTrace** — final signal, position size, entry action, gate outcomes

All six contexts are optional so that partial capture (e.g., missing market data for a new asset) does not prevent recording the decision.

#### 2. DecisionID = UUID4 + Lineage

Each record gets a unique UUID4 `decision_id`. Counterfactual records share the same `lineage_id` as their source, linking what-if scenarios back to the original decision. Lineage is a separate UUID4 stored alongside the decision ID — not embedded (e.g., composite key) — for simpler queries and serialization.

#### 3. Storage: SQLite with JSON Columns

- SQLite database with a single `decision_provenance` table
- JSON columns for the six context objects (flexible schema, no migration per context field change)
- Indexed metadata columns: `asset`, `cycle_id`, `decision_timestamp`, `decision_type`, `git_hash`, `config_hash`
- Schema versioned via `_schema_version` table (current version: 1)
- Thread-local connections (same pattern as `_DatabaseStore`)
- Optional TTL pruning via `prune(before)` method and health check via `health()`

#### 4. Capture Point

Provenance is captured inside `EngineOrchestrator._run_phases()` between Phase 3 (portfolio/risk) and Phase 4 (persist/position modification) via `_capture_provenance()`. This is the decision boundary — after all governance and before execution.

The `provenance_store` is injected via the `EngineOrchestrator` constructor (optional; if None, capture is silently skipped).

#### 5. Serialization

Uses the existing `EigenCapitalJSONEncoder` for JSON serialization. All domain objects implement `to_dict()` / `from_dict()` for round-trip fidelity.

#### 6. Git Hash

Read from `.git/HEAD` directly (no subprocess) to avoid subprocess overhead on every capture cycle. Falls back to `"unknown"` if `.git/HEAD` is unavailable.

#### 7. Validator

`ProvenanceValidator` provides 8 validation categories:
- **Identity** — decision_id is a valid UUID4
- **Schema version** — schema version is current
- **Market** — market prices are positive
- **Features** — feature hash is non-empty
- **Model** — probabilities sum to ~1.0
- **Portfolio** — exposure is finite
- **Execution** — equity is non-negative
- **Decision trace** — signal is a known value (BUY/SELL/HOLD)

Strict mode requires all 6 contexts to be present.

#### 8. Counterfactual Engine

`CounterfactualEngine` produces new `DecisionProvenance` records with `decision_type="COUNTERFACTUAL"` and the same `lineage_id`. Four override types:

- **Gate override** — flip a single gate outcome, re-derive trace
- **Probability override** — change model probabilities, re-derive signal
- **Signal override** — force final signal to a specific value
- **SL/TP override** — change stop-loss/take-profit prices

#### 9. CLI & REST

- **CLI**: `scripts/provenance_cli.py` with `recent`, `get`, `stats`, `validate`, `watch`, and `cf` (counterfactual) commands
- **REST**: `/provenance.json` (list), `/provenance/<uuid>.json` (detail), `/provenance/stats.json` (aggregate)
- **Counterfactual REST**: `POST /provenance/counterfactual` (run counterfactual via API)
- Store is lazy-initialized via `get_provenance_store()` in `api/common.py`

#### 10. Prometheus Metrics

Seven metrics in `paper_trading/metrics/provenance_metrics.py`:

- `provenance_capture_total` — counter per asset + signal
- `provenance_capture_errors_total` — counter per asset
- `provenance_store_records` — gauge
- `provenance_store_size_bytes` — gauge
- `provenance_store_healthy` — gauge (1/0)
- `provenance_capture_duration_seconds` — histogram
- `provenance_prune_records_total` — counter

### Testing

60 unit tests in `tests/domain/test_provenance.py` covering:
- All domain object construction and serialization
- SqliteProvenanceStore CRUD, query, maintenance (prune, health, count_by_asset)
- ProvenanceValidator validation categories
- CounterfactualEngine override types

7 integration tests in `tests/engine/test_end_to_end.py` (`TestProvenanceCapture`) verifying:
- Full capture path with mock actors
- Context population across multiple cycles
- Missing attribute resilience
- Post-capture validation

## Consequences

### Positive

- **Full audit trail** — every trading decision is permanently recorded with the complete system state at decision time
- **Counterfactual analysis** — operators can investigate "what if" scenarios on any captured decision
- **Drift detection** — provenance data enables win-rate drift monitoring against breakeven thresholds
- **Compliance** — immutable records satisfy audit requirements
- **Comparative backtesting** — captured decisions can be compared with backtest expectations
- **Zero impact on trading** — passive observer design means capture failures never affect trading decisions

### Negative

- **Storage growth** — each cycle captures 1 record per asset (~22 records/cycle × ~2,880 cycles/day ≈ 63K records/day at 5-second cycles). At ~2KB/record, this is ~125MB/day. TTL/pruning is required for long-running deployments.
- **Latency overhead** — JSON serialization + SQLite write per asset per cycle. Measured at <5ms per record on average hardware.
- **Thread dependency** — `_capture_provenance()` runs inside the engine thread. A slow store write blocks Phase 3→Phase 4 transition.
- **No ADR existed at implementation time** — this ADR is retrospective (written after implementation was complete).

### Risks

- **SQLite write contention** — the thread-local connection pattern means each thread has its own connection; no cross-thread contention, but concurrent writes from multiple threads are serialized by SQLite's file-level locking
- **Database corruption** — no WAL mode configured by default; power loss during write could corrupt the store. Mitigation: database is disposable — it captures trading decisions but is not the system of record for positions or PnL
- **Git hash staleness** — when running from a detached HEAD or during active development, the computed git hash may not match a known commit. Mitigation: the config hash component (SHA-256 of runtime config) provides a secondary version anchor

## Related

- ADR-021: Simulation Snapshot System (complementary — replay vs. provenance)
- ADR-027: Portfolio Execution Kernel (precedes provenance capture)
- ADR-028: Cross-Platform Architecture (provenance store uses platform path resolution)
