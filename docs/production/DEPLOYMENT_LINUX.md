# EigenCapital — Linux Deployment Guide

## Prerequisites

- Python 3.11+
- MT5 terminal running under Wine
- mt5linux Python package (RPyC bridge)
- Exness demo account (or configured broker)

## Setup

```bash
# 1. Install Python dependencies
pip install -e ".[dev,research]"

# 2. Verify MT5 connection
python -c "from mt5linux import MetaTrader5; mt5=MetaTrader5(host='127.0.0.1', port=8001); print(mt5.initialize())"

# 3. Run pre-funding gate
python scripts/evaluate_prefunding_gate.py

# 4. Run pre-trading validation
python scripts/evaluate_pre_trading.py

# 5. Capture T=0 snapshot
python scripts/capture_t0.py

# 6. Run in dry-run mode first
python scripts/r4_rebalance_loop.py --dry-run

# 7. Run in live mode
python scripts/r4_rebalance_loop.py --execute
```

## Process Supervision

### Option A: Manual (development)
```bash
python scripts/r4_rebalance_loop.py --loop --interval 3600
```

### Option B: systemd service
```ini
# /etc/systemd/system/eigencapital.service
[Unit]
Description=EigenCapital R4 Trading Loop
After=network.target

[Service]
Type=simple
User=manuelhorveydaniel
WorkingDirectory=/home/manuelhorveydaniel/Projects/EigenCapital
ExecStart=/usr/bin/python3 scripts/r4_rebalance_loop.py --loop --interval 3600
Restart=on-failure
RestartSec=60
StandardOutput=append:/var/log/eigencapital/trading.log
StandardError=append:/var/log/eigencapital/trading.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable eigencapital
sudo systemctl start eigencapital
```

### Option C: Screen/tmux (development)
```bash
screen -S eigencapital
python scripts/r4_rebalance_loop.py --loop --interval 3600
# Ctrl+A, D to detach
```

## Monitoring

```bash
# Check status
python scripts/r4_monitor.py --status

# Continuous monitoring
python scripts/r4_monitor.py --loop --interval 60

# With Telegram alerts
R4_TELEGRAM_BOT_TOKEN=xxx R4_TELEGRAM_CHAT_ID=yyy python scripts/r4_monitor.py --loop --telegram
```

## Emergency Procedures

```bash
# Emergency flatten all positions
python scripts/r4_rebalance_loop.py --flatten

# Check positions
python scripts/r4_monitor.py --status
```

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| Audit log | `reports/r4_loop/decisions.jsonl` | Every trading decision |
| Monitor log | `reports/r4_loop/monitor.jsonl` | Position/equity changes |
| Daily baseline | `reports/r4_loop/daily_baseline.json` | Daily loss tracking |
| Health status | `reports/r4_loop/loop_health.json` | Process health |
| Supervisor state | `reports/r4_loop/supervisor_state.json` | Process identity |
| PID file | `reports/r4_loop/supervisor.pid` | Duplicate prevention |
