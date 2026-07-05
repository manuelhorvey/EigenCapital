# Phase 12 plan — write-mode split, validator hardening, governance migration

**Branch**: `feature/phase-11-write-mode` (HEAD: `dbb18d9`)
**Owner**: opencode
**Date**: 2026-07-05
**Status**: Phase 11 shipped; Phase 12 scoped below.

This document is the handoff for Phase 12 work. Capture what Phase 11
left behind, what is *not* yet migrated to the typed domain tree, and
the proposed next slices.

## What Phase 11 shipped

| Phase | Outcome |
|-------|---------|
| 11.1 | `PaperConfigRegistry` reads domain YAMLs primarily; legacy fallback for unpromoted extras |
| 11.2 | `paper_trading/config_manager.py:load_config()` routes through the registry |
| 11.3 | `tools/config_mirror_legacy.py` regenerates `paper_trading.yaml` from the registry |
| 11.4 | Per-asset files (`domains/assets/<NAME>.yaml` + `_defaults.yaml`) take precedence |
| 11.5 | CI gate `tools/config_mirror_legacy.py --check` |
| 11.6 | `configs/README.md` operator workflow |

**Verified invariants**:

- 2973 tests pass; 2 skipped (pre-Phase-11, unchanged)
- `ruff check .` clean
- `config_mirror_legacy.py --check` returns 0
- `PaperConfigRegistry.as_legacy_dict()` round-trips structurally equal
  to the on-disk `paper_trading.yaml`

## Known leftovers (Phase 11 deferred)

These were *intentionally* not completed in Phase 11 because they
either require larger surface area or cannot be safely decoupled from
the runtime behavior inside a single migration branch.

### 1. Strict write-mode split (Phase 11.8 candidate)

Right now `load_config()` and `config_mirror_legacy.py` coexist.
Operators can still hand-edit `paper_trading.yaml` and rely on the
override semantics. To complete the migration:

1. Add `ENABLE_LEGACY_EDITS` env-var guard that rejects hand-edits
   outside the registry (e.g. fail CI when a diff to legacy comes
   without an accompanying domain-file diff).
2. Strip keys that the registry would *re-emit* differently from the
   legacy file (for example: descriptions, ordering) — currently kept
   to preserve operator reading.

**Risk**: tests that pass an explicit path with overrides (test
fixtures) will continue to work; only the operator-facing
`configs/paper_trading.yaml` becomes registry-controlled.

### 2. Validator hardening

`tools/check_config_schema.py` covers top-level fields, types, and
range checks. Phase 12 should add:

- **Cross-field invariants** that aren't currently asserted:
  - `defaults.mt5_max_risk_per_trade_pct ≤ defaults.max_risk_per_trade_pct` (already in 11.x)
  - `defaults.profit_lock_threshold_pct` ∈ [0, 1]
  - `portfolio.factor_exposure_limits` values sum to ≤ 1.0 (no over-allocation)
- **Asset-level invariants**:
  - For each asset: `sl_mult` and `tp_mult` both > 0
  - For each asset: `allocation + remaining_allocation ≤ 1.0` (and ≤ 0.20 for any single-asset overage)
  - `metadata.max_dd_R ≤ |portfolio_drawdown_limit| × |capital|`
- **Type strengthening**:
  - Money fields `[R|usd]` annotation must be parsed as Decimal, not float
  - Boolean keys must use the `enabled:` section pattern, not `*_enabled` keys

### 3. Governance migration (NOT in Phase 12)

The governance layer (`feature/governance-migration` in the audit
proposal) would move `monitor_paper_trading.py`, `slack_alerter.py`,
and the alert thresholds to typed configurations. This is **outside
Phase 11/12** because:

- It depends on schema_version 2.x being stable
- It is owned by a different agent thread; we don't want to fork
  orthogonal work onto the same branch

Schedule: separate branch, separate phase numbering (Phase 13+).

### 4. Dashboard binding

The dashboard `paper_trading/dashboard/src/hooks/useEngineConfig.ts`
reads `/state.json` which is server-rendered from `EngineConfig`. We
need to expose typed fields via `state.json` and add TypeScript types
in `dashboard/src/types/ConfigSnapshot.ts`. Phase 12 should ship:

- `eigencapital/observability/config_snapshot.py` — typed JSON
  serialization of the registry (filtering secrets)
- Dashboard `ConfigSnapshot.ts` (TypeScript interface)
- Hook reads from snapshot, not from raw state.json

### 5. Liveconfig environment carrier

Currently `EIGENCAPITAL_ENV` is interpreted by `monitor.py` only.
Phase 12 should centralize:

```python
# configs/environment_resolver.py
def resolve_active_environment() -> str:
    """Returns the active environment name from EIGENCAPITAL_ENV
    or the mode selector, falling back to 'paper'."""
```

— plus 5–10 test cases covering precedence + mode fallback.

## Proposed Phase 12 sub-phases

| Sub | Description | Estimated scope |
|-----|-------------|-----------------|
| 12.1 | Strict write-mode split (`ENABLE_LEGACY_EDITS` guard) | 2 files + tests |
| 12.2 | Cross-field invariants in `check_config_schema.py` | 1 file + 8 tests |
| 12.3 | Asset-level invariants (TP/SL positivity, allocation sum) | 1 file + 6 tests |
| 12.4 | ConfigSnapshot for dashboard binding | 2 files + tests |
| 12.5 | Environment resolver + mode fallback tests | 1 file + tests |
| 12.6 | Type strengthening (Decimal for money, bool section pattern) | 1 file + tests |
| 12.7 | This plan refresh + Phase 13 handoff | 1 file |

Risk-weighted estimate: 1–2 sessions.

## Important: don't do this in Phase 11

Phase 11 reached its scope: landing the registry, the mirror, and the
CI gate. Phase 12 widens into *guardrails* (strict write-mode) that
will fail loudly if something goes wrong. Pushing 12.1 → 11.7 would:

- Make Phase 11 fail-loud at points where it currently runs silently
- Force every test fixture to either remove its override semantics
  or accept the registry's intentional silence
- Block the registry on contracts not yet validated

So Phase 11.7 just records the plan; Phase 12 picks up the work on
its own branch.

## Handoff

**Branch ready for review**: `feature/phase-11-write-mode`
**Test baseline captured**: BASELINE_v2.md
**Operator workflow**: configs/README.md
**Validation commands**:

```bash
PYTHONPATH=$PYTHONPATH:. python tools/check_config_schema.py
PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --check
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/ -q
ruff check . && ruff format . --check
```
