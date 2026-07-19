# EigenCapital — Scheduled Tasks via Crontab
>
> If systemd timers are unavailable or undesired, use the crontab entries below.
> For systemd timers (Linux), run: `make all-timers-install`
> For Windows Task Scheduler, see comments in the Makefile targets.

## Weekly retrain (Sundays 03:00 UTC)

```cron
# EigenCapital weekly model retrain (Sundays 03:00 UTC)
# Logs to data/logs/retrain/retrain_cron_YYYYMMDD.log
CRON_TZ=UTC
0 3 * * 0 cd /home/manuelhorveydaniel/Projects/EigenCapital && PYTHONPATH=$PYTHONPATH:. python scripts/eigencapital/retrain.py >> data/logs/retrain/retrain_cron_$(date +\%Y\%m\%d).log 2>&1
```

## Daily health check + auto-trigger (04:00 UTC)

```cron
# EigenCapital daily model health check (04:00 UTC)
# Auto-triggers retrain if any asset exceeds urgency threshold
CRON_TZ=UTC
0 4 * * * cd /home/manuelhorveydaniel/Projects/EigenCapital && PYTHONPATH=. python scripts/ops/model_health_monitor.py --trigger --output data/logs/healthcheck/latest.json >> data/logs/healthcheck/healthcheck_cron_$(date +\%Y\%m\%d).log 2>&1
```

## Monthly retrain (1st of month 03:00 UTC)

```cron
CRON_TZ=UTC
0 3 1 * * cd /home/manuelhorveydaniel/Projects/EigenCapital && PYTHONPATH=$PYTHONPATH:. python scripts/eigencapital/retrain.py >> data/logs/retrain/retrain_cron_$(date +\%Y\%m\%d).log 2>&1
```

## Quick manual run

```bash
cd /home/manuelhorveydaniel/Projects/EigenCapital
PYTHONPATH=$PYTHONPATH:. python scripts/eigencapital/retrain.py   # full pipeline (cross-platform)
PYTHONPATH=$PYTHONPATH:. python scripts/eigencapital/retrain.py --dry-run  # dry run
make retrain                                     # full pipeline
make retrain-fast                                # retrain only (skip validation)
make health-check                                # manual health check
make health-check-trigger                        # check + trigger retrain
```

## Set up Slack alerting

Create or edit `.env` in the project root:

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00/B00/xxxxxxxx
```

### Daily SQLite backup (05:00 UTC)

```cron
# EigenCapital daily SQLite backup (05:00 UTC)
# Retains 30 days of backups; logs to data/logs/backup/backup_cron_YYYYMMDD.log
CRON_TZ=UTC
0 5 * * * cd /home/manuelhorveydaniel/Projects/EigenCapital && mkdir -p data/logs/backup && PYTHONPATH=$PYTHONPATH:. python scripts/ops/backup_sqlite.py >> data/logs/backup/backup_cron_$(date +\%Y\%m\%d).log 2>&1
```

## Quick manual run

```bash
cd /home/manuelhorveydaniel/Projects/EigenCapital
PYTHONPATH=$PYTHONPATH:. python scripts/ops/backup_sqlite.py              # daily backup
PYTHONPATH=$PYTHONPATH:. python scripts/ops/backup_sqlite.py --verify     # verify latest backup
PYTHONPATH=$PYTHONPATH:. python scripts/ops/backup_sqlite.py --retention 60  # keep 60 days
```

# Timer schedule summary

| Timer | Schedule | Purpose |
|-------|----------|---------|
| `eigencapital-retrain.timer` | Sun 03:00 UTC | Weekly model retrain |
| `eigencapital-healthcheck.timer` | Daily 04:00 UTC | Daily health check + auto-retrain trigger |
| `eigencapital-backup.timer` | Daily 05:00 UTC | Daily SQLite database backup |

Systemd timers are staggered (retrain on Sunday, health check daily 1h after retrain on Sundays,
backup 1h after health check at 05:00 UTC) to avoid overlapping pipeline runs. The health check
timer has a 30min `OnBootSec` fallback; the retrain timer has a 1h `OnBootSec` fallback; the
backup timer has a 2h `OnBootSec` fallback.
