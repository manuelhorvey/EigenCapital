# Assets Domain — per-asset catalog

Per-asset configuration files. The canonical source for asset-level parameters.

| File | Purpose |
|------|---------|
| `configs/domains/assets/_index.yaml` | Master list of all live traded assets
| `configs/domains/assets/_defaults.yaml` | Shared defaults for shadow_sltp, dynamic_sltp, adaptive_exit — inherited by all assets
| `<TICKER>.yaml` | Per-asset overrides — allocation, tp_mult, sl_mult, optional adaptive_exit overrides

**Adding an asset**: create `<TICKER>.yaml`, add ticker to `configs/domains/assets/_index.yaml`, run
`config_mirror_legacy.py --write`.

**Removing an asset**: delete or comment out the per-asset file, remove from
`configs/domains/assets/_index.yaml`, move model to `paper_trading/models/orphaned/` (create if needed), run mirror.

Per-asset files use a three-level composition:
1. `configs/domains/assets/_defaults.yaml` shared defaults
2. `<TICKER>.yaml` unique overrides
3. Legacy asset block (fallback if no per-asset file exists)

See `configs/paper_config_registry.py:_merge_assets()` for the merge logic.
