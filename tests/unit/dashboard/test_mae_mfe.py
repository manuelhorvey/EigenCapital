"""MAE/MFE Tracking Tests — verify per-position excursion tracking.

Tests:
1. RiskObserver tracks MAE/MFE per position
2. MAE/MFE updates correctly for LONG positions
3. MAE/MFE updates correctly for SHORT positions
4. Excursion state persists to disk
5. Closed positions are cleaned up
6. Dashboard reads MAE/MFE correctly
7. Edge cases (zero prices, missing tickets)
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Path:
    """Create a temporary state directory for excursion files."""
    state_dir = tmp_path / "reports" / "r4_loop"
    state_dir.mkdir(parents=True)
    return state_dir


class TestMAEMFETracking:
    """Verify per-position MAE/MFE tracking in RiskObserver."""

    def _make_observer(self, state_dir: Path) -> "RiskObserver":
        """Create a RiskObserver with temp excursion path."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        observer._excursion_path = state_dir / "position_excursion.json"
        observer._excursions = observer._load_excursions()
        return observer

    def test_new_position_tracked(self) -> None:
        """New position should be initialized with zero MAE/MFE."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        positions = [
            {
                "ticket": 12345,
                "symbol": "XAUUSD",
                "type": 0,  # BUY
                "price_open": 2500.0,
                "price_current": 2510.0,
                "sl": 2480.0,
                "volume": 0.01,
                "profit": 10.0,
            }
        ]

        observer._update_excursions(positions)
        exc = observer.get_excursion_for_ticket(12345)

        assert exc is not None
        assert exc["ticket"] == "12345"
        assert exc["symbol"] == "XAUUSD"
        assert exc["direction"] == "BUY"
        assert exc["entry_price"] == 2500.0
        assert exc["current_price"] == 2510.0
        # MFE = (2510 - 2500) / 2500 = 0.004 (0.4% favorable from entry)
        assert exc["mfe_pct"] == pytest.approx(0.004, abs=1e-6)
        # MAE = 0 (no adverse movement)
        assert exc["mae_pct"] == 0.0

    def test_long_position_mfe_tracking(self) -> None:
        """LONG position MFE should track highest favorable price."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        base = {
            "ticket": 100,
            "symbol": "XAUUSD",
            "type": 0,
            "price_open": 2500.0,
            "sl": 2480.0,
            "volume": 0.01,
            "profit": 0.0,
        }

        # Price rises to 2525 (1% favorable)
        p1 = {**base, "price_current": 2525.0, "profit": 25.0}
        observer._update_excursions([p1])
        exc = observer.get_excursion_for_ticket(100)
        assert exc is not None
        assert exc["mfe_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["highest_price"] == 2525.0

        # Price drops to 2515 (still favorable, but less)
        p2 = {**base, "price_current": 2515.0, "profit": 15.0}
        observer._update_excursions([p2])
        exc = observer.get_excursion_for_ticket(100)
        assert exc is not None
        # MFE should still be the peak (2525), not current (2515)
        assert exc["mfe_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["highest_price"] == 2525.0

    def test_long_position_mae_tracking(self) -> None:
        """LONG position MAE should track lowest adverse price."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        base = {
            "ticket": 200,
            "symbol": "XAUUSD",
            "type": 0,
            "price_open": 2500.0,
            "sl": 2480.0,
            "volume": 0.01,
            "profit": 0.0,
        }

        # Price drops to 2475 (1% adverse)
        p1 = {**base, "price_current": 2475.0, "profit": -25.0}
        observer._update_excursions([p1])
        exc = observer.get_excursion_for_ticket(200)
        assert exc is not None
        assert exc["mae_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["lowest_price"] == 2475.0

        # Price recovers to 2490 (still adverse, but less)
        p2 = {**base, "price_current": 2490.0, "profit": -10.0}
        observer._update_excursions([p2])
        exc = observer.get_excursion_for_ticket(200)
        assert exc is not None
        # MAE should still be the trough (2475), not current (2490)
        assert exc["mae_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["lowest_price"] == 2475.0

    def test_short_position_mfe_tracking(self) -> None:
        """SHORT position MFE should track lowest favorable price."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        base = {
            "ticket": 300,
            "symbol": "XAUUSD",
            "type": 1,  # SELL
            "price_open": 2500.0,
            "sl": 2520.0,
            "volume": 0.01,
            "profit": 0.0,
        }

        # Price drops to 2475 (1% favorable for short)
        p1 = {**base, "price_current": 2475.0, "profit": 25.0}
        observer._update_excursions([p1])
        exc = observer.get_excursion_for_ticket(300)
        assert exc is not None
        assert exc["direction"] == "SELL"
        assert exc["mfe_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["lowest_price"] == 2475.0  # MFE for short = lowest price

    def test_short_position_mae_tracking(self) -> None:
        """SHORT position MAE should track highest adverse price."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        base = {
            "ticket": 400,
            "symbol": "XAUUSD",
            "type": 1,  # SELL
            "price_open": 2500.0,
            "sl": 2520.0,
            "volume": 0.01,
            "profit": 0.0,
        }

        # Price rises to 2525 (1% adverse for short)
        p1 = {**base, "price_current": 2525.0, "profit": -25.0}
        observer._update_excursions([p1])
        exc = observer.get_excursion_for_ticket(400)
        assert exc is not None
        assert exc["mae_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["highest_price"] == 2525.0  # MAE for short = highest price

    def test_closed_position_removed(self) -> None:
        """Positions no longer in the list should be cleaned up."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        positions = [
            {
                "ticket": 500,
                "symbol": "XAUUSD",
                "type": 0,
                "price_open": 2500.0,
                "price_current": 2510.0,
                "sl": 2480.0,
                "volume": 0.01,
                "profit": 10.0,
            }
        ]

        observer._update_excursions(positions)
        assert observer.get_excursion_for_ticket(500) is not None

        # Position closed — empty list
        observer._update_excursions([])
        assert observer.get_excursion_for_ticket(500) is None

    def test_excursion_persists_to_disk(self) -> None:
        """Excursion state should persist to JSON file."""
        from eigencapital.live.risk_observation import RiskObserver

        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            excursion_path = state_dir / "position_excursion.json"

            # First observer — create and persist
            obs1 = RiskObserver()
            obs1._excursion_path = excursion_path
            obs1._excursions = obs1._load_excursions()

            positions = [
                {
                    "ticket": 600,
                    "symbol": "XAUUSD",
                    "type": 0,
                    "price_open": 2500.0,
                    "price_current": 2525.0,
                    "sl": 2480.0,
                    "volume": 0.01,
                    "profit": 25.0,
                }
            ]
            obs1._update_excursions(positions)

            assert excursion_path.exists()
            data = json.loads(excursion_path.read_text())
            assert "600" in data
            assert data["600"]["mfe_pct"] == pytest.approx(0.01, abs=1e-6)

            # Second observer — load from disk
            obs2 = RiskObserver()
            obs2._excursion_path = excursion_path
            obs2._excursions = obs2._load_excursions()

            exc = obs2.get_excursion_for_ticket(600)
            assert exc is not None
            assert exc["mfe_pct"] == pytest.approx(0.01, abs=1e-6)

    def test_get_position_excursions(self) -> None:
        """get_position_excursions should return all tracked positions."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        positions = [
            {
                "ticket": 700,
                "symbol": "XAUUSD",
                "type": 0,
                "price_open": 2500.0,
                "price_current": 2510.0,
                "sl": 2480.0,
                "volume": 0.01,
                "profit": 10.0,
            },
            {
                "ticket": 701,
                "symbol": "EURUSD",
                "type": 1,
                "price_open": 1.1000,
                "price_current": 1.0980,
                "sl": 1.1020,
                "volume": 0.1,
                "profit": 20.0,
            },
        ]

        observer._update_excursions(positions)
        excursions = observer.get_position_excursions()

        assert len(excursions) == 2
        assert "700" in excursions
        assert "701" in excursions
        assert excursions["700"]["symbol"] == "XAUUSD"
        assert excursions["701"]["symbol"] == "EURUSD"

    def test_zero_entry_price_skipped(self) -> None:
        """Positions with zero entry price should be skipped."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        positions = [
            {
                "ticket": 800,
                "symbol": "XAUUSD",
                "type": 0,
                "price_open": 0.0,
                "price_current": 2510.0,
                "sl": 2480.0,
                "volume": 0.01,
                "profit": 0.0,
            }
        ]

        observer._update_excursions(positions)
        assert observer.get_excursion_for_ticket(800) is None

    def test_zero_current_price_skipped(self) -> None:
        """Positions with zero current price should be skipped."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        positions = [
            {
                "ticket": 900,
                "symbol": "XAUUSD",
                "type": 0,
                "price_open": 2500.0,
                "price_current": 0.0,
                "sl": 2480.0,
                "volume": 0.01,
                "profit": 0.0,
            }
        ]

        observer._update_excursions(positions)
        assert observer.get_excursion_for_ticket(900) is None

    def test_mae_mfe_independent(self) -> None:
        """MAE and MFE should track independently — a position can have both."""
        from eigencapital.live.risk_observation import RiskObserver

        observer = RiskObserver()
        base = {
            "ticket": 1000,
            "symbol": "XAUUSD",
            "type": 0,
            "price_open": 2500.0,
            "sl": 2480.0,
            "volume": 0.01,
            "profit": 0.0,
        }

        # First: price drops to 2475 (1% MAE)
        p1 = {**base, "price_current": 2475.0, "profit": -25.0}
        observer._update_excursions([p1])

        # Then: price rises to 2525 (1% MFE)
        p2 = {**base, "price_current": 2525.0, "profit": 25.0}
        observer._update_excursions([p2])

        exc = observer.get_excursion_for_ticket(1000)
        assert exc is not None
        # Both MAE and MFE should be non-zero
        assert exc["mae_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["mfe_pct"] == pytest.approx(0.01, abs=1e-6)
        assert exc["lowest_price"] == 2475.0
        assert exc["highest_price"] == 2525.0


class TestDashboardMAEMFE:
    """Verify dashboard reads MAE/MFE from excursion data."""

    def test_dashboard_reads_excursion_data(self) -> None:
        """Dashboard state service should read MAE/MFE from persisted file."""
        from eigencapital.dashboard.services.dashboard_state import DashboardStateService

        with tempfile.TemporaryDirectory() as tmpdir:
            loop_dir = Path(tmpdir) / "reports" / "r4_loop"
            loop_dir.mkdir(parents=True)

            # Write excursion data
            excursion_data = {
                "12345": {
                    "ticket": "12345",
                    "symbol": "XAUUSD",
                    "direction": "BUY",
                    "entry_price": 2500.0,
                    "current_price": 2510.0,
                    "mae_pct": 0.005,
                    "mfe_pct": 0.01,
                    "highest_price": 2525.0,
                    "lowest_price": 2487.5,
                }
            }
            excursion_path = loop_dir / "position_excursion.json"
            excursion_path.write_text(json.dumps(excursion_data))

            # Read via dashboard state service
            service = DashboardStateService()
            service._loop_dir = loop_dir
            data = service._read_json(excursion_path)

            assert data is not None
            assert "12345" in data
            assert data["12345"]["mae_pct"] == 0.005
            assert data["12345"]["mfe_pct"] == 0.01
