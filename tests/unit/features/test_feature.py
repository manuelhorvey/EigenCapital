"""Adversarial tests for Feature model — the core domain contract.

Test invariants, edge cases, and failure modes.
"""

import pytest

from eigencapital.features.contracts import FeatureConfig, FeatureFamily, Normalization
from eigencapital.features.errors import (
    FeatureAvailabilityError,
    FeatureValidationError,
)
from eigencapital.features.feature import Feature

_counter = 0


def _next_id(prefix: str = "feat") -> str:
    global _counter
    _counter += 1
    return f"{prefix}_{_counter}"


@pytest.fixture(autouse=True)
def clear_feature_registry():
    """Clear feature registry before each test."""
    Feature._registry.clear()
    yield
    Feature._registry.clear()


def _make_feature(**overrides):
    """Create a test feature with unique defaults."""
    defaults = {
        "feature_id": _next_id(),
        "feature_version": "v1",
        "instrument_id": "ES",
        "timestamp_utc": "2025-01-01T10:00:00Z",
        "value": 0.05,
        "feature_family": FeatureFamily.RETURNS,
        "lookback": 20,
        "source_features": ["close"],
        "normalization": Normalization.NONE,
        "availability_timestamp": "2025-01-01T10:00:00Z",
    }
    defaults.update(overrides)
    return Feature(**defaults)


class TestFeatureInvariants:
    """Core invariants that must hold for all features."""

    def test_basic_creation(self):
        """Test basic feature creation."""
        f = _make_feature()
        assert f.value == 0.05

    def test_empty_feature_id_rejected(self):
        """Empty feature_id must be rejected."""
        with pytest.raises(ValueError, match="feature_id must be non-empty"):
            _make_feature(feature_id="")

    def test_empty_version_rejected(self):
        """Empty feature_version must be rejected."""
        with pytest.raises(ValueError, match="feature_version must be non-empty"):
            _make_feature(feature_version="")

    def test_empty_instrument_rejected(self):
        """Empty instrument_id must be rejected."""
        with pytest.raises(ValueError, match="instrument_id must be non-empty"):
            _make_feature(instrument_id="")

    def test_nan_value_rejected(self):
        """NaN value must be rejected."""
        with pytest.raises(FeatureValidationError):
            _make_feature(value=float("nan"))

    def test_infinite_value_rejected(self):
        """Infinite value must be rejected."""
        with pytest.raises(FeatureValidationError):
            _make_feature(value=float("inf"))

    def test_negative_infinite_rejected(self):
        """Negative infinite value must be rejected."""
        with pytest.raises(FeatureValidationError):
            _make_feature(value=float("-inf"))

    def test_invalid_family_rejected(self):
        """Invalid feature_family must be rejected."""
        with pytest.raises(ValueError, match="Invalid feature_family"):
            _make_feature(feature_family="nonexistent_family")

    def test_zero_lookback_rejected(self):
        """Zero lookback must be rejected."""
        with pytest.raises(ValueError, match="lookback must be >= 1"):
            _make_feature(lookback=0)

    def test_invalid_normalization_rejected(self):
        """Invalid normalization must be rejected."""
        with pytest.raises(ValueError, match="Invalid normalization"):
            _make_feature(normalization="invalid_method")


class TestFeatureAvailability:
    """The critical invariant: availability_timestamp <= timestamp_utc."""

    def test_same_timestamp_allowed(self):
        """availability_timestamp == timestamp_utc is allowed."""
        f = _make_feature(
            availability_timestamp="2025-01-01T10:00:00Z",
            timestamp_utc="2025-01-01T10:00:00Z",
        )
        assert f.availability_timestamp == f.timestamp_utc

    def test_earlier_availability_allowed(self):
        """availability_timestamp < timestamp_utc is allowed."""
        f = _make_feature(
            availability_timestamp="2025-01-01T09:59:00Z",
            timestamp_utc="2025-01-01T10:00:00Z",
        )
        assert f.availability_timestamp < f.timestamp_utc

    def test_later_availability_rejected(self):
        """availability_timestamp > timestamp_utc must raise FeatureAvailabilityError."""
        with pytest.raises(FeatureAvailabilityError):
            _make_feature(
                availability_timestamp="2025-01-01T10:01:00Z",
                timestamp_utc="2025-01-01T10:00:00Z",
            )

    def test_empty_availability_allowed(self):
        """Empty availability_timestamp is allowed (feature is marked unavailable)."""
        f = _make_feature(availability_timestamp="")
        assert not f.is_available

    def test_availability_property(self):
        """is_available property reflects availability_timestamp."""
        f1 = _make_feature(availability_timestamp="2025-01-01T10:00:00Z")
        assert f1.is_available

        f2 = _make_feature(availability_timestamp="")
        assert not f2.is_available


class TestFeatureDuplicatePrevention:
    """Feature IDs must be unique within the registry."""

    def test_duplicate_id_rejected(self):
        """Duplicate feature_id must be rejected."""
        _make_feature()
        # Get the ID that was just created
        last_id = list(Feature._registry.keys())[-1]
        with pytest.raises(ValueError, match="Duplicate feature_id"):
            _make_feature(feature_id=last_id)

    def test_different_ids_allowed(self):
        """Different feature_ids must be allowed."""
        f1 = _make_feature()
        f2 = _make_feature()
        assert f1.feature_id != f2.feature_id


class TestFeatureSerialization:
    """Deterministic serialization for provenance/hashing."""

    def test_to_dict_deterministic(self):
        """to_dict must be deterministic."""
        f = _make_feature()
        d1 = f.to_dict()
        d2 = f.to_dict()
        assert d1 == d2

    def test_from_dict_roundtrip(self):
        """from_dict must produce equivalent feature."""
        f = _make_feature()
        d = f.to_dict()
        # Clear registry so from_dict can re-register
        Feature._registry.clear()
        f2 = Feature.from_dict(d)
        assert f.feature_id == f2.feature_id
        assert f.value == f2.value
        assert f.feature_family == f2.feature_family

    def test_hash_consistency(self):
        """Hash must be consistent for equal features."""
        f = _make_feature()
        assert hash(f) == hash(f)

    def test_equality(self):
        """Equal features must be equal."""
        f1 = _make_feature()
        Feature._registry.clear()
        f2 = Feature.from_dict(f1.to_dict())
        assert f1 == f2

    def test_provenance_hash_deterministic(self):
        """compute_provenance_hash must be deterministic."""
        f = _make_feature()
        h1 = f.compute_provenance_hash()
        h2 = f.compute_provenance_hash()
        assert h1 == h2

    def test_config_hash_deterministic(self):
        """compute_config_hash must be deterministic."""
        f = _make_feature()
        h1 = f.compute_config_hash()
        h2 = f.compute_config_hash()
        assert h1 == h2

    def test_different_values_different_hash(self):
        """Different values must produce different provenance hashes."""
        f1 = _make_feature(value=0.05)
        f2 = _make_feature(value=0.10)
        assert f1.compute_provenance_hash() != f2.compute_provenance_hash()


class TestFeatureConfig:
    """Tests for FeatureConfig."""

    def test_valid_config(self):
        """Test valid feature configuration."""
        config = FeatureConfig(
            feature_family=FeatureFamily.MOMENTUM,
            normalization=Normalization.ZSCORE,
            lookback=20,
        )
        assert config.feature_family == "momentum"

    def test_invalid_family_rejected(self):
        """Invalid family must be rejected."""
        with pytest.raises(ValueError, match="Invalid feature_family"):
            FeatureConfig(feature_family="invalid")

    def test_invalid_normalization_rejected(self):
        """Invalid normalization must be rejected."""
        with pytest.raises(ValueError, match="Invalid normalization"):
            FeatureConfig(
                feature_family=FeatureFamily.RETURNS,
                normalization="invalid",
            )

    def test_zero_lookback_rejected(self):
        """Zero lookback must be rejected."""
        with pytest.raises(ValueError, match="lookback must be >= 1"):
            FeatureConfig(
                feature_family=FeatureFamily.RETURNS,
                lookback=0,
            )

    def test_serialization(self):
        """Config must be deterministically serializable."""
        config = FeatureConfig(
            feature_family=FeatureFamily.MOMENTUM,
            normalization=Normalization.ZSCORE,
            lookback=20,
            parameters={"window": 10},
        )
        d = config.to_dict()
        assert d["feature_family"] == "momentum"
        assert d["lookback"] == 20
