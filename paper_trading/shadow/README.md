# Shadow Analytics Engine

## Purpose

The shadow engine replays the same market tape as live positions but with
alternative SL/TP parameters. It enables **online counterfactual research**
without side effects — no capital mutation, no governance contamination,
no replayability impact.

## Architecture

```
Live:  DynamicSLTPEngine → PositionManager → trade close (mutates capital)
Shadow: ShadowSLTPEngine → shadow buffer   (zero side effects)
```

Shadow engines consume immutable execution artifacts. They never share mutable
state with the live engine.

## Modules

| Module | Role |
|--------|------|
| `engine.py` | `ShadowSLTPEngine` — counterfactual replay with alternative SL/TP params |
| `actions.py` | `compute_shadow_actions` — drift- and risk-aware shadow decisions |
| `analytics.py` | Shadow analytics aggregation and comparison (live vs shadow) |
| `feedback.py` | Feedback loop ingestion from shadow outcomes |
| `learning.py` | Reinforcement learning integration from shadow replay results |
| `memory.py` | Persistent shadow state across engine restarts |

## Dashboard Integration

- `/shadow/trades.json` — per-trade shadow comparison (MATCH / DIVERGE)
- `/shadow/summary.json` — divergence rate by config label
- Divergence rate bar chart on the Execution workspace
- Shadow Comparison panel (Layer 6) shows live vs shadow R delta

## Key Invariant

Shadow engines never mutate live positions or governance state. All shadow
outcomes are written to the `shadow_trades` table in SQLite.
