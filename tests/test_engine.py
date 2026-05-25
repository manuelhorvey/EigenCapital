import os
from types import SimpleNamespace
import tempfile

import pytest
import yaml

from features.registry import FEATURE_REGISTRY
from paper_trading.config_manager import (
    EngineConfig,
    get_config,
    load_config,
    reset_config,
)
from paper_trading.engine import (
    _SKIP_JOURNAL,
    CONFIG,
    ET,
    HALT,
    PAPER_PORTFOLIO,
    AssetEngine,
    PaperTradingEngine,
    flatten,
    norm_index,
)


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
        assert "btc-usd_mom_10" in features

    def test_btc_features(self):
        features = FEATURE_REGISTRY["BTC-USD"].features
        assert len(features) == 10
        assert "rate_diff" in features
        assert "vix_delta_5" in features
        assert "btc-usd_vs_spy_21" in features

    def test_paper_portfolio_structure(self):
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
        assert sum(v["alloc"] for v in PAPER_PORTFOLIO.values()) <= 1.0


class TestConfigManager:
    def teardown_method(self):
        reset_config()

    def test_default_config(self):
        cfg = EngineConfig()
        assert cfg.capital == 100_000
        assert cfg.position_size == 0.95
        assert cfg.halt["drawdown"] == -0.08
        assert cfg.satellite == {}

    def test_from_dict_full(self):
        data = {
            "capital": 200_000,
            "position_size": 0.80,
            "halt": {"drawdown": -0.05},
            "satellite": {"BTC": {"max_allocation_pct": 0.10}},
            "assets": {"FOO": {"ticker": "FOO"}},
        }
        cfg = EngineConfig.from_dict(data)
        assert cfg.capital == 200_000
        assert cfg.halt["drawdown"] == -0.05
        assert cfg.halt["signal_drought"] == 30
        assert cfg.satellite["BTC"]["max_allocation_pct"] == 0.10
        assert cfg.assets["FOO"]["ticker"] == "FOO"

    def test_load_config_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"capital": 50000, "halt": {"drawdown": -0.12}}, f)
            tmppath = f.name
        try:
            cfg = load_config(tmppath)
            assert cfg.capital == 50000
            assert cfg.halt["drawdown"] == -0.12
        finally:
            os.unlink(tmppath)

    def test_load_config_missing_file(self):
        cfg = load_config("/nonexistent/path.yaml")
        assert cfg.capital == 100_000

    def test_get_config_caching(self):
        reset_config()
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_reset_config(self):
        reset_config()
        cfg1 = get_config()
        reset_config()
        cfg3 = get_config()
        assert cfg1 is not cfg3

    def test_to_dict_roundtrip(self):
        cfg = EngineConfig(capital=99999, halt={"drawdown": -0.15})
        d = cfg.to_dict()
        assert d["capital"] == 99999
        assert d["halt"]["drawdown"] == -0.15

    def test_halt_defaults_merge(self):
        data = {"halt": {"drawdown": -0.15}}
        cfg = EngineConfig.from_dict(data)
        assert cfg.halt["drawdown"] == -0.15
        assert cfg.halt["monthly_pf"] == 0.70
        assert cfg.halt["signal_drought"] == 30
        assert cfg.halt["prob_drift"] == 0.15


class TestPaperTradingEngineState:
    def test_get_state_returns_dashboard_snapshot(self):
        asset = SimpleNamespace(
            allocation=1.0,
            initial_capital=100_000,
            current_value=100_000,
            capital_base=100_000,
            peak_value=100_000,
            current_price=100.0,
            trade_log=[],
            prob_history=[{"signal": "BUY", "confidence": 60, "close_price": 100.0}],
            sl_mult=1.0,
            tp_mult=2.0,
            regime_geometry={},
            _liquidity_regime="NORMAL",
            _liquidity_sl_mult=1.0,
            _liquidity_size_scalar=1.0,
            _narrative_sl_mult=1.0,
            _narrative_size_scalar=1.0,
            _narrative_active=None,
            _narrative_stale=False,
            pos_mgr=SimpleNamespace(
                has_position=lambda: False,
                exposure_multiplier=1.0,
            ),
            refresh_price=lambda: None,
            mtm_value=100_000,
            get_metrics=lambda: {
                "current_value": 100_000,
                "current_price": 100.0,
                "position": None,
                "meta_inference": {},
                "feature_stability": {},
                "drawdown": 0,
            },
            check_halt_conditions=lambda: {"halted": False},
            update_validity=lambda: {"state": "GREEN", "exposure": 1.0},
        )
        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        engine.assets = {"TEST": asset}
        engine.satellite = None
        engine.start_date = __import__("datetime").datetime.now(tz=ET)
        engine.last_update = None
        engine.portfolio_peak_value = None
        engine._rebalance_weights = {}

        state = engine.get_state()

        assert state["portfolio"]["execution_state"] == "ACTIVE"
        assert state["assets"]["TEST"]["validity_state"] == "GREEN"
        assert state["risk_parity"]["weights"] == {}


class TestUpdatePnl:
    @pytest.fixture
    def engine(self):
        return AssetEngine(
            "NZDJPY=X",
            "NZDJPY",
            FEATURE_REGISTRY["NZDJPY=X"],
            PAPER_PORTFOLIO["NZDJPY"]["alloc"],
            journal_path=_SKIP_JOURNAL,
        )

    @pytest.fixture
    def signal_data(self):
        import numpy as np
        import pandas as pd

        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(5) * 0.5)
        return pd.DataFrame(
            {
                "close": prices,
                "signal": [2, 2, 0, 0, 2],
                "position_size": [1.0] * 5,
            },
            index=dates,
        )

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

    def test_position_open_with_current_price_updates_pnl(self, engine, signal_data):
        engine.signal_data = signal_data
        engine.position = {
            "side": "long",
            "entry": 100.0,
            "sl": 95.0,
            "tp": 110.0,
            "entry_date": "2026-05-01",
            "vol": 0.02,
        }
        engine.current_price = float(signal_data["close"].iloc[-1])
        engine.update_pnl()
        # position not hit (close ~101, sl=95, tp=110), signal PnL settles
        assert engine.current_value != engine.initial_capital

    def test_sl_hit_closes_position(self, engine, signal_data):
        import pandas as pd

        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 102.0, 98.0, 96.0, 94.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [2] * 5,
                "position_size": [1.0] * 5,
            },
            index=dates,
        )
        engine.position = {
            "side": "long",
            "entry": 100.0,
            "sl": 95.0,
            "tp": 110.0,
            "entry_date": "2026-05-01",
            "vol": 0.02,
        }
        engine.current_price = prices[-1]  # 94, triggers SL at 95
        engine.update_pnl()
        assert engine.position is None
        assert len(engine.trade_log) == 1

    def test_tp_hit_closes_position(self, engine, signal_data):
        import pandas as pd

        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 105.0, 108.0, 112.0, 115.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [2] * 5,
                "position_size": [1.0] * 5,
            },
            index=dates,
        )
        engine.position = {
            "side": "long",
            "entry": 100.0,
            "sl": 95.0,
            "tp": 110.0,
            "entry_date": "2026-05-01",
            "vol": 0.02,
        }
        engine.current_price = prices[-1]  # 115, triggers TP at 110
        engine.update_pnl()
        assert engine.position is None
        assert engine.current_value > engine.initial_capital

    def test_short_sl_hit_closes_short_position(self, engine):
        import pandas as pd

        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 102.0, 105.0, 108.0, 110.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [0] * 5,
                "position_size": [1.0] * 5,
            },
            index=dates,
        )
        engine.position = {
            "side": "short",
            "entry": 100.0,
            "sl": 105.0,
            "tp": 95.0,
            "entry_date": "2026-05-01",
            "vol": 0.02,
        }
        engine.current_price = prices[-1]  # 110, triggers SL at 105
        engine.update_pnl()
        assert engine.position is None

    def test_short_tp_hit_closes_short_position(self, engine):
        import pandas as pd

        dates = pd.date_range("2026-05-01", periods=5, freq="D")
        prices = [100.0, 98.0, 96.0, 94.0, 92.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [0] * 5,
                "position_size": [1.0] * 5,
            },
            index=dates,
        )
        engine.position = {
            "side": "short",
            "entry": 100.0,
            "sl": 105.0,
            "tp": 95.0,
            "entry_date": "2026-05-01",
            "vol": 0.02,
        }
        engine.current_price = prices[-1]  # 92, triggers TP at 95
        engine.update_pnl()
        assert engine.position is None
        assert engine.current_value > engine.initial_capital
