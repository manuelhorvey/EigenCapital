"""Unit tests for R2-B1 — factor lab observation/panel assembly + evaluation.

Covers the frozen contract:
- forward-return alignment: factor(t) → close(t)→close(t+h), window starts
  AFTER the decision bar (anti-leakage)
- PIT invariant raises on violation
- missing-data policy: exclusion counted, never imputed
- cost-adjusted spread = gross − 2 × one-way × turnover
- verdicts: REJECTED / INCONCLUSIVE / CANDIDATE, never VALIDATED
- Holm correction wired through the declared trial family
- determinism
"""

from typing import List

import pytest

from eigencapital.core.costs import CostModel
from eigencapital.core.models.bar import Bar
from eigencapital.core.models.trial_metadata import TrialMetadata
from eigencapital.research.factor_lab.evaluation import (
    EvaluationError,
    evaluate_factor,
)
from eigencapital.research.factor_lab.observations import (
    FactorObservation,
    PanelBuildError,
    build_factor_panels,
)

FACTOR = "momentum_12_1"
UNIVERSE = "r4_local_v1"


def _bar(date: str, close: float) -> Bar:
    # Daily bar covering the PRIOR UTC day, closing at midnight of `date`:
    # bar_start < bar_end (Bar invariant), timestamp_utc == bar_end.
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    end = _date.fromisoformat(date)
    start = end - _timedelta(days=1)
    ts = f"{end.isoformat()}T00:00:00Z"
    return Bar(
        instrument_id="TEST",
        timestamp_utc=ts,
        bar_start_utc=f"{start.isoformat()}T00:00:00Z",
        bar_end_utc=ts,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        bar_interval="daily",
    )


def _date_seq(n: int, start: str = "2026-01-01") -> List[str]:
    """n consecutive ISO dates starting at `start` (real calendar)."""
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    d0 = _date.fromisoformat(start)
    return [(d0 + _timedelta(days=i)).isoformat() for i in range(n)]


def _calendar(n: int = 60) -> List[Bar]:
    """Rising-then-falling price path: early momentum is genuinely positive."""
    bars = []
    price = 100.0
    dates = _date_seq(n)
    for i, date in enumerate(dates):
        drift = 1.0 if i < n // 2 else -1.0
        price *= 1.0 + 0.01 * drift
        bars.append(_bar(date, price))
    return bars


def _signals(dates_and_values, availability=None):
    rows = []
    for date, value in dates_and_values:
        rows.append((date, value, availability or f"{date}T00:00:00Z"))
    return rows


class TestForwardReturnAlignment:
    def test_window_starts_after_decision_bar(self):
        """Anti-leakage: the return window must exclude the decision bar's close.

        Construct a path where close(t+1) is known and verify the h=1 forward
        return equals close(t+1)/close(t) − 1 exactly.
        """
        bars = [
            _bar("2026-01-01", 100.0),
            _bar("2026-01-02", 110.0),  # +10% after the decision bar
            _bar("2026-01-03", 121.0),
        ]
        panels = build_factor_panels(
            FACTOR,
            UNIVERSE,
            horizon=1,
            signals={"AAA": _signals([("2026-01-01", 1.0)])},
            bars_by_symbol={"AAA": bars},
        )
        assert panels.panels[0][0][1] == pytest.approx(0.10)

    def test_horizon_spans_h_closes(self):
        bars = [
            _bar("2026-01-01", 100.0),
            _bar("2026-01-02", 100.0),
            _bar("2026-01-03", 100.0),
            _bar("2026-01-04", 121.0),
        ]
        panels = build_factor_panels(
            FACTOR,
            UNIVERSE,
            horizon=3,
            signals={"AAA": _signals([("2026-01-01", 0.5)])},
            bars_by_symbol={"AAA": bars},
        )
        assert panels.panels[0][0][1] == pytest.approx(0.21)

    def test_insufficient_window_excluded_not_imputed(self):
        bars = [_bar("2026-01-01", 100.0), _bar("2026-01-02", 101.0)]
        panels = build_factor_panels(
            FACTOR,
            UNIVERSE,
            horizon=5,
            signals={"AAA": _signals([("2026-01-01", 1.0)])},
            bars_by_symbol={"AAA": bars},
        )
        assert panels.panels == []  # excluded, not filled
        assert panels.exclusions["AAA"] == 1
        assert panels.n_observations == 0

    def test_overlap_note_declared_for_multi_bar_horizon(self):
        bars = [_bar("2026-01-01", 100.0), _bar("2026-01-02", 101.0)]
        panels = build_factor_panels(
            FACTOR,
            UNIVERSE,
            horizon=2,
            signals={"AAA": _signals([("2026-01-01", 1.0)])},
            bars_by_symbol={"AAA": bars},
        )
        assert "overlap" in panels.overlap_note.lower()

    def test_panel_metadata_carries_horizon_and_universe(self):
        panels = build_factor_panels(FACTOR, UNIVERSE, horizon=1, signals={}, bars_by_symbol={})
        d = panels.to_dict()
        assert d["horizon"] == 1 and d["universe_version"] == UNIVERSE
        assert d["factor_id"] == FACTOR


class TestPITInvariant:
    def test_availability_after_decision_raises(self):
        bars = [_bar("2026-01-01", 100.0), _bar("2026-01-02", 101.0)]
        with pytest.raises(PanelBuildError, match="PIT invariant"):
            build_factor_panels(
                FACTOR,
                UNIVERSE,
                horizon=1,
                signals={"AAA": _signals([("2026-01-01", 1.0)], availability="2026-01-01T12:00:00Z")},
                bars_by_symbol={"AAA": bars},
            )

    def test_observation_record_enforces_pit(self):
        with pytest.raises(PanelBuildError, match="PIT"):
            FactorObservation(
                factor_id=FACTOR,
                period_date="2026-01-01",
                symbol="AAA",
                signal_value=1.0,
                forward_return=0.01,
                availability_ts="2026-01-02T00:00:00Z",
                decision_ts="2026-01-01T00:00:00Z",
            )


class TestMissingDataPolicy:
    def test_symbol_without_bars_excluded(self):
        panels = build_factor_panels(
            FACTOR,
            UNIVERSE,
            horizon=1,
            signals={"AAA": _signals([("2026-01-01", 1.0)])},
            bars_by_symbol={},
        )
        assert panels.exclusions.get("AAA") == 1
        assert panels.panels == []

    def test_signal_date_without_bar_excluded(self):
        bars = [_bar("2026-01-02", 101.0), _bar("2026-01-03", 102.0)]
        panels = build_factor_panels(
            FACTOR,
            UNIVERSE,
            horizon=1,
            signals={"AAA": _signals([("2026-01-01", 1.0)])},
            bars_by_symbol={"AAA": bars},
        )
        assert panels.exclusions.get("AAA") == 1

    def test_universe_membership_is_per_period(self):
        """A symbol absent from a period's signals is simply not in that panel."""
        bars = [_bar("2026-01-01", 100.0), _bar("2026-01-02", 101.0)]
        panels = build_factor_panels(
            FACTOR,
            UNIVERSE,
            horizon=1,
            signals={
                "AAA": _signals([("2026-01-01", 1.0)]),
                "BBB": _signals([("2026-01-01", 0.5), ("2026-01-02", 0.4)]),
            },
            bars_by_symbol={
                "AAA": bars,
                "BBB": [_bar("2026-01-01", 50.0), _bar("2026-01-02", 55.0)],
            },
        )
        # AAA has a signal only in period 2026-01-01; BBB in both.
        # Period 2026-01-02 exists with only BBB — until we notice BBB's own
        # forward return for 01-02 is incomputable (no bar after it), so that
        # observation is EXCLUDED (counted), leaving one usable panel.
        assert panels.n_observations == 2
        assert panels.period_dates == ["2026-01-01"]
        assert panels.exclusions == {"BBB": 1}


def _trial() -> TrialMetadata:
    return TrialMetadata(
        trial_group_id="factor_lab/momentum_12_1/h21",
        trial_index=1,
        hypothesis_family="momentum",
        selection_method="single_candidate",
        trials_in_family=1,
        parameter_search_space={},
    )


class TestEvaluation:
    def _panels(self, n_periods: int = 30, start: str = "2026-03-01"):
        """Build panels with a genuinely monotone positive signal-return link."""
        dates = _date_seq(n_periods + 1, start)
        signals = {}
        bars_by_symbol = {}
        symbols = [f"S{i}" for i in range(10)]
        for i, sym in enumerate(symbols):
            bars = []
            price = 100.0
            for date in dates:
                # signal i determines ordering; returns follow signal rank
                price *= 1.0 + 0.001 * (i - 4.5)
                bars.append(_bar(date, price))
            bars_by_symbol[sym] = bars
            rows = [(date, float(i), f"{date}T00:00:00Z") for date in dates[:-1]]
            signals[sym] = rows
        return build_factor_panels(FACTOR, UNIVERSE, horizon=1, signals=signals, bars_by_symbol=bars_by_symbol)

    def test_positive_information_scores_candidate(self):
        panels = self._panels()
        result = evaluate_factor(panels, cost_model=CostModel(model_id="zero"), trial_metadata=_trial())
        assert result.ic["mean_ic"] > 0
        assert result.verdict == "CANDIDATE"
        assert result.ic_p_value_holm <= 0.05
        assert any("positive IC survives" in r for r in result.reasons)

    def test_never_returns_validated(self):
        result = evaluate_factor(self._panels(), cost_model=CostModel(model_id="zero"), trial_metadata=_trial())
        assert result.verdict != "VALIDATED"

    def test_high_costs_can_reject(self):
        panels = self._panels()
        expensive = CostModel(model_id="brutal", spread_ticks=200.0, slippage_ticks=200.0, market_impact_bps=500.0)
        result = evaluate_factor(panels, cost_model=expensive, trial_metadata=_trial())
        assert result.cost_adjusted_spread < 0
        assert result.verdict == "REJECTED"
        assert any("cost_adjusted_spread" in r for r in result.reasons)

    def test_zero_ic_rejected(self):
        """A noise signal with zero IC must be REJECTED, never passed."""
        import random

        rng = random.Random(7)
        n_periods = 40
        dates = _date_seq(n_periods + 1, "2026-04-01")
        signals = {}
        bars_by_symbol = {}
        symbols = [f"S{i}" for i in range(10)]
        for i, sym in enumerate(symbols):
            bars = []
            price = 100.0
            for date in dates:
                price *= 1.0 + rng.gauss(0, 0.001)
                bars.append(_bar(date, price))
            bars_by_symbol[sym] = bars
            rows = [(date, rng.gauss(0, 1), f"{date}T00:00:00Z") for date in dates[:-1]]
            signals[sym] = rows
        panels = build_factor_panels(
            "noise_factor", UNIVERSE, horizon=1, signals=signals, bars_by_symbol=bars_by_symbol
        )
        result = evaluate_factor(
            panels,
            cost_model=CostModel(model_id="real", spread_ticks=50.0, slippage_ticks=50.0),
            trial_metadata=TrialMetadata(
                trial_group_id="factor_lab/noise/h1",
                trial_index=1,
                hypothesis_family="momentum",
                selection_method="single_candidate",
                trials_in_family=1,
            ),
        )
        assert result.verdict == "REJECTED"

    def test_inconclusive_on_few_periods(self):
        panels = self._panels(n_periods=8)  # below min_periods=12
        result = evaluate_factor(panels, cost_model=CostModel(model_id="zero"), trial_metadata=_trial())
        assert result.verdict == "INCONCLUSIVE"
        assert any("usable_periods" in r for r in result.reasons)

    def test_inconclusive_on_exclusion_budget(self):
        panels = self._panels(n_periods=30)
        # Fabricate a heavy exclusion history: 30 exclusions vs ~300 observations
        heavy = PanelSet_with_exclusions(panels, per_symbol=25)
        result = evaluate_factor(heavy, cost_model=CostModel(model_id="zero"), trial_metadata=_trial())
        assert result.verdict == "INCONCLUSIVE"
        assert any("exclusion_share" in r for r in result.reasons)

    def test_holm_correction_recorded_with_family(self):
        result = evaluate_factor(self._panels(), cost_model=CostModel(model_id="zero"), trial_metadata=_trial())
        assert result.trial_metadata["trial_group_id"] == "factor_lab/momentum_12_1/h21"
        assert result.trial_metadata["trials_in_family"] == 1

    def test_determinism(self):
        r1 = evaluate_factor(self._panels(), cost_model=CostModel(model_id="zero"), trial_metadata=_trial())
        r2 = evaluate_factor(self._panels(), cost_model=CostModel(model_id="zero"), trial_metadata=_trial())
        assert r1.to_dict() == r2.to_dict()

    def test_empty_panels_rejected(self):
        panels = build_factor_panels(FACTOR, UNIVERSE, horizon=1, signals={}, bars_by_symbol={})
        with pytest.raises(EvaluationError, match="empty"):
            evaluate_factor(panels, cost_model=CostModel(model_id="zero"), trial_metadata=_trial())


def PanelSet_with_exclusions(panels, per_symbol: int):
    """Test helper: clone the PanelSet with inflated exclusion counts."""
    from dataclasses import replace

    exclusions = {s: per_symbol for s in ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")}
    return replace(panels, exclusions=exclusions)
