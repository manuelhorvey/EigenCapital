# Contributing to EigenCapital

## Quick Start

```bash
git clone git@github.com:manuelhorvey/EigenCapital.git
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Code Standards

### Python

- **Style**: `ruff check . && ruff format .` — both must pass before commit.
- **Imports**: Standard library → third-party → local, one blank line between groups.
- **Types**: All public functions must have type annotations (Python 3.10+ syntax).
- **Docstrings**: Google-style on all public modules and functions. Module-level docstring required for every `.py` file.
- **Logging**: Use structured logger (`eigencapital.<module>`), never bare `print()`.
- **No bare `assert`** in production code — use `if` + explicit error handling.

### TypeScript / React

```bash
cd paper_trading/dashboard
npm ci
npx tsc -b --noEmit  # Must pass
npx vitest run        # Must pass
npm run build         # Must pass
```

- **Types**: Avoid `any`. Use Zod schemas for API response validation.
- **Data flow**: Only `AppShell` and derivation hooks may read the full state bundle. All components must use `useSystemSnapshot(selector)`.
- **Components**: Prefer `memo()` + sliced selectors to avoid unnecessary re-renders.
- **Chart accessibility**: Every visual chart component (Recharts, SVG, CSS-based) MUST include a `<ChartDataTable>` as an `sr-only` accessible data equivalent. This ensures screen reader users can navigate the underlying numbers in a structured table format. See `src/components/ui/ChartDataTable.tsx` for the component interface and examples in `EquityChart.tsx`, `DrawdownChart.tsx`, `GovernanceRadar.tsx`, `PnLDrillDown.tsx`, `MaeMfeScatter.tsx`, `PnLWaterfall.tsx`, `SlippageHistogram.tsx`, `FeatureImportanceChart.tsx`, `RiskBudgetChart.tsx`, `PerformanceStateVelocityChart.tsx`, `FactorExposureBreakdown.tsx`, and `EquityCurveWithRange.tsx`.

## Git Workflow

### Branch naming

| Prefix | Purpose |
|--------|---------|
| `fix/` | Bug fixes, doc inaccuracies |
| `feat/` | New features |
| `refactor/` | Code restructuring |
| `docs/` | Documentation changes |
| `chore/` | Maintenance, CI, config |

### Commit messages

Conventional commits (matching the existing style):

```
<type>(<scope>): <short description>

Optional body with detail on why (not just what).
```

Valid types: `fix`, `feat`, `refactor`, `chore`, `docs`, `test`, `style`, `perf`

### Pre-commit hooks

Run manually or via installed hooks:

```bash
pre-commit install
pre-commit run --all-files
```

Hooks run: ruff lint, ruff format, config schema check, import firewall, bare-assert guard, secret scanner, TODO marker scanner.

## Pull Request Process

1. Branch from `main`.
2. Make focused commits (one logical change per commit).
3. Run `ruff check . && ruff format . --check && PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -q --tb=short -x` for Python.
4. Run `cd paper_trading/dashboard && npx tsc -b --noEmit && npx vitest run` for the dashboard.
5. Open a PR with a clear description of what and why.

## Architecture Reference

Key documents:

| Document | What it covers |
|----------|---------------|
| `AGENTS.md` | Day-to-day operational guide, architecture, common tasks |
| `LIVE_CONTRACT.md` | Immutable system invariants |
| `docs/ARCHITECTURE.md` | Backtesting framework architecture |
| `docs/PRODUCTION_SYSTEM_SPEC_v1.md` | Scope, not-scope, P0-P4 framework |
| `docs/OPERATIONS.md` | Operational procedures |
| `docs/FEATURES.md` | Feature engineering details |
| `docs/GOVERNANCE.md` | Governance layer reference |
| `docs/SECURITY.md` | Security model |
| `docs/adr/ADR-000-index.md` | Architectural decision record index |

## Running Tests

```bash
# Full Python test suite
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -v --tb=short

# Specific test file
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/test_engine_weekend.py -v --tb=short

# Dashboard tests
cd paper_trading/dashboard && npx vitest run --reporter verbose

# Chaos tests
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/chaos/ -v --tb=short

# Documentation drift check
PYTHONPATH=$PYTHONPATH:. python tools/doc_drift_check.py
```
