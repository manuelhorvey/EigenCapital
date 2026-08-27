"""Tests for embargoed walk-forward analysis."""

import pytest

from eigencapital.analytics.validation.walk_forward import (
    WalkForwardResult,
    purged_walk_forward,
)


def _curve(n: int = 100) -> list:
    """Deterministic upward-drifting equity curve."""
    return [100.0 * (1.0 + 0.001 * i + 0.0005 * ((i * 7) % 13 - 6)) for i in range(n)]


class TestEmbargoExclusion:
    """Embargoed bars must never appear in any training slice."""

    PARAMS = dict(train_bars=30, test_bars=10, purge_bars=2)

    def test_embargo_zones_absent_from_train_indices(self):
        curve = _curve()
        result = purged_walk_forward(curve, embargo_bars=5, **self.PARAMS)
        assert result.total_windows == 6
        zones = [(w.test_end, w.test_end + 5) for w in result.windows[:-1]]
        for window in result.windows:
            train_set = set(window.train_indices)
            for zone_start, zone_end in zones:
                overlap = range(max(zone_start, window.train_start), min(zone_end, window.train_end))
                assert not train_set & set(overlap)

    def test_geometry_unchanged_by_embargo(self):
        curve = _curve()
        baseline = purged_walk_forward(curve, embargo_bars=0, **self.PARAMS)
        embargoed = purged_walk_forward(curve, embargo_bars=5, **self.PARAMS)
        assert baseline.total_windows == embargoed.total_windows
        for w_base, w_emb in zip(baseline.windows, embargoed.windows):
            assert (w_base.test_start, w_base.test_end) == (
                w_emb.test_start,
                w_emb.test_end,
            )
            assert (w_base.train_start, w_base.train_end) == (
                w_emb.train_start,
                w_emb.train_end,
            )

    def test_no_embargo_matches_legacy_full_slices(self):
        curve = _curve()
        result = purged_walk_forward(curve, embargo_bars=0, **self.PARAMS)
        for window in result.windows:
            assert window.train_indices == tuple(range(window.train_start, window.train_end))
            assert window.in_sample_return == pytest.approx(
                curve[window.train_end - 1] / curve[window.train_start] - 1.0
            )

    def test_embargo_gaps_contain_only_embargoed_bars(self):
        curve = _curve(200)
        embargo = 8
        result = purged_walk_forward(
            curve,
            train_bars=50,
            test_bars=10,
            purge_bars=2,
            embargo_bars=embargo,
        )
        zones = [(w.test_end, w.test_end + embargo) for w in result.windows[:-1]]
        gapped_found = False
        for window in result.windows:
            indices = list(window.train_indices)
            assert indices == sorted(indices)
            for a, b in zip(indices, indices[1:]):
                if b != a + 1:
                    gapped_found = True
                    for i in range(a + 1, b):
                        assert any(zs <= i < ze for zs, ze in zones), "gap contains a bar that is not embargoed"
        assert gapped_found

    def test_multi_segment_windows_report_zero_in_sample_return(self):
        curve = _curve(200)
        result = purged_walk_forward(curve, train_bars=50, test_bars=10, purge_bars=2, embargo_bars=8)
        multi_segment_windows = 0
        for window in result.windows:
            idx = window.train_indices
            n_segments = 1 + sum(1 for a, b in zip(idx, idx[1:]) if b != a + 1)
            if n_segments > 1:
                multi_segment_windows += 1
                assert window.in_sample_return == 0.0
        assert multi_segment_windows > 0

    def test_result_records_purge_and_embargo(self):
        result = purged_walk_forward(_curve(), embargo_bars=7, **self.PARAMS)
        assert result.purge_bars == 2
        assert result.embargo_bars == 7
        assert result.to_dict()["purge_bars"] == 2
        assert result.to_dict()["embargo_bars"] == 7


class TestAnchoredEmbargo:
    """Anchored mode with embargo remains well-formed."""

    def test_anchored_windows_valid(self):
        curve = _curve(150)
        result = purged_walk_forward(
            curve,
            train_bars=40,
            test_bars=15,
            purge_bars=3,
            embargo_bars=4,
            anchored=True,
        )
        assert result.total_windows > 0
        for window in result.windows:
            assert window.train_start == 0
            assert window.test_start >= window.train_end + 3
            assert window.test_end <= len(curve)


class TestValidationAndEdgeCases:
    """Parameter validation and degenerate inputs."""

    def test_invalid_params_raise(self):
        curve = _curve()
        with pytest.raises(ValueError):
            purged_walk_forward(curve, train_bars=0, test_bars=10)
        with pytest.raises(ValueError):
            purged_walk_forward(curve, train_bars=30, test_bars=10, purge_bars=-1)
        with pytest.raises(ValueError):
            purged_walk_forward(curve, train_bars=30, test_bars=10, embargo_bars=-2)

    def test_insufficient_data_empty_result(self):
        result = purged_walk_forward([100.0] * 20, train_bars=50, test_bars=10)
        assert isinstance(result, WalkForwardResult)
        assert result.total_windows == 0

    def test_default_embargo_is_zero_backwards_compatible(self):
        curve = _curve()
        default = purged_walk_forward(curve, train_bars=30, test_bars=10, purge_bars=2)
        explicit = purged_walk_forward(curve, train_bars=30, test_bars=10, purge_bars=2, embargo_bars=0)
        assert default.to_dict() == explicit.to_dict()
