# EigenCapital Configuration Layout

This directory is the deployment-configuration source of truth for the
EigenCapital engine. The refactor splits the legacy monolithic YAML
(`paper_trading.yaml`) into domain-separated files; behavior is preserved
during the migration window. See `BASELINE.md` and the project audit
report for context.

## Tree

```
configs/
├── README.md                       ← this file
├── schema_version.json             ← {"version": "1.0.0", "compat": "<2"}
├── paper_trading.yaml              ← legacy single-file config (mirror only)
├── mt5_symbol_map.yaml             ← broker ticker → MT5 symbol
├── modes/                          ← mode-specific overlays
├── environments/                   ← research/test/backtest/paper overlays
└── domains/
    ├── risk/                       ← capital, halt, sizing, exits
    ├── portfolio/                  ← weights, factor model
    ├── ml/                         ← ensemble, calibration, labels
    ├── broker/                     ← mt5 connection config
    ├── execution/                  ← spreads, sessions, simulation
    ├── governance/                 ← regime geometry, liquidity, narrative
    ├── infrastructure/             ← alerts, refresh, dashboard
    └── assets/                     ← per-asset catalog + per-asset files
```

## Composition order

The configuration loader merges files in this order (highest precedence last):

1. `paper_trading.yaml` legacy file (read-only mirror during migration)
2. `domains/<area>/*.yaml` typed-domain files
3. `modes/<mode>.yaml` (defaults to `modes/production.yaml`)
4. `environments/<env>.yaml` (env from `EIGENCAPITAL_ENV` or `mode:` selector)
5. `domains/assets/<NAME>.yaml` per-asset overrides
6. Environment variable overlays (secrets, bind, refresh)

Precedence: lower steps are first; later steps override earlier steps.

## Conventions

- snake_case for all keys and section names
- unit suffixes: `_pct`, `_r`, `_bars`, `_secs`, `_bps`
- booleans use a leading section `enabled:` (not a `*_enabled` key)
- per-asset dynamics live in `domains/assets/<NAME>.yaml`, never inline in a profile

## Migration tracking

| Phase | Status | Description | Commit |
|-------|--------|-------------|--------|
| 0 | ✅ completed | preparation + tooling scaffolding | `305cbf8` |
| 1 | ✅ completed | check_config_schema.py hardening | `bb1dbbf` |
| 2 | ✅ completed | flagged-dead block annotation | `016bd28` |
| 3 | ✅ completed | typed domain models | `2a5e831` |
| 4 | ✅ completed | domain tree + ConfigRegistry | `8517143` |
| 5 | ✅ completed | SELL_ONLY truth flip | `ae0b8e2` |
| 6 | ✅ completed | triple-barrier YAML unification | `409e1bc` |
| 7 | ✅ completed | per-asset file split | `57386de` |
| 8 | ✅ completed | mode + environment overlays | `b34d19e` |
| 9 | ✅ completed | generated CONFIGURATION.md | `aafd25f` |
| 10 | ✅ completed | config_diff + schema_version bump | `3b10926` |
| 11.0 | ✅ completed | Baseline v2 captured | `972e45d` |
| 11.1 | ✅ completed | PaperConfigRegistry (domain-first) | `047c8ab` |
| 11.2 | ✅ completed | EngineConfig.load() routes through registry | `bf69c3f` |
| 11.3 | ✅ completed | LegacyMirror (`config_mirror_legacy.py`) | `3ec03dc` |
| 11.4 | ✅ completed | per-asset files take precedence (verified in 11.1) | — |
| 11.5 | ✅ completed | CI drift gate | `85c755e` |
| 11.6 | ✅ completed | operator workflow docs (this file) | — |
| 11.7 | pending    | Phase 12 plan + handoff | — |

## Operator workflow (Phase 11.6)

The `domains/` tree is the **operator-write surface**. The legacy
`paper_trading.yaml` is now derived from that tree via the
`config_mirror_legacy.py` tool.

### Common tasks

| Task | Command |
|------|---------|
| Validate the YAML tree (schema + cross-fields) | `python tools/check_config_schema.py` |
| Confirm mirror matches the on-disk legacy | `PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --check` |
| Regenerate the legacy after a domain edit | `PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --write` |
| Inspect the structural diff | `PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --check` (drift shown in stderr) |
| View generated operator documentation | `docs/CONFIGURATION.md` (auto-generated; see `tools/config_docs.py`) |
| Compare two configs (env → env) | `python tools/config_diff.py --from old.yaml --to new.yaml` |

### Edit flow

1. Identify the file you want to change under `configs/domains/`.
2. Make the edit. Run `python tools/check_config_schema.py` to catch
   structural problems early.
3. Regenerate the legacy mirror:
   ```
   PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --write
   ```
4. Commit **both** the domain file change and the regenerated
   `configs/paper_trading.yaml`. CI fails if these diverge.

### Resolve drift in CI

If the CI gate `Check config mirror drift (Phase 11.3)` fails:

```
# Inspect the structural diff (in stderr)
PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --check

# Pick one:
#   A. The on-disk legacy should regenerate from the typed tree:
PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --write
git add configs/paper_trading.yaml
#   B. The legacy contains an intentional override (test fixture,
#      ad-hoc mode); that change should live in a domain file
#      instead. Add the dominant key there, then re-run the write.
```

### Composition order (paper-trading path)

The runtime loader resolves `load_config()` via PaperConfigRegistry:

1. Domain promoted keys (`risk/capital.yaml`, `risk/sizing.yaml`,
   `risk/exits.yaml`, `portfolio/weights.yaml`)
2. Per-asset files (`domains/assets/<NAME>.yaml`, fall back to
   `domains/assets/_defaults.yaml`)
3. Mode overlay (`configs/domains/modes/<mode>.yaml`, derived from
   the active `mode:` selector)
4. Environment overlay (`configs/environments/<env>.yaml`)
5. Legacy `paper_trading.yaml` for **unpromoted extras only**
   (alerting, calibration, mt5, ensemble, kelly, meta_labeling,
   portfolio, optimizations, execution)
6. Mode selector (`mode:`) applied last with mode's own defaults

Schema version is `2.0.0` (`configs/schema_version.json`); legacy
`paper_trading.yaml` remains as a derived mirror of the typed domain
tree.
