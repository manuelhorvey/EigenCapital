# Monitoring — Prometheus Metrics

## Metrics Endpoint

The engine exposes a `/metrics` HTTP endpoint on the dashboard server (port 5000).

```bash
curl http://127.0.0.1:5000/metrics
```

## Default Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `eigencapital_engine_cycles_total` | counter | — | Engine cycles executed since start |
| `eigencapital_engine_signal_total` | counter | `asset`, `side` | Signals generated per asset/direction |
| `eigencapital_engine_drawdown_pct` | gauge | — | Current portfolio drawdown (negative fraction) |
| `eigencapital_engine_uptime_seconds` | gauge | — | Seconds since registry construction |
| `eigencapital_engine_wal_events_total` | counter | `event_type` | WAL events emitted by orchestrator |
| `eigencapital_engine_skipped_entries_total` | counter | `asset`, `reason` | Entries refused by decision gates |
| `eigencapital_engine_kelly_multiplier` | gauge | — | Last computed Kelly multiplier |
| `eigencapital_engine_breakeven_count` | counter | `asset`, `outcome` | Outcome counters per asset |
| `eigencapital_engine_calibration_applied` | gauge | — | 1.0 if calibration applied on last inference |
| `eigencapital_engine_risk_exposure` | gauge | — | Current gross portfolio exposure as fraction of equity |
| `eigencapital_engine_leverage_budget_remaining` | gauge | — | Remaining leverage budget (USD) |

## Key Files

| File | Role |
|------|------|
| `eigencapital/observability/metrics.py` | Metrics registry + `default_registry()` factory |
| `paper_trading/metrics/exposition.py` | Lightweight Prometheus text-format renderer (zero deps on prometheus_client) |
| `ops/prometheus/` | Prometheus scrape config + Grafana dashboard definitions |

## Integration

The `/metrics` handler is wired into `paper_trading/serve.py` via:

```python
from eigencapital.observability.metrics import default_registry
REGISTRY = default_registry()
```

Engine code populates metrics using the handles returned by `reg.counter()` and `reg.gauge()`.

## Auto-Update

The `eigencapital_engine_uptime_seconds` gauge auto-updates in a daemon thread (5s interval). See `_AutoUptimeGauge` in `eigencapital/observability/metrics.py`.

## Grafana

Pre-built dashboard definitions are in `ops/grafana/`. The recommended queries use the `eigencapital_engine_*` metric namespace.
