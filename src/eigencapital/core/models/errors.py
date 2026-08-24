"""Domain-specific errors for invariant violations.

All errors raised by domain model validation should be instances of
these error types (or subclasses). This ensures consistent error handling
across the system and makes it easy to catch specific failure modes.

Usage:
    from eigencapital.core.models.errors import (
        InvariantViolation,
        InvalidInput,
        DuplicateResource,
    )

    try:
        position = Position(...)
    except InvariantViolation as e:
        # Handle invariant violation
    except InvalidInput as e:
        # Handle bad input data
    except DuplicateResource as e:
        # Handle duplicate ID
"""


class EigenCapitalError(ValueError):
    """Base exception for all EigenCapital domain errors.

    All domain-specific errors inherit from this, allowing callers to catch
    all domain errors with a single except clause, or specific ones for
    particular failure modes.
    """

    def __init__(self, message: str, model: str = "", field: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.model = model  # e.g. "Position", "Order", "Fill"
        self.field = field  # e.g. "quantity", "timestamp_utc"
        self.timestamp = __import__("datetime").datetime.utcnow().isoformat()

    def __str__(self) -> str:
        if self.model and self.field:
            return f"[{self.model}.{self.field}] {self.message}"
        return self.message


class InvariantViolation(EigenCapitalError):
    """Raised when a domain invariant is violated.

    Invariants are strict constraints that must always hold.
    Violation indicates a bug or data corruption, not merely bad input.

    Examples:
        - quantity == 0 but average_entry_price != None
        - timestamp_utc != bar_end_utc
        - sum(fills) > order.quantity
        - decision == REJECTED but approved_quantity != 0
    """

    def __init__(self, message: str, model: str = "", field: str = "") -> None:
        super().__init__(message, model, field)


class InvalidInput(EigenCapitalError):
    """Raised when input data is invalid or malformed.

    This is for data that fails basic validation but isn't necessarily
    an invariant violation. It's for "garbage in" scenarios.

    Examples:
        - NaN or infinite price
        - Negative quantity where positive expected
        - Unknown enum value
        - Missing required field
    """

    def __init__(self, message: str, model: str = "", field: str = "") -> None:
        super().__init__(message, model, field)


class DuplicateResource(EigenCapitalError):
    """Raised when trying to create a resource with a non-unique identifier.

    Examples:
        - Duplicate instrument_id
        - Duplicate order_id
        - Duplicate experiment_id
        - Duplicate snapshot_id
    """

    def __init__(self, message: str, model: str = "", field: str = "") -> None:
        super().__init__(message, model, field)


class ConfigurationError(EigenCapitalError):
    """Raised when configuration is inconsistent or missing.

    Examples:
        - Missing config_hash on StrategyIntent
        - Incompatible code/data/version combination
        - Risk policy version mismatch
    """

    def __init__(self, message: str, model: str = "", field: str = "") -> None:
        super().__init__(message, model, field)


class ProvenanceError(EigenCapitalError):
    """Raised when provenance/hashing is inconsistent or corrupted.

    Examples:
        - Deterministic serialization mismatch
        - Provenance hash collision
        - Version chain broken
    """

    def __init__(self, message: str, model: str = "", field: str = "") -> None:
        super().__init__(message, model, field)


# Convenience functions for common invariant violation patterns


def check_invariant(
    condition: bool, message: str, model: str = "", field: str = ""
) -> None:
    """Raise InvariantViolation if condition is False.

    Quick inline invariant checking pattern:
        check_invariant(quantity > 0, "quantity must be positive", "Position", "quantity")
    """
    if not condition:
        raise InvariantViolation(message, model, field)


def check_not_none(value: any, message: str, model: str = "", field: str = "") -> None:
    """Raise InvalidInput if value is None."""
    if value is None:
        raise InvalidInput(message, model, field)


def check_positive(value: float, model: str = "", field: str = "") -> None:
    """Raise InvariantViolation if value is not positive (> 0)."""
    if not (isinstance(value, (int, float)) and value > 0):
        raise InvariantViolation(
            f"Value must be positive (> 0), got {value}", model, field
        )


def check_non_negative(value: float, model: str = "", field: str = "") -> None:
    """Raise InvariantViolation if value is negative."""
    if isinstance(value, (int, float)) and value < 0:
        raise InvariantViolation(
            f"Value must be non-negative, got {value}", model, field
        )


def check_finite(value: float, model: str = "", field: str = "") -> None:
    """Raise InvariantViolation if value is NaN or infinite."""
    import math

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise InvariantViolation(
            f"Value must be finite (no NaN/infinity), got {value}", model, field
        )
