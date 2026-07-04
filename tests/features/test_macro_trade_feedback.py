from paper_trading.asset_engine import AssetEngine


def test_macro_blend_trade_returns_agreement():
    engine = AssetEngine.__new__(AssetEngine)
    engine._entry_signal_dir = 1
    engine._last_macro_dir = 1
    engine._last_blend_dir = 0
    from unittest.mock import MagicMock
    engine._position = MagicMock()
    engine._position.macro_blend_trade_returns.return_value = (0.05, -0.05)
    macro_ret, blend_ret = engine._macro_blend_trade_returns(0.05)
    assert macro_ret == 0.05
    assert blend_ret == -0.05
