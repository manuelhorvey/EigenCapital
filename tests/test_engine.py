import pytest
from paper_trading.engine import (
    flatten, norm_index, CONFIG, HALT,
    PAPER_PORTFOLIO,
    AssetEngine, _SKIP_JOURNAL,
)
from features.registry import FEATURE_REGISTRY


class TestHelpers:
    def test_flatten_single_level(self):
        import pandas as pd
        df = pd.DataFrame({"Close": [100, 101]})
        result = flatten(df)
        assert "close" in result.columns
        assert "Close" not in result.columns

    def test_flatten_multi_index(self):
        import pandas as pd
        arrays = [["Close", "High"], ["XLF", "XLF"]]
        cols = pd.MultiIndex.from_arrays(arrays, names=["Price", "Ticker"])
        df = pd.DataFrame([[100, 101], [102, 103]], columns=cols)
        result = flatten(df)
        assert "close" in result.columns

    def test_norm_index_already_utc(self):
        import pandas as pd
        df = pd.DataFrame({"close": [100]}, index=pd.DatetimeIndex(["2020-01-01"], tz="UTC"))
        result = norm_index(df)
        assert result.index.tz is not None

    def test_norm_index_naive(self):
        import pandas as pd
        df = pd.DataFrame({"close": [100]}, index=pd.DatetimeIndex(["2020-01-01"]))
        result = norm_index(df)
        assert result.index.tz is not None


class TestConfig:
    def test_has_expected_keys(self):
        assert "capital" in CONFIG
        assert "position_size" in CONFIG
        assert "rebalance" in CONFIG
        assert "retrain_freq" in CONFIG
        assert "retrain_window" in CONFIG

    def test_halt_has_expected_keys(self):
        assert "drawdown" in HALT
        assert "monthly_pf" in HALT
        assert "signal_drought" in HALT
        assert "prob_drift" in HALT

    def test_xlf_features(self):
        features = FEATURE_REGISTRY["BTC-USD"].features
        assert len(features) == 10
        assert "rate_diff" in features
        assert "vix_delta_5" in features
        assert "btc_mom_10" in features

    def test_btc_features(self):
        features = FEATURE_REGISTRY["BTC-USD"].features
        assert len(features) == 10
        assert "rate_diff" in features
        assert "vix_delta_5" in features
        assert "btc_vs_spy_21" in features

    def test_paper_portfolio_structure(self):
        assert "BTC" in PAPER_PORTFOLIO
        assert "NZDJPY" in PAPER_PORTFOLIO
        assert "CADJPY" in PAPER_PORTFOLIO
        assert "USDCAD" in PAPER_PORTFOLIO
        assert "GC" in PAPER_PORTFOLIO
        assert "EURAUD" in PAPER_PORTFOLIO
        assert "AUDJPY" in PAPER_PORTFOLIO
        assert "GBPJPY" in PAPER_PORTFOLIO
        assert "USDJPY" in PAPER_PORTFOLIO
        assert "USDCHF" in PAPER_PORTFOLIO
        assert "GBPUSD" in PAPER_PORTFOLIO
        assert "XLF" not in PAPER_PORTFOLIO
        assert sum(v['alloc'] for v in PAPER_PORTFOLIO.values()) <= 1.0


class TestUpdatePnl:
    @pytest.fixture
    def engine(self):
        return AssetEngine("BTC-USD", "BTC", FEATURE_REGISTRY["BTC-USD"], PAPER_PORTFOLIO["BTC"]["alloc"],
                           journal_path=_SKIP_JOURNAL)

    @pytest.fixture
    def signal_data(self):
        import pandas as pd
        import numpy as np
        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(5) * 0.5)
        return pd.DataFrame({
            "close": prices,
            "signal": [2, 2, 0, 0, 2],
            "position_size": [1.0] * 5,
        }, index=dates)

    def test_returns_when_no_signal_data(self, engine):
        engine.signal_data = None
        engine.update_pnl()
        assert engine.current_value == engine.initial_capital

    def test_returns_when_fewer_than_two_bars(self, engine):
        import pandas as pd
        engine.signal_data = pd.DataFrame({"close": [100]}, index=pd.DatetimeIndex(["2026-05-01"]))
        engine.update_pnl()
        assert engine.current_value == engine.initial_capital

    def test_returns_when_last_bar_already_processed(self, engine, signal_data):
        engine.signal_data = signal_data
        engine.trades = [{"date": str(signal_data.index[-1].date())}]
        engine.update_pnl()
        assert engine.current_value == engine.initial_capital

    def test_signal_based_pnl_when_no_position(self, engine, signal_data):
        engine.signal_data = signal_data
        engine.update_pnl()
        assert engine.current_value != engine.initial_capital

    def test_position_open_skips_signal_pnl(self, engine, signal_data):
        engine.signal_data = signal_data
        engine.position = {
            "side": "long", "entry": 100.0, "sl": 95.0, "tp": 110.0,
            "entry_date": "2026-05-01", "vol": 0.02,
        }
        current_val_before = engine.current_value
        engine.update_pnl()
        assert engine.current_value == current_val_before

    def test_sl_hit_closes_position(self, engine, signal_data):
        import pandas as pd
        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 102.0, 98.0, 96.0, 94.0]
        engine.signal_data = pd.DataFrame({
            "close": prices,
            "signal": [2] * 5,
            "position_size": [1.0] * 5,
        }, index=dates)
        engine.position = {
            "side": "long", "entry": 100.0, "sl": 95.0, "tp": 110.0,
            "entry_date": "2026-05-01", "vol": 0.02,
        }
        engine.update_pnl()
        assert engine.position is None
        assert len(engine.trade_log) == 1

    def test_tp_hit_closes_position(self, engine, signal_data):
        import pandas as pd
        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 105.0, 108.0, 112.0, 115.0]
        engine.signal_data = pd.DataFrame({
            "close": prices,
            "signal": [2] * 5,
            "position_size": [1.0] * 5,
        }, index=dates)
        engine.position = {
            "side": "long", "entry": 100.0, "sl": 95.0, "tp": 110.0,
            "entry_date": "2026-05-01", "vol": 0.02,
        }
        engine.update_pnl()
        assert engine.position is None
        assert engine.current_value > engine.initial_capital

    def test_short_sl_hit_closes_short_position(self, engine):
        import pandas as pd
        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 102.0, 105.0, 108.0, 110.0]
        engine.signal_data = pd.DataFrame({
            "close": prices,
            "signal": [0] * 5,
            "position_size": [1.0] * 5,
        }, index=dates)
        engine.position = {
            "side": "short", "entry": 100.0, "sl": 105.0, "tp": 95.0,
            "entry_date": "2026-05-01", "vol": 0.02,
        }
        engine.update_pnl()
        assert engine.position is None

    def test_short_tp_hit_closes_short_position(self, engine):
        import pandas as pd
        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 98.0, 96.0, 94.0, 92.0]
        engine.signal_data = pd.DataFrame({
            "close": prices,
            "signal": [0] * 5,
            "position_size": [1.0] * 5,
        }, index=dates)
        engine.position = {
            "side": "short", "entry": 100.0, "sl": 105.0, "tp": 95.0,
            "entry_date": "2026-05-01", "vol": 0.02,
        }
        engine.update_pnl()
        assert engine.position is None
        assert engine.current_value > engine.initial_capital
