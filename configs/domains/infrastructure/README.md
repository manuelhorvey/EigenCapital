# Infrastructure Domain — alerts

Alert channel configuration for the monitoring system.

| File | Purpose |
|------|---------|
| `configs/domains/infrastructure/config.yaml` | Operational scalars — data_source, rebalance freq, retrain_freq (promoted from legacy_extras in Phase 12.3) |
| `configs/domains/infrastructure/alerts.yaml` | PagerDuty + webhook alert channel configs — enabled/disabled, routing_key, min_interval |
| `configs/domains/infrastructure/optimizations.yaml` | Engine tuning flags — truncate_inference, batch_http, sqlite_state, async_diagnostics, regime_conviction_flip_gate (Phase 12.6) |

The alert manager (`paper_trading/alerting/manager.py`) reads `configs/domains/infrastructure/alerts.yaml` at
startup. Webhook format supports Slack-compatible payloads. PagerDuty integration
requires a valid routing key.

See `paper_trading/ops/slack_alerter.py` for the WAL-tailing Slack alert daemon
(separate from the alert channels configured here).
