"""Shared error handling utilities for the live trading subsystem.

P2-012: Consolidates the duplicated try/except/retry patterns found across
8+ modules (durable_audit, structured_alerts, risk_enforcement, daily_loss,
evidence_orchestrator, etc.) into a single reusable utility.

Usage:
    from eigencapital.live.error_handler import handle_transient, handle_fatal

    # Transient error: retry with backoff
    result = handle_transient(mt5.order_send, request, max_retries=2)

    # Fatal error: log + escalate
    handle_fatal(e, audit_fn=audit, escalate_fn=watchdog.set_state)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger("eigencapital.error_handler")


def handle_transient(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 2,
    retry_delay: float = 0.5,
    backoff_multiplier: float = 2.0,
    on_retry: Callable[[int, Exception], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Execute a function with retry logic for transient failures.

    Args:
        fn: Callable to execute
        *args: Positional arguments to pass to fn
        max_retries: Maximum retry attempts (0 = no retries)
        retry_delay: Initial delay between retries (doubles each retry)
        backoff_multiplier: Multiplier for exponential backoff
        on_retry: Optional callback(attempt_number, exception) on each retry
        **kwargs: Keyword arguments to pass to fn

    Returns:
        Result of fn(*args, **kwargs)

    Raises:
        The last exception if all retries fail
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = retry_delay * (backoff_multiplier**attempt)
                if on_retry:
                    on_retry(attempt + 1, e)
                logger.warning(
                    "Transient error on attempt %d/%d: %s — retrying in %.1fs",
                    attempt + 1,
                    max_retries + 1,
                    e,
                    delay,
                )
                time.sleep(delay)
    raise last_error  # type: ignore[misc]


def handle_fatal(
    error: Exception,
    *,
    context: str = "",
    audit_fn: Callable[[dict[str, Any]], None] | None = None,
    escalate_fn: Callable[[str], None] | None = None,
    escalate_state: str = "HALTED",
    reraise: bool = True,
) -> None:
    """Handle a fatal error: log, audit, optionally escalate.

    Args:
        error: The exception that occurred
        context: Human-readable context string (e.g., "order_submission")
        audit_fn: Optional audit function to record the error
        escalate_fn: Optional function to set a HALTED/DEGRADED state
        escalate_state: State to set via escalate_fn (default: "HALTED")
        reraise: Whether to re-raise the exception after handling
    """
    error_msg = f"Fatal error{' (' + context + ')' if context else ''}: {error}"
    logger.error(error_msg)

    if audit_fn:
        try:
            audit_fn(
                {
                    "event": "fatal_error",
                    "context": context,
                    "error": str(error),
                    "error_type": type(error).__name__,
                }
            )
        except Exception as e:
            logger.exception(f"Failed to record error to audit trail: {e}")

    if escalate_fn:
        try:
            escalate_fn(escalate_state)
        except Exception as e:
            logger.exception(f"Failed to escalate health state: {e}")

    if reraise:
        raise
