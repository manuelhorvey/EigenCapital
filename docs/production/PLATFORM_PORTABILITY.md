# Platform Portability

This document clarifies the actual platform support status.

Last updated: 2026-08-26

## Current Status

| Platform | Status | Evidence |
|---|---|---|
| Linux (Ubuntu/Debian) | 🟢 PRODUCTION | Live running since Aug 2026 |
| Windows | 🟡 ARCHITECTURALLY SUPPORTED | Code supports it, no conformance test |
| macOS | 🔴 NOT TESTED | No evidence |

## Architecture Layers

### Platform-Agnostic (Works Everywhere)

| Component | Location | Notes |
|---|---|---|
| Core domain models | `src/eigencapital/core/` | Pure Python, no OS deps |
| Risk enforcement | `src/eigencapital/live/risk_enforcement.py` | Pure computation |
| Watchdog | `src/eigencapital/live/watchdog.py` | Pure computation |
| Position attribution | `src/eigencapital/live/position_attribution.py` | Pure computation |
| Catastrophic protection | `src/eigencapital/live/catastrophic_protection.py` | Pure computation |
| Fingerprint verifier | `src/eigencapital/production_qual/fingerprint_verifier.py` | Pure computation |
| Config loader | `src/eigencapital/config.py` | TOML parsing |
| Signal computation | `scripts/r4_rebalance_loop.py` | NumPy/Pandas |

### Platform-Specific (Requires MT5)

| Component | Linux | Windows | Notes |
|---|---|---|---|
| MT5 connection | mt5linux (Rpyc) | MetaTrader5 (native) | Different packages |
| Process supervision | PID files | PID files | Same implementation |
| File paths | `/` separators | `\` separators | Use `pathlib` |
| Signals | SIGTERM available | SIGBREAK instead | Handled in code |
| Nohup | `nohup` command | Not available | Use `start /B` |

## MT5 Integration

### Linux (Current Production)

```python
# Uses mt5linux bridge (Rpyc proxy)
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host="127.0.0.1", port=8001)
mt5.initialize()
```

Requirements:
- MT5 terminal running on Windows (or Wine)
- mt5linux bridge listening on port 8001
- Rpyc connection

### Windows (Architecturally Supported)

```python
# Uses native MetaTrader5 package
import MetaTrader5 as mt5
mt5.initialize()
```

Requirements:
- MT5 terminal installed natively
- MetaTrader5 Python package
- No bridge needed

## Key Differences

| Aspect | Linux | Windows |
|---|---|---|
| MT5 package | `mt5linux` | `MetaTrader5` |
| Connection | Rpyc proxy | Direct |
| Terminal | Wine or remote | Native |
| Performance | Slight Rpyc overhead | Direct calls |
| Reliability | Bridge can stale | Direct connection |
| Tested | ✅ Production | ❌ No conformance |

## What Would Be Needed for Windows Certification

1. Conformance test suite running on Windows
2. MT5 native connection verified
3. All 2,301 tests passing
4. Live trading test (even small)
5. Process supervision verified
6. Emergency flatten tested
7. Disconnect/reconnect tested

## Deployment Differences

### Linux

```bash
# Install
pip install -e ".[research]"

# Run
python scripts/r4_rebalance_loop.py --loop --interval 3600

# Background
nohup python -u scripts/r4_rebalance_loop.py --loop > loop.log 2>&1 &

# Stop
kill $(cat reports/r4_loop/supervisor.pid)
```

### Windows

```powershell
# Install
pip install -e ".[research]"

# Run
python scripts/r4_rebalance_loop.py --loop --interval 3600

# Background (PowerShell)
Start-Process python -ArgumentList "scripts/r4_rebalance_loop.py --loop" -NoNewWindow

# Background (cmd)
start /B python scripts/r4_rebalance_loop.py --loop

# Stop
taskkill /PID (Get-Content reports/r4_loop/supervisor.pid)
```

## Recommendation

**Use Linux for production.** The system is certified and running there.

Windows is architecturally supported but requires conformance testing before any production use. The mt5linux bridge adds complexity but also provides isolation — the native Windows connection is simpler but less tested in this codebase.
