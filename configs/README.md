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
| 10 | ✅ completed | config_diff + schema_version bump | (this branch HEAD) |

Schema version is `2.0.0` (`configs/schema_version.json`); legacy
`paper_trading.yaml` remains as a co-authoritative mirror for the
migration window.
