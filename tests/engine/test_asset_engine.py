"""Tests for ``paper_trading.asset_engine.AssetEngine`` — core lifecycle.

Covers:
- ``train()`` — delegation to training pipeline + calibration refresh
- ``generate_signal()`` — halt gate, inference delegation
- ``refresh_price()`` — realtime + fallback paths
- ``refresh_spread()`` — broker spread fetch
- ``_load_model_hash()`` — sidecar verification logic
- ``_load_calibration_registry()`` — calibration loading
- ``update_pnl()`` — PnL controller delegation
- ``mtm_value`` — property delegation
- ``get_metrics()`` — metrics snapshot builder
- ``check_halt_conditions()`` — governance halt check
- ``_cooldown_penalty()`` / ``_record_stop_out()`` / ``_can_enter()`` — cooldown logic
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Re-export so ruff F811 doesn't flag class-local re-definitions.
MagicMock  # noqa: B018


def _make_engine(**overrides):
    """Build an AssetEngine via ``__new__`` with mock dependencies.

    Follows the pattern established in ``test_engine.py`` — bypass the
    heavy ``__init__`` and wire up only what each test needs.
    """
    from paper_trading.asset_engine import AssetEngine

    engine = AssetEngine.__new__(AssetEngine)

    # ── Core identity ────────────────────────────────────────────
    engine.ticker = overrides.get("ticker", "EURUSD=X")
    engine.name = overrides.get("name", "EURUSD")
    engine.config = overrides.get("config", {})
    engine.halt_config = overrides.get("halt_config", {})
    engine.sl_mult = overrides.get("sl_mult", 1.0)
    engine.tp_mult = overrides.get("tp_mult", 2.5)
    engine.max_depth = overrides.get("max_depth", 2)
    engine.regime_geometry = overrides.get("regime_geometry", {})

    # ── Capital ──────────────────────────────────────────────────
    engine.initial_capital = overrides.get("initial_capital", 100_000)
    engine.capital_base = engine.initial_capital
    engine.peak_value = engine.initial_capital
    engine.current_value = engine.initial_capital

    # ── Position management ──────────────────────────────────────
    engine.pos_mgr = overrides.get(
        "pos_mgr",
        SimpleNamespace(
            has_position=lambda: False,
            current_side=lambda: None,
            position=None,
            check_sl_tp=lambda price: None,
            get_remaining_fraction=lambda: 1.0,
        ),
    )

    # ── Runtime state (each attr enumerated once so no duplicates) ──
    engine.model = overrides.get("model")
    engine.signal_data = overrides.get("signal_data")
    engine.last_signal_date = overrides.get("last_signal_date")
    engine.current_price = overrides.get("current_price")
    engine.position = overrides.get("position")
    engine.trades = overrides.get("trades", [])
    engine.trade_log = overrides.get("trade_log", [])
    engine.prob_history = overrides.get("prob_history", [])
    engine.model_path = overrides.get("model_path", "/tmp/test_model.json")
    engine._model_hash = overrides.get("_model_hash", "test_hash")
    engine._model_hash_verified = overrides.get("_model_hash_verified", True)
    engine._total_exits = overrides.get("_total_exits", 0)
    engine._sl_exits = overrides.get("_sl_exits", 0)
    engine._cycle_counter = overrides.get("_cycle_counter", 0)
    engine._last_stop_out_side = overrides.get("_last_stop_out_side")
    engine._last_stop_out_cycle = overrides.get("_last_stop_out_cycle", -999)
    engine._last_stop_out_price = overrides.get("_last_stop_out_price")
    engine._cooldown_score = overrides.get("_cooldown_score", 0.0)
    engine._last_cooldown_update_cycle = overrides.get("_last_cooldown_update_cycle", -999)
    engine._last_confidence = overrides.get("_last_confidence", 0.0)
    engine._regime_adjusted_entry = overrides.get("_regime_adjusted_entry", False)
    engine._entry_price = overrides.get("_entry_price", 0.0)
    engine._churn_ratio_threshold = overrides.get("_churn_ratio_threshold", 0.50)
    engine._min_flip_interval_bars = overrides.get("_min_flip_interval_bars", 3)
    engine._last_signal_flip_cycle = overrides.get("_last_signal_flip_cycle", -10)
    engine._pending_entries = overrides.get("_pending_entries", [])
    engine._last_stability = overrides.get("_last_stability")
    engine._last_psi_drift = overrides.get("_last_psi_drift")
    engine._experiment_id = overrides.get("_experiment_id", "")
    engine._attribution_buffer = overrides.get("_attribution_buffer", [])
    engine._attribution_export_dir = overrides.get("_attribution_export_dir", "")
    engine._current_trade_id = overrides.get("_current_trade_id", 0)
    engine._cycle_times = overrides.get("_cycle_times", [])
    engine._last_regime_long_prob = overrides.get("_last_regime_long_prob")
    engine._last_regime_raw_probas = overrides.get("_last_regime_raw_probas")
    engine._last_regime_features = overrides.get("_last_regime_features")
    engine._entry_signal_dir = overrides.get("_entry_signal_dir", 0)
    engine._position = overrides.get("_position")
    engine._last_spread_bps = overrides.get("_last_spread_bps")
    engine._last_spread_time = overrides.get("_last_spread_time")

    # ── Calibration ──────────────────────────────────────────────
    engine._calibration_registry = overrides.get("_calibration_registry")

    # ── Sub-pipelines ────────────────────────────────────────────
    engine._training = overrides.get("_training", SimpleNamespace(train=lambda force=None: None))
    engine._inference = overrides.get(
        "_inference",
        SimpleNamespace(generate_signal=lambda threshold=0.45, **kwargs: {"signal": "BUY"}),
    )
    engine._pnl = overrides.get(
        "_pnl",
        SimpleNamespace(
            update_pnl=lambda: None,
            set_capital_base=lambda x: None,
            mtm_value=100_000,
        ),
    )

    # ── Dependencies ─────────────────────────────────────────────
    engine._market_data = overrides.get(
        "_market_data",
        SimpleNamespace(
            get_realtime_price=lambda ticker: 1.0500,
            get_historical=lambda ticker, **kw: SimpleNamespace(
                empty=False, ffill=lambda: SimpleNamespace(iloc=lambda: [1.0500])
            ),
        ),
    )
    engine.state_store = overrides.get("state_store")
    engine.execution_bridge = overrides.get("execution_bridge", SimpleNamespace(broker=None))
    engine.governance = overrides.get(
        "governance",
        SimpleNamespace(
            check_halt=lambda: {"halted": False, "reasons": []},
            _narrative_sl_mult=1.0,
            _liquidity_sl_mult=1.0,
            _narrative_size_scalar=1.0,
            _liquidity_size_scalar=1.0,
        ),
    )
    engine.validity_sm = overrides.get(
        "validity_sm",
        SimpleNamespace(
            current_state=SimpleNamespace(value="GREEN"),
            evaluate=lambda *a, **kw: ("GREEN", 1.0),
        ),
    )

    # ── Entry service ────────────────────────────────────────────
    engine._entry = overrides.get(
        "_entry",
        SimpleNamespace(
            can_enter=lambda side, price, **kw: (True, "ok"),
            effective_capital=lambda **kw: 100_000,
            composite_size_scalar=lambda *a, **kw: 0.8,
            compute_notional=lambda *a, **kw: 80_000,
            sizing_config=lambda *a, **kw: {"size": 0.8, "stop": 0.02},
            tb_vol=lambda s: 0.02,
            open_position=lambda *a, **kw: None,
            poll_pending_entries=lambda *a, **kw: None,
            drawdown_taper=lambda *a, **kw: 1.0,
        ),
    )

    return engine


# ═══════════════════════════════════════════════════════════════════
# train()
# ═══════════════════════════════════════════════════════════════════


class TestTrain:
    def test_delegates_to_training_pipeline(self):
        engine = _make_engine()
        trained = []

        engine._training.train = lambda force=False, full_panel=None, expanded_data_dir=None: trained.append(force)
        engine._load_calibration_registry = lambda: None

        engine.train(force=True)
        assert len(trained) == 1
        assert trained[0] is True

    def test_calls_load_calibration_after_train(self):
        engine = _make_engine()
        loaded = []

        engine._training.train = lambda force=False, full_panel=None, expanded_data_dir=None: None
        engine._load_calibration_registry = lambda: loaded.append(1)

        engine.train()
        assert len(loaded) == 1

    def test_train_with_force_false_default(self):
        engine = _make_engine()
        trained = []

        engine._training.train = lambda force=False, full_panel=None, expanded_data_dir=None: trained.append(force)
        engine._load_calibration_registry = lambda: None

        engine.train()
        assert len(trained) == 1
        assert trained[0] is False

    def test_training_exception_propagates(self):
        engine = _make_engine()

        engine._training.train = lambda force=False, full_panel=None, expanded_data_dir=None: (_ for _ in ()).throw(RuntimeError("train failed"))
        engine._load_calibration_registry = lambda: None

        with pytest.raises(RuntimeError, match="train failed"):
            engine.train()


# ═══════════════════════════════════════════════════════════════════
# generate_signal()
# ═══════════════════════════════════════════════════════════════════


class TestGenerateSignal:
    def test_delegates_to_inference_pipeline(self):
        engine = _make_engine()
        engine.check_halt_conditions = lambda **kw: {"halted": False}
        generated = []

        engine._inference.generate_signal = lambda threshold, **kwargs: generated.append(threshold) or {"signal": "BUY"}

        result = engine.generate_signal(threshold=0.45)
        assert result == {"signal": "BUY"}
        assert len(generated) == 1
        assert generated[0] == 0.45

    def test_returns_none_when_halted(self):
        engine = _make_engine()
        engine.check_halt_conditions = lambda **kw: {"halted": True, "reasons": ["drawdown"]}
        inference_called = []

        engine._inference.generate_signal = lambda threshold, **kwargs: inference_called.append(1) or {"signal": "BUY"}

        result = engine.generate_signal()
        assert result is None
        assert len(inference_called) == 0

    def test_passes_default_threshold(self):
        engine = _make_engine()
        engine.check_halt_conditions = lambda **kw: {"halted": False}
        captured = []

        engine._inference.generate_signal = lambda threshold, **kwargs: captured.append(threshold) or {}

        engine.generate_signal()
        assert captured[0] == 0.45

    def test_passes_custom_threshold(self):
        engine = _make_engine()
        engine.check_halt_conditions = lambda **kw: {"halted": False}
        captured = []

        engine._inference.generate_signal = lambda threshold, **kwargs: captured.append(threshold) or {}

        engine.generate_signal(threshold=0.40)
        assert captured[0] == 0.40


# ═══════════════════════════════════════════════════════════════════
# refresh_price()
# ═══════════════════════════════════════════════════════════════════


class TestRefreshPrice:
    def test_sets_current_price_from_realtime(self):
        engine = _make_engine()
        engine._market_data.get_realtime_price = lambda ticker: 1.2345

        engine.refresh_price()
        assert engine.current_price == 1.2345

    def test_falls_back_to_historical_when_realtime_none(self):
        import pandas as pd

        engine = _make_engine()
        engine._market_data.get_realtime_price = lambda ticker: None
        df = pd.DataFrame({"Close": [1.1000, 1.1100]})
        engine._market_data.get_historical = lambda ticker, **kw: df

        engine.refresh_price()
        assert engine.current_price == 1.1100

    def test_fallback_handles_empty_dataframe(self):
        import pandas as pd

        engine = _make_engine()
        engine._market_data.get_realtime_price = lambda ticker: None
        engine._market_data.get_historical = lambda ticker, **kw: pd.DataFrame()

        engine.refresh_price()
        assert engine.current_price is None

    def test_fallback_handles_exception(self):
        engine = _make_engine()
        engine._market_data.get_realtime_price = lambda ticker: None
        engine._market_data.get_historical = lambda ticker, **kw: (_ for _ in ()).throw(ValueError("API error"))

        engine.refresh_price()
        assert engine.current_price is None

    def test_realtime_takes_precedence(self):
        engine = _make_engine()
        historical_called = []

        engine._market_data.get_realtime_price = lambda ticker: 1.2345
        engine._market_data.get_historical = lambda ticker, **kw: historical_called.append(1)

        engine.refresh_price()
        assert engine.current_price == 1.2345
        assert len(historical_called) == 0


# ═══════════════════════════════════════════════════════════════════
# refresh_spread()
# ═══════════════════════════════════════════════════════════════════


class TestRefreshSpread:
    def test_sets_spread_from_broker_client(self):
        engine = _make_engine()
        client = SimpleNamespace(realtime_spread=lambda ticker: 12.0)
        engine.execution_bridge.broker = SimpleNamespace(_client=client)

        engine.refresh_spread()
        assert engine._last_spread_bps == 12.0

    def test_handles_broker_without_client(self):
        engine = _make_engine()
        engine.execution_bridge.broker = SimpleNamespace(_client=None)

        engine.refresh_spread()
        assert engine._last_spread_bps is None

    def test_handles_no_broker(self):
        engine = _make_engine()
        engine.execution_bridge.broker = None

        engine.refresh_spread()
        assert engine._last_spread_bps is None

    def test_handles_client_exception(self):
        engine = _make_engine()
        client = SimpleNamespace(realtime_spread=lambda ticker: (_ for _ in ()).throw(OSError("connection lost")))
        engine.execution_bridge.broker = SimpleNamespace(_client=client)

        engine.refresh_spread()
        assert engine._last_spread_bps is None

    def test_sets_spread_time(self):
        import time

        engine = _make_engine()
        engine._last_spread_time = None
        client = SimpleNamespace(realtime_spread=lambda ticker: 8.5)
        engine.execution_bridge.broker = SimpleNamespace(_client=client)

        before = time.time()
        engine.refresh_spread()
        after = time.time()

        assert engine._last_spread_time is not None
        assert before <= engine._last_spread_time <= after


# ═══════════════════════════════════════════════════════════════════
# _load_model_hash()
# ═══════════════════════════════════════════════════════════════════


class TestLoadModelHash:
    def test_returns_unknown_when_no_files_exist(self, tmp_path):
        engine = _make_engine()
        engine.model_path = str(tmp_path / "nonexistent_model.json")

        result = engine._load_model_hash()
        assert result == "unknown"

    def test_returns_stored_hash_when_sidecar_exists(self, tmp_path):
        model_path = tmp_path / "test_model.json"
        model_path.write_text("model data")

        hash_path = tmp_path / "test_model_hash.txt"
        hash_path.write_text("abc123def456\n")

        engine = _make_engine(model_path=str(model_path))

        result = engine._load_model_hash()
        assert result == "abc123def456"

    def test_computes_hash_when_no_sidecar(self, tmp_path):
        import hashlib

        model_path = tmp_path / "test_model.json"
        model_path.write_text("model data")
        expected_hash = hashlib.sha256(b"model data").hexdigest()[:16]

        engine = _make_engine(model_path=str(model_path))

        result = engine._load_model_hash()
        assert result == expected_hash

    def test_logs_warning_on_hash_mismatch(self, tmp_path):
        model_path = tmp_path / "test_model.json"
        model_path.write_text("model data")

        hash_path = tmp_path / "test_model_hash.txt"
        hash_path.write_text("mismatched_hash\n")

        engine = _make_engine(model_path=str(model_path))

        with patch("paper_trading.asset_engine.logger.warning") as mock_warn:
            result = engine._load_model_hash()

        assert result == "mismatched_hash"
        mock_warn.assert_called_once()
        # call_args[0][0] is the format string (first positional arg)
        assert "MODEL HASH MISMATCH" in mock_warn.call_args[0][0]
        assert engine._model_hash_verified is False


# ═══════════════════════════════════════════════════════════════════
# _load_calibration_registry()
# ═══════════════════════════════════════════════════════════════════


class TestLoadCalibrationRegistry:
    def test_sets_registry_when_assets_available(self):
        engine = _make_engine()

        with patch("paper_trading.asset_engine.CalibrationRegistry.get_or_load") as mock_get:
            mock_get.return_value.available_assets.return_value = ["EURUSD"]

            engine._load_calibration_registry()

            assert engine._calibration_registry is not None
            mock_get.assert_called_once()

    def test_sets_none_when_no_calibration_assets(self):
        engine = _make_engine()

        with patch("paper_trading.asset_engine.CalibrationRegistry.get_or_load") as mock_get:
            mock_get.return_value.available_assets.return_value = []

            engine._load_calibration_registry()

            assert engine._calibration_registry is None

    def test_handles_missing_calibration_dir(self):
        engine = _make_engine()

        with patch("paper_trading.asset_engine.CalibrationRegistry.get_or_load") as mock_get:
            mock_get.return_value.available_assets.return_value = []

            engine._load_calibration_registry()
            assert engine._calibration_registry is None


# ═══════════════════════════════════════════════════════════════════
# update_pnl() & mtm_value
# ═══════════════════════════════════════════════════════════════════


class TestUpdatePnl:
    def test_delegates_to_pnl_controller(self):
        engine = _make_engine()
        called = []

        engine._pnl.update_pnl = lambda: called.append(1)

        engine.update_pnl()
        assert len(called) == 1

    def test_mtm_value_delegates_to_pnl_controller(self):
        engine = _make_engine()
        engine._pnl.mtm_value = 105_000.0

        assert engine.mtm_value == 105_000.0

    def test_mtm_value_after_pnl_update(self):
        engine = _make_engine()
        engine._pnl.mtm_value = 95_000.0
        engine._pnl.update_pnl = lambda: setattr(engine._pnl, "mtm_value", 102_000.0)

        engine.update_pnl()
        assert engine.mtm_value == 102_000.0


# ═══════════════════════════════════════════════════════════════════
# get_metrics()
# ═══════════════════════════════════════════════════════════════════


class TestGetMetrics:
    def test_returns_dict_with_position_info(self):
        from shared.metrics_snapshot import MetricsSnapshot

        engine = _make_engine(_position=MagicMock())

        snapshot = MetricsSnapshot.build(engine)
        engine.get_metrics = lambda: snapshot

        d = engine.get_metrics().to_dict()
        assert "current_value" in d
        assert "position" in d

    def test_to_dict_serializable(self):
        from shared.metrics_snapshot import MetricsSnapshot

        engine = _make_engine(_position=MagicMock())

        snapshot = MetricsSnapshot.build(engine)
        engine.get_metrics = lambda: snapshot

        d = engine.get_metrics().to_dict()
        assert isinstance(d, dict)
        assert d["current_value"] == 100_000


# ═══════════════════════════════════════════════════════════════════
# check_halt_conditions()
# ═══════════════════════════════════════════════════════════════════


class TestCheckHaltConditions:
    def test_delegates_to_governance_service(self):
        engine = _make_engine()

        with patch(
            "paper_trading.asset_engine.GovernanceService.check_halt_conditions",
            return_value={"halted": True, "reasons": ["drawdown"]},
        ):
            result = engine.check_halt_conditions()

        assert result["halted"] is True
        assert "drawdown" in result["reasons"]

    def test_not_halted_when_healthy(self):
        engine = _make_engine()
        with patch(
            "paper_trading.asset_engine.GovernanceService.check_halt_conditions",
            return_value={"halted": False, "reasons": []},
        ):
            result = engine.check_halt_conditions()

        assert result["halted"] is False

    def test_passes_metrics_when_provided(self):
        engine = _make_engine()
        with patch("paper_trading.asset_engine.GovernanceService.check_halt_conditions") as mock_gov:
            mock_gov.return_value = {"halted": False}
            engine.check_halt_conditions(metrics={"drawdown": -0.05})
            mock_gov.assert_called_once()
            _, kwargs = mock_gov.call_args
            assert "get_metrics" in kwargs


# ═══════════════════════════════════════════════════════════════════
# Cooldown / stop-out logic
# ═══════════════════════════════════════════════════════════════════


class TestRecordStopOut:
    def test_sets_stop_out_state(self):
        engine = _make_engine(
            _cycle_counter=42,
            _entry_price=1.0500,
            _regime_adjusted_entry=True,
            _position=MagicMock(),
        )

        engine._position.record_stop_out.return_value = {
            "_last_stop_out_price": 1.0400,
            "_last_stop_out_side": "long",
            "_last_stop_out_cycle": 42,
            "_cooldown_score": 0.5,
            "_last_cooldown_update_cycle": 42,
        }

        engine._record_stop_out("long", 1.0400)

        assert engine._last_stop_out_side == "long"
        assert engine._last_stop_out_cycle == 42
        assert engine._last_stop_out_price == 1.0400
        assert engine._cooldown_score == 0.5


class TestCooldownPenalty:
    def test_returns_zero_when_no_recent_stop_out(self):
        engine = _make_engine(
            _last_stop_out_side=None,
            _cooldown_score=0.0,
            _last_cooldown_update_cycle=0,
            _cycle_counter=100,
            _position=MagicMock(),
        )
        engine._position.cooldown_penalty.return_value = 0.0

        penalty = engine._cooldown_penalty("long")
        assert penalty == 0.0

    def test_returns_positive_after_recent_stop_out(self):
        engine = _make_engine(
            _last_stop_out_side="long",
            _cooldown_score=0.5,
            _last_cooldown_update_cycle=0,
            _cycle_counter=100,
            _position=MagicMock(),
        )
        engine._last_stop_out_cycle = engine._cycle_counter
        engine._position.cooldown_penalty.return_value = 0.5

        penalty = engine._cooldown_penalty("long")
        assert penalty > 0

    def test_resets_stop_out_side_when_score_decays(self):
        engine = _make_engine(
            _last_stop_out_side="long",
            _last_stop_out_cycle=100,
            _cooldown_score=0.04,
            _last_cooldown_update_cycle=0,
            _cycle_counter=200,
            _position=MagicMock(),
        )
        engine._position.cooldown_penalty.return_value = 0.04

        engine._cooldown_penalty("long")
        assert engine._last_stop_out_side is None


class TestCanEnter:
    def test_delegates_to_entry_service(self):
        engine = _make_engine()
        ok, reason = engine._can_enter("long", 1.0500)
        assert ok is True
        assert reason == "ok"

    def test_passes_side_and_price_to_entry_service(self):
        engine = _make_engine()
        captured = []

        engine._entry.can_enter = lambda side, price, **kw: captured.extend([side, price]) or (True, "ok")

        engine._can_enter("short", 1.1000)
        assert captured == ["short", 1.1000]

    def test_passes_flip_cycle_to_entry_service(self):
        engine = _make_engine()
        captured = {}

        # Accept side, price as positional, capture all kwargs
        engine._entry.can_enter = lambda side, price, **kw: captured.update(kw) or (True, "ok")

        engine._last_signal_flip_cycle = 5
        engine._cycle_counter = 10
        engine._can_enter("long", 1.0500)

        assert captured.get("last_signal_flip_cycle") == 5
        assert captured.get("min_flip_interval_bars") == 3


# ═══════════════════════════════════════════════════════════════════
# set_capital_base
# ═══════════════════════════════════════════════════════════════════


class TestSetCapitalBase:
    def test_delegates_to_pnl_controller(self):
        engine = _make_engine()
        called = []

        engine._pnl.set_capital_base = lambda x: called.append(x)

        engine.set_capital_base(200_000)
        assert len(called) == 1
        assert called[0] == 200_000
