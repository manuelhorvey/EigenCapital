"""Tests for exposure limit checks."""

from paper_trading.services.engine_state_service import EngineStateService
from paper_trading.pek.state.portfolio_state_builder import CLUSTER_GROUPS


class TestExposureLimits:
    def test_cluster_groups_defined(self):
        assert "CHF" in CLUSTER_GROUPS
        assert len(CLUSTER_GROUPS["CHF"]) >= 4

    def test_critical_clusters_not_empty(self):
        for name, assets in CLUSTER_GROUPS.items():
            assert len(assets) >= 1, f"Cluster {name} is empty"
