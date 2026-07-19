# ADR-028: Cross-Platform Architecture — Centralized Platform Abstraction

**Status:** Accepted  
**Date:** 2026-07-19  
**Supersedes:** None (new architecture)

## Context

The trading engine was originally developed and deployed on **Linux + Wine** for MT5. The codebase had accumulated platform-specific assumptions:

1. **Hardcoded paths** — `/` separators, `/proc` filesystem reliance, Linux-specific directory layouts
2. **Signal handling** — `SIGTERM`/`SIGINT` usage that crashes on Windows (where SIGTERM cannot be caught)
3. **Process management** — `pgrep`/`pkill`, `/proc` scanning, Linux-only process discovery
4. **MT5 integration** — Hardcoded Wine prefix paths, Wine-only launch commands, no native Windows support
5. **`os.path.join` → `pathlib.Path`** — 310+ files used `os.path.join` with mixed path styles; `os.path.join` is cross-platform but `pathlib.Path` is the project convention
6. **Scattered `sys.platform` / `os.name` checks** — Platform detection was ad-hoc and duplicated across modules

Production deployment targets include Linux servers, native Windows desktops, Windows VPS, and future cloud/container environments. A single codebase must behave identically across all targets.

## Decision

Create a centralized **Cross-Platform Abstraction Layer** at `eigencapital/platform/` that encapsulates all platform-specific logic behind well-defined interfaces. The rest of the codebase must never reference `sys.platform`, `os.name`, or hardcoded platform paths directly.

### Architecture

```
eigencapital/platform/
├── __init__.py             # Public re-exports
├── detector.py             # OS / Wine / deployment mode detection
├── paths.py                # Platform-independent path resolution
├── process.py              # Process discovery, termination, health
├── signals.py              # Cross-platform graceful shutdown
├── mt5_strategies.py       # Strategy pattern for MT5 launch
└── mt5_bridge_manager.py   # MT5 terminal + bridge lifecycle
```

### Component Details

#### 1. Platform Detector (`detector.py`)

- **Singleton** via `PlatformDetector.detect()` — cached after first call
- Detects: Linux, Windows, macOS, Unknown (via `sys.platform`)
- Wine detection: `wine --version` subprocess + `WINEPREFIX` env var + `MetaTrader5` import check
- Deployment mode: `EIGENCAPITAL_DEPLOYMENT` env var (production/container/development), Kubernetes/Docker heuristics, `.git` directory fallback
- Published through `detect()` shortcut function: `from eigencapital.platform import detect`

#### 2. Path Resolution (`paths.py`)

- `resolve_project_root()` — walks up from `__file__` to find `paper_trading/` + `configs/` markers (same heuristic as legacy code)
- `resolve_data_dir()`, `resolve_log_dir()`, `resolve_config_dir()`, `resolve_model_dir()`, `resolve_backup_dir()`, `resolve_cache_dir()` — all return `pathlib.Path`
- `PathResolver` class — stateful resolver for tests and multi-instance scenarios
- All uses replaced throughout codebase: 310+ files converted from `os.path.join` to `pathlib.Path /`

#### 3. Process Management (`process.py`)

- `find_process_by_name()` — uses psutil if available; falls back to `/proc` (Linux) or `tasklist` (Windows)
- `is_process_running()` — psutil → `os.kill(pid, 0)`
- `kill_process()` — psutil → `os.kill` with SIGTERM/SIGKILL
- `wait_for_port()` — TCP socket check (platform-agnostic)
- Dataclass `ProcessInfo` for consistent return type

#### 4. Signal Handling (`signals.py`)

- `ShutdownManager` — wraps `threading.Event` for cooperative shutdown (works identically on all platforms)
- `install_graceful_shutdown()` — installs SIGINT/SIGTERM handlers; on Windows, SIGTERM handler registration is safely ignored (raises `ValueError` which is caught)
- `register_shutdown_handler()` — safe to call before `install_graceful_shutdown()` (handlers are queued)
- Context manager support via `__enter__`/`__exit__`

#### 5. MT5 Launch Strategies (`mt5_strategies.py`)

- **Strategy pattern** with `MT5LaunchStrategy` ABC
- `NoopMT5Strategy` — for Linux without Wine (all methods return None/False)
- `WineMT5Strategy` — Wine + `xvfb-run` for headless MT5 on Linux
- `NativeWindowsMT5Strategy` — native Windows MT5 + native Python bridge
- `get_strategy()` — factory function using detector output
- `MT5Environment` dataclass — describes platform-specific environment (terminal path, bridge script, env vars)

#### 6. MT5 Bridge Manager (`mt5_bridge_manager.py`)

- Combines strategy + detector into a unified lifecycle manager
- `start()` → detect terminal, launch terminal, launch bridge, wait for port
- `stop()` → graceful shutdown (bridge first, then terminal)
- `ensure_running()` — heartbeat health check + automatic restart with exponential backoff
- `start_watchdog()` — background thread monitoring bridge health
- Context manager support

### Conversion: `os.path.join` → `pathlib.Path`

All 310+ Python files across `paper_trading/`, `scripts/`, `features/`, `labels/`, `shared/`, `tools/`, `data/`, `configs/`, `backtests/`, `monitoring/` were mechanically converted from `os.path.join` to `pathlib.Path /`. An automated conversion script handled the bulk (~290 files), with manual fixes for edge cases:

- `str(path) + ".tmp"` for atomic writes (6 files)
- `str(path).replace()` instead of `Path.replace()` which renames files (2 files)
- Restored `import os` in files still using `os.fsync()`, `os.replace()`, etc. (4 files)
- Path objects in test patches instead of `str()` wrappers (1 file)

A pre-commit hook (`tools/check_import_os.py`) catches files that use `os.*` calls without `import os`, preventing future regressions.

## Consequences

### Positive

- **Single codebase** works on Linux, native Windows, and Windows VPS without platform-specific branches
- **Centralized detection** — any new platform check goes in one place, not scattered across 20+ files
- **Strategy pattern for MT5** — adding a new platform (e.g., native Linux MT5 if available) requires only a new strategy class
- **Cross-platform CI** — platform tests run on GitHub Actions for both Ubuntu and Windows
- **Graceful degradation** — `NoopMT5Strategy` allows the engine to run (paper-only) on platforms where MT5 is unavailable
- **Pre-commit guard** — `check_import_os.py` prevents pathlib conversion regressions

### Negative

- **New module dependency** — all MT5-related code must now import from `eigencapital.platform` rather than using `sys.platform` directly
- **Conversion risk** — the mechanical `os.path.join` → `pathlib.Path` conversion touched 310+ files; edge cases in test patches or type-unsafe `str() + Path` concatenation could cause runtime errors in untested paths
- **Wine detection heuristic** — auto-detection via `import MetaTrader5` may produce false positives on Linux machines with the package installed but no Wine

### Risks

- **Windows VPS headless operation** — NativeWindowsMT5Strategy assumes a desktop environment; headless Windows Server may require additional configuration (e.g., `CREATE_NO_WINDOW` flag already handled)
- **psutil optional dependency** — fallback paths (`/proc`, `tasklist`) have less test coverage than the psutil path
- **Path resolution in containers** — `resolve_project_root()` relies on `__file__` parent traversals which may behave differently in containerized or frozen Python deployments (`PyInstaller`, `Nuitka`)

## Migration Path

Existing code should migrate in this order:

1. Replace `sys.platform` / `os.name` checks with `detect()` → property access
2. Replace ad-hoc process management with `find_process_by_name()` / `kill_process()`
3. Replace `signal.signal(SIGTERM, ...)` with `ShutdownManager` / `install_graceful_shutdown()`
4. Replace MT5 launch logic with strategy pattern via `get_strategy()` → `MT5BridgeManager`

No urgent migration is required — existing code that bypasses the abstraction still works. The abstraction layer is additive: it provides the correct path without breaking the old one.
