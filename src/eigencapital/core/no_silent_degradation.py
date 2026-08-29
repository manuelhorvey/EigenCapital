"""No Silent Degradation — platform-wide invariant.

Core principle:
    UNKNOWN, MISSING, STALE, UNAVAILABLE, CORRUPT must NEVER silently become
    0, NORMAL, SAFE, VERIFIED.

This module provides:
- A decorator that prevents silent degradation of values
- A validator that checks value transformations
- A contract that all platform components must follow

Usage:
    from eigencapital.core.no_silent_degradation import guard, DegradationViolation

    # This will raise DegradationViolation:
    guard(value=None, fallback=0)  # ❌ None → 0 is silent degradation

    # This is correct:
    if value is None:
        raise DegradationViolation("Value unavailable, cannot default to 0")
    result = value + 1  # ✅ Only operates on known values
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypeVar

T = TypeVar("T")


# ═══════════════════════════════════════════════════════════════════
# Degradation States — values that must not be silently replaced
# ═══════════════════════════════════════════════════════════════════


class DegradedState(str, Enum):
    """Values that represent unknown/unavailable/corrupt data.

    These must NEVER silently become valid-looking values.
    """

    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    CORRUPT = "CORRUPT"
    INCONSISTENT = "INCONSISTENT"


# ═══════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════


class DegradationViolation(Exception):
    """Raised when a value would silently degrade.

    This is an intentional, explicit failure. It means:
    - A None/missing value would be replaced with a valid-looking default
    - A stale value would be treated as current
    - An unknown state would be treated as known

    The correct response is to:
    - Show "No data" instead of 0
    - Show "UNKNOWN" instead of "SAFE"
    - Propagate the degraded state to the operator
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.context = context or {}


# ═══════════════════════════════════════════════════════════════════
# Guard Functions
# ═══════════════════════════════════════════════════════════════════


def guard_not_none(value: Any, name: str = "value") -> Any:
    """Ensure value is not None — prevents None → 0 fallback.

    Raises:
        DegradationViolation if value is None.
    """
    if value is None:
        raise DegradationViolation(
            f"{name} is None — refusing to silently default",
            context={"name": name, "value": None},
        )
    return value


def guard_not_zero(value: Any, name: str = "value") -> Any:
    """Ensure value is not zero — prevents 0 from being used as valid data.

    Raises:
        DegradationViolation if value is 0 or 0.0.
    """
    if value == 0:
        raise DegradationViolation(
            f"{name} is zero — refusing to treat as valid",
            context={"name": name, "value": value},
        )
    return value


def guard_not_degraded(value: Any, name: str = "value") -> Any:
    """Ensure value is not in a degraded state.

    Checks for:
    - None
    - Zero (for numeric types)
    - DegradedState enum values
    - Empty strings
    - Empty collections

    Raises:
        DegradationViolation if value appears degraded.
    """
    if value is None:
        raise DegradationViolation(
            f"{name} is None",
            context={"name": name, "value": None},
        )

    if isinstance(value, DegradedState):
        raise DegradationViolation(
            f"{name} is in degraded state: {value.value}",
            context={"name": name, "value": value.value},
        )

    if isinstance(value, str):
        for state in DegradedState:
            if value.upper() == state.value:
                raise DegradationViolation(
                    f"{name} is degraded string: '{value}'",
                    context={"name": name, "value": value},
                )
        if value.strip() == "":
            raise DegradationViolation(
                f"{name} is empty string",
                context={"name": name, "value": value},
            )

    if isinstance(value, (int, float)):
        if value == 0:
            raise DegradationViolation(
                f"{name} is zero",
                context={"name": name, "value": value},
            )

    if isinstance(value, (list, dict, set)) and len(value) == 0:
        raise DegradationViolation(
            f"{name} is empty {type(value).__name__}",
            context={"name": name, "value": value},
        )

    return value


def guard_numeric_positive(value: Any, name: str = "value") -> float:
    """Ensure value is a positive number.

    Raises:
        DegradationViolation if value is None, zero, or negative.
    """
    guard_not_none(value, name)
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise DegradationViolation(
            f"{name} is not numeric: {value}",
            context={"name": name, "value": str(value)},
        ) from exc

    if num <= 0:
        raise DegradationViolation(
            f"{name} is not positive: {num}",
            context={"name": name, "value": num},
        )
    return num


def guard_numeric_non_negative(value: Any, name: str = "value") -> float:
    """Ensure value is a non-negative number.

    Raises:
        DegradationViolation if value is None or negative.
    """
    guard_not_none(value, name)
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise DegradationViolation(
            f"{name} is not numeric: {value}",
            context={"name": name, "value": str(value)},
        ) from exc

    if num < 0:
        raise DegradationViolation(
            f"{name} is negative: {num}",
            context={"name": name, "value": num},
        )
    return num


# ═══════════════════════════════════════════════════════════════════
# Decorator
# ═══════════════════════════════════════════════════════════════════


def no_silent_degradation(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator that prevents a function from returning degraded values.

    The decorated function must either:
    - Return a valid value
    - Raise an explicit exception

    It must NOT:
    - Return None when data is unavailable
    - Return 0 when data is missing
    - Return "UNKNOWN" when a specific state is expected
    - Silently swallow exceptions

    Usage:
        @no_silent_degradation
        def get_equity(account_state):
            if account_state is None:
                raise DegradationViolation("Account state unavailable")
            return account_state["equity"]
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        result = func(*args, **kwargs)

        # Check for degraded return values
        if result is None:
            raise DegradationViolation(
                f"{func.__qualname__} returned None — function must return a valid value or raise explicitly",
                context={"function": func.__qualname__},
            )

        if isinstance(result, str):
            for state in DegradedState:
                if result.upper() == state.value:
                    raise DegradationViolation(
                        f"{func.__qualname__} returned degraded state '{result}'",
                        context={"function": func.__qualname__, "value": result},
                    )

        return result

    return wrapper


# ═══════════════════════════════════════════════════════════════════
# Value Transformation Validator
# ═══════════════════════════════════════════════════════════════════


@dataclass
class TransformationCheck:
    """Result of checking a value transformation."""

    input_value: Any
    output_value: Any
    transformation: str
    is_safe: bool
    violation: str | None = None


def validate_transformation(
    input_value: Any,
    output_value: Any,
    transformation_name: str = "unknown",
) -> TransformationCheck:
    """Validate that a transformation doesn't silently degrade.

    Checks:
    - None → 0 (most dangerous)
    - None → "" (empty string)
    - None → "NORMAL"
    - None → "SAFE"
    - None → "VERIFIED"
    - Degraded state → Valid-looking state

    Returns:
        TransformationCheck with is_safe=True if the transformation is safe.
    """
    # None → anything is suspicious
    if input_value is None and output_value is not None:
        if output_value == 0 or output_value == 0.0:
            return TransformationCheck(
                input_value=input_value,
                output_value=output_value,
                transformation=transformation_name,
                is_safe=False,
                violation="None → 0 is silent degradation",
            )
        if output_value == "":
            return TransformationCheck(
                input_value=input_value,
                output_value=output_value,
                transformation=transformation_name,
                is_safe=False,
                violation="None → empty string is silent degradation",
            )
        if isinstance(output_value, str):
            safe_replacements = {"no data", "n/a", "—", "unavailable", "missing"}
            if output_value.lower() in safe_replacements:
                return TransformationCheck(
                    input_value=input_value,
                    output_value=output_value,
                    transformation=transformation_name,
                    is_safe=True,
                )
            return TransformationCheck(
                input_value=input_value,
                output_value=output_value,
                transformation=transformation_name,
                is_safe=False,
                violation=f"None → '{output_value}' may be silent degradation",
            )

    # Degraded state → valid-looking state
    if isinstance(input_value, str):
        for state in DegradedState:
            if input_value.upper() == state.value:
                if output_value not in (None, state.value):
                    return TransformationCheck(
                        input_value=input_value,
                        output_value=output_value,
                        transformation=transformation_name,
                        is_safe=False,
                        violation=(f"Degraded state '{input_value}' → '{output_value}' is silent degradation"),
                    )

    return TransformationCheck(
        input_value=input_value,
        output_value=output_value,
        transformation=transformation_name,
        is_safe=True,
    )
