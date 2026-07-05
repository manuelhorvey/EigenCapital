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

## ATLAS Covariate Shift Detector

`eigencapital/observability/atlas.py:AtlasDetector` monitors feature distributions for structural shifts using three layered change-point tests:

| Layer | Method | Sensitivity |
|-------|--------|-------------|
| **CUSUM** | Cumulative-sum control chart — two-sided | Detects abrupt shifts in the mean of a feature distribution. Fires when accumulated deviation exceeds `cusum_threshold × stddev + cusum_k` |
| **Page-Hinkley** | Symmetric CUSUM variant with running minimum | Detects gradual upward or downward drifts that CUSUM may miss. Fires when `(running_mean - min_mean) - ph_delta > ph_delta × 4` |
| **KS** | Two-sample Kolmogorov-Smirnov test (sliding window) | Non-parametric distributional equality test between two consecutive time windows. Fires when `D > ks_threshold` |

**Verdict output:** Each layer votes independently. ATLAS produces:
- `transition` (bool) — any layer fired
- `confidence` (0–1) — weighted vote across 3 layers (1/3 per layer)
- `fired_layers` (list) — which layers fired
- `layer_details` (dict) — per-layer statistics

**Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `lookback` | 63 | Number of recent samples for context |
| `cusum_threshold` | 5.0 | CUSUM threshold (stddev multiplier) |
| `cusum_k` | 0.5 | CUSUM slack allowance |
| `ph_delta` | 0.005 | Page-Hinkley sensitivity |
| `ks_window` | 30 | Width of each sliding window |
| `ks_threshold` | 0.5 | KS statistic threshold (0–1) |

**Integration:** The detector is per-asset. Call `detector.update(asset_name, feature_value)` each cycle. Verdicts are logged and exposed via the dashboard if wired.

**Run tests:**
```bash
PYTHONPATH=$PYTHONPATH:. python -m pytest tests/test_atlas_detector.py -v
```

## Grafana

Pre-built dashboard definitions are in `ops/grafana/`. The recommended queries use the `eigencapital_engine_*` metric namespace.

---

**Last updated:** 2026-07-05
