"""MarketSchedule Tests — verify trading calendar abstraction.

Tests:
1. Session types render correctly
2. Weekday schedule: Mon-Fri open, Sat-Sun closed
3. 24/7 schedule: always open except maintenance
4. Maintenance windows detected correctly
5. Next open/close queries
6. Trading day computation
7. TOML config loading
8. Predefined schedules
9. MarketState 4 independent states
10. Parity: weekday schedule produces same results as hardcoded checks
"""

from __future__ import annotations

from datetime import UTC, datetime, time as dt_time
from pathlib import Path

import pytest


class TestSessionTypes:
    """Verify session type classification."""

    def test_session_type_enum(self) -> None:
        """SessionType must have all expected values."""
        from eigencapital.core.market_schedule import SessionType

        assert SessionType.WEEKDAY.value == "WEEKDAY"
        assert SessionType.EXTENDED.value == "EXTENDED"
        assert SessionType.CONTINUOUS_24_7.value == "CONTINUOUS_24_7"
        assert SessionType.CUSTOM.value == "CUSTOM"

    def test_market_availability_enum(self) -> None:
        """MarketAvailability must have all expected values."""
        from eigencapital.core.market_schedule import MarketAvailability

        assert MarketAvailability.OPEN.value == "OPEN"
        assert MarketAvailability.CLOSED.value == "CLOSED"
        assert MarketAvailability.MAINTENANCE.value == "MAINTENANCE"
        assert MarketAvailability.HALTED.value == "HALTED"
        assert MarketAvailability.UNKNOWN.value == "UNKNOWN"


class TestWeekdaySchedule:
    """Verify WEEKDAY schedule (FX) behavior."""

    def _make_fx(self) -> "MarketSchedule":
        from eigencapital.core.market_schedule import MarketSchedule, SessionType, TradingSession

        return MarketSchedule(
            instrument="EURUSD",
            session_type=SessionType.WEEKDAY,
            trading_sessions=[TradingSession(open_time=dt_time(0, 0), close_time=dt_time(0, 0))],
        )

    def test_weekday_open(self) -> None:
        """Monday 12:00 should be open."""
        schedule = self._make_fx()
        monday = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)  # Monday
        assert schedule.is_market_open(monday) is True

    def test_friday_close(self) -> None:
        """Friday 23:59 should be open (24h session)."""
        schedule = self._make_fx()
        friday = datetime(2026, 8, 28, 23, 59, tzinfo=UTC)  # Friday
        assert schedule.is_market_open(friday) is True

    def test_saturday_closed(self) -> None:
        """Saturday should be closed."""
        schedule = self._make_fx()
        saturday = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)  # Saturday
        assert schedule.is_market_open(saturday) is False

    def test_sunday_closed(self) -> None:
        """Sunday should be closed."""
        schedule = self._make_fx()
        sunday = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)  # Sunday
        assert schedule.is_market_open(sunday) is False

    def test_trading_days_per_year(self) -> None:
        """FX should use 252 trading days."""
        schedule = self._make_fx()
        assert schedule.trading_days_per_year == 252


class TestCryptoSchedule:
    """Verify CONTINUOUS_24_7 schedule (crypto) behavior."""

    def _make_btc(self) -> "MarketSchedule":
        from eigencapital.core.market_schedule import MaintenanceWindow, MarketSchedule, SessionType

        return MarketSchedule(
            instrument="BTCUSD",
            session_type=SessionType.CONTINUOUS_24_7,
            maintenance_windows=[
                MaintenanceWindow(
                    day_of_week=5,  # Saturday
                    start_time=dt_time(4, 0),
                    end_time=dt_time(4, 30),
                    description="Saturday maintenance",
                ),
            ],
            trading_days_per_year=365,
        )

    def test_weekday_open(self) -> None:
        """Wednesday should be open."""
        schedule = self._make_btc()
        wednesday = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)  # Wednesday
        assert schedule.is_market_open(wednesday) is True

    def test_saturday_open_outside_maintenance(self) -> None:
        """Saturday outside maintenance window should be open."""
        schedule = self._make_btc()
        saturday_noon = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)  # Saturday 12:00
        assert schedule.is_market_open(saturday_noon) is True

    def test_saturday_closed_during_maintenance(self) -> None:
        """Saturday 04:15 should be in maintenance."""
        schedule = self._make_btc()
        sat_maintenance = datetime(2026, 8, 29, 4, 15, tzinfo=UTC)  # Saturday 04:15
        assert schedule.is_market_open(sat_maintenance) is False

    def test_sunday_open(self) -> None:
        """Sunday should be open (crypto)."""
        schedule = self._make_btc()
        sunday = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)  # Sunday
        assert schedule.is_market_open(sunday) is True

    def test_trading_days_per_year(self) -> None:
        """Crypto should use 365 trading days."""
        schedule = self._make_btc()
        assert schedule.trading_days_per_year == 365


class TestMaintenanceWindows:
    """Verify maintenance window detection."""

    def test_maintenance_containment(self) -> None:
        """MaintenanceWindow.contains should work for exact times."""
        from eigencapital.core.market_schedule import MaintenanceWindow

        mw = MaintenanceWindow(
            day_of_week=5,
            start_time=dt_time(4, 0),
            end_time=dt_time(4, 30),
        )

        # Inside window
        assert mw.contains(datetime(2026, 8, 29, 4, 15, tzinfo=UTC)) is True
        # Before window
        assert mw.contains(datetime(2026, 8, 29, 3, 59, tzinfo=UTC)) is False
        # After window
        assert mw.contains(datetime(2026, 8, 29, 4, 30, tzinfo=UTC)) is False
        # Wrong day
        assert mw.contains(datetime(2026, 8, 31, 4, 15, tzinfo=UTC)) is False  # Monday

    def test_no_day_restriction(self) -> None:
        """MaintenanceWindow with no day_of_week should match any day."""
        from eigencapital.core.market_schedule import MaintenanceWindow

        mw = MaintenanceWindow(
            day_of_week=None,
            start_time=dt_time(4, 0),
            end_time=dt_time(4, 30),
        )

        # Any day at 04:15 should be in maintenance
        assert mw.contains(datetime(2026, 8, 29, 4, 15, tzinfo=UTC)) is True
        assert mw.contains(datetime(2026, 8, 31, 4, 15, tzinfo=UTC)) is True


class TestNextOpenClose:
    """Verify next_open and next_close queries."""

    def test_next_open_after_weekend(self) -> None:
        """Next open after Saturday should be Monday."""
        from eigencapital.core.market_schedule import MarketSchedule, SessionType, TradingSession

        schedule = MarketSchedule(
            instrument="EURUSD",
            session_type=SessionType.WEEKDAY,
            trading_sessions=[TradingSession(open_time=dt_time(0, 0), close_time=dt_time(0, 0))],
        )

        # Saturday — market is closed, next open should be Monday
        saturday = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
        next_open = schedule.next_open(saturday)

        # Should be Monday (Aug 31)
        assert next_open.weekday() == 0  # Monday
        assert next_open.day == 31

    def test_next_close_for_crypto(self) -> None:
        """Next close for crypto should be next maintenance window."""
        from eigencapital.core.market_schedule import MaintenanceWindow, MarketSchedule, SessionType

        schedule = MarketSchedule(
            instrument="BTCUSD",
            session_type=SessionType.CONTINUOUS_24_7,
            maintenance_windows=[
                MaintenanceWindow(
                    day_of_week=5,
                    start_time=dt_time(4, 0),
                    end_time=dt_time(4, 30),
                ),
            ],
        )

        wednesday = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
        next_close = schedule.next_close(wednesday)

        # Should be Saturday 04:00
        assert next_close.weekday() == 5  # Saturday
        assert next_close.hour == 4


class TestTradingDay:
    """Verify trading day computation."""

    def test_trading_day_returns_date(self) -> None:
        """Trading day should be YYYY-MM-DD."""
        from eigencapital.core.market_schedule import MarketSchedule, SessionType

        schedule = MarketSchedule(instrument="TEST", session_type=SessionType.WEEKDAY)
        dt = datetime(2026, 8, 29, 14, 30, tzinfo=UTC)
        assert schedule.trading_day(dt) == "2026-08-29"


class TestSessionId:
    """Verify session ID computation."""

    def test_session_id_format(self) -> None:
        """Session ID should contain instrument, type, and time."""
        from eigencapital.core.market_schedule import MarketSchedule, SessionType

        schedule = MarketSchedule(instrument="EURUSD", session_type=SessionType.WEEKDAY)
        dt = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
        sid = schedule.session_id(dt)
        assert "EURUSD" in sid
        assert "WEEKDAY" in sid
        assert "2026-08-29" in sid


class TestTOMLConfigLoading:
    """Verify TOML config loading."""

    def test_load_default_config(self) -> None:
        """Should load the default market schedules config."""
        from eigencapital.core.market_schedule import load_schedules_from_file

        config_path = Path("configs/market_schedules/default.toml")
        if not config_path.exists():
            pytest.skip("Default config not found")

        schedules = load_schedules_from_file(config_path)
        assert len(schedules) > 0
        assert "EURUSD" in schedules
        assert "BTCUSD" in schedules

    def test_fx_loaded_as_weekday(self) -> None:
        """FX instruments should be loaded as WEEKDAY."""
        from eigencapital.core.market_schedule import SessionType, load_schedules_from_file

        config_path = Path("configs/market_schedules/default.toml")
        if not config_path.exists():
            pytest.skip("Default config not found")

        schedules = load_schedules_from_file(config_path)
        assert schedules["EURUSD"].session_type == SessionType.WEEKDAY
        assert schedules["GBPUSD"].session_type == SessionType.WEEKDAY

    def test_btc_loaded_as_24_7(self) -> None:
        """BTCUSD should be loaded as CONTINUOUS_24_7."""
        from eigencapital.core.market_schedule import SessionType, load_schedules_from_file

        config_path = Path("configs/market_schedules/default.toml")
        if not config_path.exists():
            pytest.skip("Default config not found")

        schedules = load_schedules_from_file(config_path)
        assert schedules["BTCUSD"].session_type == SessionType.CONTINUOUS_24_7

    def test_btc_has_maintenance(self) -> None:
        """BTCUSD should have maintenance windows."""
        from eigencapital.core.market_schedule import load_schedules_from_file

        config_path = Path("configs/market_schedules/default.toml")
        if not config_path.exists():
            pytest.skip("Default config not found")

        schedules = load_schedules_from_file(config_path)
        assert len(schedules["BTCUSD"].maintenance_windows) > 0

    def test_btc_maintenance_on_saturday(self) -> None:
        """BTCUSD maintenance should be on Saturday."""
        from eigencapital.core.market_schedule import load_schedules_from_file

        config_path = Path("configs/market_schedules/default.toml")
        if not config_path.exists():
            pytest.skip("Default config not found")

        schedules = load_schedules_from_file(config_path)
        mw = schedules["BTCUSD"].maintenance_windows[0]
        assert mw.day_of_week == 5  # Saturday

    def test_asset_class_in_details(self) -> None:
        """Asset class should be in schedule details."""
        from eigencapital.core.market_schedule import load_schedules_from_file

        config_path = Path("configs/market_schedules/default.toml")
        if not config_path.exists():
            pytest.skip("Default config not found")

        schedules = load_schedules_from_file(config_path)
        assert schedules["BTCUSD"].details.get("asset_class") == "crypto"
        assert schedules["EURUSD"].details.get("asset_class") == "forex"


class TestPredefinedSchedules:
    """Verify predefined schedule factory functions."""

    def test_fx_weekday(self) -> None:
        """fx_weekday_schedule should create a valid schedule."""
        from eigencapital.core.market_schedule import SessionType, fx_weekday_schedule

        schedule = fx_weekday_schedule("EURUSD")
        assert schedule.instrument == "EURUSD"
        assert schedule.session_type == SessionType.WEEKDAY
        assert schedule.trading_days_per_year == 252

    def test_crypto_24_7(self) -> None:
        """crypto_24_7_schedule should create a valid schedule."""
        from eigencapital.core.market_schedule import SessionType, crypto_24_7_schedule

        schedule = crypto_24_7_schedule("BTCUSD")
        assert schedule.instrument == "BTCUSD"
        assert schedule.session_type == SessionType.CONTINUOUS_24_7
        assert schedule.trading_days_per_year == 365
        assert len(schedule.maintenance_windows) > 0

    def test_get_default_schedule(self) -> None:
        """get_default_schedule should return correct type per asset class."""
        from eigencapital.core.market_schedule import SessionType, get_default_schedule

        fx = get_default_schedule("EURUSD", "forex")
        assert fx.session_type == SessionType.WEEKDAY

        crypto = get_default_schedule("BTCUSD", "crypto")
        assert crypto.session_type == SessionType.CONTINUOUS_24_7

        metals = get_default_schedule("XAUUSD", "metals")
        assert metals.session_type == SessionType.WEEKDAY


class TestMarketState:
    """Verify MarketState 4 independent states."""

    def test_tradable(self) -> None:
        """is_tradable should require all 4 states favorable."""
        from eigencapital.core.market_schedule import (
            BrokerAvailability,
            DataAvailability,
            MarketAvailability,
            MarketState,
            StrategyEligibility,
        )

        state = MarketState(
            instrument="EURUSD",
            market=MarketAvailability.OPEN,
            data=DataAvailability.FRESH,
            broker=BrokerAvailability.CONNECTED,
            strategy=StrategyEligibility.ELIGIBLE,
            authorization="TRADING_AUTHORIZED",
        )
        assert state.is_tradable is True

    def test_not_tradable_market_closed(self) -> None:
        """is_tradable should be False when market is closed."""
        from eigencapital.core.market_schedule import (
            BrokerAvailability,
            DataAvailability,
            MarketAvailability,
            MarketState,
            StrategyEligibility,
        )

        state = MarketState(
            instrument="EURUSD",
            market=MarketAvailability.CLOSED,
            data=DataAvailability.FRESH,
            broker=BrokerAvailability.CONNECTED,
            strategy=StrategyEligibility.ELIGIBLE,
            authorization="TRADING_AUTHORIZED",
        )
        assert state.is_tradable is False
        assert state.overall_status == "MARKET_CLOSED"

    def test_not_tradable_data_stale(self) -> None:
        """is_tradable should be False when data is stale."""
        from eigencapital.core.market_schedule import (
            BrokerAvailability,
            DataAvailability,
            MarketAvailability,
            MarketState,
            StrategyEligibility,
        )

        state = MarketState(
            instrument="BTCUSD",
            market=MarketAvailability.OPEN,
            data=DataAvailability.STALE,
            broker=BrokerAvailability.CONNECTED,
            strategy=StrategyEligibility.ELIGIBLE,
            authorization="TRADING_AUTHORIZED",
        )
        assert state.is_tradable is False
        assert state.overall_status == "DATA_UNAVAILABLE"

    def test_not_tradable_broker_disconnected(self) -> None:
        """is_tradable should be False when broker is disconnected."""
        from eigencapital.core.market_schedule import (
            BrokerAvailability,
            DataAvailability,
            MarketAvailability,
            MarketState,
            StrategyEligibility,
        )

        state = MarketState(
            instrument="EURUSD",
            market=MarketAvailability.OPEN,
            data=DataAvailability.FRESH,
            broker=BrokerAvailability.DISCONNECTED,
            strategy=StrategyEligibility.ELIGIBLE,
            authorization="TRADING_AUTHORIZED",
        )
        assert state.is_tradable is False
        assert state.overall_status == "BROKER_UNAVAILABLE"

    def test_not_tradable_strategy_suppressed(self) -> None:
        """is_tradable should be False when strategy is suppressed."""
        from eigencapital.core.market_schedule import (
            BrokerAvailability,
            DataAvailability,
            MarketAvailability,
            MarketState,
            StrategyEligibility,
        )

        state = MarketState(
            instrument="EURUSD",
            market=MarketAvailability.OPEN,
            data=DataAvailability.FRESH,
            broker=BrokerAvailability.CONNECTED,
            strategy=StrategyEligibility.SUPPRESSED,
            authorization="TRADING_AUTHORIZED",
        )
        assert state.is_tradable is False
        assert state.overall_status == "STRATEGY_SUPPRESSED"

    def test_to_dict(self) -> None:
        """MarketState should serialize to dict."""
        from eigencapital.core.market_schedule import (
            BrokerAvailability,
            DataAvailability,
            MarketAvailability,
            MarketState,
            StrategyEligibility,
        )

        state = MarketState(
            instrument="EURUSD",
            market=MarketAvailability.OPEN,
            data=DataAvailability.FRESH,
            broker=BrokerAvailability.CONNECTED,
            strategy=StrategyEligibility.ELIGIBLE,
            authorization="TRADING_AUTHORIZED",
        )
        d = state.to_dict()
        assert d["instrument"] == "EURUSD"
        assert d["market"] == "OPEN"
        assert d["is_tradable"] is True
        assert d["overall_status"] == "TRADABLE"


class TestParity:
    """Verify MarketSchedule produces same results as hardcoded weekday checks."""

    def test_fx_weekday_parity(self) -> None:
        """Weekday schedule should match explicit day-of-week checks."""
        from datetime import timedelta

        from eigencapital.core.market_schedule import fx_weekday_schedule

        schedule = fx_weekday_schedule("EURUSD")

        # Start from Monday Aug 31
        start = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
        for day in range(7):
            dt = start + timedelta(days=day)
            is_open = schedule.is_market_open(dt)

            if day < 5:  # Mon-Fri
                assert is_open is True, f"Expected open on {dt.strftime('%A')}"
            else:  # Sat-Sun
                assert is_open is False, f"Expected closed on {dt.strftime('%A')}"

    def test_crypto_weekend_parity(self) -> None:
        """Crypto 24/7 should be open on weekends outside maintenance."""
        from eigencapital.core.market_schedule import crypto_24_7_schedule

        schedule = crypto_24_7_schedule("BTCUSD")

        # Saturday outside maintenance
        sat_noon = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
        assert schedule.is_market_open(sat_noon) is True

        # Sunday
        sun_noon = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
        assert schedule.is_market_open(sun_noon) is True

        # Saturday during maintenance
        sat_maint = datetime(2026, 8, 29, 4, 15, tzinfo=UTC)
        assert schedule.is_market_open(sat_maint) is False
