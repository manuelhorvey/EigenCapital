# EigenCapital

[![CI](https://github.com/manuelhorvey/EigenCapital/actions/workflows/ci.yml/badge.svg)](https://github.com/manuelhorvey/EigenCapital/actions/workflows/ci.yml) [![codecov](https://codecov.io/github/manuelhorvey/EigenCapital/graph/badge.svg?token=5eUeOHPHGe)](https://codecov.io/github/manuelhorvey/EigenCapital) [![License](https://img.shields.io/badge/license-MIT-green)](LICENSE) [![Ruff](https://img.shields.io/badge/code%20style-ruff-fff0f0.svg)](https://github.com/astral-sh/ruff) [![MyPy](https://img.shields.io/badge/type%20checked-mypy-9cf)](https://mypy-lang.org) [![Security](https://img.shields.io/badge/security-reviewed-brightgrey)](https://github.com/manuelhorvey/EigenCapital/security)

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
| [Limitations](#limitations) | |
| [Licensing](#licensing) | |

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
| **Strategy** | R4 frozen momentum | Immutable parameters, volatility-gated regimes |
| **Risk** | Independent risk boundary | Enforces limits before any order reaches broker |
| **Execution** | Ticket-scoped closes, hedging-safe order generation | Auto-reconnect on stale MT5 session |
| **Audit** | JSONL with full provenance chain | Crash-resistant audit trail |

## Quick Start

### Prerequisites

- Python >= 3.11
- OS: Linux (Ubuntu/Debian production certified)
- Optional: Research extras (`pip install -e ".[research]"`)

### Installation

```bash
# Clone repository
git clone <repo> && cd EigenCapital

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
python scripts/r4_attestation.py"
```

## Requirements

| Component | Specification |
|---|---|
| **Python** | >= 3.11 (3.12 recommended) |
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
| Position count | ≤ 19 | Block new entries |
| Position notional | ≤ $5,000 | Skip symbol |
| Equity floor | ≥ $4,000 | Block trading |
| Daily loss | ≤ $250 | Block trading |
| Drawdown | ≤ 10% | Block trading |
| Foreign quarantine | 0 foreign | Block new entries |

### During-Trade Controls

- Catastrophic stop-loss (2× ATR14 or 1% floor, whichever is larger)
- Ticket-scoped closes (hedging-safe)
- Auto-reconnect on stale MT5 session
- Watchdog escalation (NORMAL → DEGRADED → BLIND → CONTAIN)

### Portfolio-Level Risk

- Signal clips weights to ±20%
- Volatility-scaled sizing
- Regime gate (no trade when vol > median)
- Correlation monitoring (rolling 20/60/120-day)

## Qualification & Capital Scaling

| Tier | Max Position | Max Concurrent | Universe | Status |
|---|---|---|---|---|
| $5K | $5,000 | 19 | 24 symbols | 🟢 Live |
| $10K | $10,000 | TBD | TBD | 🔴 Not qualified |
| $25K | $25,000 | TBD | TBD | 🔴 Not qualified |
| $50K | $50,000 | TBD | TBD | 🔴 Not qualified |

**Capital scaling is earned through evidence, not enabled by changing a configuration value.**

See [`docs/production/CAPITAL_SEMANTICS.md`](docs/production/CAPITAL_SEMANTICS.md) for full definitions.

### Position Count Governance

- **MAX_CONCURRENT = 19** (explicit governance decision)
- Top-19 captures **97.4%** of total signal weight
- Remaining 5 symbols contribute <3% — marginal
- `MAX_CONCURRENT` is a risk-policy parameter, not tied to universe size

### Capital Semantics

| Concept | Value | Meaning |
|---|---|---|
| Account equity | ~$6,980 | What broker shows |
| Authorized capital | $5,100 | What strategy trades against |
| Campaign tier | $5,000 | Qualification level |
| Position limit | $5,000 | Max notional per position |
| Risk budget | $250/day | Daily loss limit |

See [`docs/production/CAPITAL_SEMANTICS.md`](docs/production/CAPITAL_SEMANTICS.md) for full definitions.

## Research

R4 is the current production strategy. Research history:

| Strategy | Status | Notes |
|---|---|---|
| R4 momentum | 🟢 Live | Frozen, qualified at $5K |
| R5 swing breadth | 🔴 Rejected | 16/16 hypotheses failed |
| M1-1H OHLCV | 🔴 Frozen | Not production-qualified |
| Tick microstructure | 🔴 Frozen | Campaign 7 hardened, not promoted |

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
git clone <repo> && cd EigenCapital

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

- **$5K qualification only** — not certified for larger capital
- **24 symbols** — 7 JPY crosses excluded (broker contract constraint)
- **19 max concurrent** — governance decision, not technical limit
- **Linux only** — Windows architecturally supported but not certified
- **R4 edge is slow** — requires 20-40+ day holding periods for evidence
- **No guaranteed stop-loss** — catastrophic SL subject to gap/slippage risk
- **No live profitability evidence yet** — currently collecting evidence

## Licensing

[MIT](LICENSE)

## Support & Contact

- **Issues**: [GitHub Issues](https://github.com/manuelhorvey/EigenCapital/issues)
- **Documentation**: [docs/](docs/)
- **Research**: [research/](research/)
- **Contact**: eigencapital-team@example.com

## Versioning

This project follows [Semantic Versioning](https://semver.org/) principles. The current version is `0.1.0` (Pre-Alpha). Breaking changes will be documented in the changelog.

Changelog entries are tracked in [`CHANGELOG.md`](CHANGELOG.md) (to be created for v1.0).

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