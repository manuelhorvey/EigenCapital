"""Diagnostics D4 realized-outcome tests.

Covers the realized-outcome evaluation added to r4_shadow_diagnostics.py:

  * _max_drawdown — peak-to-trough on the cumulative net-P&L series.
  * _per_cycle_stats — distributional realized stats (Sharpe, vol, downside
    deviation, worst cycle, tail loss, turnover) from one size's ledger rows.
  * realized_outcomes — the R4-20 vs Shadow-4..8 table built from the
    per-cycle size ledger, with ERC read from the right place for each column
    (chain_by_n for shadow sizes, baseline metrics for R4-20).

Terminology note (R4-S verdict): effective_risk_contributors is the
Effective Risk Contributors (ERC) count — an effective-count diagnostic, NOT
a count of statistically independent bets.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "r4_shadow_diagnostics.py"


@pytest.fixture(scope="module")
def diag():
    spec = importlib.util.spec_from_file_location("r4_shadow_diagnostics_mod", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestMaxDrawdown:
    def test_simple_peak_trough(self, diag):
        # net series: +100, -50, +20, -80, +10
        assert diag._max_drawdown([100.0, -50.0, 20.0, -80.0, 10.0]) == pytest.approx(-110.0)

    def test_monotonic_up_no_drawdown(self, diag):
        assert diag._max_drawdown([1.0, 2.0, 3.0]) == pytest.approx(0.0)

    def test_empty(self, diag):
        assert diag._max_drawdown([]) is None


class TestPerCycleStats:
    def _row(self, **kw):
        base = {
            "signal_date": "2026-09-08",
            "size": 6,
            "gross_pnl": 10.0,
            "cost": 0.5,
            "net_pnl": 9.5,
            "n_exits": 2,
            "avg_r": 0.35,
            "turnover": 1.2,
            "edge_retained_pct": 60.0,
        }
        base.update(kw)
        return base

    def test_basic_aggregates(self, diag):
        rows = [
            self._row(net_pnl=10.0, avg_r=0.5, turnover=1.0, n_exits=2),
            self._row(net_pnl=-5.0, avg_r=-0.2, turnover=1.5, n_exits=1),
            self._row(net_pnl=3.0, avg_r=0.1, turnover=0.8, n_exits=3),
        ]
        s = diag._per_cycle_stats(rows)
        assert s["realized_pnl"] == pytest.approx(8.0)
        assert s["realized_r"] == pytest.approx((0.5 - 0.2 + 0.1) / 3.0, abs=5e-5)  # rounded to 4dp
        assert s["worst_cycle"] == pytest.approx(-5.0)
        assert s["turnover"] == pytest.approx((1.0 + 1.5 + 0.8) / 3.0)
        assert s["cost"] == pytest.approx(1.5)
        assert s["max_dd"] is not None
        assert s["tail_loss"] is not None
        assert s["net_r_after_costs"] is None  # documented as '—'

    def test_single_cycle_no_distribution_stats(self, diag):
        """One cycle can't produce Sharpe/vol/downside/tail (need >= 2)."""
        s = diag._per_cycle_stats([self._row(net_pnl=5.0)])
        assert s["sharpe"] is None
        assert s["realized_vol"] is None
        assert s["downside_dev"] is None
        assert s["tail_loss"] is None
        assert s["max_dd"] == pytest.approx(0.0)  # single non-negative cycle

    def test_empty(self, diag):
        s = diag._per_cycle_stats([])
        assert s["cycles"] == 0
        assert s["realized_pnl"] is None
        assert s["realized_r"] is None


class TestRealizedOutcomes:
    def _decision(self, n: int = 6, erc: float | None = 3.5, baseline_erc: float | None = 9.8):
        """Minimal decision record: chain_by_n for the shadow size + baseline."""
        chain = {}
        if erc is not None:
            chain[str(n)] = {"metrics": {"effective_risk_contributors": erc}}
        baseline_metrics = {"effective_risk_contributors": baseline_erc} if baseline_erc is not None else {}
        return {
            "chain_by_n": chain,
            "baseline": {"metrics": baseline_metrics},
        }

    def _comparative(self):
        return {
            "signal_retained_pct": {
                "r4_20": 100.0,
                "s4": 52.1, "s5": 57.2, "s6": 60.5, "s7": 63.4, "s8": 66.2,
            }
        }

    def test_erc_r4_20_reads_baseline_not_chain(self, diag):
        """R4-20 ERC comes from baseline metrics; chain_by_n has no size-20 node."""
        d = self._decision()
        assert "20" not in d["chain_by_n"]
        table = diag.realized_outcomes([d], [], self._comparative())
        assert table["erc"]["r4_20"] == pytest.approx(9.8)

    def test_erc_shadow_reads_chain(self, diag):
        table = diag.realized_outcomes([self._decision()], [], self._comparative())
        assert table["erc"]["s6"] == pytest.approx(3.5)

    def test_realized_rows_populated_from_ledger(self, diag):
        rows = [
            {
                "signal_date": "2026-09-08", "size": 6,
                "gross_pnl": 10.0, "cost": 0.5, "net_pnl": 9.5,
                "n_exits": 2, "avg_r": 0.5, "turnover": 1.0,
            },
            {
                "signal_date": "2026-09-09", "size": 6,
                "gross_pnl": -4.0, "cost": 0.5, "net_pnl": -4.5,
                "n_exits": 1, "avg_r": -0.2, "turnover": 1.5,
            },
            {"signal_date": "END", "size": 6, "net_pnl": 0.0},  # close row excluded
        ]
        table = diag.realized_outcomes([], rows, self._comparative())
        assert table["realized_pnl"]["s6"] == pytest.approx(5.0)
        assert table["realized_r"]["s6"] == pytest.approx((0.5 - 0.2) / 2.0)
        assert table["worst_cycle"]["s6"] == pytest.approx(-4.5)

    def test_missing_erc_shows_dash(self, diag):
        """Pre-0.2.2 records lack ERC — the cell must be None, not an error."""
        d = self._decision(erc=None, baseline_erc=None)
        table = diag.realized_outcomes([d], [], self._comparative())
        assert table["erc"]["s6"] is None
        assert table["erc"]["r4_20"] is None
