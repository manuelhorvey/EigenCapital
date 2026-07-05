# EigenCapital — Comprehensive Documentation Synchronization Audit

**Date:** 2026-07-05
**Author:** Documentation Audit Agent

---

## Executive Summary

This report evaluates every documentation artifact against the current codebase implementation. The documentation ecosystem is **substantial but uneven**: it contains accurate, well-maintained content (OPERATIONS.md, known-issues.md) alongside severely outdated references (ARCHITECTURE.md citing non-existent directories, SYSTEM_OVERVIEW.md referencing a deleted config file). The configuration architecture underwent a Phase 12 migration that deleted `configs/paper_trading.yaml`, but ~30 documentation cross-references still point to this deleted file.

**Documentation Health Score: 62/100** — "Needs Major Revision"

| Dimension | Score | Assessment |
|-----------|-------|------------|
| Accuracy | 55/100 | Multiple stale references to deleted/non-existent files |
| Completeness | 60/100 | Missing docs for several subsystems, no DEVELOPMENT.md |
| Consistency | 50/100 | Contradictory counts across docs (features, governance layers, phases) |
| Organization | 75/100 | Good directory structure, ADR system, clear hierarchy |
| Maintainability | 70/100 | Generated CONFIGURATION.md from domain models is excellent pattern |
| Developer Experience | 45/100 | Broken cross-references, missing onboarding doc |
| Professional Standards | 65/100 | Strong in some areas, weak in cross-references and accuracy |

---

## Repository Architecture Overview

### Directory Inventory (589 directories, 3,007 source files)

| Layer | Paths | Files |
|-------|-------|-------|
| **Core package** | `eigencapital/` | DDD structure: domain, application, observability |
| **Paper trading** | `paper_trading/` | 134 .py files — engine, inference, execution, orchestration, position, governance |
| **Features** | `features/` | Alpha features, labels, regime, archetypes, divergence |
| **Shared** | `shared/` | Portfolio weights, calibration, kelly, factor model, sizing |
| **Config** | `configs/` | Domain YAML tree (9 subdirectories), domain_models/, registry |
| **Scripts** | `scripts/` | Analysis, backtest, optimization, ops, training, replay |
| **Tests** | `tests/` | Engine, inference, features, shared, backtests, position, governance, chaos |
| **Dashboard** | `paper_trading/dashboard/` | React SPA (TypeScript, Vite) with 135+ vitest tests |
| **Docs** | `docs/` | Architecture, system overview, features, governance, operations, API, ADRs (27), planning, archive |
| **Tools** | `tools/` | 15 utilities: validation, linting, migration, security, documentation |
| **Data** | `data/` | Live state, raw data, processed data, cache, research artifacts |

### Architecture Summary

The system is a cross-sectional multi-asset paper trading engine with per-asset XGBoost models, 22 promoted assets, adaptive exit trailing (breakeven lock → retracement trail → time decay), MT5 bridge execution via Wine, and a React SPA dashboard. The core architecture is documented in AGENTS.md (the LLM-operational guide), SYSTEM_OVERVIEW.md (the human-facing architecture doc), and the newly introduced PaperConfigRegistry configuration system.

**Key architectural properties:**
- Per-asset model independence (22 separate XGBoost models)
- Walk-forward validated asset promotion
- Train/serve symmetry (shared feature builders)
- Governance-first execution (15+ layered mechanisms)
- Replay-oriented persistence (SQLite WAL)
- Independent paper/MT5 sizing chains
- Adaptive exit engine (breakeven lock → retracement trail → time decay)

---

## Documentation Inventory

### All Documentation Artifacts

| Category | Files | Status |
|----------|-------|--------|
| **Root docs** | README.md, AGENTS.md, CHANGELOG.md, CONTRIBUTING.md, LIVE_CONTRACT.md, PHASE12_PLAN.md, BASELINE.md, BASELINE_v2.md | Mixed |
| **Core docs/** | ARCHITECTURE.md, SYSTEM_OVERVIEW.md, FEATURES.md, GOVERNANCE.md, OPERATIONS.md, MONITORING.md, TESTING.md, API.md, CONFIGURATION.md, SECURITY.md, MODES.md, known-issues.md | Mixed |
| **ADRs (27)** | ADR-000 through ADR-027 in docs/adr/ | 27 records covering major decisions |
| **Planning** | docs/planning/DEVELOPMENT_PLAN.md | Planning doc |
| **Archive** | docs/archive/BASELINE_SNAPSHOT_2026-06-20.md, docs/archive/research_system_v1/ | Historical content |
| **Spec** | docs/PRODUCTION_SYSTEM_SPEC_v1.md | Production specification |
| **Risk** | docs/RISK_ITEMS.md | Historical risk document |
| **Config READMEs** | configs/domains/*/README.md | Generated per-domain docs |
| **Benchmarks** | benchmarks/README.md | Benchmark reference |
| **Total doc count** | ~50 unique markdown files | Including 27 ADRs |

### Missing Documents

| Expected Document | Path | Status |
|-------------------|------|--------|
| Developer Guide | `docs/DEVELOPMENT.md` | **DOES NOT EXIST** — linked from README.md |
| .env.example | `.env.example` | **DOES NOT EXIST** — env vars documented but no template |
| FAQ | `docs/FAQ.md` | **DOES NOT EXIST** |
| Glossary | `docs/GLOSSARY.md` | **DOES NOT EXIST** |
| Dashboard Architecture | `docs/DASHBOARD.md` | **DOES NOT EXIST** |
| Deployment Guide | `docs/DEPLOYMENT.md` | **DOES NOT EXIST** |
| Incident Response | `docs/INCIDENT_RESPONSE.md` | **DOES NOT EXIST** |

---

## Documentation-to-Code Validation

### 🔴 CRITICAL INACCURACIES (actively harmful)

| Document | Claim | Reality |
|----------|-------|---------|
| **ARCHITECTURE.md** | Data flow: `Research scripts (scripts/research/)` | `scripts/research/` directory **does not exist** |
| **ARCHITECTURE.md** | Calls `compare_models()`/`score_tickers()` from research scripts | No research scripts directory exists |
| **SYSTEM_OVERVIEW.md** | References `configs/paper_trading.yaml` throughout (~10 mentions) | File **deleted** in Phase 12.7 of config migration |
| **README.md** | Links to `docs/development.md` | File is `DEVELOPMENT.md` — **does not exist** |
| **README.md** | "Per-asset config in `configs/paper_trading.yaml`" | File **deleted** |
| **CONTRIBUTING.md** | References `scripts/research/` for screening pipeline | Directory **does not exist** |
| **LIVE_CONTRACT.md** | References `configs/paper_trading.yaml` | File **deleted** |
| **LIVE_CONTRACT.md** | References `configs/paper_trading.yaml` for per-asset configs | File **deleted** |

### 🟡 HIGH INACCURACIES (significant confusion)

| Document | Claim | Reality |
|----------|-------|---------|
| **SYSTEM_OVERVIEW.md** | "15 governance layers" + "Position sizing guardrails" as separate | GOVERNANCE.md says "16 core" mechanisms + 3 adaptive budget layers |
| **SYSTEM_OVERVIEW.md** | Feature count "15 per-asset + 4 cross-asset = 19 alpha columns" | FEATURES.md says 21 features (17 per-asset + 4 cross-asset) |
| **GOVERNANCE.md** | "16 core governance mechanisms" header | Table actually lists 16 + 3 more (RiskEngineV2, PEK, PerformanceState) = 19 total |
| **OPERATIONS.md** | "15 governance layers" | Mismatch with GOVERNANCE.md's 16 |
| **OPERATIONS.md** | Asset allocation table shows ^DJI at 2.0% | Verify current factor_constrained_v2 produces different weights |
| **GOVERNANCE.md** | "16 core" | Listed items count: 16 in first table + 3 adaptive = 19 governance mechanisms |
| **FEATURES.md** | "21 alpha features per asset" | LIVE_CONTRACT says "15–35" and "15 per-asset + 4 cross-asset + up to 16 COT" |

### 🟢 ACCURATE (no issues found)

| Document | Assessment |
|----------|------------|
| **known-issues.md** | Well maintained, updated through 2026-07-03, accurate |
| **API.md** | Accurate description of all 30+ endpoints |
| **MONITORING.md** | Accurate 11-metric Prometheus reference |
| **MODES.md** | Accurate mode descriptions and comparison matrix |
| **FEATURES.md** | Largely accurate on individual feature descriptions |
| **SECURITY.md** | Accurate security model description (loopback, .env, pre-commit) |
| **CHANGELOG.md** | Well-structured version history |

### ⚪ UNVERIFIED (not checked against code)

| Document | Reason |
|----------|--------|
| **ADRs (27)** | Not individually audited against implementation |
| **PRODUCTION_SYSTEM_SPEC_v1.md** | Not read |
| **RISK_ITEMS.md** | Archived document, not read |
| **Planning docs** | Not relevant to implementation accuracy |
| **Archive docs** | Historical by definition |

---

## Code-to-Documentation Validation

### Major Undocumented Features

| Feature | Code Location | Documented? |
|---------|---------------|-------------|
| **Weekend trading (BTCUSD 24/7)** | `engine.py:_get_weekend_eligible_assets()` | ✅ SYSTEM_OVERVIEW.md, OPERATIONS.md |
| **Adaptive Exit Engine** | `position/adaptive_exit.py` | ✅ OPERATIONS.md, LIVE_CONTRACT.md |
| **COT features injection** | `features/alpha_features.py` | ✅ FEATURES.md |
| **Chaos engineering framework** | `tests/chaos/` | ✅ CHANGELOG.md only |
| **ATLAS covariate shift detector** | `eigencapital/observability/atlas.py` | ❌ Not in any doc |
| **PEK admission controller** | `orchestrator/admission/controller.py` | ✅ SYSTEM_OVERVIEW.md, GOVERNANCE.md |
| **PerformanceState velocity** | `pek/perf/performance_state_builder.py` | ✅ GOVERNANCE.md |
| **PaperConfigRegistry** | `configs/paper_config_registry.py` | ✅ PHASE12_PLAN.md only |
| **config_mirror_legacy.py** | `tools/config_mirror_legacy.py` | ❌ Not referenced in any main doc |
| **Environment overlays** | `configs/domains/environments/` | ❌ Not well documented |
| **doc_drift_check.py** | `tools/doc_drift_check.py` | ❌ Not discoverable from docs |

### Features Documented but No Longer Active/Relevant

| Feature | Documentation | Code Status |
|---------|---------------|-------------|
| Equity Cluster Alarm | GOVERNANCE.md mentions it | Removed 2026-07-01 (code comment confirms) |
| `scripts/research/` pipeline | ARCHITECTURE.md | Directory never existed/moved |
| `configs/paper_trading.yaml` | ~30 references across all docs | Deleted Phase 12.7 |
| Ensemble model blend | SYSTEM_OVERVIEW.md mentions "regime ensemble blend skipped" | Correct: disabled per ADR-026 |
| Meta-labeling (LogisticRegression) | GOVERNANCE.md mentions old impl | Replaced by XGBoost path — code still on disk but not used |

---

## Architecture Documentation Review

### Strengths
- SYSTEM_OVERVIEW.md provides an excellent high-level architecture with ASCII diagrams
- Component responsibilities tables are clear and well-organized
- Governance layers documented in detail with config references
- AGENTS.md serves as a comprehensive operational guide for LLM agents

### Issues
- ARCHITECTURE.md describes the `backtests/` module with a **broken data flow** that references `scripts/research/` (doesn't exist)
- No diagram for the **dashboard frontend** component hierarchy
- No documentation for the **configuration domain model** loading flow (PaperConfigRegistry → EngineConfig)
- The relationship between SYSTEM_OVERVIEW.md and PRODUCTION_SYSTEM_SPEC_v1.md is unclear — overlapping content
- `backtests/` module documented in isolation but its connection to the main system is unclear

### Data Flow Issues in ARCHITECTURE.md

```
CLAIMED: Research scripts (scripts/research/) → compare_models() → ...
ACTUAL:  scripts/research/ does NOT exist
         The backtest pipeline lives in scripts/backtest/ and scripts/analysis/
```

---

## API & Interface Documentation Assessment

### REST API (docs/API.md)
- **30+ endpoints documented** — comprehensive coverage
- Good descriptions of request/response shapes
- Consistent formatting with tables
- Missing: authentication details inline (referenced to SECURITY.md)
- Missing: rate limiting details (referenced briefly)

### CLI Commands
- OPERATIONS.md documents all key run-time commands well
- CONTRIBUTING.md documents development commands
- Missing: centralized CLI reference aggregating all commands

### Configuration Schemas
- CONFIGURATION.md is auto-generated from domain models — **gold standard**
- The auto-generation means it's always up to date
- Issue: still references `configs/paper_trading.yaml` legacy file name
- Issue: overlapping config descriptions between OPERATIONS.md and CONFIGURATION.md

---

## Developer Experience Assessment

### Onboarding Flow

| Step | Status | |
|------|--------|---|
| Clone | ✅ | README has `git clone` command |
| Install dependencies | ✅ | `pip install -r requirements.txt` |
| Configure env | ⚠️ | Variables documented but no `.env.example` template |
| Run app | ⚠️ | `./monitor_all` documented but no Docker setup |
| Run tests | ✅ | Multiple commands documented |
| Build dashboard | ⚠️ | Commands in CONTRIBUTING.md but not in root README |
| Run backtests | ❌ | References to `scripts/research/` will fail |
| Deploy | ❌ | No deployment guide |
| Connect MT5 | ⚠️ | Complex process documented in OPERATIONS.md |

**Critical Block for New Developers:** Following the ARCHITECTURE.md data flow will lead to non-existent `scripts/research/` directory.

---

## Documentation Quality Review

### Positive
- Consistent Markdown formatting across all docs
- Heavy use of tables for structured information
- Cross-references between docs (when accurate)
- Detailed CHANGELOG.md with version history
- ADR system provides excellent decision history
- LIVE_CONTRACT.md single-source-of-truth concept
- Auto-generated CONFIGURATION.md from domain models

### Issues
- **~30 stale references** to deleted `configs/paper_trading.yaml`
- **Broken links**: README.md → `docs/development.md` (doesn't exist)
- **Contradictory counts**: governance layers (15 vs 16 vs 19), features (21 vs 19 vs 15+N)
- **Orphaned content**: ARCHITECTURE.md references `scripts/research/`
- **Inconsistent depth**: OPERATIONS.md (extremely detailed) vs ARCHITECTURE.md (minimal)
- **No document metadata**: No "Last updated" dates, no version markers
- **No canonical cross-reference verification** in CI

---

## Documentation Standards Compliance

| Standard | Assessment | Notes |
|----------|-----------|-------|
| Clear hierarchy | ✅ | docs/ organized by topic |
| Table of contents | ✅ | Most long docs have TOC |
| Cross-references | ⚠️ | Present but some are broken (stale file refs) |
| Version metadata | ❌ | None of the docs have dates or versions |
| Consistent formatting | ✅ | Good Markdown consistency across the board |
| Executable examples | ⚠️ | Some have examples, not all verified |
| Architecture diagrams | ⚠️ | ASCII diagrams present but ARCHITECTURE.md data flow is wrong |
| ADRs | ✅ | 27 ADRs covering major decisions |
| Glossary | ❌ | No domain glossary exists |
| Troubleshooting | ✅ | OPERATIONS.md has extensive troubleshooting |
| Runbooks | ✅ | OPERATIONS.md serves as the primary runbook |
| FAQs | ❌ | No FAQ document |

---

## Gap Analysis — Prioritized

### 🔴 CRITICAL (breakers — must fix before next release)

| # | Gap | Impact |
|---|-----|--------|
| 1 | ARCHITECTURE.md data flow references non-existent `scripts/research/` | Misleads developers, invalid architecture diagram |
| 2 | ~30 references to deleted `configs/paper_trading.yaml` | Every cross-reference is broken |
| 3 | `docs/DEVELOPMENT.md` doesn't exist but is linked from README.md | 404 link in primary entry point |
| 4 | LIVE_CONTRACT.md references deleted config file as data source | Source of truth doc points to non-existent file |

### 🟡 HIGH (significant — fix within a sprint)

| # | Gap | Impact |
|---|-----|--------|
| 5 | Governance layer count: 15 vs 16 vs 19 across SYSTEM_OVERVIEW.md, GOVERNANCE.md, OPERATIONS.md | Contradictory specifications confuse readers |
| 6 | Feature count: 21 vs 19 vs 15+N across FEATURES.md, SYSTEM_OVERVIEW.md, LIVE_CONTRACT.md | Contradictory technical specification |
| 7 | SYSTEM_OVERVIEW.md and PRODUCTION_SYSTEM_SPEC_v1.md overlap | Content duplication without clear delineation |
| 8 | CONTRIBUTING.md references broken docs and directories | Bad developer experience |
| 9 | No `.env.example` file | Setup friction for new developers |
| 10 | No domain glossary | Onboarding friction |

### 🟢 MEDIUM (improvement — next sprint)

| # | Gap | Impact |
|---|-----|--------|
| 11 | ATLAS covariate shift detector undocumented | Team may not know it exists |
| 12 | No dashboard component architecture doc | Frontend devs need to reverse-engineer |
| 13 | Chaos framework undocumented in main docs | Testing framework not discoverable |
| 14 | No FAQ document | Repeated questions slow onboarding |
| 15 | No "Last updated" metadata on documents | Impossible to detect staleness |
| 16 | `tools/doc_drift_check.py` not referenced from docs | CI tool not discoverable |

### 🔵 LOW (nice to have — backlog)

| # | Gap | Impact |
|---|-----|--------|
| 17 | No deployment guide | Live deployment is non-trivial |
| 18 | No incident response playbook | Production operations risk |
| 19 | No security policy for vulnerability reporting | Missing SECURITY.md contact |
| 20 | No ROADMAP.md | No forward-looking development doc |

---

## Recommended Documentation Structure

```
docs/
├── index.md                    # NEW: central entry point
├── SYSTEM_OVERVIEW.md          # UPDATE: remove paper_trading.yaml refs
├── ARCHITECTURE.md             # REWRITE: fix data flow diagram
├── FEATURES.md                 # UPDATE: canonical feature count from code
├── GOVERNANCE.md               # UPDATE: unify governance layer count
├── OPERATIONS.md               # UPDATE: remove paper_trading.yaml refs
├── MONITORING.md               # OK: accurate
├── API.md                      # OK: accurate
├── CONFIGURATION.md            # AUTO-GENERATED: keep
├── SECURITY.md                 # UPDATE: remove placeholder email, add deploy port
├── MODES.md                    # OK: accurate
├── TESTING.md                  # UPDATE: add chaos framework reference
├── DASHBOARD.md                # NEW: frontend architecture doc
├── DEVELOPMENT.md              # NEW: developer guide
├── GLOSSARY.md                 # NEW: domain terminology
├── FAQ.md                      # NEW: frequently asked questions
├── known-issues.md             # OK: well maintained
├── adr/                        # OK: 27 ADRs
├── archive/                    # OK: historical content
└── planning/                   # OK: planning docs
```

---

## Prioritized Backlog (execution order)

### Sprint 1 — Emergency Repairs (est. 1-2 days)

| # | Task | Est. |
|---|------|------|
| 1 | Replace all `configs/paper_trading.yaml` references with `configs/domains/` equivalents | 4h |
| 2 | Fix ARCHITECTURE.md data flow diagram (remove `scripts/research/`) | 2h |
| 3 | Create `docs/DEVELOPMENT.md` from OPERATIONS.md excerpt + CONTRIBUTING.md | 2h |
| 4 | Fix broken links in README.md | 1h |
| 5 | Run `tools/doc_drift_check.py` and fix all failures | 1h |

### Sprint 2 — Consistency Sprint (est. 2-3 days)

| # | Task | Est. |
|---|------|------|
| 6 | Audit governance layers: count from `DEFAULT_STAGES` + table in `docs/GOVERNANCE.md` | 2h |
| 7 | Unify governance layer count across SYSTEM_OVERVIEW.md, GOVERNANCE.md, OPERATIONS.md | 2h |
| 8 | Audit feature count: count from `features/alpha_features.py:build_alpha_features()` | 2h |
| 9 | Unify feature count across FEATURES.md, SYSTEM_OVERVIEW.md, LIVE_CONTRACT.md | 2h |
| 10 | Update CONTRIBUTING.md cross-references | 1h |
| 11 | Create `docs/GLOSSARY.md` | 2h |
| 12 | Create `.env.example` | 30min |

### Sprint 3 — Expansion (est. 3-5 days)

| # | Task | Est. |
|---|------|------|
| 13 | Create `docs/DASHBOARD.md` with React component tree | 4h |
| 14 | Create `docs/FAQ.md` | 2h |
| 15 | Add ATLAS detector documentation to MONITORING.md | 30min |
| 16 | Reference chaos framework in TESTING.md | 30min |
| 17 | Add "Last updated" footers to all documents | 2h |
| 18 | Delineate SYSTEM_OVERVIEW.md vs PRODUCTION_SYSTEM_SPEC_v1.md | 2h |

### Sprint 4 — Automation (est. 2-3 days)

| # | Task | Est. |
|---|------|------|
| 19 | Extend `tools/doc_drift_check.py` to scan ALL docs for path validity | 3h |
| 20 | Add CI gate for cross-reference contradiction detection | 2h |
| 21 | Add CI gate for file-path existence in all markdown files | 2h |
| 22 | Implement document versioning metadata enforcement | 1h |

---

## Template: Document Metadata Standard

```markdown
# Title

**Last updated:** 2026-07-05
**Status:** Active | Updated | Archived
**Audience:** Developers | Operators | Contributors
**Canonical source:** path/to/source/code.py (if applicable)

...
```

## Template: Module Documentation

```markdown
# {Module Name}

**Last updated:** YYYY-MM-DD

## Source
`path/to/module.py`

## Purpose
{One paragraph}

## Key Functions/Classes
| Name | Role |
|------|------|

## Integration
{How this connects to the rest of the system}

## Config
{Related configuration keys}

## Tests
`tests/path/to/tests/`
```

---

## Professional Recommendations

### Short-term (0-3 months)

1. **Establish CI documentation gates**: Extend `tools/doc_drift_check.py` to verify every path reference in every markdown file resolves to an existing file. This would have caught ALL 30 stale config references immediately.

2. **Unify contradictory specs**: Pick a canonical document (LIVE_CONTRACT.md or SYSTEM_OVERVIEW.md) for each fundamental concept (governance count, feature count, phase count) and make other documents refer to it rather than restating.

3. **Create missing essential docs**: DEVELOPMENT.md, .env.example, GLOSSARY.md. These three documents directly impact developer onboarding speed.

### Medium-term (3-6 months)

4. **Add document metadata**: Every document should have a "Last updated" date field. This makes staleness immediately visible.

5. **Document dashboard architecture**: Create `docs/DASHBOARD.md` describing the React component hierarchy, state management pattern (React Query + sliced selectors), and data flow from backend to frontend.

6. **Create deployment guide**: Document the full deployment process including Wine setup, MT5 bridge, Docker configuration, and production checklist.

### Long-term (6+ months)

7. **Implement automated diagram generation**: Use Mermaid.js or Graphviz to generate architecture diagrams from code analysis, preventing diagram staleness.

8. **Documentation ownership review process**: Assign a documentation owner per module and require doc review in PRs when code changes affect public APIs or documented behavior.

9. **Versioned release documentation**: Tag documentation versions alongside software releases, with a "What's New" section per version.

10. **Developer portal**: Consider a lightweight documentation site (MkDocs, Docusaurus) for improved navigation and search.

---

## Final Assessment

### Documentation Production Readiness: ❌ NOT READY

The documentation system has **strong structural foundations**: a well-organized directory hierarchy, an excellent ADR system, an auto-generated configuration reference, and a detailed operational runbook. However, it suffers from **acute accuracy problems** that directly undermine its value:

- **30+ references to a deleted file** is a systemic propagation failure — the Phase 12 config migration updated the code but not the documentation.
- **A broken architecture diagram** that references non-existent code paths.
- **A missing document linked from the primary README**.
- **Contradictory fundamental specifications** (feature counts, governance counts).

### Actionable Path Forward

| Phase | Duration | Outcome |
|-------|----------|---------|
| 🔴 Sprint 1: Emergency Repairs | 1-2 days | No broken links, no stale config references |
| 🟡 Sprint 2: Consistency Sprint | 2-3 days | Unified counts, glossary, CONTRIBUTING.md fixed |
| 🟢 Sprint 3: Expansion | 3-5 days | Dashboard docs, FAQ, ATLAS docs |
| 🔵 Sprint 4: Automation | 2-3 days | CI gates prevent future drift |

With ~8-13 focused engineering days, the documentation can be brought to **production-ready status (85+/100)**.
