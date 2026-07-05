# EigenCapital Configuration Layout

This directory is the deployment-configuration source of truth for the
EigenCapital engine. The architecture splits what was formerly a single
monolithic YAML into domain-separated files under `configs/domains/`.
The legacy ``configs/paper_trading.yaml`` was deleted in Phase 12.7 —
all config keys are now sourced exclusively from the domain tree.

**Rule of thumb**: edit domain files only. See [Editing workflow](#editing-workflow) below.

## Tree

```
configs/
├── README.md                       ← this file
├── schema_version.json             ← {"version": "2.0.0", …}
├── mt5_symbol_map.yaml             ← broker ticker → MT5 symbol name
├── domains/                        ← operator-write surface (Phase 11+)
│   ├── risk/                       ← capital, halt, sizing, exits
│   │   ├── capital.yaml            — initial capital, position_size, drawdown_limit
│   │   ├── halt.yaml               — circuit-breaker thresholds (drawdown, PF, signal drought, …)
│   │   ├── sizing.yaml             — 28 sizing guardrails (per-position caps, risk per trade, …)
│   │   └── exits.yaml              — adaptive-exit defaults (trailing retrace, BE lock, …)
│   ├── portfolio/                  ← weight strategy, factor model constraints
│   │   └── weights.yaml            — weight_method selector, factor exposure limits
│   ├── ml/                         ← ML pipeline parameters
│   │   ├── calibration.yaml        — probability calibration (method, bins, model_dir)
│   │   ├── ensemble.yaml           — base/regime ensemble blend weights
│   │   ├── meta_labeling.yaml      — meta-label confidence thresholds
│   │   └── triple_barrier.yaml     — per-asset TP/SL multipliers for label generation
│   ├── broker/                     ← MT5 bridge connection config
│   │   └── mt5.yaml                — host, port, symbol_map_path
│   ├── execution/                  ← live-gate parameters
│   │   ├── spreads.yaml            — spread gate tiers (bps, staleness, observe cycles)
│   │   └── sessions.yaml           — session gate tiers (UTC hour windows, crypto 24/7)
│   ├── governance/                 ← secondary gates
│   │   ├── regime_geometry.yaml    — regime-conditional SL/TP multipliers (GREEN/YELLOW/RED)
│   │   ├── liquidity.yaml          — liquidity-regime detector (volume Z, Amihud, …)
│   │   └── narrative.yaml          — FXStreet narrative ingestion + risk-off suppression
│   ├── infrastructure/             ← infrastructure wiring
│   │   └── alerts.yaml             — PagerDuty + webhook alert channel configs
│   ├── assets/                     ← per-asset catalog
│   │   ├── _index.yaml             — master list of live traded assets
│   │   ├── _defaults.yaml          — shared SL/TP overlay for all assets
│   │   ├── GC.yaml                 — per-asset overrides (allocation, pt_sl, adaptive_exit)
│   │   ├── USDCAD.yaml             ⋮
│   │   └── … (22 per-asset files)
│   └── modes/                      ← mode-specific parameter overlays
│       ├── production.yaml         — standard paper-trading defaults
│       ├── challenge_ftmo_10k.yaml — FTMO challenge profile
│       └── live.yaml               — live-trading profile
├── environments/                   ← environment overlays (paper / live / backtest / research)
│   ├── paper.yaml
│   ├── live.yaml
│   ├── backtest.yaml
│   └── research.yaml
└── domain_models/                  ← typed Python dataclasses (source of truth for defaults)
    ├── __init__.py
    ├── risk.py                     — CapitalConfig, HaltConfig, SizingConfig, ExitConfig, SellOnlyConfig
    └── assets.py                   — AssetConfig
```

## Composition order

The runtime loader (`PaperConfigRegistry.load()`) merges configuration
sources in the following order (last wins; the numbered layers map to
the concrete file groups in the table below):

```
         1. Domain promoted keys (domains/risk/*.yaml)
                  ↓
         2. Domain defaults overlay (domains/assets/_defaults.yaml)
                  ↓
         3. Per-asset file (domains/assets/<NAME>.yaml)
                  ↓
         4. Mode overlay (domains/modes/<mode>.yaml)
                  ↓
         5. Environment overlay (environments/<env>.yaml)
```

| Layer | Source | Scope |
|-------|--------|-------|
| **Risk** | `domains/risk/capital.yaml`, `sizing.yaml`, `exits.yaml`, `halt.yaml` | capital, drawdown limit, 28 sizing guardrails, adaptive-exit defaults, circuit-breaker thresholds |
| **Portfolio** | `domains/portfolio/weights.yaml` | weight_method selector, factor_exposure_limits |
| **ML** | `domains/ml/calibration.yaml`, `ensemble.yaml`, `meta_labeling.yaml`, `triple_barrier.yaml` | calibration method/bins, ensemble blend, meta-label thresholds, per-asset TP/SL for labels |
| **Broker** | `domains/broker/mt5.yaml` | MT5 bridge host/port, symbol map path |
| **Execution** | `domains/execution/spreads.yaml`, `sessions.yaml` | spread gate tier bps, session gate UTC hours |
| **Governance** | `domains/governance/regime_geometry.yaml`, `liquidity.yaml`, `narrative.yaml` | regime-conditional multipliers, liquidity regime thresholds, FXStreet narrative ingestion |
| **Infrastructure** | `domains/infrastructure/alerts.yaml` | PagerDuty/webhook alert channel configs |
| **Assets** | `domains/assets/_defaults.yaml` + `<NAME>.yaml` | per-asset allocation, pt_sl, adaptive_exit overrides |
| **Modes** | `domains/modes/<mode>.yaml` | mode-specific capital, sizing, drawdown, factor exposure limits |
| **Environments** | `environments/<env>.yaml` | data_source, rebalance, research_mode |

All keys are now **promoted** — no legacy_extras remain. All editing goes through domain files.

## Editing workflow

### Quick-reference commands

| Task | Command |
|------|---------|
| **Validate the config** (schema + cross-fields) | `python tools/check_config_schema.py` |
| **Render legacy mirror to stdout** (debugging) | `PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py` |
| **Emit legacy YAML at an explicit path** (test fixture) | `PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --write --path /tmp/legacy.yaml` |
| **Compare two configs** | `python tools/config_diff.py --from old.yaml --to new.yaml` |
| **Regenerate CONFIGURATION.md** (from domain models) | `python tools/config_docs.py` |
| **Schema-version bump** | Edit `configs/schema_version.json` (see [Schema versioning](#schema-versioning)) |

### Standard edit flow

1. **Identify** the domain file under `configs/domains/` that owns the
   setting you want to change. Use the tree above or the `summary()`
   output from the registry:
   ```python
   from configs.paper_config_registry import PaperConfigRegistry
   reg = PaperConfigRegistry.load()
   print(reg.summary())
   ```

2. **Make the edit**. Run `python tools/check_config_schema.py` to catch
   structural problems early.

3. **Run validation**:
   ```bash
   python tools/check_config_schema.py
   PYTHONPATH=$PYTHONPATH:. python -m pytest tests/config/ -q
   ```

### Adding a new asset

1. Create `configs/domains/assets/<TICKER>.yaml` (ticker = MT5 symbol
   name, e.g. `AUDJPY.yaml`). Include the per-asset unique keys:
   ```yaml
   ticker: AUDJPY
   allocation: 0.05
   tp_mult: 2.01
   sl_mult: 0.52
   ```
2. Optionally override the shared defaults for this asset:
   ```yaml
   adaptive_exit:
     trail_activation_r: 0.6
     trail_retrace_pct: 0.50
   ```
3. Run the validation commands above.
4. Add the MT5 symbol mapping in `configs/mt5_symbol_map.yaml`.

### Removing an asset

1. Remove or comment out the per-asset file in `configs/domains/assets/`.
2. Remove the ticker from `configs/domains/assets/_index.yaml`.
3. Run the validation commands above.
4. Move the model file to `paper_trading/models/orphaned/`.

## Conventions

- **snake_case** for all keys and section names
- **Unit suffixes**: `_pct`, `_r`, `_bars`, `_secs`, `_bps`, `_usd`
- **Booleans**: use a leading `enabled:` section (not a `*_enabled` key at the
  top level)
- **Per-asset dynamics**: live in `domains/assets/<NAME>.yaml`, never inline
  in a profile
- **Domain files**: overwrite complete typed defaults; to restore a default,
  remove the line from the domain file (the typed default in the dataclass
  is the source of truth)
- **MT5 symbols**: map ticker → broker symbol in `configs/mt5_symbol_map.yaml`

## Schema versioning

`configs/schema_version.json` tracks the configuration schema version.
The current version is `2.0.0`. The version is checked at load time by
`PaperConfigRegistry` and by `check_config_schema.py`.

```json
{
  "version": "2.0.0",
  "compat_max": "<3",
  "previous_version": "1.0.0",
  "note": "Configuration architecture refactor complete. ..."
}
```

Bump the major version when backward-incompatible changes land (e.g.,
removing a promoted key). Bump the minor version for additive changes.

## Migration tracking

| Phase | Status | Description | Commit |
|-------|--------|-------------|--------|
| 0 | ✅ | preparation + tooling scaffolding | `305cbf8` |
| 1 | ✅ | check_config_schema.py hardening | `bb1dbbf` |
| 2 | ✅ | flagged-dead block annotation | `016bd28` |
| 3 | ✅ | typed domain models | `2a5e831` |
| 4 | ✅ (superseded) | domain tree + ConfigRegistry (`domain_loader.py` deleted Phase 12.7) | `8517143` |
| 5 | ✅ | SELL_ONLY truth flip | `ae0b8e2` |
| 6 | ✅ | triple-barrier YAML unification | `409e1bc` |
| 7 | ✅ | per-asset file split | `57386de` |
| 8 | ✅ | mode + environment overlays | `b34d19e` |
| 9 | ✅ | generated CONFIGURATION.md | `aafd25f` |
| 10 | ✅ | config_diff + schema_version bump | `3b10926` |
| 11.0 | ✅ | Baseline v2 captured | `972e45d` |
| 11.1 | ✅ | PaperConfigRegistry (domain-first) | `047c8ab` |
| 11.2 | ✅ | EngineConfig.load() routes through registry | `bf69c3f` |
| 11.3 | ✅ | LegacyMirror (config_mirror_legacy.py) | `3ec03dc` |
| 11.4 | ✅ | per-asset files take precedence | — |
| 11.5 | ✅ | CI drift gate | `85c755e` |
| 11.6 | ✅ | operator workflow docs | — |
| 11.7 | ✅ | Phase 12 plan + handoff | — |
| 12.0 | ✅ | Phase 12 baseline | — |
| 12.1 | ✅ | Strict write-mode split (ENABLE_LEGACY_EDITS guard) | — |
| 12.2 | ✅ | Cross-field invariants, halt.yaml promotion, asset-level invariants | — |
| 12.3 | ✅ | legacy_extras pruning (5 dead keys removed from carrier) | — |
| 12.4 | ✅ | Hardened config diff (--ci flag with structured JSON, categorised changes) | — |
| 12.5 | ✅ | Operator documentation (this file refreshed) | — |

## Architecture references

| Document | Purpose |
|----------|---------|
| `docs/CONFIGURATION.md` | Auto-generated reference of all typed config fields with types and defaults |
| `configs/schema_version.json` | Schema version tracking |
| `tools/check_config_schema.py` | Structural YAML validator with cross-field checks |
| `tools/config_mirror_legacy.py` | Legacy mirror tool (--write / --check / --ci) |
| `tools/config_diff.py` | Side-by-side config comparison (--json for CI) |
| `tools/config_docs.py` | CONFIGURATION.md generator |
| `configs/paper_config_registry.py` | Typed registry — domain-first config loader |
| `configs/domain_models/risk.py` | Typed dataclasses for RiskConfig, CapitalConfig, SizingConfig, HaltConfig, ExitConfig |
| `configs/domain_models/assets.py` | Typed dataclasses for AssetConfig |
| `PHASE12_PLAN.md` | Detailed Phase 12 sub-phase plan and deferred items |
