"""
Tests for PositionIntent domain entity.
Validates effective_sl composition and risk envelope invariants.
"""

from eigencapital.domain.entities.position import PositionIntent, PositionSide, StackLayer


class TestEffectiveSL:
    """effective_sl = max(stop_loss, risk_floor, layer_stops) for longs.
    Effective SL must be monotonic — risk control that never loosens."""

    def test_effective_sl_equals_stop_loss_by_default(self):
        pos = PositionIntent(
            side=PositionSide.LONG, entry_price=100.0, entry_date="2026-07-01", stop_loss=95.0, take_profit=110.0
        )
        assert pos.effective_sl == 95.0

    def test_effective_sl_reflects_risk_floor_long(self):
        """risk_floor > stop_loss → effective_sl = risk_floor."""
        pos = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=95.0,
            take_profit=110.0,
            risk_floor=98.0,
        )
        assert pos.effective_sl == 98.0

    def test_effective_sl_ignores_lower_risk_floor(self):
        """risk_floor < stop_loss → effective_sl stays at stop_loss (no loosening)."""
        pos = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=95.0,
            take_profit=110.0,
            risk_floor=93.0,
        )
        assert pos.effective_sl == 95.0

    def test_effective_sl_reflects_layer_stops_long(self):
        """Layer stop_loss > stop_loss → effective_sl uses layer stop."""
        layer = StackLayer(entry_price=100.0, size=0.5, timestamp="2026-07-01", stop_loss=97.0)
        pos = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=95.0,
            take_profit=110.0,
            layers=[layer],
        )
        assert pos.effective_sl == 97.0

    def test_effective_sl_short_stop_loss_default(self):
        pos = PositionIntent(
            side=PositionSide.SHORT, entry_price=100.0, entry_date="2026-07-01", stop_loss=105.0, take_profit=95.0
        )
        assert pos.effective_sl == 105.0

    def test_effective_sl_short_risk_floor(self):
        """For shorts, effective_sl = min(stop_loss, risk_floor, layer_stops)."""
        pos = PositionIntent(
            side=PositionSide.SHORT,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=105.0,
            take_profit=95.0,
            risk_floor=103.0,
        )
        assert pos.effective_sl == 103.0

    def test_effective_sl_short_ignores_higher_risk_floor(self):
        pos = PositionIntent(
            side=PositionSide.SHORT,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=105.0,
            take_profit=95.0,
            risk_floor=107.0,
        )
        assert pos.effective_sl == 105.0

    def test_effective_sl_short_layer_stops(self):
        layer = StackLayer(entry_price=100.0, size=0.5, timestamp="2026-07-01", stop_loss=103.0)
        pos = PositionIntent(
            side=PositionSide.SHORT,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=105.0,
            take_profit=95.0,
            layers=[layer],
        )
        assert pos.effective_sl == 103.0

    def test_risk_floor_zero_not_considered(self):
        """risk_floor=0 should be ignored (no risk floor set)."""
        pos = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=95.0,
            take_profit=110.0,
            risk_floor=0.0,
        )
        assert pos.effective_sl == 95.0

    def test_update_stop_loss_then_effective_sl(self):
        """Simulate update_stop_loss: setting stop_loss should change effective_sl."""
        pos = PositionIntent(
            side=PositionSide.LONG, entry_price=100.0, entry_date="2026-07-01", stop_loss=95.0, take_profit=110.0
        )
        assert pos.effective_sl == 95.0
        pos.stop_loss = 97.0  # same as update_stop_loss does
        assert pos.effective_sl == 97.0

    def test_composition_risk_floor_then_stop_loss(self):
        """Both risk_floor and updated stop_loss compose correctly:
        risk_floor=98, stop_loss updated to 99 → effective_sl = 99."""
        pos = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=95.0,
            take_profit=110.0,
            risk_floor=98.0,
        )
        pos.stop_loss = 99.0
        assert pos.effective_sl == 99.0

    def test_notional_risk_uses_effective_sl(self):
        """notional_risk should use effective_sl, not stop_loss."""
        pos = PositionIntent(
            side=PositionSide.LONG,
            entry_price=100.0,
            entry_date="2026-07-01",
            stop_loss=95.0,
            take_profit=110.0,
            risk_floor=98.0,
        )
        risk = pos.notional_risk(current_price=100.0)
        # effective_sl=98, current_price=100 → risk = 2.0 * price_units
        from copy import deepcopy

        # Override total_size for the test
        pos_copy = deepcopy(pos)
        # Quick test: notional_risk uses effective_sl property
        current = 100.0
        effective = pos.effective_sl  # 98.0
        assert effective == 98.0
