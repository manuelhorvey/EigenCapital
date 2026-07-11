# EigenCapital — Documentation Improvement Plan

> **Derived from:** `docs/audit/documentation_sync_audit_2026-07-05.md`
> **Status:** Living document — update as sprints progress
> **Last updated:** 2026-07-05

---

## Current State: What's Been Completed

The documentation synchronization audit identified **22 actionable items** across 4 sprints. The following are now **resolved**:

### Sprint 1 — Emergency Repairs ✅ DONE

| Item | Status | Notes |
|------|--------|-------|
| Fix ~30 stale `configs/paper_trading.yaml` refs | ✅ DONE | Updated across SYSTEM_OVERVIEW.md, OPERATIONS.md, FEATURES.md, GOVERNANCE.md, MODES.md, SECURITY.md, LIVE_CONTRACT.md, README.md, docs/README.md, CONTRIBUTING.md |
| Fix ARCHITECTURE.md data flow | ✅ DONE | Replaced `scripts/research/` → `scripts/backtest/` |
| Create `docs/DEVELOPMENT.md` | ✅ DONE | Covers setup, run, test, build, deploy |
| Fix broken links in README.md | ✅ DONE | Fixed `docs/development.md` → `docs/DEVELOPMENT.md` |
| Run `doc_drift_check.py` | ✅ DONE | All checks pass |

### Sprint 2 — Consistency Sprint ✅ DONE

| Item | Status | Notes |
|------|--------|-------|
| Unify governance layer count | ✅ DONE | SYSTEM_OVERVIEW.md aligned with GOVERNANCE.md (16 core + 3 adaptive) |
| Unify feature count | ✅ DONE | ~21 updated across FEATURES.md, SYSTEM_OVERVIEW.md, LIVE_CONTRACT.md |
| Update CONTRIBUTING.md | ✅ DONE | References AGENTS.md as primary operational guide |
| Create `docs/GLOSSARY.md` | ✅ DONE | 80+ terms across 12 categories + acronym table |
| Create `.env.example` | ✅ DONE | All env vars documented with organized sections |

---

## Remaining Work

### Sprint 3 — Expansion (est. 2–3 days)

#### #3.1 DASHBOARD.md — Frontend Architecture Document

**Why:** New frontend developers currently reverse-engineer the React component tree. A dashboard architecture doc would reduce onboarding time from days to hours.

**Scope:**
- React component hierarchy (AppShell → CommandCenter → workspace pages)
- State management pattern (React Query + sliced selectors from `useSystemSnapshot`)
- Data flow from backend (`state.json`) → TypeScript types → React hooks → components
- Route structure (`/`, `/trading`, `/execution`, `/risk`) and per-route responsibilities
- Visual design tokens (operator-console theme: mono supremacy, single emerald accent)
- Key components: TickerRail, EquityCurveSparkline, ExecutionQualityStrip, PSI Drift Panel, etc.

**Risk:** Low — documentation only. Requires reading the dashboard source to extract component tree.

**Estimate:** 2–3 hours

---

#### #3.2 FAQ.md — Frequently Asked Questions

**Why:** Repeated questions (mode switching, retrain timing, MT5 connection issues, dashboard interpretation) fragment across Slack/README.md/known-issues. An FAQ consolidates them.

**Scope:**
- How do I switch modes? → Edit mode file in `configs/domains/modes/` and restart
- When do models retrain? → Annual (January 1), or forced via `retrain_all_fixed.py`
- How do I interpret the SELL_ONLY filter behavior? → 6 assets with inverted BUY signal
- What does "bar-jump suppression" mean? → Data source switch detected, 60min pause
- How do I know if the dashboard connection is healthy? → ConnectionStatus bar shows Live/Degraded/Offline
- How is the risk budget calculated? → PEK admission controller with adaptive scaling
- What should I check each morning? → Daily procedure from OPERATIONS.md
- Can I run the system without MT5? → Yes, PaperBroker works standalone
- How do I add a new asset? → Create per-asset YAML + MT5 symbol map + train model
- What does "CLSD" mean on the dashboard? → Market closed; BTCUSD continues 24/7

**Risk:** Low — collates existing knowledge.

**Estimate:** 1–2 hours

---

#### #3.3 ATLAS Detector Documentation

**Why:** `eigencapital/observability/atlas.py:AtlasDetector` is a production monitoring component with zero documentation. Engineers may deploy without knowing it exists.

**Scope:**
- Add a section to `docs/MONITORING.md` (or create dedicated `docs/ATLAS.md`)
- Document: three detection methods (CUSUM, Page-Hinkley, KS test)
- Integrations: which features it monitors, where results are exposed
- Dashboard display (if any) for ATLAS events

**Files to modify:** `docs/MONITORING.md` or new `docs/ATLAS.md`

**Estimate:** 30 minutes

---

#### #3.4 Chaos Framework Reference in TESTING.md

**Why:** The chaos framework (`tests/chaos/chaos_tools.py`) is discoverable only by browsing the tests directory. Adding a reference in `docs/TESTING.md` makes it discoverable.

**Scope:**
- Add "Chaos Testing" section to `docs/TESTING.md`
- Document: `FaultRecipe`, `fault_inject` context manager, use cases (transient disconnect, latency simulation)

**Files to modify:** `docs/TESTING.md`

**Estimate:** 20 minutes

---

#### #3.5 "Last Updated" Metadata

**Why:** Zero documents have "Last updated" dates (except the audit and DEVELOPMENT.md). Staleness can only be detected by reading every file.

**Scope:**
- Add `**Last updated:** 2026-07-05` footer to every active documentation file
- Files to update: SYSTEM_OVERVIEW.md, ARCHITECTURE.md, FEATURES.md, GOVERNANCE.md, OPERATIONS.md, MONITORING.md, TESTING.md, API.md, SECURITY.md, MODES.md, known-issues.md, README.md, CONTRIBUTING.md, LIVE_CONTRACT.md, CHANGELOG.md, PHASE12_PLAN.md, configs/README.md
- Skip: archive docs, ADRs (dated by filename), audit report

**Risk:** Low but repetitive. Good candidate for a script or sed batch.

**Estimate:** 30 minutes

---

#### #3.6 SYSTEM_OVERVIEW vs PRODUCTION_SYSTEM_SPEC Delineation

**Why:** Both documents cover the same high-level architecture but at different depths. New readers don't know which to read first.

**Scope:**
- Add a note at the top of SYSTEM_OVERVIEW.md: "For the production system specification (scope, constraints, P0–P4 framework), see PRODUCTION_SYSTEM_SPEC_v1.md"
- Add a note at the top of PRODUCTION_SYSTEM_SPEC_v1.md: "For the day-to-day operational system overview, see SYSTEM_OVERVIEW.md"

**Files to modify:** `docs/SYSTEM_OVERVIEW.md`, `docs/PRODUCTION_SYSTEM_SPEC_v1.md`

**Estimate:** 10 minutes

---

### Sprint 4 — Automation & CI (est. 2–3 days)

#### #4.1 MAINTAINERS.md — Maintainer's Guide

**Why:** The user specifically requested a maintainers document. The current CONTRIBUTING.md covers contributor workflow but doesn't document maintainer responsibilities: review criteria, release process, CI failure triage, dependency update cadence, security advisory process.

**Scope:**
- PR review criteria (merge vs request changes vs close)
- Release process (tagging, changelog updates, model sidecar hashes)
- CI failure triage (which failures are blockers vs flakes)
- Dependency update cadence (weekly minor, monthly major)
- Security advisory process (who to contact, response SLA)
- On-call rotation (if any)

**Estimate:** 2 hours

---

#### #4.2 Extend doc_drift_check.py for Path Validity

**Why:** The current `doc_drift_check.py` only checks asset-list and SELL_ONLY consistency against config. It does NOT verify that every file path referenced in markdown files actually exists. This would have caught ALL 30 stale `paper_trading.yaml` references automatically.

**Scope:**
- Add a `check_markdown_paths()` function that extracts all `path/to/file` references from markdown files and verifies they resolve
- Exclude intentional dead paths (archive docs, ADR historical refs)
- Wire into CI step in `.github/workflows/ci.yml`

**Files to modify:** `tools/doc_drift_check.py`, `.github/workflows/ci.yml`

**Estimate:** 2–3 hours

---

#### #4.3 CI Gate for Cross-Reference Contradiction Detection

**Why:** The audit found contradictory numbers (governance layers: 15 vs 16 vs 19; features: 21 vs 19 vs 15+N). A CI gate that compares key metrics across docs would prevent this from recurring.

**Scope:**
- Define a schema of canonical numeric facts and their source of truth
- Add a `check_metric_consistency()` function to `doc_drift_check.py` (or new tool)
- Example: `governance_layers: 16` (source: GOVERNANCE.md) → SYSTEM_OVERVIEW.md and OPERATIONS.md must agree
- Example: `feature_count_range: "~21"` (source: FEATURES.md) → other docs must use same range

**Files to modify:** `tools/doc_drift_check.py`, `.github/workflows/ci.yml`

**Estimate:** 2–3 hours

---

#### #4.4 Document Versioning Metadata Enforcement

**Why:** Without "Last updated" dates, staleness is invisible. A CI check can enforce that every active doc has a date field and flag docs unchanged for >6 months.

**Scope:**
- Add `check_last_updated_dates()` function to `doc_drift_check.py`
- Require `**Last updated:** YYYY-MM-DD` pattern in every markdown file in `docs/` (excluding archive)
- Flag files where date is >180 days old as WARNING
- Block merges where date is missing entirely

**Files to modify:** `tools/doc_drift_check.py`, `.github/workflows/ci.yml`

**Estimate:** 1–2 hours

---

## Summary: Remaining Backlog

| Priority | Item | Est. Time | Dependencies |
|----------|------|-----------|--------------|
| 🔴 High | FAQ.md | 1–2h | None |
| 🔴 High | MAINTAINERS.md | 2h | None |
| 🔴 High | DASHBOARD.md | 2–3h | Understanding dashboard source |
| 🟡 Medium | ATLAS detector docs | 30min | Reading atlas.py |
| 🟡 Medium | Chaos framework in TESTING.md | 20min | None |
| 🟡 Medium | "Last updated" metadata | 30min | None |
| 🟡 Medium | SYSTEM_OVERVIEW ↔ SPEC delineation | 10min | None |
| 🟢 Low | doc_drift_check path validation | 2–3h | Understanding markdown parsing |
| 🟢 Low | CI cross-reference gate | 2–3h | Schema design |
| 🟢 Low | Document versioning enforcement | 1–2h | Date format spec |

**Total remaining:** 12–17 hours across 10 items

## Recommended Execution Order

### Sprint 3a — Quick Wins (1 session, ~3h)
1. SYSTEM_OVERVIEW ↔ SPEC delineation (10min)
2. Chaos framework in TESTING.md (20min)
3. ATLAS detector docs (30min)
4. "Last updated" metadata on all docs (30min)
5. FAQ.md (1–2h)

### Sprint 3b — Expansion (1–2 sessions, ~5h)
6. DASHBOARD.md (2–3h)
7. MAINTAINERS.md (2h)

### Sprint 4 — Automation (1–2 sessions, ~5h)
8. doc_drift_check path validity (2–3h)
9. CI cross-reference gate (2–3h)
10. Document versioning enforcement (1–2h)
