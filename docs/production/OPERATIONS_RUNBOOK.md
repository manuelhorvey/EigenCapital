# Operations Runbook

This document covers operational procedures for EigenCapital live trading.

Last updated: 2026-08-26

## Quick Reference

| Action | Command |
|---|---|
| Check status | `ps aux \| grep r4_rebalance_loop` |
| View logs | `tail -30 reports/r4_loop/loop.log` |
| Stop loop | `kill $(cat reports/r4_loop/loop.pid)` |
| Restart loop | See below |
| Emergency flatten | `python scripts/r4_rebalance_loop.py --flatten` |
| Supervisor check | `python scripts/r4_supervisor_dryrun.py` |

## Daily Checks

### Morning (Market Open)

```bash
# 1. Check loop is running
ps aux | grep r4_rebalance_loop | grep -v grep

# 2. Check last cycle succeeded
tail -10 reports/r4_loop/loop.log

# 3. Check positions
python scripts/r4_qualification_monitor.py

# 4. Check for overnight issues
grep -i "error\|fail\|halt\|block" reports/r4_loop/loop.log | tail -10
```

### Evening (Market Close)

```bash
# 1. Check daily P&L
python -c "
import sys; sys.path.insert(0, 'src')
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
mt5.initialize()
acct = mt5.account_info()
print(f'Balance: \${acct.balance:,.2f} | Equity: \${acct.equity:,.2f}')
mt5.shutdown()
"

# 2. Check risk gates
tail -5 reports/r4_loop/decisions.jsonl | python -m json.tool

# 3. Verify no foreign positions
python -c "
import sys; sys.path.insert(0, 'src')
from mt5linux import MetaTrader5
from eigencapital.live.position_attribution import classify_all
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
mt5.initialize()
positions = mt5.positions_get()
foreign = [p for p in positions if p.magic != 20260825]
print(f'Foreign positions: {len(foreign)}')
mt5.shutdown()
"
```

## Weekly Checks

```bash
# 1. Run full supervisor dry-run
python scripts/r4_supervisor_dryrun.py

# 2. Check evidence collection
wc -l reports/r4_qualification/evidence/position_evidence.jsonl

# 3. Review correlation analysis
python scripts/r4_qualification_monitor.py

# 4. Check for config drift
python -c "from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier; print(FingerprintVerifier().verify_all().to_dict())"
```

## Failure Procedures

### Broker Disconnect

**Symptoms:** Loop log shows "Stale MT5 session detected"

**Action:** Loop auto-reconnects. Monitor for:
- Successful reconnection in logs
- Position count unchanged
- No duplicate orders

If loop fails to reconnect:
```bash
kill $(cat reports/r4_loop/loop.pid 2>/dev/null)
sleep 5
nohup python -u scripts/r4_rebalance_loop.py --loop --interval 3600 > reports/r4_loop/loop.log 2>&1 &
```

### Process Crash

**Symptoms:** No loop process running

**Action:**
```bash
# Check why it crashed
tail -50 reports/r4_loop/loop.log

# Restart
nohup python -u scripts/r4_rebalance_loop.py --loop --interval 3600 > reports/r4_loop/loop.log 2>&1 &
```

The loop loads persisted state on startup and reconciles with broker.

### Fingerprint Mismatch

**Symptoms:** "FINGERPRINT VERIFICATION FAILED" in logs

**Action:**
```bash
# Check what drifted
python -c "from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier; r=FingerprintVerifier().verify_all(); [print(f'{c.component}: {c.message}') for c in r.checks if c.status != 'verified']"

# If config changed intentionally, regenerate T=0
python scripts/r4_generate_t0.py
```

### Risk Breach

**Symptoms:** "BLOCKED" or "CRITICAL" in logs

**Action:** Do NOT restart the loop to bypass. Investigate:
```bash
# Check which gate breached
grep -i "blocked\|critical" reports/r4_loop/loop.log | tail -5

# Check equity/drawdown
python -c "
import sys; sys.path.insert(0, 'src')
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
mt5.initialize()
acct = mt5.account_info()
print(f'Equity: \${acct.equity:,.2f} | Floor: \$4,000')
mt5.shutdown()
"
```

### Foreign Position Detected

**Symptoms:** "QUARANTINE" in logs

**Action:** The loop blocks new entries but allows self-rotation. To close foreign positions:
```bash
python -c "
import sys, time; sys.path.insert(0, 'src')
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
mt5.initialize()
for p in mt5.positions_get():
    if p.magic != 20260825:
        tick = mt5.symbol_info_tick(p.symbol)
        close_type = 1 if p.type == 0 else 0
        price = tick.bid if p.type == 0 else tick.ask
        req = {'action': 5, 'symbol': p.symbol, 'volume': p.volume,
               'type': close_type, 'position': p.ticket, 'price': price,
               'deviation': 20, 'magic': 20260825, 'comment': 'QUARANTINE-CLOSE'}
        r = mt5.order_send(req)
        print(f'Closed {p.symbol}: {r.retcode}')
        time.sleep(0.2)
mt5.shutdown()
"
```

### Duplicate Process

**Symptoms:** Two loop processes running

**Action:**
```bash
# Find all
ps aux | grep r4_rebalance_loop | grep -v grep

# Kill all except the newest
ps aux | grep r4_rebalance_loop | grep -v grep | sort -k2 -n | head -n -1 | awk '{print $2}' | xargs kill
```

## Emergency Procedures

### Emergency Flatten

Close ALL positions immediately:

```bash
python scripts/r4_rebalance_loop.py --flatten
```

### Account Freeze

If account is frozen by broker:
1. Do NOT restart the loop
2. Contact broker support
3. Document the incident
4. Wait for account restoration
5. Reconcile before resuming

## Monitoring Alerts

### Critical (Act Immediately)

- Equity < $4,000 (floor breach)
- Daily loss > $250
- Drawdown > 10%
- Foreign position detected
- Fingerprint mismatch
- Loop process dead

### Warning (Investigate)

- Watchdog state != NORMAL
- Position count approaching limit
- Spread > normal
- Fill rejection
- Reconciliation mismatch

### Informational (Log Only)

- Regime change
- Signal rotation
- New position opened
- Position closed
- Cycle completed

## Log Analysis

### Find Errors

```bash
grep -i "error\|fail\|exception" reports/r4_loop/loop.log
```

### Find Blocked Trades

```bash
grep -i "blocked\|critical" reports/r4_loop/loop.log
```

### Find Executions

```bash
grep "EXECUTED\|filled" reports/r4_loop/loop.log
```

### Find Risk Gate Results

```bash
cat reports/r4_loop/decisions.jsonl | python -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    if 'gates' in d:
        for g in d['gates']:
            print(f\"{g['gate_name']}: {g['result']}\")
"
```
