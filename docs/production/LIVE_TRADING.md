# Live Trading Operations

This document describes the actual live trading operational sequence.

Last updated: 2026-08-26

## System Components

| Component | Script | Purpose |
|---|---|---|
| Rebalance loop | `scripts/r4_rebalance_loop.py` | Hourly signal check + order execution |
| Monitor | `scripts/r4_monitor.py` | Continuous health monitoring |
| Safety supervisor | `scripts/r4_safety_supervisor.py` | Safety gate verification |
| Quarantined script | `scripts/r4_live_orders.py` | **QUARANTINED** — `--execute` disabled, cannot submit orders |
| Qualification monitor | `scripts/r4_qualification_monitor.py` | Hourly evidence collection |

## Startup Sequence

### Pre-flight (Manual)

```bash
# 1. Verify fingerprints
python -c "from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier; r=FingerprintVerifier().verify_all(); print('PASS' if r.all_verified else 'FAIL')"

# 2. Run supervisor dry-run
python scripts/r4_supervisor_dryrun.py

# 3. Run adversarial audit
python scripts/r4_adversarial_audit.py

# 4. Verify T=0 exists
ls reports/r4_qualification/T0_*.json
```

### Automated Startup (Loop)

Every cycle, the loop executes:

```
1. Connect to MT5
2. Load persisted state
3. Verify fingerprints (fail-closed)
4. Validate T=0 snapshot
5. Assert position count
6. Check watchdog state
7. Run risk gates
8. Fetch market data
9. Compute R4 signal
10. Check regime gate
11. Generate orders
12. Execute orders
13. Audit to JSONL
14. Persist state
15. Wait for next cycle
```

### Authorization Gate

No order is submitted without:

```
BUILD VERIFIED → T=0 VALIDATED → POSITION GATE → WATCHDOG NORMAL → RISK ENVELOPE → TRADING_AUTHORIZED
```

## Normal Operation

### Hourly Cycle

The rebalance loop runs every hour:

1. **Signal computation:** 12-1 month momentum, cross-sectional ranks, regime conditioning, vol scaling
2. **Portfolio comparison:** Current positions vs target weights
3. **Order generation:** Close positions no longer in top-19, open new positions that entered top-19
4. **Execution:** Ticket-scoped closes (hedging-safe), market orders for new entries
5. **Audit:** Every decision recorded to JSONL

### Monitoring

```bash
# Check loop health
tail -20 reports/r4_loop/loop.log

# Check decisions
tail -5 reports/r4_loop/decisions.jsonl | python -m json.tool

# Check positions
python -c "
import sys; sys.path.insert(0, 'src')
from mt5linux import MetaTrader5
mt5 = MetaTrader5(host='127.0.0.1', port=8001)
mt5.initialize()
for p in mt5.positions_get():
    print(f'{p.symbol} {p.type} {p.volume} @ {p.price_open} SL={p.sl} P&L={p.profit}')
mt5.shutdown()
"

# Run qualification snapshot
python scripts/r4_qualification_monitor.py
```

## Failure Handling

### Broker Disconnect

The loop detects stale MT5 sessions and auto-reconnects:

```
DISCONNECTED → reconnect → reconciliation → RESUMED
```

If reconciliation fails → HALTED (manual intervention required).

### Process Crash

State is persisted after each cycle. On restart:

1. Load persisted state
2. Reconcile with broker
3. Resume if clean, halt if not

### Fingerprint Mismatch

If config drifts from T=0:

```
FINGERPRINT FAILED → BLOCKED → no trading until resolved
```

### Risk Breach

| Breach | Action |
|---|---|
| Daily loss > $250 | Block all new entries |
| Drawdown > 10% | Block all new entries |
| Equity < $4,000 | Block all new entries |
| Foreign position detected | Block new entries, allow self-rotation |
| Position count > 19 | Force rotation |

### Emergency Flatten

```bash
# Close all R4 positions immediately
python scripts/r4_rebalance_loop.py --flatten
```

## Evidence Collection

### Hourly Evidence

The qualification monitor captures:

- Position details (entry, current, SL, MAE/MFE)
- Portfolio risk (loss-at-SL, correlation)
- Account state (equity, balance, free margin)

### Governance Artifacts

Preserved in git:

- `reports/r4_qualification/T0_*.json` — Campaign boundaries
- `reports/r4_qualification/supervisor_dryrun_*.json` — Gate verification
- `reports/r4_qualification/adversarial_audit_*.json` — Fault injection tests
- `reports/r4_qualification/attestation_*.json` — Ownership proof

### Runtime Artifacts (Gitignored)

- `reports/r4_loop/*.log` — Operational logs
- `reports/r4_loop/*.jsonl` — Decision audit trail
- `reports/r4_qualification/evidence/*.jsonl` — Position snapshots

## What NOT to Do

- **Do not manually place orders** during normal operation
- **Do not modify strategy parameters** during qualification
- **Do not force regime** unless explicitly instructed
- **Do not change risk limits** without governance approval
- **Do not skip pre-flight checks** before starting the loop
- **Do not run multiple loop instances** (supervisor prevents this)

## Configuration

Single source of truth: `configs/production/config.toml`

| Parameter | Value | Location |
|---|---|---|
| MAX_CONCURRENT | 19 | `[capital].max_concurrent_positions` |
| MAX_POSITION_USD | $5,000 | `[capital].max_position_size` |
| MAX_EQUITY | $5,100 | `[capital].max_equity` |
| MAX_DAILY_LOSS | $250 | `[capital].max_daily_loss` |
| MIN_EQUITY | $4,000 | `[live_risk].min_equity` |
| MAX_DD | 10% | `[live_risk].max_account_drawdown_pct` |
| MAGIC | 20260825 | Hardcoded in order requests |
