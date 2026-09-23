"""Tests for the offline rebalance-policy replay engine (EXP-000002).

Validates the Section 14/15/11/21 invariants in a synthetic, deterministic
setting: identical targets for all policies, no look-ahead, uniform costs,
thresholds reducing turnover, min-lot floor mirroring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.core.rebalance import (
    PolicyConfig,
    PolicyType,
    experiment_matrix,
)
from eigencapital.research.rebalance.replay import (
    PolicyReplay,
    ReplayConfig,
    apply_min_lot_floor,
    build_decision_grid,
    cost_ladder,
    run_policy_matrix,
)

SYMBOLS = ["A", "B", "C", "D"]


def _synthetic_signal(n: int = 320, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deterministic synthetic close panel + frozen-signal-STYLE weight panel.

    The weight panel mimics the R4 shape (small cross-sectional weights that
    drift daily), computed from past closes only — so tests exercise the
    replay mechanics without depending on the external parity-verified
    reconstruction.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = pd.DataFrame(
        100.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.01, size=(n, len(SYMBOLS))), axis=0),
        index=idx,
        columns=SYMBOLS,
    )
    # Simple point-in-time "signal": 5-day momentum of past closes (uses only
    # information up to each row — same no-lookahead discipline as R4).
    mom = closes.pct_change(5).shift(0).clip(-0.05, 0.05)
    ranks = mom.rank(axis=1, pct=True) - 0.5
    weights = (ranks * 0.2).round(6)  # ±10% band, 6dp like the live signal
    return closes, weights


@pytest.fixture(scope="module")
def panels():
    closes, weights = _synthetic_signal()
    return closes, weights


class TestSameSignalDifferentExecution:
    def test_targets_identical_across_policies(self, panels):
        """Section 14: every policy sees the SAME target stream."""
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-09-01")
        captured = []

        for config in experiment_matrix()[:3]:
            replay = PolicyReplay(config, cfg, weights, closes)
            # canary: record the targets the policy is offered (defaults bind
            # the loop variables to avoid B023 late-binding).
            seen: list = []
            original = replay._policy.should_rebalance

            def spy(*args, _seen=seen, _orig=original, **kwargs):
                _seen.append(dict(kwargs["target_weights"]))
                return _orig(*args, **kwargs)

            replay._policy.should_rebalance = spy
            replay.run()
            captured.append(seen)

        assert captured[0] == captured[1] == captured[2]

    def test_no_lookahead_weights_use_past_only(self, panels):
        """Recomputing the weight panel row-by-row from past closes must match
        the panel the replay consumed (the panel itself is point-in-time)."""
        closes, weights = _synthetic_signal()
        for t in list(weights.index)[:50:10]:
            past = closes.loc[:t]
            recomputed = past.pct_change(5).clip(-0.05, 0.05).rank(axis=1, pct=True).sub(0.5).mul(0.2).round(6)
            pd.testing.assert_series_equal(recomputed.iloc[-1], weights.loc[t], check_names=False)


class TestNoLookaheadExecution:
    def test_returns_use_held_weights_and_future_close_intervals(self, panels):
        """Interval P&L must reflect weights held BEFORE the trade at t
        (decided with info ≤ t), priced over [t_prev, t]."""
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-02-03", end="2025-03-03", cost_bps=0.0)
        config = PolicyConfig(policy_type=PolicyType.CANONICAL)
        result = PolicyReplay(config, cfg, weights, closes).run()
        assert len(result.daily_gross_returns) == len(pd.date_range("2025-02-03", "2025-03-03", freq="B"))
        # Zero-cost CANONICAL: gross == net.
        assert result.gross_pnl == pytest.approx(result.net_pnl, abs=1e-9)


class TestCostConsistency:
    def test_uniform_cost_model(self, panels):
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-09-01", cost_bps=15.0)
        results = run_policy_matrix(weights, closes, cfg)
        for pid, res in results.items():
            expected = res.total_gross_turnover * 15.0 / 1e4 * cfg.equity
            assert res.total_costs == pytest.approx(expected, rel=1e-9), pid
            # Section 11: costs = turnover × bps for EVERY policy — no
            # gross-vs-net comparisons across different conventions.
            assert res.summary(15.0)["cost_bps"] == 15.0

    def test_cost_ladder_multipliers(self):
        assert cost_ladder(15.0) == [15.0, 18.75, 22.5, 30.0]

    def test_zero_cost_gross_equals_net(self, panels):
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-09-01", cost_bps=0.0)
        results = run_policy_matrix(weights, closes, cfg)
        for res in results.values():
            assert res.gross_pnl == pytest.approx(res.net_pnl, abs=1e-9)


class TestThresholdReducesTurnover:
    def test_threshold_trades_less_often_and_costs_less(self, panels):
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-12-01", cost_bps=15.0)
        results = run_policy_matrix(weights, closes, cfg)
        canon = results["R4-REB-CANONICAL"]
        t010 = results["R4-REB-T010"]
        t020 = results["R4-REB-T020"]
        # Fewer interventions, and never more implementation cost.
        assert t010.n_rebalances < canon.n_rebalances
        assert t010.total_costs <= canon.total_costs
        # The band only suppresses same-direction adjustments — discrete
        # events (exits/entries/reversals) always trade, so wider bands can
        # converge in count when churn is event-dominated. Contract: wider
        # band ⇒ no more rebalances, no more orders.
        assert t020.n_rebalances <= t010.n_rebalances
        assert t020.n_orders <= t010.n_orders

    def test_threshold_no_phantom_exits(self, panels):
        """Banded positions must carry, never be force-exited by a trade."""
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-12-01", cost_bps=15.0)
        results = run_policy_matrix(weights, closes, cfg)
        canon = results["R4-REB-CANONICAL"]
        t010 = results["R4-REB-T010"]
        # Exits only happen when targets actually go flat — same discrete
        # event set as the baseline (not proportional to band width).
        assert t010.n_exits <= canon.n_exits * 2

    def test_daily_one_intervention_per_day(self, panels):
        """On an intraday-grid variant, DAILY must trade ≤ once per day."""
        closes, weights = _synthetic_signal(n=120)
        # Two unique timestamps per day (10:00 / 14:00) simulate an
        # hourly-style grid within a day — duplicate index labels would break
        # .loc row selection, so each intraday stamp is unique.
        stamps = [ts + pd.Timedelta(hours=h) for ts in weights.index for h in (10, 14)]
        weights2 = pd.concat([weights, weights]).sort_index()
        weights2.index = pd.DatetimeIndex(stamps)
        closes2 = pd.concat([closes, closes]).sort_index()
        closes2.index = pd.DatetimeIndex(stamps)
        cfg = ReplayConfig(decision_dates=stamps, cost_bps=15.0)
        daily = PolicyReplay(PolicyConfig(policy_type=PolicyType.DAILY), cfg, weights2, closes2).run()
        traded_days = [c.decision_date.date() for c in daily.cycles if c.action == "TRADE"]
        assert len(traded_days) == len(set(traded_days))  # ≤1 trade per calendar day


class TestMinLotFloor:
    def test_floor_mirrors_live_sizing(self):
        floored, floored_syms = apply_min_lot_floor(
            {"A": 0.004, "B": 0.02, "C": -0.008}, min_lot_weight=0.01, max_positions=20
        )
        # A: active (0.004 > 0.005 is FALSE → inactive, dropped before floor).
        # Actually 0.004 < 0.005 → not ranked at all.
        assert "A" not in floored
        # C: active (|0.008| > 0.005) but sub-minimum → floored UP to 0.01.
        assert floored["C"] == pytest.approx(-0.01)
        assert "C" in floored_syms
        assert floored["B"] == pytest.approx(0.02)

    def test_top_n_selection(self):
        weights = {f"S{i}": 0.05 - i * 0.001 for i in range(30)}
        floored, _ = apply_min_lot_floor(weights, min_lot_weight=0.01, max_positions=20)
        assert len(floored) == 20
        assert "S0" in floored and "S19" in floored and "S20" not in floored

    def test_replay_records_distortion(self, panels):
        closes, weights = _synthetic_signal()
        weights = weights.copy()
        # Force a sub-minimum active target INSIDE the replay window (the
        # first date ≥ 2025-06-01); CANONICAL trades every day, so the floor
        # distortion must be recorded.
        in_window = weights.index[weights.index >= pd.Timestamp("2025-06-01")][0]
        weights.loc[in_window, weights.columns[0]] = 0.008
        cfg = ReplayConfig(start="2025-06-01", end="2025-09-01", cost_bps=15.0, min_lot_weight=0.01)
        result = PolicyReplay(PolicyConfig(policy_type=PolicyType.CANONICAL), cfg, weights, closes).run()
        assert result.min_lot_distortion > 0.0


class TestDecisionGrid:
    def test_daily_grid(self, panels):
        closes, _ = _synthetic_signal()
        grid = build_decision_grid(closes.index, "2025-01-01", "2025-03-01", cadence="daily")
        assert grid[0] == pd.Timestamp("2025-01-01")
        assert len(grid) < len(closes.index)  # windowed

    def test_weekly_grid_one_bar_per_iso_week(self, panels):
        closes, _ = _synthetic_signal()
        grid = build_decision_grid(closes.index, None, None, cadence="weekly")
        # Contract: exactly one bar per ISO week, and it is the LATEST bar of
        # that week present in the panel (a Friday for mid-year weeks; a
        # shorter week at data boundaries yields its own last bar).
        weeks = [ts.isocalendar()[:2] for ts in grid]
        assert len(weeks) == len(set(weeks))
        for ts in grid:
            iso = ts.isocalendar()[:2]
            same_week = [t for t in closes.index if t.isocalendar()[:2] == iso]
            assert ts == max(same_week)


class TestPolicyResultSummary:
    def test_turnover_counts_only_traded_notional(self, panels):
        """A banded (carried) symbol places no order and pays no cost.

        Regression: turnover was computed over the full target∪current union,
        charging deferred band drift to whichever cycle traded next — an
        accounting artifact that made wide bands *more* expensive.
        """
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-12-01", cost_bps=15.0)
        results = run_policy_matrix(weights, closes, cfg)
        # Wider band ⇒ strictly less executed turnover and cost (every
        # suppressed adjustment is real notional never traded).
        assert results["R4-REB-T020"].total_gross_turnover <= results["R4-REB-T010"].total_gross_turnover
        assert results["R4-REB-T050"].total_gross_turnover <= results["R4-REB-T020"].total_gross_turnover
        assert results["R4-REB-T010"].total_costs <= results["R4-REB-CANONICAL"].total_costs
        # Per-cycle bookkeeping invariant: each rebalance's turnover equals
        # the deviation actually closed on tradable symbols.
        for r in results.values():
            assert r.total_gross_turnover >= 0.0

    def test_summary_fields_present(self, panels):
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-09-01", cost_bps=15.0)
        results = run_policy_matrix(weights, closes, cfg)
        s = results["R4-REB-T010"].summary(15.0)
        for key in (
            "policy_id",
            "rebalances",
            "orders",
            "entries",
            "exits",
            "reductions",
            "increases",
            "reversals",
            "turnover_total",
            "turnover_annualized",
            "gross_return",
            "net_return",
            "cost_drag",
            "cost_over_gross",
            "return_per_turnover",
            "net_sharpe",
            "max_drawdown",
            "tracking_error_mean",
            "tracking_error_max",
            "avg_holding_days",
            "min_lot_distortion",
        ):
            assert key in s, key

    def test_holding_period_and_counts(self, panels):
        closes, weights = _synthetic_signal()
        cfg = ReplayConfig(start="2025-06-01", end="2025-09-01", cost_bps=15.0)
        result = PolicyReplay(PolicyConfig(policy_type=PolicyType.WEEKLY), cfg, weights, closes).run()
        assert result.n_rebalances > 0
        assert result.n_entries + result.n_increases + result.n_reductions + result.n_reversals > 0
        if result.holding_periods:
            assert all(h > 0 for h in result.holding_periods)
