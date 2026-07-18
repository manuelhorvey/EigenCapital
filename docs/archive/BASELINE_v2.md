> **🪦 ARCHIVED** — Historical snapshot of the post-Phase-10 state. Retained for reference only. See current config at `configs/domains/` and `configs/paper_config_registry.py`.

# Configuration Architecture Phase 11 — Baseline v2

Captured at the start of Phase 11 (write-mode split). Reference for
diffing post-Phase 11 outputs against the pre-Phase 11 state.

Captured at:
- branch: `feature/phase11-write-mode-split`
- parent HEAD: `3b10926` (Phase 10 completion)
- 11a2=11b derivation: Phase 11 base = Phase 10 + closing commits

## Tooling checks

| Check | Result |
|-------|--------|
| `ruff check .` | All checks passed! |
| `ruff format . --check` | 206 files already formatted |
| `python tools/check_config_schema.py` | PASSED: 22 assets, 3 sell-only |

## Test suite

| Metric | Value |
|--------|-------|
| collected | 2965 |
| passed | 2941 |
| skipped | 2 |
| failed | 0 |
| duration | ~56s |

## Configuration shape (pre-Phase 11)

Domain tree (32 files):
- configs/domains/{risk, portfolio, ml, broker, execution, governance,
  infrastructure, assets, modes}/
- 22 per-asset files + _defaults.yaml + _index.yaml
- 3 mode files (production, challenge_ftmo_10k, live)
- 3 risk files (capital, sizing, exits)
- 3 ml files (ensemble, calibration, meta_labeling) + triple_barrier.yaml
- 3 execution files (spreads + sessions)
- 3 governance files (regime_geometry + liquidity + narrative)
- 1 portfolio/weights.yaml + 1 broker/mt5.yaml + 1 infrastructure/alerts.yaml

Environments (5 files):
- backtest, live, paper, research, test

Legacy:
- configs/paper_trading.yaml (1094 lines, still authoritative)

## Phase 11 Goals

1. paper_trading.yaml stays writable but mirror-regenerated from
   ConfigRegistry on every config edit.
2. Phase-11 router prefers per-asset YAMLs; falls back to legacy
   assets block when asset file is absent.
3. CI fails when generated shadow drifts from operator-edited legacy.
4. The EngineConfig.load() route uses PaperConfigRegistry as the
   primary bootstrap; legacy file becomes a secondary mirror.
5. Operator workflow: edit configs/domains/assets/USDCAD.yaml,
   run tools/config_migrate.py, commit both files.
6. Final Phase 12 (separate branch) deletes configs/paper_trading.yaml.
