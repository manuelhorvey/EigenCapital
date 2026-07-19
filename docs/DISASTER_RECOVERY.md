# EigenCapital — Disaster Recovery & Incident Response

**Last updated:** 2026-07-11

> Operational playbook for recovering from system failures, data corruption,
> and unexpected events. This document complements the daily runbook in
> [`docs/OPERATIONS.md`](OPERATIONS.md).

---

## Table of Contents

- [Incident Severity Levels](#incident-severity-levels)
- [Engine Crash Recovery](#engine-crash-recovery)
- [Data Corruption Recovery](#data-corruption-recovery)
- [MT5 Bridge Failure](#mt5-bridge-failure)
- [State File Corruption](#state-file-corruption)
- [Model File Corruption](#model-file-corruption)
- [Yahoo Finance API Downtime](#yahoo-finance-api-downtime)
- [Configuration Corruption](#configuration-corruption)
- [Incident Report Template](#incident-report-template)

---

## Incident Severity Levels

| Level | Label | Definition | Response Time |
|-------|-------|------------|---------------|
| **SEV-1** | Critical | Engine won't start, complete data loss, persistent circuit breaker loop | Immediate |
| **SEV-2** | High | Partial functionality loss (MT5 bridge down, some assets halted) | 4 hours |
| **SEV-3** | Medium | Degraded dashboard, stale data, single asset issues | 24 hours |
| **SEV-4** | Low | Cosmetic issues, documentation errors | Next sprint |

---

## Engine Crash Recovery

### Symptoms
- Dashboard returns `502` or connection refused
- `ps aux | grep monitor.py` shows no process
- Log output stops

### Recovery Steps

```bash
# 1. Check what happened
tail -100 data/live/state.json  # Last persisted state
journalctl -u eigencapital-* -n 50  # If running as systemd service (Linux only)

# 2. Verify state integrity
python -c "
import json
with open('data/live/state.json') as f:
    s = json.load(f)
print('Last sequence_id:', s.get('sequence_id'))
print('Emergency halt:', s.get('emergency_halt'))
print('Portfolio value:', s.get('portfolio', {}).get('total_value'))
"

# 3. Clear stale emergency halt if needed
PYTHONPATH=$PYTHONPATH:. python tools/reset_halt.py

# 4. Restart the engine
./monitor_all

# 5. Verify recovery
curl -s http://127.0.0.1:5000/ping | python3 -m json.tool
```

### Automatic Recovery

The engine auto-recovers from the following conditions on restart:
- **Stale emergency halt**: Cleared when equity ≥ 99% of peak and reason is DRAWDOWN or CONSECUTIVE_LOSSES (see `paper_trading/orchestrator/engine.py`)
- **Peak value re-anchor**: `_peak_portfolio_value` is re-anchored at init if lower than current equity
- **Schema migration**: SQLite auto-migrates at connect time (`DB_SCHEMA_VERSION = "2.0.0"`)

### Post-Crash Checklist

1. ✅ Engine started and `/ping` returns `{"status": "ok"}`
2. ✅ Dashboard loads at `http://127.0.0.1:5000`
3. ✅ All 22 assets show signals
4. ✅ No RED halt states on any asset
5. ✅ Portfolio drawdown is within normal range
6. ✅ MT5 bridge (if enabled) reconnected
7. ✅ Narrative is confirmed or pending
8. ✅ No position concentration alerts
9. ✅ Log output shows `Engine cycle complete` for at least 2 cycles

---

## Data Corruption Recovery

### SQLite Database Corruption

**File:** `data/live/state.db`

**Symptoms:**
- `sqlite3.DatabaseError` in logs
- Dashboard shows zero trades or missing history
- Engine crashes on startup with database errors

**Recovery:**

```bash
# 1. Check database integrity
sqlite3 data/live/state.db "PRAGMA integrity_check;"

# 2. Attempt recovery
sqlite3 data/live/state.db ".clone data/live/state_recovered.db"
mv data/live/state.db data/live/state_corrupted.db
mv data/live/state_recovered.db data/live/state.db

# 3. If clone fails, dump and restore
sqlite3 data/live/state_corrupted.db ".mode insert" ".output /tmp/dump.sql" ".dump"
sqlite3 data/live/state.db < /tmp/dump.sql

# 4. Regenerate from WAL replay (if state.db is unrecoverable)
# The WAL at data/live/wal/engine.jsonl contains causal boundary events
# that can reconstruct trade history. See replay/runner.py for tooling.

# 5. Restart engine
./monitor_all
```

### Trade History Loss

If the trades table is empty but the engine is running, trade outcomes will be lost but the engine will continue generating new trades. Run `scripts/optimization/trade_outcome_repository.py` after recovery to rebuild outcome analytics from current state.

---

## MT5 Bridge Failure

### Symptoms
- `MT5_ERROR` or `MT5_BRIDGE_TIMEOUT` in logs
- Dashboard MT5 status shows **DISCONNECTED** or red status
- Paper trading continues normally (simulated fills)

### Recovery Steps

```bash
# 1. Check bridge health
curl http://127.0.0.1:9879/health

# 2. If bridge is down, restart it
# The BridgeSupervisor should auto-restart. Check systemd:
systemctl status eigencapital-mt5-bridge  # Linux only; on Windows check Task Manager or NSSM

# 3. Manual restart
cd /home/manuelhorveydaniel/Projects/EigenCapital
./scripts/ops/mt5_bridge_supervisor.py --restart

# 4. Verify MT5 terminal is running under Wine
wine --version
ps aux | grep mt5
```

### Escalation

| Problem | Action |
|---------|--------|
| Bridge doesn't restart | Check Wine prefix: `ls ~/.wine_mt5/drive_c/` |
| Wine crash | Restart terminal: `wine start /unix /path/to/terminal64.exe` |
| MT5 password changed | Update `.env` with new credentials |
| Port conflict | Check `fuser 9879/tcp` |

**No recovery action required for paper trading** — MT5 bridge failure does not affect paper trade execution. Paper trades continue to be simulated via `PaperBroker`.

---

## State File Corruption

**File:** `data/live/state.json`

**Symptoms:**
- Dashboard shows NaN or undefined values
- JSON parse errors in logs
- Missing fields in state.json

### Recovery

```bash
# 1. Check if state.json is valid JSON
python -c "
import json
with open('data/live/state.json') as f:
    s = json.load(f)
print('Valid JSON, keys:', list(s.keys()))
"

# 2. If corrupted, restore from backup (if any)
cp data/live/state.json.bak data/live/state.json

# 3. If no backup, restart the engine — it will generate a fresh state.json on next cycle
./monitor_all

# 4. Verify recovery
curl -s http://127.0.0.1:5000/state.json | python3 -c "
import json, sys
s = json.load(sys.stdin)
print('sequence_id:', s.get('sequence_id'))
print('Assets:', len(s.get('assets', {})))
"
```

---

## Model File Corruption

**Files:** `paper_trading/models/*.json`

**Symptoms:**
- `Cannot load model` error on startup
- Asset shows `ERROR` state in logs
- Missing hash sidecar files

### Recovery

If a single model file is corrupted:

```bash
# 1. Identify the corrupted model
python -c "
import json
import glob
for f in glob.glob('paper_trading/models/*.json'):
    try:
        json.load(open(f))
    except Exception as e:
        print(f'CORRUPT: {f} - {e}')
"

# 2. Retrain the specific asset
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py --assets <TICKER>

# 3. Or retrain everything
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py
```

If ALL models need regeneration (e.g., after config schema change):

```bash
# Full pipeline
PYTHONPATH=$PYTHONPATH:. python scripts/training/retrain_all_fixed.py
PYTHONPATH=$PYTHONPATH:. python scripts/backtest/walk_forward_backtest.py
PYTHONPATH=$PYTHONPATH:. python scripts/training/train_calibration.py
```

---

## Yahoo Finance API Downtime

### Symptoms
- `ERROR - No live data for <ticker>` in logs
- All assets show stale prices
- Dashboard shows prices >24h old

### Recovery

```bash
# 1. Verify yfinance status
python -c "
import yfinance as yf
try:
    d = yf.download('EURUSD=X', period='5d')
    print(f'yfinance OK: {len(d)} rows, last date: {d.index[-1]}')
except Exception as e:
    print(f'yfinance ERROR: {e}')
"

# 2. Check internet connectivity
ping -c 3 google.com
```

### Extended Outage (>1 trading day)

During extended yfinance downtime, the engine continues running but cannot generate new signals. Options:

1. **Wait for recovery** — yfinance is generally reliable; outages rarely exceed a few hours
2. **Switch to MT5-only** — if MT5 bridge is operational, it serves as a fallback data source
3. **Stop the engine** — if no data is available, the engine will generate flat signals for all assets

---

## Configuration Corruption

**Files:** `configs/domains/*.yaml`

### Recovery

```bash
# 1. Verify config schema
PYTHONPATH=$PYTHONPATH:. python tools/check_config_schema.py

# 2. Check for diff from registry mirror
PYTHONPATH=$PYTHONPATH:. python tools/config_mirror_legacy.py --check

# 3. Restore from git if needed
git checkout -- configs/domains/

# 4. Re-apply any local changes after restore
```

### Failed Config Migration

If a config migration (adding/removing an asset, changing parameters) causes the engine to fail on startup:

```bash
# 1. Revert config changes
git checkout -- configs/

# 2. Verify
PYTHONPATH=$PYTHONPATH:. python tools/check_config_schema.py

# 3. Restart engine
./monitor_all
```

---

## Incident Report Template

Use this template for documenting incidents:

```markdown
## Incident Report — YYYY-MM-DD

### Severity: SEV-{1|2|3|4}

### Summary
One-line description of what happened.

### Timeline
- HH:MM — First symptom detected
- HH:MM — Root cause identified
- HH:MM — Mitigation applied
- HH:MM — System restored

### Root Cause
Description of what caused the incident.

### Impact
- Trading disruption: {None | Partial | Full} for {N} minutes
- Data loss: {None | Partial | Full}
- Assets affected: {List}

### Resolution
Steps taken to resolve.

### Prevention
Changes to prevent recurrence:
- [ ] Automated check added
- [ ] Documentation updated
- [ ] Monitoring improved
- [ ] Code change (link to PR)

### Related Documents
- `docs/OPERATIONS.md`
- `docs/DISASTER_RECOVERY.md`
```

---

## Prevention Measures

| Measure | Frequency | Tool/Script |
|---------|-----------|-------------|
| Config schema validation | Every commit | `tools/check_config_schema.py` |
| Doc-drift consistency check | Every PR | `tools/doc_drift_check.py` |
| Model health check | Daily | `scripts/ops/model_health_monitor.py` |
| MT5 bridge supervision | Continuous | `BridgeSupervisor` (systemd / NSSM) |
| Engine liveness check | Every 5s | Dashboard `/health` endpoint |
| WAL fsync | Every cycle | `WalWriter.flush()` with `os.fsync` |
| Emergency halt auto-clear | On restart | `orchestrator/engine.py` |

---

## Related Documents

| Document | Contents |
|----------|----------|
| [`docs/OPERATIONS.md`](OPERATIONS.md) | Daily/weekly ops, halt responses, troubleshooting |
| [`docs/SECURITY.md`](SECURITY.md) | Security model, secret management, bridge security |
| [`docs/MONITORING.md`](MONITORING.md) | Prometheus metrics, ATLAS drift detector |
| [`docs/TESTING.md`](TESTING.md) | Chaos testing, determinism tests, circuit breaker tests |
| [`docs/FAQ.md`](FAQ.md) | Frequently asked questions and quick fixes |
| [`AGENTS.md`](../AGENTS.md) | Known issues, structural limitations |
