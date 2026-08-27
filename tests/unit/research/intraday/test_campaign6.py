"""Campaign 6 — 1H confirmation of ST-001 tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.intraday import campaign6_1h_confirmation as c6

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def h1_df() -> pd.DataFrame:
    """Synthetic H1 OHLCV data (10 weekdays, 24 bars/day)."""
    rng = np.random.default_rng(7)
    times = pd.date_range("2025-01-06 00:00", periods=24 * 12, freq="1h")
    times = times[times.dayofweek < 5]
    n = len(times)
    ret = rng.normal(0, 0.0012, n)
    close = 1.1000 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0, 0.0004, n))
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.integers(100, 900, n).astype(float)
    return pd.DataFrame(
        {
            "time": times,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": vol,
        }
    )


# ── Signal: same economic mechanism, no look-ahead ──────────────────────


class TestSignal:
    def test_primary_signal_gated_to_london_open(self, h1_df):
        sig = c6.PRIMARY_SIGNAL(h1_df).fillna(0)
        hours = h1_df["time"].dt.hour
        assert (sig[hours != 7].abs() < 1e-15).all()
        assert (sig[hours == 7].abs() > 0).any()

    def test_boundary_grid_variants_gated(self, h1_df):
        for b in c6.BOUNDARY_GRID:
            sig = c6.make_asia_london_signal(b, 2)(h1_df).fillna(0)
            hours = h1_df["time"].dt.hour
            assert (sig[hours != b].abs() < 1e-15).all()

    @pytest.mark.parametrize("b,k", [(6, 2), (7, 2), (8, 3)])
    def test_no_lookahead_future_prices_dont_change_past(self, h1_df, b, k):
        func = c6.make_asia_london_signal(b, k)
        base = func(h1_df).fillna(0)
        cut = int(len(h1_df) * 0.75)
        pert = h1_df.copy()
        pert.loc[pert.index[cut:], ["open", "high", "low", "close"]] *= 2.0
        after = func(pert).fillna(0)
        pd.testing.assert_series_equal(base.iloc[:cut], after.iloc[:cut], check_names=False)

    def test_pre_registered_grids_frozen(self):
        assert c6.BOUNDARY_GRID == [6, 7, 8]
        assert c6.LOOKBACK_GRID == [2, 3]
        assert (c6.PRIMARY_BOUNDARY, c6.PRIMARY_LOOKBACK) in [
            (b, k) for b in c6.BOUNDARY_GRID for k in c6.LOOKBACK_GRID
        ]


# ── Engine ──────────────────────────────────────────────────────────────


class TestEngine:
    def test_h1_annualization(self):
        assert c6.BARS_PER_TRADING_DAY == 24

    def test_bt_perfect_foresight_positive(self, h1_df):
        sig = np.sign(h1_df["close"].shift(-2) - h1_df["close"]).fillna(0)
        sh, _, _, trades = c6.bt(h1_df, sig, hp=2, cost=0)
        assert sh > 1.0 and trades > 0

    def test_costs_reduce_returns(self, h1_df):
        sig = pd.Series(np.sign(h1_df["close"].pct_change().fillna(0)), index=h1_df.index)
        _, r_free, _, _ = c6.bt(h1_df, sig, hp=1, cost=0)
        _, r_cost, _, _ = c6.bt(h1_df, sig, hp=1, cost=0.0022)
        assert r_cost <= r_free

    def test_wf_bounds(self, h1_df):
        cons, oos = c6.wf_validate(h1_df, c6.PRIMARY_SIGNAL, hp=1, n_folds=3)
        assert 0 <= cons <= 1 and np.isfinite(oos)

    def test_permutation_p_bounds(self, h1_df):
        p = c6.permutation_test(h1_df, c6.PRIMARY_SIGNAL, hp=1, n_permutations=20)
        assert 0 <= p <= 1

    def test_regime_analysis_includes_year_dd(self, h1_df):
        yr, sess, ydd = c6.regime_analysis(h1_df, c6.PRIMARY_SIGNAL(h1_df).fillna(0), hp=1)
        assert set(yr) == set(ydd)
        assert all(-1 <= d <= 0 for d in ydd.values())
        assert set(sess).issubset({"asian", "london", "overlap", "new_york", "off_hours"})

    def test_daily_returns_aggregates_by_day(self, h1_df):
        dr = c6.daily_returns(h1_df, c6.PRIMARY_SIGNAL(h1_df), hp=1)
        # one value per trading day at most
        n_days = h1_df["time"].dt.date.nunique()
        assert len(dr) <= n_days


# ── Confirmation logic is fail-closed ───────────────────────────────────


def _mk_result(**over):
    base = dict(
        variant="b=07,k=2",
        boundary=7,
        lookback=2,
        hp=2,
        gross_sharpe=0.6,
        net_base=0.5,
        net_adverse=0.35,
        max_dd=-0.08,
        trades=400,
        wf_consistency=0.85,
        wf_oos_sharpe=0.4,
        degradation=0.15,
        permutation_p=0.01,
        permutation_p_bonferroni=0.16,
        verdict="fragile",
    )
    base.update(over)
    return c6.ConfirmResult(**base)


class TestConfirmationLogic:
    def test_confirmed_requires_supported_and_corrected_p(self):
        v, notes = c6.confirm_verdict(
            [
                _mk_result(verdict="supported", permutation_p_bonferroni=0.04),
            ]
        )
        assert v == "CONFIRMED"

    def test_supported_but_uncorrected_is_not_confirmed(self):
        v, _ = c6.confirm_verdict(
            [
                _mk_result(verdict="supported", permutation_p_bonferroni=0.16),
            ]
        )
        assert v == "NOT_CONFIRMED"

    def test_all_fragile_not_confirmed(self):
        v, _ = c6.confirm_verdict([_mk_result()])
        assert v == "NOT_CONFIRMED"

    def test_empty_results_fail_closed(self):
        v, _ = c6.confirm_verdict([])
        assert v == "NOT_CONFIRMED"


# ── Frozen gates still enforced through classify ────────────────────────


class TestFrozenGates:
    def test_classify_blocks_weak_edge(self):
        """net_base barely positive + poor WF must NOT classify supported."""
        from eigencapital.research.intraday.campaign4_15m import HypResult

        hr = HypResult(
            hid="t",
            family="f",
            description="d",
            hp=2,
            gross_sharpe=0.31,
            net_base=0.05,
            net_adverse=-0.05,
            max_dd=-0.5,
            trades=50,
            wf_consistency=0.4,
            wf_oos_sharpe=0.0,
            degradation=0.8,
            permutation_p=0.9,
        )
        verdict, reasons, _ = __import__(
            "eigencapital.research.intraday.campaign5_30m",
            fromlist=["classify"],
        ).classify(hr)
        assert verdict.value != "supported"

    def test_classify_permutation_uses_corrected_value(self):
        """evaluate_variant feeds p_adj into classify; a raw-pass but
        corrected-fail signal cannot be supported."""
        from eigencapital.research.intraday.campaign4_15m import HypResult
        from eigencapital.research.intraday.campaign5_30m import classify

        hr = HypResult(
            hid="t",
            family="f",
            description="d",
            hp=2,
            gross_sharpe=0.6,
            net_base=0.5,
            net_adverse=0.4,
            max_dd=-0.05,
            trades=500,
            wf_consistency=0.9,
            wf_oos_sharpe=0.5,
            degradation=0.1,
            permutation_p=0.20,  # corrected value fails
        )
        verdict, reasons, _ = classify(hr)
        assert verdict.value != "supported"
        assert "permutation_insignificant" in reasons


# ── Reports smoke test ──────────────────────────────────────────────────


class TestReports:
    def test_write_reports_smoke(self, tmp_path, monkeypatch):
        monkeypatch.setattr(c6, "REPORT_MD", str(tmp_path / "c6.md"))
        monkeypatch.setattr(c6, "REPORT_JSON", str(tmp_path / "c6.json"))
        primary = [_mk_result()]
        sens = [
            c6.ConfirmResult(
                variant="x",
                boundary=6,
                lookback=2,
                hp=1,
                net_base=0.1,
                permutation_p_bonferroni=0.5,
                verdict="rejected",
            ),
        ]
        c6.write_reports(primary, sens, {("EURUSDm", "GBPUSDm"): 0.21})
        md = (tmp_path / "c6.md").read_text()
        assert "CAMPAIGN 6" in md
        assert "CONFIRMATION VERDICT" in md
        assert "SENSITIVITY GRID" in md
        js = (tmp_path / "c6.json").read_text()
        assert "final_verdict" in js

    def test_report_decision_not_confirmed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(c6, "REPORT_MD", str(tmp_path / "c6b.md"))
        monkeypatch.setattr(c6, "REPORT_JSON", str(tmp_path / "c6b.json"))
        c6.write_reports([_mk_result()], [])
        md = (tmp_path / "c6b.md").read_text()
        assert "NOT_CONFIRMED" in md
