# EigenCapital

Asset-agnostic quantitative research and execution platform.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![Version](https://img.shields.io/badge/version-0.1.0--pre--alpha-orange)](#status)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Runtime deps](https://img.shields.io/badge/core%20runtime%20deps-0-success)](#design-principles)

> **Status: Pre-Alpha.** The core is under active development ahead of the initial
> release. Public APIs are not yet stable and may change without notice.

EigenCapital separates *deciding* from *doing*. Strategies express intent; the
portfolio layer allocates; risk adjudicates; execution acts; reconciliation and
monitoring verify. Each stage communicates through explicit, immutable decision
objects — never through inferred state — so every production outcome can be
reconstructed and audited end-to-end.

## Architecture

A strict, acyclic dependency graph. Dependencies point upward only; no layer may
import a layer above it.

```
                    CORE (models, contracts)
                       ▲
                       │
                      DATA
                       │
                   FEATURES
                       │
                  STRATEGIES
                       │
                  PORTFOLIO
                       │
                     RISK
                       │
                 EXECUTION
                       │
               RECONCILIATION
                       │
                  MONITORING
```

| Layer | Responsibility | Status |
|---|---|---|
| `core` | Domain models, invariants, contracts, events | Implemented |
| `data` | Ingestion, normalization, instrument catalogue | Scaffolded |
| `features` | Signal computation over normalized data | Scaffolded |
| `strategies` | Alpha generation → `StrategyIntent` | Scaffolded |
| `portfolio` | Intent aggregation → `PortfolioTarget` | Scaffolded |
| `risk` | Limit enforcement → `RiskDecision` | Scaffolded |
| `execution` | `ApprovedTarget` → order plans → live orders | Scaffolded |
| `reconciliation` | Broker/fund state vs. internal books | Scaffolded |
| `monitoring` | Health, drift, alerting | Scaffolded |
| `backtest`, `analytics` | Research and evaluation tooling | Scaffolded |

## Decision Pipeline

```
Market Data → Strategy → StrategyIntent → Portfolio → PortfolioTarget
→ EigenRisk → RiskDecision → ApprovedTarget → OrderPlan → Order
→ Fill → Position → Reconciliation → AccountSnapshot
```

Every transition is explicit. No downstream subsystem may infer upstream intent
from downstream state when the upstream decision object should exist. This rule
is what makes the system auditable: given any fill, you can walk backward through
`Order`, `OrderPlan`, `ApprovedTarget`, `RiskDecision`, `PortfolioTarget`, and
`StrategyIntent` to recover exactly *why* a trade happened.

## Design Principles

1. **Explicit decisions over inferred state.** Every pipeline transition produces
   a named, typed decision object.
2. **Invariants at construction.** Domain objects validate themselves in
   `__post_init__`; an invalid object cannot exist.
3. **Immutability by default.** All domain models are frozen dataclasses.
4. **Canonical serialization.** Deterministic `to_dict` / `from_dict` with sorted
   keys and stable hashing (`canonical_serialization`) for provenance and audit trails.
5. **Zero runtime dependencies in core.** The domain core is pure standard
   library; heavy numerics stay optional (`research` extra) and out of the kernel.
6. **Uniqueness enforced system-wide.** E.g., `instrument_id` is registered once
   and duplicates are rejected at construction.

## Domain Models

Implemented in [`src/eigencapital/core/models/`](src/eigencapital/core/models/) — all frozen dataclasses
with invariant validation and deterministic serialization.

### Market Data

| Model | Purpose |
|---|---|
| `Instrument` | Immutable tradable-instrument metadata; globally unique `instrument_id` |
| `Bar` / `BarInterval` | Normalized OHLCV bars at explicit intervals |
| `MarketSnapshot` | Point-in-time market state for decision inputs |

### Decision Chain

| Model | Purpose |
|---|---|
| `StrategyIntent` (+ `Horizon`) | A strategy's desired exposure change and horizon |
| `PortfolioTarget` | Portfolio-level allocation target derived from intents |
| `RiskCheckResult` / `RiskDecision` | Risk gate evaluation and verdict |
| `ApprovedTarget` | Target cleared for execution |
| `OrderPlan` (+ `Urgency`) | Execution plan: slicing, urgency, constraints |
| `Order` / `OrderSide` | Order instructions issued to a venue |
| `Fill` | Execution report for (part of) an order |
| `OrderLifecycle` | Order state machine from submission to terminal state |
| `Position` | Resulting holding state after fills |

### Audit & Research

| Model | Purpose |
|---|---|
| `DecisionSnapshot` | Full provenance record of one decision cycle |
| `Experiment` / `ExperimentStatus` | Research experiment tracking |
| `errors.py` | Exception hierarchy (`EigenCapitalError`, `InvariantViolation`, ...) |
| `canonical_serialization.py` | Deterministic serialization and hashing utilities |

## Project Layout

```
eigencapital/
├── src/eigencapital/          # Source (src-layout)
│   ├── core/
│   │   ├── models/            # Domain models (implemented)
│   │   ├── interfaces/        # Layer contracts (planned)
│   │   └── events/            # Event definitions (planned)
│   └── data, features, strategies, portfolio, risk,
│       execution, reconciliation, monitoring,
│       backtest, analytics    # Layer packages (scaffolded)
├── tests/
│   ├── unit/                  # Unit tests per model/layer
│   ├── property/              # Property-based tests (invariants hold universally)
│   ├── integration/           # Cross-layer contract tests
│   ├── simulation/            # End-to-end simulated runs
│   └── failure_injection/     # Fault-tolerance scenarios
├── configs/
│   ├── development/  paper/  production/  research/
├── data/
│   ├── raw/  normalized/  features/  metadata/
├── docs/
│   ├── architecture/  operations/  risk/  research/
├── research/
│   ├── hypotheses/  experiments/  notebooks/  reports/
├── scripts/
├── .github/workflows/         # CI (planned)
├── Makefile
└── pyproject.toml
```

## Getting Started

**Requirements:** Python 3.11+

```bash
# Clone
git clone <repo-url> && cd eigencapital

# Install with dev dependencies (editable install)
make dev

# Run the full test suite
make test

# Unit tests only
make test-unit

# Property-based tests only
make test-property

# Lint and type-check
make lint        # ruff
make typecheck   # mypy

# See all targets
make help
```

If you prefer not to install, run tests against the source tree directly:

```bash
PYTHONPATH=src python -m pytest tests/
```

## Configuration

Copy `.env.example` to `.env`. Key variables:

| Variable | Description | Default |
|---|---|---|
| `EIGENCAPITAL_ENV` | Execution context: `PAPER` \| `LIVE` \| `BACKTEST` | `development` |
| `BROKER_API_KEY` / `BROKER_API_SECRET` | Broker credentials (Phase 2+) | unset |
| `BROKER_PAPER` | Route to broker paper endpoint | `true` |
| `DATA_PROVIDER` / `DATA_API_KEY` | Market data source (Phase 1B+) | unset |
| `MAX_LEVERAGE` | Portfolio leverage cap | `2.0` |
| `MAX_DRAWDOWN` | Max drawdown cap | `0.10` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

Never commit `.env` or real credentials. Environment loading is enforced from
Phase 1B onward; until then these values document the target contract.

## Testing Strategy

Tests mirror the dependency graph: lower layers are tested exhaustively before
upper layers are trusted on top of them.

| Suite | Scope | Command |
|---|---|---|
| Unit (`tests/unit/`) | Model invariants, edge cases, error paths | `make test-unit` |
| Property (`tests/property/`) | Invariants hold for arbitrary valid inputs | `make test-property` |
| Integration (`tests/integration/`) | Cross-layer contracts | planned |
| Simulation (`tests/simulation/`) | Full-pipeline behavior | planned |
| Failure injection (`tests/failure_injection/`) | Fault tolerance and recovery | planned |

Coverage is configured with a minimum gate of 80% (`pyproject.toml`).

## Roadmap

- [x] **Phase 1A** — Core domain models, invariants, canonical serialization *(current)*
- [ ] **Phase 1B** — Instrument catalogue + data ingestion & normalization
- [ ] **Phase 2** — Features, strategies, portfolio construction
- [ ] **Phase 3** — Risk engine, execution, broker adapters (paper first)
- [ ] **Phase 4** — Reconciliation, monitoring, operations hardening
- [ ] **Phase 5** — Backtesting and research workbench

## Contributing

This project is pre-release and the architecture is still being set in stone.
Before opening PRs:

1. Read the architecture section above — respect the dependency graph.
2. New domain models must enforce their invariants in `__post_init__`.
3. Every model ships with unit tests; invariant-critical logic warrants
   property-based tests.
4. Run `make lint typecheck test` locally before submitting.

## License

[MIT](LICENSE) — see [LICENSE](LICENSE).
