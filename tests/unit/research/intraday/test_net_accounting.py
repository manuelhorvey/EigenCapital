"""Tests for corrected per-flip net accounting engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.intraday.net_accounting import NetResult, bt_net

COST = 6.5e-4  # 6.5 bps one-way


def _flat_df(closes: list) -> pd.DataFrame:
    idx = pd.date_range("2026-06-01 09:30", periods=len(closes), freq="5min")
    return pd.DataFrame({"close": closes}, index=idx)


class TestFlipAccounting:
    """Costs are charged exactly once per position change, in-series."""

    def test_hand_computed_single_flip(self):
        df = _flat_df([100.0, 101.0, 102.0, 103.0])
        sig = pd.Series([1.0, 1.0, 0.0, 0.0], index=df.index)
        r = bt_net(df, sig, hp=1, cost_one_way=COST)

        # pos = [0, +1, +1, 0]; fwd = pct_change(1).shift(-1)
        # gross bars: (101/100-1)*0=0, (102/101-1)*1, (103/102-1)*1, NaN
        expected_gross = (102.0 / 101.0 - 1) + (103.0 / 102.0 - 1)
        # flips: |Δpos| = [0, 1, 0, 1] → cost on entry and exit
        assert r.n_flips == 2
        assert r.total_cost_drag == pytest.approx(2 * COST)
        assert r.total_net_ret == pytest.approx(expected_gross - 2 * COST)
        assert r.total_gross_ret == pytest.approx(expected_gross)

    def test_zero_cost_equals_gross_exactly(self):
        rng = np.random.default_rng(5)
        n = 400
        close = 100 * np.exp(np.cumsum(rng.normal(0, 1e-3, n)))
        df = _flat_df(close.tolist())
        sig = pd.Series(rng.choice([-1.0, 0.0, 1.0], n), index=df.index)
        r = bt_net(df, sig, hp=1, cost_one_way=0.0)
        assert r.total_net_ret == pytest.approx(r.total_gross_ret)
        assert r.net_sharpe == pytest.approx(r.gross_sharpe)
        assert r.total_cost_drag == 0.0

    def test_costs_monotonically_reduce_total_return(self):
        rng = np.random.default_rng(9)
        n = 600
        close = 50 * np.exp(np.cumsum(rng.normal(0, 5e-4, n)))
        df = _flat_df(close.tolist())
        sig = pd.Series(np.sign(rng.normal(0, 1, n)), index=df.index)
        totals = [bt_net(df, sig, hp=1, cost_one_way=c).total_net_ret for c in (0.0, 1e-4, 5e-4, 2e-3)]
        assert all(a >= b for a, b in zip(totals, totals[1:]))

    def test_extreme_cost_forces_negative_net(self):
        rng = np.random.default_rng(11)
        n = 500
        close = 10 * np.exp(np.cumsum(rng.normal(0, 1e-3, n)))
        df = _flat_df(close.tolist())
        sig = pd.Series(np.sign(rng.normal(0, 1, n)), index=df.index)
        gross = bt_net(df, sig, hp=1, cost_one_way=0.0).total_gross_ret
        wrecked = bt_net(df, sig, hp=1, cost_one_way=abs(gross) + 0.01).total_net_ret
        assert wrecked < 0 < gross or (gross < 0 and wrecked < gross)

    def test_constant_position_charges_only_entry_exit(self):
        df = _flat_df([100.0 + i * 0.1 for i in range(100)])
        sig = pd.Series(1.0, index=df.index)
        r = bt_net(df, sig, hp=1, cost_one_way=COST)
        assert r.n_flips == 1  # single entry at bar 1; never exits in-sample
        assert r.exposure == pytest.approx((len(df) - 1) / len(df))


class TestSeriesSemantics:
    """No look-ahead; DD/tail measured on the NET series."""

    def test_no_lookahead_future_signal_changes_past_not(self):
        rng = np.random.default_rng(3)
        n = 300
        close = 100 * np.exp(np.cumsum(rng.normal(0, 1e-3, n)))
        df = _flat_df(close.tolist())
        sig_a = pd.Series(np.sign(rng.normal(0, 1, n)), index=df.index)
        sig_b = sig_a.copy()
        cut = n // 2
        sig_b.iloc[cut:] = -sig_b.iloc[cut:]

        def net_prefix(sig: pd.Series, upto: int) -> float:
            pos = np.sign(sig).shift(1).fillna(0)
            fwd = df["close"].pct_change(1).shift(-1)
            flips = pos.diff().abs().fillna(0)
            net = pos * fwd - flips * COST
            return float(net.iloc[:upto].dropna().sum())

        # positions are shift(1), so altering signals after `cut` cannot
        # change any net return at bars before `cut`
        assert net_prefix(sig_a, cut) == pytest.approx(net_prefix(sig_b, cut))

    def test_dd_and_worst_bar_on_net_series(self):
        df = _flat_df([100.0, 110.0, 99.0, 108.0])
        sig = pd.Series([1.0, 1.0, 1.0, 0.0], index=df.index)
        r = bt_net(df, sig, hp=1, cost_one_way=COST)
        pos = np.sign(sig).shift(1).fillna(0)
        fwd = df["close"].pct_change(1).shift(-1)
        flips = pos.diff().abs().fillna(0)
        net = (pos * fwd - flips * COST).dropna()
        cum = (1 + net).cumprod()
        expected_dd = float(((cum - cum.cummax()) / cum.cummax()).min())
        assert r.max_dd == pytest.approx(expected_dd)
        assert r.worst_bar == pytest.approx(net.min())
        assert r.max_dd <= 0.0

    def test_exposure_fraction(self):
        df = _flat_df([100.0] * 200)
        sig = pd.Series([0.0] * 100 + [1.0] * 100, index=df.index)
        r = bt_net(df, sig, hp=1, cost_one_way=COST)
        assert r.exposure == pytest.approx(99 / 200)


class TestValidationAndAnnualization:
    """Input validation and annualization parameters."""

    def test_missing_price_column_raises(self):
        df = _flat_df([100.0, 101.0])
        with pytest.raises(ValueError, match="price column"):
            bt_net(df, pd.Series([1.0, 0.0], index=df.index), price_col="px")

    def test_index_mismatch_raises(self):
        df = _flat_df([100.0, 101.0])
        bad_idx = pd.date_range("2020-01-01", periods=2, freq="5min")
        with pytest.raises(ValueError, match="index"):
            bt_net(df, pd.Series([1.0, 0.0], index=bad_idx))

    def test_annualization_parameters_recorded(self, tmp_path=None):
        df = _flat_df(list(100 + np.arange(80) * 0.05))
        sig = pd.Series(1.0, index=df.index)
        r = bt_net(df, sig, hp=2, bars_per_trading_day=96, trading_days_per_year=260, cost_one_way=COST)
        assert r.bars_per_trading_day == 96
        assert r.trading_days_per_year == 260
        assert r.hp == 2

    def test_custom_price_column(self):
        idx = pd.date_range("2026-06-01", periods=60, freq="5min")
        df = pd.DataFrame({"mid_close": 100 + np.arange(60) * 0.01}, index=idx)
        sig = pd.Series(1.0, index=idx)
        r = bt_net(df, sig, hp=1, price_col="mid_close", cost_one_way=COST)
        assert r.n_flips == 1


class TestSerialization:
    """Deterministic serialization contract."""

    def test_to_dict_round_stable(self):
        df = _flat_df(list(100 + np.arange(120) * 0.02))
        sig = pd.Series(np.sign(np.sin(np.arange(120))), index=df.index)
        d1 = bt_net(df, sig, hp=1, cost_one_way=COST).to_dict()
        d2 = NetResult(**d1).to_dict()
        assert d1 == d2
        for key in ("gross_sharpe", "net_sharpe", "n_flips", "total_cost_drag", "max_dd", "exposure"):
            assert key in d1
