"""Synthetic trade-path cases with hand-computed expectations."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from research.volatility import config as C
from research.volatility import features as F
from research.volatility import regimes as R
from research.volatility.trade_path import NO_PROFIT, compute_trade_path
from research.volatility.trade_stream import PathTrade


def _bars(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(t) for t, *_ in rows])
    df = pd.DataFrame([r[1:] for r in rows], index=idx, columns=["open", "high", "low", "close"])
    df.index.name = "time"
    return df


def _series(bars: pd.DataFrame):
    rv = F.realized_vol(bars["close"], C.PRIMARY_RV)
    rvp = rv.expanding(min_periods=250).rank(pct=True)
    reg_p = R.expanding_percentile_regimes(rv)
    reg_z = R.zscore_regimes(rv)
    return rv, rvp, reg_p, reg_z


def _trade(**kw) -> PathTrade:
    d = dict(
        trade_id=1,
        instrument="EURUSDm",
        asset="EURUSD",
        side="LONG",
        signal_date=pd.Timestamp("2024-01-01"),
        entry_ts=pd.Timestamp("2024-01-02"),
        exit_ts=pd.Timestamp("2024-01-04"),
        entry_px=100.0,
        exit_px=102.5,
        weight=0.1,
        net_pnl=0.0025 - 0.0003,
        costs=0.0003,
        is_terminal_close=False,
    )
    d.update(kw)
    return PathTrade(**d)


def test_long_path_mae_mfe_ttf():
    bars = _bars(
        [
            ("2024-01-02", 100.0, 102.0, 98.0, 101.0),
            ("2024-01-03", 101.0, 103.0, 99.0, 102.0),
            ("2024-01-04", 102.5, 104.0, 101.0, 103.0),
        ]
    )
    rv, rvp, rp, rz = _series(bars)
    m = compute_trade_path(_trade(), bars, rv, rvp, rp, rz)
    assert m is not None
    assert m.mae_ret == pytest.approx(0.02)  # low 98 vs entry 100
    assert m.mfe_ret == pytest.approx(0.04)  # high 104 vs entry 100
    assert m.time_to_mae == 1
    assert m.time_to_mfe == 3
    assert m.first_profit_bar == 1  # close 101 > 100
    assert m.underwater_bars == 0
    assert m.max_underwater_run == 0
    assert m.entry_crossings == 0  # never crosses entry
    # path: 100 -> 101 -> 102 -> 102.5 : perfectly efficient
    assert m.path_length == pytest.approx(2.5)
    assert m.path_efficiency == pytest.approx(1.0)
    assert m.holding_bars == 3
    assert m.holding_days == 2.0
    assert m.time_to_first_profit_str is None


def test_short_path_direction_signs():
    bars = _bars(
        [
            ("2024-01-02", 100.0, 101.0, 99.0, 99.5),
            ("2024-01-03", 99.5, 100.0, 97.0, 98.0),
            ("2024-01-04", 97.5, 98.0, 96.5, 97.0),
        ]
    )
    rv, rvp, rp, rz = _series(bars)
    m = compute_trade_path(_trade(side="SHORT", exit_px=97.5), bars, rv, rvp, rp, rz)
    assert m is not None
    # SHORT: adverse = highs above entry, favorable = lows below entry.
    # Exit-bar low 96.5 is included (documented daily-granularity caveat).
    assert m.mae_ret == pytest.approx(0.01)  # high 101
    assert m.mfe_ret == pytest.approx(0.035)  # low 96.5 (exit bar)
    assert m.first_profit_bar == 1  # close 99.5 < 100 => u>0
    assert m.exit_u_ret == pytest.approx(0.025)
    assert m.net_displacement == pytest.approx(2.5)


def test_underwater_run_and_no_profit_sentinel():
    bars = _bars(
        [
            ("2024-01-02", 100.0, 100.5, 98.5, 99.0),
            ("2024-01-03", 99.0, 99.5, 97.5, 98.0),
            ("2024-01-04", 98.0, 99.0, 97.0, 98.5),
        ]
    )
    rv, rvp, rp, rz = _series(bars)
    m = compute_trade_path(_trade(exit_px=98.5), bars, rv, rvp, rp, rz)
    assert m is not None
    # closes after entry: 99, 98 — both underwater; exit 98.5 also < 100
    assert m.underwater_bars == 2
    assert m.max_underwater_run == 2
    assert m.underwater_fraction == pytest.approx(1.0)
    assert m.first_profit_bar is None
    assert m.time_to_first_profit_str == NO_PROFIT
    assert m.exit_u_ret < 0
    assert m.trade_type == "D_persistent_adverse"


def test_oscillation_counts_entry_crossings():
    bars = _bars(
        [
            ("2024-01-02", 100.0, 101.5, 98.5, 101.0),
            ("2024-01-03", 101.0, 101.5, 98.5, 99.0),
            ("2024-01-04", 99.0, 101.5, 98.5, 101.0),
            ("2024-01-05", 101.0, 101.5, 98.5, 99.0),
            ("2024-01-08", 99.0, 101.5, 98.5, 100.5),
        ]
    )
    rv, rvp, rp, rz = _series(bars)
    m = compute_trade_path(
        _trade(exit_ts=pd.Timestamp("2024-01-08"), exit_px=100.5),
        bars,
        rv,
        rvp,
        rp,
        rz,
    )
    assert m is not None
    # closes after entry: 101, 99, 101, 99 => signs + - + - => 3 changes
    assert m.entry_crossings == 3
    assert m.pl_sign_changes == 3


def test_missing_exit_bar_returns_none():
    bars = _bars(
        [
            ("2024-01-02", 100.0, 101.0, 99.0, 100.5),
            ("2024-01-03", 100.5, 101.0, 99.5, 100.8),
        ]
    )
    rv, rvp, rp, rz = _series(bars)
    m = compute_trade_path(_trade(), bars, rv, rvp, rp, rz)  # exit 01-04 missing
    assert m is None


def test_entry_regime_is_pit_labeled_or_none():
    bars = _bars(
        [
            ("2024-01-02", 100.0, 102.0, 98.0, 101.0),
            ("2024-01-03", 101.0, 103.0, 99.0, 102.0),
            ("2024-01-04", 102.5, 104.0, 101.0, 103.0),
        ]
    )
    rv, rvp, rp, rz = _series(bars)
    m = compute_trade_path(_trade(), bars, rv, rvp, rp, rz)
    assert m is not None
    # no prior RV history -> labels None (fail-closed), not a future label
    assert m.entry_regime is None
    assert m.entry_regime_z is None
    assert m.entry_rv_pctile is None or math.isnan(m.entry_rv_pctile)


def test_net_underwater_stricter_than_price_path():
    bars = _bars(
        [
            ("2024-01-02", 100.0, 100.2, 99.9, 100.1),
            ("2024-01-03", 100.1, 100.3, 100.0, 100.2),
            ("2024-01-04", 100.2, 100.4, 100.1, 100.3),
        ]
    )
    rv, rvp, rp, rz = _series(bars)
    m = compute_trade_path(_trade(exit_px=100.3), bars, rv, rvp, rp, rz)
    assert m is not None
    # price path profitable at every close, but never clears 2*cost asset-space
    assert m.underwater_bars == 0
    assert m.underwater_bars_net == 2  # closes 100.1, 100.2 vs 2*15bp
    assert m.max_underwater_run_net >= m.max_underwater_run
