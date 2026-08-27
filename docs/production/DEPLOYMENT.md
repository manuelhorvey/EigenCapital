# EigenCapital — Deployment Guide

**Last Updated:** 2026-08-27  
**Supported Platforms:** Linux, macOS, Windows

---

## Prerequisites

- Python 3.11+ (tested on 3.11, 3.12, 3.13, 3.14)
- MetaTrader 5 terminal (Wine on Linux/macOS, native on Windows)
- Exness demo account (or configured broker)
- Minimum $5,000 equity for qualification

---

## Platform-Specific Setup

### Linux (Production)

```bash
# 1. Install Python dependencies
pip install -e ".[dev,research]"

# 2. Install MT5 under Wine
# (See docs/production/OPERATIONS_RUNBOOK.md for Wine setup)

# 3. Verify MT5 connection
python3 -c "
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
print('Connected:', mt5.initialize())
"

# 4. Start trading system
./scripts/start_trading.sh

# 5. Check status
./scripts/start_trading.sh --status
```

### macOS

```bash
# 1. Install Python dependencies
pip install -e ".[dev,research]"

# 2. Install MT5 under Wine (same as Linux)
# brew install wine
# (See docs/production/OPERATIONS_RUNBOOK.md for Wine setup)

# 3. Verify MT5 connection
python3 -c "
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
print('Connected:', mt5.initialize())
"

# 4. Start trading system
./scripts/start_trading.sh

# 5. Check status
./scripts/start_trading.sh --status
```

### Windows (Native MT5)

```powershell
# 1. Install Python dependencies
pip install -e ".[dev,research]"

# 2. Install MetaTrader5 package (official)
pip install MetaTrader5

# 3. Verify MT5 connection
python -c "
import MetaTrader5 as mt5
print('Connected:', mt5.initialize())
"

# 4. Start trading loop
python scripts/r4_rebalance_loop.py --loop --interval 3600

# 5. Start monitor (optional)
python scripts/r4_monitor.py --loop --interval 60
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EIGENCAPITAL_ENV` | `production` | Config profile to use |
| `MT5_HOST` | `127.0.0.1` | MT5 bridge host |
| `MT5_PORT` | `8001` | MT5 bridge port |
| `WINEPREFIX` | `~/.wine_mt5` | Wine prefix for MT5 (Linux/macOS) |

### Config Files

| File | Purpose |
|------|---------|
| `config/production.toml` | Production configuration |
| `config/development.toml` | Development configuration |
| `src/eigencapital/config.py` | Config loader (single source of truth) |

---

## Startup Scripts

### `start_trading.sh` (Linux/macOS)

```bash
./scripts/start_trading.sh              # start rebalance loop
./scripts/start_trading.sh --with-monitor  # rebalance + monitor
./scripts/start_trading.sh --dry-run     # dry-run mode
./scripts/start_trading.sh --status      # check health
./scripts/start_trading.sh --stop        # graceful shutdown
```

### `mt5-bridge` Helper

```bash
mt5-bridge              # start bridge (idempotent)
mt5-bridge --status     # check if bridge is alive
mt5-bridge --restart    # restart bridge
mt5-bridge --stop       # stop bridge
```

### Direct Python (Windows)

```bash
python scripts/r4_rebalance_loop.py --loop --interval 3600
python scripts/r4_monitor.py --loop --interval 60
```

---

## Health Checks

### Automated

- **Bridge health:** RPyC connection test every cycle
- **MT5 connectivity:** Account info probe every cycle
- **Fingerprint verification:** SHA-256 check at startup and every cycle
- **Risk gates:** 7 broker-authoritative checks every cycle

### Manual

```bash
# Check all components
./scripts/start_trading.sh --status

# Check bridge specifically
mt5-bridge --status

# Check rebalance loop logs
tail -50 reports/r4_loop/loop_stdout.log

# Check monitor logs
tail -50 reports/r4_loop/monitor_stdout.log
```

---

## Troubleshooting

### Bridge Won't Start

```bash
# Check if port is in use
ss -tlnp | grep 8001  # Linux
lsof -i :8001          # macOS

# Kill stale processes
pkill -f "server.py.*8001"

# Restart bridge
mt5-bridge --restart
```

### MT5 Connection Refused

```bash
# Check MT5 terminal is running
ps aux | grep terminal64  # Linux
ps aux | grep terminal64  # macOS
tasklist | findstr terminal64  # Windows

# Check Wine prefix (Linux/macOS)
export WINEPREFIX=$HOME/.wine_mt5
wine python -c "import MetaTrader5; print('OK')"
```

### Rebalance Loop Not Starting

```bash
# Check logs for errors
tail -100 reports/r4_loop/loop_stdout.log

# Run in dry-run mode to debug
python scripts/r4_rebalance_loop.py --dry-run
```

---

## Deployment Checklist

- [ ] Python 3.11+ installed
- [ ] MT5 terminal running (Wine or native)
- [ ] Bridge alive on port 8001
- [ ] Config fingerprint verified
- [ ] T=0 snapshot exists and matches
- [ ] Risk gates passing
- [ ] Audit log writable
- [ ] Evidence directory writable

---

*This document consolidates: DEPLOYMENT.md, DEPLOYMENT_LINUX.md, DEPLOYMENT_WINDOWS.md, DEPLOYMENT_REPRODUCIBILITY_REPORT.md*
