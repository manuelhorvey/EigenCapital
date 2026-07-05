# Infrastructure Domain — alerts

Alert channel configuration for the monitoring system.

| File | Purpose |
|------|---------|
| `alerts.yaml` | PagerDuty + webhook alert channel configs — enabled/disabled, routing_key, min_interval

The alert manager (`paper_trading/alerting/manager.py`) reads this file at
startup. Webhook format supports Slack-compatible payloads. PagerDuty integration
requires a valid routing key.

See `paper_trading/ops/slack_alerter.py` for the WAL-tailing Slack alert daemon
(separate from the alert channels configured here).
