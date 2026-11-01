# F-19 — CI and Supply-Chain Hardening

**Status:** `IMPLEMENTED — AWAITING VERIFICATION` (lockfile/hashes follow-up tracked)
**Branch:** `audit/comprehensive-remediation-001`
**Code commit:** `678433b`
**Severity:** Medium · **Phase:** P2
**Date:** 2026-11-01

---

## 1. Finding

GitHub Actions were referenced by tag, not commit SHA; no `permissions` block;
runtime dependencies unpinned; no dependency vulnerability scan;
`Codecov fail_ci_if_error=false`; CI matrix 3.11–3.13 while local review used
3.14.8 (undefined Python support).

## 2. Correction

`.github/workflows/ci.yml`:

- Added top-level `permissions: contents: read`.
- SHA-pinned all `uses` actions:
  - `actions/checkout@11d5960a326750d5838078e36cf38b85af677262` (v4)
  - `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065` (v5)
  - `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020` (v4)
  - `codecov/codecov-action@04b047e8bb82a0c002c8312c1c880fbc6a999d45` (v5)
- Added Python 3.14 to the CI matrix (`"3.11", "3.12", "3.13", "3.14"`),
  matching the locally verified 3.14.8; added the `3.14` trove classifier in
  `pyproject.toml`.
- Added a `pip-audit` dependency-vulnerability scan step after dependency
  installation.

`pyproject.toml`: added `Programming Language :: Python :: 3.14` classifier.

## 3. Items tracked as follow-up (not fabricated)

- **Lockfile / hashes for operational installs:** CI still installs from
  `pyproject.toml` version specifiers (`>=`) without a pinned lockfile or
  per-package hashes. Generating one (`pip-compile` / `pip hash`) requires
  dependency resolution not attempted here; recorded as a tracked follow-up so
  it is not silently dropped.

## 4. Verification executed

- `python -c "import yaml; yaml.safe_load(ci.yml)"` → valid YAML.
- Repo hygiene step (`git ls-files -i -c --exclude-standard`) returns no
  tracked gitignored files.
- `pytest` unit/analytics/live suites pass on local Python 3.14.8 (see F-04,
  F-08, F-09, F-11 records).

GitHub Actions cannot be executed in this offline environment, so the workflow
itself has not been run end-to-end; that verification is deferred to the next
push to `main`/a PR.

## 5. What this does not establish

- No vulnerability scan result is available (pip-audit needs the PyPI advisory
  database at CI time).
- No claim that dependencies are vulnerability-free.
- Capital-readiness decision unchanged.

## 6. Closure decision

`IMPLEMENTED — AWAITING VERIFICATION`. Not `CLOSED`. Lockfile/hashes follow-up
and a green Actions run remain.
