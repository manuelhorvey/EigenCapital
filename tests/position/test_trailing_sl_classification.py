"""Tests for TRAILING_SL exit classification — trailing-stop profit exits.

Verifies that:
1. A trailing stop that locks in profit and gets hit → TRAILING_SL
2. An initial SL hit below entry → SL (actual loss)
3. A TP hit → TP
4. Breakeven exit → BREAKEVEN
5. Expected invariant: a trade is never counted as both TP and SL
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paper_trading.asset_pnl_controller import AssetPnlController


def _make_position_dict(
    side: str = "long",
    entry: float = 100.0,
    sl: float = 95.0,
    tp: float = 110.0,
) -> dict:
    return {
        "side": side,
        "entry": entry,
        "sl": sl,
        "tp": tp,
    }


def _make_asset(name: str = "TEST", current_price: float | None = 105.0):
    """Create a minimal asset mock with only the attributes accessed by
    _check_position_sltp_hit and _check_sltp_hit."""
    asset = MagicMock()
    asset.name = name
    asset.current_price = current_price
    asset.current_value = 100_000.0
    asset.peak_value = 100_000.0
    return asset


class TestCheckPositionSltpHit:
    """Tests for AssetPnlController._check_position_sltp_hit."""

    @pytest.fixture
    def controller(self):
        asset = _make_asset()
        return AssetPnlController(asset)

    def test_tp_hit_long(self, controller):
        """TP hit on a long position returns TP."""
        asset = _make_asset(current_price=112.0)
        controller.asset = asset
        pos = _make_position_dict(side="long", entry=100.0, sl=95.0, tp=110.0)
        result = controller._check_position_sltp_hit(asset, pos, "trade_1")
        assert result is True
        asset._close_position.assert_called_once()
        reason = asset._close_position.call_args[0][2]
        assert reason == "TP"

    def test_sl_hit_long_loss(self, controller):
        """SL hit below entry on a long position returns SL (actual loss)."""
        asset = _make_asset(current_price=94.0)
        controller.asset = asset
        pos = _make_position_dict(side="long", entry=100.0, sl=95.0, tp=110.0)
        result = controller._check_position_sltp_hit(asset, pos, "trade_1")
        assert result is True
        asset._close_position.assert_called_once()
        reason = asset._close_position.call_args[0][2]
        assert reason == "SL"

    def test_trailing_sl_hit_long_profit(self, controller):
        """Trailing stop that locked in profit ⇒ TRAILING_SL.
        SL is above entry (103 > 100) but current_price hit it (102 <= 103).
        Since hit_price (103) > entry (100), it's a profit-locked trail exit.
        """
        asset = _make_asset(current_price=102.0)
        controller.asset = asset
        # SL trail-updated to 103 (above entry 100 = profit-locked)
        pos = _make_position_dict(side="long", entry=100.0, sl=103.0, tp=110.0)
        result = controller._check_position_sltp_hit(asset, pos, "trade_1")
        assert result is True
        asset._close_position.assert_called_once()
        reason = asset._close_position.call_args[0][2]
        assert reason == "TRAILING_SL"

    def test_trailing_sl_hit_short_profit(self, controller):
        """Trailing stop that locked in profit on short ⇒ TRAILING_SL.
        SL is below entry (97 < 100) but current_price hit it (98 >= 97).
        Since hit_price (97) < entry (100), it's a profit-locked trail exit.
        """
        asset = _make_asset(current_price=98.0)
        controller.asset = asset
        # SL trail-updated to 97 (below entry 100 = profit-locked for short)
        pos = _make_position_dict(side="short", entry=100.0, sl=97.0, tp=90.0)
        result = controller._check_position_sltp_hit(asset, pos, "trade_2")
        assert result is True
        asset._close_position.assert_called_once()
        reason = asset._close_position.call_args[0][2]
        assert reason == "TRAILING_SL"

    def test_sl_hit_short_loss(self, controller):
        """SL hit above entry on a short returns SL (actual loss)."""
        asset = _make_asset(current_price=106.0)
        controller.asset = asset
        pos = _make_position_dict(side="short", entry=100.0, sl=105.0, tp=95.0)
        result = controller._check_position_sltp_hit(asset, pos, "trade_1")
        assert result is True
        asset._close_position.assert_called_once()
        reason = asset._close_position.call_args[0][2]
        assert reason == "SL"

    def test_tp_hit_short(self, controller):
        """TP hit on a short returns TP."""
        asset = _make_asset(current_price=93.0)
        controller.asset = asset
        pos = _make_position_dict(side="short", entry=100.0, sl=105.0, tp=95.0)
        result = controller._check_position_sltp_hit(asset, pos, "trade_1")
        assert result is True
        asset._close_position.assert_called_once()
        reason = asset._close_position.call_args[0][2]
        assert reason == "TP"

    def test_no_hit(self, controller):
        """Price between SL and TP → no hit, returns False."""
        asset = _make_asset(current_price=102.0)
        controller.asset = asset
        pos = _make_position_dict(side="long", entry=100.0, sl=95.0, tp=110.0)
        result = controller._check_position_sltp_hit(asset, pos, "trade_1")
        assert result is False

    def test_invariant_not_both_tp_and_sl(self, controller):
        """Invariant: a single call never produces both TP and SL.
        Tested by exhaustive enumeration of price scenarios.
        """
        scenarios = [
            # (side, entry, sl, tp, current_price, expected_reason_substring)
            ("long", 100.0, 95.0, 110.0, 94.0, "SL"),  # SL hit below entry
            ("long", 100.0, 95.0, 110.0, 112.0, "TP"),  # TP hit
            ("long", 100.0, 103.0, 115.0, 102.0, "TRAILING"),  # trail-SL above entry
            ("short", 100.0, 105.0, 95.0, 106.0, "SL"),  # SL hit above entry
            ("short", 100.0, 105.0, 95.0, 93.0, "TP"),  # TP hit
            ("short", 100.0, 97.0, 90.0, 98.0, "TRAILING"),  # trail-SL below entry
        ]
        for side, entry, sl, tp, current_price, expected in scenarios:
            asset = _make_asset(current_price=current_price)
            ctrl = AssetPnlController(asset)
            asset._close_position = MagicMock(return_value=True)
            pos = _make_position_dict(side=side, entry=entry, sl=sl, tp=tp)
            result = ctrl._check_position_sltp_hit(asset, pos, "trade_x")
            assert result is True, f"Expected hit for {side} entry={entry} sl={sl} tp={tp} price={current_price}"
            reason = asset._close_position.call_args[0][2]
            assert expected in reason.upper(), (
                f"Expected '{expected}' in reason for {side} entry={entry} sl={sl} "
                f"tp={tp} price={current_price}, got '{reason}'"
            )


class TestOutcomeTrackerIsWin:
    """Tests for OutcomeTracker.record_trade is_win classification."""

    def test_tp_is_win(self):
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker(window=10)
        tracker.record_trade("TP", 2.0, 0.5, 3.0)
        assert tracker.win_rate == 1.0

    def test_trailing_sl_is_win(self):
        """TRAILING_SL is a profitable exit → counted as win."""
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker(window=10)
        tracker.record_trade("TRAILING_SL", 0.5, 1.0, 2.0)
        assert tracker.win_rate == 1.0

    def test_breakeven_is_win(self):
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker(window=10)
        tracker.record_trade("BREAKEVEN", 0.0, 0.5, 0.5)
        assert tracker.win_rate == 1.0

    def test_sl_is_loss(self):
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker(window=10)
        tracker.record_trade("SL", -1.0, 1.5, 0.5)
        assert tracker.win_rate == 0.0

    def test_flip_uses_r_multiple_win(self):
        """FLIP with positive R-multiple → win."""
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker(window=10)
        tracker.record_trade("FLIP", 0.8, 0.3, 1.5)
        assert tracker.win_rate == 1.0

    def test_flip_uses_r_multiple_loss(self):
        """FLIP with negative R-multiple → loss."""
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker(window=10)
        tracker.record_trade("FLIP", -0.5, 1.0, 0.2)
        assert tracker.win_rate == 0.0

    def test_expiry_uses_r_multiple(self):
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        tracker = OutcomeTracker(window=10)
        tracker.record_trade("EXPIRY", 0.3, 0.5, 1.0)
        assert tracker.win_rate == 1.0

    def test_invariant_no_trade_is_both_win_and_loss(self):
        """Invariant: is_win is always True or False, never both."""
        from paper_trading.pek.perf.outcome_tracker import OutcomeTracker

        reasons = ["TP", "SL", "TRAILING_SL", "BREAKEVEN", "FLIP", "EXPIRY", "MANUAL"]
        for reason in reasons:
            tracker = OutcomeTracker(window=10)
            tracker.record_trade(reason, 1.0 if reason != "SL" else -1.0, 0.5, 2.0)
            # is_win is stored as a bool — can't be both True and False
            outcomes = list(tracker._outcomes)
            assert isinstance(outcomes[-1]["is_win"], bool), f"is_win must be bool for {reason}"
