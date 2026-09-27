"""Exposure model tests (brief Section 18 — FX exposure)."""

from __future__ import annotations

import pytest

from eigencapital.shadow.portfolio.exposure import (
    ExposureModel,
    ExposureModelConfig,
    classify_asset_class,
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

    def test_hk50_jp225_classified_as_index_equity_beta(self):
        """HK50/JP225 (admitted 2026-09-27) are single-leg indices in the
        equity_beta factor group — never 'other', never FX."""
        assert get_factor_group("HK50") == "equity_beta"
        assert get_factor_group("JP225") == "equity_beta"
        assert classify_asset_class("HK50") == "indices"
        assert classify_asset_class("JP225") == "indices"
        assert get_currencies("HK50") == ("", "")
        assert get_currencies("JP225") == ("", "")

    def test_shadow_classification_derived_from_canonical_map(self):
        """Drift guard: the shadow layer owns no symbol lists — classification
        must derive from the canonical ASSET_CLASS_MAP. Every admitted
        single-leg production symbol must classify to a real class here;
        'other' would mean the shadow layer silently diverged from config."""
        from eigencapital.config import load_config
        from eigencapital.live.portfolio_analytics import ASSET_CLASS_MAP

        config = load_config("production")
        single_leg = [sym for sym, cls in config.broker.allowed_symbols.items() if not cls.startswith("forex")]
        assert single_leg, "expected single-leg symbols in the production universe"
        for sym in single_leg:
            expected = ASSET_CLASS_MAP.get(sym)
            assert expected is not None, f"{sym} missing from canonical ASSET_CLASS_MAP"
            assert classify_asset_class(sym) == expected, f"shadow classification for {sym} diverged from canonical map"

    def test_new_canonical_entry_propagates_to_shadow(self):
        """A symbol added to the canonical map is classified by the shadow layer
        with NO shadow-side edit — the property that eliminates inline-list
        drift (e.g. US500 was previously only in the shadow copy)."""
        from eigencapital.live.portfolio_analytics import ASSET_CLASS_MAP

        assert "US500" in ASSET_CLASS_MAP
        assert classify_asset_class("US500") == ASSET_CLASS_MAP["US500"]
        assert get_factor_group("US500") == "equity_beta"


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
