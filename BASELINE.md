# Configuration Architecture Refactor — Baseline Snapshot

This snapshot pins the pre-refactor state of the configuration system and
test surface. Subsequent phases compare against this baseline; deviations
require explicit acknowledgment before merge.

Captured at:
- branch: `feature/config-architecture-refactor`
- HEAD: `5ac2a28`
- date: capture on first phase commit

## Tooling checks

| Check | Result |
|-------|--------|
| `ruff check .` | All checks passed! |
| `ruff format . --check` | 197 files already formatted |
| `python tools/check_config_schema.py` | PASSED: config schema valid (22 assets, 3 sell-only assets) |

## Test suite

| Metric | Value |
|--------|-------|
| collected | 2824 |
| passed | 2822 |
| skipped | 2 |
| failed | 0 |
| duration | ~47s |

## Configuration shape (pre-refactor)

- Single source file: `configs/paper_trading.yaml` (1082 lines)
- Symbol map: `configs/mt5_symbol_map.yaml` (60 lines)
- Auxiliary loader: `paper_trading/config_manager.py` (290 lines)
- Auxiliary typed module: `shared/execution_config.py` (122 lines)
- Asset label registry (Python): `features/registry.py` (540 lines)
- Factor model (Python): `shared/factor_model.py` (260 lines)
- Weight methods (Python Literal): `shared/portfolio_weights.py` (508 lines)
- Validator: `tools/check_config_schema.py` (156 lines)

## Confirmed issues to remediate across the refactor

CRITICAL: cross-file truth forks
- C1 SELL_ONLY truth split between YAML and Python constant
- C2 tp_mult/sl_mut split between YAML and ASSET_LABEL_PARAMS
- C3 validator references a removed YAML key (mt5.min_lot)
- C4 per-cycle `get_config()` calls without startup-time caching

HIGH: file organization
- H1 1,082-line monolithic YAML
- H2 per-asset block ~95% duplicated boilerplate (~500 of ~600 lines)
- H3-H6 dead configs (stacking, adx_entry_gate, kelly, entry_optimization)
- H7 mode overrides partially honored
- H8 missing allocation-sum check
- H9-H11 single-source decomposition (shadow_sltp, dynamic_sltp, regime_geometry)
- H12-H14 validation gaps and missing environment overlays

MEDIUM/LOW: naming, docs, and DX (see audit report).
