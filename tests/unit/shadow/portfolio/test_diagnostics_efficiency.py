"""Diagnostics D3c efficiency + version-boundary tests.

Covers the two R4-S verdict additions to r4_shadow_diagnostics.py:

  * marginal_efficiency — per-transition Δsignal / Δvariance, the tool for
    locating where additional R4 signal becomes inefficient relative to
    incremental modeled risk.
  * filter_by_selector_version — the clean evaluation boundary that keeps
    pre-v0.2.2 records (which lack risk-contribution metrics) out of the
    post-upgrade qualification sample.
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


def _table(sig, var):
    """Build a minimal comparative_evidence-style table for efficiency math."""
    sizes = ["r4_20"] + [f"s{n}" for n in (4, 5, 6, 7, 8)]
    return {
        "signal_retained_pct": dict(zip(sizes, sig)),
        "portfolio_variance": dict(zip(sizes, var)),
    }


class TestMarginalEfficiency:
    def test_transition_math(self, diag):
        """Δsignal/Δvariance per transition, from the D3b table values."""
        eff = diag.marginal_efficiency(
            _table(
                sig=[100.0, 52.1, 57.2, 60.5, 63.4, 66.2],
                var=[0.00826, 0.00652, 0.00705, 0.00710, 0.00714, 0.00725],
            )
        )
        trans = {t["transition"]: t for t in eff["transitions"]}
        # S-5 → S-6: +3.3pp signal / +0.00005 variance
        t = trans["S-5 → S-6"]
        assert t["d_signal_pp"] == pytest.approx(3.3, abs=0.05)
        assert t["d_variance"] == pytest.approx(0.00005, abs=1e-6)
        # efficiency = pp per 1e-4 variance: 3.3 / 0.5
        assert t["efficiency_pp_per_1e4_var"] == pytest.approx(6.6, abs=0.2)

    def test_level_ratio(self, diag):
        eff = diag.marginal_efficiency(_table([100.0, 52.1], [0.00826, 0.00652]))
        lv = {r["size"]: r for r in eff["levels"]}
        assert lv["R4-20"]["signal_per_variance"] == pytest.approx(100.0 / 0.00826, abs=0.05)
        assert lv["S-4"]["signal_per_variance"] == pytest.approx(52.1 / 0.00652, abs=0.05)

    def test_missing_values_skipped(self, diag):
        """None (pre-0.2.2 missing metric) must not produce bogus transitions."""
        eff = diag.marginal_efficiency(
            _table(sig=[100.0, 52.1, None, None, None, None], var=[0.00826] * 6)
        )
        # Only the R4-20 → S-4 transition is computable; the rest are dropped.
        assert len(eff["transitions"]) == 1
        assert eff["transitions"][0]["transition"] == "R4-20 → S-4"

    def test_flat_variance_marked_not_bogus_ratio(self, diag):
        eff = diag.marginal_efficiency(_table(sig=[100.0, 52.1, 57.2], var=[0.00826, 0.00826, 0.00826]))
        for t in eff["transitions"]:
            assert t["efficiency_pp_per_1e4_var"] in (None, float("inf"))


class TestSelectorVersionBoundary:
    def test_full_record_value_parsed(self, diag):
        assert diag._version_tuple("r4s-shadow-selector-0.2.2") == (0, 2, 2)

    def test_bare_semver_parsed(self, diag):
        assert diag._version_tuple("0.2.2") == (0, 2, 2)

    def test_unparseable_none(self, diag):
        assert diag._version_tuple("r4s-shadow-selector") is None

    def test_filter_keeps_only_boundary_and_above(self, diag):
        records = [
            {"selector_version": "r4s-shadow-selector-0.2.0"},
            {"selector_version": "r4s-shadow-selector-0.2.1"},
            {"selector_version": "r4s-shadow-selector-0.2.2"},
            {"selector_version": "r4s-shadow-selector-0.3.0"},
            {},  # unparseable → dropped when a boundary is requested
        ]
        kept, dropped = diag.filter_by_selector_version(records, "0.2.2")
        assert [d["selector_version"] for d in kept] == [
            "r4s-shadow-selector-0.2.2",
            "r4s-shadow-selector-0.3.0",
        ]
        assert dropped == 3

    def test_no_boundary_keeps_everything(self, diag):
        records = [{"selector_version": "r4s-shadow-selector-0.2.0"}, {}]
        kept, dropped = diag.filter_by_selector_version(records, None)
        assert len(kept) == 2 and dropped == 0

    def test_invalid_boundary_raises(self, diag):
        with pytest.raises(ValueError):
            diag.filter_by_selector_version([], "not-a-version")
