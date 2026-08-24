"""Feature-specific exceptions.

All feature errors are subclasses of FeatureError for consistent handling.
"""


class FeatureError(ValueError):
    """Base class for all feature-related errors."""

    pass


class FeatureAvailabilityError(FeatureError):
    """Raised when a feature's availability timestamp violates the information boundary.

    Critical invariant: availability_timestamp <= decision_timestamp.

    If this error is raised, the feature CANNOT be used for the decision
    because it would constitute look-ahead bias.
    """

    pass


class FeatureDuplicateError(FeatureError):
    """Raised when a duplicate feature_id is registered.

    Feature identity must be unique within the registry.
    """

    pass


class FeatureValidationError(FeatureError):
    """Raised when a feature fails validation (NaN, infinite, etc.)."""

    pass


class FeatureRegistryError(FeatureError):
    """Raised on registry-level errors (not found, version mismatch, etc.)."""

    pass
