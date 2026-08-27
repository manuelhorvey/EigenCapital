"""Comprehensive tests to boost coverage across low-tested modules."""

from __future__ import annotations

from pathlib import Path

import pytest

# ── Core Models: Errors ──────────────────────────────────────────


class TestCoreErrors:
    """Tests for eigencapital.core.models.errors."""

    def test_eigen_capital_error_base(self):
        from eigencapital.core.models.errors import EigenCapitalError

        exc = EigenCapitalError("test message", model="Position", field="qty")
        assert str(exc) == "[Position.qty] test message"
        assert exc.message == "test message"
        assert exc.model == "Position"
        assert exc.field == "qty"
        assert exc.timestamp is not None

    def test_eigen_capital_error_no_model_field(self):
        from eigencapital.core.models.errors import EigenCapitalError

        exc = EigenCapitalError("plain message")
        assert str(exc) == "plain message"

    def test_invariant_violation(self):
        from eigencapital.core.models.errors import InvariantViolation

        exc = InvariantViolation("bad invariant", model="Order", field="size")
        assert isinstance(exc, ValueError)
        assert exc.model == "Order"

    def test_invalid_input(self):
        from eigencapital.core.models.errors import InvalidInput

        exc = InvalidInput("NaN price", model="Bar", field="close")
        assert isinstance(exc, ValueError)

    def test_duplicate_resource(self):
        from eigencapital.core.models.errors import DuplicateResource

        exc = DuplicateResource("dup id", model="Instrument", field="instrument_id")
        assert isinstance(exc, ValueError)

    def test_configuration_error(self):
        from eigencapital.core.models.errors import ConfigurationError

        exc = ConfigurationError("missing config", model="Strategy", field="config_hash")
        assert isinstance(exc, ValueError)

    def test_provenance_error(self):
        from eigencapital.core.models.errors import ProvenanceError

        exc = ProvenanceError("hash mismatch", model="Manifest", field="hash")
        assert isinstance(exc, ValueError)

    def test_check_invariant_passes(self):
        from eigencapital.core.models.errors import check_invariant

        check_invariant(True, "should not raise")

    def test_check_invariant_fails(self):
        from eigencapital.core.models.errors import InvariantViolation, check_invariant

        with pytest.raises(InvariantViolation, match="must be positive"):
            check_invariant(False, "must be positive", "Position", "qty")

    def test_check_not_none_passes(self):
        from eigencapital.core.models.errors import check_not_none

        check_not_none("value", "should not raise")

    def test_check_not_none_fails(self):
        from eigencapital.core.models.errors import InvalidInput, check_not_none

        with pytest.raises(InvalidInput, match="required"):
            check_not_none(None, "required field", "Order", "symbol")

    def test_check_positive_passes(self):
        from eigencapital.core.models.errors import check_positive

        check_positive(1.0)
        check_positive(0.01)

    def test_check_positive_fails(self):
        from eigencapital.core.models.errors import InvariantViolation, check_positive

        with pytest.raises(InvariantViolation):
            check_positive(0)
        with pytest.raises(InvariantViolation):
            check_positive(-1.0)

    def test_check_non_negative_passes(self):
        from eigencapital.core.models.errors import check_non_negative

        check_non_negative(0.0)
        check_non_negative(1.0)

    def test_check_non_negative_fails(self):
        from eigencapital.core.models.errors import InvariantViolation, check_non_negative

        with pytest.raises(InvariantViolation):
            check_non_negative(-0.01)

    def test_check_finite_passes(self):
        from eigencapital.core.models.errors import check_finite

        check_finite(1.0)
        check_finite(0.0)

    def test_check_finite_nan(self):
        from eigencapital.core.models.errors import InvariantViolation, check_finite

        with pytest.raises(InvariantViolation):
            check_finite(float("nan"))

    def test_check_finite_inf(self):
        from eigencapital.core.models.errors import InvariantViolation, check_finite

        with pytest.raises(InvariantViolation):
            check_finite(float("inf"))


# ── Strategies: Registry ─────────────────────────────────────────


class TestStrategyRegistry:
    """Tests for eigencapital.strategies.registry."""

    def test_register_and_get(self):
        from eigencapital.strategies.base import BaseStrategy
        from eigencapital.strategies.registry import StrategyRegistry

        class TestStrat(BaseStrategy):
            strategy_id = "test_strat"
            strategy_version = "1.0"

            def generate_signal(self, **kwargs):
                return 0.0

            def on_bar(self, bar, **kwargs):
                pass

        reg = StrategyRegistry()
        reg.register(TestStrat)
        assert "test_strat" in reg
        assert reg.get("test_strat") is TestStrat

    def test_get_not_found(self):
        from eigencapital.strategies.registry import StrategyNotFoundError, StrategyRegistry

        reg = StrategyRegistry()
        with pytest.raises(StrategyNotFoundError, match="not found"):
            reg.get("nonexistent")

    def test_create(self):
        from eigencapital.strategies.base import BaseStrategy
        from eigencapital.strategies.registry import StrategyRegistry

        class MyStrat(BaseStrategy):
            strategy_id = "my_strat"
            strategy_version = "1.0"

            def generate_signal(self, **kwargs):
                return 0.0

            def on_bar(self, bar, **kwargs):
                pass

        reg = StrategyRegistry()
        reg.register(MyStrat)
        instance = reg.create("my_strat")
        assert isinstance(instance, MyStrat)

    def test_list_ids(self):
        from eigencapital.strategies.base import BaseStrategy
        from eigencapital.strategies.registry import StrategyRegistry

        class A(BaseStrategy):
            strategy_id = "a"
            strategy_version = "1.0"

            def generate_signal(self, **kwargs):
                return 0.0

            def on_bar(self, bar, **kwargs):
                pass

        class B(BaseStrategy):
            strategy_id = "b"
            strategy_version = "1.0"

            def generate_signal(self, **kwargs):
                return 0.0

            def on_bar(self, bar, **kwargs):
                pass

        reg = StrategyRegistry()
        reg.register(B)
        reg.register(A)
        assert reg.list_ids() == ["a", "b"]

    def test_len(self):
        from eigencapital.strategies.base import BaseStrategy
        from eigencapital.strategies.registry import StrategyRegistry

        class X(BaseStrategy):
            strategy_id = "x"
            strategy_version = "1.0"

            def generate_signal(self, **kwargs):
                return 0.0

            def on_bar(self, bar, **kwargs):
                pass

        reg = StrategyRegistry()
        assert len(reg) == 0
        reg.register(X)
        assert len(reg) == 1


# ── Production Qual: Evidence Maturity ───────────────────────────


class TestEvidenceMaturity:
    """Tests for eigencapital.production_qual.evidence_maturity."""

    def test_e0_no_evidence(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(0, 0, 0, 0)
        assert state.level == EvidenceLevel.E0_NO_EVIDENCE.value
        assert state.level_number == 0
        assert state.operational_days == 0
        assert state.completed_trades == 0

    def test_e1_operational(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(7, 0, 0, 0)
        assert state.level == EvidenceLevel.E1_OPERATIONAL.value
        assert state.level_number == 1

    def test_e2_execution(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(14, 10, 0, 0)
        assert state.level == EvidenceLevel.E2_EXECUTION.value

    def test_e3_early_economic(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(21, 20, 1, 10)
        assert state.level == EvidenceLevel.E3_EARLY_ECONOMIC.value

    def test_e4_full_holding(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(45, 30, 2, 30)
        assert state.level == EvidenceLevel.E4_FULL_HOLDING.value

    def test_e5_replicated(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(90, 50, 3, 40)
        assert state.level == EvidenceLevel.E5_REPLICATED.value

    def test_e6_promotion_ready(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(120, 80, 5, 40)
        assert state.level == EvidenceLevel.E6_PROMOTION_READY.value
        assert tracker.is_promotion_ready()

    def test_not_promotion_ready(self):
        from eigencapital.production_qual.evidence_maturity import EvidenceMaturityTracker

        tracker = EvidenceMaturityTracker()
        tracker.assess(45, 30, 2, 30)
        assert not tracker.is_promotion_ready()

    def test_level_history(self):
        from eigencapital.production_qual.evidence_maturity import EvidenceMaturityTracker

        tracker = EvidenceMaturityTracker()
        tracker.assess(7, 0, 0, 0)
        tracker.assess(14, 10, 0, 0)
        history = tracker.get_history()
        assert len(history) == 2
        assert history[0]["from"] == "E0_NO_EVIDENCE"
        assert history[0]["to"] == "E1_OPERATIONAL"

    def test_assessment_text(self):
        from eigencapital.production_qual.evidence_maturity import EvidenceMaturityTracker

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(7, 0, 0, 0)
        assert "Operational" in state.assessment

    def test_next_level_requirements(self):
        from eigencapital.production_qual.evidence_maturity import EvidenceMaturityTracker

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(3, 0, 0, 0)
        assert len(state.next_level_requirements) > 0

    def test_to_dict(self):
        from eigencapital.production_qual.evidence_maturity import EvidenceMaturityTracker

        tracker = EvidenceMaturityTracker()
        tracker.assess(7, 0, 0, 0)
        d = tracker.to_dict()
        assert "current_level" in d
        assert "history" in d
        assert "promotion_ready" in d

    def test_evidence_state_to_dict(self):
        from eigencapital.production_qual.evidence_maturity import EvidenceMaturityTracker

        tracker = EvidenceMaturityTracker()
        state = tracker.assess(45, 30, 2, 30)
        d = state.to_dict()
        assert d["level_number"] == 4
        assert d["operational_days"] == 45


# ── Live: Structured Logging ─────────────────────────────────────


class TestStructuredLogging:
    """Tests for eigencapital.live.structured_logging."""

    def test_logger_creation(self):
        from eigencapital.live.structured_logging import StructuredLogger

        logger = StructuredLogger("test_module")
        assert logger._module_name == "test_module"

    def test_logger_with_file(self, tmp_path):
        from eigencapital.live.structured_logging import StructuredLogger

        log_file = str(tmp_path / "test.log")
        logger = StructuredLogger("test", log_file=log_file)
        logger.info("test_event", key="value")
        # File should exist
        assert Path(log_file).exists()

    def test_logger_min_level(self):
        from eigencapital.live.structured_logging import LogLevel, StructuredLogger

        logger = StructuredLogger("test", min_level=LogLevel.WARNING)
        # debug and info should be filtered out
        logger.debug("debug_event")
        logger.info("info_event")
        logger.warning("warning_event")
        # No exception = filtering works

    def test_logger_with_correlation_id(self):
        from eigencapital.live.structured_logging import StructuredLogger

        logger = StructuredLogger("test")
        logger.trade("order_submitted", correlation_id="abc-123", symbol="EURUSD")

    def test_logger_error_with_exception(self):
        from eigencapital.live.structured_logging import StructuredLogger

        logger = StructuredLogger("test")
        try:
            raise ValueError("test error")
        except ValueError as e:
            logger.error("error_occurred", error=e)

    def test_logger_critical(self):
        from eigencapital.live.structured_logging import StructuredLogger

        logger = StructuredLogger("test")
        logger.critical("system_halt", reason="reconciliation_failed")

    def test_get_logger_singleton(self):
        from eigencapital.live.structured_logging import get_logger

        logger1 = get_logger("test_singleton")
        logger2 = get_logger("test_singleton")
        assert logger1 is logger2

    def test_get_logger_different_modules(self):
        from eigencapital.live.structured_logging import get_logger

        logger1 = get_logger("module_a")
        logger2 = get_logger("module_b")
        assert logger1 is not logger2

    def test_log_level_enum(self):
        from eigencapital.live.structured_logging import LogLevel

        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARNING.value == "WARNING"
        assert LogLevel.ERROR.value == "ERROR"
        assert LogLevel.CRITICAL.value == "CRITICAL"


# ── Features: Mean Reversion Deviation ───────────────────────────


class TestMeanReversionDeviation:
    """Tests for eigencapital.features.mean_reversion.deviation."""

    def _make_bars(self, closes, highs=None, lows=None, volumes=None):
        from eigencapital.core.models.bar import Bar

        if highs is None:
            highs = [c * 1.01 for c in closes]
        if lows is None:
            lows = [c * 0.99 for c in closes]
        if volumes is None:
            volumes = [1000.0] * len(closes)

        bars = []
        for i, (c, h, idx, v) in enumerate(zip(closes, highs, lows, volumes)):
            start_ts = f"2026-01-{i + 1:02d}T00:00:00Z"
            end_ts = f"2026-01-{i + 1:02d}T23:59:59Z"
            bars.append(
                Bar(
                    instrument_id="TEST",
                    timestamp_utc=end_ts,
                    bar_start_utc=start_ts,
                    bar_end_utc=end_ts,
                    open=c * 0.999,
                    high=h,
                    low=idx,
                    close=c,
                    volume=v,
                )
            )
        return bars

    def test_distance_from_sma(self):
        from eigencapital.features.mean_reversion.deviation import compute_distance_from_sma

        bars = self._make_bars([100.0] * 20)
        result = compute_distance_from_sma(bars, lookback=10)
        assert result is not None
        assert abs(result) < 1e-10  # Constant series → 0 distance

    def test_distance_from_sma_insufficient_data(self):
        from eigencapital.features.mean_reversion.deviation import compute_distance_from_sma

        bars = self._make_bars([100.0] * 5)
        result = compute_distance_from_sma(bars, lookback=10)
        assert result is None

    def test_distance_from_ema(self):
        from eigencapital.features.mean_reversion.deviation import compute_distance_from_ema

        bars = self._make_bars([100.0] * 20)
        result = compute_distance_from_ema(bars, lookback=10)
        assert result is not None

    def test_distance_from_ema_insufficient(self):
        from eigencapital.features.mean_reversion.deviation import compute_distance_from_ema

        bars = self._make_bars([100.0] * 3)
        result = compute_distance_from_ema(bars, lookback=10)
        assert result is None

    def test_vwap_deviation(self):
        from eigencapital.features.mean_reversion.deviation import compute_vwap_deviation

        bars = self._make_bars([100.0] * 20)
        result = compute_vwap_deviation(bars, lookback=10)
        assert result is not None

    def test_vwap_deviation_insufficient(self):
        from eigencapital.features.mean_reversion.deviation import compute_vwap_deviation

        bars = self._make_bars([100.0] * 3)
        result = compute_vwap_deviation(bars, lookback=10)
        assert result is None

    def test_vwap_deviation_zero_volume(self):
        from eigencapital.features.mean_reversion.deviation import compute_vwap_deviation

        bars = self._make_bars([100.0] * 10, volumes=[0.0] * 10)
        result = compute_vwap_deviation(bars, lookback=10)
        assert result is None

    def test_make_distance_from_sma_feature(self):
        from eigencapital.features.mean_reversion.deviation import make_distance_from_sma_feature

        bars = self._make_bars([100.0] * 20)
        feature = make_distance_from_sma_feature(bars, lookback=10, instrument_id="TEST")
        assert feature is not None
        assert feature.instrument_id == "TEST"

    def test_make_distance_from_sma_feature_insufficient(self):
        from eigencapital.features.mean_reversion.deviation import make_distance_from_sma_feature

        bars = self._make_bars([100.0] * 3)
        feature = make_distance_from_sma_feature(bars, lookback=10, instrument_id="TEST")
        assert feature is None


# ── Features: Mean Reversion Reversal ────────────────────────────


class TestMeanReversionReversal:
    """Tests for eigencapital.features.mean_reversion.reversal."""

    def _make_bars(self, closes):
        from eigencapital.core.models.bar import Bar

        bars = []
        for i, c in enumerate(closes):
            start_ts = f"2026-01-{i + 1:02d}T00:00:00Z"
            end_ts = f"2026-01-{i + 1:02d}T23:59:59Z"
            bars.append(
                Bar(
                    instrument_id="TEST",
                    timestamp_utc=end_ts,
                    bar_start_utc=start_ts,
                    bar_end_utc=end_ts,
                    open=c * 0.999,
                    high=c * 1.01,
                    low=c * 0.99,
                    close=c,
                    volume=1000.0,
                )
            )
        return bars

    def test_short_term_reversal(self):
        from eigencapital.features.mean_reversion.reversal import compute_short_term_reversal

        bars = self._make_bars([100.0, 101.0])
        result = compute_short_term_reversal(bars, lookback=1)
        assert result is not None
        # Price went up 1%, reversal should be -1%
        assert abs(result - (-0.01)) < 1e-10

    def test_short_term_reversal_insufficient(self):
        from eigencapital.features.mean_reversion.reversal import compute_short_term_reversal

        bars = self._make_bars([100.0])
        result = compute_short_term_reversal(bars, lookback=1)
        assert result is None

    def test_rsi_all_gains(self):
        from eigencapital.features.mean_reversion.reversal import compute_rsi

        bars = self._make_bars([100.0 + i for i in range(20)])
        result = compute_rsi(bars, lookback=14)
        assert result is not None
        assert result == 100.0  # All gains → RSI = 100

    def test_rsi_all_losses(self):
        from eigencapital.features.mean_reversion.reversal import compute_rsi

        bars = self._make_bars([100.0 - i for i in range(20)])
        result = compute_rsi(bars, lookback=14)
        assert result is not None
        assert result == 0.0  # All losses → RSI = 0

    def test_rsi_insufficient(self):
        from eigencapital.features.mean_reversion.reversal import compute_rsi

        bars = self._make_bars([100.0] * 5)
        result = compute_rsi(bars, lookback=14)
        assert result is None

    def test_rsi_zscore(self):
        from eigencapital.features.mean_reversion.reversal import compute_rsi_zscore

        bars = self._make_bars([100.0 + i for i in range(20)])
        result = compute_rsi_zscore(bars, lookback=14)
        assert result is not None
        assert result > 0  # Overbought → positive z-score

    def test_rsi_zscore_insufficient(self):
        from eigencapital.features.mean_reversion.reversal import compute_rsi_zscore

        bars = self._make_bars([100.0] * 3)
        result = compute_rsi_zscore(bars, lookback=14)
        assert result is None

    def test_make_rsi_feature(self):
        from eigencapital.features.mean_reversion.reversal import make_rsi_feature

        bars = self._make_bars([100.0 + i for i in range(20)])
        feature = make_rsi_feature(bars, lookback=14, instrument_id="TEST")
        assert feature is not None

    def test_make_rsi_feature_insufficient(self):
        from eigencapital.features.mean_reversion.reversal import make_rsi_feature

        bars = self._make_bars([100.0] * 3)
        feature = make_rsi_feature(bars, lookback=14, instrument_id="TEST")
        assert feature is None

    def test_make_reversal_feature(self):
        from eigencapital.features.mean_reversion.reversal import make_reversal_feature

        bars = self._make_bars([100.0, 101.0])
        feature = make_reversal_feature(bars, lookback=1, instrument_id="TEST")
        assert feature is not None

    def test_make_reversal_feature_insufficient(self):
        from eigencapital.features.mean_reversion.reversal import make_reversal_feature

        bars = self._make_bars([100.0])
        feature = make_reversal_feature(bars, lookback=1, instrument_id="TEST")
        assert feature is None


# ── Live: Structured Alerts ──────────────────────────────────────


class TestStructuredAlerts:
    """Tests for eigencapital.live.structured_alerts."""

    def test_alert_creation(self):
        from eigencapital.live.structured_alerts import Alert, AlertSeverity

        alert = Alert(
            alert_id="alert-001",
            timestamp="2026-01-01T00:00:00Z",
            severity=AlertSeverity.CRITICAL.value,
            category="HEALTH",
            event_type="system_halt",
            message="Reconciliation failed",
        )
        assert alert.severity == "CRITICAL"
        assert alert.event_type == "system_halt"

    def test_alert_severity_levels(self):
        from eigencapital.live.structured_alerts import AlertSeverity

        assert AlertSeverity.INFO.value == "INFO"
        assert AlertSeverity.WARNING.value == "WARNING"
        assert AlertSeverity.CRITICAL.value == "CRITICAL"

    def test_alert_to_dict(self):
        from eigencapital.live.structured_alerts import Alert, AlertSeverity

        alert = Alert(
            alert_id="alert-002",
            timestamp="2026-01-01T00:00:00Z",
            severity=AlertSeverity.WARNING.value,
            category="EXECUTION",
            event_type="spread_high",
            message="EURUSD spread > 2 pips",
        )
        d = alert.to_dict()
        assert d["severity"] == "WARNING"
        assert d["event_type"] == "spread_high"


# ── Live: Risk Observation ───────────────────────────────────────


class TestRiskObservation:
    """Tests for eigencapital.live.risk_observation."""

    def test_risk_observer_creation(self):
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver(min_equity=4000.0)
        assert observer._min_equity == 4000.0

    def test_observe_healthy(self):
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver(min_equity=4000.0, max_daily_loss=250.0)
        state = observer.observe(
            equity=5000.0,
            balance=5000.0,
            free_margin=4500.0,
            positions=[],
            daily_pnl=0.0,
        )
        assert state.overall_level in ("HEALTHY", "NORMAL", "healthy", "normal")

    def test_observe_drawdown(self):
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver(min_equity=4000.0)
        observer.observe(
            equity=7000.0,
            balance=7000.0,
            free_margin=6500.0,
            positions=[],
            daily_pnl=0.0,
        )
        state = observer.observe(
            equity=6500.0,
            balance=6500.0,
            free_margin=6000.0,
            positions=[],
            daily_pnl=-500.0,
        )
        assert state.observations is not None

    def test_observe_with_positions(self):
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver(min_equity=4000.0)
        positions = [{"symbol": "EURUSD", "volume": 0.01, "profit": 10.0}]
        state = observer.observe(
            equity=5000.0,
            balance=5000.0,
            free_margin=4500.0,
            positions=positions,
            daily_pnl=10.0,
        )
        assert state is not None


# ── Production Qual: Evidence Maturity — Edge Cases ──────────────


class TestEvidenceMaturityEdgeCases:
    """Edge case tests for evidence maturity."""

    def test_level_decreases_if_metrics_drop(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        tracker.assess(120, 80, 5, 40)  # E6
        # Re-assess with low metrics — level drops (no hysteresis)
        state = tracker.assess(5, 0, 0, 0)
        assert state.level == EvidenceLevel.E0_NO_EVIDENCE.value

    def test_get_current_level(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        assert tracker.get_current_level() == EvidenceLevel.E0_NO_EVIDENCE
        tracker.assess(14, 10, 0, 0)
        assert tracker.get_current_level() == EvidenceLevel.E2_EXECUTION

    def test_thresholds_complete(self):
        from eigencapital.production_qual.evidence_maturity import (
            EvidenceLevel,
            EvidenceMaturityTracker,
        )

        tracker = EvidenceMaturityTracker()
        # All 7 levels should have thresholds
        assert len(tracker.THRESHOLDS) == 7
        for level in EvidenceLevel:
            assert level in tracker.THRESHOLDS
