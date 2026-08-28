# Documentation Governance

## Authority Model

Each subject has exactly one authoritative source. All other documents referencing the same subject must defer.

| Subject | Authoritative Source | Location |
|---------|---------------------|----------|
| **Strategy behavior** | R4 manifest + implementation | `src/eigencapital/fidelity/r4_manifest.py`, `scripts/r4_rebalance_loop.py` |
| **Production configuration** | Config module + production TOML | `src/eigencapital/config.py`, `configs/production/config.toml` |
| **Risk semantics** | Risk enforcement + domain models | `src/eigencapital/live/risk_enforcement.py`, `src/eigencapital/core/models.py` |
| **Current architecture** | Architecture current state doc | `docs/architecture/ARCHITECTURE_CURRENT_STATE.md` |
| **Architecture gaps** | Architecture gaps doc | `docs/architecture/ARCHITECTURE_GAPS.md` |
| **Technical debt** | Debt register | `docs/architecture/TECHNICAL_DEBT_REGISTER.md` |
| **Live qualification state** | Latest qualification artifacts | `reports/r4_qualification/T0_*.json`, `reports/r4_qualification/attestation_*.json` |
| **Phase 2 status** | Phase status doc | `docs/production/PHASE_STATUS.md` |
| **Phase alignment** | Phase alignment doc | `docs/architecture/PHASE_ALIGNMENT.md` |
| **Capital semantics** | Capital scaling doc | `docs/production/CAPITAL_SCALING.md` |
| **Operations runbook** | Operations runbook | `docs/production/OPERATIONS_RUNBOOK.md` |
| **Live trading setup** | Live trading doc | `docs/production/LIVE_TRADING.md` |
| **Deployment** | Deployment doc | `docs/production/DEPLOYMENT.md` |
| **Research methodology** | Research docs | `docs/research/` |
| **Machine-readable audit** | Audit JSON reports | `reports/codebase_audit/` |
| **Machine-readable config** | Config audit reports | `reports/configuration_audit/` |
| **Documentation inventory** | This governance model | `docs/DOCUMENTATION_GOVERNANCE.md` |

## Rules

1. **Code is source of truth.** Documentation follows code. If documentation conflicts with code, update documentation.
2. **One owner per subject.** No two documents may claim authority over the same fact.
3. **Historical documents stay historical.** Do not rewrite audit reports from past phases. Mark them with a superseded notice if needed.
4. **No planned features as implemented.** Documentation must not claim capabilities that do not exist in code.
5. **No hardcoded test counts.** Prefer `run make test-unit` over exact numbers.
6. **No hardcoded commit hashes.** State the branch and date instead.
7. **No marketing language.** Avoid "production-grade", "institutional-grade", "guaranteed" unless objectively qualified.
8. **Evidence-based claims.** Every claim must be verifiable against code, tests, or configuration.

## Documentation Structure

```
docs/
├── architecture/              # Architecture analysis (audit-driven)
│   ├── ARCHITECTURE_CURRENT_STATE.md    # Current actual architecture
│   ├── ARCHITECTURE_GAPS.md             # Prioritized gaps
│   ├── COMPREHENSIVE_CODEBASE_AUDIT.md  # Full audit
│   ├── TECHNICAL_DEBT_REGISTER.md       # Complete debt register
│   ├── REFACTOR_ROADMAP.md              # Keep/refactor/remove/defer
│   └── PHASE_ALIGNMENT.md              # Roadmap alignment
├── production/                # Production operations
│   ├── LIVE_TRADING.md                  # Live trading setup & runbooks
│   ├── OPERATIONS_RUNBOOK.md            # Operator actions
│   ├── DEPLOYMENT.md                    # Deployment guide
│   ├── PHASE_STATUS.md                  # Phase 2 status
│   ├── CAPITAL_SCALING.md               # Capital semantics (consolidated)
│   ├── RISK_ARCHITECTURE.md             # Risk architecture
│   ├── CONFIGURATION_AUDIT.md           # Config audit
│   └── ...                              # Other production docs
├── research/                  # Research methodology
│   └── ...
├── DOCUMENTATION_GOVERNANCE.md          # This file
├── DOCUMENTATION_SOURCE_OF_TRUTH.md     # Source mapping
└── ...                                  # Other docs
```

## Change Process

1. When modifying production code, check if related documentation needs updating.
2. When documentation is found to conflict with code, update the documentation (not the code).
3. When creating new subsystems, create corresponding documentation.
4. When consolidating documents, mark originals as superseded.
5. Run `grep -rn "TODO\|FIXME\|OUTDATED" docs/` periodically to catch stale content.
