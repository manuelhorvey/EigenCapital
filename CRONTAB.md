# EigenCapital — Scheduled Tasks via Crontab
>
> If systemd timers are unavailable or undesired, use the crontab entries below.
> For systemd timers, run: `make all-timers-install`

## Weekly retrain (Sundays 03:00 UTC)

```cron
# EigenCapital weekly model retrain (Sundays 03:00 UTC)
# Logs to data/logs/retrain/retrain_cron_YYYYMMDD.log
CRON_TZ=UTC
0 3 * * 0 cd /home/manuelhorveydaniel/Projects/Quorrin && ./scripts/ops/retrain_scheduler.sh >> data/logs/retrain/retrain_cron_$(date +\%Y\%m\%d).log 2>&1
```

## Daily health check + auto-trigger (04:00 UTC)

```cron
# EigenCapital daily model health check (04:00 UTC)
# Auto-triggers retrain if any asset exceeds urgency threshold
CRON_TZ=UTC
0 4 * * * cd /home/manuelhorveydaniel/Projects/Quorrin && PYTHONPATH=. python scripts/ops/model_health_monitor.py --trigger --output data/logs/healthcheck/latest.json >> data/logs/healthcheck/healthcheck_cron_$(date +\%Y\%m\%d).log 2>&1
```

## Monthly retrain (1st of month 03:00 UTC)

```cron
CRON_TZ=UTC
0 3 1 * * cd /home/manuelhorveydaniel/Projects/Quorrin && ./scripts/ops/retrain_scheduler.sh >> data/logs/retrain/retrain_cron_$(date +\%Y\%m\%d).log 2>&1
```

## Quick manual run

```bash
cd /home/manuelhorveydaniel/Projects/Quorrin
./scripts/ops/retrain_scheduler.sh              # full pipeline
./scripts/ops/retrain_scheduler.sh --dry-run     # dry run
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

## Timer schedule summary

| Timer | Schedule | Purpose |
|-------|----------|---------|
| `eigencapital-retrain.timer` | Sun 03:00 UTC | Weekly model retrain |
| `eigencapital-healthcheck.timer` | Daily 04:00 UTC | Daily health check + auto-retrain trigger |

Systemd timers are staggered (retrain on Sunday, health check daily 1h after retrain on Sundays)
to avoid overlapping pipeline runs. The health check timer has a 30min `OnBootSec` fallback;
the retrain timer has a 1h `OnBootSec` fallback.
