"""Centralized UTC time helpers.

This module is the single source of truth for "what time is it?" in UTC.  All
engine code should import from here rather than calling ``datetime.now(timezone.utc)``
directly.

Rationale (see AGENTS.md Phase 7):

Consistency.  Many call sites in the codebase previously computed
``datetime.now(timezone.utc).replace(tzinfo=None)`` or
``datetime.now(timezone.utc).isoformat()`` independently.  The repeated pattern
made it easy to drift -- a future change to formatting (e.g. adding fractional
seconds, switching from iso8601 to RFC3339) would have required visiting dozens
of files.  Funnelling these through helpers below means one change covers all
call sites.

Mixed timezone-naive vs timezone-aware code.  The codebase contains both
``datetime.now(timezone.utc)`` (aware) and
``datetime.now(timezone.utc).replace(tzinfo=None)`` (naive) patterns.  The
naive-iso variant is overwhelmingly more common (>30 sites), while a smaller
set of call sites need a timezone-aware datetime (e.g. for ISO serialization
that includes the ``+00:00`` suffix).  Both patterns are valid; the helpers
here make the choice explicit at the import site instead of relying on
``replace(tzinfo=None)`` sprinkled throughout.

Function summary:

- ``utc_now()``: timezone-aware UTC ``datetime`` (preferred for inter-module
  logic; matches ``datetime.now(timezone.utc)`` byte-for-byte).
- ``utc_now_naive()``: timezone-naive UTC ``datetime`` -- the dominant pattern
  in the codebase, used for SQLite ``TEXT`` columns, JSON ``timestamp`` fields,
  and any other surface where a naive datetime is the established convention.
- ``utc_now_iso()``: ``str`` -- ISO-8601 of ``utc_now_naive()`` with no
  microseconds overflow.  This corresponds to the previous inlined pattern
  ``datetime.now(timezone.utc).replace(tzinfo=None).isoformat()``.
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = ["utc_now", "utc_now_naive", "utc_now_iso"]


def utc_now() -> datetime:
    """Return current UTC ``datetime`` with ``tzinfo=timezone.utc``.

    Equivalent to ``datetime.now(timezone.utc)``.  Use for inter-module logic
    where timezone-awareness matters (e.g. comparing against timestamps from
    external sources that include tzinfo).
    """
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """Return current UTC ``datetime`` with ``tzinfo=None``.

    Equivalent to ``datetime.now(timezone.utc).replace(tzinfo=None)``.
    Preferred for SQLite ``TEXT`` columns and JSON ``timestamp`` fields where
    the codebase has historically used the naive form.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_iso() -> str:
    """Return current UTC ``datetime`` as ISO-8601 string (naive form).

    Equivalent to ``datetime.now(timezone.utc).replace(tzinfo=None).isoformat()``.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
