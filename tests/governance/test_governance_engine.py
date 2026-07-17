from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from features.liquidity_regime import (
    classify_liquidity_regime,
    compute_liquidity_features,
    liquidity_governance_scalars,
    neutral_liquidity,
)
from features.macro_narrative import (
    MacroNarrativeFeatures,
    narrative_governance_scalars,
    neutral_narrative,
)


class TestNarrativeGovernanceScalars:
    def test_risk_on_returns_neutral(self):
        n = MacroNarrativeFeatures(
            week_start="2025-01-01",
            usd_strength_narrative=0.3,
            geopol_risk_score=0.3,
            fed_hawkishness=0.5,
            rbnz_hawkishness=0.5,
            rba_hawkishness=0.5,
            boj_intervention_risk=0.3,
            energy_crisis_pressure=0.3,
            usd_bias="neutral",
            nzd_bias="neutral",
            aud_bias="neutral",
            jpy_bias="neutral",
            cad_bias="neutral",
            eur_bias="neutral",
            key_events=[],
            overall_regime="risk_on",
            confidence=0.8,
        )
        s = narrative_governance_scalars(n, geopol_sl_widen_pct=10, risk_off_size_reduce_pct=20, min_confidence=0.6)
        assert s["sl_mult"] == 1.0
        assert s["size_scalar"] == 1.0

    def test_risk_off_reduces_size(self):
        n = MacroNarrativeFeatures(
            week_start="2025-01-01",
            usd_strength_narrative=0.3,
            geopol_risk_score=0.3,
            fed_hawkishness=0.5,
            rbnz_hawkishness=0.5,
            rba_hawkishness=0.5,
            boj_intervention_risk=0.3,
            energy_crisis_pressure=0.3,
            usd_bias="neutral",
            nzd_bias="neutral",
            aud_bias="neutral",
            jpy_bias="neutral",
            cad_bias="neutral",
            eur_bias="neutral",
            key_events=[],
            overall_regime="risk_off",
            confidence=0.8,
        )
        s = narrative_governance_scalars(n, geopol_sl_widen_pct=10, risk_off_size_reduce_pct=20, min_confidence=0.6)
        assert s["sl_mult"] == 1.0
        assert s["size_scalar"] == pytest.approx(0.80)

    def test_high_geopol_widens_sl(self):
        n = MacroNarrativeFeatures(
            week_start="2025-01-01",
            usd_strength_narrative=0.4,
            geopol_risk_score=0.85,
            fed_hawkishness=0.5,
            rbnz_hawkishness=0.5,
            rba_hawkishness=0.5,
            boj_intervention_risk=0.7,
            energy_crisis_pressure=0.6,
            usd_bias="neutral",
            nzd_bias="neutral",
            aud_bias="neutral",
            jpy_bias="neutral",
            cad_bias="neutral",
            eur_bias="neutral",
            key_events=["event"],
            overall_regime="geopol_tension",
            confidence=0.8,
        )
        s = narrative_governance_scalars(n, geopol_sl_widen_pct=10, risk_off_size_reduce_pct=20, min_confidence=0.6)
        assert s["sl_mult"] == pytest.approx(1.10)
        assert s["size_scalar"] == 1.0

    def test_below_min_confidence_returns_neutral(self):
        n = MacroNarrativeFeatures(
            week_start="2025-01-01",
            usd_strength_narrative=0.3,
            geopol_risk_score=0.85,
            fed_hawkishness=0.5,
            rbnz_hawkishness=0.5,
            rba_hawkishness=0.5,
            boj_intervention_risk=0.3,
            energy_crisis_pressure=0.3,
            usd_bias="neutral",
            nzd_bias="neutral",
            aud_bias="neutral",
            jpy_bias="neutral",
            cad_bias="neutral",
            eur_bias="neutral",
            key_events=[],
            overall_regime="risk_off",
            confidence=0.5,
        )
        s = narrative_governance_scalars(n, geopol_sl_widen_pct=10, risk_off_size_reduce_pct=20, min_confidence=0.6)
        assert s["sl_mult"] == 1.0
        assert s["size_scalar"] == 1.0

    def test_stale_returns_neutral(self):
        n = MacroNarrativeFeatures(
            week_start="2025-01-01",
            usd_strength_narrative=0.3,
            geopol_risk_score=0.85,
            fed_hawkishness=0.5,
            rbnz_hawkishness=0.5,
            rba_hawkishness=0.5,
            boj_intervention_risk=0.3,
            energy_crisis_pressure=0.3,
            usd_bias="neutral",
            nzd_bias="neutral",
            aud_bias="neutral",
            jpy_bias="neutral",
            cad_bias="neutral",
            eur_bias="neutral",
            key_events=[],
            overall_regime="risk_off",
            confidence=0.8,
        )
        s = narrative_governance_scalars(
            n, geopol_sl_widen_pct=10, risk_off_size_reduce_pct=20, min_confidence=0.6, stale=True
        )
        assert s["sl_mult"] == 1.0
        assert s["size_scalar"] == 1.0


class TestNeutralNarrative:
    def test_returns_defaults(self):
        n = neutral_narrative("2025-01-01")
        assert n.week_start == "2025-01-01"
        assert n.overall_regime == "data_driven"
        assert n.confidence == 0.5
        assert n.geopol_risk_score == 0.3


class TestComputeLiquidityFeatures:
    @pytest.fixture
    def sample_df(self):
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(100) * 0.5)
        return pd.DataFrame(
            {
                "close": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "volume": np.where(
                    np.random.rand(100) < 0.05, 0, 1_000_000 + np.random.randint(-100_000, 100_000, 100)
                ),
            }
        )

    def test_returns_expected_keys(self, sample_df):
        f = compute_liquidity_features(sample_df, window=21)
        assert "volume_z" in f
        assert "amihud_z" in f
        assert "spread_est_bps" in f

    def test_short_dataframe_returns_neutral(self):
        df = pd.DataFrame({"close": [100], "high": [101], "low": [99], "volume": [1_000_000]})
        f = compute_liquidity_features(df, window=21)
        assert f["volume_z"] == 0.0
        assert f["amihud_z"] == 0.0
        assert f["spread_est_bps"] == 0.0

    def test_zero_volume_does_not_crash(self):
        df = pd.DataFrame(
            {
                "close": np.linspace(100, 105, 50),
                "high": np.linspace(101, 106, 50),
                "low": np.linspace(99, 104, 50),
                "volume": np.zeros(50),
            }
        )
        f = compute_liquidity_features(df, window=21)
        assert isinstance(f["volume_z"], float)


class TestClassifyLiquidityRegime:
    def test_normal_by_default(self):
        r = classify_liquidity_regime({"volume_z": 0.0, "amihud_z": 0.0})
        assert r == "NORMAL"

    def test_volume_below_thin_threshold(self):
        r = classify_liquidity_regime({"volume_z": -1.6, "amihud_z": 0.0}, vol_thin_threshold=-1.5)
        assert r == "THIN"

    def test_volume_below_stressed_threshold(self):
        r = classify_liquidity_regime({"volume_z": -2.6, "amihud_z": 0.0}, vol_stressed_threshold=-2.5)
        assert r == "STRESSED"

    def test_stressed_takes_priority(self):
        r = classify_liquidity_regime(
            {"volume_z": -2.6, "amihud_z": 2.0}, vol_stressed_threshold=-2.5, amihud_high_threshold=1.5
        )
        assert r == "STRESSED"

    def test_amihud_high_triggers_thin(self):
        r = classify_liquidity_regime({"volume_z": 0.0, "amihud_z": 2.0}, amihud_high_threshold=1.5)
        assert r == "THIN"

    def test_amihud_stressed_triggers_stressed(self):
        r = classify_liquidity_regime({"volume_z": 0.0, "amihud_z": 3.5}, amihud_stressed_threshold=3.0)
        assert r == "STRESSED"

    def test_exactly_at_threshold_is_thin(self):
        r = classify_liquidity_regime({"volume_z": -1.5, "amihud_z": 0.0}, vol_thin_threshold=-1.5)
        assert r == "THIN"

    def test_just_above_threshold_is_normal(self):
        r = classify_liquidity_regime({"volume_z": -1.49, "amihud_z": 0.0}, vol_thin_threshold=-1.5)
        assert r == "NORMAL"


class TestLiquidityGovernanceScalars:
    def test_normal_returns_neutral(self):
        s = liquidity_governance_scalars("NORMAL")
        assert s["sl_mult"] == 1.0
        assert s["size_scalar"] == 1.0
        assert s["halted"] is False

    def test_thin_widens_sl_and_reduces_size(self):
        s = liquidity_governance_scalars("THIN", thin_sl_widen_pct=15, thin_size_reduce_pct=15)
        assert s["sl_mult"] == pytest.approx(1.15)
        assert s["size_scalar"] == pytest.approx(0.85)
        assert s["halted"] is False

    def test_stressed_widens_sl_and_reduces_size_and_halts(self):
        s = liquidity_governance_scalars("STRESSED", stressed_sl_widen_pct=30, stressed_size_reduce_pct=30)
        assert s["sl_mult"] == pytest.approx(1.30)
        assert s["size_scalar"] == pytest.approx(0.70)
        assert s["halted"] is True

    def test_custom_pcts(self):
        s = liquidity_governance_scalars("THIN", thin_sl_widen_pct=5, thin_size_reduce_pct=10)
        assert s["sl_mult"] == pytest.approx(1.05)
        assert s["size_scalar"] == pytest.approx(0.90)


class TestNeutralLiquidity:
    def test_returns_normal(self):
        n = neutral_liquidity()
        assert n.regime == "NORMAL"
        assert n.sl_mult == 1.0
        assert n.size_scalar == 1.0
        assert n.halted is False


class TestMalformedLLMOutput:
    def test_neutral_narrative_is_safe_fallback(self):
        n = neutral_narrative("2025-01-01")
        assert n.overall_regime == "data_driven"
        assert n.confidence == 0.5
        s = narrative_governance_scalars(n, min_confidence=0.6)
        assert s["sl_mult"] == 1.0
        assert s["size_scalar"] == 1.0

    def test_missing_fields_construct_from_dict(self):
        data = {"week_start": "2025-01-01"}
        with pytest.raises(TypeError):
            MacroNarrativeFeatures(**data)

    def test_partial_dict_with_defaults(self):
        n = MacroNarrativeFeatures(
            week_start="2025-01-01",
            usd_strength_narrative=0.0,
            geopol_risk_score=0.0,
            fed_hawkishness=0.0,
            rbnz_hawkishness=0.0,
            rba_hawkishness=0.0,
            boj_intervention_risk=0.0,
            energy_crisis_pressure=0.0,
            usd_bias="neutral",
            nzd_bias="neutral",
            aud_bias="neutral",
            jpy_bias="neutral",
            cad_bias="neutral",
            eur_bias="neutral",
            key_events=[],
            overall_regime="data_driven",
            confidence=0.0,
        )
        s = narrative_governance_scalars(n, min_confidence=0.6)
        assert s["sl_mult"] == 1.0
        assert s["size_scalar"] == 1.0


class TestIsNarrativeStale:
    def test_recent_not_stale(self):
        today = datetime.now().strftime("%Y-%m-%d")
        from features.fxstreet_fetcher import is_narrative_stale

        assert is_narrative_stale(today) is False

    def test_older_than_week_is_stale(self):
        old = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
        from features.fxstreet_fetcher import is_narrative_stale

        assert is_narrative_stale(old) is True

    def test_exactly_7_days_is_stale(self):
        old = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        from features.fxstreet_fetcher import is_narrative_stale

        assert is_narrative_stale(old) is True


class TestRegimeConvictionFlipGate:
    def test_high_model_confidence_allows_flip(self):
        from paper_trading.governance.conviction_gate import evaluate_regime_conviction_gate, RegimeRow

        # High confidence (e.g. 0.85 >= 0.50 threshold) should bypass the gate
        row = RegimeRow(P_trend=0.1, P_range=0.8, P_volatile=0.1, regime_label="range")
        allowed, reason = evaluate_regime_conviction_gate(
            regime_row=row,
            model_confidence=85.0,  # percentage
            bars_in_current_regime=1,
            regime_margin_threshold=0.35,
            confidence_threshold=0.50,
            min_bars_in_regime=3,
        )
        assert allowed is True
        assert "high_model_confidence" in reason

    def test_no_regime_row_allows_flip(self):
        from paper_trading.governance.conviction_gate import evaluate_regime_conviction_gate

        allowed, reason = evaluate_regime_conviction_gate(
            regime_row=None,
            model_confidence=30.0,  # low confidence
            bars_in_current_regime=5,
            regime_margin_threshold=0.35,
            confidence_threshold=0.50,
            min_bars_in_regime=3,
        )
        assert allowed is True
        assert "no_regime_data" in reason

    def test_insufficient_bars_in_regime_blocks_flip(self):
        from paper_trading.governance.conviction_gate import evaluate_regime_conviction_gate, RegimeRow

        row = RegimeRow(P_trend=0.8, P_range=0.1, P_volatile=0.1, regime_label="trend")
        allowed, reason = evaluate_regime_conviction_gate(
            regime_row=row,
            model_confidence=30.0,
            bars_in_current_regime=2,  # < 3 min_bars_in_regime
            regime_margin_threshold=0.35,
            confidence_threshold=0.50,
            min_bars_in_regime=3,
        )
        assert allowed is False
        assert "regime_duration_insufficient" in reason

    def test_non_trend_regime_blocks_flip(self):
        from paper_trading.governance.conviction_gate import evaluate_regime_conviction_gate, RegimeRow

        row = RegimeRow(P_trend=0.1, P_range=0.8, P_volatile=0.1, regime_label="range")
        allowed, reason = evaluate_regime_conviction_gate(
            regime_row=row,
            model_confidence=30.0,
            bars_in_current_regime=5,
            regime_margin_threshold=0.35,
            confidence_threshold=0.50,
            min_bars_in_regime=3,
        )
        assert allowed is False
        assert "regime_not_trend" in reason

    def test_insufficient_trend_margin_blocks_flip(self):
        from paper_trading.governance.conviction_gate import evaluate_regime_conviction_gate, RegimeRow

        # Trend is dominant but P_trend - P_range is 0.45 - 0.35 = 0.10 (< 0.35 threshold)
        row = RegimeRow(P_trend=0.45, P_range=0.35, P_volatile=0.20, regime_label="trend")
        allowed, reason = evaluate_regime_conviction_gate(
            regime_row=row,
            model_confidence=30.0,
            bars_in_current_regime=5,
            regime_margin_threshold=0.35,
            confidence_threshold=0.50,
            min_bars_in_regime=3,
        )
        assert allowed is False
        assert "trend_margin_insufficient" in reason

    def test_decisive_trend_allows_flip(self):
        from paper_trading.governance.conviction_gate import evaluate_regime_conviction_gate, RegimeRow

        # Trend is dominant and P_trend - P_range is 0.70 - 0.20 = 0.50 (>= 0.35 threshold)
        row = RegimeRow(P_trend=0.70, P_range=0.20, P_volatile=0.10, regime_label="trend")
        allowed, reason = evaluate_regime_conviction_gate(
            regime_row=row,
            model_confidence=30.0,
            bars_in_current_regime=5,
            regime_margin_threshold=0.35,
            confidence_threshold=0.50,
            min_bars_in_regime=3,
        )
        assert allowed is True
        assert "decisive_trend_regime" in reason
