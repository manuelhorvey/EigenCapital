# EigenCapital — Windows Deployment Guide

## Prerequisites

- Python 3.11+ (Windows native)
- MetaTrader 5 terminal installed (native Windows)
- MetaTrader5 Python package (official)
- Exness demo account (or configured broker)

## Setup

```powershell
# 1. Install Python dependencies
pip install -e ".[dev,research]"

# 2. Install MetaTrader5 package
pip install MetaTrader5

# 3. Verify MT5 connection
python -c "import MetaTrader5 as mt5; print(mt5.initialize())"

# 4. Run pre-funding gate
python scripts/evaluate_prefunding_gate.py

# 5. Run pre-trading validation
python scripts/evaluate_pre_trading.py

# 6. Capture T=0 snapshot
python scripts/capture_t0.py

# 7. Run in dry-run mode first
python scripts/r4_rebalance_loop.py --dry-run

# 8. Run in live mode
python scripts/r4_rebalance_loop.py --execute
```

## Process Supervision

### Option A: Manual (development)
```powershell
python scripts/r4_rebalance_loop.py --loop --interval 3600
```

### Option B: NSSM Windows Service
```powershell
# Download NSSM from https://nssm.cc/download

# Install as Windows service
nssm install EigenCapital "C:\Python314\python.exe" "scripts\r4_rebalance_loop.py --loop --interval 3600"
nssm set EigenCapital AppDirectory "C:\Users\manuelhorveydaniel\Projects\EigenCapital"
nssm set EigenCapital DisplayName "EigenCapital R4 Trading"
nssm set EigenCapital Start SERVICE_AUTO_START
nssm start EigenCapital
```

### Option C: Task Scheduler
```powershell
# Create a scheduled task that runs at startup
schtasks /create /tn "EigenCapital" /tr "python scripts\r4_rebalance_loop.py --loop --interval 3600" /sc onstart /ru SYSTEM
```

### Option D: Process supervision wrapper
```python
# scripts/supervise.py — restart on crash with backoff
import subprocess, time, sys
max_restarts = 10
restart_count = 0
while restart_count < max_restarts:
    result = subprocess.run([sys.executable, "scripts/r4_rebalance_loop.py", "--loop", "--interval", "3600"])
    restart_count += 1
    if result.returncode == 0:
        break  # Clean exit
    backoff = min(300, 2 ** restart_count)
    print(f"Restart {restart_count}/{max_restarts} in {backoff}s...")
    time.sleep(backoff)
```

## Monitoring

```powershell
# Check status
python scripts/r4_monitor.py --status

# Continuous monitoring
python scripts/r4_monitor.py --loop --interval 60
```

## Emergency Procedures

```powershell
# Emergency flatten all positions
python scripts/r4_rebalance_loop.py --flatten
```

## Platform Differences from Linux

| Feature | Linux | Windows |
|---------|-------|---------|
| MT5 provider | mt5linux (Wine) | MetaTrader5 (native) |
| Process supervision | systemd/screen | NSSM/Task Scheduler |
| Signal handling | SIGTERM/SIGINT | SIGINT only |
| File locking | flock | os.replace() (atomic) |
| Health checks | PID file | PID file |

## File Locations

Same as Linux deployment — all state files are in `reports/r4_loop/`.
