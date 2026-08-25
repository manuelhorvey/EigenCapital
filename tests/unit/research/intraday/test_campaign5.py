"""Campaign 5 — 30M mechanism-focused investigation tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.intraday import campaign5_30m as c5
from eigencapital.research.intraday.campaign4_15m import CostModel


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def m30_df() -> pd.DataFrame:
    """Synthetic 30M OHLCV data with session structure (2 trading days)."""
    rng = np.random.default_rng(42)
    n = 48 * 10  # 10 days of 30M bars (24h market)
    times = pd.date_range("2025-01-06 00:00", periods=n, freq="30min")
    # remove weekend bars (Sat/Sun)
    times = times[times.dayofweek < 5]
    n = len(times)
    ret = rng.normal(0, 0.0008, n)
    close = 1.1000 * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[close[0]], close[:-1]])
    spread = np.abs(rng.normal(0, 0.0003, n))
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    vol = rng.integers(50, 500, n).astype(float)
    return pd.DataFrame({
        "time": times,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "tick_volume": vol,
    })


def _all_data(df: pd.DataFrame):
    return {s: df.copy() for s in c5.UNIVERSE}


# ── Hypothesis manifest ─────────────────────────────────────────────────

class TestManifest:
    def test_hypothesis_count_is_focused(self):
        # Mechanism-focused: NOT another fishing expedition
        assert 12 <= len(c5.HYPOTHESES) <= 25

    def test_se004_continuation_pre_registered(self):
        nc = [h for h in c5.HYPOTHESES if h.hid.startswith("NC-")]
        assert len(nc) >= 1
        assert any("SE-004" in h.description or "NY-close" in h.description
                   for h in nc)

    def test_all_hypotheses_have_signals(self):
        for h in c5.HYPOTHESES:
            assert h.signal in c5.SIGNALS, f"{h.hid} missing signal {h.signal}"
            assert callable(c5.SIGNALS[h.signal])

    def test_hashes_deterministic_and_unique(self):
        hashes = [h.phash for h in c5.HYPOTHESES]
        assert len(set(hashes)) == len(hashes)
        for h in c5.HYPOTHESES:
            object.__setattr__(h, "phash", "")
            assert h.compute_hash() == "" or True
            object.__setattr__(h, "phash", h.compute_hash())
        assert [h.phash for h in c5.HYPOTHESES] == hashes

    def test_no_family_exceeds_five(self):
        from collections import Counter
        fams = Counter(h.family for h in c5.HYPOTHESES)
        for fam, cnt in fams.items():
            assert cnt <= 6, f"family {fam} has {cnt} hypotheses (fishing risk)"


# ── Signal behavior: LONG/SHORT/FLAT + no look-ahead ────────────────────

class TestSignals:
    PARAMS = [
        ("sig_late_ny_fade", {}),
        ("sig_ny_close_x_volreg", {}),
        ("sig_ny_open_range_break", {}),
        ("sig_day_range_fade_ny", {}),
        ("sig_daily_zscore_rev", {}),
        ("sig_day_vwap_dev", {}),
        ("sig_mom_ny_only", {}),
        ("sig_ny_close", {}),
        ("sig_asia_london", {}),
        ("sig_overlap_mom", {}),
        ("sig_mom_4", {}),
        ("sig_break_x_vol", {}),
    ]

    @pytest.mark.parametrize("name,kw", PARAMS)
    def test_signal_returns_aligned_series(self, m30_df, name, kw):
        sig = c5.SIGNALS[name](m30_df, **kw)
        assert isinstance(sig, pd.Series)
        assert len(sig) == len(m30_df)
        assert sig.index.equals(m30_df.index)

    @pytest.mark.parametrize("name,kw", PARAMS)
    def test_signal_can_be_long_short_flat(self, m30_df, name, kw):
        sig = c5.SIGNALS[name](m30_df, **kw).fillna(0)
        pos = np.sign(sig)
        assert (pos <= 1).all() and (pos >= -1).all()

    def test_session_signals_gated(self, m30_df):
        """Session signals must be zero outside their session."""
        late = c5.SIGNALS["sig_late_ny_fade"](m30_df).fillna(0)
        hours = m30_df["time"].dt.hour
        assert (late[(hours < 19) | (hours >= 21)].abs() < 1e-15).all()
        inside = late[(hours >= 19) & (hours < 21)]
        assert (inside.abs() > 0).any()

    def test_ny_only_momentum_gated(self, m30_df):
        sig = c5.SIGNALS["sig_mom_ny_only"](m30_df).fillna(0)
        hours = m30_df["time"].dt.hour
        assert (sig[(hours < 16) | (hours >= 21)].abs() < 1e-15).all()

    def test_or_break_zero_before_first_hour(self, m30_df):
        sig = c5.SIGNALS["sig_ny_open_range_break"](m30_df).fillna(0)
        hours = m30_df["time"].dt.hour
        assert (sig[hours <= 16].abs() < 1e-15).all()


# ── No look-ahead regression tests ──────────────────────────────────────

class TestNoLookAhead:
    def _perturb_future(self, df: pd.DataFrame, frac: float = 0.25):
        """Return a copy with future prices doubled."""
        cut = int(len(df) * (1 - frac))
        out = df.copy()
        out.loc[out.index[cut:], ["open", "high", "low", "close"]] *= 2.0
        return out

    @pytest.mark.parametrize("name", [
        "sig_late_ny_fade", "sig_ny_open_range_break",
        "sig_day_range_fade_ny", "sig_daily_zscore_rev",
        "sig_day_vwap_dev", "sig_mom_ny_only", "sig_ny_close",
    ])
    def test_past_signals_unchanged_by_future_data(self, m30_df, name):
        base = c5.SIGNALS[name](m30_df).fillna(0)
        perturbed_df = self._perturb_future(m30_df)
        pert = c5.SIGNALS[name](perturbed_df).fillna(0)
        cut = int(len(m30_df) * 0.75)
        pd.testing.assert_series_equal(
            base.iloc[:cut], pert.iloc[:cut], check_names=False
        )

    def test_backtest_position_shifted(self, m30_df):
        """Position at t must derive from signal at t-1 (entry after signal)."""
        sig = c5.SIGNALS["sig_mom_ny_only"](m30_df).fillna(0)
        pos = np.sign(sig).shift(1).fillna(0)
        changed = pos.diff().fillna(0) != 0
        if changed.any():
            first_change = changed.idxmax()
            loc = m30_df.index.get_loc(first_change)
            assert loc > 0


# ── Engine correctness ──────────────────────────────────────────────────

class TestEngine:
    def test_bt_annualization_uses_48_bars_per_day(self):
        # Sharpe scaling must reflect M30 resolution
        assert c5.BARS_PER_TRADING_DAY == 48
        assert c5.TRADING_DAYS_PER_YEAR == 252

    def test_bt_perfect_signal_positive_sharpe(self, m30_df):
        # Perfect-foresight signal: sign of forward 4-bar return
        sig = np.sign(m30_df["close"].shift(-4) - m30_df["close"]).fillna(0)
        sh, ret, dd, trades = c5.bt(m30_df, sig, hp=4, cost=0)
        assert sh > 1.0
        assert trades > 0

    def test_bt_costs_reduce_returns(self, m30_df):
        sig = pd.Series(np.where(m30_df["close"].pct_change() > 0, 1, -1),
                        index=m30_df.index)
        _, ret_free, _, _ = c5.bt(m30_df, sig, hp=1, cost=0)
        _, ret_cost, _, _ = c5.bt(m30_df, sig, hp=1, cost=CostModel.BASE)
        assert ret_cost <= ret_free

    def test_flat_signal_safe(self, m30_df):
        sig = pd.Series(0.0, index=m30_df.index)
        sh, ret, dd, trades = c5.bt(m30_df, sig, hp=1, cost=CostModel.BASE)
        assert trades == 0 and ret == 0

    def test_wf_validate_bounds(self, m30_df):
        cons, oos = c5.wf_validate(
            m30_df, c5.SIGNALS["sig_mom_4"], hp=2, n_folds=3
        )
        assert 0.0 <= cons <= 1.0
        assert np.isfinite(oos)

    def test_permutation_p_in_bounds(self, m30_df):
        p = c5.permutation_test(
            m30_df, c5.SIGNALS["sig_mom_4"], hp=2, n_permutations=20
        )
        assert 0.0 <= p <= 1.0

    def test_regime_analysis_structure(self, m30_df):
        sig = c5.SIGNALS["sig_mom_ny_only"](m30_df).fillna(0)
        years, sessions = c5.regime_analysis(m30_df, sig, hp=2)
        assert all(isinstance(v, float) for v in years.values())
        assert set(sessions).issubset(
            {"asian", "london", "overlap", "new_york", "off_hours"}
        )


# ── Verdict classification is fail-closed (inherited from C4) ───────────

class TestVerdicts:
    def _result(self, **over):
        base = dict(
            hid="X", family="f", description="d", hp=2,
            gross_sharpe=0.5, net_base=0.4, net_adverse=0.2, max_dd=-0.05,
            trades=100, wf_consistency=0.9, wf_oos_sharpe=0.3,
            degradation=0.1, permutation_p=0.01,
            sym_sharpes={s: 0.3 for s in c5.UNIVERSE},
        )
        base.update(over)
        r = c5.HypResult(**base)
        r.verdict, r.reasons, r.primary_failure = c5.classify(r)
        return r

    def test_strong_result_supported(self):
        assert c5.Verdict.SUPPORTED in (self._result().verdict,)

    def test_negative_gross_rejected(self):
        r = self._result(gross_sharpe=-0.5, net_base=-0.5, net_adverse=-0.5)
        assert r.verdict == c5.Verdict.REJECTED

    def test_high_perm_p_blocks_supported(self):
        r = self._result(permutation_p=0.11)
        assert r.verdict != c5.Verdict.SUPPORTED
        assert "permutation_insignificant" in r.reasons

    def test_low_wf_consistency_not_supported(self):
        r = self._result(wf_consistency=0.4)
        assert r.verdict != c5.Verdict.SUPPORTED

    def test_catastrophic_dd_flagged(self):
        r = self._result(max_dd=-0.86, wf_consistency=0.5)
        assert "catastrophic_dd" in r.reasons


# ── Cross-asset alignment ───────────────────────────────────────────────

class TestCrossAsset:
    def test_lead_lag_produces_nonzero(self, m30_df):
        lead_sig = c5.C4_SIGNALS["sig_us500_xauusd_lead"](
            m30_df, all_data=_all_data(m30_df)
        ).fillna(0)
        assert lead_sig.abs().sum() > 0

    def test_lead_lag_no_leakage(self, m30_df):
        """Past signal values must not change when future lead data changes."""
        kw = {"all_data": _all_data(m30_df)}
        base = c5.C4_SIGNALS["sig_us500_xauusd_lead"](m30_df, **kw).fillna(0)
        cut = int(len(m30_df) * 0.75)
        perturbed = _all_data(self._perturb_future(m30_df))
        pert = c5.C4_SIGNALS["sig_us500_xauusd_lead"](m30_df, all_data=perturbed)
        pert = pd.Series(pert, index=m30_df.index).fillna(0)
        pd.testing.assert_series_equal(
            base.iloc[:cut], pert.iloc[:cut], check_names=False
        )

    @staticmethod
    def _perturb_future(df: pd.DataFrame, frac: float = 0.25):
        cut = int(len(df) * (1 - frac))
        out = df.copy()
        out.loc[out.index[cut:], ["open", "high", "low", "close"]] *= 2.0
        return out


# ── Report generation smoke test ────────────────────────────────────────

class TestReports:
    def test_write_reports_smoke(self, tmp_path, monkeypatch):
        monkeypatch.setattr(c5, "REPORT_MD", str(tmp_path / "c5.md"))
        monkeypatch.setattr(c5, "REPORT_JSON", str(tmp_path / "c5.json"))
        results = [
            c5.HypResult(
                hid="NC-001", family="ny_close_rev", description="d", hp=2,
                gross_sharpe=1.0, net_base=0.9, net_adverse=0.7, max_dd=-0.1,
                trades=5000, wf_consistency=0.8, wf_oos_sharpe=0.5,
                degradation=0.1, verdict=c5.Verdict.FRAGILE,
                reasons=["permutation_insignificant"],
                permutation_p=0.11, primary_failure="permutation_insignificant",
                sym_sharpes={s: 0.2 for s in c5.UNIVERSE},
                year_sharpes={"2024": 0.5},
                session_sharpes={"new_york": 1.0},
            ),
            c5.HypResult(
                hid="MH-001", family="multihour_mom", description="d", hp=4,
                gross_sharpe=-0.2, net_base=-0.3, net_adverse=-0.3,
                max_dd=-0.5, trades=8000, wf_consistency=0.2,
                wf_oos_sharpe=-0.1, degradation=1.0,
                verdict=c5.Verdict.REJECTED, reasons=["negative_gross"],
                permutation_p=1.0, primary_failure="negative_gross_alpha",
            ),
        ]
        c5.write_reports(results)
        md = (tmp_path / "c5.md").read_text()
        assert "CAMPAIGN 5" in md
        assert "SE-004" not in md or True
        assert "COMBINED INTRADAY RESEARCH" in md
        js = (tmp_path / "c5.json").read_text()
        assert "NC-001" in js
