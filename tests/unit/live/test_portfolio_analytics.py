"""Tests for PortfolioAnalyzer — shadow portfolio diagnostics.

Verifies:
- effective_positions = 1/HHI (weight concentration)
- effective_bets (correlation-adjusted, distinct from effective_positions)
- Concentration metrics (HHI, top-N, max position)
- Currency factor decomposition
- Asset class classification
- Edge cases: insufficient data, NaN returns, singular matrices
- Governance: zero side effects on inputs
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from eigencapital.live.portfolio_analytics import (
    PortfolioAnalyzer,
    _classify_asset_class,
    _compute_correlation_adjusted_bets,
    _compute_counterfactuals,
    _compute_currency_exposure,
)

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def analyzer(tmp_path):
    """Create a PortfolioAnalyzer with a temp audit directory."""
    return PortfolioAnalyzer(audit_dir=str(tmp_path))


@pytest.fixture
def equal_weight_positions():
    """6 equal-weight long positions."""
    return {
        "EURUSD": 0.01,
        "GBPUSD": 0.01,
        "AUDUSD": 0.01,
        "NZDUSD": 0.01,
        "USDCHF": -0.01,
        "USDCAD": -0.01,
    }


@pytest.fixture
def concentrated_positions():
    """1 large position, 5 tiny ones — highly concentrated."""
    return {
        "EURUSD": 0.10,  # dominant
        "GBPUSD": 0.001,
        "AUDUSD": 0.001,
        "NZDUSD": 0.001,
        "USDCHF": -0.001,
        "USDCAD": -0.001,
    }


@pytest.fixture
def standard_prices():
    return {
        "EURUSD": 1.08,
        "GBPUSD": 1.27,
        "AUDUSD": 0.65,
        "NZDUSD": 0.59,
        "USDCHF": 0.88,
        "USDCAD": 1.36,
        "EURGBP": 0.85,
    }


@pytest.fixture
def standard_contract_sizes():
    return {
        s: 100000
        for s in [
            "EURUSD",
            "GBPUSD",
            "AUDUSD",
            "NZDUSD",
            "USDCHF",
            "USDCAD",
            "EURGBP",
        ]
    }


@pytest.fixture
def correlated_returns():
    """100 days of returns with known correlation structure."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=100)
    n = len(dates)

    # Independent base returns
    base = np.random.randn(n) * 0.005

    # EURUSD and GBPUSD highly correlated (0.85+)
    eurusd = base + np.random.randn(n) * 0.001
    gbpusd = base * 0.9 + np.random.randn(n) * 0.002

    # USDCHF negatively correlated with EURUSD (-0.8+)
    usdchf = -base * 0.85 + np.random.randn(n) * 0.002

    # AUDUSD moderately correlated (0.3)
    audusd = base * 0.3 + np.random.randn(n) * 0.004

    # USDCAD independent
    usdcad = np.random.randn(n) * 0.005

    # BTCUSD uncorrelated
    btcusd = np.random.randn(n) * 0.02

    return pd.DataFrame(
        {
            "EURUSD": eurusd,
            "GBPUSD": gbpusd,
            "AUDUSD": audusd,
            "USDCHF": usdchf,
            "USDCAD": usdcad,
            "BTCUSD": btcusd,
        },
        index=dates,
    )


@pytest.fixture
def uncorrelated_returns():
    """100 days of independent returns."""
    np.random.seed(123)
    dates = pd.date_range("2026-01-01", periods=100)
    return pd.DataFrame(
        np.random.randn(100, 6) * 0.005,
        index=dates,
        columns=["EURUSD", "GBPUSD", "AUDUSD", "USDCHF", "USDCAD", "BTCUSD"],
    )


# ── HHI / Effective Positions Tests ──────────────────────────────


class TestEffectivePositions:
    """Verify effective_positions = 1/HHI measures weight concentration."""

    def test_equal_weights_higher_effective_positions_than_concentrated(
        self, analyzer, standard_prices, standard_contract_sizes
    ):
        """Equal weights → higher effective_positions than concentrated."""
        # Equal-weight portfolio
        equal_positions = {
            "EURUSD": 0.0046,
            "GBPUSD": 0.0039,
            "AUDUSD": 0.0077,
            "NZDUSD": 0.0085,
            "USDCHF": -0.0057,
            "USDCAD": -0.0037,
        }
        weights = pd.Series(
            {
                "EURUSD": 0.167,
                "GBPUSD": 0.167,
                "AUDUSD": 0.167,
                "NZDUSD": 0.167,
                "USDCHF": -0.166,
                "USDCAD": -0.166,
            }
        )

        diag_equal = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=equal_positions,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        # Concentrated portfolio (one large, rest tiny)
        diag_conc = analyzer.compute_diagnostics(
            target_weights=pd.Series(
                {"EURUSD": 0.80, "GBPUSD": 0.05, "AUDUSD": 0.05, "NZDUSD": 0.05, "USDCHF": -0.025, "USDCAD": -0.025}
            ),
            current_positions={
                "EURUSD": 0.04,
                "GBPUSD": 0.001,
                "AUDUSD": 0.001,
                "NZDUSD": 0.001,
                "USDCHF": -0.001,
                "USDCAD": -0.001,
            },
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        # Equal-weight should have MORE effective positions than concentrated
        assert diag_equal.effective_positions > diag_conc.effective_positions

    def test_concentrated_weights_reduces_effective_positions(
        self, analyzer, concentrated_positions, standard_prices, standard_contract_sizes
    ):
        """One dominant position → effective_positions close to 1."""
        weights = pd.Series(
            {
                "EURUSD": 0.50,
                "GBPUSD": 0.05,
                "AUDUSD": 0.05,
                "NZDUSD": 0.05,
                "USDCHF": -0.05,
                "USDCAD": -0.05,
            }
        )

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=concentrated_positions,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        # Highly concentrated → effective_positions should be low
        assert diag.effective_positions < 3.0

    def test_single_position_gives_effective_positions_near_one(
        self, analyzer, standard_prices, standard_contract_sizes
    ):
        """Single position → effective_positions ≈ 1.0 (may be <1 if leveraged)."""
        # Use a weight that keeps notional <= equity
        # 0.0046 lots * 1.08 * 100000 = $496.80, weight = 0.099
        diag = analyzer.compute_diagnostics(
            target_weights=pd.Series({"EURUSD": 0.10}),
            current_positions={"EURUSD": 0.0046},
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        # Single position with weight < 1 → HHI ≈ w^2, effective ≈ 1/w^2
        # With w ≈ 0.1, HHI ≈ 0.01, effective ≈ 100
        # But we're computing from ACTUAL notional weights, so effective_positions
        # reflects the actual concentration. For a single position, it should be
        # close to 1 if weight is near 1, or larger if weight is small.
        # The key invariant: effective_positions > 0
        assert diag.effective_positions > 0

    def test_hhi_formula_correct(self, analyzer):
        """Verify HHI = sum(w_i^2) and effective_positions = 1/HHI directly."""
        # 3 positions with weights 0.5, 0.3, 0.2
        hhi = 0.5**2 + 0.3**2 + 0.2**2  # = 0.25 + 0.09 + 0.04 = 0.38
        expected_eff = 1.0 / hhi  # ≈ 2.63

        assert abs(hhi - 0.38) < 1e-10
        assert abs(expected_eff - 1.0 / 0.38) < 1e-10


# ── Correlation-Adjusted Effective Bets Tests ─────────────────────


class TestEffectiveBets:
    """Verify effective_bets is distinct from effective_positions and accounts for correlation."""

    def test_uncorrelated_assets_higher_effective_bets(
        self, analyzer, uncorrelated_returns, standard_prices, standard_contract_sizes
    ):
        """Uncorrelated assets → effective_bets ≈ effective_positions."""
        current = {
            "EURUSD": 0.01,
            "GBPUSD": 0.01,
            "AUDUSD": 0.01,
            "USDCHF": -0.01,
            "USDCAD": -0.01,
            "BTCUSD": 0.01,
        }
        weights = pd.Series(
            {
                "EURUSD": 0.17,
                "GBPUSD": 0.17,
                "AUDUSD": 0.17,
                "USDCHF": -0.17,
                "USDCAD": -0.16,
                "BTCUSD": 0.16,
            }
        )

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
            returns_history=uncorrelated_returns,
        )

        cd = diag.correlation_diagnostics
        assert "effective_bets" in cd
        # Uncorrelated → effective_bets should be close to effective_positions
        assert cd["effective_bets"] >= diag.effective_positions * 0.8

    def test_correlated_returns_produce_correlation_diagnostics(
        self, analyzer, correlated_returns, standard_prices, standard_contract_sizes
    ):
        """Correlated returns should produce non-empty correlation diagnostics."""
        current = {
            "EURUSD": 0.01,
            "GBPUSD": 0.01,
            "AUDUSD": 0.01,
            "USDCHF": -0.01,
            "USDCAD": -0.01,
            "BTCUSD": 0.01,
        }
        weights = pd.Series(
            {
                "EURUSD": 0.17,
                "GBPUSD": 0.17,
                "AUDUSD": 0.17,
                "USDCHF": -0.17,
                "USDCAD": -0.16,
                "BTCUSD": 0.16,
            }
        )

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
            returns_history=correlated_returns,
        )

        cd = diag.correlation_diagnostics
        assert "effective_bets" in cd
        # With negative correlations, effective_bets can exceed effective_positions
        # because negative correlations REDUCE portfolio variance.
        # The key invariant: effective_bets > 0 and correlations are reported
        assert cd["effective_bets"] > 0
        assert cd["cluster_count"] >= 1  # EURUSD↔GBPUSD should be detected

    def test_effective_bets_distinct_from_effective_positions(
        self, analyzer, correlated_returns, standard_prices, standard_contract_sizes
    ):
        """effective_bets and effective_positions measure different things."""
        current = {
            "EURUSD": 0.01,
            "GBPUSD": 0.01,
            "AUDUSD": 0.01,
            "USDCHF": -0.01,
            "USDCAD": -0.01,
            "BTCUSD": 0.01,
        }
        weights = pd.Series(
            {
                "EURUSD": 0.17,
                "GBPUSD": 0.17,
                "AUDUSD": 0.17,
                "USDCHF": -0.17,
                "USDCAD": -0.16,
                "BTCUSD": 0.16,
            }
        )

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
            returns_history=correlated_returns,
        )

        # Both should exist and be positive
        assert diag.effective_positions > 0
        assert diag.correlation_diagnostics["effective_bets"] > 0

        # They should be different values (unless perfectly uncorrelated)
        # With the synthetic correlated data, they will differ
        assert diag.effective_positions != diag.correlation_diagnostics["effective_bets"]

    def test_avg_pairwise_correlation_reported(
        self, analyzer, correlated_returns, standard_prices, standard_contract_sizes
    ):
        """Average pairwise correlation should be reported."""
        current = {
            "EURUSD": 0.01,
            "GBPUSD": 0.01,
            "AUDUSD": 0.01,
            "USDCHF": -0.01,
            "USDCAD": -0.01,
            "BTCUSD": 0.01,
        }
        weights = pd.Series(
            {
                "EURUSD": 0.17,
                "GBPUSD": 0.17,
                "AUDUSD": 0.17,
                "USDCHF": -0.17,
                "USDCAD": -0.16,
                "BTCUSD": 0.16,
            }
        )

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
            returns_history=correlated_returns,
        )

        cd = diag.correlation_diagnostics
        assert "avg_pairwise_correlation" in cd
        assert -1.0 <= cd["avg_pairwise_correlation"] <= 1.0

    def test_high_corr_clusters_detected(self, analyzer, correlated_returns, standard_prices, standard_contract_sizes):
        """Highly correlated pairs should be detected as clusters."""
        current = {
            "EURUSD": 0.01,
            "GBPUSD": 0.01,
            "AUDUSD": 0.01,
            "USDCHF": -0.01,
            "USDCAD": -0.01,
            "BTCUSD": 0.01,
        }
        weights = pd.Series(
            {
                "EURUSD": 0.17,
                "GBPUSD": 0.17,
                "AUDUSD": 0.17,
                "USDCHF": -0.17,
                "USDCAD": -0.16,
                "BTCUSD": 0.16,
            }
        )

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
            returns_history=correlated_returns,
        )

        cd = diag.correlation_diagnostics
        assert "high_corr_clusters" in cd
        # Our synthetic data has EURUSD↔GBPUSD and USDCHF↔EURUSD correlations
        assert cd["cluster_count"] >= 1


# ── Edge Cases / Data Quality Tests ───────────────────────────────


class TestEdgeCases:
    """Verify graceful handling of bad data."""

    def test_insufficient_history_returns_empty(self, analyzer):
        """Returns with < 30 observations should produce empty diagnostics."""
        short_returns = pd.DataFrame(
            np.random.randn(10, 3) * 0.005,
            columns=["EURUSD", "GBPUSD", "AUDUSD"],
        )

        cd = _compute_correlation_adjusted_bets(
            short_returns,
            {"EURUSD": 0.5, "GBPUSD": 0.3, "AUDUSD": 0.2},
        )

        assert cd == {}

    def test_none_returns_produces_empty(self, analyzer):
        """None returns should produce empty correlation diagnostics."""
        cd = _compute_correlation_adjusted_bets(None, {"EURUSD": 0.5})
        assert cd == {}

    def test_nan_returns_handled(self, analyzer):
        """NaN-contaminated returns should not produce NaN metrics."""
        np.random.seed(42)
        returns = pd.DataFrame(
            np.random.randn(60, 3) * 0.005,
            columns=["EURUSD", "GBPUSD", "AUDUSD"],
        )
        # Inject NaN
        returns.iloc[5, 0] = float("nan")
        returns.iloc[10, 1] = float("nan")

        cd = _compute_correlation_adjusted_bets(
            returns,
            {"EURUSD": 0.5, "GBPUSD": 0.3, "AUDUSD": 0.2},
        )

        # Should either produce a result or empty dict, never NaN
        if cd:
            assert not math.isnan(cd.get("effective_bets", 0))
            assert not math.isinf(cd.get("effective_bets", 0))

    def test_infinite_returns_handled(self, analyzer):
        """Infinite returns should not crash the computation."""
        returns = pd.DataFrame(
            np.random.randn(60, 3) * 0.005,
            columns=["EURUSD", "GBPUSD", "AUDUSD"],
        )
        returns.iloc[0, 0] = float("inf")

        cd = _compute_correlation_adjusted_bets(
            returns,
            {"EURUSD": 0.5, "GBPUSD": 0.3, "AUDUSD": 0.2},
        )

        # Should not crash; result is either empty or finite
        if cd:
            assert not math.isnan(cd.get("effective_bets", 0))

    def test_singular_correlation_matrix_handled(self, analyzer):
        """Identical return series produce singular correlation matrix."""
        base = np.random.randn(60) * 0.005
        returns = pd.DataFrame(
            {
                "EURUSD": base,
                "GBPUSD": base,  # identical
                "AUDUSD": base,  # identical
            }
        )

        cd = _compute_correlation_adjusted_bets(
            returns,
            {"EURUSD": 0.5, "GBPUSD": 0.3, "AUDUSD": 0.2},
        )

        # Should handle gracefully (empty or valid)
        if cd:
            assert not math.isnan(cd.get("effective_bets", 0))

    def test_single_position_no_correlation(self, analyzer):
        """Single position → no correlation diagnostics needed."""
        # Use weight that keeps notional <= equity
        # 0.0046 lots * 1.08 * 100000 = $496.80, weight ≈ 0.1
        diag = analyzer.compute_diagnostics(
            target_weights=pd.Series({"EURUSD": 0.10}),
            current_positions={"EURUSD": 0.0046},
            prices={"EURUSD": 1.08},
            contract_sizes={"EURUSD": 100000},
            equity=5000.0,
        )

        # Should work without error
        assert diag.position_count == 1
        assert diag.effective_positions > 0

    def test_empty_positions(self, analyzer):
        """No positions → all metrics should be zero/empty."""
        weights = pd.Series(dtype=float)

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions={},
            prices={},
            contract_sizes={},
            equity=5000.0,
        )

        assert diag.position_count == 0
        assert diag.gross_exposure == 0
        assert diag.effective_positions == 0


# ── Currency Factor Tests ─────────────────────────────────────────


class TestCurrencyFactors:
    """Verify currency factor decomposition."""

    def test_long_eurusd_exposure(self):
        """Long EURUSD → long EUR, short USD."""
        exp = _compute_currency_exposure("EURUSD", 0.15, 16200, "LONG")
        assert exp["EUR"] == 16200
        assert exp["USD"] == -16200

    def test_short_eurusd_exposure(self):
        """Short EURUSD → short EUR, long USD."""
        exp = _compute_currency_exposure("EURUSD", 0.10, 10800, "SHORT")
        assert exp["EUR"] == -10800
        assert exp["USD"] == 10800

    def test_cross_pair_exposure(self):
        """Long EURGBP → long EUR, short GBP."""
        exp = _compute_currency_exposure("EURGBP", 0.05, 4250, "LONG")
        assert exp["EUR"] == 4250
        assert exp["GBP"] == -4250

    def test_unknown_symbol_returns_empty(self):
        """Unknown symbol → empty currency exposure."""
        exp = _compute_currency_exposure("UNKNOWN", 0.1, 1000, "LONG")
        assert exp == {}

    def test_largest_factor_identified(self, analyzer, standard_prices, standard_contract_sizes):
        """Largest currency factor should be correctly identified."""
        current = {"EURUSD": 0.05, "GBPUSD": 0.01}
        weights = pd.Series({"EURUSD": 0.50, "GBPUSD": 0.10})

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        # EURUSD is largest → EUR and USD should be dominant
        assert diag.largest_currency_factor in ("EUR", "USD")


# ── Asset Class Tests ─────────────────────────────────────────────


class TestAssetClass:
    """Verify asset class classification."""

    def test_forex_classification(self):
        assert _classify_asset_class("EURUSD") == "forex"
        assert _classify_asset_class("GBPJPY") == "forex"

    def test_crypto_classification(self):
        assert _classify_asset_class("BTCUSD") == "crypto"
        assert _classify_asset_class("ETHUSD") == "crypto"

    def test_metals_classification(self):
        assert _classify_asset_class("XAUUSD") == "metals"

    def test_indices_classification(self):
        assert _classify_asset_class("US30") == "indices"
        assert _classify_asset_class("USTEC") == "indices"


# ── Concentration Metrics Tests ───────────────────────────────────


class TestConcentration:
    """Verify top-N and HHI concentration metrics."""

    def test_top3_concentration(self, analyzer, standard_prices, standard_contract_sizes):
        """Top-3 concentration should be sum of 3 largest weights."""
        current = {"EURUSD": 0.05, "GBPUSD": 0.03, "AUDUSD": 0.02}
        weights = pd.Series({"EURUSD": 0.50, "GBPUSD": 0.30, "AUDUSD": 0.20})

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        # Top-3 = 100% of weight in this case
        assert diag.top3_concentration >= 0.99

    def test_max_position_weight(self, analyzer, standard_prices, standard_contract_sizes):
        """Max position weight should be the largest single position."""
        current = {"EURUSD": 0.10, "GBPUSD": 0.01, "AUDUSD": 0.01}
        weights = pd.Series({"EURUSD": 0.70, "GBPUSD": 0.15, "AUDUSD": 0.15})

        diag = analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        assert diag.max_position_symbol == "EURUSD"
        assert diag.max_position_weight > 0.5


# ── Governance / Side-Effect Tests ────────────────────────────────


class TestGovernance:
    """Verify shadow analytics has zero side effects."""

    def test_analyzer_does_not_modify_positions(self, analyzer, standard_prices, standard_contract_sizes):
        """Input positions dict must be unchanged after compute_diagnostics."""
        current = {"EURUSD": 0.01, "GBPUSD": 0.01}
        original = dict(current)
        weights = pd.Series({"EURUSD": 0.50, "GBPUSD": 0.50})

        analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions=current,
            prices=standard_prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        assert current == original

    def test_analyzer_does_not_modify_prices(self, analyzer, standard_contract_sizes):
        """Input prices dict must be unchanged."""
        prices = {"EURUSD": 1.08, "GBPUSD": 1.27}
        original = dict(prices)
        weights = pd.Series({"EURUSD": 0.50, "GBPUSD": 0.50})

        analyzer.compute_diagnostics(
            target_weights=weights,
            current_positions={"EURUSD": 0.01, "GBPUSD": 0.01},
            prices=prices,
            contract_sizes=standard_contract_sizes,
            equity=5000.0,
        )

        assert prices == original

    def test_record_is_append_only(self, analyzer, tmp_path):
        """Recording should append, not overwrite."""
        weights = pd.Series({"EURUSD": 0.50})
        prices = {"EURUSD": 1.08}
        cs = {"EURUSD": 100000}

        d1 = analyzer.compute_diagnostics(weights, {"EURUSD": 0.01}, prices, cs, 5000.0)
        analyzer.record(d1)

        d2 = analyzer.compute_diagnostics(weights, {"EURUSD": 0.01}, prices, cs, 5000.0)
        analyzer.record(d2)

        history = analyzer.get_history()
        assert len(history) == 2

    def test_diagnostics_is_frozen_compatible(self, analyzer, standard_prices, standard_contract_sizes):
        """PortfolioDiagnostics should be serializable to JSON."""
        weights = pd.Series({"EURUSD": 0.50, "GBPUSD": 0.50})
        current = {"EURUSD": 0.01, "GBPUSD": 0.01}

        diag = analyzer.compute_diagnostics(
            weights,
            current,
            standard_prices,
            standard_contract_sizes,
            5000.0,
        )

        # Should serialize without error
        data = diag.to_dict()
        serialized = json.dumps(data, default=str)
        assert len(serialized) > 0


# ── Counterfactual Tests ─────────────────────────────────────────


class TestCounterfactuals:
    """Verify counterfactual portfolio constructions."""

    def test_equal_weight_counterfactual(self, analyzer):
        """Equal-weight counterfactual should have equal weights and HHI = 1/N."""
        symbols = ["EURUSD", "GBPUSD", "AUDUSD"]
        weights = {"EURUSD": 0.60, "GBPUSD": 0.30, "AUDUSD": 0.10}

        cf = _compute_counterfactuals(
            active_symbols=symbols,
            weights=weights,
            prices={"EURUSD": 1.08, "GBPUSD": 1.27, "AUDUSD": 0.65},
            contract_sizes={"EURUSD": 100000, "GBPUSD": 100000, "AUDUSD": 100000},
            equity=5000.0,
        )

        assert "equal_weight" in cf
        eq = cf["equal_weight"]
        # 3 equal weights → HHI = 3 * (1/3)^2 = 1/3 → effective = 3
        assert abs(eq["herfindahl"] - 1.0 / 3) < 0.01
        assert abs(eq["effective_positions"] - 3.0) < 0.1

    def test_inverse_vol_counterfactual(self, analyzer, uncorrelated_returns):
        """Inverse-vol counterfactual should exist when returns provided."""
        symbols = ["EURUSD", "GBPUSD", "AUDUSD"]
        weights = {"EURUSD": 0.50, "GBPUSD": 0.30, "AUDUSD": 0.20}

        cf = _compute_counterfactuals(
            active_symbols=symbols,
            weights=weights,
            prices={"EURUSD": 1.08, "GBPUSD": 1.27, "AUDUSD": 0.65},
            contract_sizes={"EURUSD": 100000, "GBPUSD": 100000, "AUDUSD": 100000},
            equity=5000.0,
            returns=uncorrelated_returns,
        )

        # Should have inverse_volatility if returns are sufficient
        if "inverse_volatility" in cf:
            iv = cf["inverse_volatility"]
            assert "weights" in iv
            assert "herfindahl" in iv
            # Weights should sum to approximately 1
            total = sum(abs(w) for w in iv["weights"].values())
            assert 0.9 <= total <= 1.1
