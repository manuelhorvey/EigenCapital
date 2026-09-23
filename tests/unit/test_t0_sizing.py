"""T0 sizing tests — notional envelope enforcement + min-lot weight-error evidence.

Covers the two T0 findings from the forensic audit (2026-09-13):

1. DEAD LIMITS: ``live_risk.max_position_notional`` / ``max_order_notional``
   were defined but enforced nowhere. Now:
   a. ``validate_config_consistency`` raises a CRITICAL when the live-risk
      envelope disagrees with the capital section the sizing path uses.
   b. The rebalance loop skips new OPEN orders whose notional exceeds the
      envelope (fail-closed per order, closes always allowed).
2. MIN-LOT WEIGHT DISTORTION: the min-lot floor in ``generate_orders`` can
   convert a weak signal into a much larger exposure (XAUUSD |w|=14% →
   min-lot ≈ 91% of authorized capital). Behavior is deliberately UNCHANGED
   (approved policy: keep floor + evidence), but every symbol now records
   intended vs achievable weight, and the map is deterministic.

The loop module is imported read-only exactly as the immutability tests do.
No broker is contacted; every test uses synthetic data.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from eigencapital.config import CapitalConfig, LiveRiskConfig, load_config, validate_config_consistency

REPO = Path(__file__).resolve().parents[2]

TEST_SYMBOLS = ["EURUSD", "GBPUSD", "AUDUSD", "USDCHF", "US30", "USTEC", "XAUUSD", "USOIL"]


def _load_loop_module():
    spec = importlib.util.spec_from_file_location("r4_rebalance_loop_t0", REPO / "scripts" / "r4_rebalance_loop.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop_t0"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 1. Config consistency: envelope must match the sizing path ────


class TestConfigConsistencyNotionalAlignment:
    def test_production_config_is_aligned(self):
        """The shipped production config must pass the new CRITICAL gate."""
        config = load_config("production")
        assert validate_config_consistency(config) == []

    def test_drift_between_live_risk_and_capital_is_critical(self):
        lr = LiveRiskConfig(max_position_notional=2500.0)
        cap = CapitalConfig(max_position_size=5000.0)
        warnings = validate_config_consistency(_cfg(lr, cap))
        assert any(w.startswith("CRITICAL") and "max_position_notional" in w for w in warnings)

    def test_order_notional_drift_is_critical(self):
        lr = LiveRiskConfig(max_order_notional=1000.0)
        cap = CapitalConfig(max_order_notional=5000.0)
        warnings = validate_config_consistency(_cfg(lr, cap))
        assert any(w.startswith("CRITICAL") and "max_order_notional" in w for w in warnings)

    def test_aligned_config_produces_no_notional_warning(self):
        lr = LiveRiskConfig(max_position_notional=5000.0, max_order_notional=5000.0)
        cap = CapitalConfig(max_position_size=5000.0, max_order_notional=5000.0)
        warnings = validate_config_consistency(_cfg(lr, cap))
        assert not any("notional" in w for w in warnings)


def _cfg(lr: LiveRiskConfig, cap: CapitalConfig):
    from eigencapital.config import EigenCapitalConfig

    return EigenCapitalConfig(live_risk=lr, capital=cap)


# ── 2. Weight-error evidence: distortion is measured, not silent ──


class TestWeightErrorEvidence:
    @pytest.fixture()
    def loop(self):
        return _load_loop_module()

    @pytest.fixture()
    def sized(self, loop):
        """generate_orders over realistic specs incl. high min-lot symbols."""
        prices = {
            "EURUSD": 1.09,
            "GBPUSD": 1.27,
            "AUDUSD": 0.66,
            "USDCHF": 0.88,
            "US30": 43000.0,
            "USTEC": 21000.0,
            "XAUUSD": 4627.0,
            "USOIL": 75.0,
        }
        contract_sizes = {
            "EURUSD": 100000.0,
            "GBPUSD": 100000.0,
            "AUDUSD": 100000.0,
            "USDCHF": 100000.0,
            "US30": 0.1,
            "USTEC": 0.1,
            "XAUUSD": 100.0,
            "USOIL": 100.0,
        }
        min_volumes = {s: 0.01 for s in TEST_SYMBOLS}
        weights = {s: 0.05 for s in TEST_SYMBOLS}
        equity = 5100.0

        orders = loop.generate_orders(
            target_weights=_series(weights),
            current_positions={},
            prices=prices,
            contract_sizes=contract_sizes,
            min_volumes=min_volumes,
            equity=equity,
            pos_details=None,
        )
        return loop, orders, prices, contract_sizes, min_volumes, equity

    def test_evidence_map_populated_and_reset_per_call(self, sized):
        loop, orders, prices, cs, mv, equity = sized
        assert loop.weight_error_by_symbol, "evidence map must be populated"
        assert set(loop.weight_error_by_symbol) <= set(TEST_SYMBOLS)
        # Deterministic: same inputs → same evidence.
        snapshot = dict(loop.weight_error_by_symbol)
        loop.generate_orders(
            target_weights=_series({s: 0.05 for s in TEST_SYMBOLS}),
            current_positions={},
            prices=prices,
            contract_sizes=cs,
            min_volumes=mv,
            equity=equity,
            pos_details=None,
        )
        assert loop.weight_error_by_symbol == snapshot

    def test_min_lot_floor_is_recorded_with_full_deviation(self, sized):
        """XAUUSD: |w|=5% → $255 target, min lot $4,627 → floored, huge error."""
        loop, _orders, _p, _c, _m, _e = sized
        ev = loop.weight_error_by_symbol["XAUUSD"]
        assert ev["floored"] is True
        assert ev["min_lot_cost"] == pytest.approx(4627.0, rel=0.01)
        assert ev["weight_error_pct"] > 800.0  # $4,627 vs $255 target

    def test_unfloored_symbol_has_small_error(self, sized):
        """EURUSD: |w|=5% → $255 target; min lot 0.01 ≈ $1,090 notional...

        actually floored too. USOIL min lot $75 → NOT floored, error stays
        small (lot rounding only).
        """
        loop, _orders, _p, _c, _m, _e = sized
        ev = loop.weight_error_by_symbol["USOIL"]
        assert ev["floored"] is False
        assert abs(ev["weight_error_pct"]) < 15.0

    def test_evidence_does_not_change_order_lot_sizes(self, loop):
        """Behavior preservation: lots must equal the frozen formula."""
        prices = {s: 100.0 for s in TEST_SYMBOLS}
        cs = {s: 500.0 for s in TEST_SYMBOLS}
        mv = {s: 0.01 for s in TEST_SYMBOLS}
        weights = {s: 0.08 for s in TEST_SYMBOLS}
        equity = 5100.0

        orders = loop.generate_orders(
            target_weights=_series(weights),
            current_positions={},
            prices=prices,
            contract_sizes=cs,
            min_volumes=mv,
            equity=equity,
            pos_details=None,
        )
        # Frozen formula: round(|w|*capped_equity/(price*cs), 2), floored at
        # min_vol, capped at max_lots.
        expected_lots = 0.08 * 5100.0 / (100.0 * 500.0)  # 0.00816 → rounded 0.01
        for _sym, _side, lots, _reason, _tkt in orders:
            assert lots == pytest.approx(max(0.01, expected_lots), abs=1e-9)

    def test_subminimum_target_executes_within_position_envelope(self, loop):
        """Minimum-lot distortion is diagnostic when the notional remains safe."""
        orders = loop.generate_orders(
            target_weights=_series({"XAUUSD": 0.05}),
            current_positions={},
            prices={"XAUUSD": 4627.0},
            contract_sizes={"XAUUSD": 100.0},
            min_volumes={"XAUUSD": 0.01},
            equity=5100.0,
            pos_details=None,
        )
        assert len(orders) == 1
        assert orders[0][0:3] == ("XAUUSD", "BUY", 0.01)
        ev = loop.weight_error_by_symbol["XAUUSD"]
        assert bool(ev["is_feasible"]) is True
        assert ev["absolute_weight_error"] > loop._config.execution.max_absolute_weight_error

    def test_infeasible_target_does_not_close_existing_position(self, loop):
        """Broker granularity must not turn an existing holding into an exit."""
        orders = loop.generate_orders(
            target_weights=_series({"XAUUSD": 0.05}),
            current_positions={"XAUUSD": 0.01},
            prices={"XAUUSD": 4627.0},
            contract_sizes={"XAUUSD": 100.0},
            min_volumes={"XAUUSD": 0.01},
            equity=5100.0,
            pos_details={"XAUUSD": [{"ticket": 123, "volume": 0.01, "type": 0}]},
        )

        assert orders == []

    def test_minimum_lot_symbol_can_consume_target_slot_when_safe(self, loop):
        """A safe minimum-lot candidate participates in target selection."""
        symbols = ["XAUUSD", "EURUSD", "GBPUSD"]
        weights = _series({"XAUUSD": 0.05, "EURUSD": 0.04, "GBPUSD": 0.03})
        orders = loop.generate_orders(
            target_weights=weights,
            current_positions={},
            prices={"XAUUSD": 4327.88, "EURUSD": 1.10, "GBPUSD": 1.27},
            contract_sizes={"XAUUSD": 100.0, "EURUSD": 100000.0, "GBPUSD": 100000.0},
            min_volumes={symbol: 0.01 for symbol in symbols},
            equity=20000.0,
            pos_details=None,
        )

        assert any(order[0] == "XAUUSD" for order in orders)
        assert bool(loop.weight_error_by_symbol["XAUUSD"]["is_feasible"]) is True

    def test_live_equity_uses_capped_step_safe_lot(self, loop):
        """A larger account uses live equity but never exceeds position cap."""
        orders = loop.generate_orders(
            target_weights=_series({"XAUUSD": 0.066}),
            current_positions={},
            prices={"XAUUSD": 4327.88},
            contract_sizes={"XAUUSD": 100.0},
            min_volumes={"XAUUSD": 0.01},
            equity=99483.0,
            pos_details=None,
        )

        assert orders[0][0:3] == ("XAUUSD", "BUY", 0.01)
        assert loop.weight_error_by_symbol["XAUUSD"]["executable_notional"] <= loop.MAX_POSITION_USD

    def test_mt5_request_contains_native_scalars(self, loop, monkeypatch):
        """mt5linux remote eval must not receive NumPy scalar reprs.

        mt5linux is an optional ``mt5`` extra — CI installs only
        ``research``/``dev``, so ``loop.MetaTrader5`` may be None. The
        request builder only needs the enum constants, not a live bridge.
        """
        import numpy as np

        class _MT5Stub:
            TRADE_ACTION_DEAL = 1
            ORDER_TIME_GTC = 0
            ORDER_TYPE_SELL = 1
            ORDER_FILLING_FOK = 0

        monkeypatch.setattr(loop, "MetaTrader5", _MT5Stub, raising=False)
        request = loop._build_mt5_order_request(
            symbol="BTCUSD",
            lots=np.float64(0.03),
            mt5_type=np.int64(_MT5Stub.ORDER_TYPE_SELL),
            price=np.float64(75814.3),
            filling_mode=np.int64(_MT5Stub.ORDER_FILLING_FOK),
            ticket=np.int64(123),
        )

        assert all(type(value) in (int, float, str) for value in request.values())
        assert "np." not in repr(request)

    def test_zero_weight_symbols_absent_from_evidence(self, loop):
        prices = {s: 100.0 for s in TEST_SYMBOLS}
        cs = {s: 1000.0 for s in TEST_SYMBOLS}
        mv = {s: 0.01 for s in TEST_SYMBOLS}
        weights = {**{s: 0.08 for s in TEST_SYMBOLS}, "BTCUSD": 0.0}
        loop.generate_orders(
            target_weights=_series(weights),
            current_positions={},
            prices=prices,
            contract_sizes=cs,
            min_volumes=mv,
            equity=5100.0,
            pos_details=None,
        )
        assert "BTCUSD" not in loop.weight_error_by_symbol

    def test_entry_spread_policy_uses_fx_absolute_units(self, loop):
        assert loop._entry_spread_ok("EURUSD", 1.1000, 1.1010)
        assert not loop._entry_spread_ok("EURUSD", 1.1000, 1.1020)

    def test_entry_spread_policy_uses_relative_units_for_non_fx(self, loop):
        assert loop._entry_spread_ok("USOIL", 75.00, 75.05)
        assert not loop._entry_spread_ok("USOIL", 75.00, 75.20)

    def test_d1_data_age_is_measured_from_newest_bar(self, loop):
        import pandas as pd

        bars = pd.DataFrame({"close": [1.0, 1.1]}, index=pd.to_datetime(["2026-09-13", "2026-09-14"]))
        age = loop._latest_data_age_seconds({"EURUSD": bars}, now=pd.Timestamp("2026-09-14 12:00:00").to_pydatetime())
        assert age == pytest.approx(12 * 60 * 60)

    def test_concentration_hhi_uses_normalized_absolute_weights(self, loop):
        import pandas as pd

        hhi, top3 = loop._target_concentration_diagnostics(pd.Series({"A": 0.2, "B": -0.2, "C": 0.1}))
        assert hhi == pytest.approx(0.36)
        assert top3 == [("A", 0.4), ("B", 0.4), ("C", 0.2)]

    def test_correlation_dashboard_uses_returns_not_symbol_ranks(self, loop):
        import numpy as np
        import pandas as pd

        base = np.arange(1.0, 61.0)
        returns = pd.DataFrame({"A": base, "B": base[::-1], "C": np.sin(base)})
        mean_abs, max_abs, quality, count = loop._signal_correlation_diagnostics(
            pd.Series({"A": 0.2, "B": 0.1, "C": -0.1}), returns
        )
        assert count == 3
        assert max_abs == pytest.approx(1.0)
        assert mean_abs > 0.3
        assert quality == pytest.approx(1.0 - mean_abs)


def _series(d):
    import pandas as pd

    return pd.Series(d)


# ── 3. Envelope enforcement: over-cap opens skipped, closes pass ──


# ── 4. Intent↔fill symbol-level reconciliation ────────────────────


class TestIntentFillSymbolReconciliation:
    """Count-only reconciliation passes when the WRONG orders fill; the
    (symbol, side) matcher must catch compensating errors."""

    @pytest.fixture()
    def loop(self):
        return _load_loop_module()

    def test_matching_symbols_reconcile(self, loop):
        orders = [("EURUSD", "BUY", 1.0, "r", None), ("GBPUSD", "SELL", 2.0, "r", None)]
        fills = [
            {"symbol": "EURUSD", "side": "BUY", "lots": 1.0},
            {"symbol": "GBPUSD", "side": "SELL", "lots": 2.0},
        ]
        result = loop._reconcile_against_intents(2, 0, orders, fills=fills)
        assert result["status"] == "RECONCILED"
        assert result["unmatched_intents"] == []
        assert result["unexpected_fills"] == []

    def test_compensating_errors_no_longer_hidden(self, loop):
        """1 filled + 1 failed with the WRONG symbol filled → DISCREPANCY.
        (A count-only check would call this RECONCILED.)"""
        orders = [
            ("EURUSD", "BUY", 1.0, "r", None),
            ("GBPUSD", "SELL", 2.0, "r", None),
        ]
        fills = [{"symbol": "USDCHF", "side": "BUY", "lots": 1.0}]  # wrong symbol
        result = loop._reconcile_against_intents(1, 1, orders, fills=fills)
        assert result["status"] == "DISCREPANCY"
        assert result["unmatched_intents"] and result["unexpected_fills"]

    def test_timeout_executed_then_retry_fills_both(self, loop):
        """Timeout-actually-executed hazard shape: same (symbol, side) filled
        twice against one intent → unexpected fill surfaced."""
        orders = [("EURUSD", "BUY", 1.0, "r", None)]
        fills = [
            {"symbol": "EURUSD", "side": "BUY", "lots": 1.0},
            {"symbol": "EURUSD", "side": "BUY", "lots": 1.0},
        ]
        result = loop._reconcile_against_intents(2, 0, orders, fills=fills)
        assert result["status"] == "DISCREPANCY"
        assert len(result["unexpected_fills"]) == 1  # excess reported once


class TestEnvelopeEnforcement:
    """The REAL enforcement helper (_apply_order_notional_envelope), not a
    re-implementation of it: over-cap opens are skipped, closes always pass,
    unreadable symbol specs fail closed, and every blocked order is reported."""

    @pytest.fixture()
    def loop(self):
        return _load_loop_module()

    def _apply(self, loop, orders, cap, prices=None, cs=None, symbol_info=None):
        prices = prices if prices is not None else {"XAUUSD": 100.0, "EURUSD": 1.0}
        cs = cs if cs is not None else {"XAUUSD": 1.0, "EURUSD": 1.0}
        return loop._apply_order_notional_envelope(orders, prices, cs, cap, symbol_info=symbol_info)

    def test_over_cap_open_is_blocked_and_reported(self, loop):
        orders = [("XAUUSD", "SELL", 100.0, "LONG 50.0% (50.0% |w|)", None)]
        kept, blocked = self._apply(loop, orders, cap=5_000.0)
        assert kept == []
        assert len(blocked) == 1
        assert blocked[0]["symbol"] == "XAUUSD"
        assert blocked[0]["notional"] == pytest.approx(10_000.0)
        assert blocked[0]["detail"] == "notional_over_cap"

    def test_within_cap_open_passes(self, loop):
        orders = [("EURUSD", "BUY", 1.0, "LONG 5.0% (5.0% |w|)", None)]
        kept, blocked = self._apply(loop, orders, cap=5_000.0)
        assert kept == orders and blocked == []

    def test_close_orders_never_blocked_even_when_over_cap(self, loop):
        orders = [
            ("XAUUSD", "SELL", 100.0, "rotated out", None),
            ("XAUUSD", "SELL", 100.0, "lot adjustment", 12345),
        ]
        kept, blocked = self._apply(loop, orders, cap=10.0)
        assert kept == orders and blocked == []

    def test_unreadable_spec_fails_closed(self, loop):
        """An open we cannot PROVE fits the envelope must not go out."""
        orders = [("XAUUSD", "BUY", 1.0, "LONG 5.0% (5.0% |w|)", None)]
        kept, blocked = self._apply(loop, orders, cap=5_000.0, prices={"XAUUSD": 0.0})
        assert kept == [] and len(blocked) == 1
        assert blocked[0]["detail"] == "unreadable_symbol_spec"

    def test_unreadable_spec_recovered_via_broker_fallback(self, loop):
        class _Info:
            ask = 100.0
            trade_contract_size = 1.0

        orders = [("XAUUSD", "BUY", 1.0, "LONG 5.0% (5.0% |w|)", None)]
        kept, blocked = self._apply(loop, orders, cap=5_000.0, prices={"XAUUSD": 0.0}, symbol_info=lambda s: _Info())
        assert kept == orders and blocked == []

    def test_disabled_cap_passes_everything(self, loop):
        orders = [("XAUUSD", "SELL", 9999.0, "LONG 99.0% (99.0% |w|)", None)]
        kept, blocked = self._apply(loop, orders, cap=0.0)
        assert kept == orders and blocked == []

    def test_cap_matches_aligned_config(self, loop):
        config = load_config("production")
        assert loop.RISK_ENVELOPE.max_position_notional == config.capital.max_position_size
        assert loop.RISK_ENVELOPE.max_order_notional == config.capital.max_order_notional
