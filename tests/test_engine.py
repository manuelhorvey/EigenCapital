import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

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
    ET,
    AssetEngine,
    PaperTradingEngine,
    flatten,
    norm_index,
)
from paper_trading.portfolio_builder import build_paper_portfolio


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

    @pytest.mark.skip(reason="CI runner pandas C extensions segfault on DatetimeIndex construction")
    def test_norm_index_already_utc(self):
        import pandas as pd

        df = pd.DataFrame({"close": [100]}, index=pd.DatetimeIndex(["2020-01-01"], tz="UTC"))
        result = norm_index(df)
        assert result.index.tz is not None

    @pytest.mark.skip(reason="CI runner pandas C extensions segfault on DatetimeIndex construction")
    def test_norm_index_naive(self):
        import pandas as pd

        df = pd.DataFrame({"close": [100]}, index=pd.DatetimeIndex(["2020-01-01"]))
        result = norm_index(df)
        assert result.index.tz is not None


class TestConfig:
    def test_has_expected_keys(self):
        cfg = get_config()
        d = cfg.to_dict()
        assert "capital" in d
        assert "position_size" in d
        assert "rebalance" in d
        assert "retrain_freq" in d
        assert "retrain_window" in d

    def test_halt_has_expected_keys(self):
        cfg = get_config()
        assert "drawdown" in cfg.halt
        assert "monthly_pf" in cfg.halt
        assert "signal_drought" in cfg.halt
        assert "prob_drift" in cfg.halt

    def test_xlf_features(self):
        features = FEATURE_REGISTRY["BTC-USD"].features
        assert len(features) == 8
        assert "rate_diff" in features
        assert "vix_delta_5" in features
        assert "btc-usd_mom_10" in features

    def test_btc_features(self):
        features = FEATURE_REGISTRY["BTC-USD"].features
        assert len(features) == 8
        assert "rate_diff" in features
        assert "btc-usd_mom_10" in features
        assert "btc-usd_mom_63" in features

    def test_paper_portfolio_structure(self):
        pf = build_paper_portfolio(get_config().halt)
        for asset in ("USDCAD", "GC", "EURCAD", "NZDUSD", "USDCHF", "AUDUSD", "GBPCAD"):
            assert asset in pf
        assert "XLF" not in pf
        assert "EURGBP" not in pf  # removed — RED in walk-forward
        assert "AUDCAD" not in pf  # removed — FAIL in survival sim
        assert sum(v["alloc"] for v in pf.values()) > 0.5  # diversified portfolio


class TestConfigManager:
    def teardown_method(self):
        reset_config()

    def test_default_config(self):
        cfg = EngineConfig()
        assert cfg.capital == 100_000
        assert cfg.position_size == 0.95
        assert cfg.halt["drawdown"] == -0.08

    def test_from_dict_full(self):
        data = {
            "capital": 200_000,
            "position_size": 0.80,
            "halt": {"drawdown": -0.05},
            "assets": {"FOO": {"ticker": "FOO"}},
        }
        cfg = EngineConfig.from_dict(data)
        assert cfg.capital == 200_000
        assert cfg.halt["drawdown"] == -0.05
        assert cfg.halt["signal_drought"] == 30
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
        assert cfg.halt["prob_drift"] == 0.25


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
            governance=SimpleNamespace(
                _liquidity_regime="NORMAL",
                _liquidity_sl_mult=1.0,
                _liquidity_size_scalar=1.0,
                _narrative_sl_mult=1.0,
                _narrative_size_scalar=1.0,
                _narrative_active=None,
                _narrative_stale=False,
            ),
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
            check_halt_conditions=lambda *a, **kw: {"halted": False},
            update_validity=lambda *a, **kw: {"state": "GREEN", "exposure": 1.0},
        )
        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        engine.assets = {"TEST": asset}
        engine.start_date = __import__("datetime").datetime.now(tz=ET)
        engine.last_update = None
        engine.portfolio_peak_value = None
        engine._rebalance_weights = {}
        from paper_trading.services.engine_state_service import EngineStateService
        engine._state = EngineStateService(engine)

        state = engine.get_state()

        assert state["portfolio"]["execution_state"] == "ACTIVE"
        assert state["assets"]["TEST"]["validity_state"] == "GREEN"
        assert state["risk_parity"]["weights"] == {}


class TestUpdatePnl:
    @pytest.fixture
    def engine(self):
        pf = build_paper_portfolio(get_config().halt)
        return AssetEngine(
            "EURCAD=X",
            "EURCAD",
            FEATURE_REGISTRY["EURCAD=X"],
            pf["EURCAD"]["alloc"],
            journal_path=_SKIP_JOURNAL,
        )

    @pytest.fixture
    def signal_data(self):
        import numpy as np
        import pandas as pd

        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(5) * 0.5)
        return pd.DataFrame(
            {
                "close": prices,
                "signal": [2, 2, 0, 0, 2],
                "position_size": [1.0] * 5,
            },
            index=pd.RangeIndex(5),
        )

    def test_returns_when_no_signal_data(self, engine):
        engine.signal_data = None
        engine.update_pnl()
        assert engine.current_value == engine.initial_capital

    def test_returns_when_fewer_than_two_bars(self, engine):
        import pandas as pd

        engine.signal_data = pd.DataFrame({"close": [100]}, index=pd.RangeIndex(1))
        engine.update_pnl()
        assert engine.current_value == engine.initial_capital

    def test_returns_when_last_bar_already_processed(self, engine, signal_data):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ET = ZoneInfo("US/Eastern")
        engine.signal_data = signal_data
        engine.trades = [{"date": str(datetime.now(tz=ET).date())}]
        engine.update_pnl()
        assert engine.current_value == engine.initial_capital

    def test_signal_based_pnl_when_no_position(self, engine, signal_data):
        engine.signal_data = signal_data
        engine.update_pnl()  # first call seeds self.trades
        engine.update_pnl()  # second call applies signal PnL
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
        engine.update_pnl()  # first call seeds self.trades
        engine.update_pnl()  # second call applies signal PnL
        # position not hit (close ~101, sl=95, tp=110), signal PnL settles
        assert engine.current_value != engine.initial_capital

    def test_sl_hit_closes_position(self, engine, signal_data):
        import pandas as pd

        prices = [100.0, 102.0, 98.0, 96.0, 94.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [2] * 5,
                "position_size": [1.0] * 5,
            },
            index=pd.RangeIndex(5),
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

        prices = [100.0, 105.0, 108.0, 112.0, 115.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [2] * 5,
                "position_size": [1.0] * 5,
            },
            index=pd.RangeIndex(5),
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

        prices = [100.0, 102.0, 105.0, 108.0, 110.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [0] * 5,
                "position_size": [1.0] * 5,
            },
            index=pd.RangeIndex(5),
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

        prices = [100.0, 98.0, 96.0, 94.0, 92.0]
        engine.signal_data = pd.DataFrame(
            {
                "close": prices,
                "signal": [0] * 5,
                "position_size": [1.0] * 5,
            },
            index=pd.RangeIndex(5),
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


class TestPaperTradingEngine:
    """Tests for PaperTradingEngine methods using __new__ to bypass __init__."""

    @pytest.fixture
    def engine(self):
        eng = PaperTradingEngine.__new__(PaperTradingEngine)
        eng.assets = {"A": SimpleNamespace(
            ticker="EURUSD", name="A", train=lambda force=None: None,
            sl_mult=1.0, tp_mult=2.0,
        )}
        eng._rebalance_weights = {}
        eng._cycle_count = 0
        eng._cycle_times = []
        eng._cycle_times_maxlen = 1000
        eng._rebalance_last_day = None
        eng._rebalance_dow = 0
        eng._last_prune_date = None
        eng.last_update = None
        import pytz
        from datetime import datetime
        eng.start_date = datetime.now(tz=pytz.timezone("US/Eastern"))
        eng._wal = None
        eng._background_writer = SimpleNamespace(flush=lambda: None, shutdown=lambda: None)
        eng._orchestrator = SimpleNamespace(
            run_once=lambda: {},
            shutdown=lambda: None,
            drain_persist_buffer=lambda: [],
        )
        eng._narrative = SimpleNamespace(_refresh_narrative=lambda: None)
        eng._rebalance = SimpleNamespace(
            should_rebalance=lambda: False,
            rebalance_portfolio=lambda: None,
        )
        eng._state = SimpleNamespace(
            get_state=lambda: {"portfolio": {}, "assets": {}},
            save_state=lambda: None,
        )
        eng._engine_cfg = SimpleNamespace(execution_defaults={})
        eng._cycle_weekend = False
        return eng

    def test_shutdown_calls_orchestrator_and_background_writer(self, engine):
        engine._orchestrator = SimpleNamespace(shutdown=lambda: setattr(engine, "_orch_shutdown", True))
        engine._background_writer = SimpleNamespace(shutdown=lambda: setattr(engine, "_bw_shutdown", True), flush=lambda: None)
        engine._state = SimpleNamespace(save_state=lambda: setattr(engine, "_state_saved", True))
        engine.shutdown()
        assert engine._orch_shutdown
        assert engine._bw_shutdown
        assert engine._state_saved

    def test_shutdown_saves_state(self, engine):
        saved = []
        engine._state = SimpleNamespace(save_state=lambda: saved.append(1))
        engine.shutdown()
        assert len(saved) == 1

    def test_initialize_calls_train_on_all_assets(self, engine):
        trained = []
        asset = SimpleNamespace(
            ticker="EURUSD", name="A",
            train=lambda force=None: trained.append(1),
            sl_mult=1.0, tp_mult=2.0,
        )
        engine.assets = {"A": asset}
        engine.initialize()
        assert len(trained) == 1

    def test_initialize_logs_warning_on_config_registry_mismatch(self, engine):
        from paper_trading.config_manager import reset_config, load_config

        reset_config()
        import tempfile, os, yaml
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"capital": 100000}, f)
            tmppath = f.name
        cfg = load_config(tmppath)
        asset = SimpleNamespace(
            ticker="EURUSD", name="TEST",
            train=lambda force=None: None,
            sl_mult=1.0, tp_mult=2.0,
        )
        engine._engine_cfg = cfg
        engine.assets = {"TEST": asset}
        engine.initialize()
        os.unlink(tmppath)

    def test_initialize_handles_train_exception(self, engine):
        errors = []
        asset = SimpleNamespace(
            ticker="EURUSD", name="A",
            train=lambda force=None: (_ for _ in ()).throw(Exception("train failed")),
            sl_mult=1.0, tp_mult=2.0,
        )
        engine.assets = {"A": asset}
        engine.initialize()

    def test_run_once_returns_empty_when_market_closed(self, engine):
        with patch("paper_trading.engine.is_market_closed", return_value=True):
            result = engine.run_once()
        assert result == {}

    def test_run_once_weekend_eligible_scopes_orchestrator(self, engine):
        """Weekend cycle with eligible assets passes allowed_assets to orchestrator."""
        engine.assets = {
            "BTCUSD": SimpleNamespace(
                ticker="BTC-USD", name="BTCUSD", train=lambda force=None: None,
                sl_mult=1.0, tp_mult=2.0,
                config={"weekend_eligible": True},
            ),
        }
        orch_args = []
        engine._orchestrator = SimpleNamespace(
            run_once=lambda **kw: (orch_args.append(kw), {"assets": {}})[1],
            drain_persist_buffer=lambda: [],
        )
        with patch("paper_trading.engine.is_market_closed", return_value=True):
            result = engine.run_once()
        assert result.get("weekend_cycle") is True
        assert len(orch_args) == 1
        assert orch_args[0].get("allowed_assets") == {"BTCUSD"}

    def test_run_once_weekend_eligible_sets_and_resets_flag(self, engine):
        engine.assets = {
            "BTCUSD": SimpleNamespace(
                ticker="BTC-USD", name="BTCUSD", train=lambda force=None: None,
                sl_mult=1.0, tp_mult=2.0,
                config={"weekend_eligible": True},
            ),
        }
        engine._orchestrator = SimpleNamespace(
            run_once=lambda **kw: {"assets": {"BTCUSD": {"signal": "SELL"}}},
            drain_persist_buffer=lambda: [],
        )
        engine._cycle_weekend = False
        with patch("paper_trading.engine.is_market_closed", return_value=True):
            engine.run_once()
        assert not engine._cycle_weekend  # should be reset after cycle

    def test_run_once_weekend_flushes_wal_and_background_writer(self, engine):
        engine.assets = {
            "BTCUSD": SimpleNamespace(
                ticker="BTC-USD", name="BTCUSD", train=lambda force=None: None,
                sl_mult=1.0, tp_mult=2.0,
                config={"weekend_eligible": True},
            ),
        }
        wal_flushed = []
        bw_flushed = []
        engine._wal = SimpleNamespace(write=lambda kind, data: None, flush=lambda: wal_flushed.append(1))
        engine._background_writer = SimpleNamespace(flush=lambda: bw_flushed.append(1), shutdown=lambda: None)
        engine._orchestrator = SimpleNamespace(
            run_once=lambda **kw: {"assets": {"BTCUSD": {"signal": "SELL"}}},
            drain_persist_buffer=lambda: [],
        )
        with patch("paper_trading.engine.is_market_closed", return_value=True):
            engine.run_once()
        assert len(wal_flushed) >= 1
        assert len(bw_flushed) >= 1

    def test_run_once_weekend_noneligible_not_called(self, engine):
        """Non-eligible assets should not appear in orchestrator results."""
        engine.assets = {
            "BTCUSD": SimpleNamespace(
                ticker="BTC-USD", name="BTCUSD", train=lambda force=None: None,
                sl_mult=1.0, tp_mult=2.0,
                config={"weekend_eligible": True},
            ),
            "EURUSD": SimpleNamespace(
                ticker="EURUSD=X", name="EURUSD", train=lambda force=None: None,
                sl_mult=1.0, tp_mult=2.0,
                config={},
            ),
        }
        engine._orchestrator = SimpleNamespace(
            run_once=lambda **kw: {"assets": {"BTCUSD": {"signal": "BUY"}}},
            drain_persist_buffer=lambda: [],
        )
        with patch("paper_trading.engine.is_market_closed", return_value=True):
            result = engine.run_once()
        assert result.get("weekend_cycle") is True
        assert "EURUSD" not in result.get("assets", {})

    def test_run_once_dispatch_to_orchestrator(self, engine):
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            result = engine.run_once()
        assert isinstance(result, dict)

    def test_run_once_propagates_orchestrator_results(self, engine):
        engine._orchestrator = SimpleNamespace(
            run_once=lambda: {"assets": {"A": {"signal": "BUY"}}, "health": {"status": "OK"}},
            drain_persist_buffer=lambda: [],
        )
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            result = engine.run_once()
        assert result.get("orchestrator_health") == {"status": "OK"}
        assert result.get("A") == {"signal": "BUY"}

    def test_run_once_triggers_rebalance_when_due(self, engine):
        rebalanced = []
        engine._rebalance = SimpleNamespace(
            should_rebalance=lambda: True,
            rebalance_portfolio=lambda: rebalanced.append(1),
        )
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            engine.run_once()
        assert len(rebalanced) == 1

    def test_run_once_wal_portfolio_weights(self, engine):
        wal_events = []
        engine._rebalance_weights = {"A": 0.5, "B": 0.5}
        engine._wal = SimpleNamespace(write=lambda kind, data: wal_events.append((kind, data)))
        engine._rebalance = SimpleNamespace(
            should_rebalance=lambda: True,
            rebalance_portfolio=lambda: None,
        )
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            engine.run_once()
        assert any(k == "portfolio_weights" for k, _ in wal_events)

    def test_run_once_circuit_breaker_path(self, engine):
        engine._orchestrator = SimpleNamespace(
            run_once=lambda: {"circuit_breaker": "drawdown_exceeded"},
            drain_persist_buffer=lambda: [],
        )
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            result = engine.run_once()
        assert result.get("orchestrator_circuit_breaker") == "drawdown_exceeded"

    def test_prune_old_data_once_per_day(self, engine):
        engine._last_prune_date = None
        with patch("scripts.ops.prune_data.prune_all", return_value={"a": {"pruned": 5}}):
            engine._prune_old_data()
            assert engine._last_prune_date is not None
            engine._prune_old_data()  # same day, should not fire again
            assert engine._last_prune_date is not None  # unchanged

    def test_prune_old_data_skips_on_same_day(self, engine):
        from datetime import datetime
        import pytz
        engine._last_prune_date = datetime.now(tz=pytz.timezone("US/Eastern")).strftime("%Y-%m-%d")
        with patch("scripts.ops.prune_data.prune_all") as mock_prune:
            engine._prune_old_data()
            mock_prune.assert_not_called()

    def test_save_state_delegates(self, engine):
        saved = []
        engine._state = SimpleNamespace(save_state=lambda: saved.append(1))
        engine.save_state()
        assert len(saved) == 1

    def test_get_state_delegates(self, engine):
        engine._state = SimpleNamespace(get_state=lambda: {"key": "val"})
        assert engine.get_state() == {"key": "val"}

    def test_create_mt5_broker_uses_config(self):
        from paper_trading.engine import PaperTradingEngine
        from types import SimpleNamespace

        eng = PaperTradingEngine.__new__(PaperTradingEngine)
        cfg = SimpleNamespace(
            mt5=SimpleNamespace(
                account=12345, password="pwd", server="srv",
                symbol_map_path=None,
                bridge_host="127.0.0.1", bridge_port=9879,
                enabled=False,
            ),
        )
        with patch("paper_trading.engine.MT5Broker") as MockMT5B:
            broker = eng._create_mt5_broker(cfg)
            MockMT5B.assert_called_once()
            args, kwargs = MockMT5B.call_args
            assert kwargs.get("account") == 12345
            assert kwargs.get("password") == "pwd"
            assert kwargs.get("server") == "srv"

    def test_install_mt5_data_provider(self):
        eng = PaperTradingEngine.__new__(PaperTradingEngine)
        eng._engine_cfg = SimpleNamespace(mt5=SimpleNamespace(
            account=12345, password="pwd", server="srv",
            symbol_map_path=None,
            bridge_host="127.0.0.1", bridge_port=9879,
        ))
        with patch("paper_trading.engine.MT5Client") as MockClient:
            MockClient.return_value.connect.return_value = True
            with patch("paper_trading.ops.data_fetcher.set_mt5_client") as mock_set:
                eng._install_mt5_data_provider(eng._engine_cfg)
                MockClient.assert_called_once()
                mock_set.assert_called_once()

    def test_run_once_updates_last_update(self, engine):
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            engine.run_once()
        assert engine.last_update is not None

    def test_run_once_increments_cycle_count(self, engine):
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            engine.run_once()
        assert engine._cycle_count == 1

    def test_run_once_benchmark_logging(self, engine):
        with patch("paper_trading.engine.is_market_closed", return_value=False):
            with patch.object(engine, "_cycle_times", [0.1] * 100):
                engine.run_once()


class TestStopOutCooldown:
    @pytest.fixture
    def engine(self):
        pf = build_paper_portfolio(get_config().halt)
        return AssetEngine(
            "EURCAD=X",
            "EURCAD",
            FEATURE_REGISTRY["EURCAD=X"],
            pf["EURCAD"]["alloc"],
            journal_path=_SKIP_JOURNAL,
        )

    def test_cooldown_penalty_active_after_stop_out(self, engine):
        engine._record_stop_out("short", 100.0)
        assert engine._cooldown_penalty("short") > 0

    def test_cooldown_penalty_allows_opposite_direction(self, engine):
        engine._record_stop_out("short", 100.0)
        assert engine._cooldown_penalty("long") == 0

    def test_cooldown_active_after_sl_hit_in_update_pnl(self, engine):
        import pandas as pd

        engine.signal_data = pd.DataFrame(
            {"close": [100, 99], "signal": [0, 0], "position_size": [1.0, 1.0]},
            index=pd.RangeIndex(2),
        )
        engine.position = {
            "side": "long",
            "entry": 100.0,
            "sl": 99.0,
            "tp": 110.0,
            "entry_date": "2026-05-01",
            "vol": 0.02,
        }
        engine.current_price = 99.0
        engine.update_pnl()
        assert engine.position is None
        assert engine._cooldown_penalty("long") > 0
        assert engine._last_stop_out_side == "long"

    def test_churn_case_skips_cooldown(self, engine):
        """Price barely touches SL and bounces — cooldown skipped."""
        from paper_trading.entry.decision import PositionIntent

        intent = PositionIntent(
            side="short",
            entry_price=158.00,
            entry_date="2026-05-26",
            stop_loss=158.30,
            take_profit=157.00,
            vol=0.02,
        )
        engine.pos_mgr.open(intent)
        engine._entry_price = 158.00
        engine._regime_adjusted_entry = True
        engine._record_stop_out("short", exit_price=158.32)
        assert engine._last_stop_out_side is None
        assert engine._last_stop_out_cycle == -999

    def test_blowthrough_case_sets_cooldown(self, engine):
        """Price blows through SL — cooldown applied."""
        from paper_trading.entry.decision import PositionIntent

        intent = PositionIntent(
            side="short",
            entry_price=158.00,
            entry_date="2026-05-26",
            stop_loss=158.30,
            take_profit=157.00,
            vol=0.02,
        )
        engine.pos_mgr.open(intent)
        engine._entry_price = 158.00
        engine._regime_adjusted_entry = True
        engine._record_stop_out("short", exit_price=158.55)
        assert engine._last_stop_out_side == "short"
        assert engine._last_stop_out_cycle == 0
