"""Tests for the Prometheus metrics registry + text exposition format."""
from __future__ import annotations

import pytest

from paper_trading.metrics.exposition import MetricsRegistry, _escape, default_registry


class TestRegistryBasics:
    def test_render_is_valid_prometheus_format(self):
        reg = MetricsRegistry()
        c = reg.counter("test_total", "Test counter")
        c.inc()
        c.inc()
        rendered = reg.render()
        assert "# HELP test_total Test counter" in rendered
        assert "# TYPE test_total counter" in rendered
        assert "test_total 2.0" in rendered

    def test_render_empty_registry(self):
        reg = MetricsRegistry()
        rendered = reg.render()
        # Should be valid empty text; just the trailing newline is fine
        assert rendered == "" or len(rendered) < 32  # tolerant empty rendering

    def test_gauge_can_increase_and_decrease(self):
        reg = MetricsRegistry()
        g = reg.gauge("temperature", "Test gauge")
        g.set(50.0)
        assert "temperature 50.0" in reg.render()
        g.dec(10.0)
        assert "temperature 40.0" in reg.render()
        g.inc(5.0)
        assert "temperature 45.0" in reg.render()

    def test_label_format(self):
        reg = MetricsRegistry()
        c = reg.counter("req_total", "Requests", labelnames=("method", "code"))
        c.inc(method="GET", code="200")
        c.inc(method="GET", code="200")  # same labels → value accumulates
        c.inc(method="POST", code="500")
        rendered = reg.render()
        # Labels are sorted alphabetically per Prometheus spec
        assert 'req_total{code="200",method="GET"} 2.0' in rendered
        assert 'req_total{code="500",method="POST"} 1.0' in rendered

    def test_unknown_metric_raises(self):
        reg = MetricsRegistry()
        with pytest.raises(KeyError):
            reg._set("nope", 1.0)

    def test_invalid_label_raises(self):
        reg = MetricsRegistry()
        c = reg.counter("foo_total", "desc", labelnames=("asset",))
        with pytest.raises(ValueError):
            c.inc(asset="x", extra="y")  # noqa

    def test_counter_must_be_nonnegative(self):
        reg = MetricsRegistry()
        c = reg.counter("neg_total", "neg")
        with pytest.raises(ValueError):
            c.inc(-1.0)

    def test_invalid_metric_name_rejected(self):
        reg = MetricsRegistry()
        with pytest.raises(ValueError):
            reg.counter("123_starts_with_digit", "x")
        with pytest.raises(ValueError):
            reg.counter("has-dash", "x")

    def test_metric_name_reuse_same_type(self):
        """Re-registering a metric with the same name and type is allowed."""
        reg = MetricsRegistry()
        c1 = reg.counter("same_total", "desc")
        c2 = reg.counter("same_total", "desc")  # re-register
        c1.inc()
        c2.inc()
        rendered = reg.render()
        assert "same_total 2.0" in rendered


class TestLabelEscaping:
    """Label values containing special characters must be escaped per spec."""

    def test_escapes_backslash(self):
        assert _escape("a\\b") == "a\\\\b"

    def test_escapes_double_quote(self):
        assert _escape('he said "hi"') == 'he said \\"hi\\"'

    def test_escapes_newline(self):
        assert _escape("line1\nline2") == "line1\\nline2"


class TestDefaultRegistry:
    def test_seeded_with_canonical_metrics(self):
        reg = default_registry()
        rendered = reg.render()
        # Spot-check several known metrics are present
        for metric in (
            "eigencapital_engine_cycles_total",
            "eigencapital_engine_signal_total",
            "eigencapital_engine_drawdown_pct",
            "eigencapital_engine_wal_events_total",
            "eigencapital_engine_skipped_entries_total",
            "eigencapital_engine_risk_exposure",
        ):
            assert f"# TYPE {metric}" in rendered

    def test_signal_total_labeled(self):
        reg = default_registry()
        signals = reg.counter(
            "eigencapital_engine_signal_total", "Sig", labelnames=("asset", "side")
        )
        signals.inc(asset="EURUSD", side="long")
        signals.inc(asset="EURUSD", side="short")
        rendered = reg.render()
        assert 'eigencapital_engine_signal_total{asset="EURUSD",side="long"} 1.0' in rendered
        assert 'eigencapital_engine_signal_total{asset="EURUSD",side="short"} 1.0' in rendered


class TestRenderOrdering:
    def test_metrics_sorted_by_name(self):
        reg = MetricsRegistry()
        reg.counter("zeta_total", "Z")
        reg.counter("alpha_total", "A")
        reg.counter("beta_total", "B")
        rendered = reg.render()
        # Find the order of "# TYPE" lines
        lines = [
            line for line in rendered.splitlines() if line.startswith("# TYPE")
        ]
        names = [line.split()[2] for line in lines]
        assert names == sorted(names)

    def test_samples_within_metric_sorted_by_label(self):
        reg = MetricsRegistry()
        c = reg.counter("hits_total", "hits", labelnames=("k",))
        c.inc(k="z")
        c.inc(k="a")
        c.inc(k="m")
        rendered = reg.render()
        body_lines = [
            line for line in rendered.splitlines()
            if line.startswith("hits_total{")
        ]
        # Should be sorted by label key alphabetically
        assert body_lines[0].startswith('hits_total{k="a"')
        assert body_lines[2].startswith('hits_total{k="z"')


class TestConcurrentSafety:
    def test_concurrent_inc(self):
        reg = MetricsRegistry()
        c = reg.counter("concurrent_total", "x")
        import threading

        n_per_thread = 100
        n_threads = 8

        def inc():
            for _ in range(n_per_thread):
                c.inc()

        threads = [threading.Thread(target=inc) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rendered = reg.render()
        expected = n_per_thread * n_threads
        assert f"concurrent_total {expected}.0" in rendered


class TestReset:
    def test_reset_clears_samples(self):
        reg = MetricsRegistry()
        c = reg.counter("foo", "x")
        c.inc(100.0)
        assert "foo 100.0" in reg.render()
        reg.reset()
        assert "foo 0" in reg.render()
