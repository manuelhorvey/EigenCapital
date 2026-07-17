import json
import pytest

from features.macro_narrative import (
    MacroNarrativeFeatures,
    narrative_governance_scalars,
    neutral_narrative,
    load_narrative_json,
    save_narrative_json,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def default_features():
    return MacroNarrativeFeatures(
        week_start="2026-05-25",
        usd_strength_narrative=0.7,
        geopol_risk_score=0.3,
        fed_hawkishness=0.8,
        rbnz_hawkishness=0.4,
        rba_hawkishness=0.4,
        boj_intervention_risk=0.2,
        energy_crisis_pressure=0.3,
        usd_bias="bullish",
        nzd_bias="neutral",
        aud_bias="neutral",
        jpy_bias="bearish",
        cad_bias="neutral",
        eur_bias="bearish",
        key_events=["FOMC", "NFP"],
        overall_regime="data_driven",
        confidence=0.75,
    )


# ── MacroNarrativeFeatures ───────────────────────────────────────────────────


class TestMacroNarrativeFeatures:
    def test_to_dict(self, default_features):
        d = default_features.to_dict()
        assert isinstance(d, dict)
        assert d["week_start"] == "2026-05-25"
        assert d["usd_bias"] == "bullish"
        assert d["key_events"] == ["FOMC", "NFP"]

    def test_to_feature_vector_returns_all_keys(self, default_features):
        v = default_features.to_feature_vector()
        expected_keys = [
            "usd_strength_narr",
            "geopol_risk",
            "fed_hawk",
            "rbnz_hawk",
            "rba_hawk",
            "boj_intervene_risk",
            "energy_pressure",
            "usd_bias_num",
            "nzd_bias_num",
            "aud_bias_num",
            "jpy_bias_num",
            "cad_bias_num",
            "eur_bias_num",
            "regime_risk_on",
            "regime_geopol",
        ]
        for k in expected_keys:
            assert k in v, f"Missing key: {k}"

    def test_to_feature_vector_bias_mapping(self, default_features):
        v = default_features.to_feature_vector()
        assert v["usd_bias_num"] == 1.0
        assert v["nzd_bias_num"] == 0.0
        assert v["jpy_bias_num"] == -1.0

    def test_to_feature_vector_regime_one_hot(self):
        features = MacroNarrativeFeatures(
            week_start="2026-05-25",
            usd_strength_narrative=0.5,
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
        v = features.to_feature_vector()
        assert v["regime_risk_on"] == 1.0
        assert v["regime_geopol"] == 0.0

    def test_to_feature_vector_geopol_regime(self):
        features = MacroNarrativeFeatures(
            week_start="2026-05-25",
            usd_strength_narrative=0.5,
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
            overall_regime="geopol_tension",
            confidence=0.8,
        )
        v = features.to_feature_vector()
        assert v["regime_risk_on"] == 0.0
        assert v["regime_geopol"] == 1.0

    def test_to_feature_vector_unknown_bias_defaults_zero(self):
        features = MacroNarrativeFeatures(
            week_start="2026-05-25",
            usd_strength_narrative=0.5,
            geopol_risk_score=0.3,
            fed_hawkishness=0.5,
            rbnz_hawkishness=0.5,
            rba_hawkishness=0.5,
            boj_intervention_risk=0.3,
            energy_crisis_pressure=0.3,
            usd_bias="extreme_bullish",
            nzd_bias="neutral",
            aud_bias="neutral",
            jpy_bias="neutral",
            cad_bias="neutral",
            eur_bias="neutral",
            key_events=[],
            overall_regime="data_driven",
            confidence=0.5,
        )
        v = features.to_feature_vector()
        assert v["usd_bias_num"] == 0.0


# ── narrative_governance_scalars ─────────────────────────────────────────────


class TestNarrativeGovernanceScalars:
    def test_normal_returns_defaults(self, default_features):
        result = narrative_governance_scalars(default_features)
        assert result["sl_mult"] == 1.0
        assert result["size_scalar"] == 1.0

    def test_stale_returns_defaults(self, default_features):
        result = narrative_governance_scalars(default_features, stale=True)
        assert result["sl_mult"] == 1.0
        assert result["size_scalar"] == 1.0

    def test_low_confidence_returns_defaults(self, default_features):
        default_features.confidence = 0.5
        result = narrative_governance_scalars(default_features, min_confidence=0.6)
        assert result["sl_mult"] == 1.0
        assert result["size_scalar"] == 1.0

    def test_high_geopol_widens_sl(self, default_features):
        default_features.geopol_risk_score = 0.8
        result = narrative_governance_scalars(default_features)
        assert result["sl_mult"] == 1.10
        assert result["size_scalar"] == 1.0

    def test_risk_off_reduces_size(self, default_features):
        default_features.overall_regime = "risk_off"
        result = narrative_governance_scalars(default_features)
        assert result["sl_mult"] == 1.0
        assert result["size_scalar"] == 0.80

    def test_high_geopol_and_risk_off_combine(self, default_features):
        default_features.geopol_risk_score = 0.9
        default_features.overall_regime = "risk_off"
        result = narrative_governance_scalars(default_features)
        assert result["sl_mult"] == 1.10
        assert result["size_scalar"] == 0.80

    def test_custom_percentages(self, default_features):
        default_features.geopol_risk_score = 0.9
        default_features.overall_regime = "risk_off"
        result = narrative_governance_scalars(default_features, geopol_sl_widen_pct=25.0, risk_off_size_reduce_pct=35.0)
        assert result["sl_mult"] == 1.25
        assert result["size_scalar"] == 0.65

    def test_geopol_boundary_below_threshold(self, default_features):
        default_features.geopol_risk_score = 0.7
        result = narrative_governance_scalars(default_features)
        assert result["sl_mult"] == 1.0

    def test_geopol_boundary_above_threshold(self, default_features):
        default_features.geopol_risk_score = 0.71
        result = narrative_governance_scalars(default_features)
        assert result["sl_mult"] == 1.10

    def test_exact_min_confidence_boundary(self, default_features):
        default_features.confidence = 0.6
        result = narrative_governance_scalars(default_features, min_confidence=0.6)
        assert result["sl_mult"] == 1.0


# ── neutral_narrative ────────────────────────────────────────────────────────


class TestNeutralNarrative:
    def test_returns_default_values(self):
        result = neutral_narrative()
        assert result.usd_strength_narrative == 0.5
        assert result.geopol_risk_score == 0.3
        assert result.usd_bias == "neutral"
        assert result.overall_regime == "data_driven"
        assert result.confidence == 0.5
        assert result.key_events == []
        assert result.narrative_version == ""

    def test_with_custom_week_start(self):
        result = neutral_narrative(week_start="2026-06-01")
        assert result.week_start == "2026-06-01"

    def test_with_none_week_start_uses_today(self):
        result = neutral_narrative(week_start=None)
        from datetime import datetime

        assert result.week_start == datetime.now().strftime("%Y-%m-%d")


# ── load_narrative_json ──────────────────────────────────────────────────────


class TestLoadNarrativeJson:
    def test_success(self, tmp_path, default_features):
        path = tmp_path / "narrative.json"
        path.write_text(json.dumps(default_features.to_dict()))
        result = load_narrative_json(str(path))
        assert result.week_start == "2026-05-25"
        assert result.usd_bias == "bullish"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_narrative_json("/nonexistent/path.json")

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{invalid")
        with pytest.raises(json.JSONDecodeError):
            load_narrative_json(str(path))


# ── save_narrative_json ──────────────────────────────────────────────────────


class TestSaveNarrativeJson:
    def test_roundtrip(self, tmp_path, default_features):
        path = tmp_path / "narrative_out.json"
        save_narrative_json(str(path), default_features)
        result = load_narrative_json(str(path))
        assert result.week_start == "2026-05-25"
        assert result.confidence == 0.75
