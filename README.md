# EigenCapital

Asset-agnostic quantitative research and execution platform.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-2%2C301%20passing-brightgreen)](#testing)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **Status: 🟢 LIVE — CONTROLLED $5K QUALIFICATION**
>
> EigenCapital is running live against a real MT5 broker under explicit safety
> controls. The frozen R4 strategy is generating real trade evidence. No strategy
> modifications, parameter tuning, or capital promotion is permitted until the
> evidence window is complete.

## What EigenCapital Does

EigenCapital separates *deciding* from *doing*:

```
Research → Validation → Frozen Strategy → Signal → Portfolio → Risk → Execution → MT5 → Audit
```

- **Research**: Falsifiable hypotheses survive hostile validation (walk-forward, bootstrap, multiple-testing correction, deflated Sharpe)
- **Strategy**: R4 is a frozen momentum strategy — parameters are immutable
- **Risk**: Independent risk boundary enforces limits before any order reaches the broker
- **Execution**: Ticket-scoped closes, hedging-safe order generation, auto-reconnect
- **Audit**: Every decision recorded to JSONL with full provenance chain

## Current Architecture

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

## R4 Strategy

R4 is a **frozen** cross-sectional momentum strategy:

- **Signal**: 12-month minus 1-month momentum, cross-sectional ranks
- **Regime**: Volatility gate (trade when vol < median)
- **Sizing**: Volatility-scaled, clipped to ±20% (BTC ±10%)
- **Rebalance**: Hourly rotation of top-19 positions by signal strength
- **Exit**: Signal reversal, regime change, or catastrophic stop-loss
- **Protection**: 2× ATR14 or 1% floor (whichever is larger)

### What R4 Is NOT

- R4 does **not** use conventional SL/TP as normal exits
- R4 does **not** optimize for short-term profit
- R4's edge emerges **slowly** (20-40+ day holding periods)
- R4 does **not** trade every signal — regime gate filters low-conviction periods

## Qualification Status

| Tier | Status | Evidence |
|---|---|---|
| $5K | 🟢 LIVE | T=0 frozen, attestation valid, 10/10 adversarial tests |
| $10K | 🔴 Not yet | Requires $5K evidence window |
| $25K+ | 🔴 Not yet | Requires $10K qualification |

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

## Live Execution Sequence

Every cycle (hourly):

1. Verify build fingerprints (fail-closed)
2. Validate T=0 snapshot matches config
3. Assert position count within limits
4. Check watchdog state (NORMAL/DEGRADED/BLIND/CONTAIN)
5. Check risk gates (equity, drawdown, daily loss)
6. Compute R4 signal (frozen, regime-gated)
7. Generate orders (rotation-aware, ticket-scoped closes)
8. Execute only what passes all gates
9. Audit every decision to JSONL

**No valid R4 signal = no trade.**

## Platform Support

| Platform | Status | Evidence |
|---|---|---|
| Linux (Ubuntu/Debian) | 🟢 Production | Live running since Aug 2026 |
| Windows | 🟡 Architecturally supported | Deployment docs exist |
| mt5linux bridge | 🟢 Working | Rpyc connection to MT5 terminal |

### Key Distinction

- **Application architecture**: Platform-agnostic (abstraction layer)
- **MT5 integration**: Requires mt5linux bridge on Linux, native on Windows
- **Currently certified**: Linux only (where live qualification runs)

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

### Pre-flight Checks

Before live trading:

```bash
# 1. Verify fingerprints
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

## Testing

| Suite | Count | Command |
|---|---|---|
| Unit | 2,301 | `pytest tests/unit/` |
| Property | — | `pytest tests/property/` |
| P0 Safety | 44 | `pytest tests/unit/live/test_p0_safety.py` |
| Risk Enforcement | — | `pytest tests/unit/live/test_risk_enforcement.py` |

```bash
# Full suite
make test

# Unit tests only
make test-unit

# Lint and type-check
make lint && make typecheck
```

## Risk Architecture

### Pre-trade Gates

| Gate | Limit | Enforcement |
|---|---|---|
| Fingerprint | 5 components | Fail-closed |
| Position count | ≤ 19 | Block new entries |
| Position notional | ≤ $5,000 | Skip symbol |
| Equity floor | ≥ $4,000 | Block trading |
| Daily loss | ≤ $250 | Block trading |
| Drawdown | ≤ 10% | Block trading |
| Foreign quarantine | 0 foreign | Block new entries |

### During-trade Controls

- Catastrophic stop-loss (2× ATR or 1% floor)
- Ticket-scoped closes (hedging-safe)
- Auto-reconnect on stale MT5 session
- Watchdog escalation (NORMAL → DEGRADED → BLIND → CONTAIN)

### Portfolio-level Risk

- Signal clips weights to ±20%
- Volatility-scaled sizing
- Regime gate (no trade when vol > median)
- Correlation monitoring (rolling 20/60/120-day)

## Capital Scaling

| Tier | Max Position | Max Concurrent | Universe | Status |
|---|---|---|---|---|
| $5K | $5,000 | 19 | 24 symbols | 🟢 Live |
| $10K | $10,000 | TBD | TBD | 🔴 Not qualified |
| $25K | $25,000 | TBD | TBD | 🔴 Not qualified |
| $50K | $50,000 | TBD | TBD | 🔴 Not qualified |

**Capital scaling is earned through evidence, not enabled by changing a configuration value.**

See [`docs/production/CAPITAL_SEMANTICS.md`](docs/production/CAPITAL_SEMANTICS.md).

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

## Project Structure

```
eigencapital/
├── src/eigencapital/
│   ├── core/            # Domain models, contracts
│   ├── data/            # Catalogue, loaders, normalization
│   ├── features/        # Feature library, pipeline
│   ├── risk/            # Risk engine, policy
│   ├── execution/       # Broker, positions, reconciliation
│   ├── live/            # Safety: watchdog, attribution, catastrophic protection
│   ├── production_qual/ # Qualification: fingerprint, scaling, campaigns
│   └── fidelity/        # R4 manifest, replay, parity
├── tests/
│   ├── unit/            # 2,301 unit tests
│   └── unit/live/       # P0 safety, risk enforcement
├── configs/production/  # Single source of truth for config
├── scripts/             # Live trading, monitoring, qualification
├── reports/
│   ├── r4_qualification/ # T=0, audits, attestation
│   ├── r4_loop/          # Runtime logs (gitignored)
│   └── r4_economics_audit/ # Trade economics evidence
├── docs/
│   ├── production/       # Production documentation
│   └── research/         # Research documentation
└── research/             # Hypotheses, experiments
```

## Documentation

| Document | Purpose |
|---|---|
| [`docs/DOCUMENTATION_SOURCE_OF_TRUTH.md`](docs/DOCUMENTATION_SOURCE_OF_TRUTH.md) | Which doc is authoritative for each subject |
| [`docs/production/PRODUCTION_EVIDENCE_INDEX.md`](docs/production/PRODUCTION_EVIDENCE_INDEX.md) | All qualification evidence artifacts |
| [`docs/production/CAPITAL_SEMANTICS.md`](docs/production/CAPITAL_SEMANTICS.md) | Capital concept definitions |
| [`docs/production/PRODUCTION_OPERATIONS_RUNBOOK.md`](docs/production/PRODUCTION_OPERATIONS_RUNBOOK.md) | Operations procedures |
| [`docs/production/FAILURE_RECOVERY_MATRIX.md`](docs/production/FAILURE_RECOVERY_MATRIX.md) | Failure handling procedures |

## Limitations

- **$5K qualification only** — not certified for larger capital
- **24 symbols** — 7 JPY crosses excluded (broker contract constraint)
- **19 max concurrent** — governance decision, not technical limit
- **Linux only** — Windows architecturally supported but not certified
- **R4 edge is slow** — requires 20-40+ day holding periods for evidence
- **No guaranteed stop-loss** — catastrophic SL subject to gap/slippage risk
- **No live profitability evidence yet** — currently collecting evidence

## License

[MIT](LICENSE)
