# EigenCapital — Production Operations Runbook

## Daily Operations

### Pre-Session Checklist
1. Verify MT5 terminal is running (Wine on Linux, native on Windows)
2. Check `reports/r4_loop/loop_health.json` — should show `"alive": true`
3. Check `reports/r4_loop/supervisor_state.json` — should show `"status": "running"`
4. Review recent alerts in `reports/r4_loop/monitor.jsonl`
5. Verify account balance matches expected

### Starting the System
```bash
# Dry-run first
python scripts/r4_rebalance_loop.py --dry-run

# Then live
python scripts/r4_rebalance_loop.py --loop --interval 3600
```

### Monitoring
```bash
# One-shot status check
python scripts/r4_monitor.py --status

# Continuous monitoring
python scripts/r4_monitor.py --loop --interval 60 --telegram
```

### Stopping the System
```bash
# Send SIGINT (Ctrl+C) — finishes current cycle
kill -INT <pid>

# Or SIGTERM for immediate shutdown
kill -TERM <pid>
```

## Emergency Procedures

### Emergency Flatten
```bash
python scripts/r4_rebalance_loop.py --flatten
```
Closes ALL open positions immediately. Idempotent.

### Kill Switch
Set `kill_switch = true` in `configs/production/config.toml` under `[risk]`.

### After Crash
1. Check `reports/r4_loop/decisions.jsonl` for last action
2. Check `reports/r4_loop/daily_baseline.json` for loss tracking
3. Check broker state directly via MT5
4. Reconcile: verify positions match expected state
5. Restart: `python scripts/r4_rebalance_loop.py --loop --interval 3600`

## Fingerprint Verification

The system verifies fingerprints at startup and every cycle. If verification fails:

1. Check `reports/r4_loop/decisions.jsonl` for the failure reason
2. Verify `configs/production/config.toml` hasn't been modified
3. Verify `src/eigencapital/fidelity/r4_manifest.py` is unchanged
4. If intentional change: update the fingerprint in config.toml
5. If unintentional: revert the change

## Daily Loss Tracking

The daily loss tracker:
- Resets at midnight UTC
- Persists baseline to `reports/r4_loop/daily_baseline.json`
- Survives process restart
- Breach at $250/day → BLOCKS all trading

If daily loss is breached:
1. Trading is automatically halted
2. Check `reports/r4_loop/decisions.jsonl` for breach details
3. Wait for next trading day (midnight UTC reset)
4. Or manually: `DailyLossTracker.force_reset(equity)`

## Log Locations

| Log | Location | Rotation |
|-----|----------|----------|
| Trading decisions | `reports/r4_loop/decisions.jsonl` | Manual |
| Monitor alerts | `reports/r4_loop/monitor.jsonl` | Manual |
| Telegram alerts | Via bot | N/A |
| Daily baseline | `reports/r4_loop/daily_baseline.json` | Daily auto |
| Health status | `reports/r4_loop/loop_health.json` | Per cycle |
| Supervisor state | `reports/r4_loop/supervisor_state.json` | Per cycle |

## Troubleshooting

| Symptom | Likely Cause | Action |
|---------|-------------|--------|
| "FINGERPRINT VERIFICATION FAILED" | Config modified | Revert change |
| "DAILY LOSS BREACHED" | Loss > $250 | Wait for midnight reset |
| "Cannot connect to MT5" | MT5 not running | Start MT5 terminal |
| "Another instance running" | Stale PID | Delete `reports/r4_loop/supervisor.pid` |
| Positions don't match | Manual trade or crash | Reconcile manually |
| No alerts | Telegram not configured | Set env vars |
