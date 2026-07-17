"""Tests for governance/drift.py — all 5 drift dimensions and aggregation."""

from __future__ import annotations


from paper_trading.governance import drift


# ── Helper: build a shadow event dict ───────────────────────────────────


def _make_event(
    proba_short=0.3,
    proba_neutral=0.4,
    proba_long=0.3,
    signal_match=True,
    flip_reason=None,
    original_pnl=100.0,
    computed_pnl=100.0,
    regime="low_vol",
    features=None,
):
    event = {
        "model_divergence": {
            "current": {
                "proba_short": proba_short,
                "proba_neutral": proba_neutral,
                "proba_long": proba_long,
            }
        },
        "signal_divergence": {
            "match": signal_match,
        },
        "pnl_decomposition": {
            "original_pnl": original_pnl,
            "computed_pnl": computed_pnl,
        },
        "regime_context": {
            "volatility_regime": regime,
        },
        "feature_drivers": [{"feature": f} for f in (features or ["feature_a"])],
    }
    if flip_reason:
        event["signal_divergence"]["flip_reason"] = flip_reason
    return event


# ── KL divergence and histogram helpers ─────────────────────────────────


class TestKlDivergence:
    def test_identical_distributions(self):
        assert drift._kl_divergence([1, 0, 0], [1, 0, 0]) == 0.0

    def test_different_distributions(self):
        kl = drift._kl_divergence([1, 0, 0], [0, 1, 0])
        assert kl > 0.0

    def test_zero_sum_p_returns_zero(self):
        assert drift._kl_divergence([0, 0], [1, 1]) == 0.0


class TestJaccardSimilarity:
    def test_identical_sets(self):
        assert drift._jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert drift._jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_both_empty_returns_one(self):
        assert drift._jaccard_similarity(set(), set()) == 1.0

    def test_one_empty_returns_zero(self):
        assert drift._jaccard_similarity({"a"}, set()) == 0.0


# ── extract helpers ─────────────────────────────────────────────────────


class TestExtractProbas:
    def test_extracts_probas(self):
        events = [_make_event(proba_short=0.3, proba_neutral=0.4, proba_long=0.3)]
        short, neutral, long_ = drift._extract_probas(events)
        assert short == [0.3]
        assert neutral == [0.4]
        assert long_ == [0.3]

    def test_skips_events_without_model_divergence(self):
        events = [{"no_model": True}]
        short, neutral, long_ = drift._extract_probas(events)
        assert short == []
        assert neutral == []
        assert long_ == []


class TestExtractSignalMismatches:
    def test_all_matching(self):
        events = [_make_event(signal_match=True) for _ in range(10)]
        total, mismatches, flips = drift._extract_signal_mismatches(events)
        assert total == 10
        assert mismatches == 0
        assert flips == 0

    def test_some_mismatches(self):
        events = [_make_event(signal_match=True) for _ in range(8)]
        events.append(_make_event(signal_match=False))
        events.append(_make_event(signal_match=False, flip_reason="direction_flip"))
        total, mismatches, flips = drift._extract_signal_mismatches(events)
        assert total == 10
        assert mismatches == 2
        assert flips == 1


# ── compute_model_drift ─────────────────────────────────────────────────


class TestComputeModelDrift:
    def test_insufficient_data_returns_zero(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [])
        result = drift.compute_model_drift("EURUSD")
        assert result["score"] == 0.0
        assert result["status"] == "insufficient_data"

    def test_no_baseline_returns_zero(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [_make_event()])
        result = drift.compute_model_drift("EURUSD")
        assert result["score"] == 0.0
        assert result["status"] == "no_baseline"

    def test_perfect_match_with_baseline(self, monkeypatch):
        monkeypatch.setattr(
            drift,
            "read_events",
            lambda asset, **kw: [_make_event(proba_short=0.3, proba_neutral=0.4, proba_long=0.3) for _ in range(10)],
        )
        baseline = {
            "model_proba_distribution": {
                "short": [0.3] * 10,
                "neutral": [0.4] * 10,
                "long": [0.3] * 10,
            }
        }
        result = drift.compute_model_drift("EURUSD", baseline=baseline)
        assert result["status"] == "ok"
        assert result["score"] < 0.1

    def test_drift_detected(self, monkeypatch):
        monkeypatch.setattr(
            drift,
            "read_events",
            lambda asset, **kw: [_make_event(proba_short=0.9, proba_neutral=0.05, proba_long=0.05) for _ in range(10)],
        )
        baseline = {
            "model_proba_distribution": {
                "short": [0.3] * 10,
                "neutral": [0.4] * 10,
                "long": [0.3] * 10,
            }
        }
        result = drift.compute_model_drift("EURUSD", baseline=baseline)
        assert result["status"] == "ok"
        assert result["score"] > 0.1


# ── compute_signal_drift ───────────────────────────────────────────────


class TestComputeSignalDrift:
    def test_no_events_returns_zero(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [])
        result = drift.compute_signal_drift("EURUSD")
        assert result["status"] == "insufficient_data"

    def test_no_baseline_returns_mismatch_rate(self, monkeypatch):
        events = [_make_event(signal_match=False) for _ in range(3)] + [
            _make_event(signal_match=True) for _ in range(7)
        ]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        result = drift.compute_signal_drift("EURUSD")
        assert result["status"] == "no_baseline"
        assert result["mismatch_rate"] == 0.3

    def test_mismatch_with_baseline(self, monkeypatch):
        events = [_make_event(signal_match=False) for _ in range(3)] + [
            _make_event(signal_match=True) for _ in range(7)
        ]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        baseline = {"signal_distribution": {"mismatch_rate": 0.1}}
        result = drift.compute_signal_drift("EURUSD", baseline=baseline)
        assert result["status"] == "ok"
        assert result["score"] > 0


# ── compute_pnl_drift ──────────────────────────────────────────────────


class TestComputePnlDrift:
    def test_insufficient_data(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [])
        result = drift.compute_pnl_drift("EURUSD")
        assert result["status"] == "insufficient_data"

    def test_no_baseline_returns_mae(self, monkeypatch):
        events = [_make_event(original_pnl=100.0, computed_pnl=105.0) for _ in range(5)]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        result = drift.compute_pnl_drift("EURUSD")
        assert result["status"] == "no_baseline"
        assert result["mae"] > 0

    def test_pnl_drift_scored(self, monkeypatch):
        events = [_make_event(original_pnl=100.0, computed_pnl=150.0) for _ in range(5)]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        baseline = {"pnl_mismatch_stats": {"mean_abs_error": 5.0}}
        result = drift.compute_pnl_drift("EURUSD", baseline=baseline)
        assert result["status"] == "ok"
        assert result["score"] > 0


# ── compute_feature_stability ──────────────────────────────────────────


class TestComputeFeatureStability:
    def test_insufficient_data(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [])
        result = drift.compute_feature_stability("EURUSD")
        assert result["status"] == "insufficient_data"

    def test_stable_features(self, monkeypatch):
        events = [_make_event(features=["a", "b", "c"]) for _ in range(10)]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        result = drift.compute_feature_stability("EURUSD")
        assert result["status"] == "ok"
        assert result["score"] < 0.5  # stable = low score

    def test_unstable_features(self, monkeypatch):
        features_list = [["a", "b", "c"], ["d", "e", "f"], ["g", "h", "i"], ["j", "k", "l"], ["m", "n", "o"]]
        events = [_make_event(features=f) for f in features_list]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        result = drift.compute_feature_stability("EURUSD")
        assert result["status"] == "ok"
        assert result["score"] > 0.5  # unstable = high score


# ── compute_regime_consistency ─────────────────────────────────────────


class TestComputeRegimeConsistency:
    def test_no_events(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [])
        result = drift.compute_regime_consistency("EURUSD")
        assert result["status"] == "insufficient_data"

    def test_identical_to_baseline(self, monkeypatch):
        events = [_make_event(regime="low_vol") for _ in range(10)]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        baseline = {"regime_distribution": {"low_vol": 10}}
        result = drift.compute_regime_consistency("EURUSD", baseline=baseline)
        assert result["status"] == "ok"
        assert result["score"] < 0.1
        assert result["mode_match"]

    def test_different_from_baseline(self, monkeypatch):
        events = [_make_event(regime="high_vol") for _ in range(10)]
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: events)
        baseline = {"regime_distribution": {"low_vol": 10}}
        result = drift.compute_regime_consistency("EURUSD", baseline=baseline)
        assert result["score"] > 0.5
        assert not result["mode_match"]


# ── get_shadow_intelligence ─────────────────────────────────────────────


class TestGetShadowIntelligence:
    def test_aggregates_all_scores(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [_make_event() for _ in range(10)])
        monkeypatch.setattr(drift, "load_baseline", lambda asset: None)

        result = drift.get_shadow_intelligence("EURUSD")
        assert "drift_scores" in result
        assert all(
            k in result["drift_scores"]
            for k in ["model_drift", "signal_drift", "pnl_drift", "feature_stability", "regime_consistency"]
        )
        assert result["trend"] in ("stable", "degrading")
        assert result["risk_flag"] in ("low", "medium", "high")

    def test_low_drift_stable_trend(self, monkeypatch):
        monkeypatch.setattr(drift, "read_events", lambda asset, **kw: [_make_event() for _ in range(10)])
        monkeypatch.setattr(drift, "load_baseline", lambda asset: {"event_count": 10})

        # Ensure all compute functions return low scores via matching baseline
        baseline = {
            "event_count": 10,
            "model_proba_distribution": {"short": [0.3] * 10, "neutral": [0.4] * 10, "long": [0.3] * 10},
            "signal_distribution": {"mismatch_rate": 0.1},
            "pnl_mismatch_stats": {"mean_abs_error": 5.0},
            "regime_distribution": {"low_vol": 10},
        }
        result = drift.get_shadow_intelligence("EURUSD", baseline=baseline)
        assert result["trend"] == "stable"
        assert result["risk_flag"] == "low"
