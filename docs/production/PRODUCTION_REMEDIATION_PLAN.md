# EigenCapital — Production Remediation Plan

**Status:** IN PROGRESS  
**Started:** 2026-08-25  
**Baseline Commit:** `0852d22`

## Summary

| Category | P0 Fixes Done | P0 Total | P1 Done | P1 Total | P2 Done | P2 Total |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|
| Configuration | ✅ | 1 | — | 0 | — | 0 |
| Fingerprint | ✅ | 1 | — | 0 | — | 0 |
| MT5 Portability | ✅ | 1 | — | 0 | — | 0 |
| Daily Loss | ✅ | 1 | — | 0 | — | 0 |
| Process Supervision | ✅ | 1 | — | 0 | — | 0 |
| Disconnect Safety | — | 1 | — | 0 | — | 0 |

## Completed P0 Fixes

### 1. Configuration Single Source of Truth
**Commit:** (this session)  
**Problem:** Three competing configuration sources with different values.  
**Root cause:** Hardcoded constants in `r4_rebalance_loop.py` + defaults in `config.py` + TOML files.  
**Implementation:**
- Added `LiveRiskConfig` dataclass to `config.py`
- Added `live_risk` section to `configs/production/config.toml`
- Added R4-specific strategy params (`skip_months`, `vol_lookback_signal`, `risk_lookback`)
- Added `max_orders_per_cycle` to `ExecutionConfig`
- Rewrote `r4_rebalance_loop.py` to load ALL config from TOML
- Removed all hardcoded risk/capital constants from scripts
**Tests:** 14 config consistency tests (all pass)  
**Negative paths:** Tested discrepancies between live_risk and capital configs

### 2. Real Fingerprint Enforcement
**Commit:** (this session)  
**Problem:** Fingerprint gate hardcoded to `True` in live trading loop.  
**Root cause:** No runtime fingerprint verification existed.  
**Implementation:**
- Created `FingerprintVerifier` class in `production_qual/fingerprint_verifier.py`
- Verifies: R4 manifest, RiskPolicy, LiveRiskConfig, strategy version, full config
- Fail closed: any mismatch blocks ALL trading
- Wired into `r4_rebalance_loop.py` at startup AND every cycle
- Startup verification blocks trading if fingerprints don't match
**Tests:** 12 fingerprint verification tests (all pass)  
**Negative paths:** Manifest mutation, risk policy mutation, live risk mutation, version mutation, multiple simultaneous mutations

### 3. MT5 Provider Abstraction
**Commit:** (this session)  
**Problem:** All live code directly imports `from mt5linux import MetaTrader5` — Linux-only.  
**Root cause:** No abstraction layer between business logic and MT5.  
**Implementation:**
- Created `TradingProvider` ABC in `execution/trading_provider.py`
- Created `LinuxMT5Provider` (uses mt5linux)
- Created `WindowsMT5Provider` (uses official MetaTrader5 package)
- Created `create_trading_provider()` factory (platform-aware)
- Platform-agnostic data models: `AccountInfo`, `PositionInfo`, `TickInfo`, `SymbolInfo`, `OrderRequest`, `OrderResult`, `BarData`
- Fixed cross-platform signal handling (SIGTERM → SIGBREAK on Windows)
**Tests:** 20 trading provider contract tests (all pass)  
**Negative paths:** Not-connected queries, order submission when disconnected, Windows provider on Linux

### 4. Correct Daily Loss Accounting
**Commit:** (this session)  
**Problem:** `_daily_pnl_start` set once at startup, never reset at midnight.  
**Root cause:** No day-aware baseline management.  
**Implementation:**
- Created `DailyLossTracker` in `live/daily_loss.py`
- Resets at midnight UTC automatically
- Persists baseline to disk (atomic write + fsync)
- Survives process restart (loads existing baseline for same day)
- Handles corrupted baseline (treats as missing, creates fresh)
- `force_reset()` for reconnect scenarios
- Hash-verified baseline integrity
- Wired into `r4_rebalance_loop.py` with proper initialization
**Tests:** 17 daily loss tracker tests (all pass)  
**Negative paths:** Midnight rollover, restart same day, restart different day, corrupted baseline, force reset

### 5. Process Supervision
**Commit:** (this session)  
**Problem:** No process supervision; `--loop` is the only mechanism.  
**Root cause:** Not implemented.  
**Implementation:**
- Created `ProcessSupervisor` in `live/supervisor.py`
- PID file management (atomic write)
- Duplicate instance prevention (checks if existing PID is alive)
- Instance identity (unique ID per process)
- Health status file for external monitoring
- Restart count tracking
- FROZEN state for repeated failures
- Graceful shutdown via signal handlers
- Platform-neutral (no pgrep, no systemctl)
**Tests:** 13 supervisor tests (all pass)  
**Negative paths:** Stale PID files, duplicate claims, release cleanup

## Remaining P0 Fixes

### 6. Disconnect Safety
**Status:** NOT STARTED  
**Problem:** MT5 disconnect leaves positions unprotected; no halt-on-disconnect.  
**Required:**
- Wire `DisconnectRecovery` state machine into live loop
- Halt trading on disconnect
- Reconcile on reconnect before resuming
- Flatten option after max retries
- Tests for all disconnect scenarios

## Remaining Work

### P1 — Execution Reliability
- Wire `PartialFillManager` into live loop
- Add order ID persistence
- Add post-trade reconciliation
- Order timeout handling

### P1 — Observability
- Health endpoint
- Trading authorization status
- Structured state output

### P1 — Testing
- Integration tests with real MT5 (or mock)
- Failure injection tests
- Contract tests for providers

### P2 — Persistence
- Atomic writes for all JSONL files
- fsync after writes
- Log rotation

### P2 — OS Portability
- Replace `pgrep` in monitor
- Replace shell script with Python
- Windows deployment documentation

### P2 — Dependencies
- Add lockfile
- Declare all runtime dependencies in pyproject.toml

## Test Count Progression

| Milestone | Passed | Failed | New |
|-----------|--------|--------|-----|
| Baseline (0852d22) | 1942 | 5 | — |
| After config fix | 1956 | 5 | +14 |
| After fingerprint | 1968 | 5 | +12 |
| After provider | 1988 | 5 | +20 |
| After daily loss | 2005 | 5 | +17 |
| After supervisor | 2018 | 5 | +13 |
| **Total new** | — | — | **+76** |

## R4 Research Identity Verification

| Component | Pre-Remediation | Post-Remediation | Status |
|-----------|----------------|-----------------|--------|
| R4 Manifest Fingerprint | `aaab6c00dc05...` | `aaab6c00dc05...` | ✅ Unchanged |
| RiskPolicy Fingerprint | `a1eb1373fa11...` | `a1eb1373fa11...` | ✅ Unchanged |
| Strategy Version | R4.0 | R4.0 | ✅ Unchanged |
| T=0 Equity | 5010.94 | 5010.94 | ✅ Unchanged |
