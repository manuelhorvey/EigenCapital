"""Exposure model tests (brief Section 18 — FX exposure)."""

from __future__ import annotations

import pytest

from eigencapital.shadow.portfolio.exposure import (
    ExposureModel,
    ExposureModelConfig,
    get_currencies,
    get_factor_group,
)


class TestCurrencyExposure:
    def test_audusd_long(self):
        model = ExposureModel()
        exp = model.currency_exposure({"AUDUSD": 0.2})
        assert exp["AUD"] == pytest.approx(0.2)
        assert exp["USD"] == pytest.approx(-0.2)

    def test_audusd_short(self):
        model = ExposureModel()
        exp = model.currency_exposure({"AUDUSD": -0.2})
        assert exp["AUD"] == pytest.approx(-0.2)
        assert exp["USD"] == pytest.approx(0.2)

    def test_eurusd_short(self):
        model = ExposureModel()
        exp = model.currency_exposure({"EURUSD": -0.3})
        assert exp["EUR"] == pytest.approx(-0.3)
        assert exp["USD"] == pytest.approx(0.3)

    def test_offsetting_exposures(self):
        """AUDUSD LONG + EURUSD SHORT leaves USD net ~zero (offsetting)."""
        model = ExposureModel()
        exp = model.currency_exposure({"AUDUSD": 0.2, "EURUSD": -0.2})
        assert exp["AUD"] == pytest.approx(0.2)
        assert exp["EUR"] == pytest.approx(-0.2)
        assert abs(exp.get("USD", 0.0)) < 1e-12

    def test_multi_currency_portfolio(self):
        model = ExposureModel()
        exp = model.currency_exposure({"AUDUSD": 0.1, "EURCHF": -0.2, "NZDUSD": 0.1})
        assert exp["AUD"] == pytest.approx(0.1)
        assert exp["EUR"] == pytest.approx(-0.2)
        assert exp["CHF"] == pytest.approx(0.2)
        assert exp["NZD"] == pytest.approx(0.1)
        # AUDUSD LONG -0.1 USD, NZDUSD LONG -0.1 USD; EURCHF SHORT has no USD leg.
        assert exp["USD"] == pytest.approx(-0.2)

    def test_single_leg_usd_quoted(self):
        """BTCUSD / US30 / XAUUSD are USD-quoted single-leg risk positions."""
        model = ExposureModel()
        exp = model.currency_exposure({"BTCUSD": 0.1, "US30": 0.05, "XAUUSD": 0.05})
        assert exp["USD"] == pytest.approx(-0.2)


class TestClassification:
    def test_get_currencies(self):
        assert get_currencies("AUDCHF") == ("AUD", "CHF")
        assert get_currencies("EURUSD") == ("EUR", "USD")
        assert get_currencies("BTCUSD") == ("", "")

    def test_factor_groups(self):
        assert get_factor_group("US30") == "equity_beta"
        assert get_factor_group("USTEC") == "equity_beta"
        assert get_factor_group("XAUUSD") == "safe_haven"
        assert get_factor_group("USOIL") == "commodity"
        assert get_factor_group("AUDUSD") == "commodity"  # commodity currency
        assert get_factor_group("USDJPY") == "safe_haven"  # JPY leg
        assert get_factor_group("EURUSD") == "risk_on"


class TestConcentration:
    def test_max_cluster_exposure(self):
        model = ExposureModel()
        name, share = model.max_cluster_exposure({"US30": 0.2, "USTEC": 0.2, "AUDUSD": 0.1})
        assert name == "equity_beta"
        assert share == pytest.approx(0.8)

    def test_concentration_summary(self):
        model = ExposureModel()
        summary = model.concentration_summary({"AUDUSD": 0.2, "EURUSD": -0.2})
        assert summary["max_currency_exposure"]["pct"] == pytest.approx(0.5)
        assert summary["gross"] == pytest.approx(0.4)

    def test_violates_currency_cap(self):
        model = ExposureModel(ExposureModelConfig(max_currency_exposure_pct=0.5))
        # Two AUD legs stack AUD to 100% of gross.
        reasons = model.violates({"AUDUSD": 0.2, "AUDCHF": 0.2})
        assert "currency_concentration" in reasons

    def test_violates_factor_cap(self):
        model = ExposureModel(ExposureModelConfig(max_factor_group_pct=0.5))
        reasons = model.violates({"US30": 0.2, "USTEC": 0.2})
        assert "factor_concentration" in reasons

    def test_no_violation_for_offsetting(self):
        model = ExposureModel(ExposureModelConfig(max_currency_exposure_pct=0.5))
        reasons = model.violates({"AUDUSD": 0.2, "EURUSD": -0.2, "USDJPY": -0.2})
        assert reasons == []
