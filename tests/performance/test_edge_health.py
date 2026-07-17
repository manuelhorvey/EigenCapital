"""
Tests for EdgeHealthMonitor — live structural edge health tracking.

Covers reversal rate computation, alert transitions, window management,
and the singleton accessor.
"""

from __future__ import annotations

from paper_trading.performance.edge_health import EdgeHealthMonitor, get_monitor, reset_monitor


class TestEdgeHealthMonitor:
    def test_initial_state(self):
        m = EdgeHealthMonitor()
        assert m.reversal_rate is None
        s = m.summary
        assert s["n_trades"] == 0
        assert s["n_losers"] == 0
        assert s["reversal_rate"] is None
        assert not s["alert"]

    def test_winner_ignored(self):
        m = EdgeHealthMonitor()
        m.record_trade("AUDUSD", "long", 1.0, 1.05, "tp", 0.3, peak_mfe_r=0.8)
        assert m.reversal_rate is None  # no losers yet

    def test_loser_with_mfe_below_1(self):
        m = EdgeHealthMonitor()
        m.record_trade("AUDUSD", "long", 1.0, 0.97, "sl", -0.5, peak_mfe_r=0.8)
        assert m.reversal_rate == 0.0  # 0/1 losers had MFE>=1R

    def test_loser_with_mfe_above_1(self):
        m = EdgeHealthMonitor()
        m.record_trade("AUDUSD", "long", 1.0, 0.96, "sl", -0.8, peak_mfe_r=1.5)
        assert m.reversal_rate == 1.0  # 1/1 losers had MFE>=1R

    def test_mixed_losers(self):
        m = EdgeHealthMonitor()
        m.record_trade("AUDUSD", "long", 1.0, 0.97, "sl", -0.5, peak_mfe_r=0.8)  # no MFE
        m.record_trade("AUDUSD", "long", 1.0, 0.95, "sl", -1.2, peak_mfe_r=1.5)  # MFE >= 1
        assert m.reversal_rate == 0.5  # 1/2

    def test_alert_activates_below_threshold(self):
        m = EdgeHealthMonitor(warning_threshold=0.5)
        # 3 losers, none with MFE>=1R → rate = 0.0 < 0.5
        for _ in range(3):
            m.record_trade("AUDUSD", "long", 1.0, 0.97, "sl", -0.5, peak_mfe_r=0.3)
        assert m.summary["alert"]

    def test_alert_clears_above_threshold(self):
        m = EdgeHealthMonitor(warning_threshold=0.5)
        # 2 losers without MFE, then 2 with MFE → rate = 2/4 = 0.5
        for _ in range(2):
            m.record_trade("AUDUSD", "long", 1.0, 0.97, "sl", -0.5, peak_mfe_r=0.3)
        assert m.summary["alert"]  # 0/2 = 0.0
        for _ in range(2):
            m.record_trade("AUDUSD", "long", 1.0, 0.95, "sl", -1.2, peak_mfe_r=1.5)
        assert not m.summary["alert"]  # 2/4 = 0.5 >= 0.5

    def test_rolling_window_evicts_old_trades(self):
        m = EdgeHealthMonitor(max_trades=5)
        for i in range(10):
            # Alternate: every other loser has MFE>=1R
            peak = 1.5 if i % 2 == 0 else 0.3
            m.record_trade("AUDUSD", "long", 1.0, 0.97, "sl", -0.5, peak_mfe_r=peak)
        assert len(m._trades) == 5  # max 5 in window
        # With even distribution in last 5, rate should be ~0.5
        assert m.reversal_rate is not None

    def test_no_mfe_peak_defaults_to_zero(self):
        m = EdgeHealthMonitor()
        # Simulate trade where adaptive exit engine never fired
        m.record_trade("AUDUSD", "long", 1.0, 0.97, "sl", -0.5)
        assert m.reversal_rate == 0.0  # peak_mfe_r defaults to 0.0

    def test_summary_structure(self):
        m = EdgeHealthMonitor()
        for i in range(3):
            m.record_trade("AUDUSD", "long", 1.0, 0.97, "sl", -0.5, peak_mfe_r=0.3 + i * 0.5)
        s = m.summary
        assert "n_trades" in s
        assert "n_losers" in s
        assert "reversal_rate" in s
        assert "mean_mfe_r" in s
        assert "median_mfe_r" in s
        assert "alert" in s

    def test_singleton(self):
        reset_monitor()
        m1 = get_monitor()
        m2 = get_monitor()
        assert m1 is m2  # same instance
        reset_monitor()
        m3 = get_monitor()
        assert m3 is not m1  # new instance after reset
