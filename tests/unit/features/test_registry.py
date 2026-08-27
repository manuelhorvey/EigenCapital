"""Tests for FeatureRegistry — duplicate prevention and version tracking."""

import pytest

from eigencapital.features.contracts import FeatureConfig, FeatureFamily
from eigencapital.features.errors import FeatureDuplicateError, FeatureRegistryError
from eigencapital.features.registry import FeatureRegistry


def _make_config(family=FeatureFamily.RETURNS, lookback=20):
    """Create a test feature config."""
    return FeatureConfig(feature_family=family, lookback=lookback)


class TestFeatureRegistry:
    """Tests for feature registration and retrieval."""

    def test_register_and_get(self):
        """Test basic register and get."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("return_20", "v1", config)
        result = registry.get("return_20")
        assert result.feature_id == "return_20"
        assert result.version == "v1"

    def test_duplicate_version_rejected(self):
        """Duplicate feature_id + version must be rejected."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("return_20", "v1", config)
        with pytest.raises(FeatureDuplicateError):
            registry.register("return_20", "v1", config)

    def test_different_versions_allowed(self):
        """Different versions of same feature must be allowed."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("return_20", "v1", config)
        registry.register("return_20", "v2", config)
        assert registry.has_version("return_20", "v1")
        assert registry.has_version("return_20", "v2")

    def test_get_latest_version(self):
        """Getting without version should return latest."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("return_20", "v1", config)
        registry.register("return_20", "v2", config)
        result = registry.get("return_20")
        assert result.version == "v2"

    def test_get_specific_version(self):
        """Getting with specific version should return that version."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("return_20", "v1", config)
        registry.register("return_20", "v2", config)
        result = registry.get("return_20", version="v1")
        assert result.version == "v1"

    def test_get_nonexistent_raises(self):
        """Getting nonexistent feature must raise."""
        registry = FeatureRegistry()
        with pytest.raises(FeatureRegistryError):
            registry.get("nonexistent")

    def test_list_features(self):
        """list_features must return sorted feature IDs."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("momentum_20", "v1", config)
        registry.register("return_20", "v1", config)
        registry.register("volatility_10", "v1", config)
        assert registry.list_features() == ["momentum_20", "return_20", "volatility_10"]

    def test_list_versions(self):
        """list_versions must return sorted versions."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("return_20", "v2", config)
        registry.register("return_20", "v1", config)
        registry.register("return_20", "v3", config)
        assert registry.list_versions("return_20") == ["v1", "v2", "v3"]

    def test_len(self):
        """len must return total definitions across all features."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("f1", "v1", config)
        registry.register("f1", "v2", config)
        registry.register("f2", "v1", config)
        assert len(registry) == 3

    def test_contains(self):
        """in operator must work for feature IDs."""
        registry = FeatureRegistry()
        config = _make_config()
        registry.register("return_20", "v1", config)
        assert "return_20" in registry
        assert "nonexistent" not in registry

    def test_serialization(self):
        """FeatureDefinition must be serializable."""
        registry = FeatureRegistry()
        config = _make_config()
        defn = registry.register("return_20", "v1", config, description="20-period return")
        d = defn.to_dict()
        assert d["feature_id"] == "return_20"
        assert d["version"] == "v1"
        assert d["description"] == "20-period return"
