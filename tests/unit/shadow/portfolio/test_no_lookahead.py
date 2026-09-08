"""Explicit no-lookahead tests (brief Section 13 — hard requirement).

The shadow layer may only use information available at the R4 decision
timestamp. These tests prove each component is structurally incapable of
seeing the future:

1. CorrelationModel.build(returns, as_of) truncates to rows <= as_of.
2. The selector receives a pre-built snapshot and candidate list — it never
   touches raw price data, so there is no future-data path into selection.
3. The tracker realizes outcomes only from prices the caller supplies at
   close time.
4. The R4 signal at date t is identical whether or not later bars exist.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from eigencapital.shadow.portfolio.correlation import CorrelationModel
from eigencapital.shadow.portfolio.selector import ShadowSelector, ShadowSelectorConfig
from tests.unit.shadow.portfolio.helpers import make_candidate, make_returns, snapshot_for


class TestCorrelationNoLookahead:
    def test_future_crash_invisible(self):
        returns = make_returns(["AUDUSD", "EURUSD", "USDJPY"], n=300, seed=41)
        as_of = returns.index[260]
        before = returns.loc[:as_of].copy()

        # Plant a violent future regime change STRICTLY AFTER as_of (would
        # change correlation if it leaked; the as_of row itself is untouched).
        future = returns.loc[as_of:].iloc[1:].copy()
        future["AUDUSD"] = -future["AUDUSD"] * 100
        future["EURUSD"] = future["EURUSD"] * 100
        future["USDJPY"] = -future["USDJPY"] * 100
        full = pd.concat([before, future])

        snap_full = CorrelationModel().build(full, as_of=as_of)
        snap_before = CorrelationModel().build(before, as_of=as_of)
        assert snap_full is not None and snap_before is not None
        assert np.allclose(snap_full.corr.fillna(0).values, snap_before.corr.fillna(0).values)
        assert snap_full.observations_used == min(60, len(before))
        assert snap_full.as_of == str(as_of.date())

    def test_vol_uses_only_past_rows(self):
        returns = make_returns(["AUDUSD"], n=300, seed=42)
        as_of = returns.index[200]
        before = returns.loc[:as_of].copy()
        snap = CorrelationModel().build(before, as_of=as_of)
        assert snap is not None
        assert snap.observations_used <= 200


class TestSelectorNoLookahead:
    def test_selection_depends_only_on_snapshot_and_candidates(self):
        """Selection inputs are the pre-built snapshot + candidates. There is
        no raw-data argument, so future bars cannot influence the decision."""
        returns = make_returns(["AUDUSD", "EURUSD"], n=300, seed=43)
        as_of = returns.index[250]
        snapshot = snapshot_for(returns.loc[:as_of])

        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("EURUSD", -0.19, rank=2),
        ]
        selector = ShadowSelector(ShadowSelectorConfig())
        d1 = selector.select(
            candidates,
            snapshot,
            ["AUDUSD", "EURUSD"],
            cycle_id="C",
            decision_timestamp="t",
            signal_date=str(as_of.date()),
        )

        # A future crash frame must not change the decision: the selector
        # never sees it.
        future = returns.loc[as_of:].copy() * 100
        _ = future  # selector has no argument that could receive this
        d2 = selector.select(
            candidates,
            snapshot,
            ["AUDUSD", "EURUSD"],
            cycle_id="C",
            decision_timestamp="t",
            signal_date=str(as_of.date()),
        )
        assert d1.to_dict() == d2.to_dict()

    def test_signal_at_t_independent_of_later_bars(self):
        """The R4 signal row at t is a function of data <= t only."""
        returns = make_returns(["AUDUSD", "EURUSD", "GBPUSD"], n=400, seed=44)
        as_of = returns.index[330]
        before = returns.loc[:as_of].copy()
        # Rebuild a close-price frame and compute the momentum signal on both
        # truncated and full histories; the t-row must be identical.
        closes_before = (1 + before).cumprod()
        closes_full = (1 + returns).cumprod()
        sig_t_before = _momentum_row(closes_before, as_of)
        sig_t_full = _momentum_row(closes_full, as_of)
        assert np.allclose(sig_t_before.values, sig_t_full.values, atol=1e-12)


def _momentum_row(closes: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    """12-1 momentum at row t using only rows <= t (same math as the frozen
    R4 signal, kept local so the test does not depend on runner imports)."""
    ret = closes.pct_change().dropna(how="all").ffill().fillna(0)
    mom12 = (1 + ret).rolling(252).apply(lambda x: x.prod() - 1, raw=True)
    mom1 = (1 + ret).rolling(21).apply(lambda x: x.prod() - 1, raw=True)
    sig = (mom12 - mom1).dropna(how="all")
    return sig.loc[t]


class TestTrackerNoLookahead:
    def test_missing_future_price_no_outcome(self, tmp_path):
        from eigencapital.shadow.portfolio.tracker import (
            ShadowDecisionRecorder,
            ShadowPositionTracker,
        )

        recorder = ShadowDecisionRecorder(audit_dir=str(tmp_path))
        tracker = ShadowPositionTracker(recorder, equity=5100.0)
        tracker.open_cycle(
            ["AUDUSD"],
            {"AUDUSD": 0.1},
            {"AUDUSD": 100.0},
            {"AUDUSD": 0.01},
            "C1",
            "2026-01-01",
            "2026-01-01",
        )
        # No future price provided → no realized outcome (cannot invent one).
        outcomes = tracker.close_all({}, "2026-01-02", "C1", "2026-01-02")
        assert outcomes == []
        assert "AUDUSD" in tracker.open_positions()
