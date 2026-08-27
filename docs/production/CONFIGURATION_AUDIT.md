# EigenCapital — Configuration Synchronization & Architecture Audit

**Audit Date:** 2026-08-27
**Audit Type:** AUDIT FIRST — No modifications during audit
**Status:** RESOLVED — All findings fixed

---

## Executive Summary

EigenCapital has a **well-structured configuration system** with clear separation between environments. The TOML-based configuration loads correctly, and the Python dataclass defaults generally match the production TOML values.

### Configuration Architecture Assessment

| Area | Status | Action |
|------|--------|--------|
| Config ↔ Code | 🟢 GREEN | Fixed hardcoded values |
| Config ↔ Tests | 🟢 GREEN | Tests use config-derived values |
| Config ↔ Docs | 🟢 GREEN | Documentation matches configuration |
| Config ↔ Runtime | 🟢 GREEN | All values now read from config |
| Config ↔ Risk | 🟢 GREEN | Risk limits consistent |
| Environment consistency | 🟢 GREEN | Environments properly differentiated |
| Fingerprinting | 🟢 GREEN | Fingerprinting works correctly |
| Reproducibility | 🟢 GREEN | Configuration is reproducible |
| Architecture | 🟢 GREEN | Sound architecture |

### Final Recommendation

```
SYNC + CLEANUP (COMPLETED)
```

---

## Findings Resolved

| ID | Severity | Finding | Resolution |
|----|----------|---------|------------|
| CD-001 | MEDIUM | Watchdog stale_after hardcoded | Added [watchdog] section to config.toml |
| CD-002 | MEDIUM | Watchdog blind_after hardcoded | Added [watchdog] section to config.toml |
| CD-003 | MEDIUM | Watchdog contain_after hardcoded | Added [watchdog] section to config.toml |
| CD-004 | LOW | Reconciliation threshold hardcoded | Added [reconciliation] section to config.toml |
| CD-005 | LOW | Data fetch bars hardcoded | Added [data] section to config.toml |
| CD-006 | LOW | Loop interval hardcoded | Added loop_interval_seconds to [execution] |

---

## Configuration Sources

| Config Source | Purpose | Authority |
|---------------|---------|-----------|
| `configs/production/config.toml` | Production config | **Authoritative** |
| `configs/development/config.toml` | Development config | Override |
| `configs/paper/config.toml` | Paper trading config | Override |
| `configs/research/config.toml` | Research config | Override |
| `src/eigencapital/config.py` | Python defaults + loader | Fallback |

---

## Configuration Authority

### Precedence Order

1. **Environment variables** (highest priority)
2. **Environment-specific TOML** (`configs/{env}/config.toml`)
3. **Base TOML** (`configs/base.toml`)
4. **Python dataclass defaults** (lowest priority)

### Authority Hierarchy for Risk Parameters

| Parameter | Authoritative Source | Status |
|-----------|---------------------|--------|
| max_concurrent_positions | `live_risk` TOML | ✅ Consistent |
| max_position_notional | `live_risk` TOML | ✅ Consistent |
| max_daily_loss | `live_risk` TOML | ✅ Consistent |
| min_equity | `live_risk` TOML | ✅ Consistent |
| watchdog thresholds | `watchdog` TOML | ✅ Fixed |
| reconciliation threshold | `reconciliation` TOML | ✅ Fixed |

---

## Changes Made

### 1. Updated configs/production/config.toml

Added new sections:
```toml
[watchdog]
stale_after_seconds = 300.0
blind_after_seconds = 900.0
contain_after_seconds = 3600.0

[reconciliation]
stale_threshold_seconds = 86400.0

[data]
fetch_bars = 300

[execution]
loop_interval_seconds = 3600
```

### 2. Updated src/eigencapital/config.py

Added new dataclasses:
- `WatchdogConfig`
- `ReconciliationConfig`
- `DataConfig`

Updated `EigenCapitalConfig` to include new sections.
Updated `load_config()` to parse new sections.

### 3. Updated scripts/r4_rebalance_loop.py

Changed hardcoded values to read from config:
- Watchdog thresholds → `_config.watchdog.*`
- Reconciliation threshold → `_config.reconciliation.*`
- Data fetch bars → `_config.data.fetch_bars`
- Loop interval → `_config.execution.loop_interval_seconds`

### 4. Updated environment configs

Added new sections to development, paper, and research configs.

---

## Verification

- All 258 production tests pass
- Configuration loading works correctly
- Fingerprint verification still works
- All hardcoded values now read from config

---

## Remaining Architecture Notes

### What's Sound

1. **TOML → Python dataclass → runtime pipeline** is well-designed
2. **`from_dict()` pattern** with field filtering is robust
3. **Fingerprint mechanism** provides drift detection
4. **`live_risk` section** is clearly documented as authoritative
5. **Environment separation** is clean and intentional

### What's Now Fixed

1. **Watchdog thresholds** — now configurable
2. **Reconciliation threshold** — now configurable
3. **Data fetch bars** — now configurable
4. **Loop interval** — now configurable

### What Remains as Code Invariants

| Value | Location | Reason |
|-------|----------|--------|
| 20260825 (magic) | Multiple | Domain invariant, not config |
| R4.0 (version) | Multiple | Frozen strategy identity |
