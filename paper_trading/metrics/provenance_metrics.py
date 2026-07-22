"""Provenance-layer Prometheus metrics — emitted after each capture cycle."""

from paper_trading.metrics.exposition import global_registry

_registry = global_registry()

_capture_total = _registry.counter(
    "provenance_capture_total",
    "Total provenance records captured",
    labelnames=("asset", "signal"),
)
_capture_errors = _registry.counter(
    "provenance_capture_errors_total",
    "Provenance capture failures",
    labelnames=("asset",),
)
_store_records = _registry.gauge(
    "provenance_store_records",
    "Total records in provenance store",
)
_store_size_bytes = _registry.gauge(
    "provenance_store_size_bytes",
    "Provenance database file size in bytes",
)
_capture_duration = _registry.histogram(
    "provenance_capture_duration_seconds",
    "Time to capture and persist one cycle's provenance records",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
_prune_records = _registry.counter(
    "provenance_prune_records_total",
    "Total records pruned from provenance store",
)
_store_health = _registry.gauge(
    "provenance_store_healthy",
    "1 if provenance store is healthy, 0 otherwise",
)


def record_capture(asset: str, signal: str) -> None:
    _capture_total.inc(asset=asset, signal=signal)


def record_capture_error(asset: str) -> None:
    _capture_errors.inc(asset=asset)


def update_store_metrics(store) -> None:
    try:
        h = store.health()
        _store_records.set(h.get("total_records", 0))
        _store_size_bytes.set(h.get("db_size_bytes", 0))
        _store_health.set(1.0 if h.get("status") == "ok" else 0.0)
    except Exception:
        _store_health.set(0.0)


def record_prune(count: int) -> None:
    _prune_records.inc(count)
