# QuantForge Documentation

Project documentation and reference materials for the QuantForge quantitative trading framework.

## Quick Start

| Guide | Description |
|-------|-------------|
| [`PAPER_TRADING_RUNBOOK.md`](PAPER_TRADING_RUNBOOK.md) | Daily/weekly ops, halt responses, troubleshooting |
| [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) | Architecture, components, data flow (includes Phases 0–6 execution pipeline) |
| [`GOVERNANCE_LAYER.md`](GOVERNANCE_LAYER.md) | 7-layer governance: validity, narrative, liquidity, PSI, halt chain |
| [`FEATURES.md`](FEATURES.md) | FeatureContract system, driver atlas, cross-asset isolation, archetype classification |
| [`ARCHITECTURE_FOUNDATIONS.md`](ARCHITECTURE_FOUNDATIONS.md) | Model architecture, labeling, regime classifier, execution pipeline decomposition |
| [`HARDENING_ROADMAP.md`](HARDENING_ROADMAP.md) | Execution physics, extended history, lead-lag, adaptive macro, Phases 0–6 |
| [`SURVIVAL_SIMULATION.md`](SURVIVAL_SIMULATION.md) | Adversarial survival testing, deleveraging feedback |

### Execution Research Framework (Phases 0–6)

| Phase | Layer | Module |
|-------|-------|--------|
| 0 | Frozen Kernel + Labels | `labels/triple_barrier.py` |
| 1 | Entry Quality Engine | `paper_trading/entry_optimizer.py`, `paper_trading/deferred_entry.py` |
| 2 | TP/Exit Geometry | `paper_trading/tp_compiler.py`, `paper_trading/scale_out.py` |
| 3 | Archetype Classification | `features/archetypes.py` |
| 4 | Execution Policy Layer | `paper_trading/execution_policy.py` |
| 5 | Fill Realism Layer | `paper_trading/execution_simulator.py`, `paper_trading/slippage_model.py`, `paper_trading/fill_model.py`, `paper_trading/latency_model.py` |
| 6 | Trade Attribution | `paper_trading/trade_attribution.py` |

## ADRs

Architecture Decision Records in [`adr/`](adr/) — see [`adr/ADR-000-index.md`](adr/ADR-000-index.md) for the full list.

## Conventions

- ADRs follow the standard [Michael Nygard template](https://github.com/joelparkerhenderson/architecture-decision-record)
- All docs are written in Markdown
- `LIVE_CONTRACT.md` at the project root is the immutable system contract
