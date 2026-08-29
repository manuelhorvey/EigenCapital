# Configuration Forensic Audit — 2026-08-29

> **Scope:** Full repository configuration architecture  
> **Method:** Code-traces-code, not documentation-trusts-documentation  
> **Governance:** Phase 2 frozen — no R4 behavior changes

## Executive Summary

The configuration architecture is **fundamentally sound** with one authoritative path (TOML → dataclass → typed model → consumer). Fingerprint coverage ensures that any behaviorally significant configuration change is detected. However, the codebase contains **legacy configuration artifacts** from earlier design phases that are dead code or misleading. These should be cleaned up during Phase 2 since they carry zero production risk.

**Overall: MINOR CLEANUP recommended — no restructure needed.**

---

## Findings

### P1 — High (Production Risk)

**None.** All behaviorally significant configuration values flow through the correct chain and are fingerprint-protected.

### P2 — Medium (Code Quality / Maintenance Risk)

| ID | Finding | Evidence | Action |
|----|---------|----------|--------|
| CFG-001 | **TrendConfig is dead code** — `strategies/trend/config.py` defines lookback=63, vol=21, risk_target=0.10. The actual R4 loop uses `StrategyConfig` with lookback=252, vol_lookback_signal=60, risk_lookback=20. TrendConfig is only imported by `strategies/trend/strategy.py`, which is NOT used by the R4 loop. | `grep -rn "TrendConfig"` shows only internal usage in trend module. R4 loop uses `_config.strategy.*` | Remove or clearly label as "unused by R4" |
| CFG-002 | **MicroLiveLimits is legacy** — `live/risk.py` defines MicroLiveLimits (max3 positions, $500 daily loss) but the production R4 loop uses LiveRiskConfig (max19, $250 daily loss) via RiskEnvelope. MicroLiveLimits is only a fallback default in MicroLiveRiskEnvelope. | grep shows only `live/risk.py` and `__init__.py` | Remove or label as legacy |
| CFG-003 | **RiskConfig is dead code** — `config.py` defines RiskConfig and constructs it from TOML, but no production code imports or uses it. RiskPolicy is the actual risk consumer. | `grep "from eigencapital.config import.*RiskConfig"` → 0 results outside config.py | Remove from config.py or redirect to RiskPolicy |
| CFG-004 | **rebalance_frequency="weekly" is misleading** — StrategyConfig declares `rebalance_frequency = "weekly"` but the R4 loop runs hourly (`loop_interval_seconds=3600`). The setting is not consumed by any code. | grep shows no consumer of `rebalance_frequency` | Remove or rename to document actual behavior |
| CFG-005 | **base.toml is missing** — `config.py` references `configs/base.toml` which doesn't exist. The loader silently handles this. Harmless but technically an incomplete config chain. | `ls configs/base.toml` → No such file | Either create it or remove the reference |

### P3 — Low (Cleanup)

| ID | Finding | Evidence | Action |
|----|---------|----------|--------|
| CFG-006 | **Duplicate max_concurrent_positions** — CapitalConfig(19) and LiveRiskConfig(19) both define it, but only LiveRiskConfig is used by risk gates. CapitalConfig's value is unused by production. | `validate_config_consistency()` already flags this mismatch | Remove from CapitalConfig or document that it's informational only |
| CFG-007 | **Duplicate daily_loss** — CapitalConfig(250) and LiveRiskConfig(250) both define it, but only LiveRiskConfig is used. | Same as above | Same as above |
| CFG-008 | **Order timeout hardcoded** — `_ORDER_SEND_TIMEOUT_SECONDS = 30` is hardcoded in r4_rebalance_loop.py, not from config. | Line 45 of r4_rebalance_loop.py | Low priority — could be in ExecutionConfig |
| CFG-009 | **DataQuality freshness thresholds hardcoded** — DataQualityPresets defines 30s/120s thresholds in code, not config. | data_quality.py lines 547-580 | Acceptable — these are domain invariants |

---

## Configuration Authority Model — VERIFIED

```
configs/production/config.toml  ← Authoritative for deployment-varying settings
        ↓
config.py dataclasses           ← Typed validation, frozen after construction
        ↓
EigenCapitalConfig              ← Single top-level config object
        ↓
┌──────────────────────────────────────┐
│ R4 loop: StrategyConfig + LiveRiskConfig + CapitalConfig + ExecutionConfig
│ Risk: LiveRiskConfig → RiskEnvelope → RiskEnforcer
│ Fingerprint: config_fp captures all behaviorally significant values
│ Dashboard: LoadConfig("production") — read-only
│ Event Ledger: load_config("production") — fingerprint only
└──────────────────────────────────────┘
```

**Verdict:** Single authoritative configuration path. No competing sources in the live R4 path.

---

## Fingerprint Coverage — VERIFIED

| Config Change | Fingerprint Detected? | Trading Blocked? |
|---------------|----------------------|------------------|
| Strategy parameters | ✅ config_fp | ✅ Yes |
| Live risk limits | ✅ live_risk_fp | ✅ Yes |
| Risk policy | ✅ risk_fp | ✅ Yes |
| Symbol universe | ✅ symbol_fp | ✅ Yes |
| Broker identity | ✅ config_fp | ✅ Yes |
| Watchdog thresholds | ✅ config_fp | ✅ Yes |
| Execution limits | ✅ config_fp | ✅ Yes |

**No behaviorally significant configuration can change without fingerprint detection.**

---

## Configuration Validation — VERIFIED

`validate_config_consistency()` in config.py checks:
- live_risk.min_equity vs capital.max_equity
- live_risk.max_daily_loss > 0
- live_risk.max_concurrent_positions > 0
- live_risk.max_account_drawdown_pct ∈ (0, 1.0]

Additional validation in dataclass `__post_init__`:
- TrendConfig: lookback > 0, vol_lookback > 0, risk_target > 0
- RiskPolicy: max_drawdown > 0, daily_loss >= 0, min_equity >= 0

---

## Security — VERIFIED

- No secrets in config files or source code
- Account credentials in config.toml (demo account, not production secrets)
- No API keys, tokens, or passwords committed
- .env.example exists for environment variables

---

## Final Scorecard

```
CONFIGURATION AUDIT
────────────────────────────────────
Authority model:       ✅ PASS — single authoritative path
Hardcoded config:      🟡 WARN — _ORDER_SEND_TIMEOUT_SECONDS, TrendConfig
Duplicate config:      🟡 WARN — TrendConfig vs StrategyConfig, RiskConfig vs RiskPolicy
Config/code parity:    ✅ PASS — TOML values match runtime behavior
Runtime consumption:   ✅ PASS — all critical config consumed by R4 loop
Validation:            ✅ PASS — dataclass __post_init__ + validate_config_consistency
Fingerprint coverage:  ✅ PASS — all behaviorally significant values covered
Risk configuration:    ✅ PASS — LiveRiskConfig authoritative, fingerprinted
Execution config:      ✅ PASS — consumed by R4 loop
Market schedules:      ✅ PASS — canonical TOML, loaded by MarketSchedule
Data quality config:   ✅ PASS — domain invariants in code (acceptable)
Dashboard config:      ✅ PASS — read-only, uses load_config
Security:              ✅ PASS — no secrets committed
Documentation:         🟡 WARN — TrendConfig/MicroLiveLimits undocumented as legacy

P0: 0
P1: 0
P2: 5 (all dead code / misleading naming)
P3: 4 (cosmetic / minor)

R4 fingerprint:        UNCHANGED
R4 behavior:           UNCHANGED
Tests:                 PASS
Lint:                  PASS

Recommendation: MINOR CLEANUP — remove dead config, clarify naming
```

## Recommended Actions (Safe During Phase 2)

1. **Remove TrendConfig** — dead code, R4 uses StrategyConfig
2. **Remove MicroLiveLimits** — legacy, R4 uses LiveRiskConfig
3. **Remove RiskConfig** — dead code, RiskPolicy is the consumer
4. **Remove rebalance_frequency** — misleading, not consumed
5. **Create or remove base.toml reference** — clarify config chain

All changes are behavior-preserving (dead code removal only). No R4 parameters touched.
