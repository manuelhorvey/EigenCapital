# Cross-Platform Architecture

> **Status:** Production-ready — tested on Linux + Wine and native Windows.  
> **Module:** `eigencapital/platform/`  
> **Tests:** `tests/test_platform_*` (306 tests)

---

## Overview

The platform abstraction layer centralises every OS-specific behaviour in the codebase behind well-defined interfaces. Business logic in `paper_trading/`, `features/`, `shared/`, etc. never references `sys.platform`, `os.name`, hardcoded paths, or platform-specific APIs directly.

```
                    ┌──────────────────────┐
                    │   Business Logic      │
                    │  (paper_trading,      │
                    │   features, shared)   │
                    └───────┬──────┬───────┘
                            │      │
                    ┌───────▼──────▼───────┐
                    │  eigencapital/       │
                    │  platform/           │
                    │                      │
                    │  detector            │
                    │  paths               │
                    │  signals             │
                    │  process             │
                    │  mt5_strategies      │
                    │  mt5_bridge_manager  │
                    └───────┬──────┬───────┘
                            │      │
               ┌────────────▼──┐ ┌─▼────────────┐
               │   Linux +     │ │   Windows     │
               │   Wine        │ │   Native      │
               └───────────────┘ └──────────────┘
```

---

## Module Reference

### 1. `detector.py` — Platform Detection

**File:** `eigencapital/platform/detector.py`  
**Tests:** `tests/test_platform_detector.py`

Singleton service that detects and caches the runtime platform. All `sys.platform` and `os.name` calls are isolated here.

**Detection outputs:**

| Property | Values | Detection Method |
|---|---|---|
| `platform` | `LINUX`, `WINDOWS`, `MACOS`, `UNKNOWN` | `sys.platform` |
| `is_wine` | `True`/`False` | Wine on PATH, `WINEPREFIX` env var, `MetaTrader5` import under Linux |
| `deployment_mode` | `DEVELOPMENT`, `PRODUCTION`, `CONTAINER` | `EIGENCAPITAL_DEPLOYMENT` env var, Kubernetes/Docker heuristics |
| `architecture` | `x86_64`, `AMD64`, etc. | `platform.machine()` |
| `mt5_available` | `True`/`False` | `MetaTrader5` import check |

**Deployment mode resolution order:**
1. `EIGENCAPITAL_DEPLOYMENT` env var (explicit override: `production`, `container`, `development`)
2. `KUBERNETES_SERVICE_HOST` or `DOCKER` env var → `CONTAINER`
3. `.git` directory exists → `DEVELOPMENT`
4. Otherwise → `PRODUCTION`

**Usage:**
```python
from eigencapital.platform import detect

plat = detect()
if plat.is_windows:
    # Windows-native path
elif plat.is_linux and plat.is_wine:
    # Linux + Wine path
```

---

### 2. `paths.py` — Path Resolution

**File:** `eigencapital/platform/paths.py`  
**Tests:** `tests/test_platform_paths.py`

Cross-platform directory resolution. All paths use `pathlib.Path` — never string concatenation or `os.path.join`.

**Module-level functions:**

| Function | Returns |
|---|---|
| `resolve_project_root()` | Auto-detected project root (walks up from `__file__`) |
| `resolve_data_dir()` | `{root}/data` |
| `resolve_log_dir()` | `{root}/data/live` |
| `resolve_config_dir()` | `{root}/configs` |
| `resolve_model_dir()` | `{root}/paper_trading/models` |
| `resolve_backup_dir()` | `{root}/data/backups/sqlite` |
| `resolve_cache_dir()` | `{root}/data/live/cache` |

**Stateful `PathResolver` class:**
Useful in tests and multi-instance deployments — supply an explicit base directory:

```python
from eigencapital.platform import PathResolver

resolver = PathResolver("/custom/deployment/path")
resolver.live_dir  # /custom/deployment/path/data/live
resolver.state_path  # /custom/deployment/path/data/live/state.json
resolver.ensure_dirs()  # Create all required directories
```

---

### 3. `signals.py` — Shutdown & Signal Handling

**File:** `eigencapital/platform/signals.py`  
**Tests:** `tests/test_platform_signals.py`

Cooperative shutdown via `threading.Event` works identically on all platforms.

**Platform differences handled internally:**
- **Linux:** `SIGTERM` and `SIGINT` are caught via `signal.signal()` for graceful shutdown.
- **Windows:** `SIGTERM` immediately kills the process (cannot be caught). `SIGINT` (Ctrl+C) is caught. The `ShutdownManager` provides a programmatic `trigger()` that works on both platforms.
- Signal handler registration is wrapped in `try/except` for platforms that don't support specific signals.

**Usage:**
```python
from eigencapital.platform import ShutdownManager, install_graceful_shutdown

shutdown = ShutdownManager()
install_graceful_shutdown(shutdown)

while not shutdown.is_set():
    shutdown.wait(timeout=30.0)

# Cleanup runs here on both platforms
```

**Handler registration:**
```python
def on_exit():
    save_state()

register_shutdown_handler(on_exit)
# Safe to call before install_graceful_shutdown() — handlers are queued
```

---

### 4. `process.py` — Process Management

**File:** `eigencapital/platform/process.py`  
**Tests:** `tests/test_platform_process.py`

Cross-platform process discovery, health checks, and termination.

**Capabilities:**

| Function | Linux Method | Windows Method |
|---|---|---|
| `find_process_by_name()` | psutil → /proc | psutil → tasklist |
| `is_process_running(pid)` | psutil → `os.kill(pid, 0)` | psutil → PID exists |
| `kill_process(pid)` | psutil → `os.kill(pid, SIGTERM/KILL)` | psutil → process kill |
| `wait_for_port(port)` | TCP connect (cross-platform) | TCP connect |

**Fallback chain:**
1. `psutil` (preferred on both platforms — rich process info)
2. Linux: `/proc` filesystem parsing (when psutil unavailable)
3. Windows: `tasklist` / `taskkill` subprocess (when psutil unavailable)

**Usage:**
```python
from eigencapital.platform.process import find_process_by_name, kill_process

processes = find_process_by_name("terminal64")
for proc in processes:
    kill_process(proc.pid, force=True)
```

---

### 5. `mt5_strategies.py` — MT5 Launch Strategies

**File:** `eigencapital/platform/mt5_strategies.py`  
**Tests:** `tests/test_platform_mt5_strategies.py`

Strategy pattern for MT5 terminal and bridge lifecycle. Three implementations:

| Strategy | Platform | Terminal | Bridge | Dependencies |
|---|---|---|---|---|
| `WineMT5Strategy` | Linux + Wine | `wine terminal64.exe` (+ xvfb-run) | `wine python mt5_bridge.py` | Wine, xvfb-run, WINEPREFIX |
| `NativeWindowsMT5Strategy` | Windows native | `terminal64.exe` (direct) | `python mt5_bridge.py` | MT5 installed |
| `NoopMT5Strategy` | Unsupported | No-op (logs warning) | No-op (logs warning) | None |

**Environment auto-detection:**
```python
from eigencapital.platform.mt5_strategies import get_strategy

strategy = get_strategy()
if strategy.is_available:
    strategy.launch_terminal(terminal_path)
    strategy.launch_bridge(bridge_script)
```

**`MT5Environment` dataclass** describes the full environment for each platform:
- `terminal_exe`: Path to terminal64.exe
- `bridge_script`: Path to mt5_bridge.py
- `python_exe`: `"wine python"` on Linux, `sys.executable` on Windows
- `wine_prefix`: WINEPREFIX path (Linux only)
- `use_xvfb`: Whether to wrap commands with `xvfb-run`

**Terminal path discovery:**
- Linux+Wine: `{WINEPREFIX}/drive_c/Program Files/MetaTrader 5/terminal64.exe`
- Windows: `C:/Program Files/MetaTrader 5/terminal64.exe` (or `MT5_PATH` env var, or `PROGRAMFILES`/`PROGRAMW6432`)
- Fallback: Returns `None` (logged warning)

---

### 6. `mt5_bridge_manager.py` — Bridge Lifecycle Manager

**File:** `eigencapital/platform/mt5_bridge_manager.py`  
**Tests:** `tests/test_platform_mt5_bridge_manager.py`

Orchestrates the full MT5 bridge lifecycle using the strategy and detector modules.

**`BridgeManagerConfig`:**

| Field | Default | Description |
|---|---|---|
| `bridge_host` | `127.0.0.1` | Bridge TCP host |
| `bridge_port` | `9879` | Bridge TCP port |
| `health_port` | `9880` | Health check port |
| `heartbeat_interval` | `15.0s` | Heartbeat check interval |
| `watchdog_interval` | `30.0s` | Background watchdog interval |
| `max_restarts` | `10` | Max consecutive restart attempts |
| `terminal_timeout` | `30.0s` | Timeout for terminal initialisation |
| `bridge_timeout` | `30.0s` | Timeout for bridge initialisation |
| `auto_start_terminal` | `True` | Auto-launch terminal on start |
| `auto_start_bridge` | `True` | Auto-launch bridge on start |

**Lifecycle:**

```
start()
  ├── detect_terminal() ──→ terminal found? → launch_terminal()
  └── launch_bridge() ──→ wait_for_port() ──→ bridge ready

ensure_running()
  ├── check_bridge_heartbeat() ──→ alive? → OK
  └── dead? → restart bridge (up to max_restarts)

start_watchdog()
  └── background thread → heartbeat every 30s → restart on 2 consecutive failures

stop()
  ├── stop_bridge() → SIGTERM → SIGKILL fallback
  └── stop_terminal() → SIGTERM → SIGKILL fallback
```

**Usage:**
```python
from eigencapital.platform.mt5_bridge_manager import MT5BridgeManager

mgr = MT5BridgeManager()
mgr.start()
mgr.start_watchdog()

# Bridge runs in background
mgr.ensure_running()  # Check + restart if needed
mgr.is_healthy()      # Quick health check

mgr.stop()
```

---

## Deployment Matrix

| Aspect | Linux + Wine | Windows Native | Windows VPS |
|---|---|---|---|
| **Python** | Native Linux Python | Native Windows Python | Native Windows Python |
| **MT5** | Via Wine (terminal64.exe) | Native installation | Native installation |
| **Bridge** | `wine python mt5_bridge.py` | `python mt5_bridge.py` | `python mt5_bridge.py` |
| **Display** | xvfb-run (headless) | GUI or headless | GUI or headless |
| **Path separators** | `/` (pathlib handles cross-platform) | `\` (pathlib handles cross-platform) | `\` (pathlib handles cross-platform) |
| **Process management** | psutil → /proc/tasklist | psutil → tasklist | psutil → tasklist |
| **Shutdown signals** | SIGTERM + SIGINT | SIGINT only (programmatic trigger fallback) | SIGINT only (programmatic trigger fallback) |
| **Service supervision** | systemd service | Windows Service / Scheduled Task | Windows Service / Scheduled Task |
| **Startup** | `systemctl start eigencapital` | `Start-Service EigenCapital` | Scheduled task on login |
| **Logging** | `data/live/engine.log` | Same path | Same path |
| **State persistence** | SQLite (`data/live/state.db`) | Same | Same |

---

## Testing

```bash
# Run all platform tests
python -m pytest tests/test_platform_* -v

# Individual modules
python -m pytest tests/test_platform_detector.py -v
python -m pytest tests/test_platform_paths.py -v
python -m pytest tests/test_platform_process.py -v
python -m pytest tests/test_platform_signals.py -v
python -m pytest tests/test_platform_mt5_strategies.py -v
python -m pytest tests/test_platform_mt5_bridge_manager.py -v

# Check platform detection
python -c "from eigencapital.platform import detect; d = detect(); print(d)"
```

---

## Pre-commit Guard

`tools/check_import_os.py` scans all production Python files for `os.*` calls (excluding `os.path`, `os.environ`, `os.sep`, `os.linesep`, `os.name`) that lack a corresponding `import os` statement. This prevents regressions where `import os` is accidentally stripped during refactoring but `os.fsync()`, `os.replace()`, or other calls remain.

```bash
python tools/check_import_os.py
```

Installed as a pre-commit hook in `.pre-commit-config.yaml` — runs automatically on every commit.

---

## Path Migration Status

All `os.path.join()` and `os.path.dirname()` chains have been replaced with `pathlib.Path` throughout the codebase:

| Directory | Files Scanned | os.path.join Converted | Status |
|---|---|---|---|
| `paper_trading/` | ~120 | All | ✅ |
| `scripts/` | ~80 | All | ✅ |
| `eigencapital/` | ~30 | N/A (pathlib from creation) | ✅ |
| `features/` | ~19 | All | ✅ |
| `labels/` | ~6 | All | ✅ |
| `shared/` | ~29 | All | ✅ |
| `backtests/` | ~10 | All | ✅ |
| `monitoring/` | ~7 | All | ✅ |
| `configs/` | ~7 | N/A (YAML only) | ✅ |
| `tools/` | ~18 | All | ✅ |
| **Total** | **~313** | **All** | **✅ Clean** |

---

## Future Broker Architecture

The platform layer was designed with future broker integrations in mind:

1. **New broker strategies** follow the same pattern as MT5: a `{Broker}LaunchStrategy` abstracted behind the interface.
2. **The bridge manager** is broker-agnostic — the `MT5BridgeManager` can be generalised to a `BrokerBridgeManager` by parameterising the strategy.
3. **Path resolution** is already broker-agnostic (data dirs, log dirs, model dirs).
4. **Process management** and **signal handling** are broker-agnostic.

To add a new broker (e.g. cTrader):

1. Create `eigencapital/platform/ctrader_strategies.py` with the strategy implementation
2. Add to `eigencapital/platform/__init__.py` exports
3. Wire into the bridge manager or create a dedicated manager
4. No changes needed in `detector`, `paths`, `signals`, or `process`

---

**Last updated:** 2026-07-19
