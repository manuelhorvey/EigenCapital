# EigenCapital

Asset-agnostic quantitative research and execution platform.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![Version](https://img.shields.io/badge/version-0.1.0-orange)](#status)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Runtime deps](https://img.shields.io/badge/core%20runtime%20deps-0-success)](#design-principles)
[![Tests](https://img.shields.io/badge/tests-1%2C267%20passing-brightgreen)](#testing-strategy)

> **Status: Pre-Alpha.** Phases 1A–1T are complete: research-to-paper fidelity
> passes all gates (`paper_fidelity_pass`, 7/7), the system is shadow-qualified,
> and a micro-live runner operates against a real MT5 broker under strict
> capital limits. EigenCapital is **not** cleared for unrestricted live trading;
> every promotion step requires an explicit evidence-based verdict.

EigenCapital separates *deciding* from *doing*. Strategies express intent; the
portfolio layer allocates; risk adjudicates; execution acts; reconciliation and
monitoring verify. Each stage communicates through explicit, immutable decision
objects — never through inferred state — so every production outcome can be
reconstructed and audited end-to-end.

The same discipline governs research: claims enter as falsifiable hypotheses,
survive a hostile validation pipeline (or don't), and only then may cross the
fidelity ladder toward real capital. Verdicts are evidence-based and fail-closed:
the evidence gate can return `INCONCLUSIVE`, never an unearned pass.

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
| `core` | Domain models, invariants, contracts, events | ✅ Implemented |
| `data` | Instrument catalogue, loaders (CSV, MT5), normalization, OHLC/temporal validation | ✅ Implemented |
| `features` | Feature library (base, momentum, mean-reversion), registry, pipeline, provenance | ✅ Implemented |
| `strategies` | Strategy contract, registry; trend strategy | ✅ Implemented |
| `portfolio` | Intent aggregation → `PortfolioTarget`; allocation research | ✅ Implemented |
| `risk` | EigenRisk engine, policy, account checks | ✅ Implemented |
| `execution` | Paper broker, account, position manager, events, reconciliation | ✅ Implemented |
| `reconciliation` | Broker/fund state vs. internal books | 🟡 Partial (execution layer) |
| `monitoring` | Health, drift, alerting | ⬜ Scaffolded |

| Subsystem | Responsibility | Status |
|---|---|---|
| `backtest` | Deterministic engine, clock, accounting (no look-ahead) | ✅ Implemented |
| `analytics` | Canonical metrics + statistical validation suite | ✅ Implemented |
| `research` | Hypothesis library, campaigns (R2–R4), provenance, cost model, combination | ✅ Implemented |
| `stress` | Adversarial scenario engine | ✅ Implemented |
| `fidelity` | R4 replay, research↔paper parity, forward paper campaigns, fidelity gates | ✅ Implemented |
| `shadow` | Fail-closed shadow-mode live boundary | ✅ Implemented |
| `live` / `paper` | Controlled live/paper boundaries, broker adapters, qualification | ✅ Implemented |
| `production` | Readiness audits, fingerprinting, execution evidence, security | ✅ Implemented |
| `micro_live` | Micro-live qualification framework + real-broker runner | ✅ Implemented |
| `production_qual` | Scaling qualification from micro-live to larger capital | 🚧 Phase 1U (in progress) |

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
7. **No look-ahead.** A signal at time *t* uses only information available at
   *t* — see [RESEARCH_ENGINE_CONTRACT.md](docs/RESEARCH_ENGINE_CONTRACT.md).
8. **Falsification-first.** Evidence gates default to rejection
   (`MISSING`/`INCONCLUSIVE`); nothing passes by implication.
9. **Fail-closed boundaries.** Shadow/live boundaries make unauthorized real-money
   execution impossible by default.

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
| `TrialMetadata` | Multi-trial accounting (group id, selection method, ...) |
| `errors.py` | Exception hierarchy (`EigenCapitalError`, `InvariantViolation`, ...) |
| `canonical_serialization.py` | Deterministic serialization and hashing utilities |

## Research & Qualification Pipeline

Research and deployment follow one continuous, gated pipeline:

```
Hypothesis → Backtest (contract-bound) → Statistical Validation → Stress
→ Alpha Campaign → Freeze → Replay Parity → Forward Paper → Shadow
→ Micro-Live → Production Qualification
```

- **Hypotheses are not strategies.** [29 pre-registered hypotheses](research/hypotheses/README.md)
  across ten families (momentum, mean reversion, trend, volatility, stat-arb,
  factor, cross-sectional, ML, breakout, alternative data) each carry mandatory
  economic rationale and falsification criteria.
- **Hostile validation** ([`analytics/validation/`](src/eigencapital/analytics/validation/)):
  purged + embargoed walk-forward, IID/block bootstrap, permutation tests,
  multiple-testing corrections (Bonferroni, Holm, BH/FDR), deflated Sharpe
  ratio (Bailey & Prado), PBO, parameter-sensitivity plateaus, cost breakeven
  stress, regime conditioning, universe perturbation, temporal stability,
  Alphalens-style factor evaluation (IC / quantile spreads / turnover), and a
  falsification-first evidence gate.
- **Information-driven bars**: volume and notional bars with VWAP + trade
  counts (`data/normalization/information_bars.py`); storage policy per book
  guidance — HDF5 numeric, Parquet mixed, CSV fallback (`data/storage/`);
  survivorship-aware universe membership with point-in-time queries
  (`data/catalogue/membership.py`).
- **Adversarial stress testing** per [STRESS_TEST_CONTRACT.md](docs/STRESS_TEST_CONTRACT.md):
  perturbation scenarios must produce defined behavior and forbid undefined behavior.
- **Alpha campaigns** executed against real MT5 data produced the
  [Alpha Research Map](docs/research/ALPHA_RESEARCH_MAP_1Q_FULL.md); campaigns R2–R4
  are pre-registered risk transformations with frozen manifests.
- **Fidelity ladder**: frozen-config deterministic replay, research↔paper parity
  (100% effective match rate on R4), forward paper campaign (`paper_fidelity_pass`,
  7/7 gates), shadow execution (`SHADOW_QUALIFIED`), then micro-live with minimal
  capital on a real broker.

## Project Layout

```
eigencapital/
├── src/eigencapital/
│   ├── core/            # Domain models, contracts, events
│   ├── data/            # Catalogue, loaders (CSV, MT5), normalization, validation
│   ├── features/        # Feature library, registry, pipeline, provenance
│   ├── strategies/      # Strategy contract, registry, trend strategy
│   ├── portfolio/       # Intent aggregation and allocation
│   ├── risk/            # EigenRisk engine, policy, checks
│   ├── execution/       # Paper broker, account, positions, reconciliation
│   ├── backtest/        # Deterministic backtest engine
│   ├── analytics/       # Metrics + statistical validation suite
│   ├── research/        # Hypotheses, campaigns, executors, provenance, costs
│   ├── stress/          # Adversarial scenario engine
│   ├── fidelity/        # Replay, parity, forward paper, verdicts
│   ├── shadow/          # Fail-closed shadow boundary
│   ├── live/, paper/    # Controlled live/paper boundaries and adapters
│   ├── production/      # Readiness audits, fingerprints, evidence
│   ├── micro_live/      # Micro-live qualification + runner
│   └── production_qual/ # Scaling qualification (in progress)
├── tests/
│   ├── unit/            # Unit tests per model/layer/subsystem
│   ├── property/        # Property-based tests (invariants hold universally)
│   ├── integration/     # Cross-layer contract tests
│   ├── simulation/      # End-to-end simulated runs
│   └── failure_injection/  # Fault-tolerance scenarios
├── configs/             # development/ paper/ production/ research/
├── data/                # raw/ normalized/ features/ metadata/ mt5/
├── docs/                # Contracts, phase reports, research results
├── research/            # hypotheses/ experiments/ notebooks/ reports/
├── scripts/
├── .github/workflows/   # CI (planned)
├── Makefile
└── pyproject.toml
```

## Governing Contracts

These documents are authoritative; code that violates them is wrong:

| Document | Scope |
|---|---|
| [DATA_CONTRACT.md](docs/DATA_CONTRACT.md) | What counts as a valid bar; quality classification |
| [RESEARCH_ENGINE_CONTRACT.md](docs/RESEARCH_ENGINE_CONTRACT.md) | Timestamp semantics, look-ahead prohibition, trial accounting |
| [STRESS_TEST_CONTRACT.md](docs/STRESS_TEST_CONTRACT.md) | Scenario taxonomy, expected vs. forbidden behavior |

Phase reports and campaign results live in [`docs/`](docs/) and
[`docs/research/`](docs/research/).

## Getting Started

**Requirements:** Python 3.11+

```bash
# Clone
git clone git@github.com:manuelhorvey/EigenCapital.git && cd EigenCapital

# Install with dev dependencies (editable install)
make dev

# Optional numerics for research/analytics work
pip install -e ".[research]"

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
| `BROKER_API_KEY` / `BROKER_API_SECRET` | Broker credentials (live phases only) | unset |
| `BROKER_PAPER` | Route to broker paper endpoint | `true` |
| `DATA_PROVIDER` / `DATA_API_KEY` | Market data source | unset |
| `MAX_LEVERAGE` | Portfolio leverage cap | `2.0` |
| `MAX_DRAWDOWN` | Max drawdown cap | `0.10` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

Never commit `.env` or real credentials. Real market data flows through the
MT5 provider (Wine bridge) with a yfinance fallback; exports land under
`data/mt5/` (gitignored).

## Testing Strategy

Tests mirror the dependency graph: lower layers are tested exhaustively before
upper layers are trusted on top of them.

| Suite | Scope | Command |
|---|---|---|
| Unit (`tests/unit/`) | Models, layers, subsystems, edge cases, error paths — **all green** | `make test-unit` |
| Property (`tests/property/`) | Invariants hold for arbitrary valid inputs | `make test-property` |
| Integration (`tests/integration/`) | Cross-layer contracts | scaffolded |
| Simulation (`tests/simulation/`) | Full-pipeline behavior | scaffolded |
| Failure injection (`tests/failure_injection/`) | Fault tolerance and recovery | scaffolded |

Coverage is configured with a minimum gate of 80% (`pyproject.toml`). An
architecture audit test (`tests/unit/test_architecture_audit.py`) continuously
verifies layer-dependency rules.

## Roadmap

- [x] **Phase 1A** — Core domain models, invariants, canonical serialization
- [x] **Phase 1B** — Instrument catalogue, ingestion, normalization, data validation
- [x] **Phase 1C** — Research identity: experiment registry, provenance hashing
- [x] **Phase 1D** — Contract-bound backtest engine (clock, accounting)
- [x] **Phase 1E** — EigenRisk independent risk boundary
- [x] **Phase 1F** — Portfolio construction and allocation pipeline
- [x] **Phase 1G** — Statistical validation suite + falsification-first evidence gate
- [x] **Phase 1H** — Stress testing and adversarial simulation
- [x] **Phase 1I** — Feature infrastructure and alpha research readiness
- [x] **Phase 1J** — Portfolio research and allocation evidence
- [x] **Phase 1K** — Paper-trading infrastructure
- [x] **Phase 1L** — Paper-trading validation and qualification
- [x] **Phase 1M** — Production readiness and governance audit
- [x] **Phase 1N** — Shadow trading and live boundary (fail-closed)
- [x] **Phase 1O** — Controlled live execution boundary
- [x] **Phase 1P** — Controlled live campaign + production qualification
- [x] **Phase 1Q** — Independent alpha research campaigns (R2–R4) on real MT5 data
- [x] **Phase 1R** — R4 replay, paper fidelity (`PASS`), shadow execution (`QUALIFIED`)
- [x] **Phase 1T** — Micro-live qualification framework + real-broker runner
- [ ] **Phase 1U** — Production qualification and capital scaling *(current)*
- [ ] **Phase 2** — Monitoring, alerting, operations hardening
- [ ] **Phase 3** — CI workflows, multi-strategy portfolio at scale

## Contributing

This project is pre-release and governed by explicit contracts. Before opening PRs:

1. Read the architecture section above — respect the dependency graph.
2. New domain models must enforce their invariants in `__post_init__`.
3. Every model ships with unit tests; invariant-critical logic warrants
   property-based tests.
4. Never weaken an evidence gate or invariant to make something pass —
   `INCONCLUSIVE` is a valid, honest outcome.
5. Run `make lint typecheck test` locally before submitting.

## License

[MIT](LICENSE) — see [LICENSE](LICENSE).
