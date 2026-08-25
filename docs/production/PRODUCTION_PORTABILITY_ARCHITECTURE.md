# EigenCapital — Production Portability Architecture

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Configuration Layer                    │
│  configs/{env}/config.toml → EigenCapitalConfig          │
│  Single source of truth for ALL parameters               │
│  Immutable after startup | Fingerprinted | Validated     │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                   Identity Layer                         │
│  FingerprintVerifier                                     │
│  ├── R4 Manifest (frozen research identity)              │
│  ├── RiskPolicy (frozen risk parameters)                 │
│  ├── LiveRiskConfig (qualification envelope)             │
│  ├── Strategy Version (frozen at R4.0)                   │
│  └── Full Config (detects any drift)                     │
│  Fail closed on ANY mismatch                             │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                   Strategy Layer                         │
│  R4 Signal: 12-1 month momentum → cross-sectional ranks  │
│  Regime Gate: 20-day vol < expanding median              │
│  Vol Scaling: 60-day vol → 50% target → clip ±0.20      │
│  All parameters from config (not hardcoded)              │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                    Risk Layer                             │
│  ┌─────────────────────┐  ┌──────────────────────────┐  │
│  │ EigenRiskEngine     │  │ RiskEnforcer              │  │
│  │ (paper trading)     │  │ (live trading)            │  │
│  │ Uses RiskPolicy     │  │ 7 broker-authoritative    │  │
│  │                     │  │ gates:                    │  │
│  │                     │  │ 1. Broker connectivity    │  │
│  │                     │  │ 2. Position count         │  │
│  │                     │  │ 3. Account drawdown       │  │
│  │                     │  │ 4. Daily loss (FIXED)     │  │
│  │                     │  │ 5. Equity floor           │  │
│  │                     │  │ 6. Position protection    │  │
│  │                     │  │ 7. Fingerprint (FIXED)    │  │
│  └─────────────────────┘  └──────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐   │
│  │ DailyLossTracker (NEW)                           │   │
│  │ - Midnight UTC reset                             │   │
│  │ - Persistent baseline                            │   │
│  │ - Survives restart                               │   │
│  │ - Hash-verified integrity                        │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  Trading Provider Layer (NEW)            │
│  TradingProvider (ABC)                                   │
│  ├── LinuxMT5Provider (mt5linux / Wine bridge)          │
│  └── WindowsMT5Provider (official MetaTrader5 pkg)      │
│                                                          │
│  Platform-agnostic data models:                          │
│  AccountInfo, PositionInfo, TickInfo, SymbolInfo,        │
│  OrderRequest, OrderResult, BarData                      │
│                                                          │
│  Capability Matrix:                                      │
│  connect | account | positions | orders | data | symbols │
│  ALL required on BOTH platforms                          │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  Execution Layer                         │
│  Portfolio Construction (top-N by |weight|, max 8)      │
│  Order Generation (rotation-aware: close weak, open)    │
│  Emergency Flatten (idempotent, retry-safe)             │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                Supervision Layer (NEW)                   │
│  ProcessSupervisor                                       │
│  ├── PID file (duplicate prevention)                    │
│  ├── Instance identity (unique per process)             │
│  ├── Health file (external monitoring)                  │
│  ├── Restart count tracking                             │
│  ├── FROZEN state (repeated failures)                   │
│  └── Graceful shutdown (signal handlers)                │
│                                                          │
│  Platform-neutral (no pgrep, no systemctl)              │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  Observability Layer                     │
│  Audit Log (JSONL, append-only, hash-chained)           │
│  Monitor (position changes, equity, regime, risk gates) │
│  Telegram Alerts (configurable)                         │
│  Health File (machine-readable status)                  │
└─────────────────────────────────────────────────────────┘
```

## Platform Support Matrix

| Capability | Windows | Linux | Notes |
|-----------|---------|-------|-------|
| connect | ✅ via WindowsMT5Provider | ✅ via LinuxMT5Provider | Factory selects |
| account read | ✅ | ✅ | Same data model |
| positions | ✅ | ✅ | Same data model |
| orders | ✅ | ✅ | Same request/result |
| historical data | ✅ | ✅ | Same rates format |
| symbol metadata | ✅ | ✅ | Same info model |
| order submission | ✅ | ✅ | Same OrderRequest |
| cancellation | ✅ | ✅ | Via provider |
| emergency flatten | ✅ | ✅ | Via provider |
| reconciliation | ✅ | ✅ | Via provider |
| process supervision | ✅ PID file | ✅ PID file | Platform-neutral |
| signal handling | ✅ SIGBREAK | ✅ SIGTERM/SIGINT | Handled in supervisor |
| file locking | ✅ atomic rename | ✅ atomic rename | os.replace() |
| health monitoring | ✅ JSON file | ✅ JSON file | Same format |

## Configuration Flow

```
configs/{env}/config.toml
    ↓ (tomllib)
Deep merge with base.toml
    ↓ (from_dict per section)
EigenCapitalConfig (frozen dataclass)
    ↓ (consumed by)
├── Strategy → R4 signal computation
├── Capital → Position sizing limits
├── LiveRisk → RiskEnforcer envelope
├── Execution → Order limits
├── Broker → Symbol universe
├── Health → Snapshot freshness
├── FingerprintVerifier → Integrity checks
└── ProcessSupervisor → State management
```

## Fingerprint Chain

```
R4ConfigManifest.compute_identity()
    → aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb
    ↓ (verified at startup + every cycle)

RiskPolicy.to_dict() → SHA256
    → a1eb1373fa11dff7c3dc0c22dbbedcac1857a04b45f252de9ec2d373aadbda6c
    ↓ (verified at startup + every cycle)

LiveRiskConfig.compute_fingerprint()
    → (computed from config.toml [live_risk] section)
    ↓ (verified at startup + every cycle)

StrategyConfig.strategy_version == "R4.0"
    ↓ (verified at startup + every cycle)

EigenCapitalConfig.to_dict() → SHA256
    → (full config fingerprint, detects ANY drift)
    ↓ (verified at startup + every cycle)
```

Any mismatch → BLOCKED → no trading
