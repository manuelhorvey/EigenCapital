"""Portfolio Health Monitor Tests — fail-closed assessment + immutable log."""

from copy import deepcopy

import pytest

from eigencapital.execution.account import AccountSnapshot
from eigencapital.monitoring import (
    ALERT_ASSET_CLASS_EXPOSURE,
    ALERT_CONCENTRATION,
    ALERT_DAILY_LOSS,
    ALERT_GROSS_LEVERAGE,
    ALERT_KILL_SWITCH,
    ALERT_MAX_DRAWDOWN,
    ALERT_MIN_EQUITY,
    ALERT_POSITION_COUNT,
    ALERT_SNAPSHOT_STALE,
    ALERT_SNAPSHOT_UNPARSEABLE,
    ALERT_WARN_DAILY_LOSS,
    HealthReport,
    HealthState,
    PortfolioHealthMonitor,
    Severity,
)
from eigencapital.risk.policy import RiskPolicy

NOW = "2026-08-25T12:00:00+00:00"


def _snapshot(
    *,
    equity: float = 100_000.0,
    gross_exposure: float = 50_000.0,
    num_positions: int = 2,
    timestamp_utc: str = NOW,
) -> AccountSnapshot:
    return AccountSnapshot(
        timestamp_utc=timestamp_utc,
        cash=equity - gross_exposure * 0.5,
        equity=equity,
        gross_exposure=gross_exposure,
        net_exposure=gross_exposure * 0.5,
        num_positions=num_positions,
    )


@pytest.fixture
def policy() -> RiskPolicy:
    return RiskPolicy(
        max_drawdown_pct=10.0,
        warn_drawdown_pct=5.0,
        daily_loss_limit=1_000.0,
        warn_daily_loss=500.0,
        weekly_loss_limit=3_000.0,
        max_gross_leverage=2.0,
        warn_gross_leverage=1.5,
        max_position_count=5,
        min_equity=50_000.0,
    )


class TestHealthyPath:
    def test_fresh_snapshot_within_limits(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(), now_utc=NOW)

        assert report.state == HealthState.HEALTHY
        assert report.alerts == ()
        assert report.checks["snapshot_fresh"] is True
        assert report.checks["min_equity"] is True
        assert report.is_operational

    def test_report_is_immutable(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(), now_utc=NOW)
        with pytest.raises(AttributeError):
            report.state = HealthState.CRITICAL  # type: ignore[misc]


class TestFailClosed:
    def test_unparseable_snapshot_timestamp(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        snap = _snapshot(timestamp_utc="not-a-timestamp")
        report = monitor.assess(snap, now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_SNAPSHOT_UNPARSEABLE for a in report.alerts)
        assert report.checks["snapshot_fresh"] is False
        assert report.snapshot_age_seconds is None

    def test_stale_snapshot(self, policy):
        monitor = PortfolioHealthMonitor(policy, max_snapshot_age_seconds=60)
        stale_ts = "2026-08-25T11:58:00+00:00"  # 120s before NOW
        report = monitor.assess(_snapshot(timestamp_utc=stale_ts), now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        codes = [a.code for a in report.alerts]
        assert ALERT_SNAPSHOT_STALE in codes
        assert report.snapshot_age_seconds == pytest.approx(120.0)

    def test_future_snapshot_rejected(self, policy):
        """A snapshot from the future must not count as fresh."""
        monitor = PortfolioHealthMonitor(policy)
        future_ts = "2026-08-25T12:01:00+00:00"
        report = monitor.assess(_snapshot(timestamp_utc=future_ts), now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_SNAPSHOT_STALE for a in report.alerts)

    def test_zero_equity_fail_closed(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(equity=0.0), now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_MIN_EQUITY for a in report.alerts)
        # Downstream ratio checks must not run on zero equity.
        assert "gross_leverage" not in report.checks


class TestHardConstraintBreaches:
    def test_kill_switch_freezes(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(), kill_switch_active=True, now_utc=NOW)

        assert report.state == HealthState.FROZEN
        assert not report.is_operational
        assert any(a.code == ALERT_KILL_SWITCH for a in report.alerts)

    def test_min_equity_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(equity=40_000.0), now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_MIN_EQUITY for a in report.alerts)

    def test_max_drawdown_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        peak = monitor.assess(_snapshot(equity=100_000.0), now_utc=NOW)
        assert peak.state == HealthState.HEALTHY

        trough = monitor.assess(_snapshot(equity=85_000.0), now_utc=NOW)
        assert trough.state == HealthState.CRITICAL
        assert any(a.code == ALERT_MAX_DRAWDOWN for a in trough.alerts)

    def test_drawdown_warning_only_degrades(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        monitor.assess(_snapshot(equity=100_000.0), now_utc=NOW)
        mid = monitor.assess(_snapshot(equity=93_000.0), now_utc=NOW)

        assert mid.state == HealthState.DEGRADED
        assert all(a.severity != Severity.CRITICAL for a in mid.alerts)

    def test_daily_loss_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(), daily_pnl=-1_500.0, now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_DAILY_LOSS for a in report.alerts)

    def test_daily_loss_warning(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(), daily_pnl=-700.0, now_utc=NOW)

        assert report.state == HealthState.DEGRADED
        assert any(a.code == ALERT_WARN_DAILY_LOSS for a in report.alerts)

    def test_weekly_loss_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(), weekly_pnl=-3_500.0, now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        codes = [a.code for a in report.alerts]
        assert "weekly_loss_breach" in codes

    def test_gross_leverage_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(
            _snapshot(equity=100_000.0, gross_exposure=250_000.0),
            now_utc=NOW,
        )

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_GROSS_LEVERAGE for a in report.alerts)

    def test_position_count_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(num_positions=6), now_utc=NOW)

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_POSITION_COUNT for a in report.alerts)

    def test_concentration_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(
            _snapshot(),
            position_notionals={"XAUUSDm": 30_000.0},  # 30% of equity
            now_utc=NOW,
        )

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_CONCENTRATION for a in report.alerts)

    def test_asset_class_exposure_breach(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(
            _snapshot(),
            asset_class_exposure={"crypto": 45_000.0},  # 45% > default cap
            now_utc=NOW,
        )

        assert report.state == HealthState.CRITICAL
        assert any(a.code == ALERT_ASSET_CLASS_EXPOSURE for a in report.alerts)


class TestCriticalDominates:
    def test_critical_overrides_warnings(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        monitor.assess(_snapshot(equity=100_000.0), now_utc=NOW)
        # Drawdown 7% (> 5% warn, < 10% max) + daily loss breach.
        report = monitor.assess(_snapshot(equity=93_000.0), daily_pnl=-2_000.0, now_utc=NOW)
        criticals = [a for a in report.alerts if a.severity == Severity.CRITICAL]
        warnings = [a for a in report.alerts if a.severity == Severity.WARNING]
        assert criticals and warnings
        assert report.state == HealthState.CRITICAL

    def test_kill_switch_dominates_everything(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        healthy_first = monitor.assess(_snapshot(), now_utc=NOW)
        assert healthy_first.state == HealthState.HEALTHY

        frozen = monitor.assess(_snapshot(), kill_switch_active=True, now_utc=NOW)
        assert frozen.state == HealthState.FROZEN


class TestImmutableEventLog:
    def test_log_appends_and_chains(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        monitor.assess(_snapshot(), now_utc=NOW)
        monitor.assess(_snapshot(), now_utc=NOW)

        log = monitor.event_log
        assert len(log) == 2
        assert [e["seq"] for e in log] == [0, 1]
        assert log[1]["prev_entry_hash"] == log[0]["entry_hash"]
        assert monitor.verify_log_integrity()

    def test_tamper_detection_payload_swap(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        monitor.assess(_snapshot(equity=100_000.0), now_utc=NOW)
        monitor.assess(_snapshot(equity=90_000.0), now_utc=NOW)

        tampered = [deepcopy(e) for e in monitor.event_log]
        tampered[0]["payload_sha256"] = "0" * 64

        class TamperedMonitor:
            event_log = property(lambda self: tuple(tampered))
            verify_log_integrity = PortfolioHealthMonitor.verify_log_integrity

        assert not TamperedMonitor().verify_log_integrity()

    def test_tamper_detection_chain_break(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        monitor.assess(_snapshot(), now_utc=NOW)
        monitor.assess(_snapshot(), now_utc=NOW)

        tampered = [dict(e) for e in monitor.event_log]
        tampered[1]["prev_entry_hash"] = "f" * 64

        class TamperedMonitor:
            event_log = property(lambda self: tuple(tampered))
            verify_log_integrity = PortfolioHealthMonitor.verify_log_integrity

        assert not TamperedMonitor().verify_log_integrity()

    def test_entry_hash_deterministic(self, policy):
        m1 = PortfolioHealthMonitor(policy)
        m2 = PortfolioHealthMonitor(policy)
        m1.assess(_snapshot(), now_utc=NOW)
        m2.assess(_snapshot(), now_utc=NOW)

        assert m1.event_log[0]["entry_hash"] == m2.event_log[0]["entry_hash"]
        assert m1.verify_log_integrity()
        assert m2.verify_log_integrity()


class TestConstructorGuards:
    def test_invalid_max_age_rejected(self, policy):
        with pytest.raises(ValueError):
            PortfolioHealthMonitor(policy, max_snapshot_age_seconds=0)


class TestReportContract:
    def test_to_dict_shape(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report: HealthReport = monitor.assess(_snapshot(), daily_pnl=-100.0, now_utc=NOW)
        d = report.to_dict()
        assert set(d) == {
            "state",
            "alerts",
            "checks",
            "assessed_at_utc",
            "snapshot_age_seconds",
        }
        assert d["state"] == "healthy"

    def test_alert_dict_shape(self, policy):
        monitor = PortfolioHealthMonitor(policy)
        report = monitor.assess(_snapshot(), daily_pnl=-2_000.0, now_utc=NOW)
        alert = next(a for a in report.alerts if a.code == ALERT_DAILY_LOSS)
        assert set(alert.to_dict()) == {
            "severity",
            "code",
            "message",
            "observed",
        }
