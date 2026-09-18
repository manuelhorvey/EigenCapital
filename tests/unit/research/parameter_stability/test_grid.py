"""Unit tests for R3 grid machinery — the preregistered robustness contract.

Covers the frozen R3 contract (docs/research/R3_PARAMETER_STABILITY.md):
- preregistered enumeration with center-in-grid enforcement
- von-Neumann adjacency
- FRAGILE classification at the frozen thresholds (DD >= 0.40 or Sharpe <= 0)
- connected component + STABLE fraction per the preregistered rules
- axis-level Spearman association tests (hand-computed)
- F1/F2 verdict semantics: INSIDE / OUTSIDE / INCONCLUSIVE, exact statements
- the preregistered daily-path realization (next-bar execution lag,
  per-change costs) against hand-computed values
- per-point evaluation with injected pipeline functions
"""

import math

import pandas as pd
import pytest

from eigencapital.research.parameter_stability.evaluate import (
    daily_portfolio_path,
    equity_curve_from_returns,
    evaluate_grid_point,
)
from eigencapital.research.parameter_stability.grid import (
    FRAGILE_MAX_DRAWDOWN,
    FRAGILE_SHARPE_MAX,
    STABLE_FRACTION_F1,
    GridAxis,
    GridError,
    GridPoint,
    PointMetrics,
    axis_association_tests,
    build_grid,
    classify_point,
    stability_verdict,
    stable_region_metrics,
    von_neumann_neighbors,
)

AXES = [
    GridAxis(name="lookback", values=(189.0, 220.0, 252.0, 284.0, 315.0)),
    GridAxis(name="skip", values=(0.0, 21.0, 42.0, 63.0)),
    GridAxis(name="vol_lookback", values=(40.0, 50.0, 60.0, 70.0, 80.0)),
    GridAxis(name="risk_lookback", values=(10.0, 15.0, 20.0, 25.0, 30.0)),
    GridAxis(name="rebalance", values=(3.0, 5.0, 10.0)),
]
CENTER = {"lookback": 252.0, "skip": 21.0, "vol_lookback": 60.0, "risk_lookback": 20.0, "rebalance": 5.0}


def _metrics(params, **kw) -> PointMetrics:
    base = dict(
        cagr=0.05,
        ann_vol=0.10,
        max_drawdown=0.10,
        sharpe=1.0,
        total_pnl=0.5,
        trade_count=100,
        turnover=0.2,
        hit_rate=0.5,
        payoff_ratio=1.5,
    )
    base.update(kw)
    return PointMetrics(params=dict(params), **base)


class TestGridPreregistration:
    def test_grid_size_is_1500(self):
        grid = build_grid(AXES, CENTER)
        assert len(grid) == 5 * 4 * 5 * 5 * 3 == 1500

    def test_center_is_a_grid_point(self):
        grid = build_grid(AXES, CENTER)
        keys = {p.key() for p in grid}
        assert tuple(sorted(CENTER.items())) in keys

    def test_center_missing_from_axis_raises(self):
        bad = dict(CENTER, rebalance=7.0)
        with pytest.raises(GridError, match="frozen configuration must be a grid point"):
            build_grid(AXES, bad)

    def test_center_value_missing_raises(self):
        with pytest.raises(GridError, match="center value missing"):
            build_grid(AXES, {k: v for k, v in CENTER.items() if k != "rebalance"})

    def test_axis_values_must_be_ascending_unique(self):
        with pytest.raises(GridError, match="ascending"):
            GridAxis(name="x", values=(3.0, 1.0, 2.0))
        with pytest.raises(GridError, match="ascending"):
            GridAxis(name="x", values=(1.0, 1.0, 2.0))

    def test_enumeration_is_deterministic(self):
        g1, g2 = build_grid(AXES, CENTER), build_grid(AXES, CENTER)
        assert [p.key() for p in g1] == [p.key() for p in g2]
        assert g1[0].params == {a.name: a.values[0] for a in AXES}


class TestAdjacency:
    def test_one_step_one_axis(self):
        a = GridPoint(params={"x": 1.0, "y": 5.0}, indices=(0, 1))
        b = GridPoint(params={"x": 2.0, "y": 5.0}, indices=(1, 1))
        assert von_neumann_neighbors(a, b)
        assert von_neumann_neighbors(b, a)

    def test_two_axes_changed(self):
        a = GridPoint(params={"x": 1.0, "y": 5.0}, indices=(0, 1))
        b = GridPoint(params={"x": 2.0, "y": 6.0}, indices=(1, 2))
        assert not von_neumann_neighbors(a, b)

    def test_two_steps_same_axis(self):
        a = GridPoint(params={"x": 1.0, "y": 5.0}, indices=(0, 1))
        b = GridPoint(params={"x": 3.0, "y": 5.0}, indices=(2, 1))
        assert not von_neumann_neighbors(a, b)


class TestFrozenClassification:
    def test_frozen_thresholds_are_the_ledger_values(self):
        assert FRAGILE_MAX_DRAWDOWN == 0.40
        assert FRAGILE_SHARPE_MAX == 0.0
        assert STABLE_FRACTION_F1 == 0.60

    def test_healthy_point(self):
        assert classify_point(_metrics({}, max_drawdown=0.39, sharpe=1.0)) == "NON_FRAGILE"

    def test_drawdown_threshold_is_inclusive(self):
        assert classify_point(_metrics({}, max_drawdown=0.40, sharpe=2.0)) == "FRAGILE"

    def test_zero_sharpe_is_fragile(self):
        assert classify_point(_metrics({}, max_drawdown=0.05, sharpe=0.0)) == "FRAGILE"

    def test_negative_sharpe_is_fragile(self):
        assert classify_point(_metrics({}, max_drawdown=0.05, sharpe=-0.1)) == "FRAGILE"


def _flat_grid(values, name="x"):
    axis = GridAxis(name=name, values=tuple(float(v) for v in values))
    center = {name: float(values[len(values) // 2])}
    return build_grid([axis], center), center


class TestStableRegion:
    def test_component_stops_at_fragile_and_boundary_is_transitional(self):
        grid, center = _flat_grid([10, 15, 20, 25, 30])
        classes = {}
        for p in grid:
            classes[p.key()] = "FRAGILE" if p.params["x"] == 30.0 else "NON_FRAGILE"
        region = stable_region_metrics(grid, classes, center)
        # Component from idx2 reaches 0..3 (idx4 FRAGILE); idx3 borders it.
        assert region["component_size"] == 4
        assert region["stable_count"] == 3
        assert region["stable_fraction"] == pytest.approx(0.75)

    def test_all_neighbors_fragile(self):
        grid, center = _flat_grid([10, 15, 20, 25, 30])
        classes = {}
        for p in grid:
            classes[p.key()] = "FRAGILE" if p.params["x"] in (15.0, 25.0) else "NON_FRAGILE"
        region = stable_region_metrics(grid, classes, center)
        assert region["center_classification"] == "NON_FRAGILE"
        assert region["center_all_neighbors_fragile"] is True
        assert region["component_size"] == 1
        # Preregistered rule: STABLE = non-FRAGILE AND not adjacent to any
        # FRAGILE point. The center borders FRAGILE points on BOTH sides, so
        # it is TRANSITIONAL → component {center} contributes 0 stable points.
        assert region["stable_count"] == 0
        assert region["stable_fraction"] == pytest.approx(0.0)

    def test_center_fragile(self):
        grid, center = _flat_grid([10, 15, 20, 25, 30])
        classes = {p.key(): ("FRAGILE" if p.params["x"] == 20.0 else "NON_FRAGILE") for p in grid}
        region = stable_region_metrics(grid, classes, center)
        assert region["center_classification"] == "FRAGILE"
        assert region["component_size"] == 0

    def test_center_not_in_grid_raises(self):
        grid, _ = _flat_grid([10, 15, 20, 25, 30])
        classes = {p.key(): "NON_FRAGILE" for p in grid}
        with pytest.raises(GridError, match="preregistration violation"):
            stable_region_metrics(grid, classes, {"x": 99.0})


class TestAxisAssociation:
    def test_perfect_monotone_positive(self):
        grid, _ = _flat_grid([1, 2, 3, 4])
        metrics = {p.key(): _metrics(p.params, sharpe=float(i)) for i, p in enumerate(grid)}
        recs = axis_association_tests(grid, metrics)
        assert recs[0]["spearman_rho"] == pytest.approx(1.0)
        assert recs[0]["raw_p"] == 0.0

    def test_hand_computed_tie_ranks(self):
        grid, _ = _flat_grid([1, 2, 3, 4])
        # sharpes 0.0, 0.1, 0.0, 0.1 → avg ranks 1.5, 3.5, 1.5, 3.5 → rho = 2/sqrt(20)
        metrics = {p.key(): _metrics(p.params, sharpe=s) for p, s in zip(grid, (0.0, 0.1, 0.0, 0.1))}
        recs = axis_association_tests(grid, metrics)
        assert recs[0]["spearman_rho"] == pytest.approx(2.0 / math.sqrt(20.0))
        assert 0.0 < recs[0]["raw_p"] < 0.6

    def test_perfect_monotone_negative(self):
        grid, _ = _flat_grid([1, 2, 3, 4])
        metrics = {p.key(): _metrics(p.params, sharpe=-float(i)) for i, p in enumerate(grid)}
        recs = axis_association_tests(grid, metrics)
        assert recs[0]["spearman_rho"] == pytest.approx(-1.0)
        assert recs[0]["raw_p"] == 0.0


def _region(fraction, comp, cls="NON_FRAGILE", neighbors_fragile=False):
    return {
        "center_classification": cls,
        "component_size": comp,
        "stable_fraction": fraction,
        "stable_count": int(fraction * comp),
        "center_all_neighbors_fragile": neighbors_fragile,
    }


def _axis_recs(ps):
    return [
        {"axis": f"a{i}", "spearman_rho": 0.0, "t_stat": 0.0, "raw_p": p, "n_points": 100} for i, p in enumerate(ps)
    ]


class TestVerdictSemantics:
    def test_inside_statement_exact(self):
        v = stability_verdict(_region(0.8, 100), _axis_recs([0.5, 0.5, 0.5, 0.5, 0.5]))
        assert v.outcome == "INSIDE_STABLE_REGION"
        assert v.region_statement == (
            "the frozen configuration lies inside a historically stable region on this data (preregistered thresholds)"
        )

    def test_f1_outside_statement_exact(self):
        v = stability_verdict(_region(0.4, 100), _axis_recs([0.001, 0.001, 0.5, 0.5, 0.5]))
        assert v.outcome == "OUTSIDE_STABLE_REGION"
        assert v.region_statement == (
            "the frozen configuration does not sit inside a historically stable region on this data"
        )
        assert sorted(v.axes_flagged) == ["a0", "a1"]

    def test_f1_requires_both_arms(self):
        v = stability_verdict(_region(0.4, 100), _axis_recs([0.001, 0.5, 0.5, 0.5, 0.5]))
        assert v.outcome == "INSIDE_STABLE_REGION"

    def test_center_fragile_statement_exact(self):
        v = stability_verdict(_region(0.0, 0, cls="FRAGILE"), _axis_recs([0.5] * 5))
        assert v.outcome == "OUTSIDE_STABLE_REGION"
        assert "classifies as FRAGILE" in v.region_statement
        assert "no recommendation is made" in v.region_statement

    def test_center_fragile_all_neighbors(self):
        v = stability_verdict(_region(0.0, 0, cls="FRAGILE", neighbors_fragile=True), _axis_recs([0.5] * 5))
        assert "all its immediate grid neighbours are also FRAGILE" in v.region_statement

    def test_holm_keys_cover_all_axes(self):
        v = stability_verdict(_region(0.9, 100), _axis_recs([0.5] * 5))
        assert set(v.holm_adjusted_p) == {f"a{i}" for i in range(5)}


class TestDailyPath:
    def _one_symbol(self, closes):
        idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
        return {"SYM": pd.DataFrame({"close": closes, "open": closes}, index=idx)}

    def test_hand_computed_lag_and_cost(self):
        data = self._one_symbol([100.0, 110.0, 99.0])
        idx = pd.date_range("2026-01-01", periods=3, freq="D")
        weights = pd.DataFrame({"SYM": [0.0, 1.0, 1.0]}, index=idx)
        port = daily_portfolio_path(data, weights, cost_one_way=0.0015)
        # Executed weights lag one bar: E = [0, 0, 1]; returns = [0, +.10, -.10].
        assert port.iloc[0] == pytest.approx(0.0)
        assert port.iloc[1] == pytest.approx(0.0)  # profit NOT earned — execution lagged
        assert port.iloc[2] == pytest.approx(-0.10 - 0.0015)

    def test_cost_charged_on_every_weight_change(self):
        data = self._one_symbol([100.0] * 4)
        idx = pd.date_range("2026-01-01", periods=4, freq="D")
        weights = pd.DataFrame({"SYM": [0.0, 0.5, 0.0, 0.5]}, index=idx)
        port = daily_portfolio_path(data, weights, cost_one_way=0.001)
        # Frozen one-bar lag: E = [0, 0, 0.5, 0] → ΔE = [—, 0, 0.5, 0.5].
        # Costs land one bar AFTER the target-weight change, on execution.
        assert port.iloc[1] == pytest.approx(0.0)
        assert port.iloc[2] == pytest.approx(-0.5 * 0.001)
        assert port.iloc[3] == pytest.approx(-0.5 * 0.001)

    def test_equity_curve_shape(self):
        data = self._one_symbol([100.0, 101.0, 102.0])
        idx = pd.date_range("2026-01-01", periods=3, freq="D")
        weights = pd.DataFrame({"SYM": [0.0, 0.0, 0.0]}, index=idx)
        eq = equity_curve_from_returns(daily_portfolio_path(data, weights, 0.0))
        assert len(eq) == 4 and eq[0] == 1.0 and eq[-1] == pytest.approx(1.0)


class TestEvaluateGridPoint:
    def _data(self):
        idx = pd.date_range("2026-01-01", periods=6, freq="D")
        return {
            "AAA": pd.DataFrame({"close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0], "open": [100.0] * 6}, index=idx),
            "BBB": pd.DataFrame({"close": [50.0, 50.5, 51.0, 51.5, 52.0, 52.5], "open": [50.0] * 6}, index=idx),
        }

    def test_trade_metrics_and_path_consistency(self):
        idx = pd.date_range("2026-01-01", periods=6, freq="D")
        weights = pd.DataFrame(
            {"AAA": [0.0, 0.1, 0.1, 0.1, 0.1, 0.1], "BBB": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}, index=idx
        )
        pnls = {
            # Exporter contract: (signed pnl, exit timestamp) tuples.
            "AAA": [
                (0.02, pd.Timestamp("2026-01-03")),
                (-0.01, pd.Timestamp("2026-01-04")),
                (0.03, pd.Timestamp("2026-01-05")),
            ],
            "BBB": [],
        }

        def signal_fn(params, data):
            return weights

        def sim_fn(data, w, params):
            return {}, pnls

        base = {"cost_one_way": 0.0015, "lookback": 252}
        m = evaluate_grid_point({"lookback": 220.0}, self._data(), base, signal_fn, sim_fn)
        assert m.params == {"lookback": 220.0}
        assert m.trade_count == 3
        assert m.hit_rate == pytest.approx(2 / 3)
        assert m.total_pnl == pytest.approx(0.04)
        assert m.payoff_ratio == pytest.approx(0.025 / 0.01)
        # Path metrics consistent with the preregistered realization
        port = daily_portfolio_path(self._data(), weights, 0.0015)
        eq = equity_curve_from_returns(port)
        peak, max_dd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            max_dd = max(max_dd, 1.0 - v / peak)
        assert m.max_drawdown == pytest.approx(max_dd)
        assert m.wf_total_windows == 0  # short test path — geometry cannot fit
        assert all(math.isfinite(v) for v in (m.cagr, m.ann_vol, m.sharpe, m.turnover))

    def test_pipeline_exception_propagates(self):
        def signal_fn(params, data):
            raise RuntimeError("signal failure")

        with pytest.raises(RuntimeError, match="signal failure"):
            evaluate_grid_point(
                {"lookback": 220.0}, self._data(), {"cost_one_way": 0.0015}, signal_fn, lambda d, w, p: ({}, {})
            )
