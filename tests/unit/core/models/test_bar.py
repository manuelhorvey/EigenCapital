"""Unit tests for EigenCapital domain models — Bar.

Tests invariants, UTC-end invariant, price hierarchy, serialization, and deterministic behavior.
"""

import sys
import json
from datetime import datetime, timezone, timedelta

from eigencapital.core.models.bar import Bar, BarInterval
from eigencapital.core.models.errors import InvariantViolation, InvalidInput


def clear_registry():
    """Clear the class-level registry."""
    if hasattr(Bar, '_registry'):
        Bar._registry.clear()


def make_utc_iso(year, month, day, hour, minute, second=0):
    """Helper to create ISO-8601 UTC string."""
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def test_bar_creation():
    """Test basic Bar creation and invariants."""
    clear_registry()
    bar = Bar(
        instrument_id="ES",
        timestamp_utc=make_utc_iso(2024, 3, 15, 9, 35),
        bar_start_utc=make_utc_iso(2024, 3, 15, 9, 30),
        bar_end_utc=make_utc_iso(2024, 3, 15, 9, 35),
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )
    assert bar.instrument_id == "ES"
    assert bar.timestamp_utc == "2024-03-15T09:35:00Z"
    assert bar.bar_start_utc == "2024-03-15T09:30:00Z"
    assert bar.bar_end_utc == "2024-03-15T09:35:00Z"
    assert bar.open == 4500.0
    assert bar.high == 4510.0
    assert bar.low == 4495.0
    assert bar.close == 4505.0
    assert bar.volume == 1000
    assert bar.bar_interval == "1m"  # default
    print("  PASS: test_bar_creation")


def test_bar_utc_end_invariant():
    """Test that timestamp_utc == bar_end_utc is enforced."""
    clear_registry()
    # Valid case: invariant holds
    bar = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )
    # Should not raise
    print("  PASS: Valid bar invariant holds")

    # Invalid case: timestamp_utc != bar_end_utc
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:34:00Z",  # wrong! should equal timestamp_utc
            open=4500.0,
            high=4510.0,
            low=4495.0,
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for UTC invariant violation"
    except ValueError as e:
        assert "timestamp_utc" in str(e) and "bar_end_utc" in str(e)
    print("  PASS: test_bar_utc_end_invariant")


def test_bar_chronological_order():
    """Test that bar_start_utc < timestamp_utc (bar start before end)."""
    clear_registry()
    # Valid
    bar = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )
    print("  PASS: Valid bar chronological order")

    # Invalid: bar_start_utc >= timestamp_utc
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:35:00Z",  # equal! invalid
            bar_end_utc="2024-03-15T09:35:00Z",
            open=4500.0,
            high=4510.0,
            low=4495.0,
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for bar_start >= timestamp"
    except ValueError as e:
        assert "bar_start_utc" in str(e) and "timestamp_utc" in str(e)
    print("  PASS: test_bar_chronological_order")


def test_bar_price_hierarchy():
    """Test high >= max(open, close) and low <= min(open, close)."""
    clear_registry()
    # Valid bar
    bar = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )
    print("  PASS: Valid price hierarchy")

    # Invalid: high < max(open, close)
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=4500.0,
            high=4499.0,  # too low! max(open,close)=4505
            low=4495.0,
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for high < max(open,close)"
    except ValueError as e:
        assert "high" in str(e) and "max" in str(e)
    print("  PASS: test_bar_price_hierarchy high check")

    # Invalid: low > min(open, close)
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=4500.0,
            high=4510.0,
            low=4506.0,  # too high! min(open,close)=4500
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for low > min(open,close)"
    except ValueError as e:
        assert "low" in str(e) and "min" in str(e)
    print("  PASS: test_bar_price_hierarchy low check")


def test_bar_price_must_be_positive():
    """Test that all prices must be > 0."""
    clear_registry()
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=0,  # invalid: must be > 0
            high=4510.0,
            low=4495.0,
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for open=0"
    except ValueError as e:
        assert "open must be > 0" in str(e)
    print("  PASS: test_bar_price_must_be_positive open")

    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=4500.0,
            high=4510.0,
            low=0,  # invalid
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for low=0"
    except ValueError as e:
        assert "low must be > 0" in str(e)
    print("  PASS: test_bar_price_must_be_positive low")


def test_bar_volume_nonnegative():
    """Test that volume >= 0."""
    clear_registry()
    # Valid
    bar = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=0,  # valid: zero volume
    )
    print("  PASS: volume=0 is valid")

    # Invalid: negative volume
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=4500.0,
            high=4510.0,
            low=4495.0,
            close=4505.0,
            volume=-1,  # invalid
        )
        assert False, "Should have raised ValueError for negative volume"
    except ValueError as e:
        assert "volume must be >= 0" in str(e)
    print("  PASS: test_bar_volume_nonnegative negative")


def test_bar_nan_inf_prices():
    """Test that NaN/infinite prices are rejected."""
    import math
    
    clear_registry()
    
    # NaN open
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=float("nan"),
            high=4510.0,
            low=4495.0,
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for NaN open"
    except ValueError as e:
        assert "finite" in str(e).lower()
    print("  PASS: NaN open rejected")

    # Inf high
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=4500.0,
            high=float("inf"),
            low=4495.0,
            close=4505.0,
            volume=1000,
        )
        assert False, "Should have raised ValueError for inf high"
    except ValueError as e:
        assert "finite" in str(e).lower()
    print("  PASS: inf high rejected")


def test_bar_vwap_optional():
    """Test that vwap is Optional (can be None)."""
    clear_registry()
    # Valid: vwap=None
    bar = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
        vwap=None,
    )
    assert bar.vwap is None
    print("  PASS: vwap=None is valid")
    
    # Valid: vwap set - need to clear registry first since first bar registered ES+timestamp
    clear_registry()
    bar2 = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
        vwap=4505.0,
    )
    assert bar2.vwap == 4505.0
    print("  PASS: vwap=4505.0 is valid")


def test_bar_to_from_dict():
    """Test deterministic serialization round-trip for Bar."""
    clear_registry()
    original = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )

    d = original.to_dict()
    assert "instrument_id" in d
    assert "timestamp_utc" in d
    assert "open" in d

    # Round-trip
    clear_registry()
    roundtrip = Bar.from_dict(d)
    assert roundtrip.instrument_id == original.instrument_id
    assert roundtrip.timestamp_utc == original.timestamp_utc
    assert roundtrip.open == original.open
    assert roundtrip.high == original.high
    assert roundtrip.low == original.low
    assert roundtrip.close == original.close
    assert roundtrip.volume == original.volume
    print("  PASS: test_bar_to_from_dict")


def test_bar_dict_consistency():
    """Test that to_dict produces consistent output."""
    clear_registry()
    original = Bar(
        instrument_id="NQ",
        timestamp_utc="2024-03-15T14:50:00Z",
        bar_start_utc="2024-03-15T14:45:00Z",
        bar_end_utc="2024-03-15T14:50:00Z",
        open=18000.0,
        high=18050.0,
        low=17980.0,
        close=18025.0,
        volume=500,
    )

    d1 = original.to_dict()
    d2 = original.to_dict()
    assert d1 == d2  # deterministic
    assert list(d1.keys()) == list(d2.keys())
    print("  PASS: test_bar_dict_consistency")


def test_bar_config_hash():
    """Test that config_hash is deterministic."""
    clear_registry()
    original = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000,
    )

    h1 = original.config_hash()
    h2 = original.config_hash()
    assert h1 == h2
    assert len(h1) == 64
    assert len(h2) == 64
    print("  PASS: test_bar_config_hash")


def test_bar_interval_enum():
    """Test BarInterval enum validity."""
    clear_registry()
    # Valid intervals
    valid = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]
    for v in valid:
        bi = BarInterval(value=v)
        assert bi.value == v
    
    # Invalid interval
    try:
        BarInterval(value="10m")
        assert False, "Should reject invalid interval"
    except ValueError:
        pass  # Expected
    
    print("  PASS: test_bar_interval_enum")


def test_bar_side_property():
    """Test Bar.side property (up/down from close vs open)."""
    clear_registry()
    # close > open => "up"
    bar_up = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,  # > open
        volume=1000,
    )
    assert bar_up.side == "up"
    
    # close < open => "down"
    clear_registry()
    bar_down = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4495.0,  # < open (same as low)
        volume=1000,
    )
    assert bar_down.side == "down"
    
    # close == open => "down" (else branch)
    clear_registry()
    bar_flat = Bar(
        instrument_id="ES",
        timestamp_utc="2024-03-15T09:35:00Z",
        bar_start_utc="2024-03-15T09:30:00Z",
        bar_end_utc="2024-03-15T09:35:00Z",
        open=4500.0,
        high=4500.0,
        low=4500.0,
        close=4500.0,  # == open
        volume=1000,
    )
    assert bar_flat.side == "down"  # else branch
    print("  PASS: test_bar_side_property")


def test_bar_negative_quantity():
    """Test that negative volume is rejected (already tested in volume test, but double-check)."""
    clear_registry()
    try:
        bad_bar = Bar(
            instrument_id="ES",
            timestamp_utc="2024-03-15T09:35:00Z",
            bar_start_utc="2024-03-15T09:30:00Z",
            bar_end_utc="2024-03-15T09:35:00Z",
            open=4500.0,
            high=4510.0,
            low=4495.0,
            close=4505.0,
            volume=-1,
        )
        assert False, "Negative volume should be rejected"
    except ValueError:
        pass  # Expected
    print("  PASS: test_bar_negative_quantity")


if __name__ == ".__main__":
    # Run all tests
    test_bar_creation()
    test_bar_utc_end_invariant()
    test_bar_chronological_order()
    test_bar_price_hierarchy()
    test_bar_price_must_be_positive()
    test_bar_volume_nonnegative()
    test_bar_nan_inf_prices()
    test_bar_vwap_optional()
    test_bar_to_from_dict()
    test_bar_dict_consistency()
    test_bar_config_hash()
    test_bar_interval_enum()
    test_bar_side_property()
    test_bar_negative_quantity()
    print("\nAll Bar tests passed!")
