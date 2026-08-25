# EigenCapital — Comprehensive Production-Grade & Platform-Agnostic Codebase Audit

**Audit Date:** 2026-08-25  
**Auditor:** Buffy (Codebuff)  
**Scope:** Full repository forensic audit  
**Verdict:** ⚠️ QUALIFICATION ONLY — NOT PRODUCTION READY

---

## Executive Verdict

**QUALIFICATION ONLY**

EigenCapital has sophisticated risk governance architecture (7 broker-authoritative gates, immutable campaign boundaries, hash-chained audit trails, frozen R4 manifest) but is **not production-ready** for continuous unattended operation. The system is **Linux-only by design** due to the `mt5linux` dependency, has **no process supervision**, contains **duplicated configuration** across at least 3 authoritative sources, has **empty test directories** for critical failure injection and integration scenarios, and the live trading scripts **bypass the broker abstraction layer** entirely.

The project CAN continue the $5K qualification under supervised operation (human starts and monitors the loop), but it CANNOT safely operate unattended, scale beyond the current scope, or run on Windows.

---

## Overall Scores

| Category | Score | Notes |
|----------|-------|-------|
| Architecture | 6/10 | Clean layering exists but not enforced at runtime |
| Risk | 7/10 | 7 gates are well-designed but daily loss tracking is broken |
| Execution | 5/10 | Scripts bypass abstraction; no atomic order persistence |
| Reliability | 3/10 | No process supervision, no crash recovery, no restart |
| Observability | 5/10 | Audit logs exist but no health endpoint, no dashboard |
| Security | 6/10 | No hard-coded secrets, but no secrets rotation |
| Testing | 4/10 | Unit tests for risk enforcement are excellent; integration/failure/simulation empty |
| Portability | 2/10 | Linux-only by design; pgrep, SIGTERM, shell scripts |
| Reproducibility | 5/10 | Config exists but triplicated; no lockfiles |
| Maintainability | 5/10 | Good docstrings; god-scripts; circular config concerns |

---

## 1. System Architecture Map

### Actual Architecture (verified from code)

```
Market Data (MT5 via mt5linux)
    ↓
Normalization (pandas DataFrame)
    ↓
Features (momentum: 12-1 month)
    ↓
R4 Signal (cross-sectional ranks → centered weights)
    ↓
Regime Gate (20-day vol < expanding median → full/zero exposure)
    ↓
Vol Scaling (60-day vol → 50% target → clip ±0.20)
    ↓
Portfolio Construction (top-N by |weight|, max 8 concurrent)
    ↓
RiskEnvelope (7 gates: connectivity, position count, drawdown, daily loss, equity floor, SL, fingerprint)
    ↓
Emergency Flatten (optional --flatten mode)
    ↓
Execution (mt5linux → MT5 order_send)
    ↓
MT5 Broker State
    ↓
Reconciliation (partial: comparison, not automated repair)
    ↓
Audit Log (JSONL append-only)
    ↓
Monitor (separate process: position diff, equity change, regime change)
    ↓
Telegram Alerts
```

### Divergence Between Documented and Executable Architecture

| Documented | Actual | Severity |
|------------|--------|----------|
| `BrokerAdapter` ABC exists | Scripts bypass it entirely, calling `mt5linux` directly | HIGH |
| `ExecutionBoundary` enforces authorization | `r4_rebalance_loop.py` has no authorization check | HIGH |
| `HealthGate` maps health → action | HealthGate exists in code but is not wired into the rebalance loop | MEDIUM |
| `DisconnectRecovery` state machine | Not instantiated anywhere in live scripts | MEDIUM |
| `ReconciliationEngine` | Exists in `execution/reconciliation.py` but is paper-only; live scripts have no reconciliation | HIGH |
| `PortfolioHealthMonitor` | Exists but not called from live loop | MEDIUM |
| Process supervision | Does not exist; `--loop` flag is the only mechanism | CRITICAL |

---

## 2. Production Readiness Audit

### 2.1 Startup Behavior
- `r4_rebalance_loop.py` connects to MT5 on startup via `MetaTrader5(host="127.0.0.1", port=8001)`
- No configuration validation at startup
- No fingerprint verification at startup
- No T=0 snapshot comparison at startup
- **Finding:** CRITICAL — The script starts trading immediately without verifying it's connected to the correct account, correct environment, or that the frozen manifest matches.

### 2.2 Shutdown Behavior
- SIGINT and SIGTERM handlers set a `_shutdown` flag
- Loop finishes current cycle before exiting
- **Finding:** MEDIUM — On Windows, SIGTERM is not available; only SIGINT works. No cleanup of partial orders on shutdown.

### 2.3 Restart Behavior
- No restart mechanism exists
- No state persistence across restarts
- `_daily_start_recorded` is a module-level global that resets on restart
- Peak equity resets to `t0_equity` on restart
- **Finding:** HIGH — Restart loses daily loss tracking state and peak equity tracking.

### 2.4 Crash Recovery
- No crash recovery mechanism
- JSONL audit log is append-only (good) but not fsync'd (bad)
- No WAL or journaling for crash consistency
- **Finding:** HIGH — Crash during write can corrupt the audit trail.

### 2.5 Process Supervision
- **Does not exist.** The `--loop` flag runs a `while not _shutdown` loop.
- `r4_monitor.py` uses `pgrep -f r4_rebalance_loop` to check if the loop is alive — **Linux-only**
- No automatic restart on crash
- No duplicate instance prevention
- **Finding:** CRITICAL — A production trading system MUST have process supervision.

### 2.6 Configuration Loading
- `config.py` loads from TOML files via `load_config()`
- BUT `r4_rebalance_loop.py` does NOT use `load_config()` — it hardcodes all values
- Three separate configuration sources for the same parameters:
  1. `configs/production/config.toml`
  2. `src/eigencapital/config.py` (Python dataclass defaults)
  3. `scripts/r4_rebalance_loop.py` (hardcoded constants)
- **Finding:** CRITICAL — Configuration can silently disagree between sources.

### 2.7 Secrets Handling
- No hard-coded credentials found in source code
- Account ID `436921728` is in config files (not a secret per se, but should be in env vars)
- `.env.example` shows the pattern but is not used by live scripts
- **Finding:** MEDIUM — Acceptable for demo account; MUST use env vars for live.

### 2.8 Dependency Pinning
- `pyproject.toml` has NO runtime dependencies listed (`dependencies = []`)
- `mt5linux`, `numpy`, `pandas` are imported but not declared as dependencies
- No lockfile exists
- **Finding:** HIGH — Two clean machines cannot reproduce the environment.

---

## 3. Platform-Agnostic Audit — CRITICAL

### Verdict: Linux-Only by Design

The system is **Category A: Linux-only by design**. This is not a minor portability gap — it is a fundamental architectural constraint.

### 3.1 `mt5linux` Dependency (CRITICAL)

Every live trading script and data provider imports:
```python
from mt5linux import MetaTrader5
```

`mt5linux` is a RPyC bridge that connects to a Python server running inside Wine on Linux. It is NOT the official MetaTrader5 Python package (which only runs on Windows). This means:

- **All live trading is Linux-only**
- **All data fetching from MT5 is Linux-only**
- The MT5 terminal must be running under Wine on the same machine
- The Wine/MT5 process must be started manually before the scripts work

**Files affected:** Every script in `scripts/` and several modules in `src/eigencapital/`

### 3.2 POSIX-Only Utilities (HIGH)

| Utility | Location | Impact |
|---------|----------|--------|
| `pgrep -f r4_rebalance_loop` | `scripts/r4_monitor.py` lines 368, 436 | Process health check fails on Windows |
| `/usr/bin/python3` | `scripts/r4_daily.sh` line 32 | Hard-coded Linux path |
| `flock -n 9` | `scripts/r4_daily.sh` line 15 | File locking is Linux-specific |
| `find . -type d -name __pycache__` | `Makefile` lines 29-30 | Linux-only (but dev-only) |

### 3.3 Signal Handling (MEDIUM)

```python
signal.signal(signal.SIGINT, _handle_signal)   # Works on Windows
signal.signal(signal.SIGTERM, _handle_signal)  # NOT available on Windows
```

`SIGTERM` is not a real signal on Windows. Python maps it to `SIGBREAK` on Windows, but behavior differs.

### 3.4 Shell Script (HIGH)

`scripts/r4_daily.sh` is a POSIX shell script that:
- Uses `/usr/bin/python3` (Linux path)
- Uses `flock` (Linux-specific file locking)
- Uses `$HOME/Projects/EigenCapital` (hard-coded path)
- **Cannot run on Windows at all**

### 3.5 Filesystem Assumptions
- `AUDIT_DIR = "reports/r4_loop"` — relative path, platform-agnostic (OK)
- `CONFIGS_DIR = Path(__file__).parent.parent.parent / "configs"` — uses pathlib (OK)
- No assumptions about `/tmp`, `/var`, `/proc`, `/dev` in production code

### 3.6 What Would Be Needed for Windows
1. Replace `mt5linux` with the official `MetaTrader5` Python package
2. Replace `pgrep` with `tasklist` or `psutil`
3. Replace shell script with Python or batch file
4. Replace `flock` with `msvcrt.locking` or `portalocker`
5. Remove `SIGTERM` handler or use `SIGBREAK` on Windows
6. Replace `/usr/bin/python3` with `sys.executable`

---

## 4. MT5 Portability Audit

### 4.1 Current MT5 Integration

The MT5 integration has **no abstraction boundary** in the live path:

```
r4_rebalance_loop.py  ──direct──→  mt5linux.MetaTrader5
r4_live_orders.py     ──direct──→  mt5linux.MetaTrader5
r4_monitor.py         ──direct──→  mt5linux.MetaTrader5
capture_t0.py         ──direct──→  mt5linux.MetaTrader5
account_readiness.py  ──direct──→  mt5linux.MetaTrader5
instrument_eligibility.py ──direct──→  mt5linux.MetaTrader5
```

The `BrokerAdapter` ABC exists in `shadow/contracts.py` but is **not used** by any live script.

### 4.2 MT5 Assumptions

| Assumption | Evidence | Impact |
|------------|----------|--------|
| MT5 runs under Wine on Linux | `from mt5linux import MetaTrader5` everywhere | Linux-only |
| MT5 is on localhost:8001 | `MetaTrader5(host="127.0.0.1", port=8001)` | Cannot use remote MT5 |
| Exness broker | Hardcoded in config and scripts | Broker-specific |
| Exness-MT5Trial9 server | Hardcoded in config | Server-specific |
| FOK filling mode | `filling_mode = MetaTrader5.ORDER_FILLING_FOK` | Broker-specific |
| Account 436921728 | Hardcoded in config | Account-specific |
| Symbol names without suffix | `R4_SYMBOLS = ["US30", "AUDJPY", ...]` | Broker-specific (Exness uses bare names; others use suffixes) |
| Magic number 20260825 | Hardcoded in scripts | Identification only |

### 4.3 Recommended Broker/Execution Adapter Boundary

The `BrokerAdapter` ABC should be the **mandatory** interface for all broker communication:

```python
class MT5BrokerAdapter(BrokerAdapter):
    """Real MT5 implementation via mt5linux or official API."""
    
    def __init__(self, host, port, account_id, environment):
        ...
    
    def connect(self) -> bool: ...
    def submit_order(self, order: BrokerOrder) -> Tuple[OrderResult, str]: ...
    def get_positions(self) -> Dict[str, float]: ...
    def get_account_state(self) -> Dict[str, Any]: ...
    def health_check(self) -> bool: ...
```

The live scripts should call `adapter.submit_order()` instead of directly calling `mt5.order_send()`.

---

## 5. Configuration Governance

### 5.1 Configuration Source Table

| Parameter | config.toml | config.py defaults | r4_rebalance_loop.py | Conflict? |
|-----------|-------------|-------------------|---------------------|-----------|
| max_concurrent_positions | 8 | 10 | 8 | ⚠️ config.py differs |
| max_position_notional | 1500 | 500000 | 1500 | ⚠️ config.py is 333x larger |
| max_order_notional | 1500 | 500000 | 1500 | ⚠️ config.py is 333x larger |
| max_daily_loss | 250 | 5000 | 250 | ⚠️ config.py is 20x larger |
| min_equity | — | 50000 | 4000 | ⚠️ config.py is 12.5x larger |
| max_drawdown_pct | 20 (capital) | 10 (risk) | 10 (envelope) | ⚠️ Three different values |
| account_id | 436921728 | 436921728 | — | ✅ Consistent |
| t0_equity | — | — | 5010.94 | ⚠️ Only in script |
| manifest_fingerprint | aaab6c... | aaab6c... | — | ✅ Consistent |

### 5.2 Critical Configuration Discrepancies

**CRITICAL: `RiskConfig` in `config.py` has `min_equity = 50,000` but the actual account has ~$5,000 equity.** If the `RiskPolicy` (which uses `RiskConfig` values) were actually applied to the live trading loop, every single trade would be rejected because equity is always below 50K.

The live loop uses `RiskEnvelope` (hardcoded in `r4_rebalance_loop.py`) with `min_equity = 4,000`, which IS appropriate for the $5K account.

This means the `RiskPolicy`/`EigenRiskEngine` path is **not connected** to the live trading loop. The live loop uses `RiskEnforcer` instead.

### 5.3 Risk Logic Duplication

There are **three separate risk enforcement implementations**:

1. **`risk/policy.py` + `risk/engine.py`** — `EigenRiskEngine` with `RiskPolicy` (paper trading)
2. **`live/risk_enforcement.py`** — `RiskEnforcer` with `RiskEnvelope` (live trading)
3. **`live/risk.py`** — `MicroLiveRiskEnvelope` (micro-live)

These have overlapping but inconsistent limits and are not cross-validated.

---

## 6. Live Risk Enforcement Audit

### 6.1 Seven Broker-Authoritative Gates

| # | Gate | Implemented? | Broker-Auth? | Before Orders? | Bypassable? | Data Missing? | Broker API Throw? | Stale Data? | Persisted? | Testable? |
|---|------|-------------|-------------|---------------|------------|--------------|-------------------|------------|-----------|----------|
| 1 | Broker Connectivity | ✅ | ✅ (equity+margin) | ✅ | ❌ | CRITICAL | Fail-closed (0,0) | Partially | Audit log | ✅ |
| 2 | Position Count | ✅ | ✅ (broker_positions) | ✅ | ❌ | Would pass (0 pos) | Fail-closed | Stale = pass | Audit log | ✅ |
| 3 | Account Drawdown | ✅ | ✅ (equity) | ✅ | ❌ | Would pass | Fail-closed | Stale data = stale DD | Audit log | ✅ |
| 4 | Daily Loss | ⚠️ | ⚠️ | ✅ | ❌ | Would pass (0 loss) | Fail-closed | Stale = stale loss | Audit log | ✅ |
| 5 | Equity Floor | ✅ | ✅ (equity) | ✅ | ❌ | Would fail (0 < 4000) | Fail-closed | Stale = stale equity | Audit log | ✅ |
| 6 | Position Protection | ✅ | ✅ (broker sl) | ✅ | ⚠️ (disabled) | Pass (check disabled) | Fail-closed | Stale SL state | Audit log | ✅ |
| 7 | Fingerprint | ✅ | ⚠️ (bool passed) | ✅ | ⚠️ (hardcoded True) | Would fail | Fail-closed | N/A | Audit log | ✅ |

### 6.2 Critical Gate Issues

**Gate 4 (Daily Loss) — BROKEN:**
```python
def __init__(self, envelope):
    self._daily_pnl_start = 0.0  # Initialized to 0

def record_daily_start(self, equity):
    self._daily_pnl_start = equity  # Set once at startup
```

The daily loss is computed as `self._daily_pnl_start - equity`. But `_daily_pnl_start` is **never reset between days**. If the process runs past midnight, the daily loss calculation accumulates across days.

In `r4_rebalance_loop.py`:
```python
if not _daily_start_recorded:
    _risk_enforcer.record_daily_start(account.equity)
    _daily_start_recorded = True
```

This is called **once** at startup. If the process starts at 23:59 and runs past midnight, the daily loss window spans two calendar days.

**Gate 6 (Position Protection) — DISABLED:**
```python
RISK_ENVELOPE = RiskEnvelope(
    require_sl_on_positions=False,  # R4 uses signal-based exits, not fixed SL
)
```

This is intentionally disabled because R4 uses signal-based exits. However, the audit requirement states: "determine whether an unprotected position causes a CRITICAL state." Currently it does NOT cause any state change because the check is disabled.

**Gate 7 (Fingerprint) — HARDCODED:**
```python
all_pass, gate_results = _risk_enforcer.check_all(
    ...
    fingerprint_match=True,  # Always True — never actually checked
)
```

The fingerprint gate always passes because `fingerprint_match` is hardcoded to `True`.

---

## 7. Order Lifecycle Audit

### 7.1 Current Order Flow (r4_rebalance_loop.py)

```
1. Compute R4 signal
2. Regime gate check
3. Get broker positions
4. Run risk gates
5. Generate orders (generate_orders)
6. Execute orders (execute_orders → mt5.order_send)
7. Sleep 1 second
8. Read post-trade state
9. Audit log
```

### 7.2 Missing Transitions

| Transition | State | Persistence | Idempotency | Retry | Failure | Duplicate Handling |
|------------|-------|------------|-------------|-------|---------|-------------------|
| Signal → Target Weight | In-memory | ❌ None | N/A | N/A | N/A | N/A |
| Target → Order | In-memory | ❌ None | ❌ None | ❌ None | Silent skip | ❌ None |
| Order → Broker Submit | In-memory | ❌ None | ❌ None | ❌ None | Log error, continue | ❌ None |
| Broker → Fill | Not tracked | ❌ None | N/A | N/A | N/A | N/A |
| Fill → Position | Not tracked | ❌ None | N/A | N/A | N/A | N/A |
| Position → Reconciliation | Not implemented | N/A | N/A | N/A | N/A | N/A |

### 7.3 Critical Order Lifecycle Gaps

1. **No order ID tracking** — Orders are submitted but the result (deal number) is only logged, not persisted
2. **No partial fill handling** — `PartialFillManager` exists in code but is NOT used by the live loop
3. **No order timeout** — If `mt5.order_send()` hangs, the loop hangs
4. **No idempotency** — If the loop crashes after order submission but before logging, the order could be re-submitted on restart
5. **No reconciliation** — The `ReconciliationEngine` exists but is paper-only; live scripts have no reconciliation
6. **No atomic state** — Position state is derived from broker queries each cycle, not from a local authoritative store

---

## 8. Position Protection Audit

### 8.1 Current State

- **SL is NOT mandatory** — `require_sl_on_positions=False` in the live envelope
- **SL is NOT calculated** — R4 uses signal-based exits, not fixed SL
- **SL is NOT attached** — Orders are submitted without SL/TP
- **No CRITICAL state for unprotected positions** — The check is disabled
- **No repair mechanism** — If SL were to be required, there's no code to attach it to existing positions
- **TP/trailing behavior** — Intentionally absent (R4 uses weekly rebalance, not intraday management)

### 8.2 Assessment

The absence of SL is **intentional** for the R4 strategy design (signal-based weekly exits). However:
- This means a broker disconnection during the week leaves positions completely unprotected
- A gap down on Monday could cause losses beyond any calculated risk
- The `emergency_flatten` function exists but requires the process to be running

---

## 9. Health and Safety State Machines

### 9.1 Health State Machine (monitoring/health.py)

```
HEALTHY ←→ DEGRADED → CRITICAL → FROZEN
                        ↑
                   (any CRITICAL alert)
```

**Implemented transitions:**
- HEALTHY → DEGRADED: warning threshold breached
- DEGRADED → CRITICAL: hard constraint breached
- CRITICAL → FROZEN: kill switch activated
- No recovery transitions implemented (one-way escalation only)

**Missing transitions:**
- DEGRADED → HEALTHY: No automatic recovery
- CRITICAL → DEGRADED: No recovery path
- FROZEN → anything: Only via `authorize_reset()` in DisconnectRecovery

### 9.2 Disconnect Recovery State Machine (live/risk.py)

```
CONNECTED → DISCONNECTED → RECONCILING → RESUMED
                ↓               ↓
             HALTED          HALTED
                ↓
             FROZEN (excessive disconnects)
```

**Implemented transitions:**
- CONNECTED → DISCONNECTED: `on_disconnect()`
- DISCONNECTED → RECONCILING: `on_reconnect()`
- RECONCILING → RESUMED: `request_resume()` (all checks pass)
- RECONCILING → HALTED: `submit_reconciliation()` (mismatch)
- RECONCILING → HALTED: `request_resume()` (check fails)
- DISCONNECTED → FROZEN: `on_disconnect()` (excessive attempts)

**Critical gap:** This state machine is **never instantiated** in the live scripts. The `DisconnectRecovery` class exists but is not wired into `r4_rebalance_loop.py`.

### 9.3 What Actually Happens on Disconnect

In `r4_rebalance_loop.py`:
```python
try:
    result = run_cycle(mt5, force_regime, dry_run)
except Exception as e:
    log(f"❌ Cycle error: {e}")
    audit({"event": "error", "error": str(e)})
    result = {"status": "ERROR"}
```

On MT5 disconnect:
1. `mt5.account_info()` returns `None`
2. `account.equity` raises `AttributeError`
3. Exception is caught
4. Error is logged
5. Loop continues to next cycle
6. **No position flattening**
7. **No state transition**
8. **No alert sent** (beyond the audit log entry)

---

## 10. Process Lifecycle / Continuous Operation

### 10.1 Current Process Model

```
User runs: python scripts/r4_rebalance_loop.py --loop --interval 3600
    ↓
while not _shutdown:
    run_cycle()
    sleep(interval)
    ↓
User presses Ctrl+C
    ↓
mt5.shutdown()
```

### 10.2 What's Missing

| Requirement | Status | Impact |
|------------|--------|--------|
| Process supervision | ❌ Missing | Crash = dead system |
| Duplicate instance prevention | ❌ Missing | Two loops = double orders |
| Automatic restart | ❌ Missing | Any crash = manual intervention |
| Health endpoint | ❌ Missing | Cannot probe from outside |
| Log rotation | ❌ Missing | JSONL grows unbounded |
| Graceful drain | ❌ Missing | Ctrl+C may interrupt mid-order |
| State persistence | ❌ Missing | Restart loses all state |
| OS-independent daemonization | ❌ Missing | Linux-only via shell script |

### 10.3 Recommended Architecture

```
EigenCapital Application (Python)
    ↓
Process Supervisor (cross-platform)
    ├── Option A: systemd (Linux) / nssm (Windows)
    ├── Option B: Docker container with restart policy
    └── Option C: Python supervisor (watchdog + PID file)
    ↓
Health Endpoint (HTTP or file-based)
    ↓
Restart / Alert on failure
```

For the $5K qualification, the minimum viable supervision is:
1. A PID file to prevent duplicate instances
2. A wrapper script that restarts on crash
3. A health file that the monitor checks

---

## 11. Data and Time Integrity

### 11.1 Unsafe Datetime Usage

| Location | Usage | Safe? |
|----------|-------|-------|
| `r4_rebalance_loop.py` | `datetime.now(timezone.utc)` | ✅ UTC-aware |
| `r4_monitor.py` | `datetime.now(timezone.utc)` | ✅ UTC-aware |
| `monitoring/health.py` | `datetime.now(timezone.utc)` | ✅ UTC-aware |
| `risk_enforcement.py` | `datetime.now(timezone.utc).isoformat()` | ✅ UTC-aware |
| `core/models/errors.py` | `datetime.utcnow()` | ⚠️ Deprecated, but UTC |
| `research/intraday/*.py` | `datetime.now()` (multiple) | ❌ Naive, local timezone |
| `micro_live/runner.py` | `time.time()` | ⚠️ Epoch, no timezone |

### 11.2 Timezone Concerns
- MT5 broker server time may differ from local time
- DST transitions could cause issues with daily loss reset
- No explicit timezone configuration exists

---

## 12. Persistence and Crash Consistency

### 12.1 Persistent Artifacts

| Artifact | Format | Atomic? | fsync? | Concurrent Writers? | Recovery |
|----------|--------|---------|--------|--------------------|-------------|
| `decisions.jsonl` | JSONL append | ❌ No | ❌ No | ⚠️ Possible (no lock) | Partial line = corrupt |
| `monitor.jsonl` | JSONL append | ❌ No | ❌ No | ⚠️ Possible | Partial line = corrupt |
| `last_positions.json` | JSON | ❌ No (write truncates) | ❌ No | ⚠️ Possible | Truncated = corrupt |
| `last_equity.json` | JSON | ❌ No | ❌ No | ⚠️ Possible | Truncated = corrupt |
| `last_regime.json` | JSON | ❌ No | ❌ No | ⚠️ Possible | Truncated = corrupt |
| `last_health.json` | JSON | ❌ No | ❌ No | ⚠️ Possible | Truncated = corrupt |

### 12.2 Critical Persistence Issues

1. **No atomic writes** — `json.dump()` writes directly to the file; a crash mid-write corrupts it
2. **No fsync** — Data may be in OS buffer cache, not on disk
3. **No file locking** — Monitor and loop could write simultaneously
4. **No backup** — No rotation, no backup, no integrity verification
5. **No hash chaining** — JSONL files don't chain hashes (the in-memory health log does, but not the on-disk files)

### 12.3 Recommended Fix

Use atomic write pattern:
```python
import tempfile
def atomic_write_json(path, data):
    tmp = tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False)
    json.dump(data, tmp)
    tmp.flush()
    os.fsync(tmp.fileno())
    tmp.close()
    os.replace(tmp.name, path)  # Atomic on POSIX
```

---

## 13. Observability

### 13.1 Operator Questions

| Question | Answerable? | How |
|----------|------------|-----|
| Is the system running? | ⚠️ Only via `pgrep` (Linux) | Monitor checks process |
| Is MT5 connected? | ❌ Not directly | Monitor reconnects each cycle |
| Is the correct account connected? | ❌ Not verified at startup | Should check at startup |
| Is the correct manifest loaded? | ❌ Not verified at startup | Fingerprint gate hardcoded True |
| Is the system trading? | ✅ Via audit log | Read decisions.jsonl |
| Why did it not trade? | ⚠️ Partially | Audit log has regime_skip, risk_blocked |
| What is the current regime? | ✅ Via last_regime.json | Monitor writes it |
| What positions exist? | ✅ Via last_positions.json | Monitor writes it |
| What is current exposure? | ❌ Not directly | Would need to compute from positions |
| What risk gates are active? | ✅ Via audit log | Gate results logged |
| Why was an order blocked? | ✅ Via audit log | Risk gate messages |
| Has the system reconciled? | ❌ No reconciliation exists | N/A |
| Has the process restarted? | ❌ No restart detection | N/A |
| Has any safety state changed? | ⚠️ Partially | Monitor tracks position changes |
| Are alerts working? | ⚠️ Telegram only | No health check for alert delivery |

### 13.2 Missing Observability

- No HTTP health endpoint
- No metrics (Prometheus, etc.)
- No structured logging (uses `print()` with timestamps)
- No dashboard
- No log rotation
- No alert delivery confirmation

---

## 14. Security Audit

### 14.1 Findings

| Finding | Severity | Location |
|---------|----------|----------|
| Account ID in config files | LOW | `configs/production/config.toml` |
| Magic number hardcoded | INFO | `scripts/r4_rebalance_loop.py` line 376 |
| Telegram bot token in env vars | OK | `scripts/r4_monitor.py` |
| No hard-coded passwords/API keys | OK | — |
| No secrets in git history | ⚠️ Cannot verify | — |
| `sys.path.insert(0, "src")` | LOW | Multiple scripts — path traversal risk in dev |
| No dependency vulnerability scanning | MEDIUM | No safety/bandit in CI |

### 14.2 Positive Security Patterns

- RiskPolicy is a frozen dataclass (immutable)
- Campaign boundary is immutable
- Authorization requires explicit human grant
- Kill switch is independent of strategy logic
- Audit log is append-only with hash chaining (in-memory)

---

## 15. Testing Quality Audit

### 15.1 Test Coverage Assessment

| Category | Tests | Quality | Notes |
|----------|-------|---------|-------|
| Unit: Risk Enforcement | ✅ 30+ tests | Excellent | Covers 9>8 regression, all gates, boundaries |
| Unit: Architecture Audit | ✅ 7 tests | Good | Verifies no bypass paths |
| Unit: Risk Policy | ✅ Exists | Good | Frozen dataclass validation |
| Unit: Health Monitor | ✅ Exists | Good | Hash chain verification |
| Integration | ❌ Empty | CRITICAL | No integration tests |
| Failure Injection | ❌ Empty | CRITICAL | No failure scenario tests |
| Property-based | ⚠️ 1 test file | Minimal | Only core properties |
| Simulation | ❌ Empty | HIGH | No simulation tests |
| Broker Integration | ❌ None | CRITICAL | No real broker tests |
| Portability | ❌ None | HIGH | No cross-platform tests |
| Restart/Recovery | ❌ None | CRITICAL | No restart tests |
| Concurrency | ❌ None | HIGH | No race condition tests |
| End-to-end | ❌ None | CRITICAL | No E2E tests |

### 15.2 Tests That Could Pass While Production Is Broken

1. **Risk enforcement tests use mock data** — They test the `RiskEnforcer` class in isolation but don't test whether the rebalance loop actually calls it correctly
2. **Architecture audit tests check source code text** — `test_strategy_cannot_import_order` reads source files and checks for string patterns, which is fragile
3. **No test for daily loss reset** — The daily loss tracking bug (never resetting between days) has no test
4. **No test for MT5 disconnect handling** — The exception-swallowing in the main loop has no test
5. **No test for fingerprint gate** — The hardcoded `fingerprint_match=True` has no test

---

## 16. Research Integrity Preservation

### 16.1 Frozen Manifest

The `R4ConfigManifest` in `fidelity/r4_manifest.py` is a frozen dataclass that captures:
- Strategy name, version, hash
- Feature registry version, hash
- Data source, terminal ID, snapshot hash
- Universe (15 symbols with `m` suffix)
- Risk parameters, signal parameters, cost model
- Validation thresholds

**Fingerprint:** `aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb`

### 16.2 Integrity Risks

| Risk | Status | Evidence |
|------|--------|----------|
| Production can retrain | ✅ Protected | No training code in live path |
| Production can change parameters | ⚠️ Partially protected | Hardcoded in scripts, not loaded from manifest |
| Production can change universe | ⚠️ Partially protected | `ELIGIBLE_SYMBOLS` hardcoded in scripts |
| Production can bypass regime | ⚠️ Possible | `--force-regime` flag exists |
| Production can change sizing | ⚠️ Partially protected | `MAX_POSITION_USD` hardcoded |
| T=0 snapshot immutable | ✅ Yes | `CampaignStartSnapshot` is frozen |
| RiskPolicy fingerprint immutable | ✅ Yes | `RiskPolicy` is frozen dataclass |
| Manifest checked at runtime | ❌ No | Fingerprint gate hardcoded True |

### 16.3 Critical Gap

The frozen R4 manifest exists but is **not loaded or verified** by the live trading scripts. The scripts use their own hardcoded constants that are SEPARATE from the manifest. If someone changes the manifest, the live scripts would not notice.

---

## 17. Performance and Reliability

### 17.1 Resource Usage
- **CPU:** Minimal (pandas operations on small DataFrames)
- **RAM:** ~100MB (pandas + numpy)
- **Network:** MT5 connection only (local Wine bridge)
- **Disk:** JSONL append-only (unbounded growth)

### 17.2 Long-Running Stability Concerns
1. **JSONL file growth** — `decisions.jsonl` grows without bound; no rotation
2. **Memory growth** — `RiskEnforcer._audit_log` grows without bound
3. **MT5 connection staleness** — Connection may silently die; no heartbeat
4. **Floating-point drift** — Cumulative position calculations could drift over weeks

### 17.3 Can It Run for 30 Days?

| Requirement | Status |
|------------|--------|
| 24 hours supervised | ✅ Yes (with manual start) |
| 24 hours unattended | ❌ No (no supervision) |
| 7 days | ❌ No (audit log grows, no restart) |
| 30 days | ❌ No (all of the above + daily loss reset bug) |

---

## 18. Platform Test Matrix

| Environment | Research | Paper | MT5 | Live | Status |
|------------|---------:|------:|----:|-----:|--------|
| Linux native | ✅ | ✅ | ⚠️ (needs Wine+MT5) | ⚠️ (needs Wine+MT5) | Primary platform |
| Windows native | ✅ | ✅ | ❌ (needs mt5linux replacement) | ❌ (needs mt5linux replacement) | Not supported |
| Linux + Wine | ✅ | ✅ | ✅ | ✅ | Tested architecture |
| Windows VPS | ✅ | ✅ | ❌ | ❌ | Not supported |
| Docker/Linux | ✅ | ✅ | ⚠️ (Wine in Docker) | ⚠️ (Wine in Docker) | Possible but untested |

---

## 19. Production Failure Scenarios

### Scenario Analysis (25 scenarios)

| # | Scenario | Detection | Immediate Action | Trading | Position | Recovery | Notification | Audit |
|---|----------|-----------|-----------------|---------|----------|----------|-------------|-------|
| 1 | MT5 disconnect | Exception in `mt5.account_info()` | Log error, continue loop | Continues (may fail) | No change | Next cycle retry | ❌ No alert | ✅ Logged |
| 2 | MT5 terminal crash | Same as disconnect | Same | Same | No change | Same | ❌ No | ✅ |
| 3 | Python process crash | N/A (dead) | N/A | Dead | No change | ❌ Manual restart | ❌ No | Partial (last JSONL) |
| 4 | Machine reboot | N/A (dead) | N/A | Dead | No change | ❌ Manual restart | ❌ No | Partial |
| 5 | Network outage | Same as disconnect | Same | Same | No change | Same | ❌ No | ✅ |
| 6 | Stale market data | Not detected | N/A | May trade on stale | May get bad fills | N/A | ❌ No | ❌ No |
| 7 | Broker timeout | Exception | Log error | Continues | No change | Next cycle | ❌ No | ✅ |
| 8 | Order timeout | Not implemented | N/A | Order may hang | Unknown | N/A | ❌ No | ❌ No |
| 9 | Duplicate order response | Not handled | N/A | May double-fill | Incorrect position | N/A | ❌ No | ❌ No |
| 10 | Partial fill | Not handled | N/A | Incomplete position | Incorrect | N/A | ❌ No | ❌ No |
| 11 | Rejected order | `result.retcode != DONE` | Log error | Continues | No change | Next cycle | ❌ No | ✅ |
| 12 | Rejected SL | N/A (SL not submitted) | N/A | N/A | Unprotected | N/A | ❌ No | N/A |
| 13 | Position mismatch | Not detected | N/A | Unknown | Incorrect | N/A | ❌ No | ❌ No |
| 14 | Equity mismatch | Not detected | N/A | Unknown | Incorrect | N/A | ❌ No | ❌ No |
| 15 | Fingerprint mismatch | Not detected (hardcoded True) | N/A | Continues | May be wrong strategy | N/A | ❌ No | ❌ No |
| 16 | Corrupted snapshot | Not detected | N/A | Unknown | Unknown | N/A | ❌ No | ❌ No |
| 17 | Corrupted audit log | Not detected | N/A | Continues | No change | N/A | ❌ No | ❌ No |
| 18 | Clock drift | Not detected | N/A | May affect daily loss | Incorrect daily P&L | N/A | ❌ No | ❌ No |
| 19 | Disk full | `open()` raises | Exception caught | Continues (audit fails) | No change | N/A | ❌ No | ❌ No |
| 20 | Insufficient margin | MT5 rejects order | Log error | Continues | No change | Next cycle | ❌ No | ✅ |
| 21 | Spread explosion | Not checked in loop | N/A | May trade at bad price | Unfavorable fill | N/A | ❌ No | ❌ No |
| 22 | Unexpected manual trade | Not detected at runtime | N/A | May conflict | Incorrect attribution | N/A | ❌ No | ❌ No |
| 23 | Duplicate process | Not prevented | N/A | Double orders | Over-trading | N/A | ❌ No | ❌ No |
| 24 | Config drift | Not detected | N/A | Wrong parameters | Incorrect behavior | N/A | ❌ No | ❌ No |
| 25 | Symbol spec change | Not detected | N/A | Wrong lot sizes | Incorrect sizing | N/A | ❌ No | ❌ No |

**Summary:** Of 25 failure scenarios, only 3 have proper detection AND audit trail. 0 have automatic recovery. 0 have operator notification (except via manual Telegram alerts).

---

## 20. Code Quality / Maintainability

### 20.1 God Scripts

`r4_rebalance_loop.py` (680+ lines) contains:
- Configuration constants
- MT5 connection
- Data fetching
- Signal computation (frozen R4)
- Order generation
- Order execution
- Emergency flatten
- Audit logging
- Signal handling
- Main loop

This should be split into:
- `r4_signal.py` — Signal computation
- `r4_orders.py` — Order generation
- `r4_execution.py` — Order execution
- `r4_loop.py` — Main loop orchestration

### 20.2 Separation of Concerns

| Layer | Clean? | Notes |
|-------|--------|-------|
| Research | ✅ | Well-separated in `research/` |
| Risk | ⚠️ | Three competing implementations |
| Execution | ❌ | Scripts bypass abstraction |
| Broker | ❌ | No adapter boundary in live path |
| Platform | ❌ | Linux-only, hardcoded |
| Observability | ⚠️ | Exists but not integrated |

### 20.3 Dead Code

- `execution/adapters/` — Empty directory (adapter pattern not implemented)
- `reconciliation/__init__.py` — Empty module
- `LiveBrokerAdapter` in `live/broker.py` — Simulated, not real MT5
- `DisconnectRecovery` — Never instantiated
- `HealthGate` — Never wired into live loop
- `ExecutionBoundary` — Never used in live scripts

---

## 21. Recommended Remediation Plan

### P0 — Blocks Live Operation (must fix before continuing qualification)

| # | Finding | Root Cause | Minimal Fix | Test Required |
|---|---------|-----------|-------------|---------------|
| P0-1 | Daily loss never resets between days | `_daily_pnl_start` set once at startup | Reset daily start equity at midnight UTC | Unit test: verify reset across day boundary |
| P0-2 | Fingerprint gate hardcoded True | Not wired to manifest | Load manifest fingerprint, compare at startup | Unit test: verify mismatch blocks |
| P0-3 | No process supervision | Not implemented | Add PID file + wrapper restart script | Integration test: kill process, verify restart |
| P0-4 | No duplicate instance prevention | Not implemented | PID file lock with `fcntl.flock` (Linux) or `msvcrt` (Windows) | Test: start two instances, verify second fails |
| P0-5 | MT5 disconnect leaves positions unprotected | No flatten on disconnect | Add flatten-on-disconnect after max retries | Failure injection test |

### P1 — Must Fix Before Scaling Beyond $5K

| # | Finding | Root Cause | Minimal Fix | Test Required |
|---|---------|-----------|-------------|---------------|
| P1-1 | Scripts bypass BrokerAdapter | No adapter boundary | Create MT5BrokerAdapter, wire into scripts | Integration test with real MT5 |
| P1-2 | No order persistence | No local state store | Persist order IDs + fills to JSONL atomically | Crash recovery test |
| P1-3 | No reconciliation | Not implemented for live | Add post-trade reconciliation check | Integration test |
| P1-4 | Three competing risk implementations | Organic growth | Consolidate into single RiskPolicy with per-environment overrides | Regression test suite |
| P1-5 | Configuration triplicated | No single source of truth | Load ALL config from TOML, remove hardcoded constants | Config drift test |
| P1-6 | No partial fill handling in live loop | Not wired | Integrate PartialFillManager | Unit + integration test |

### P2 — Important Production Hardening

| # | Finding | Root Cause | Minimal Fix |
|---|---------|-----------|-------------|
| P2-1 | JSONL not atomic | Direct write | Use atomic write pattern (temp file + rename) |
| P2-2 | No fsync | Not implemented | Add fsync after write |
| P2-3 | Unbounded audit log growth | No rotation | Add log rotation (daily or size-based) |
| P2-4 | No MT5 heartbeat | Not implemented | Add periodic `mt5.account_info()` check |
| P2-5 | No order timeout | Not implemented | Add `max_order_age` check |
| P2-6 | Spread not checked in rebalance loop | Not implemented | Add per-symbol spread check before order |
| P2-7 | `datetime.now()` in research code | Naive datetimes | Replace with `datetime.now(timezone.utc)` |
| P2-8 | No secrets in env vars for live | Hardcoded config | Move account_id, server to env vars |
| P2-9 | Makefile uses `find` (Linux) | Linux-only clean | Use `pathlib` or cross-platform clean |

### P3 — Technical Debt

| # | Finding | Root Cause | Minimal Fix |
|---|---------|-----------|-------------|
| P3-1 | Empty test directories | Not written | Write integration, failure injection, simulation tests |
| P3-2 | `sys.path.insert` in scripts | Not using installed package | Use `pip install -e .` properly |
| P3-3 | `print()` for logging | No logging framework | Use `logging` module |
| P3-4 | God scripts | Not refactored | Split into modules |
| P3-5 | Dead code (empty adapters dir, unused classes) | Incomplete refactoring | Remove or complete |
| P3-6 | No type checking in CI | Not configured | Add mypy to CI |
| P3-7 | No lockfile | Not generated | Add pip-compile or poetry.lock |

---

## 22. Verification Plan

### After P0 Fixes

1. Run full test suite: `python -m pytest tests/ -v`
2. Run lint: `python -m ruff check src/ tests/`
3. Run type check: `python -m mypy src/eigencapital/`
4. Verify R4 fingerprint unchanged: `python -c "from eigencapital.fidelity.r4_manifest import R4ConfigManifest; print(R4ConfigManifest().compute_identity())"`
5. Verify T=0 snapshot unchanged
6. Verify RiskPolicy fingerprint unchanged
7. Run risk enforcement tests: `python -m pytest tests/unit/live/test_risk_enforcement.py -v`
8. Run architecture audit tests: `python -m pytest tests/unit/test_architecture_audit.py -v`
9. Manual: Start loop, verify PID file created, verify second instance blocked
10. Manual: Kill process, verify wrapper restarts it
11. Manual: Simulate MT5 disconnect, verify flatten behavior

### Before Continuing Qualification

1. All P0 fixes merged and tested
2. Daily loss reset verified across midnight
3. Fingerprint gate verified against manifest
4. Process supervision verified (crash → restart)
5. MT5 disconnect → flatten behavior verified
6. No configuration discrepancies between TOML and scripts

---

## 23. Critical Rules Compliance

| Rule | Status | Evidence |
|------|--------|----------|
| Do NOT modify R4 parameters | ✅ Compliant | R4 constants unchanged |
| Do NOT optimize the strategy | ✅ Compliant | No strategy modifications |
| Do NOT retune thresholds | ✅ Compliant | RiskEnvelope unchanged |
| Do NOT reopen frozen research | ✅ Compliant | No research mutations |
| Do NOT weaken risk controls | ✅ Compliant | All 7 gates intact |
| Do NOT bypass regime gate | ⚠️ Partially | `--force-regime` flag exists |
| Do NOT manufacture trades | ✅ Compliant | No synthetic trades |
| Do NOT change T=0 boundary | ✅ Compliant | CampaignStartSnapshot immutable |
| Do NOT silently alter manifest | ✅ Compliant | Manifest is frozen dataclass |

---

## 24. Final Assessment

### What EigenCapital Does Well

1. **Sophisticated risk architecture** — The 7-gate broker-authoritative risk enforcement is genuinely well-designed
2. **Immutable campaign boundaries** — Frozen dataclasses, hash-chained audit trails, position classification
3. **Pre-trading validation** — The 5-step pre-trading sequence is thorough
4. **Risk enforcement regression tests** — The 9>8 position count tests are excellent
5. **Research integrity** — R4 manifest, fingerprint verification, experiment immutability
6. **Documentation** — Comprehensive audit contracts, governance documents

### What Must Be Fixed

1. **Process supervision** — The single most critical gap for production operation
2. **Configuration single source of truth** — Three competing configurations is dangerous
3. **MT5 disconnect handling** — Positions must be flattened or protected
4. **Daily loss reset** — Currently broken across day boundaries
5. **Fingerprint verification** — Must actually check the manifest at runtime
6. **Integration/failure tests** — Empty test directories for critical scenarios

### Bottom Line

EigenCapital has the **architectural vision** of a production-grade trading system but lacks the **operational infrastructure** to safely run unattended. The risk governance is sophisticated but disconnected from the live execution path. The system CAN continue the $5K qualification under **supervised operation** (human starts, monitors, and can intervene), but it **CANNOT** safely:

- Run unattended for 24+ hours
- Survive a process crash without manual intervention
- Detect and respond to MT5 disconnects
- Operate on Windows
- Scale beyond the current $5K scope

The path to production readiness requires implementing P0 fixes (estimated 2-3 days of focused work) before the qualification can safely continue.

---

*This audit was conducted adversarially and evidence-driven. Every finding is backed by specific code references. The objective was to find what could actually break, not to make the project appear production-ready.*
