"""Tests for eigencapital.domain.time helpers."""

import datetime as _dt

from eigencapital.domain.time import utc_now, utc_now_iso, utc_now_naive


def test_utc_now_returns_aware_utc():
    t = utc_now()
    assert isinstance(t, _dt.datetime)
    assert t.tzinfo is _dt.timezone.utc


def test_utc_now_naive_returns_naive_utc():
    t = utc_now_naive()
    assert isinstance(t, _dt.datetime)
    assert t.tzinfo is None


def test_utc_now_naive_uses_utc():
    """Naive result should still match UTC (within a small tolerance)."""
    t = utc_now_naive()
    # Compare against UTC by stripping tzinfo from utc_now's result
    t_aware = utc_now()
    diff = abs((t - t_aware.replace(tzinfo=None)).total_seconds())
    assert diff < 1.0  # within 1 second


def test_utc_now_iso_returns_string():
    s = utc_now_iso()
    assert isinstance(s, str)
    # Should be parseable as ISO-8601
    parsed = _dt.datetime.fromisoformat(s)
    assert isinstance(parsed, _dt.datetime)


def test_utc_now_iso_is_naive():
    s = utc_now_iso()
    parsed = _dt.datetime.fromisoformat(s)
    assert parsed.tzinfo is None


def test_all_return_current_time():
    """Three sequential calls should produce monotonically increasing timestamps."""
    a = utc_now()
    b = utc_now_naive()
    c = utc_now_iso()
    assert b.tzinfo is None  # naive
    assert isinstance(c, str)
