# EigenCapital — Maintainer's Guide

**Last updated:** 2026-07-05

> This document covers maintainer responsibilities, release process, CI triage,
> dependency management, and security advisories. For contributor workflow, see
> [`CONTRIBUTING.md`](../CONTRIBUTING.md). For the operational runbook, see
> [`docs/OPERATIONS.md`](OPERATIONS.md).

---

## Table of Contents

- [PR Review Criteria](#pr-review-criteria)
- [Release Process](#release-process)
- [CI Failure Triage](#ci-failure-triage)
- [Dependency Management](#dependency-management)
- [Security Advisories](#security-advisories)
- [Documentation Maintenance](#documentation-maintenance)
- [Model Retrain Cadence](#model-retrain-cadence)
- [On-Call Responsibilities](#on-call-responsibilities)

---

## PR Review Criteria

### Merge requirements

A PR must satisfy all of the following before merging to `main`:

| Check | Enforcement | Exceptions |
|-------|-------------|------------|
| Python tests pass | CI `test` job | No |
| Dashboards tests pass | CI `test` job | No |
| Ruff lint + format | CI `lint` job | No |
| Config schema valid | CI `lint` job | Skipped on pure frontend changes |
| Import firewall | CI `lint` job | No |
| Doc drift check | CI `lint` job | Skipped on pure code changes |
| No bare asserts | CI `lint` job | Test files excluded |
| No plaintext secrets | CI `lint` job | Test fixtures excluded |
| TypeScript type-check | CI `lint` job | Skipped on pure Python changes |
| Coverage ≥ 70% | CI `test` job | Hot paths exempted by `# pragma: no cover` |

### Review depth by change type

| Change Type | Reviewer Focus | Required Approvals |
|-------------|---------------|-------------------|
| Bug fix (1-50 lines) | Correctness, test coverage, invariant check | 1 |
| Bug fix (50+ lines) | Correctness, test coverage, regression risk, invariant check | 2 |
| New feature | Architecture alignment, test coverage, documentation, config schema | 2 |
| Refactor (module-level) | No behavior change, test pass rate preserved, no uncovered branches | 1 |
| Refactor (cross-module) | Import boundary checks, no circular deps, test pass rate | 2 |
| Config changes | Schema validation, cross-field invariants, mirror check | 1 |
| Documentation only | Accuracy, no broken links, formatting | 1 |
| CI/Infrastructure | Security, determinism, no hardcoded secrets, no `latest` tags | 1 |

### PR size guidelines

- **Small**: < 100 lines changed — preferred for most changes
- **Medium**: 100-500 lines — acceptable with clear scope
- **Large**: 500+ lines — must be justified. Prefer splitting into stacked PRs

### Reviewer responsibilities

1. Verify the PR description explains **what** and **why** (not just code diff)
2. Check that tests cover the change (not just existing tests pass)
3. Verify any uncovered invariants are documented in `LIVE_CONTRACT.md`
4. Check for stale documentation references (the `tools/doc_drift_check.py` CI gate
   catches path-level staleness; check for semantic drift manually)
5. Ensure no `TODO`/`FIXME` markers are introduced without a linked issue
6. For ML changes: verify walk-forward methodology is not broken by the change

---

## Release Process

EigenCapital does not follow a fixed release cadence. Releases are triggered
by passable milestones (e.g., a critical fix, a new asset promotion, a
configuration migration).

### Pre-release checklist

1. **All CI passes** — run full pipeline on the release branch
2. **CHANGELOG.md updated** — all changes since last release documented
3. **AGENTS.md known issues updated** — any resolved issues moved to resolved section
4. **LIVE_CONTRACT.md updated** — any architecture changes reflected
5. **Config schema matches** — `python tools/check_config_schema.py` passes
6. **Doc drift check passes** — `python tools/doc_drift_check.py` exits 0
7. **All models trained** — `ls paper_trading/models/*.json` shows expected count

### Release steps

```bash
# 1. Create release branch
git checkout -b release/v<version>

# 2. Update CHANGELOG.md — ensure version, date, and description
#    Use format:
#    ## [<version>] — YYYY-MM-DD
#    ### Added / Changed / Fixed / Removed

# 3. Tag and push
git tag -a v<version> -m "Release v<version>: <short summary>"
git push origin v<version>

# 4. Create GitHub Release from the tag
#    Include a summary of changes (copy from CHANGELOG.md)
```

### Version numbering

`<major>.<minor>.<patch>`

| Bump | When | Example |
|------|------|---------|
| Major | Breaking change (config schema, contract, architecture) | 1.0.0 → 2.0.0 |
| Minor | New feature, asset promotion, new governance layer | 1.0.0 → 1.1.0 |
| Patch | Bug fix, documentation, CI, tests | 1.0.0 → 1.0.1 |

### Hotfix process

For critical bugs in production:

```bash
git checkout -b hotfix/<description> main
# Fix + test
git push origin hotfix/<description>
# Create PR — fast-track review (1 reviewer, can merge with CI green)
```

---

## CI Failure Triage

### Common CI failures and first actions

| Failure | Likely Cause | First Action |
|---------|-------------|--------------|
| `ruff check` fails | Lint errors in new/changed code | Run `ruff check .` locally and fix |
| `ruff format` fails | Formatting drift | Run `ruff format .` and commit |
| Config schema fails | YAML syntax or cross-field violation | Run `tools/check_config_schema.py` |
| Doc drift check fails | Asset list or SELL_ONLY mismatch | Run `tools/doc_drift_check.py` — tells you what's wrong |
| Config mirror drift | Domain tree and mirror out of sync | Run `tools/config_mirror_legacy.py --check` |
| Python tests fail | Logic regression or test fixture issue | Check which tests fail; run `pytest -x` locally |
| Dashboard tests fail | TypeScript error or component regression | Run `npx tsc -b --noEmit` + `npx vitest run` |
| Coverage < 70% | New code lacks test coverage | Add tests for uncovered paths |
| Bandit SAST | Security concern flagged | Check bandit output — most are medium-severity (paper trading risk) |
| Import firewall | Cross-module boundary violation | Move import to allowed module |

### Flaky tests

If a test fails intermittently:

1. Check if it's in `tests/temporal/` (differential leakage — sensitive to random seeds)
2. Check if it's in `tests/chaos/` (fault injection — expected to test failure modes)
3. Check if it's a timing test (e.g., `test_wal_concurrency`) — may need timeout adjustment
4. If consistently flaky across 3+ runs, mark with `@pytest.mark.flaky` and file a fix issue

### CI is red — who fixes it?

| Scenario | Owner |
|----------|-------|
| PR author's change caused the failure | PR author |
| In-flight PR conflicting with main | PR author rebases |
| Infrastructure failure (runner, network) | Any maintainer with access |
| Pre-existing failure on main | Primary maintainer files a fix issue |

---

## Dependency Management

### Python dependencies

Dependencies are tracked in `pyproject.toml` (`[project.dependencies]` for
runtime, `[project.optional-dependencies]` for dev). A locked `requirements.lock`
is committed for deterministic installs.

| Action | Command |
|--------|---------|
| Add runtime dependency | `pip install <pkg> && pip freeze | grep <pkg> >> requirements.in` (then sort) |
| Add dev dependency | Add to `[project.optional-dependencies.dev]` in `pyproject.toml` |
| Update all deps | `pip install -e ".[dev]" --upgrade && pip freeze > requirements.lock` |
| Security audit | `pip-audit` — runs in CI (non-blocking) |

### Dashboard dependencies

```bash
cd paper_trading/dashboard
npm ci              # Clean install from lockfile
npm update          # Update within semver range
npm install <pkg>   # Add new dependency
```

### Update cadence

| Dependency Type | Update Frequency | Risk Level |
|-----------------|-----------------|------------|
| Python runtime | Monthly minor, quarterly major | Medium — test suite catches regressions |
| Python dev | Quarterly | Low — no production impact |
| Dashboard (npm) | Monthly | Medium — vitest + tsc catches breaking changes |
| XGBoost | On release — validate walk-forward results | High — numerical changes can affect predictions |

### Dependency freeze policy

Before any production deployment:
1. All Python deps should be frozen to their current versions
2. `requirements.lock` must be committed
3. Dashboard `package-lock.json` must be committed
4. CI must pass on the locked versions

---

## Security Advisories

### Reporting a vulnerability

For non-critical issues (paper trading system, no live capital):
- Open a GitHub issue with the `security` label
- Include: affected component, vulnerability description, proof of concept
- Expected response: 7 days

For critical issues (password exposure, live capital compromise):
- Email: `security@eigencapital.local` (placeholder — set up a real address)
- Encrypted communication preferred (PGP key available on request)
- Expected response: 24 hours

### Current threat model

| Threat | Risk | Mitigation |
|--------|------|-----------|
| MT5 password exposure | Low — demo account ($107) | `.env` permission check, no argv leak |
| Dashboard access | Low — loopback bound | Optional bearer token auth |
| Model theft | Low — no financial value | Gitignored model files |
| Config tampering | Low — git-controlled | `config_mirror_legacy.py --check` in CI |
| Dependency vuln | Low — paper trading | `pip-audit` in CI (non-blocking) |

### Vulnerability disclosure policy

1. Reporter submits issue via appropriate channel
2. Maintainer triages within stated response time
3. Fix is developed on a private branch
4. Fix is merged with a `fix(security)` conventional commit
5. Release is published with the fix documented in CHANGELOG.md

---

## Documentation Maintenance

Documentation is updated as part of the PR process. See the audit report at
`docs/audit/documentation_sync_audit_2026-07-05.md` for the full backlog.

### When to update which document

| Document | Update When | Owner |
|----------|------------|-------|
| `LIVE_CONTRACT.md` | Architecture changes, config schema changes | PR author |
| `AGENTS.md` | New features, fixed issues, operational changes | PR author |
| `docs/SYSTEM_OVERVIEW.md` | Architecture changes, new components | PR author |
| `docs/GOVERNANCE.md` | Governance layer changes | PR author |
| `docs/API.md` | New/modified endpoints | PR author |
| `docs/GLOSSARY.md` | New domain terms introduced | PR author |
| `docs/OPERATIONS.md` | Operational procedure changes | PR author |
| `CHANGELOG.md` | Every merged PR | Maintainer at release time |
| `docs/FAQ.md` | When the same question comes up 3+ times | Any maintainer |

### Documentation quality checks

Run before every release:

```bash
PYTHONPATH=$PYTHONPATH:. python tools/doc_drift_check.py
ruff check . && ruff format . --check
# Manual check: do the docs still describe the current system?
```

---

## Model Retrain Cadence

### Scheduled retrains

| Cadence | Schedule | Scope |
|---------|----------|-------|
| Annual | January 1 | Full retrain — all 22 assets, new labels from updated config |
| Ad-hoc | As needed | Specific asset(s) — e.g., after config change or bug fix |

### Retrain procedure

```bash
# Full retrain
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py

# Regenerate walk-forward signal parquets
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/walk_forward_backtest.py

# Retrain calibration models from new parquets
PYTHONPATH=$PYTHONPATH:. python scripts/training/train_calibration.py

# Verify model count matches
ls paper_trading/models/*.json | wc -l
# Should match config asset count (22)

# Update model hash sidecars (for doc drift check)
# Hash files are generated by the training pipeline
```

### Model validation after retrain

After retrain, validate:
1. Walk-forward metrics for each asset (IC positive, total_R positive)
2. No asset lost profitability (compare to pre-retrain baseline)
3. Feature stability (Jaccard similarity of top-10 features vs prior retrain)
4. PSI baseline persisted correctly

---

## On-Call Responsibilities

For the person monitoring the paper trading system:

### Normal hours (market open, Mon–Fri)

| Time | Task | Duration |
|------|------|----------|
| 08:30 ET | Morning check: dashboard, signals, MT5 status, narrative | 15min |
| Throughout the day | Monitor alerts: governance halts, PSI-SEVERE, position concentration | Occasional |
| 17:00 ET | End-of-day summary: log daily summary, check narrative | 10min |

### Weekly tasks

| Day | Task | Duration |
|-----|------|----------|
| Monday | Confirm macro narrative (check NARR PENDING button) | 5min |
| Monday | Liquidity regime check | 5min |
| Friday | End-of-week position check before weekend mode | 10min |

### Escalation

| Issue | Escalate To | Response Time |
|-------|-----------|---------------|
| Engine crash | Primary maintainer | 4 hours |
| MT5 bridge down | Primary maintainer | 8 hours |
| Dashboard down | Primary maintainer | 8 hours |
| Model degredation detected (PSI halt, validity RED) | Primary maintainer + model owner | 24 hours |
| Security vulnerability | Primary maintainer | 24 hours |

---

## Project Standards

### Coding standards

See `CONTRIBUTING.md` for full standards. Summary:

- Python: `ruff check . && ruff format .` — both must pass
- TypeScript: `tsc -b --noEmit` — must pass
- Imports: Standard library → third-party → local, blank line between groups
- Types: All public functions must have type annotations (Python 3.10+ syntax)
- Docstrings: Google-style on all public modules and functions
- Logging: Use structured logger (`eigencapital.<module>`), never bare `print()`
- No bare `assert` in production code

### Branch naming

| Prefix | Purpose |
|--------|---------|
| `fix/` | Bug fixes, doc inaccuracies |
| `feat/` | New features |
| `refactor/` | Code restructuring |
| `docs/` | Documentation changes |
| `chore/` | Maintenance, CI, config |
| `hotfix/` | Critical production fixes |

### Commit messages

Conventional commits: `<type>(<scope>): <short description>`
Valid types: `fix`, `feat`, `refactor`, `chore`, `docs`, `test`, `style`, `perf`

---

**Last updated:** 2026-07-05
