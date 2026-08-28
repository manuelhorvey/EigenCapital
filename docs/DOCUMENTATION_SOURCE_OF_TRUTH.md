# Documentation Source of Truth

This document defines which file is the **authoritative source** for each subject area.
When documentation and code disagree, trace back to the authoritative source listed here.

Last updated: 2026-08-26

## Core System

| Domain | Authoritative Source | Location |
|---|---|---|
| R4 identity (frozen) | R4 manifest | `src/eigencapital/fidelity/r4_manifest.py` |
| Strategy parameters | Config production | `configs/production/config.toml` |
| Risk policy | RiskPolicy class | `src/eigencapital/risk/policy.py` |
| Capital limits | CapitalConfig | `src/eigencapital/config.py` → `CapitalConfig` |
| Live risk envelope | LiveRiskConfig | `src/eigencapital/config.py` → `LiveRiskConfig` |
| Broker config | BrokerConfig | `src/eigencapital/config.py` → `BrokerConfig` |
| Position limits | RiskEnvelope | `src/eigencapital/live/risk_enforcement.py` |
| Eligible symbols | Broker config | `configs/production/config.toml` → `[broker.allowed_symbols]` |

## Safety Architecture

| Domain | Authoritative Source | Location |
|---|---|---|
| Catastrophic protection | catastrophic_protection.py | `src/eigencapital/live/catastrophic_protection.py` |
| Watchdog state machine | watchdog.py | `src/eigencapital/live/watchdog.py` |
| Position attribution | position_attribution.py | `src/eigencapital/live/position_attribution.py` |
| Fingerprint verification | fingerprint_verifier.py | `src/eigencapital/production_qual/fingerprint_verifier.py` |
| Durable audit trail | durable_audit.py | `src/eigencapital/live/durable_audit.py` |
| Process supervision | supervisor.py | `src/eigencapital/live/supervisor.py` |

## Live Trading

| Domain | Authoritative Source | Location |
|---|---|---|
| Rebalance loop | r4_rebalance_loop.py | `scripts/r4_rebalance_loop.py` |
| Live orders | r4_live_orders.py | `scripts/r4_live_orders.py` — **QUARANTINED**, cannot submit orders |
| Monitor | r4_monitor.py | `scripts/r4_monitor.py` |
| Safety supervisor | r4_safety_supervisor.py | `scripts/r4_safety_supervisor.py` |
| T=0 snapshot | T0 JSON files | `reports/r4_qualification/T0_*.json` |
| Attestation | Attestation JSON | `reports/r4_qualification/attestation_*.json` |

## Qualification

| Domain | Authoritative Source | Location |
|---|---|---|
| Supervisor dry-run | Dry-run reports | `reports/r4_qualification/supervisor_dryrun_*.json` |
| Adversarial audit | Audit reports | `reports/r4_qualification/adversarial_audit_*.json` |
| Position evidence | Evidence JSONL | `reports/r4_qualification/evidence/` |
| Capital semantics | Capital semantics doc | `docs/production/CAPITAL_SCALING.md` |

## Research

| Domain | Authoritative Source | Location |
|---|---|---|
| Research hypotheses | Hypotheses README | `research/hypotheses/README.md` |
| Alpha research map | Research map | `docs/research/ALPHA_RESEARCH_MAP_1Q_FULL.md` |
| Trial ledger | Trial ledger | `reports/r4_economics_audit/trial_ledger.json` |
| R4 economics | Economics audit | `reports/r4_economics_audit/` |

## Configuration

| Domain | Authoritative Source | Location |
|---|---|---|
| Production config | config.toml | `configs/production/config.toml` |
| Risk limits | RiskPolicy | `src/eigencapital/risk/policy.py` |
| Capital limits | CapitalConfig | `src/eigencapital/config.py` |
| Live risk limits | LiveRiskConfig | `src/eigencapital/config.py` |
| Risk enforcement | RiskEnvelope | `src/eigencapital/live/risk_enforcement.py` |

## Testing

| Domain | Authoritative Source | Location |
|---|---|---|
| Unit tests | pytest output | `tests/unit/` |
| Safety tests | P0 safety tests | `tests/unit/live/test_p0_safety.py` |
| Risk enforcement tests | Risk tests | `tests/unit/live/test_risk_enforcement.py` |
| Test count | pytest collection | Run `pytest --co -q` |

## Operational Documents

| Document | Purpose | Location |
|---|---|---|
| Risk architecture | Complete risk control documentation | `docs/production/RISK_ARCHITECTURE.md` |
| Live trading | Operational sequence and procedures | `docs/production/LIVE_TRADING.md` |
| Deployment | Installation and startup procedures | `docs/production/DEPLOYMENT.md` |
| Operations runbook | Daily/weekly checks, failure handling | `docs/production/OPERATIONS_RUNBOOK.md` |
| Capital scaling | Tier definitions and promotion criteria | `docs/production/CAPITAL_SCALING.md` |
| Platform portability | Linux vs Windows support status | `docs/production/PLATFORM_PORTABILITY.md` |
| Testing | Test architecture and categories | `docs/production/TESTING.md` |
| Sync audit | Documentation synchronization results | `docs/production/DOCUMENTATION_SYNC_AUDIT.md` |

## Documentation Gaps

The following areas lack a single authoritative document:

1. **Strategy capacity limits** — Not formally documented
2. **Correlation/concentration limits** — No formal portfolio-level risk policy
3. **Holding period economics** — Only research evidence, no live confirmation
4. **Entry slippage benchmarks** — No baseline established yet

## How to Use This Map

1. **For any claim in documentation**, trace it to the authoritative source above
2. **If code and docs disagree**, the authoritative source wins
3. **If no authoritative source exists**, flag it as a documentation gap
4. **When adding new features**, update this map with the new authoritative source
