# Deployment Guide

This document describes how to deploy EigenCapital for live trading.

Last updated: 2026-08-26

## Prerequisites

- Python 3.11+
- MT5 terminal with bridge (Linux) or native (Windows)
- Exness demo account (or compatible broker)
- Minimum $5,000 equity for qualification

## Linux Deployment (Production)

### 1. Install

```bash
git clone <repo-url> && cd EigenCapital
pip install -e ".[research]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with broker credentials
```

Key config: `configs/production/config.toml`

### 3. Verify MT5 Connection

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
if mt5.initialize():
    acct = mt5.account_info()
    print(f'Connected: {acct.login} | Equity: {acct.equity}')
    mt5.shutdown()
else:
    print(f'Failed: {mt5.last_error()}')
"
```

### 4. Pre-flight Checks

```bash
# Fingerprint verification
python -c "from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier; print('PASS' if FingerprintVerifier().verify_all().all_verified else 'FAIL')"

# Supervisor dry-run
python scripts/r4_supervisor_dryrun.py

# Adversarial audit
python scripts/r4_adversarial_audit.py

# Generate T=0
python scripts/r4_generate_t0.py

# Generate attestation
python scripts/r4_attestation.py
```

### 5. Start Live Loop

```bash
# Foreground (for testing)
python scripts/r4_rebalance_loop.py --loop --interval 3600

# Background (production)
nohup python -u scripts/r4_rebalance_loop.py --loop --interval 3600 > reports/r4_loop/loop.log 2>&1 &
echo $! > reports/r4_loop/loop.pid
```

### 6. Start Monitor

```bash
nohup python -u scripts/r4_monitor.py --loop --interval 60 > reports/r4_loop/monitor.log 2>&1 &
```

### 7. Verify Running

```bash
# Check processes
ps aux | grep r4_rebalance_loop | grep -v grep
ps aux | grep r4_monitor | grep -v grep

# Check logs
tail -20 reports/r4_loop/loop.log
```

## Windows Deployment (Not Certified)

### 1. Install

```powershell
git clone <repo-url> && cd EigenCapital
pip install -e ".[research]"
```

### 2. Configure

```powershell
copy .env.example .env
# Edit .env with broker credentials
```

### 3. Verify MT5 Connection

```python
import MetaTrader5 as mt5
if mt5.initialize():
    acct = mt5.account_info()
    print(f'Connected: {acct.login} | Equity: {acct.equity}')
    mt5.shutdown()
else:
    print(f'Failed: {mt5.last_error()}')
```

### 4. Start Services

```powershell
# Start loop
python scripts/r4_rebalance_loop.py --loop --interval 3600

# Or background
Start-Process python -ArgumentList "scripts/r4_rebalance_loop.py --loop" -NoNewWindow
```

## Emergency Procedures

### Flatten All Positions

```bash
python scripts/r4_rebalance_loop.py --flatten
```

### Stop Loop

```bash
# Find PID
cat reports/r4_loop/loop.pid

# Stop
kill $(cat reports/r4_loop/loop.pid)

# Or find and kill
ps aux | grep r4_rebalance_loop | grep -v grep | awk '{print $2}' | xargs kill
```

### Force Reconnect

If the loop has a stale MT5 connection, kill and restart:

```bash
kill $(cat reports/r4_loop/loop.pid 2>/dev/null) 2>/dev/null
sleep 2
nohup python -u scripts/r4_rebalance_loop.py --loop --interval 3600 > reports/r4_loop/loop.log 2>&1 &
```

## Service Management

### Systemd (Linux)

Create `/etc/systemd/system/eigencapital.service`:

```ini
[Unit]
Description=EigenCapital R4 Rebalance Loop
After=network.target

[Service]
Type=simple
User=manuelhorveydaniel
WorkingDirectory=/home/manuelhorveydaniel/Projects/EigenCapital
ExecStart=/usr/bin/python3 scripts/r4_rebalance_loop.py --loop --interval 3600
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable eigencapital
sudo systemctl start eigencapital
sudo systemctl status eigencapital
sudo journalctl -u eigencapital -f
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `EIGENCAPITAL_ENV` | No | `production` | Config environment |
| `PYTHONPATH` | Yes | — | Must include `src` |

## Logs

| Log | Location | Rotation |
|---|---|---|
| Loop log | `reports/r4_loop/loop.log` | Manual |
| Monitor log | `reports/r4_loop/monitor.log` | Manual |
| Decisions | `reports/r4_loop/decisions.jsonl` | Manual |
| Evidence | `reports/r4_qualification/evidence/` | Rolling 30 days |

## Backup

Before any manual intervention:

```bash
# Backup current state
cp reports/r4_loop/runtime_state.json reports/r4_loop/runtime_state.json.bak
cp reports/r4_loop/decisions.jsonl reports/r4_loop/decisions.jsonl.bak
```
