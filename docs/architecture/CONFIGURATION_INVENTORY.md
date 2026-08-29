# Configuration Inventory — Authoritative Source Map

> **Status: CURRENT**  
> **Created: 2026-08-29**  
> **Authority: codebase (this document maps, not defines)**

## Configuration Loading Chain

```
configs/production/config.toml  (authoritative overrides)
        ↓
configs/base.toml               (missing — defaults to empty)
        ↓
Hardcoded defaults in dataclasses (fallback)
        ↓
EigenCapitalConfig (typed model)
        ↓
R4 loop / risk enforcement / dashboard / fingerprint verifier
```

**Precedence:** TOML override → dataclass default → nothing (no env vars in production path)

## Configuration Authority Map

### Strategy

| Setting | Source | Consumer | Authority | Fingerprint |
|---------|--------|----------|-----------|-------------|
| version | config.toml → StrategyConfig | fingerprint_verifier | StrategyConfig | ✅ manifest |
| manifest_fingerprint | config.toml → StrategyConfig | fingerprint_verifier | StrategyConfig | ✅ cached |
| signal_lookback_long (252) | config.toml → StrategyConfig | r4_rebalance_loop | StrategyConfig | ✅ config_fp |
| skip_months (1) | config.toml → StrategyConfig | r4_rebalance_loop | StrategyConfig | ✅ config_fp |
| vol_lookback_signal (60) | config.toml → StrategyConfig | r4_rebalance_loop | StrategyConfig | ✅ config_fp |
| risk_lookback (20) | config.toml → StrategyConfig | r4_rebalance_loop | StrategyConfig | ✅ config_fp |
| vol_target_annual (0.10) | config.toml → StrategyConfig | r4_rebalance_loop | StrategyConfig | ✅ config_fp |
| rebalance_frequency ("weekly") | config.toml → StrategyConfig | ⚠️ NOT consumed | StrategyConfig | — |
| transaction_cost_bps (10) | config.toml → StrategyConfig | ⚠️ NOT consumed by loop | StrategyConfig | — |
| slippage_bps (5) | config.toml → StrategyConfig | ⚠️ NOT consumed by loop | StrategyConfig | — |

### Risk

| Setting | Source | Consumer | Authority | Fingerprint |
|---------|--------|----------|-----------|-------------|
| LiveRiskConfig.max_daily_loss (250) | config.toml → LiveRiskConfig | RiskEnvelope → RiskEnforcer | LiveRiskConfig | ✅ live_risk_fp |
| LiveRiskConfig.min_equity (4000) | config.toml → LiveRiskConfig | RiskEnvelope → RiskEnforcer | LiveRiskConfig | ✅ live_risk_fp |
| LiveRiskConfig.max_concurrent (19) | config.toml → LiveRiskConfig | RiskEnvelope → RiskEnforcer | LiveRiskConfig | ✅ live_risk_fp |
| LiveRiskConfig.max_order_notional (2500) | config.toml → LiveRiskConfig | RiskEnvelope → RiskEnforcer | LiveRiskConfig | ✅ live_risk_fp |
| LiveRiskConfig.max_account_drawdown_pct (0.10) | config.toml → LiveRiskConfig | RiskEnvelope → RiskEnforcer | LiveRiskConfig | ✅ live_risk_fp |
| RiskPolicy (various) | config.toml → RiskConfig → RiskPolicy | risk/engine.py, health.py, checks | RiskPolicy | ✅ risk_fp |

### Capital

| Setting | Source | Consumer | Authority | Fingerprint |
|---------|--------|----------|-----------|-------------|
| max_equity (5100) | config.toml → CapitalConfig | r4_rebalance_loop (MAX_EQUITY) | CapitalConfig | ✅ config_fp |
| max_concurrent_positions (19) | config.toml → CapitalConfig | r4_rebalance_loop (MAX_CONCURRENT) | CapitalConfig | ✅ config_fp |
| max_daily_loss (250) | config.toml → CapitalConfig | ⚠️ NOT used (live_risk used instead) | CapitalConfig | — |
| max_drawdown_pct (20) | config.toml → CapitalConfig | ⚠️ NOT used by loop | CapitalConfig | — |

### Execution

| Setting | Source | Consumer | Authority | Fingerprint |
|---------|--------|----------|-----------|-------------|
| loop_interval_seconds (3600) | config.toml → ExecutionConfig | r4_rebalance_loop (snapshot_interval) | ExecutionConfig | ✅ config_fp |
| max_orders_per_cycle (8) | config.toml → ExecutionConfig | r4_rebalance_loop (MAX_ORDERS_PER_CYCLE) | ExecutionConfig | ✅ config_fp |
| max_chase_attempts (2) | config.toml → ExecutionConfig | execution code | ExecutionConfig | — |
| _ORDER_SEND_TIMEOUT_SECONDS (30) | hardcoded in r4_rebalance_loop | r4_rebalance_loop | ⚠️ CODE | — |

### Watchdog

| Setting | Source | Consumer | Authority | Fingerprint |
|---------|--------|----------|-----------|-------------|
| stale_after_seconds (300) | config.toml → WatchdogConfig | r4_rebalance_loop → Watchdog | WatchdogConfig | ✅ config_fp |
| blind_after_seconds (900) | config.toml → WatchdogConfig | r4_rebalance_loop → Watchdog | WatchdogConfig | ✅ config_fp |
| contain_after_seconds (3600) | config.toml → WatchdogConfig | r4_rebalance_loop → Watchdog | WatchdogConfig | ✅ config_fp |

### Broker

| Setting | Source | Consumer | Authority | Fingerprint |
|---------|--------|----------|-----------|-------------|
| allowed_symbols (31 symbols) | config.toml → BrokerConfig | r4_rebalance_loop (R4_SYMBOLS, ELIGIBLE_SYMBOLS) | BrokerConfig | ✅ symbol_fp |
| max_spread (0.0015) | config.toml → BrokerConfig | execution code | BrokerConfig | — |
| account_id (436921728) | config.toml → BrokerConfig | MT5 connection | BrokerConfig | ✅ config_fp |

### Data Quality / Truth / Schedule

| Setting | Source | Consumer | Authority | Fingerprint |
|---------|--------|----------|-----------|-------------|
| freshness thresholds (30s/120s) | code (DataQualityPresets) | DataQualityAssessor | DataQualityPresets | — |
| market schedules (per-instrument) | configs/market_schedules/default.toml | MarketSchedule | TOML file | — |
| staleness thresholds | code defaults | RiskObserver | RiskObserver | — |
| fetch_bars (300) | config.toml → DataConfig | r4_rebalance_loop | DataConfig | — |

## Dead / Unused Configuration

| Config | Location | Status | Evidence |
|--------|----------|--------|----------|
| TrendConfig | strategies/trend/config.py | **UNUSED by production R4** | R4 loop uses StrategyConfig, not TrendConfig |
| MicroLiveLimits | live/risk.py | **LEGACY** — only used as fallback in live/risk.py | Production uses LiveRiskConfig → RiskEnvelope |
| RiskConfig | config.py | **DEAD** — constructed but never consumed | RiskPolicy is the actual risk consumer |
| rebalance_frequency | StrategyConfig | **MISLEADING** — says "weekly" but loop runs hourly | Not consumed by any code |
| configs/base.toml | Referenced in config.py | **MISSING** — silently ignored | Loader handles gracefully |

## Duplicate Definitions

| Concept | Location A | Location B | Authority | Discrepancy |
|---------|-----------|-----------|-----------|-------------|
| Max concurrent positions | LiveRiskConfig (19) | CapitalConfig (19) | LiveRiskConfig | Same value, but capital.max_concurrent_positions is unused by risk gates |
| Daily loss limit | LiveRiskConfig (250) | CapitalConfig (250) | LiveRiskConfig | Same value, but capital.max_daily_loss is unused by risk gates |
| Strategy lookback | TrendConfig (63) | StrategyConfig (252) | StrategyConfig | **DIFFERENT** — TrendConfig is legacy, R4 uses 252 |
| Vol lookback | TrendConfig (21) | StrategyConfig (60) | StrategyConfig | **DIFFERENT** — TrendConfig is legacy, R4 uses 60 |
| Risk limits | RiskPolicy (defaults) | RiskConfig (defaults) | RiskPolicy | Same values — RiskConfig is dead code |

## Configuration Contract

```
Every behaviorally significant configuration value:
  ✅ Declared in dataclass
  ✅ Overridable via TOML
  ✅ Validated by __post_init__ (where applicable)
  ✅ Consumed by production code
  ✅ Covered by fingerprint (where behaviorally significant)
  ✅ Documented in config.toml comments
```

## Fingerprint Coverage

| Component | Fingerprint | Includes Config? | What's Protected |
|-----------|-------------|-------------------|------------------|
| R4 Manifest | strategy.manifest_fingerprint | ✅ Direct | Strategy identity |
| Risk Policy | risk_fp | ✅ RiskPolicy fields | Risk boundaries |
| Live Risk | live_risk_fp | ✅ LiveRiskConfig fields | Live trading envelope |
| Config | config_fp | ✅ Full config serialization | All config changes |
| Symbol Mapping | symbol_fp | ✅ allowed_symbols | Universe changes |

**Verdict:** Any change to a behaviorally significant configuration value will change the appropriate fingerprint and block trading. This is correct.

## Risk Configuration Hierarchy (Production)

```
LiveRiskConfig (config.py, authoritative)
    ↓
RiskEnvelope (r4_rebalance_loop.py)
    ↓
RiskEnforcer (live/risk_enforcement.py)
    ↓
Risk checks → REJECT / PASS

RiskPolicy (risk/policy.py, account-level limits)
    ↓
EigenRiskEngine (risk/engine.py)
    ↓
Account checks → REJECT / PASS

⚠️ MicroLiveLimits (live/risk.py, legacy fallback)
    NOT used in production R4 path
```
