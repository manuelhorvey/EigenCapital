"""Tests for the publish-marker contract on per-asset state dicts.

ARCHITECTURE.md Key Contract §4 declares that the dashboard slice
selectors and React Query's structural-sharing depend on per-asset dicts
being immutable across the publish window. `engine_state_service.py`
sets a marker key on each dict at publish time.

This file exercises the marker via a small port-style test (we use a
fixture rather than a full engine mock because the marker utility is
isolated and the production path is exercised end-to-end in the
existing test_engine_state_service.py suite).
"""
import pytest

from paper_trading.services.engine_state_service import (
    _ASSET_DICT_PUBLISHED_MARKER,
    _publish_asset_dict,
)


def _fixture_dict() -> dict:
    return {
        "side": "long",
        "metrics": {"pnl": 100, "sl_mult": 1.0},
        "feature_stability": {"jaccard": 0.5},
        "layers": [{"entry": 1.10}],  # list — not recursively marked
    }


class TestPublishMarker:
    def test_marker_key_set_on_top_level(self):
        d = _fixture_dict()
        _publish_asset_dict(d)
        assert _ASSET_DICT_PUBLISHED_MARKER in d
        assert d[_ASSET_DICT_PUBLISHED_MARKER] is None

    def test_marker_does_not_recurse_into_nested_dicts(self):
        """Nested dicts are intentionally NOT marked to avoid breaking
        z.record schemas on the frontend (e.g. regime_geometry, batches)."""
        d = _fixture_dict()
        _publish_asset_dict(d)
        assert _ASSET_DICT_PUBLISHED_MARKER not in d["metrics"]
        assert _ASSET_DICT_PUBLISHED_MARKER not in d["feature_stability"]

    def test_lists_are_not_recursed(self):
        d = _fixture_dict()
        _publish_asset_dict(d)
        for layer in d["layers"]:
            assert _ASSET_DICT_PUBLISHED_MARKER not in layer

    def test_non_dict_passthrough(self):
        # The function early-returns on non-dict values; this protects
        # helper call sites from accidental attribute errors.
        _publish_asset_dict(None)
        _publish_asset_dict(42)
        _publish_asset_dict("string")

    def test_idempotent(self):
        d = _fixture_dict()
        _publish_asset_dict(d)
        before = dict(d)
        _publish_asset_dict(d)
        # No additional side effects other than setdefault which is
        # idempotent on existing keys.
        assert d == before
