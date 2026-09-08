"""PortfolioMetrics risk-contribution tests (R4-S comparative evidence table).

Risk-contribution concentration answers "how many independent risk bets is
this portfolio really making?" — weight-space HHI counts positions, but
correlated positions share risk, so the variance-share concentration is the
tighter diagnostic the comparative evidence table reports.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.shadow.portfolio.metrics import compute_portfolio_metrics


def _metrics(weights, vol=None, corr=None):
    symbols = list(weights)
    vol = vol or {s: 0.2 for s in symbols}
    corr = corr if corr is not None else pd.DataFrame(1.0, index=symbols, columns=symbols)
    return compute_portfolio_metrics(weights, vol, corr, {})


class TestRiskContributionConcentration:
    def test_single_name_is_fully_concentrated(self):
        m = _metrics({"AUDUSD": 0.2})
        assert m.max_risk_contribution_share == pytest.approx(1.0)
        assert m.risk_contribution_hhi == pytest.approx(1.0)
        assert m.effective_risk_contributors == pytest.approx(1.0)

    def test_two_uncorrelated_equal_names(self):
        """Equal-weight, uncorrelated names split variance 50/50 → 2 bets."""
        corr = pd.DataFrame([[1.0, 0.0], [0.0, 1.0]], index=["A", "B"], columns=["A", "B"])
        m = _metrics({"A": 0.2, "B": 0.2}, corr=corr)
        assert m.max_risk_contribution_share == pytest.approx(0.5, abs=1e-6)
        assert m.risk_contribution_hhi == pytest.approx(0.5, abs=1e-6)
        assert m.effective_risk_contributors == pytest.approx(2.0, abs=1e-6)

    def test_correlated_equal_names_stay_symmetric(self):
        """Equal weight + equal vol → each name owns half the variance for ANY
        correlation (contributions are symmetric), so HHI stays 0.5 — this is
        the baseline the asymmetric cases below must beat."""
        for rho in (0.0, 0.5, 0.99):
            corr = pd.DataFrame([[1.0, rho], [rho, 1.0]], index=["A", "B"], columns=["A", "B"])
            m = _metrics({"A": 0.2, "B": 0.2}, corr=corr)
            assert m.risk_contribution_hhi == pytest.approx(0.5, abs=1e-6)
            assert m.effective_risk_contributors == pytest.approx(2.0, abs=1e-6)

    def test_small_high_vol_name_dominates_risk(self):
        """Risk concentration diverges from weight concentration: a small
        high-vol name (A: 25% of gross weight) can own most of the variance.
        max_risk_contribution_share must exceed its weight share materially."""
        corr = pd.DataFrame([[1.0, 0.0], [0.0, 1.0]], index=["A", "B"], columns=["A", "B"])
        m = _metrics({"A": 0.1, "B": 0.3}, vol={"A": 0.5, "B": 0.1}, corr=corr)
        # A: var = 0.01·0.25 = 0.0025; B: var = 0.09·0.01 = 0.0009 → A owns 73.5%
        assert m.max_risk_contribution_share == pytest.approx(0.0025 / 0.0034, abs=1e-3)
        assert m.max_risk_contribution_share > 0.7  # vs 0.25 weight share
        assert m.risk_contribution_hhi > 0.5
        assert m.effective_risk_contributors < 2.0

    def test_shares_bounded(self):
        """Shares are normalized: HHI in (0,1], max share in (0,1]."""
        rng = np.random.default_rng(7)
        weights = {f"S{i}": float(w) for i, w in enumerate(rng.uniform(-0.2, 0.2, 6))}
        n = len(weights)
        corr = pd.DataFrame(rng.uniform(-0.3, 0.3, (n, n)), index=list(weights), columns=list(weights))
        np.fill_diagonal(corr.values, 1.0)
        m = _metrics(weights, corr=corr)
        assert 0.0 < m.risk_contribution_hhi <= 1.0
        assert 0.0 < m.max_risk_contribution_share <= 1.0
        assert m.effective_risk_contributors >= 1.0

    def test_recorded_in_to_dict(self):
        m = _metrics({"A": 0.2, "B": -0.1})
        d = m.to_dict()
        assert "risk_contribution_hhi" in d
        assert "max_risk_contribution_share" in d
        assert "effective_risk_contributors" in d
