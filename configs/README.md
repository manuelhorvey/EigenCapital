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

| Phase | Status | Branch pair |
|-------|--------|-------------|
| 0 — preparation | active | `feature/config-architecture-refactor` |
| 1 — validation hardening | pending | - |
| 2 — dead-config removal | pending | - |
| 3 — domain split (read mirror) | pending | - |
| 4 — write-mode split | pending | - |
| 5 — SELL_ONLY truth flip | pending | - |
| 6 — triple-barrier unification | pending | - |
| 7 — per-asset file split | pending | - |
| 8 — mode + environment overlay | pending | - |
| 9 — generated docs | pending | - |
| 10 — final hardening | pending | - |
