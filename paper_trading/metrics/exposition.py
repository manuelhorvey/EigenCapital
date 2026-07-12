"""Lightweight Prometheus-format metrics exposition.

Provides a MetricsRegistry that accumulates counters, gauges, and histograms
and renders them in Prometheus text format — no external dependency required.
"""

from __future__ import annotations

import re
import threading
from collections import defaultdict

_VALID_METRIC_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


def _is_valid_metric_name(name: str) -> bool:
    """Check the [a-zA-Z_:][a-zA-Z0-9_:]* convention."""
    return bool(_VALID_METRIC_NAME_RE.match(name))


def _escape(value: str) -> str:
    """Escape a label value per Prometheus exposition format spec."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: dict[str, str]) -> str:
    """Format label dict into Prometheus label string (sorted by key).

    Returns empty string if there are no labels.
    """
    if not labels:
        return ""
    parts = []
    for k in sorted(labels):
        parts.append(f'{k}="{_escape(labels[k])}"')
    return "{" + ",".join(parts) + "}"


class _Metric:
    __slots__ = ("name", "documentation", "type_name", "_labelnames", "_lock")

    def __init__(self, name: str, documentation: str, type_name: str, labelnames: tuple[str, ...] | None = None):
        if not _is_valid_metric_name(name):
            raise ValueError(f"Invalid metric name: {name!r}")
        self.name = name
        self.documentation = documentation
        self.type_name = type_name
        self._labelnames: frozenset[str] = frozenset(labelnames) if labelnames else frozenset()
        self._lock = threading.Lock()

    def _validate_labels(self, labels: dict[str, str]) -> None:
        """If labelnames were declared, verify all given labels are declared."""
        if self._labelnames:
            extra = set(labels) - self._labelnames
            if extra:
                raise ValueError(
                    f"Unexpected label(s) {sorted(extra)} for metric {self.name!r}; "
                    f"declared labelnames={sorted(self._labelnames)}"
                )

    def _format(self) -> list[str]:
        raise NotImplementedError


class Counter(_Metric):
    """Monotonically increasing counter."""

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: tuple[str, ...] | None = None,
    ):
        super().__init__(name, documentation, "counter", labelnames=labelnames)
        self._values: dict[tuple, float] = {}

    def inc(self, value: float = 1.0, **labels: str) -> None:
        if value < 0:
            raise ValueError(f"Counter can only increase, got {value}")
        self._validate_labels(labels)
        with self._lock:
            key = tuple(sorted(labels.items()))
            self._values[key] = self._values.get(key, 0.0) + value

    def _format(self) -> list[str]:
        lines: list[str] = []
        with self._lock:
            if not self._values:
                # Prometheus convention: even zero-valued metrics render
                lines.append(f"{self.name} 0")
            else:
                for key, val in sorted(self._values.items()):
                    labels = dict(key)
                    labels_str = _format_labels(labels)
                    lines.append(f"{self.name}{labels_str} {val}")
        return lines


class Gauge(_Metric):
    """Single numeric value that can go up or down."""

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: tuple[str, ...] | None = None,
    ):
        super().__init__(name, documentation, "gauge", labelnames=labelnames)
        self._values: dict[tuple, float] = {}

    def set(self, value: float, **labels: str) -> None:
        self._validate_labels(labels)
        with self._lock:
            key = tuple(sorted(labels.items()))
            self._values[key] = value

    def inc(self, value: float = 1.0, **labels: str) -> None:
        self._validate_labels(labels)
        with self._lock:
            key = tuple(sorted(labels.items()))
            self._values[key] = self._values.get(key, 0.0) + value

    def dec(self, value: float = 1.0, **labels: str) -> None:
        self._validate_labels(labels)
        with self._lock:
            key = tuple(sorted(labels.items()))
            self._values[key] = self._values.get(key, 0.0) - value

    def _format(self) -> list[str]:
        lines: list[str] = []
        with self._lock:
            if not self._values:
                lines.append(f"{self.name} 0")
            else:
                for key, val in sorted(self._values.items()):
                    labels = dict(key)
                    labels_str = _format_labels(labels)
                    lines.append(f"{self.name}{labels_str} {val}")
        return lines


class Histogram(_Metric):
    """Histogram with configurable buckets (count + sum + per-bucket)."""

    def __init__(
        self,
        name: str,
        documentation: str,
        buckets: list[float] | None = None,
        labelnames: tuple[str, ...] | None = None,
    ):
        super().__init__(name, documentation, "histogram", labelnames=labelnames)
        if buckets is None:
            buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        self._buckets = sorted(buckets)
        self._counts: dict[tuple, list[int]] = defaultdict(lambda: [0] * (len(self._buckets) + 1))
        self._sums: dict[tuple, float] = defaultdict(float)

    def observe(self, value: float, **labels: str) -> None:
        self._validate_labels(labels)
        with self._lock:
            key = tuple(sorted(labels.items()))
            self._sums[key] += value
            for i, b in enumerate(self._buckets):
                if value <= b:
                    self._counts[key][i] += 1
            self._counts[key][len(self._buckets)] += 1  # +Inf bucket

    def _format(self) -> list[str]:
        lines: list[str] = []
        with self._lock:
            for key, count_list in sorted(self._counts.items()):
                labels = dict(key)
                labels_str = _format_labels(labels)
                total = count_list[-1]
                for i, b in enumerate(self._buckets):
                    lines.append(f'{self.name}_bucket{labels_str}{{le="{b}"}} {count_list[i]}')
                lines.append(f'{self.name}_bucket{labels_str}{{le="+Inf"}} {total}')
                lines.append(f"{self.name}_count{labels_str} {total}")
                lines.append(f"{self.name}_sum{labels_str} {self._sums.get(key, 0.0)}")
        return lines


class MetricsRegistry:
    """Thread-safe registry of Prometheus metrics."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, documentation: str, labelnames: tuple[str, ...] | None = None) -> Counter:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, documentation, labelnames=labelnames)
            return self._counters[name]

    def gauge(self, name: str, documentation: str, labelnames: tuple[str, ...] | None = None) -> Gauge:
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, documentation, labelnames=labelnames)
            return self._gauges[name]

    def histogram(
        self,
        name: str,
        documentation: str,
        buckets: list[float] | None = None,
        labelnames: tuple[str, ...] | None = None,
    ) -> Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, documentation, buckets, labelnames=labelnames)
            return self._histograms[name]

    def reset(self) -> None:
        """Clear all metrics (used in tests)."""
        with self._lock:
            for metric in self._counters.values():
                metric._values.clear()
            for metric in self._gauges.values():
                metric._values.clear()
            for metric in self._histograms.values():
                metric._counts.clear()
                metric._sums.clear()

    def _set(self, metric_name: str, value: float, **labels: str) -> None:
        """Set a gauge value by name."""
        gauge = self._gauges.get(metric_name)
        if gauge is None:
            raise KeyError(f"Unknown metric {metric_name!r}")
        gauge.set(value, **labels)

    def _inc(self, metric_name: str, amount: float = 1.0, **labels: str) -> None:
        """Increment a counter/gauge by name (backward compat)."""
        counter = self._counters.get(metric_name)
        if counter is not None:
            counter.inc(amount, **labels)
            return
        gauge = self._gauges.get(metric_name)
        if gauge is not None:
            gauge.inc(amount, **labels)
            return
        raise KeyError(f"Unknown metric {metric_name!r}")

    def render(self) -> str:
        """Render all metrics in Prometheus text format.

        Metrics are sorted by name (as required by the Prometheus exposition
        format spec for deterministic output).
        """
        lines: list[str] = []
        with self._lock:
            # Gather all metrics sorted by name
            all_metrics: list[_Metric] = list(self._counters.values())
            all_metrics += list(self._gauges.values())
            all_metrics += list(self._histograms.values())
            all_metrics.sort(key=lambda m: m.name)
            for metric in all_metrics:
                lines.append(f"# HELP {metric.name} {metric.documentation}")
                lines.append(f"# TYPE {metric.name} {metric.type_name}")
                lines.extend(metric._format())
        # Prometheus expects a trailing newline
        lines.append("")
        return "\n".join(lines)


# Global registry shared across the application
_registry_lock = threading.Lock()
_registry: MetricsRegistry | None = None


def global_registry() -> MetricsRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = MetricsRegistry()
    return _registry


def _reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry
    with _registry_lock:
        _registry = None


def default_registry() -> MetricsRegistry:
    """Build a registry pre-populated with canonical EigenCapital engine metrics."""
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
    )
    reg.counter(
        "eigencapital_engine_skipped_entries_total",
        "Entries refused by decision gates",
    )
    reg.gauge(
        "eigencapital_engine_kelly_multiplier",
        "Last computed Kelly multiplier (1.0 = neutral)",
    )
    reg.counter(
        "eigencapital_engine_breakeven_count",
        "Outcome counters per asset",
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
