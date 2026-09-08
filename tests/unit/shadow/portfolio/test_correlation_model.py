"""Correlation model tests (brief Section 18 — Correlation)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.shadow.portfolio.correlation import CorrelationModel, CorrelationModelConfig
from tests.unit.shadow.portfolio.helpers import make_returns


def _corr_of(symbols, factor_map=None, n=300, seed=1):
    returns = make_returns(symbols, n=n, seed=seed, factor_map=factor_map)
    snap = CorrelationModel().build(returns, as_of=returns.index[-1])
    assert snap is not None
    return snap


class TestCorrelationLevels:
    def test_highly_correlated(self):
        """Shared-factor symbols must show high positive correlation."""
        snap = _corr_of(
            ["AUDUSD", "AUDCHF"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0},
        )
        rho = snap.corr.loc["AUDUSD", "AUDCHF"]
        assert rho > 0.7

    def test_negatively_correlated(self):
        """Opposite-factor symbols must show negative correlation."""
        snap = _corr_of(
            ["AUDUSD", "EURUSD"],
            factor_map={"AUDUSD": 1.0, "EURUSD": -1.0},
        )
        rho = snap.corr.loc["AUDUSD", "EURUSD"]
        assert rho < -0.5

    def test_zero_low_correlation(self):
        """Independent noise must produce near-zero correlation."""
        snap = _corr_of(["AUDUSD", "BTCUSD"], factor_map={}, n=500)
        rho = snap.corr.loc["AUDUSD", "BTCUSD"]
        assert abs(rho) < 0.3

    def test_identical_return_series(self):
        """Identical return series must produce correlation exactly 1.0."""
        returns = make_returns(["AUDUSD", "GBPUSD"], n=300, seed=3)
        returns["GBPUSD"] = returns["AUDUSD"].copy()
        snap = CorrelationModel().build(returns, as_of=returns.index[-1])
        assert snap is not None
        assert snap.corr.loc["AUDUSD", "GBPUSD"] == pytest.approx(1.0, abs=1e-9)


class TestDataQuality:
    def test_insufficient_history_returns_none(self):
        """Too little history must yield no snapshot (data gap, not a guess)."""
        returns = make_returns(["AUDUSD", "EURUSD"], n=5, seed=4)
        snap = CorrelationModel().build(returns, as_of=returns.index[-1])
        assert snap is None

    def test_missing_data_pairwise_complete(self):
        """NaN gaps must be handled pairwise-complete without fabrication."""
        returns = make_returns(["AUDUSD", "EURUSD", "USDJPY"], n=300, seed=5)
        returns.loc[returns.index[100:150], "USDJPY"] = np.nan
        snap = CorrelationModel().build(returns, as_of=returns.index[-1])
        assert snap is not None
        # The pair with the gap still has a defined correlation (other rows).
        assert not np.isnan(snap.corr.loc["AUDUSD", "USDJPY"])
        # Observed-pair counts reflect the gap.
        assert snap.pairwise_obs_counts.loc["AUDUSD", "USDJPY"] <= 250

    def test_min_pairwise_obs_floor(self):
        """Pairs with too few overlapping observations stay NaN (not invented)."""
        returns = make_returns(["AUDUSD", "EURUSD", "GBPUSD"], n=300, seed=6)
        # Keep only 5 overlapping observations between AUDUSD and GBPUSD.
        returns.loc[returns.index[10:], "GBPUSD"] = np.nan
        returns.loc[returns.index[:5], "GBPUSD"] = 0.001
        returns.loc[returns.index[:5], "AUDUSD"] = 0.001
        snap = CorrelationModel().build(returns, as_of=returns.index[-1])
        assert snap is not None
        assert np.isnan(snap.corr.loc["AUDUSD", "GBPUSD"])


class TestStability:
    def test_stability_detects_regime_change(self):
        """A structural break INSIDE the lookback windows must surface as
        elevated cross-window instability."""
        rng = np.random.default_rng(7)
        idx = pd.date_range("2024-01-01", periods=300, freq="B")
        common = rng.normal(0.0, 0.01, 300)
        noise = rng.normal(0.0, 0.005, 300)
        # Anti-correlated for the first 210 days, positively correlated for
        # the last 90. The 120-day window spans BOTH regimes; the 60-day and
        # 20-day windows see only the positive regime → instability.
        eur = np.where(np.arange(300) < 210, -common + noise, common + noise)
        unstable_returns = pd.DataFrame({"AUDUSD": common + noise, "EURUSD": eur}, index=idx)
        unstable = CorrelationModel().build(unstable_returns, as_of=idx[-1])
        assert unstable is not None
        stable_returns = pd.DataFrame({"AUDUSD": common + noise, "EURUSD": common + noise}, index=idx)
        stable = CorrelationModel().build(stable_returns, as_of=idx[-1])
        assert stable is not None
        assert unstable.cross_window_stability > stable.cross_window_stability

    def test_per_lookback_avg_populated(self):
        snap = _corr_of(["AUDUSD", "EURUSD"], factor_map={"AUDUSD": 1.0, "EURUSD": -1.0})
        assert 20 in snap.per_lookback_avg
        assert 60 in snap.per_lookback_avg
        assert 120 in snap.per_lookback_avg


class TestLookaheadBoundary:
    def test_as_of_truncation_hides_future(self):
        """Correlation at as_of must not be influenced by future data."""
        returns = make_returns(["AUDUSD", "EURUSD"], n=300, seed=9)
        as_of = returns.index[250]
        before = returns.loc[:as_of].copy()
        # Plant a violent future move STRICTLY AFTER as_of (would change
        # correlation if it leaked; the inclusive as_of row is untouched).
        future = returns.loc[as_of:].iloc[1:].copy()
        future["AUDUSD"] = -future["AUDUSD"] * 50
        future["EURUSD"] = future["EURUSD"] * 50
        full = pd.concat([before, future])
        snap_full = CorrelationModel().build(full, as_of=as_of)
        snap_before = CorrelationModel().build(before, as_of=as_of)
        assert snap_full is not None and snap_before is not None
        assert np.allclose(
            snap_full.corr.fillna(0).values,
            snap_before.corr.fillna(0).values,
        )

    def test_non_datetime_index_rejected(self):
        """Point-in-time truncation must refuse non-datetime indices."""
        returns = make_returns(["AUDUSD"], n=100, seed=10)
        returns.index = list(range(len(returns)))
        with pytest.raises(TypeError):
            CorrelationModel().build(returns, as_of=returns.index[-1])


class TestTimezoneHandling:
    """Regression for R4-S 2026-09-08: live callers pass tz-aware
    `pd.Timestamp(datetime.now(UTC))` while broker bar indexes are tz-naive.
    pandas raises `Invalid comparison between dtype=datetime64[ns] and
    Timestamp` — the live cycle crashed after risk gates passed.
    """

    def test_aware_as_of_vs_naive_index(self):
        """Live path: tz-aware as_of, tz-naive bar index — must not crash."""
        returns = make_returns(["AUDUSD", "EURUSD"], n=120, seed=12)
        as_of_aware = pd.Timestamp(returns.index[-1]).tz_localize("UTC")
        snap = CorrelationModel().build(returns, as_of=as_of_aware)
        assert snap is not None
        # Same truncation boundary as the naive equivalent.
        snap_naive = CorrelationModel().build(returns, as_of=returns.index[-1])
        assert snap_naive is not None
        assert snap.observations_used == snap_naive.observations_used
        assert snap.as_of == snap_naive.as_of

    def test_naive_as_of_vs_aware_index(self):
        """Inverse path: naive as_of, tz-localized bar index."""
        returns = make_returns(["AUDUSD", "EURUSD"], n=120, seed=13).tz_localize("UTC")
        snap = CorrelationModel().build(returns, as_of=returns.index[-1].tz_localize(None))
        assert snap is not None
        assert snap.observations_used == min(60, len(returns))

    def test_aware_as_of_truncates_future_rows(self):
        """Aware as_of must still exclude later bars (no-lookahead holds)."""
        returns = make_returns(["AUDUSD"], n=120, seed=14)
        as_of_pos = 80
        as_of_aware = pd.Timestamp(returns.index[as_of_pos]).tz_localize("UTC")
        snap = CorrelationModel().build(returns, as_of=as_of_aware)
        assert snap is not None
        assert snap.observations_used == min(60, as_of_pos + 1)
        assert snap.as_of == str(returns.index[as_of_pos].date())

    def test_both_aware_same_tz(self):
        returns = make_returns(["AUDUSD", "EURUSD"], n=120, seed=15).tz_localize("UTC")
        snap = CorrelationModel().build(returns, as_of=returns.index[-1])
        assert snap is not None
        assert snap.observations_used == min(60, len(returns))


class TestShrinkage:
    def test_shrunk_matrix_psd(self):
        returns = make_returns(["AUDUSD", "EURUSD", "USDJPY"], n=120, seed=11)
        snap = CorrelationModel().build(returns, as_of=returns.index[-1])
        assert snap is not None
        shrunk = CorrelationModel().shrunk_correlation(snap, list(returns.columns))
        eigenvalues = np.linalg.eigvalsh(shrunk.values)
        assert eigenvalues.min() >= -1e-9
        assert np.allclose(shrunk.values, shrunk.values.T)

    def test_config_validation(self):
        with pytest.raises(ValueError):
            CorrelationModelConfig(shrinkage=1.5)
        with pytest.raises(ValueError):
            CorrelationModelConfig(primary_lookback=45)  # not in lookbacks
        with pytest.raises(ValueError):
            CorrelationModelConfig(lookbacks=(1,))
