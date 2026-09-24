# EigenCapital

[![CI](https://github.com/manuelhorvey/EigenCapital/actions/workflows/ci.yml/badge.svg)](https://github.com/manuelhorvey/EigenCapital/actions/workflows/ci.yml) [![codecov](https://codecov.io/github/manuelhorvey/EigenCapital/graph/badge.svg?token=5eUeOHPHGe)](https://codecov.io/github/manuelhorvey/EigenCapital) [![License](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Ruff](https://img.shields.io/badge/code%20style-ruff-fff0f0.svg)](https://github.com/astral-sh/ruff) [![MyPy](https://img.shields.io/badge/type%20checked-mypy-9cf)](https://mypy-lang.org) [![Security](https://img.shields.io/badge/security-SECURITY.md-brightgrey)](SECURITY.md)

## Table of Contents

| Section | |
|---|---|
| [Overview](#overview) | |
| [Quick Start](#quick-start) | |
| [Requirements](#requirements) | |
| [Architecture](#architecture) | |
| [Risk Architecture](#risk-architecture) | |
| [Qualification & Capital Scaling](#qualification--capital-scaling) | |
| [Research](#research) | |
| [Deployment](#deployment) | |
| [Testing](#testing) | |
| [Documentation Map](#documentation-map) | |
| [Limitations](#limitations) | |
| [Licensing](#licensing) | |

### Status at a Glance

| Area | Status | Authority |
|---|---|---|
| System phase | Phase 1 complete · Phase 2 evidence collection active · Phase 3 locked | [`docs/production/PHASE_STATUS.md`](docs/production/PHASE_STATUS.md) |
| Production strategy | R4 frozen (`risk_conditioned_continuation` R4.0) — frozen ≠ proven profitable | [`src/eigencapital/fidelity/r4_manifest.py`](src/eigencapital/fidelity/r4_manifest.py), [`configs/production/config.toml`](configs/production/config.toml) |
| Execution | MT5 loop under safety gates; evidence collection (no capital promotion) | [`docs/production/LIVE_TRADING.md`](docs/production/LIVE_TRADING.md) |
| Research queue | R0–R8 closed at last review (COMPLETE/FROZEN/PARKED/BLOCKED/DEFERRED per stage) | [`docs/research/RESEARCH_PROGRAM_STATUS.md`](docs/research/RESEARCH_PROGRAM_STATUS.md) |
| Architecture map | Current concept → authority map | [`docs/architecture/SYSTEM_TRUTH.md`](docs/architecture/SYSTEM_TRUTH.md) |
| Doc authority | One source per mutable fact | [`docs/DOCUMENTATION_SOURCE_OF_TRUTH.md`](docs/DOCUMENTATION_SOURCE_OF_TRUTH.md) |

## Overview

**EigenCapital** is an asset-agnostic quantitative research and execution platform designed for production-grade algorithmic trading. The platform implements a phase-gated qualification process ensuring strategies meet safety and evidence thresholds before any capital deployment.

> **Phase 1**: `🟢 COMPLETE` — Production Hardening & Safety Qualification
> **Phase 2**: `🟡 ACTIVE` — Live Economic Validation & Capacity Discovery
> **Phase 3**: `🔒 LOCKED` — Capital Scaling (requires Phase 2 evidence gates)

EigenCapital is running live against a real MT5 broker under explicit safety controls. The frozen R4 strategy is generating real trade evidence. No strategy modifications, parameter tuning, or capital promotion is permitted until Phase 2 evidence gates are satisfied.

See [`docs/production/PHASE_STATUS.md`](docs/production/PHASE_STATUS.md) for details.

## What EigenCapital Does

EigenCapital separates *deciding* from *doing*:

```
Research → Validation → Frozen Strategy → Signal → Portfolio → Risk → Execution → MT5 → Audit
```

### Core Modules

| Category | Module | Purpose |
|---|---|---|
| **Research** | Falsifiable hypotheses | Walk-forward, bootstrap, multiple-testing correction, deflated Sharpe |
| **Strategy** | R4 frozen momentum | Volatility-normalized signal, frozen parameters |
| **Risk** | Independent risk boundary | Enforces limits before any order reaches broker |
| **Execution** | Ticket-scoped closes, hedging-safe order generation | Auto-reconnect on stale MT5 session |
| **Audit** | JSONL with full provenance chain | Crash-resistant audit trail |
| **Data Infrastructure** | MarketSchedule, DataQuality, DataTruth | Canonical market availability, data quality, and provenance |

## Quick Start

### Prerequisites

- Python >= 3.11
- OS: Linux (Ubuntu/Debian production certified)
- Optional: Research extras (`pip install -e ".[research]"`)

### Installation

```bash
# Clone repository
git clone https://github.com/manuelhorvey/EigenCapital.git && cd EigenCapital

# Install package in development mode
pip install -e ".[research]"

# Configure environment
cp .env.example .env
# Edit .env with broker credentials
```

### Run Live Loop

```bash
# Hourly rebalance loop
python scripts/r4_rebalance_loop.py --loop --interval 3600

# Monitoring (60s interval)
python scripts/r4_monitor.py --loop --interval 60

# Supervisor dry-run
python scripts/r4_supervisor_dryrun.py
```

### Pre-Flight Checks (mandatory before live trading)

```bash
# 1. Verify fingerprints (fail-closed)
python -c "from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier; print(FingerprintVerifier().verify_all().all_verified)"

# 2. Run supervisor dry-run
python scripts/r4_supervisor_dryrun.py

# 3. Run adversarial audit
python scripts/r4_adversarial_audit.py

# 4. Generate T=0 snapshot
python scripts/r4_generate_t0.py

# 5. Generate attestation
python scripts/r4_attestation.py
```

## Requirements

| Component | Specification |
|---|---|
| **Python** | >= 3.11 |
| **OS** | Linux (Ubuntu/Debian production certified) |
| **Arch** | x86_64 / ARM64 |
| **Dependencies (research)** | numpy>=1.24, pandas>=2.0 |
| **Build** | setuptools>=68.0, wheel |

### Production Constraints

- **OS**: Linux only (Windows architecturally supported but not certified)
- **MT5 Bridge**: `mt5linux` required on Linux; native on Windows
- **Capital**: Currently $5K qualification only (not certified for larger)

## Architecture

```
                     Market Data
                          ↓
                     MarketSchedule (canonical calendar)
                          ↓
                     DataQuality (freshness, completeness, spread)
                          ↓
                     DataTruth (authoritative/derived/stale/unavailable)
                          ↓
                     MarketDataBridge
                          ↓
                     R4 Signal (frozen)
                          ↓
                     Portfolio Construction
                          ↓
                     RiskPolicy Check
                     ├─ Fingerprint ✅
                     ├─ Position Count ✅
                     ├─ Equity Floor ✅
                     ├─ Daily Loss ✅
                     ├─ Watchdog ✅
                     └─ Foreign Quarantine ✅
                          ↓
                     Order Generation
                     ├─ Ticket-scoped closes
                     └─ Signed volumes
                          ↓
                     MT5 Execution
                          ↓
                     Reconciliation
                          ↓
                     Audit Trail (JSONL)
                          ↓
                     Dashboard (read-only observer)
```

### Safety Stack

| Layer | Module | Purpose |
|---|---|---|
| Fingerprint | `fingerprint_verifier.py` | Fail-closed config integrity |
| Attribution | `position_attribution.py` | R4/foreign classification |
| Quarantine | `position_attribution.py` | Foreign → block new entries |
| Watchdog | `watchdog.py` | Blind-window detection |
| Catastrophic | `catastrophic_protection.py` | Disaster stop-loss boundary |
| Recovery | `risk.py` | Disconnect/reconnect handling |
| Audit | `durable_audit.py` | Crash-resistant JSONL trail |

## Risk Architecture

### Pre-Trade Gates

| Gate | Limit | Enforcement |
|---|---|---|
| Fingerprint | 5 components | Fail-closed |
| Position count | ≤ 20 | Block new entries |
| Position notional | ≤ $5,000 | Skip symbol |
| Equity floor | ≥ $4,000 | Block trading |
| Daily loss | ≤ $250 | Block trading |
| Drawdown | ≤ 10% | Block trading |
| Foreign quarantine | 0 foreign | Block new entries |

Authoritative gate semantics: [`docs/production/RISK_ARCHITECTURE.md`](docs/production/RISK_ARCHITECTURE.md) and `configs/production/config.toml` (`[live_risk]`).

### During-Trade Controls

- Catastrophic stop-loss (2× ATR14 or 1% floor, whichever is larger)
- Ticket-scoped closes (hedging-safe)
- Auto-reconnect on stale MT5 session
- Watchdog escalation (NORMAL → DEGRADED → BLIND → CONTAIN)

### Portfolio-Level Risk

- Volatility-scaled sizing
- Asset-class concentration monitoring

## Data Infrastructure

EigenCapital maintains a canonical chain of truth for all market data:

```
MarketSchedule → DataQuality → DataTruth → MarketDataBridge
```

| Component | Purpose |
|---|---|
| **MarketSchedule** | Authoritative trading calendar per instrument (28 instruments in `configs/market_schedules/default.toml`: FX, metals, indices, energy, crypto) |
| **DataQuality** | Freshness, completeness, spread, plausibility, timestamp integrity assessment |
| **DataTruth** | Provenance tracking: AUTHORITATIVE / DERIVED / ESTIMATED / STALE / UNAVAILABLE / CORRUPT |
| **MarketDataBridge** | Connects schedule → quality → truth; distinguishes expected vs unexpected data absence |
| **NoSilentDegradation** | Platform invariant: missing/stale data never silently becomes valid-looking data |

**Key invariant:** When the market is closed, missing data is `EXPECTED_MISSING` (not a failure). When the market is open, missing data is `UNEXPECTED_MISSING` (triggers risk response).

See [`docs/architecture/DATA_INVARIANTS.md`](docs/architecture/DATA_INVARIANTS.md) for the full invariant specification.

## Qualification & Capital Scaling

| Tier | Max Position | Max Concurrent | Universe | Status |
|---|---|---|---|---|
| $5K campaign | $5,000 | 20 | 28 tradeable listed symbols | 🟢 Live (Phase 2 evidence collection) |
| $10K | $10,000 | TBD | TBD | 🔴 Not qualified |
| $25K | $25,000 | TBD | TBD | 🔴 Not qualified |
| $50K | $50,000 | TBD | TBD | 🔴 Not qualified |

**Capital scaling is earned through evidence, not enabled by changing a configuration value.**

See [`docs/production/CAPITAL_SCALING.md`](docs/production/CAPITAL_SCALING.md) for full definitions.

### Position Count Governance

- **`max_concurrent_positions = 20`** (config + tests; risk-policy parameter, not tied to universe size)
- Universe listing: 35 entries under `[broker.allowed_symbols]`, of which 7 are `forex_excluded` → **28 tradeable**

### Capital Semantics (current config)

| Concept | Value | Meaning |
|---|---|---|
| Account equity | Live (varies) | What broker shows |
| `capital.max_equity` | $20,000 | Sizing/envelope ceiling in production config |
| Campaign tier | $5,000 | Qualification level label |
| Position limit | $5,000 | Max notional per position |
| Risk budget | $250/day | Daily loss limit (`[live_risk]`) |

See [`docs/production/CAPITAL_SCALING.md`](docs/production/CAPITAL_SCALING.md) for full definitions.

## Research

R4 is the current production strategy. Research does not modify R4.

| Track | Status | Notes |
|---|---|---|
| R4 production (`risk_conditioned_continuation`) | 🟢 Live evidence collection | Frozen parameters; Phase 2 gates control promotion |
| Literature research program (R0–R8) | Queue closed at last status | Verdicts per stage in [`docs/research/RESEARCH_PROGRAM_STATUS.md`](docs/research/RESEARCH_PROGRAM_STATUS.md) |
| R4 rebalance-frequency study (EXP-000002) | Research complete | GO to qualification, **not** production change ([`docs/research/R4_REBALANCE_FREQUENCY.md`](docs/research/R4_REBALANCE_FREQUENCY.md)) |
| R5 swing-breadth campaign (2026-08-25) | 0/16 supported | 13 REJECTED, 3 FRAGILE — [`research/hypotheses/README.md`](research/hypotheses/README.md) |
| Intraday / tick microstructure | Frozen research branches | Not production-qualified |

**Frozen does not mean proven profitable.** Shadow selectors and research experiments observe or diagnose; they do not alter frozen R4.

### Research Philosophy

> Falsification is a successful outcome.

The research pipeline intentionally rejects attractive-looking signals when they fail:
- Multiple-testing correction (Bonferroni, Holm, BH/FDR)
- Out-of-sample validation
- Parameter stability checks
- Drawdown requirements
- Evidence thresholds

## Deployment

### Linux (Production)

```bash
# Clone
git clone git@github.com:manuelhorvey/EigenCapital.git && cd EigenCapital

# Install
pip install -e ".[research]"

# Configure
cp .env.example .env
# Edit .env with broker credentials

# Run live loop
python scripts/r4_rebalance_loop.py --loop --interval 3600

# Monitor
python scripts/r4_monitor.py --loop --interval 60

# Supervisor dry-run
python scripts/r4_supervisor_dryrun.py
```

### Pre-Flight Checks

Before live trading, always run:

1. **Verify fingerprints** — fail-closed config integrity
2. **Supervisor dry-run** — validate T=0 snapshot matches config
3. **Adversarial audit** — test P0 safety boundaries
4. **Generate T=0 snapshot** — create baseline for audit trail
5. **Generate attestation** — formal qualification evidence

## Testing

| Suite | Command |
|---|---|
| Unit | `pytest tests/unit/` |
| Property | `pytest tests/property/` |
| P0 Safety | `pytest tests/unit/live/test_p0_safety.py` |
| Risk Enforcement | `pytest tests/unit/live/test_risk_enforcement.py` |
| With coverage | `pytest --cov=eigencapital tests/unit/` |

```bash
# Full test suite
make test

# Unit tests only
make test-unit

# With coverage
pytest --cov=eigencapital --cov-report=term-missing tests/unit/

# Lint and type-check
make lint && make typecheck
```

Coverage is tracked via [Codecov](https://codecov.io/github/manuelhorvey/EigenCapital). The CI workflow uploads coverage reports on every push to `main` and on pull requests.

## Limitations

- **Phase 2 only** — capital promotion locked until evidence gates pass
- **28 tradeable listed symbols** — 7 JPY crosses marked `forex_excluded` (broker min-lot constraint)
- **20 max concurrent** — governance/config decision, not a technical ceiling
- **Linux certified for production** — Windows/macOS documented for development; not production-certified
- **R4 edge is slow** — evidence collection expects multi-week holding periods
- **No guaranteed stop-loss** — catastrophic SL subject to gap/slippage risk
- **No live profitability claim** — Phase 2 is collecting evidence; expectancy gates not yet satisfied by documentation alone

## Documentation Map

| Need | Document |
|---|---|
| Phase / production status | [`docs/production/PHASE_STATUS.md`](docs/production/PHASE_STATUS.md) |
| Architecture & concept authority | [`docs/architecture/SYSTEM_TRUTH.md`](docs/architecture/SYSTEM_TRUTH.md) |
| Doc source-of-truth map | [`docs/DOCUMENTATION_SOURCE_OF_TRUTH.md`](docs/DOCUMENTATION_SOURCE_OF_TRUTH.md) |
| Risk architecture | [`docs/production/RISK_ARCHITECTURE.md`](docs/production/RISK_ARCHITECTURE.md) |
| Live operations | [`docs/production/LIVE_TRADING.md`](docs/production/LIVE_TRADING.md), [`docs/production/OPERATIONS_RUNBOOK.md`](docs/production/OPERATIONS_RUNBOOK.md) |
| Deployment | [`docs/production/DEPLOYMENT.md`](docs/production/DEPLOYMENT.md) |
| Capital scaling | [`docs/production/CAPITAL_SCALING.md`](docs/production/CAPITAL_SCALING.md) |
| Testing | [`docs/production/TESTING.md`](docs/production/TESTING.md) |
| Research program status | [`docs/research/RESEARCH_PROGRAM_STATUS.md`](docs/research/RESEARCH_PROGRAM_STATUS.md) |
| Literature roadmap (governing review) | [`docs/research/RESEARCH_LITERATURE_AUDIT_REVIEW.md`](docs/research/RESEARCH_LITERATURE_AUDIT_REVIEW.md) |
| Data invariants | [`docs/architecture/DATA_INVARIANTS.md`](docs/architecture/DATA_INVARIANTS.md) |
| Historical audits | [`docs/audits/`](docs/audits/) (dated; not current status) |

## Licensing

[MIT](LICENSE)

## Versioning

Follows [Semantic Versioning](https://semver.org/). Package version is declared in [`pyproject.toml`](pyproject.toml) (currently `0.5.0`). Release history: [`CHANGELOG.md`](CHANGELOG.md).

## Contributing

> **Note**: This project is in active production qualification. Contributions are limited to bug fixes and documentation improvements that do not alter strategy parameters or qualification gates.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/foo`)
3. Commit changes (`git commit -m "Add foo feature"`)
4. Push to branch (`git push origin feature/foo`)
5. Open a Pull Request

All PRs must pass:
- Full test suite (`make test`)
- Code style (`make lint`)
- Type checking (`make typecheck`)
- No strategy parameter changes without Phase 2 evidence

---

*Generated from the EigenCapital production-grade documentation suite. See [`docs/DOCUMENTATION_SOURCE_OF_TRUTH.md`](docs/DOCUMENTATION_SOURCE_OF_TRUTH.md) for the authoritative source mapping.*