"""C-6 regression: the flatten retry loop must never drop close exceptions.

Safety context: catastrophic_protection places/repairs idempotent disaster
stops and flattens R4 positions. A retry loop that swallows broker errors can
silently leave a position unprotected, so:

  * transient error then success -> retried and eventually FLATTENED
  * permanent error -> the last error propagates to the caller
  * no exception may vanish without a traceback log AND a failed outcome
"""

from __future__ import annotations

import logging

import pytest

from eigencapital.live.catastrophic_protection import (
    FlattenOutcome,
    flatten_with_retry,
)


def test_transient_close_error_then_success_is_retried(caplog: pytest.LogCaptureFixture) -> None:
    open_tickets = {1}
    calls: list[int] = []

    def list_positions() -> list[dict[str, int]]:
        return [{"ticket": t} for t in sorted(open_tickets)]

    def close(ticket: int) -> bool:
        calls.append(ticket)
        if len(calls) == 1:
            raise ConnectionError("bridge briefly down")
        open_tickets.discard(ticket)
        return True

    with caplog.at_level(logging.ERROR):
        outcome, n = flatten_with_retry(list_positions, close, max_passes=5)

    assert outcome is FlattenOutcome.FLATTENED
    assert n == 1
    assert calls == [1, 1]  # retried after the transient failure
    assert "bridge briefly down" in caplog.text  # transient error recorded, not dropped
    assert any(record.exc_info for record in caplog.records)  # traceback preserved


def test_permanent_close_failure_propagates_the_error() -> None:
    def list_positions() -> list[dict[str, int]]:
        return [{"ticket": 7}]

    def close(ticket: int) -> bool:
        raise ConnectionError("broker unreachable")

    with pytest.raises(RuntimeError) as exc_info:
        flatten_with_retry(list_positions, close, max_passes=3)

    assert "broker unreachable" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ConnectionError)  # last error preserved
    assert str(exc_info.value.__cause__) == "broker unreachable"


def test_permanent_failure_is_never_reported_as_success_or_silently_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def list_positions() -> list[dict[str, int]]:
        return [{"ticket": 4}]

    def close(ticket: int) -> bool:
        raise TimeoutError("close timed out")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="close timed out"):
        flatten_with_retry(list_positions, close, max_passes=2)

    # The failure surfaced as an exception AND as an error log with a traceback.
    assert "close timed out" in caplog.text
    assert any(record.exc_info for record in caplog.records)


def test_partial_progress_still_surfaces_the_error(caplog: pytest.LogCaptureFixture) -> None:
    open_tickets = {1, 2}

    def list_positions() -> list[dict[str, int]]:
        return [{"ticket": t} for t in sorted(open_tickets)]

    def close(ticket: int) -> bool:
        if ticket == 2:
            raise TimeoutError("close timed out")
        open_tickets.discard(ticket)
        return True

    with caplog.at_level(logging.ERROR):
        outcome, n = flatten_with_retry(list_positions, close, max_passes=3)

    assert outcome is FlattenOutcome.PARTIAL  # partial progress is never full success
    assert n == 1
    assert open_tickets == {2}
    assert "close timed out" in caplog.text  # the dropped error is still reported


def test_refusal_without_exception_still_returns_failed_halt() -> None:
    def list_positions() -> list[dict[str, int]]:
        return [{"ticket": 3}]

    def close(ticket: int) -> bool:
        return False

    outcome, n = flatten_with_retry(list_positions, close, max_passes=3)
    assert outcome is FlattenOutcome.FAILED_HALT
    assert n == 0


def test_backoff_between_retries_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr("time.sleep", delays.append)

    def list_positions() -> list[dict[str, int]]:
        return [{"ticket": 1}]

    def close(ticket: int) -> bool:
        raise OSError("still down")

    with pytest.raises(RuntimeError):
        flatten_with_retry(list_positions, close, max_passes=5)

    assert 0 < len(delays) <= 4  # backoff only between passes, never after the last
    assert all(0 < delay <= 1.0 for delay in delays)  # bounded, no unbounded sleep
