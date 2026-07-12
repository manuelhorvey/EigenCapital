"""
Deterministic replay tests: given known signal + price sequences,
assert that PnL, position state, and trade log are fully deterministic.
"""
import pandas as pd
import pytest

from paper_trading.engine import AssetEngine
from paper_trading.entry.decision import PositionIntent
from paper_trading.state_store import _SKIP_JOURNAL
from features.registry import FEATURE_REGISTRY
from paper_trading.config_manager import get_config
from paper_trading.portfolio_builder import build_paper_portfolio


class TestUpdatePnlDeterministic:
    """
    Feed known price sequences with known signal directions.
    Assert that PnL is accurately computed and trades are correctly recorded.
    """

    @pytest.fixture
    def engine(self):
        pf = build_paper_portfolio(get_config().halt)
        # Use first available asset from config portfolio
        asset_name = list(pf.keys())[0]
        spec = pf[asset_name]
        contract = FEATURE_REGISTRY[spec["ticker"]]
        return AssetEngine(
            spec["ticker"], asset_name, contract, spec["alloc"],
            journal_path=_SKIP_JOURNAL,
        )

    def _make_signal_data(self, prices, signals):
        return pd.DataFrame({
            "close": prices,
            "signal": signals,
            "position_size": [1.0] * len(prices),
        }, index=pd.RangeIndex(len(prices)))

    def test_monotonic_long_profits(self, engine):
        """Prices go up, signal is long -> positive PnL."""
        prices = [100, 101, 102, 103, 104]
        signals = [2, 2, 2, 2, 2]
        engine.signal_data = self._make_signal_data(prices, signals)
        engine.update_pnl()  # first call seeds _initial_settlement_done
        engine.update_pnl()  # second call applies signal PnL
        assert engine.current_value > engine.initial_capital
        assert len(engine.trades) == 1

    def test_long_then_sell(self, engine):
        """Long then sell in a rising market -> sell trade book negative return."""
        prices = [100, 102, 104, 106, 108]
        signals = [2, 2, 2, 0, 0]
        engine.signal_data = self._make_signal_data(prices, signals)
        engine.update_pnl()  # first call seeds _initial_settlement_done
        engine.update_pnl()  # second call applies signal PnL
        assert len(engine.trades) == 1
        assert engine.trades[0]["direction"] == -1

    def test_flat_signals_no_pnl(self, engine):
        """All flat signals -> no PnL change."""
        prices = [100, 101, 102, 103, 104]
        signals = [1, 1, 1, 1, 1]
        engine.signal_data = self._make_signal_data(prices, signals)
        engine.update_pnl()
        assert engine.current_value == engine.initial_capital
        assert len(engine.trades) == 0

    def test_idempotent_update_pnl(self, engine):
        """Calling update_pnl twice with same data does not double-count."""
        prices = [100, 105, 110]
        signals = [2, 2, 2]
        engine.signal_data = self._make_signal_data(prices, signals)
        engine.update_pnl()  # seeds _initial_settlement_done
        engine.update_pnl()  # applies signal PnL
        cv_after_settle = engine.current_value
        engine.update_pnl()  # should be idempotent (same-day guard)
        assert engine.current_value == cv_after_settle


class TestPositionManagerDeterministic:
    """
    Feed known price paths into PositionManager.
    Assert exact PnL values and trade entries.
    """

    def test_long_position_exact_pnl(self):
        from paper_trading.position.manager import PositionManager
        pm = PositionManager(initial_capital=10000, position_size=1.0)

        intent = PositionIntent(
            side="long", entry_price=100.0, entry_date="2026-06-01",
            stop_loss=90.0, take_profit=110.0, vol=0.05,
        )
        pm.open(intent)
        trade = pm.close(exit_price=110.0, exit_date="2026-06-10", reason="tp")
        assert trade is not None
        assert trade["return"] == pytest.approx(0.10)
        assert trade["pnl"] == pytest.approx(1000.0)

    def test_short_position_exact_pnl(self):
        from paper_trading.position.manager import PositionManager
        pm = PositionManager(initial_capital=10000, position_size=1.0)

        intent = PositionIntent(
            side="short", entry_price=100.0, entry_date="2026-06-01",
            stop_loss=110.0, take_profit=90.0, vol=0.05,
        )
        pm.open(intent)
        trade = pm.close(exit_price=90.0, exit_date="2026-06-10", reason="tp")
        assert trade is not None
        assert trade["return"] == pytest.approx(100.0 / 90.0 - 1)
        assert trade["pnl"] == pytest.approx(10000 * (100.0 / 90.0 - 1))

    def test_sl_hit_exact_pnl(self):
        from paper_trading.position.manager import PositionManager
        pm = PositionManager(initial_capital=10000, position_size=1.0)

        intent = PositionIntent(
            side="long", entry_price=100.0, entry_date="2026-06-01",
            stop_loss=95.0, take_profit=110.0, vol=0.025,
        )
        pm.open(intent)
        trade = pm.close(exit_price=95.0, exit_date="2026-06-05", reason="sl")
        assert trade is not None
        assert trade["return"] == pytest.approx(-0.05)
        assert trade["pnl"] == pytest.approx(-500.0)

    def test_price_path_with_multiple_checks(self):
        """
        Simulate daily price checks on an open position:
        no hit until the price crosses the TP threshold.
        """
        from paper_trading.position.manager import PositionManager
        pm = PositionManager(initial_capital=10000, position_size=1.0)

        intent = PositionIntent(
            side="long", entry_price=100.0, entry_date="2026-06-01",
            stop_loss=95.0, take_profit=110.0, vol=0.025,
        )
        pm.open(intent)
        prices = [101, 103, 105, 108, 112]
        hits = []
        for price in prices:
            hit = pm.check_sl_tp(price)
            hits.append(hit is not None)
        assert hits[:4] == [False, False, False, False]
        assert hits[4] is True

    def test_stop_loss_chain(self):
        """
        Short position: price keeps rising until SL hit.
        """
        from paper_trading.position.manager import PositionManager
        pm = PositionManager(initial_capital=10000, position_size=1.0)

        intent = PositionIntent(
            side="short", entry_price=100.0, entry_date="2026-06-01",
            stop_loss=105.0, take_profit=95.0, vol=0.025,
        )
        pm.open(intent)
        prices = [101, 102, 103, 104, 106]
        for i, price in enumerate(prices):
            hit = pm.check_sl_tp(price)
            if hit:
                trade = pm.close(hit[1], f"2026-06-0{i+1}", hit[0])
                assert trade is not None
                assert trade["reason"] == "sl"
                break
        assert not pm.has_position()


class TestStateStoreDeterministic:
    """StateStore round-trip preserves exact data."""

    def test_snapshot_roundtrip_exact(self):
        import tempfile
        from paper_trading.state_store import StateStore, EngineSnapshot

        with tempfile.TemporaryDirectory() as td:
            store = StateStore(td)
            snap = EngineSnapshot(
                timestamp="2026-06-01T12:00:00",
                portfolio={"total_value": 105000.0, "total_return": 5.0},
                assets={
                    "BTC": {"metrics": {"current_value": 21000}},
                    "NZDJPY": {"metrics": {"current_value": 15750}},
                },
                engine_status={"initialized": True},
            )
            store.save_snapshot(snap)
            loaded = store.load_snapshot()
            assert loaded is not None
            assert loaded.portfolio["total_value"] == 105000.0
            assert loaded.assets["BTC"]["metrics"]["current_value"] == 21000
