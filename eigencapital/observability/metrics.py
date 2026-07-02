"""Prometheus metrics exporter — exposes Quorrin engine state as Prometheus
text format.

The endpoint is intentionally lightweight (zero deps on `prometheus_client`):
a ``/metrics`` HTTP handler renders the current registry to the standard
Prometheus text exposition format (v0.0.4).

Wire into the existing dashboard HTTP server by adding::

    from eigencapital.observability.metrics import MetricsRegistry, render_prometheus
    REGISTRY = MetricsRegistry()
    app.metrics_registry = REGISTRY
    # In handler.py: return self.server.metrics_registry.render() for /metrics

Metrics registered by default:

- quorrin_engine_cycles_total   — engine cycle counter
- quorrin_engine_signal_total    — labelled by asset + signal long/short/flat
- quorrin_engine_drawdown_pct    — current portfolio drawdown (gauge)
- quorrin_engine_uptime_seconds  — since start (gauge)
- quorrin_engine_wal_events_total — WAL events written
- quorrin_engine_skipped_entries_total — entries refused by gates
- quorrin_engine_kelly_multiplier — last computed kelly multiplier (gauge)
- quorrin_engine_breakeven_count  — counters for OK / fail trades
- quorrin_engine_calibration_applied — 1.0 if calibration ran on last inference

Each metric supports labels via the ``labelnames`` argument at registration.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class _Sample:
    """One label-set + value for a metric."""

    labels: tuple[tuple[str, str], ...]
    value: float


@dataclass
class _Metric:
    name: str
    type: str  # "counter" | "gauge"
    help: str
    labelnames: tuple[str, ...]
    samples: list[_Sample] = field(default_factory=list)

    def reset(self) -> None:
        self.samples.clear()


class MetricsRegistry:
    """Thread-safe metric registry — Prometheus text-format exposition.

    Metric types: counter (monotonic), gauge (settable in either direction).

    Labels: pass as keyword arguments to ``register`` and use ``samples()``
    to retrieve labelled values.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: dict[str, _Metric] = {}
        self._started_at: float = time.monotonic()

    def counter(
        self,
        name: str,
        help: str,
        labelnames: Iterable[str] = (),
    ) -> _CounterHandle:
        return self._register(name, "counter", help, tuple(labelnames))

    def gauge(
        self,
        name: str,
        help: str,
        labelnames: Iterable[str] = (),
    ) -> _GaugeHandle:
        return self._register(name, "gauge", help, tuple(labelnames))

    def _register(
        self,
        name: str,
        type_: str,
        help: str,
        labelnames: tuple[str, ...],
    ) -> _CounterHandle | _GaugeHandle:
        if not _is_valid_metric_name(name):
            raise ValueError(f"Metric name {name!r} must match Prometheus convention [a-zA-Z_:][a-zA-Z0-9_:]*")
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = _Metric(name=name, type=type_, help=help, labelnames=labelnames)
            metric = self._metrics[name]
        if type_ == "counter":
            return _CounterHandle(self, metric)
        return _GaugeHandle(self, metric)

    def _set(self, metric_name: str, value: float, **labels: str) -> None:
        with self._lock:
            metric = self._metrics.get(metric_name)
            if metric is None:
                raise KeyError(f"Unknown metric {metric_name!r}")
            self._validate_labels(metric, labels)
            label_tuple = tuple(sorted(labels.items()))
            # Remove any prior sample with these labels
            metric.samples = [s for s in metric.samples if s.labels != label_tuple]
            metric.samples.append(_Sample(labels=label_tuple, value=value))

    def _inc(self, metric_name: str, amount: float = 1.0, **labels: str) -> None:
        with self._lock:
            metric = self._metrics.get(metric_name)
            if metric is None:
                raise KeyError(f"Unknown metric {metric_name!r}")
            self._validate_labels(metric, labels)
            label_tuple = tuple(sorted(labels.items()))
            found = False
            for s in metric.samples:
                if s.labels == label_tuple:
                    s.value += amount
                    found = True
                    break
            if not found:
                metric.samples.append(_Sample(labels=label_tuple, value=amount))

    def _validate_labels(self, metric: _Metric, labels: dict[str, str]) -> None:
        if set(labels) - set(metric.labelnames):
            extra = set(labels) - set(metric.labelnames)
            raise ValueError(f"Metric {metric.name!r} does not accept labels {extra}; declared: {metric.labelnames}")

    def render(self) -> str:
        """Render all metrics in Prometheus text exposition format (v0.0.4)."""
        out: list[str] = []
        with self._lock:
            metrics = list(self._metrics.values())
        # Stable ordering by name
        metrics.sort(key=lambda m: m.name)
        for metric in metrics:
            out.append(f"# HELP {metric.name} {metric.help}")
            out.append(f"# TYPE {metric.name} {metric.type}")
            if not metric.samples:
                out.append(f"{metric.name} 0")
                continue
            for sample in sorted(metric.samples, key=lambda s: s.labels):
                if sample.labels:
                    label_str = ",".join(f'{k}="{_escape(v)}"' for k, v in sample.labels)
                    out.append(f"{metric.name}{{{label_str}}} {sample.value}")
                else:
                    out.append(f"{metric.name} {sample.value}")
        return "\n".join(out) + "\n"

    def reset(self) -> None:
        """Clear all sample values (used in tests)."""
        with self._lock:
            for m in self._metrics.values():
                m.reset()


def _escape(value: str) -> str:
    """Escape a label value per Prometheus exposition format spec."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _is_valid_metric_name(name: str) -> bool:
    """Check the [a-zA-Z_:][a-zA-Z0-9_:]* convention."""
    if not name:
        return False
    first = name[0]
    if not (first.isalpha() or first == "_" or first == ":"):
        return False
    return all(ch.isalnum() or ch == "_" or ch == ":" for ch in name[1:])


class _CounterHandle:
    """Bound reference to a counter metric registered on a registry."""

    def __init__(self, registry: MetricsRegistry, metric: _Metric) -> None:
        self._registry = registry
        self._metric = metric

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError("Counter can only increase")
        self._registry._inc(self._metric.name, amount, **labels)


class _GaugeHandle:
    """Bound reference to a gauge metric."""

    def __init__(self, registry: MetricsRegistry, metric: _Metric) -> None:
        self._registry = registry
        self._metric = metric

    def set(self, value: float, **labels: str) -> None:
        self._registry._set(self._metric.name, value, **labels)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        self._registry._inc(self._metric.name, amount, **labels)

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self._registry._inc(self._metric.name, -amount, **labels)


# ── Default registry factory ──────────────────────────────────────────────


def default_registry() -> MetricsRegistry:
    """Build a registry pre-populated with the canonical Quorrin engine metrics."""
    reg = MetricsRegistry()

    reg.counter(
        "eigencapital_engine_cycles_total",
        "Engine cycles executed since start (one per inference round)",
    )
    reg.counter(
        "eigencapital_engine_signal_total",
        "Signals generated per asset/direction",
        labelnames=("asset", "side"),
    )
    reg.gauge(
        "eigencapital_engine_drawdown_pct",
        "Current portfolio drawdown as fraction (negative)",
    )
    reg.gauge(
        "eigencapital_engine_uptime_seconds",
        "Seconds since the metrics registry was constructed",
    )
    reg.counter(
        "eigencapital_engine_wal_events_total",
        "Total WAL events emitted by the orchestrator",
        labelnames=("event_type",),
    )
    reg.counter(
        "eigencapital_engine_skipped_entries_total",
        "Entries refused by decision gates",
        labelnames=("asset", "reason"),
    )
    reg.gauge(
        "eigencapital_engine_kelly_multiplier",
        "Last computed Kelly multiplier (1.0 = neutral)",
    )
    reg.counter(
        "eigencapital_engine_breakeven_count",
        "Outcome counters per asset",
        labelnames=("asset", "outcome"),
    )
    reg.gauge(
        "eigencapital_engine_calibration_applied",
        "1.0 if calibration was applied on the last inference cycle, else 0.0",
    )
    reg.gauge(
        "eigencapital_engine_risk_exposure",
        "Current gross portfolio exposure as fraction of equity",
    )
    reg.gauge(
        "eigencapital_engine_leverage_budget_remaining",
        "Remaining leverage budget (USD) — paper path",
    )
    return reg


# ── Auto-updating gauges ─────────────────────────────────────────────────


class _AutoUptimeGauge:
    """Periodically refresh a gauge from a callable or monotonic clock."""

    def __init__(self, registry: MetricsRegistry, name: str, source: callable) -> None:
        self._registry = registry
        self._name = name
        self._source = source
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"eigencapital-prom-{name}")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                value = self._source()
                self._registry._set(self._name, value)
            except (OSError, ValueError, TypeError, AttributeError):
                # Auto-updater should never crash the host process; we
                # simply skip this cycle and try again after the wait.
                pass
            self._stop.wait(5.0)

    def stop(self) -> None:
        self._stop.set()
