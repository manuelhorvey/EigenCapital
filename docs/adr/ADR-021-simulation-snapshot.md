# ADR-021: Simulation Snapshot System for Deterministic Replay

**Date:** 2026-05-18
**Status:** Accepted

## Context

The paper trading engine runs continuously, accumulating state in memory (trade_log, prob_history, positions, validity states). If a bug is discovered or a configuration change needs validation, there was no way to rewind the engine to a specific past date and replay from that point. The entire simulation had to be restarted from scratch, losing accumulated trade history and state context.

For effective research iteration and post-hoc analysis, the system needed to support:
- Capture full engine state at arbitrary save points
- Replay from any historical date with identical feature and model state
- List available snapshot dates for UI/CLI consumption

## Decision

Create `SimulationStore` in `paper_trading/simulation_snapshot.py` with:

1. **Per-asset snapshots** — `AssetSnapshot` captures position, trade_log, prob_history, validity state, meta-model inference, and feature stability metrics for each asset
2. **Portfolio-level row** — associates the entire asset snapshot set with portfolio value, return, cash buffer, and satellite value at a single timestamp
3. **Parquet persistence** to `data/live/snapshots/simulation_history.parquet` — append-only with deduplication on (timestamp, asset)
4. **Cold state store** — `cold_state.pkl` for non-feature-engineerable data (model pickle paths etc.)
5. **Three load modes:**
   - `load_snapshot(timestamp)` — exact-timestamp lookup
   - `load_snapshot_by_date(date_str)` — latest snapshot on a given date
   - `list_snapshot_dates()` — all unique snapshot timestamps
6. **Triggered by existing save_state()** — no separate cron or scheduler needed

## Alternatives Considered

- **Full-database approach (SQLite):** Overengineered for snapshot storage. Parquet with deduplication is simpler, self-contained, and directly readable by pandas for analysis.
- **Checkpoint entire engine as pickle:** Fragile across code changes. Row-based parquet allows schema evolution and partial loads.
- **Store model pickle inside snapshot:** Model files are large (5-50 MB per asset × 6 assets). External references via cold_state.pkl avoids duplicating into every snapshot row.

## Consequences

- Snapshots are captured at every save_state() call alongside equity history, adding minimal overhead
- Deduplication on (timestamp, asset) keeps the parquet file from growing unboundedly on repeated saves
- Cold state (model pickles) remains as file references, not embedded — model directory must survive for replay
- Parquet format enables SQL-like queries: "what was asset X's position on all Mondays in May?"

## Affected code

- `paper_trading/simulation_snapshot.py` — SimulationStore, AssetSnapshot, PortfolioSnapshot, build_asset_snapshot
- `paper_trading/state_store.py` — snapshot path at data/live/snapshots/
- `paper_trading/engine.py:1160-1230` — snapshot capture in save_state()
- `tests/test_simulation_snapshot.py` — 14 tests
